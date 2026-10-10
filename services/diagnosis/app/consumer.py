"""DiagnosisAnalyzed AMQP consumer and finalization authority for Diagnosis service.

Architectural guarantees (ADR-0008, Tasks 6.1, 6.2, 6.4):
- Diagnosis is the SOLE authority of visible diagnosis states and user-facing results.
- Pre-validation against DiagnosisAnalyzed.v1.schema.json; invalid schemas are quarantined
  and ACKed without executing business logic.
- Inbox deduplication by (consumer='diagnosis', event_id, canonical_hash). Idempotent
  duplicates are acknowledged without re-executing. Collisions with different payloads
  are quarantined and audited without altering existing inbox records.
- Strict fencing verification: checks that diagnosis status is PROCESANDO, lease_token matches,
  and DB relational clock (CURRENT_TIMESTAMP) is strictly less than lease_expires_at.
- Late results, expired leases, or results arriving for terminal states (CANCELADO,
  COMPLETADO, NO_CONCLUYENTE, FALLIDO) are discarded with operational audit and ACKed.
- Business decisions:
  * ABSTENTION -> NO_CONCLUYENTE (with reason_code)
  * FAILURE -> FALLIDO (with reason_code/failure_code)
  * PREDICTION ->
      - crop inactive / unsupported -> NO_CONCLUYENTE (UNSUPPORTED_CROP)
      - problem inactive / model_supported=False -> NO_CONCLUYENTE (UNSUPPORTED_CLASS)
      - recommendation unavailable -> NO_CONCLUYENTE (CATALOG_UNAVAILABLE)
      - valid crop, problem (model_supported=True), and active recommendation -> COMPLETADO
        with immutable snapshot of recommendation_id, catalog_version, and recommendation_text.
- Single atomic transaction confirms: Diagnosis state update, DiagnosisInbox, DiagnosisOutbox
  (DiagnosisFinished v1), and DiagnosisAuditLog BEFORE calling channel.basic_ack().
"""
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable, Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.internal_diagnoses import ensure_utc, get_db_now
from app.infrastructure.publication_policy import prediction_rejection
from app.domain.models import (
    Crop,
    Diagnosis,
    DiagnosisInbox,
    DiagnosisOutbox,
    DiagnosisQuarantineMessage,
    Problem,
    Recommendation,
)
from app.infrastructure.cursor import format_utc_iso
from app.infrastructure.event_validation import (
    compute_canonical_hash,
    validate_diagnosis_analyzed_v1,
    validate_diagnosis_finished_v1,
)
from app.infrastructure.quarantine import (
    publish_dlq_descriptor,
    record_audit_log,
    record_quarantine_message,
)

logger = logging.getLogger("diagnosis.consumer")

SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class DiagnosisAnalyzedConsumer:
    """Consumes DiagnosisAnalyzed events, decides visible status, and emits DiagnosisFinished."""

    def __init__(self, db_session_factory: Callable[[], Session]):
        self.db_session_factory = db_session_factory

    def process_message(
        self,
        channel: Any,
        delivery_tag: Any,
        body: bytes,
        routing_key: str,
    ) -> bool:
        """Process incoming DiagnosisAnalyzed message from RabbitMQ.
        
        Returns:
            True if message was acknowledged (processed, deduplicated, or quarantined),
            False if nacked.
        """
        # Step 1: Pre-validation
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception as ex:
            return self._quarantine_and_ack(
                channel=channel,
                delivery_tag=delivery_tag,
                raw_payload=body,
                routing_key=routing_key,
                error_reason=f"MALFORMED_JSON: {str(ex)[:150]}",
            )

        is_valid, error_reason = validate_diagnosis_analyzed_v1(parsed)
        if not is_valid:
            diag_id, evt_id = self._extract_uuids_defensive(parsed)
            return self._quarantine_and_ack(
                channel=channel,
                delivery_tag=delivery_tag,
                raw_payload=body,
                routing_key=routing_key,
                error_reason=error_reason or "SCHEMA_VALIDATION_FAILED",
                diagnosis_id=diag_id,
                event_id=evt_id,
            )

        try:
            event_id = uuid.UUID(parsed["event_id"])
            correlation_id = uuid.UUID(parsed["correlation_id"])
            payload = parsed["payload"]
            diagnosis_id = uuid.UUID(payload["diagnosis_id"])
            lease_token = uuid.UUID(payload["lease_token"])
        except Exception as ex:
            return self._quarantine_and_ack(
                channel=channel,
                delivery_tag=delivery_tag,
                raw_payload=body,
                routing_key=routing_key,
                error_reason=f"INVALID_FIELD_UUID: {str(ex)[:150]}",
            )

        canonical_hash = compute_canonical_hash(parsed)

        # Step 2: Inbox deduplication and collision check
        with self.db_session_factory() as session:
            stmt = select(DiagnosisInbox).where(
                DiagnosisInbox.consumer == "diagnosis",
                DiagnosisInbox.event_id == event_id,
            )
            existing_inbox = session.execute(stmt).scalar_one_or_none()

            if existing_inbox is not None:
                if existing_inbox.canonical_hash == canonical_hash:
                    # Idempotent duplicate: already processed
                    channel.basic_ack(delivery_tag=delivery_tag)
                    return True
                else:
                    # Integrity collision: same event_id with different content
                    quarantine_entry = None
                    try:
                        quarantine_entry = record_quarantine_message(
                            session=session,
                            consumer="diagnosis",
                            routing_key=routing_key,
                            raw_payload=body,
                            error_reason="EVENT_ID_COLLISION: Same event_id with different payload content",
                            diagnosis_id=diagnosis_id,
                            event_id=event_id,
                        )
                        record_audit_log(
                            session=session,
                            actor_id=SYSTEM_ACTOR_ID,
                            action="COLLISION_QUARANTINED",
                            target_type="diagnosis_inbox",
                            correlation_id=correlation_id,
                            target_id=str(event_id),
                            details={"error": "Event ID collision detected"},
                        )
                        session.commit()
                    except Exception as ex:
                        session.rollback()
                        logger.error("Failed to persist collision quarantine in DB: %s", str(ex))
                        return False

                    # Attempt DLQ descriptor publication via outbox
                    try:
                        if channel is not None and quarantine_entry is not None:
                            if publish_dlq_descriptor(channel, quarantine_entry):
                                quarantine_entry.descriptor_sent_at = datetime.now(timezone.utc)
                                session.commit()
                    except Exception as ex:
                        session.rollback()
                        logger.warning("DLQ temporarily unavailable for collision: %s (descriptor remains in DB)", str(ex))

                    channel.basic_ack(delivery_tag=delivery_tag)
                    return True

        # Step 3 & 4 & 5: Fencing, Business Decision, and Atomic Confirmation
        with self.db_session_factory() as session:
            # Row lock on Diagnosis
            diag_stmt = select(Diagnosis).where(Diagnosis.id == diagnosis_id)
            if session.bind and session.bind.dialect.name == "postgresql":
                diag_stmt = diag_stmt.with_for_update()
            diag = session.execute(diag_stmt).scalar_one_or_none()

            if diag is None:
                # Diagnosis not found
                record_audit_log(
                    session=session,
                    actor_id=SYSTEM_ACTOR_ID,
                    action="DIAGNOSIS_NOT_FOUND",
                    target_type="diagnosis",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                )
                session.commit()
                channel.basic_ack(delivery_tag=delivery_tag)
                return True

            now = get_db_now(session)

            # Check if diagnosis is already in terminal state
            if diag.status in ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO", "CANCELADO"):
                record_audit_log(
                    session=session,
                    actor_id=SYSTEM_ACTOR_ID,
                    action="LATE_RESULT_DISCARDED",
                    target_type="diagnosis",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                    details={
                        "reason": f"Diagnosis is already in terminal status '{diag.status}'",
                        "incoming_lease_token": str(lease_token),
                    },
                )
                session.commit()
                channel.basic_ack(delivery_tag=delivery_tag)
                return True

            if diag.status != "PROCESANDO":
                record_audit_log(
                    session=session,
                    actor_id=SYSTEM_ACTOR_ID,
                    action="NON_PROCESSING_RESULT_DISCARDED",
                    target_type="diagnosis",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                    details={"status": diag.status},
                )
                session.commit()
                channel.basic_ack(delivery_tag=delivery_tag)
                return True

            # Fencing check 1: Lease token match
            if diag.lease_token is None or diag.lease_token != lease_token:
                record_audit_log(
                    session=session,
                    actor_id=SYSTEM_ACTOR_ID,
                    action="STALE_LEASE_TOKEN_DISCARDED",
                    target_type="diagnosis",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                    details={
                        "expected_lease_token": str(diag.lease_token) if diag.lease_token else None,
                        "received_lease_token": str(lease_token),
                    },
                )
                session.commit()
                channel.basic_ack(delivery_tag=delivery_tag)
                return True

            # Fencing check 2: DB Clock expiration
            diag_expires = ensure_utc(diag.lease_expires_at)
            if diag_expires is not None and now >= diag_expires:
                record_audit_log(
                    session=session,
                    actor_id=SYSTEM_ACTOR_ID,
                    action="EXPIRED_LEASE_RESULT_DISCARDED",
                    target_type="diagnosis",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                    details={
                        "lease_expires_at": diag_expires.isoformat(),
                        "db_clock": now.isoformat(),
                    },
                )
                session.commit()
                channel.basic_ack(delivery_tag=delivery_tag)
                return True

            # Business Decision Logic
            outcome = payload.get("outcome")
            final_status: str
            reason_code: Optional[str] = None
            failure_code: Optional[str] = None

            if outcome == "ABSTENTION":
                final_status = "NO_CONCLUYENTE"
                reason_code = payload.get("reason_code", "LOW_CONFIDENCE")
                diag.status = final_status
                diag.reason_code = reason_code
                diag.crop_code = payload.get("crop_code")
                diag.class_code = None
                diag.raw_score = None
                diag.model_id = None
                diag.model_version = None
                diag.dataset_version = None

            elif outcome == "FAILURE":
                final_status = "FALLIDO"
                failure_code = payload.get("reason_code", "INFERENCE_ERROR")
                reason_code = failure_code
                diag.status = final_status
                diag.reason_code = reason_code
                diag.failure_code = failure_code
                diag.crop_code = None
                diag.class_code = None
                diag.raw_score = None
                diag.model_id = None
                diag.model_version = None
                diag.dataset_version = None

            elif outcome == "PREDICTION":
                crop_code = payload.get("crop_code")
                class_code = payload.get("class_code")
                raw_score = payload.get("raw_score")
                model_id = payload.get("model_id")
                model_version = payload.get("model_version")
                dataset_version = payload.get("dataset_version")

                # Validate Agricultural Catalog support
                crop = session.execute(
                    select(Crop).where(Crop.code == crop_code, Crop.active.is_(True))
                ).scalar_one_or_none()

                if crop is None:
                    final_status = "NO_CONCLUYENTE"
                    reason_code = "UNSUPPORTED_CROP"
                    diag.status = final_status
                    diag.reason_code = reason_code
                else:
                    problem = session.execute(
                        select(Problem).where(
                            Problem.code == class_code,
                            Problem.crop_code == crop_code,
                            Problem.active.is_(True),
                        )
                    ).scalar_one_or_none()

                    if problem is None or not problem.model_supported:
                        final_status = "NO_CONCLUYENTE"
                        reason_code = "UNSUPPORTED_CLASS"
                        diag.status = final_status
                        diag.reason_code = reason_code
                    elif rejection := prediction_rejection(payload):
                        final_status = "NO_CONCLUYENTE"
                        reason_code = rejection
                        diag.status = final_status
                        diag.reason_code = reason_code
                    else:
                        # Find active recommendation
                        rec = session.execute(
                            select(Recommendation)
                            .where(
                                Recommendation.problem_code == class_code,
                                Recommendation.active.is_(True),
                            )
                            .order_by(Recommendation.version.desc())
                        ).scalars().first()

                        if rec is None:
                            final_status = "NO_CONCLUYENTE"
                            reason_code = "CATALOG_UNAVAILABLE"
                            diag.status = final_status
                            diag.reason_code = reason_code
                        else:
                            final_status = "COMPLETADO"
                            diag.status = final_status
                            diag.reason_code = None
                            diag.recommendation_id = rec.id
                            diag.catalog_version = str(rec.version)
                            diag.recommendation_text = rec.summary

                diag.crop_code = crop_code
                diag.class_code = class_code
                diag.raw_score = raw_score
                diag.model_id = model_id
                diag.model_version = model_version
                diag.dataset_version = dataset_version

            else:
                self._quarantine_and_ack(
                    channel=channel,
                    delivery_tag=delivery_tag,
                    raw_payload=body,
                    routing_key=routing_key,
                    error_reason=f"UNKNOWN_OUTCOME: {outcome}",
                    diagnosis_id=diagnosis_id,
                    event_id=event_id,
                )
                return True

            # Clear active lease on terminal transition
            diag.lease_token = None
            diag.lease_expires_at = None
            diag.updated_at = now

            # Construct DiagnosisFinished v1 envelope
            finished_event_id = uuid.uuid4()
            finished_envelope = {
                "event_id": str(finished_event_id),
                "event_type": "DiagnosisFinished",
                "schema_version": 1,
                "occurred_at": format_utc_iso(now),
                "correlation_id": str(diag.correlation_id or correlation_id),
                "payload": {
                    "diagnosis_id": str(diagnosis_id),
                    "owner_id": str(diag.owner_id),
                    "final_status": final_status,
                },
            }

            val_ok, val_err = validate_diagnosis_finished_v1(finished_envelope)
            if not val_ok:
                raise RuntimeError(f"Generated DiagnosisFinished envelope failed contract: {val_err}")

            try:
                # 1. Inbox entry
                inbox_entry = DiagnosisInbox(
                    consumer="diagnosis",
                    event_id=event_id,
                    canonical_hash=canonical_hash,
                    diagnosis_id=diagnosis_id,
                    lease_token=lease_token,
                    status="PROCESSED",
                    processed_at=now,
                )
                session.add(inbox_entry)

                # 2. Outbox entry for Finished event
                outbox_entry = DiagnosisOutbox(
                    event_id=finished_event_id,
                    event_type="DiagnosisFinished",
                    schema_version=1,
                    routing_key="diagnosis.finished.v1",
                    envelope=finished_envelope,
                    diagnosis_id=diagnosis_id,
                    attempt_number=1,
                    created_at=now,
                    available_at=now,
                )
                session.add(outbox_entry)

                # 3. Operational Audit log
                record_audit_log(
                    session=session,
                    actor_id=SYSTEM_ACTOR_ID,
                    action="DIAGNOSIS_FINALIZED",
                    target_type="diagnosis",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                    details={
                        "final_status": final_status,
                        "reason_code": reason_code,
                        "failure_code": failure_code,
                    },
                )

                # Atomic commit of state update, inbox, outbox, and audit
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(select(DiagnosisInbox).where(
                    DiagnosisInbox.consumer == "diagnosis",
                    DiagnosisInbox.event_id == event_id,
                    DiagnosisInbox.canonical_hash == canonical_hash,
                ))
                if existing is not None:
                    channel.basic_ack(delivery_tag=delivery_tag)
                    return True
                return False

        # ONLY after DB commit succeeds: acknowledge broker message
        channel.basic_ack(delivery_tag=delivery_tag)
        return True

    def _quarantine_and_ack(
        self,
        channel: Any,
        delivery_tag: Any,
        raw_payload: bytes,
        routing_key: str,
        error_reason: str,
        diagnosis_id: Optional[uuid.UUID] = None,
        event_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Persist invalid message in quarantine and acknowledge broker."""
        quarantine_entry = None
        try:
            with self.db_session_factory() as session:
                quarantine_entry = record_quarantine_message(
                    session=session,
                    consumer="diagnosis",
                    routing_key=routing_key,
                    raw_payload=raw_payload,
                    error_reason=error_reason[:255],
                    diagnosis_id=diagnosis_id,
                    event_id=event_id,
                )
                session.commit()
                quarantine_id = quarantine_entry.id
        except Exception as ex:
            logger.error(
                "Failed to persist quarantine message in DB for routing_key=%s reason=%s: %s",
                routing_key,
                error_reason[:100],
                str(ex),
            )
            # Persistence failed: DO NOT acknowledge message
            return False

        # Attempt to publish DLQ descriptor via outbox pattern
        try:
            with self.db_session_factory() as session:
                entry = session.get(DiagnosisQuarantineMessage, quarantine_id)
                if entry and channel is not None:
                    if publish_dlq_descriptor(channel, entry):
                        entry.descriptor_sent_at = datetime.now(timezone.utc)
                        session.commit()
        except Exception as ex:
            logger.warning(
                "DLQ broker temporarily unavailable for quarantine_id=%s: %s (descriptor remains in DB)",
                quarantine_id,
                str(ex),
            )

        # Only after quarantine is safely persisted: acknowledge the broker message
        channel.basic_ack(delivery_tag=delivery_tag)
        return True

    def _extract_uuids_defensive(self, parsed: Any) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
        """Safely extract diagnosis_id and event_id from unvalidated message if possible."""
        diag_id: Optional[uuid.UUID] = None
        evt_id: Optional[uuid.UUID] = None
        if isinstance(parsed, dict):
            try:
                evt_id = uuid.UUID(parsed.get("event_id"))
            except Exception:
                pass
            payload = parsed.get("payload")
            if isinstance(payload, dict):
                try:
                    diag_id = uuid.UUID(payload.get("diagnosis_id"))
                except Exception:
                    pass
        return diag_id, evt_id


def main() -> int:
    import os
    from pathlib import Path
    import signal
    import sys
    import pika
    from app.persistence import get_sessionmaker
    from threading import Event

    ready_file = Path("/tmp/diagnosis_consumer_ready")

    rabbit_host = os.environ.get("RABBITMQ_HOST", "rabbitmq")
    rabbit_user = os.environ.get("RABBITMQ_USER", "rabbit_diagnosis")
    pw_file = os.environ.get("RABBITMQ_PASSWORD_FILE", "/run/secrets/rabbit_diagnosis_password")
    rabbit_pw = Path(pw_file).read_text().strip() if Path(pw_file).is_file() else os.environ.get("RABBITMQ_PASSWORD", "")

    credentials = pika.PlainCredentials(rabbit_user, rabbit_pw) if rabbit_pw else None
    params = pika.ConnectionParameters(
        host=rabbit_host,
        credentials=credentials,
        connection_attempts=10,
        retry_delay=2.0,
    )

    consumer = DiagnosisAnalyzedConsumer(db_session_factory=get_sessionmaker())
    stopping = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    while not stopping.is_set():
        connection = None
        try:
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                if not consumer.process_message(ch, method.delivery_tag, body, method.routing_key):
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    connection.sleep(2)

            channel.basic_consume(queue="diagnosis.diagnosis-analyzed.v1",
                                  on_message_callback=on_message, auto_ack=False)
            ready_file.touch()
            while not stopping.is_set():
                connection.process_data_events(time_limit=1)
        except Exception:
            logger.warning("Diagnosis consumer interrupted; reconnecting without acknowledging pending work")
        finally:
            ready_file.unlink(missing_ok=True)
            if connection is not None and connection.is_open:
                connection.close()
        stopping.wait(2)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

