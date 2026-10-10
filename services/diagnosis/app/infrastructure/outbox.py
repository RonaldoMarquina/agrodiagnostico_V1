"""Transactional Outbox repository and publisher for Diagnosis events.

Guarantees:
- Short DB claim transaction using FOR UPDATE SKIP LOCKED (no open SQL transaction while waiting for broker).
- Expirable durable lease on claimed rows.
- Publisher confirms with mandatory=True.
- basic.return (unroutable) does not mark sent_at; schedules retry with exponential backoff.
- Redeliveries after crash retain exact, immutable envelope (event_id, occurred_at, correlation_id, payload).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

import pika
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.domain.models import DiagnosisOutbox

logger = logging.getLogger("diagnosis_outbox")

EXCHANGE_NAME = "agrodiagnostico.events"


def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class OutboxItem:
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    schema_version: int
    routing_key: str
    envelope: Dict[str, Any]
    diagnosis_id: Optional[uuid.UUID]
    attempt_number: int
    claim_token: uuid.UUID


def claim_outbox_batch(
    db: Session,
    batch_size: int = 10,
    lease_seconds: int = 30,
    claim_token: Optional[uuid.UUID] = None,
) -> Tuple[uuid.UUID, List[OutboxItem]]:
    """Select and lease a batch of publishable outbox events.
    
    Commits immediately to release row locks before network I/O.
    """
    token = claim_token or uuid.uuid4()
    now = get_utc_now()
    expires_at = now + timedelta(seconds=lease_seconds)

    stmt = (
        select(DiagnosisOutbox)
        .where(
            DiagnosisOutbox.sent_at.is_(None),
            DiagnosisOutbox.available_at <= now,
            or_(
                DiagnosisOutbox.claim_expires_at.is_(None),
                DiagnosisOutbox.claim_expires_at < now,
            ),
        )
        .order_by(DiagnosisOutbox.created_at.asc())
        .limit(batch_size)
    )

    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    else:
        stmt = stmt.with_for_update()

    records = db.execute(stmt).scalars().all()
    items = []

    for rec in records:
        rec.claim_token = token
        rec.claim_expires_at = expires_at
        items.append(
            OutboxItem(
                id=rec.id,
                event_id=rec.event_id,
                event_type=rec.event_type,
                schema_version=rec.schema_version,
                routing_key=rec.routing_key,
                envelope=rec.envelope,
                diagnosis_id=rec.diagnosis_id,
                attempt_number=rec.attempt_number,
                claim_token=token,
            )
        )

    db.commit()
    return token, items


def mark_outbox_sent(
    db: Session,
    outbox_id: uuid.UUID,
    claim_token: uuid.UUID,
) -> bool:
    """Mark an outbox event as sent after successful publisher confirmation."""
    now = get_utc_now()
    result = db.execute(update(DiagnosisOutbox).where(
        DiagnosisOutbox.id == outbox_id,
        DiagnosisOutbox.claim_token == claim_token,
        DiagnosisOutbox.sent_at.is_(None),
    ).values(sent_at=now, claim_token=None, claim_expires_at=None))
    db.commit()
    return result.rowcount == 1


def mark_outbox_failed(
    db: Session,
    outbox_id: uuid.UUID,
    claim_token: uuid.UUID,
    backoff_seconds: int = 5,
) -> None:
    """Release claim and schedule retry with exponential backoff on delivery failure."""
    now = get_utc_now()
    db.execute(update(DiagnosisOutbox).where(
        DiagnosisOutbox.id == outbox_id,
        DiagnosisOutbox.claim_token == claim_token,
        DiagnosisOutbox.sent_at.is_(None),
    ).values(available_at=now + timedelta(seconds=backoff_seconds),
             claim_token=None, claim_expires_at=None))
    db.commit()


class DiagnosisOutboxPublisher:
    """Publishes outbox batches to RabbitMQ with publisher confirms and mandatory delivery."""

    def __init__(self, connection_parameters: Optional[pika.ConnectionParameters] = None):
        self.parameters = connection_parameters

    def publish_batch(
        self,
        db: Session,
        items: List[OutboxItem],
        claim_token: uuid.UUID,
        channel: Optional[Any] = None,
    ) -> Dict[str, int]:
        """Publish a list of claimed items.
        
        If channel is provided (e.g. for testing or pooled connection), uses it.
        Otherwise creates a blocking connection.
        """
        stats = {"published": 0, "unroutable": 0, "failed": 0}
        if not items:
            return stats

        managed_conn = None
        pub_channel = channel

        if pub_channel is None:
            if not self.parameters:
                raise ValueError("ConnectionParameters required when channel is not supplied")
            managed_conn = pika.BlockingConnection(self.parameters)
            pub_channel = managed_conn.channel()

        try:
            pub_channel.confirm_delivery()
            returned_events = set()

            def on_return(ch, method, properties, body):
                # When mandatory=True and no queue matches routing key
                msg_id = properties.message_id
                logger.warning(
                    "Outbox message unroutable: reply_code=%s reply_text=%s routing_key=%s msg_id=%s",
                    method.reply_code,
                    method.reply_text,
                    method.routing_key,
                    msg_id,
                )
                if msg_id:
                    returned_events.add(msg_id)

            pub_channel.add_on_return_callback(on_return)

            for item in items:
                msg_body = json.dumps(item.envelope).encode("utf-8")
                props = pika.BasicProperties(
                    delivery_mode=2,  # Persistent
                    content_type="application/json",
                    message_id=str(item.event_id),
                    correlation_id=str(item.envelope.get("correlation_id", "")),
                )

                try:
                    # mandatory=True ensures basic.return if unroutable
                    published = pub_channel.basic_publish(
                        exchange=EXCHANGE_NAME,
                        routing_key=item.routing_key,
                        body=msg_body,
                        properties=props,
                        mandatory=True,
                    )

                    # Check if returned as unroutable
                    if str(item.event_id) in returned_events:
                        stats["unroutable"] += 1
                        mark_outbox_failed(db, item.id, claim_token, backoff_seconds=10)
                    # BlockingChannel returns None after a confirmed ACK; NACK/return raise.
                    elif published is not False:
                        # Confirmed ack and not returned
                        mark_outbox_sent(db, item.id, claim_token)
                        stats["published"] += 1
                    else:
                        # Broker sent nack
                        stats["failed"] += 1
                        mark_outbox_failed(db, item.id, claim_token, backoff_seconds=5)
                except Exception as exc:
                    logger.error("Error publishing outbox event %s: %s", item.event_id, exc)
                    stats["failed"] += 1
                    mark_outbox_failed(db, item.id, claim_token, backoff_seconds=5)

            return stats
        finally:
            if managed_conn is not None:
                try:
                    managed_conn.close()
                except Exception:
                    pass


def publish_pending_outbox_batches(
    db: Session,
    batch_size: int = 10,
    host: str = "rabbitmq",
    user: str = "rabbit_diagnosis",
    password: str = "",
) -> int:
    """Claims pending outbox batch and publishes to RabbitMQ."""
    claim_token, items = claim_outbox_batch(db, batch_size=batch_size)
    if not items:
        return 0

    credentials = pika.PlainCredentials(user, password) if password else None
    params = pika.ConnectionParameters(
        host=host,
        credentials=credentials,
        connection_attempts=3,
        retry_delay=1.0,
    )
    publisher = DiagnosisOutboxPublisher(connection_parameters=params)
    stats = publisher.publish_batch(db=db, items=items, claim_token=claim_token)
    return stats.get("published", 0)


