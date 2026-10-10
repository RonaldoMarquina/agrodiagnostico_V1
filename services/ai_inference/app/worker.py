"""AI Inference asynchronous worker consumer for DiagnosisRequested v1 and v2.

Architectural guarantees (ADR-0008, Tasks 5.1-5.4):
- ZERO direct access to S3 or Diagnosis database tables. Worker interacts exclusively
  with Diagnosis via internal HTTP API (/internal/diagnoses/{id}/claim, /image) authenticated
  with dedicated Ed25519 instance JWTs.
- Strict pre-validation: validates against DiagnosisRequested.v1 or v2 JSON schemas before
  any side-effects. Malformed/unknown versions are quarantined transactionally and ACKed.
- Inbox deduplication by (consumer='ai_inference', event_id, canonical_hash). Idempotent
  redelivery is acknowledged without re-executing. Same event_id with different hash is
  quarantined as an integrity collision and ACKed without overwriting existing inbox record.
- Local exclusive claim via InferenceJob row lock and expirative local claim token.
- Atomic HTTP claim with lease derivation. Uncertain claim timeouts fail closed without
  blind retry loops.
- Fenced image fetch via X-Lease-Token header. Stale lease (409) terminates processing immediately.
- Atomic commit: InferenceResult, InferenceInbox, InferenceOutbox (DiagnosisAnalyzed v1),
  and InferenceJob status are committed in a single database transaction BEFORE calling basic_ack.
- Crash recovery: crash before commit leaves message unacknowledged; crash between commit
  and ACK is safely deduplicated upon redelivery.
"""
from datetime import datetime, timedelta, timezone
import json
import logging
from contextlib import contextmanager
from threading import Event, Thread
from typing import Any, Callable, Dict, Optional
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import (
    InferenceInbox,
    InferenceJob,
    InferenceOutbox,
    InferenceQuarantineMessage,
    InferenceResult,
)
from app.infrastructure.auth import InternalTokenSigner
from app.infrastructure.event_validation import (
    compute_canonical_hash,
    validate_diagnosis_analyzed_v1,
    validate_diagnosis_requested,
)
from app.infrastructure.quarantine import (
    publish_inference_dlq_descriptor,
    record_audit_log,
    record_quarantine_message,
)
from app.simulator import run_simulated_inference

logger = logging.getLogger("ai_inference.worker")


class InferenceWorker:
    """Consumes DiagnosisRequested events and runs technical inference."""

    def __init__(
        self,
        db_session_factory: Callable[[], Session],
        diagnosis_internal_url: str,
        token_signer: InternalTokenSigner,
        http_client: Optional[httpx.Client] = None,
        local_lease_seconds: int = 60,
        heartbeat_seconds: float = 20,
    ):
        if local_lease_seconds <= 0 or not 0 < heartbeat_seconds < local_lease_seconds:
            raise ValueError("Heartbeat must be positive and shorter than the local lease")
        self.db_session_factory = db_session_factory
        self.diagnosis_internal_url = diagnosis_internal_url.rstrip("/")
        self.token_signer = token_signer
        self.http_client = http_client or httpx.Client(timeout=10.0)
        self.local_lease_seconds = local_lease_seconds
        self.heartbeat_seconds = heartbeat_seconds

    def process_message(
        self,
        channel: Any,
        delivery_tag: Any,
        body: bytes,
        routing_key: str,
    ) -> bool:
        """Process incoming AMQP message.
        
        Returns:
            True if message was acknowledged (processed, deduplicated, or quarantined),
            False if message was nacked/requeued.
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

        is_valid, error_reason, schema_version = validate_diagnosis_requested(parsed)
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

        # Extract envelope fields
        try:
            event_id = uuid.UUID(parsed["event_id"])
            correlation_id = uuid.UUID(parsed["correlation_id"])
            diagnosis_id = uuid.UUID(parsed["payload"]["diagnosis_id"])
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
            stmt = select(InferenceInbox).where(
                InferenceInbox.consumer == "ai_inference",
                InferenceInbox.event_id == event_id,
            )
            existing_inbox = session.execute(stmt).scalar_one_or_none()

            if existing_inbox is not None:
                if existing_inbox.canonical_hash == canonical_hash:
                    # Idempotent redelivery after crash or network retry
                    channel.basic_ack(delivery_tag=delivery_tag)
                    return True
                else:
                    # Collision: same event_id with different payload content
                    quarantine_entry = None
                    try:
                        quarantine_entry = record_quarantine_message(
                            session=session,
                            consumer="ai_inference",
                            routing_key=routing_key,
                            raw_payload=body,
                            error_reason="EVENT_ID_COLLISION: Same event_id with different payload content",
                            diagnosis_id=diagnosis_id,
                            event_id=event_id,
                        )
                        record_audit_log(
                            session=session,
                            actor="ai_worker",
                            action="COLLISION_QUARANTINED",
                            correlation_id=correlation_id,
                            target_id=str(event_id),
                            details={"error": "Event ID collision detected"},
                        )
                        session.commit()
                    except Exception as ex:
                        session.rollback()
                        logger.error("Failed to persist collision quarantine in DB")
                        channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                        return False

                    # Attempt DLQ descriptor publication via outbox
                    try:
                        if channel is not None and quarantine_entry is not None:
                            if publish_inference_dlq_descriptor(channel, quarantine_entry):
                                quarantine_entry.descriptor_sent_at = datetime.now(timezone.utc)
                                session.commit()
                    except Exception as ex:
                        session.rollback()
                        logger.warning("DLQ temporarily unavailable for collision: %s (descriptor remains in DB)", str(ex))

                    channel.basic_ack(delivery_tag=delivery_tag)
                    return True

        # Step 3: Local exclusive job claim
        local_claim_token = uuid.uuid4()
        now = datetime.now(timezone.utc)
        with self.db_session_factory() as session:
            # Query job with update lock
            stmt = select(InferenceJob).where(InferenceJob.diagnosis_id == diagnosis_id)
            if session.bind and session.bind.dialect.name == "postgresql":
                stmt = stmt.with_for_update()
            job = session.execute(stmt).scalar_one_or_none()

            if job is not None:
                if job.status in ("CLAIMING", "PROCESSING"):
                    if job.local_claim_expires_at is not None:
                        job_exp = job.local_claim_expires_at
                        if job_exp.tzinfo is None:
                            job_exp = job_exp.replace(tzinfo=timezone.utc)
                        if now < job_exp:
                            # Concurrent execution in progress; requeue message
                            channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                            return False

                # Claim expired or job is queued/failed: take over local claim
                job.status = "CLAIMING"
                job.local_claim_token = local_claim_token
                job.local_claim_expires_at = now + timedelta(seconds=self.local_lease_seconds)
                session.commit()
            else:
                job = InferenceJob(
                    diagnosis_id=diagnosis_id,
                    status="CLAIMING",
                    local_claim_token=local_claim_token,
                    local_claim_expires_at=now + timedelta(seconds=self.local_lease_seconds),
                )
                session.add(job)
                session.commit()

        # Step 4: HTTP claim on Diagnosis service
        internal_jwt = self.token_signer.issue_token()
        claim_headers = {
            "Authorization": f"Bearer {internal_jwt}",
            "X-Correlation-ID": str(correlation_id),
        }
        claim_url = f"{self.diagnosis_internal_url}/internal/diagnoses/{diagnosis_id}/claim"

        try:
            claim_resp = self.http_client.post(claim_url, headers=claim_headers)
        except Exception as ex:
            # Uncertain claim timeout: do NOT loop retry
            self._handle_uncertain_claim_failure(diagnosis_id, correlation_id, str(ex), local_claim_token)
            channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
            return False

        if claim_resp.status_code == 200:
            claim_data = claim_resp.json()
            lease_token = uuid.UUID(claim_data["lease_token"])
            with self.db_session_factory() as session:
                job = session.execute(
                    select(InferenceJob).where(InferenceJob.diagnosis_id == diagnosis_id).with_for_update()
                ).scalar_one()
                if job.local_claim_token != local_claim_token:
                    channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                    return False
                job.status = "PROCESSING"
                job.current_lease_token = lease_token
                session.commit()
        elif claim_resp.status_code == 409:
            # Conflict on claim
            error_data = {}
            try:
                error_data = claim_resp.json()
            except Exception:
                pass
            error_code = error_data.get("code") if isinstance(error_data, dict) else ""

            # Check if permanently unclaimable (terminal state, cancelado, deadline, budget)
            with self.db_session_factory() as session:
                job = session.execute(
                    select(InferenceJob).where(InferenceJob.diagnosis_id == diagnosis_id)
                ).scalar_one_or_none()
                if job and job.local_claim_token == local_claim_token:
                    job.status = "DISCARDED"
                    job.local_claim_token = None
                    job.local_claim_expires_at = None
                record_audit_log(
                    session=session,
                    actor="ai_worker",
                    action="CLAIM_CONFLICT_409",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                    details={"code": error_code, "status": claim_resp.status_code},
                )
                session.commit()

            terminal = isinstance(error_data, dict) and any(
                item.get("field") == "status" and item.get("code") == "TERMINAL"
                for item in error_data.get("details", []) if isinstance(item, dict)
            )
            if terminal:
                channel.basic_ack(delivery_tag=delivery_tag)
                return True
            channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
            return False
        else:
            # Only a missing diagnosis is permanent; retain deliveries on infrastructure errors.
            with self.db_session_factory() as session:
                job = session.execute(
                    select(InferenceJob).where(InferenceJob.diagnosis_id == diagnosis_id)
                ).scalar_one_or_none()
                if job and job.local_claim_token == local_claim_token:
                    job.status = "FAILED"
                    job.local_claim_token = None
                    job.local_claim_expires_at = None
                record_audit_log(
                    session=session,
                    actor="ai_worker",
                    action="CLAIM_HTTP_ERROR",
                    correlation_id=correlation_id,
                    target_id=str(diagnosis_id),
                    details={"status": claim_resp.status_code},
                )
                session.commit()

            if claim_resp.status_code == 404:
                channel.basic_ack(delivery_tag=delivery_tag)
                return True
            channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
            return False

        with self._heartbeat(diagnosis_id, lease_token, local_claim_token, correlation_id) as lost_lease:
            # Step 5: Fetch private image bytes via internal API
            image_headers = {
                "Authorization": f"Bearer {internal_jwt}",
                "X-Lease-Token": str(lease_token),
                "X-Correlation-ID": str(correlation_id),
            }
            image_url = f"{self.diagnosis_internal_url}/internal/diagnoses/{diagnosis_id}/image"

            try:
                image_resp = self.http_client.get(image_url, headers=image_headers)
            except Exception as ex:
                # Transient image network error: consumes this attempt without inner loops
                self._handle_execution_failure(diagnosis_id, correlation_id, f"IMAGE_NETWORK_ERROR: {str(ex)[:150]}", local_claim_token)
                channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                return False

            if image_resp.status_code == 409:
                # Stale lease! Lease expired before or during image fetch; fencing violated.
                self._handle_execution_failure(diagnosis_id, correlation_id, "STALE_LEASE_ON_IMAGE_FETCH", local_claim_token)
                channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                return False
            elif image_resp.status_code != 200:
                self._handle_execution_failure(
                    diagnosis_id, correlation_id, f"IMAGE_FETCH_HTTP_{image_resp.status_code}", local_claim_token
                )
                channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                return False

            image_bytes = image_resp.content

            # Step 6: Technical inference execution (simulator in test environment)
            try:
                inference = run_simulated_inference(diagnosis_id=diagnosis_id, image_bytes=image_bytes)
            except Exception as ex:
                self._handle_execution_failure(diagnosis_id, correlation_id, f"INFERENCE_ERROR: {str(ex)[:150]}", local_claim_token)
                channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                return False

            # Step 7: Atomic commit (Result + Inbox + Outbox + Job Status)
            analyzed_event_id = uuid.uuid4()
            now_dt = datetime.now(timezone.utc)
            occurred_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            analyzed_payload: Dict[str, Any] = {
                "diagnosis_id": str(diagnosis_id),
                "lease_token": str(lease_token),
                "crop_code": inference.get("crop_code"),
                "outcome": inference["outcome"],
                "model_id": inference.get("model_id"),
                "model_version": inference.get("model_version"),
                "dataset_version": inference.get("dataset_version"),
                "inference_ms": inference.get("inference_ms"),
            }
            if inference["outcome"] == "PREDICTION":
                analyzed_payload["class_code"] = inference["class_code"]
                analyzed_payload["raw_score"] = float(inference["raw_score"])
            else:
                analyzed_payload["reason_code"] = inference["reason_code"]

            analyzed_envelope = {
                "event_id": str(analyzed_event_id),
                "event_type": "DiagnosisAnalyzed",
                "schema_version": 1,
                "occurred_at": occurred_iso,
                "correlation_id": str(correlation_id),
                "payload": analyzed_payload,
            }

            # Contract assertion
            val_ok, val_err = validate_diagnosis_analyzed_v1(analyzed_envelope)
            if not val_ok:
                raise RuntimeError(f"Generated DiagnosisAnalyzed envelope failed contract: {val_err}")

            with self.db_session_factory() as session:
                try:
                    job = session.execute(select(InferenceJob).where(
                        InferenceJob.diagnosis_id == diagnosis_id
                    ).with_for_update()).scalar_one()
                    expires = job.local_claim_expires_at
                    if expires is not None and expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if (lost_lease.is_set() or job.local_claim_token != local_claim_token
                            or expires is None or expires <= datetime.now(timezone.utc)):
                        channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                        return False
                    # 1. InferenceResult
                    result_entry = InferenceResult(
                        diagnosis_id=diagnosis_id,
                        lease_token=lease_token,
                        outcome=inference["outcome"],
                        crop_code=inference.get("crop_code"),
                        class_code=inference.get("class_code"),
                        raw_score=float(inference["raw_score"]) if inference.get("raw_score") is not None else None,
                        model_id=inference.get("model_id"),
                        model_version=inference.get("model_version"),
                        dataset_version=inference.get("dataset_version"),
                        reason_code=inference.get("reason_code"),
                        inference_ms=inference.get("inference_ms"),
                    )
                    session.add(result_entry)

                    # 2. InferenceInbox
                    inbox_entry = InferenceInbox(
                        consumer="ai_inference",
                        event_id=event_id,
                        canonical_hash=canonical_hash,
                        diagnosis_id=diagnosis_id,
                        status="PROCESSED",
                    )
                    session.add(inbox_entry)

                    # 3. InferenceOutbox
                    outbox_entry = InferenceOutbox(
                        event_id=analyzed_event_id,
                        event_type="DiagnosisAnalyzed",
                        schema_version=1,
                        routing_key="diagnosis.analyzed.v1",
                        envelope=analyzed_envelope,
                        diagnosis_id=diagnosis_id,
                        lease_token=lease_token,
                    )
                    session.add(outbox_entry)

                    # 4. InferenceJob status
                    job = session.execute(
                        select(InferenceJob).where(InferenceJob.diagnosis_id == diagnosis_id)
                    ).scalar_one()
                    job.status = "COMPLETED"
                    job.local_claim_token = None
                    job.local_claim_expires_at = None

                    # 5. Audit log
                    record_audit_log(
                        session=session,
                        actor="ai_worker",
                        action="ANALYSIS_COMPLETED",
                        correlation_id=correlation_id,
                        target_id=str(diagnosis_id),
                        details={"outcome": inference["outcome"]},
                    )

                    session.commit()
                except IntegrityError:
                    session.rollback()
                    existing = session.scalar(select(InferenceInbox).where(
                        InferenceInbox.consumer == "ai_inference",
                        InferenceInbox.event_id == event_id,
                        InferenceInbox.canonical_hash == canonical_hash,
                    ))
                    if existing is not None:
                        channel.basic_ack(delivery_tag=delivery_tag)
                        return True
                    channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
                    return False

            # Step 8: Broker ACK ONLY after DB commit
            channel.basic_ack(delivery_tag=delivery_tag)
            return True

    @contextmanager
    def _heartbeat(self, diagnosis_id, lease_token, local_claim_token, correlation_id):
        stop, lost = Event(), Event()

        def renew():
            while not stop.wait(self.heartbeat_seconds):
                try:
                    response = self.http_client.post(
                        f"{self.diagnosis_internal_url}/internal/diagnoses/{diagnosis_id}/lease/renew",
                        headers={"Authorization": f"Bearer {self.token_signer.issue_token()}",
                                 "X-Correlation-ID": str(correlation_id)},
                        json={"lease_token": str(lease_token)},
                    )
                    if response.status_code != 200:
                        lost.set()
                        return
                    with self.db_session_factory() as session:
                        job = session.scalar(select(InferenceJob).where(
                            InferenceJob.diagnosis_id == diagnosis_id
                        ).with_for_update())
                        if job is None or job.local_claim_token != local_claim_token:
                            lost.set()
                            return
                        job.local_claim_expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.local_lease_seconds)
                        session.commit()
                except Exception:
                    logger.warning("Lease renewal failed; execution will not commit")
                    lost.set()
                    return

        thread = Thread(target=renew, name="lease-heartbeat", daemon=True)
        thread.start()
        try:
            yield lost
        finally:
            stop.set()
            thread.join(timeout=12)

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
        """Record invalid message in quarantine and acknowledge broker."""
        quarantine_entry = None
        try:
            with self.db_session_factory() as session:
                quarantine_entry = record_quarantine_message(
                    session=session,
                    consumer="ai_inference",
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
            channel.basic_nack(delivery_tag=delivery_tag, requeue=True)
            return False

        # Attempt to publish DLQ descriptor via outbox pattern
        try:
            with self.db_session_factory() as session:
                entry = session.get(InferenceQuarantineMessage, quarantine_id)
                if entry and channel is not None:
                    if publish_inference_dlq_descriptor(channel, entry):
                        entry.descriptor_sent_at = datetime.now(timezone.utc)
                        session.commit()
        except Exception as ex:
            logger.warning(
                "DLQ broker temporarily unavailable for quarantine_id=%s: %s (descriptor remains in DB)",
                quarantine_id,
                str(ex),
            )

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

    def _handle_uncertain_claim_failure(
        self,
        diagnosis_id: uuid.UUID,
        correlation_id: uuid.UUID,
        error_msg: str,
        local_claim_token: uuid.UUID,
    ) -> None:
        """Handle uncertain claim failure (timeout, network error)."""
        with self.db_session_factory() as session:
            job = session.execute(
                select(InferenceJob).where(InferenceJob.diagnosis_id == diagnosis_id).with_for_update()
            ).scalar_one_or_none()
            if job and job.local_claim_token == local_claim_token:
                job.status = "FAILED"
                job.local_claim_token = None
                job.local_claim_expires_at = None
            record_audit_log(
                session=session,
                actor="ai_worker",
                action="CLAIM_TIMEOUT_UNCERTAIN",
                correlation_id=correlation_id,
                target_id=str(diagnosis_id),
                details={"error": error_msg[:200]},
            )
            session.commit()

    def _handle_execution_failure(
        self,
        diagnosis_id: uuid.UUID,
        correlation_id: uuid.UUID,
        error_msg: str,
        local_claim_token: uuid.UUID,
    ) -> None:
        """Handle execution failure (image fetch error, inference error).
        
        Consumes this attempt without inner loops exceeding generation budget.
        """
        with self.db_session_factory() as session:
            job = session.execute(
                select(InferenceJob).where(InferenceJob.diagnosis_id == diagnosis_id).with_for_update()
            ).scalar_one_or_none()
            if job and job.local_claim_token == local_claim_token:
                job.status = "FAILED"
                job.local_claim_token = None
                job.local_claim_expires_at = None
            record_audit_log(
                session=session,
                actor="ai_worker",
                action="EXECUTION_FAILED",
                correlation_id=correlation_id,
                target_id=str(diagnosis_id),
                details={"error": error_msg[:200]},
            )
            session.commit()


def main() -> int:
    import os
    from pathlib import Path
    import signal
    import sys
    import pika
    from app.persistence import get_sessionmaker

    instance_id = os.environ.get(
        "WORKER_INSTANCE_ID",
        os.environ.get("INTERNAL_WORKER_INSTANCE_ID", "worker-1"),
    )
    ready_file = Path(f"/tmp/ai_worker_ready_{instance_id}")

    rabbit_host = os.environ.get("RABBITMQ_HOST", "rabbitmq")
    rabbit_user = os.environ.get("RABBITMQ_USER", "rabbit_ai_inference")
    pw_file = os.environ.get("RABBITMQ_PASSWORD_FILE", "/run/secrets/rabbit_ai_inference_password")
    rabbit_pw = Path(pw_file).read_text().strip() if Path(pw_file).is_file() else os.environ.get("RABBITMQ_PASSWORD", "")

    diag_internal_url = os.environ.get("DIAGNOSIS_INTERNAL_URL", "http://diagnosis:8000")

    signer = InternalTokenSigner.from_environment()
    if signer is None:
        raise RuntimeError("A configured internal worker signing key is required")
    from app.simulator import ensure_simulation_permitted
    ensure_simulation_permitted()

    credentials = pika.PlainCredentials(rabbit_user, rabbit_pw) if rabbit_pw else None
    params = pika.ConnectionParameters(
        host=rabbit_host,
        credentials=credentials,
        connection_attempts=10,
        retry_delay=2.0,
    )

    worker = InferenceWorker(
        db_session_factory=get_sessionmaker(),
        diagnosis_internal_url=diag_internal_url,
        token_signer=signer,
        local_lease_seconds=int(os.environ.get("LEASE_DURATION_SECONDS", "60")),
        heartbeat_seconds=float(os.environ.get("LEASE_HEARTBEAT_SECONDS", "20")),
    )
    stopping = Event()

    def sig_handler(signum, frame):
        stopping.set()

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)
    while not stopping.is_set():
        connection = None
        try:
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                processed = worker.process_message(
                    channel=ch, delivery_tag=method.delivery_tag,
                    body=body, routing_key=method.routing_key,
                )
                if not processed:
                    connection.sleep(2.0)

            for version in (1, 2):
                channel.basic_consume(
                    queue=f"ai_inference.diagnosis-requested.v{version}",
                    on_message_callback=on_message, auto_ack=False,
                )
            ready_file.touch()
            Path("/tmp/ai_worker_ready").touch()
            while not stopping.is_set():
                connection.process_data_events(time_limit=1)
        except Exception:
            # Closing the connection requeues any delivery without a durable ACK.
            logger.warning("Worker transport or persistence interrupted; reconnecting")
        finally:
            for path in (ready_file, Path("/tmp/ai_worker_ready")):
                path.unlink(missing_ok=True)
            if connection is not None and connection.is_open:
                connection.close()
        stopping.wait(2)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


