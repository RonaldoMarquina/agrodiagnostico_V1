"""Durable DiagnosisFinished v1 consumer and decoupled email delivery runner (ADR-0014)."""
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
from threading import Event
from typing import Any, Callable, Optional, Sequence
import uuid

import pika
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.models import (
    Notification,
    NotificationDeliveryAttempt,
    NotificationInbox,
    NotificationPreference,
)
from app.infrastructure.email import (
    EmailDeliveryAdapter,
    EmailDeliveryError,
    get_email_delivery_adapter,
)
from app.infrastructure.event_validation import (
    compute_canonical_hash,
    validate_diagnosis_finished_v1,
)
from app.infrastructure.internal_client import (
    ContactLookupTransientError,
    IdentityContactClient,
)
from app.infrastructure.quarantine import (
    publish_pending_dlq_outbox,
    record_quarantine_and_dlq,
)

logger = logging.getLogger("notification.consumer")

CONSUMER_NAME = "notification-consumer"
QUEUE_NAME = "notification.diagnosis-finished.v1"
DEFAULT_RETRY_BACKOFF_SECONDS = (5, 15, 30)


class DiagnosisFinishedConsumer:
    """Consumes DiagnosisFinished v1 idempotently and processes decoupled email delivery attempts."""

    def __init__(
        self,
        db_session_factory: Callable[[], Session],
        contact_client: Optional[IdentityContactClient] = None,
        email_adapter: Optional[EmailDeliveryAdapter] = None,
        retry_backoff_seconds: Sequence[int] = DEFAULT_RETRY_BACKOFF_SECONDS,
    ):
        self.db_session_factory = db_session_factory
        self.contact_client = contact_client or IdentityContactClient.from_environment()
        self.email_adapter = email_adapter or get_email_delivery_adapter()
        self.retry_backoff_seconds = tuple(retry_backoff_seconds) or DEFAULT_RETRY_BACKOFF_SECONDS

    def process_message(
        self,
        channel: Any,
        delivery_tag: Any,
        body: bytes,
        routing_key: str,
        publish_channel: Any = None,
    ) -> bool:
        """Process one DiagnosisFinished message. Emits basic_ack strictly after local commit."""
        dlq_channel = publish_channel if publish_channel is not None else channel

        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            return self._quarantine_and_ack(
                channel=channel,
                dlq_channel=dlq_channel,
                delivery_tag=delivery_tag,
                raw_payload=body,
                routing_key=routing_key,
                reason_code="MALFORMED_JSON",
            )

        is_valid, reason_code = validate_diagnosis_finished_v1(parsed)
        if not is_valid:
            evt_id, cid = self._extract_safe_ids(parsed)
            return self._quarantine_and_ack(
                channel=channel,
                dlq_channel=dlq_channel,
                delivery_tag=delivery_tag,
                raw_payload=body,
                routing_key=routing_key,
                reason_code=reason_code or "SCHEMA_VALIDATION_FAILED",
                event_id=evt_id,
                correlation_id=cid,
            )

        event_id = uuid.UUID(parsed["event_id"])
        correlation_id = uuid.UUID(parsed["correlation_id"])
        payload = parsed["payload"]
        diagnosis_id = uuid.UUID(payload["diagnosis_id"])
        owner_id = uuid.UUID(payload["owner_id"])
        final_status = payload["final_status"]
        canonical_hash = compute_canonical_hash(parsed)

        queued_delivery = False
        quarantined_collision = False

        try:
            with self.db_session_factory() as db:
                existing_inbox = db.execute(
                    select(NotificationInbox).where(
                        NotificationInbox.consumer == CONSUMER_NAME,
                        NotificationInbox.event_id == event_id,
                    )
                ).scalar_one_or_none()

                if existing_inbox is not None:
                    if existing_inbox.payload_hash == canonical_hash:
                        # Exact idempotent duplicate
                        channel.basic_ack(delivery_tag=delivery_tag)
                        return True
                    # Same event_id with different content -> quarantine collision
                    record_quarantine_and_dlq(
                        db=db,
                        routing_key=routing_key,
                        raw_payload=body,
                        reason_code="EVENT_ID_COLLISION",
                        event_id=str(event_id),
                        correlation_id=str(correlation_id),
                    )
                    db.commit()
                    quarantined_collision = True
                else:
                    now = datetime.now(timezone.utc)
                    db.add(
                        NotificationInbox(
                            consumer=CONSUMER_NAME,
                            event_id=event_id,
                            payload_hash=canonical_hash,
                            diagnosis_id=diagnosis_id,
                            received_at=now,
                        )
                    )

                    existing_notif = db.execute(
                        select(Notification).where(Notification.diagnosis_id == diagnosis_id)
                    ).scalar_one_or_none()

                    if existing_notif is None:
                        notif = Notification(
                            owner_id=owner_id,
                            diagnosis_id=diagnosis_id,
                            final_status=final_status,
                            created_at=now,
                            read_at=None,
                            correlation_id=correlation_id,
                        )
                        db.add(notif)
                        db.flush()

                        pref = db.get(NotificationPreference, owner_id)
                        if pref is not None and bool(pref.email_enabled):
                            db.add(
                                NotificationDeliveryAttempt(
                                    notification_id=notif.id,
                                    owner_id=owner_id,
                                    channel="EMAIL",
                                    status="PENDING",
                                    attempt_count=0,
                                    max_attempts=3,
                                    next_attempt_at=now,
                                    created_at=now,
                                    updated_at=now,
                                )
                            )
                            queued_delivery = True

                    db.commit()
        except Exception as exc:
            logger.error("Failed local commit for DiagnosisFinished event_id=%s: %s", event_id, type(exc).__name__)
            return False

        if quarantined_collision:
            self._try_publish_dlq(dlq_channel)

        # ACK strictly after local commit
        channel.basic_ack(delivery_tag=delivery_tag)

        # Decoupled email delivery pass: failures never affect committed notification or ACK
        if queued_delivery:
            try:
                self.process_pending_deliveries(batch_size=5)
            except Exception as exc:
                logger.warning("Post-commit email delivery sweep failed safely: %s", type(exc).__name__)

        return True

    def process_pending_deliveries(self, batch_size: int = 20) -> dict:
        """Process due PENDING/FAILED_RETRYABLE email delivery attempts with bounded retries."""
        stats = {"sent": 0, "retryable": 0, "permanent": 0, "skipped": 0}

        with self.db_session_factory() as db:
            now = datetime.now(timezone.utc)
            dialect_name = db.bind.dialect.name if db.bind is not None else ""
            compare_now = now.replace(tzinfo=None) if dialect_name == "sqlite" else now

            stmt = (
                select(NotificationDeliveryAttempt)
                .where(
                    NotificationDeliveryAttempt.status.in_(("PENDING", "FAILED_RETRYABLE")),
                    or_(
                        NotificationDeliveryAttempt.next_attempt_at.is_(None),
                        NotificationDeliveryAttempt.next_attempt_at <= compare_now,
                    ),
                )
                .order_by(NotificationDeliveryAttempt.created_at.asc())
                .limit(batch_size)
            )
            if dialect_name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)

            attempts = db.execute(stmt).scalars().all()
            for attempt in attempts:
                notif = db.get(Notification, attempt.notification_id)
                if notif is None:
                    attempt.status = "SKIPPED"
                    attempt.last_error_code = "NOTIFICATION_MISSING"
                    attempt.next_attempt_at = None
                    attempt.updated_at = datetime.now(timezone.utc)
                    stats["skipped"] += 1
                    continue

                attempt_now = datetime.now(timezone.utc)
                try:
                    contact = self.contact_client.get_user_contact(
                        user_id=attempt.owner_id,
                        correlation_id=notif.correlation_id,
                    )
                except ContactLookupTransientError as exc:
                    self._record_retryable_or_permanent(attempt, exc.error_code, attempt_now, stats)
                    continue
                except Exception:
                    self._record_retryable_or_permanent(attempt, "IDENTITY_LOOKUP_ERROR", attempt_now, stats)
                    continue

                if not contact.found or not contact.active or not contact.email:
                    attempt.status = "SKIPPED"
                    attempt.last_error_code = "ACCOUNT_INACTIVE_OR_MISSING"
                    attempt.next_attempt_at = None
                    attempt.updated_at = attempt_now
                    stats["skipped"] += 1
                    continue

                try:
                    self.email_adapter.send_diagnosis_finished(
                        to_email=contact.email,
                        diagnosis_id=str(notif.diagnosis_id),
                        final_status=notif.final_status,
                        correlation_id=str(notif.correlation_id),
                    )
                except EmailDeliveryError as exc:
                    self._record_retryable_or_permanent(attempt, exc.error_code, attempt_now, stats)
                    continue
                except Exception:
                    self._record_retryable_or_permanent(attempt, "EMAIL_DELIVERY_ERROR", attempt_now, stats)
                    continue

                attempt.attempt_count += 1
                attempt.status = "SENT"
                attempt.sent_at = attempt_now
                attempt.next_attempt_at = None
                attempt.last_error_code = None
                attempt.updated_at = attempt_now
                stats["sent"] += 1

            if attempts:
                db.commit()

        return stats

    def _record_retryable_or_permanent(
        self,
        attempt: NotificationDeliveryAttempt,
        error_code: str,
        now: datetime,
        stats: dict,
    ) -> None:
        attempt.attempt_count += 1
        attempt.last_error_code = (error_code or "DELIVERY_ERROR")[:80]
        attempt.updated_at = now
        if attempt.attempt_count >= attempt.max_attempts:
            attempt.status = "FAILED_PERMANENT"
            attempt.next_attempt_at = None
            stats["permanent"] += 1
        else:
            idx = min(attempt.attempt_count - 1, len(self.retry_backoff_seconds) - 1)
            delay = self.retry_backoff_seconds[idx]
            attempt.status = "FAILED_RETRYABLE"
            attempt.next_attempt_at = now + timedelta(seconds=delay)
            stats["retryable"] += 1

    def _quarantine_and_ack(
        self,
        channel: Any,
        dlq_channel: Any,
        delivery_tag: Any,
        raw_payload: bytes,
        routing_key: str,
        reason_code: str,
        event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        try:
            with self.db_session_factory() as db:
                record_quarantine_and_dlq(
                    db=db,
                    routing_key=routing_key,
                    raw_payload=raw_payload,
                    reason_code=reason_code,
                    event_id=event_id,
                    correlation_id=correlation_id,
                )
                db.commit()
        except Exception as exc:
            logger.error("Failed to persist quarantine message reason=%s: %s", reason_code, type(exc).__name__)
            return False

        self._try_publish_dlq(dlq_channel)
        channel.basic_ack(delivery_tag=delivery_tag)
        return True

    def _try_publish_dlq(self, dlq_channel: Any) -> None:
        if dlq_channel is None:
            return
        try:
            with self.db_session_factory() as db:
                publish_pending_dlq_outbox(db, dlq_channel)
        except Exception as exc:
            logger.warning("DLQ outbox publish deferred: %s", type(exc).__name__)

    @staticmethod
    def _extract_safe_ids(parsed: Any) -> tuple[Optional[str], Optional[str]]:
        if not isinstance(parsed, dict):
            return None, None
        evt_id = parsed.get("event_id")
        cid = parsed.get("correlation_id")
        return (
            str(evt_id)[:64] if isinstance(evt_id, str) else None,
            str(cid)[:64] if isinstance(cid, str) else None,
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    from app.persistence import get_sessionmaker

    ready_file = Path("/tmp/notification_consumer_ready")
    rabbit_host = os.environ.get("RABBITMQ_HOST", "rabbitmq")
    rabbit_user = os.environ.get("RABBITMQ_USER", "rabbit_notification")
    pw_file = os.environ.get("RABBITMQ_PASSWORD_FILE", "/run/secrets/rabbit_notification_password")
    rabbit_pw = (
        Path(pw_file).read_text().strip()
        if Path(pw_file).is_file()
        else os.environ.get("RABBITMQ_PASSWORD", "")
    )

    credentials = pika.PlainCredentials(rabbit_user, rabbit_pw) if rabbit_pw else None
    params = pika.ConnectionParameters(
        host=rabbit_host,
        credentials=credentials,
        connection_attempts=10,
        retry_delay=2.0,
    )

    session_factory = get_sessionmaker()
    consumer = DiagnosisFinishedConsumer(db_session_factory=session_factory)
    stopping = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())

    while not stopping.is_set():
        connection = None
        try:
            connection = pika.BlockingConnection(params)
            consume_channel = connection.channel()
            consume_channel.basic_qos(prefetch_count=1)
            publish_channel = connection.channel()
            publish_channel.confirm_delivery()

            def on_message(ch, method, properties, body):
                ok = consumer.process_message(
                    ch,
                    method.delivery_tag,
                    body,
                    method.routing_key,
                    publish_channel=publish_channel,
                )
                if not ok:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    connection.sleep(2)

            consume_channel.basic_consume(
                queue=QUEUE_NAME,
                on_message_callback=on_message,
                auto_ack=False,
            )
            ready_file.touch()

            while not stopping.is_set():
                connection.process_data_events(time_limit=1)
                try:
                    consumer.process_pending_deliveries()
                    with session_factory() as db:
                        publish_pending_dlq_outbox(db, publish_channel)
                except Exception as sweep_exc:
                    logger.warning("Periodic notification sweep error: %s", type(sweep_exc).__name__)
        except Exception:
            logger.warning("Notification consumer interrupted; reconnecting without acknowledging pending work")
        finally:
            ready_file.unlink(missing_ok=True)
            if connection is not None and connection.is_open:
                connection.close()
        stopping.wait(2)

    return 0


if __name__ == "__main__":
    sys.exit(main())
