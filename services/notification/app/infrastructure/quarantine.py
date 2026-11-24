"""Durable quarantine persistence and confirmed DLQ outbox publisher for Notification."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Any, Optional

import pika
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import NotificationDlqOutbox, NotificationQuarantineMessage
from app.infrastructure.cursor import format_utc_iso

logger = logging.getLogger("notification.quarantine")

EXCHANGE_NAME = "agrodiagnostico.events"


def record_quarantine_and_dlq(
    db: Session,
    routing_key: str,
    raw_payload: bytes,
    reason_code: str,
    event_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> NotificationDlqOutbox:
    """Persist safe quarantine metadata and a durable DLQ outbox descriptor in the active transaction."""
    now = datetime.now(timezone.utc)
    payload_sha256 = hashlib.sha256(raw_payload).hexdigest()
    safe_reason = (reason_code or "INVALID_MESSAGE")[:80]
    dlq_routing_key = routing_key if routing_key.endswith(".dlq") else f"{routing_key}.dlq"

    quarantine = NotificationQuarantineMessage(
        event_id=str(event_id)[:64] if event_id else None,
        routing_key=routing_key[:128],
        reason_code=safe_reason,
        payload_sha256=payload_sha256,
        correlation_id=str(correlation_id)[:64] if correlation_id else None,
        received_at=now,
    )
    db.add(quarantine)
    db.flush()

    descriptor = {
        "quarantine_id": str(quarantine.id),
        "consumer": "notification-consumer",
        "event_id": quarantine.event_id,
        "routing_key": quarantine.routing_key,
        "reason_code": quarantine.reason_code,
        "payload_sha256": payload_sha256,
        "correlation_id": quarantine.correlation_id,
        "received_at": format_utc_iso(now),
    }

    outbox = NotificationDlqOutbox(
        quarantine_id=quarantine.id,
        routing_key=dlq_routing_key[:128],
        descriptor=descriptor,
        created_at=now,
        available_at=now,
    )
    db.add(outbox)
    return outbox


def publish_pending_dlq_outbox(
    db: Session,
    channel: Any,
    batch_size: int = 20,
) -> int:
    """Publish pending DLQ descriptors with mandatory delivery and publisher confirms."""
    if channel is None:
        return 0

    now = datetime.now(timezone.utc)
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    compare_now = now.replace(tzinfo=None) if dialect_name == "sqlite" else now

    stmt = (
        select(NotificationDlqOutbox)
        .where(
            NotificationDlqOutbox.sent_at.is_(None),
            NotificationDlqOutbox.available_at <= compare_now,
        )
        .order_by(NotificationDlqOutbox.created_at.asc())
        .limit(batch_size)
    )
    if dialect_name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    rows = db.execute(stmt).scalars().all()
    published = 0

    for row in rows:
        body = json.dumps(row.descriptor, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            channel.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key=row.routing_key,
                body=body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                ),
                mandatory=True,
            )
            row.sent_at = datetime.now(timezone.utc)
            row.attempt_count += 1
            published += 1
        except Exception as exc:
            logger.warning("Failed to publish DLQ descriptor id=%s: %s", row.id, type(exc).__name__)
            row.attempt_count += 1
            backoff_sec = min(60, 5 * row.attempt_count)
            row.available_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_sec)

    if rows:
        db.commit()
    return published
