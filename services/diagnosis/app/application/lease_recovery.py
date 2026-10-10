"""Lease recovery service for expired diagnosis executions.

In accordance with ADR-0008 (D6) and Task 6.3:
- Inspects diagnoses in status='PROCESANDO' whose lease_expires_at is in the past.
- Enforces minimum recovery waits (5s after attempt 1, 15s after attempt 2).
- Emits exactly ONE recovery signal per generation (tracked via recovery_signaled_at >= lease_expires_at).
- Respects maximum 3 execution generations and global processing deadline (300s).
- When budget or deadline is exhausted, atómicamente transitions to FALLIDO with
  reason_code='PROCESSING_TIMEOUT' and emits exactly ONE DiagnosisFinished v1 outbox event.
- When budget and deadline allow, emits a new DiagnosisRequested v2 outbox signal
  with a new event_id and attempt_number=(current attempt + 1).
- Unclaimed PENDIENTE diagnoses have no lease and are NEVER expired or timed out by this recovery policy.
"""
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.internal_diagnoses import ensure_utc, get_db_now
from app.domain.models import Diagnosis, DiagnosisOutbox
from app.infrastructure.cursor import format_utc_iso
from app.infrastructure.event_validation import validate_diagnosis_finished_v1
from app.infrastructure.lease_config import LeasePolicy, get_lease_policy
from app.infrastructure.quarantine import record_audit_log

logger = logging.getLogger("diagnosis.lease_recovery")

SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def recover_expired_leases(
    session: Session,
    policy: Optional[LeasePolicy] = None,
) -> List[Dict[str, Any]]:
    """Scan and process expired leases, recovering or timing out as appropriate.
    
    Returns a list of summary action dictionaries for processed diagnoses.
    """
    if policy is None:
        policy = get_lease_policy()

    now = get_db_now(session)

    # Find candidate diagnoses in PROCESANDO whose lease has expired
    stmt = (
        select(Diagnosis)
        .where(
            Diagnosis.status == "PROCESANDO",
            Diagnosis.lease_expires_at.is_not(None),
            Diagnosis.lease_expires_at <= now,
        )
        .order_by(Diagnosis.lease_expires_at.asc())
    )

    if session.bind and session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    candidates = session.execute(stmt).scalars().all()
    actions_taken: List[Dict[str, Any]] = []

    for diag in candidates:
        if diag.status != "PROCESANDO" or diag.lease_expires_at is None:
            continue

        lease_exp = ensure_utc(diag.lease_expires_at)
        if lease_exp is None or now < lease_exp:
            continue

        # 3. Check budget exhaustion or deadline reached
        deadline = ensure_utc(diag.processing_deadline_at)
        budget_exhausted = diag.attempt_count >= policy.max_attempt_count
        deadline_reached = deadline is not None and now >= deadline

        if budget_exhausted or deadline_reached:
            # Terminal PROCESSING_TIMEOUT transition
            diag.status = "FALLIDO"
            diag.reason_code = "PROCESSING_TIMEOUT"
            diag.failure_code = "PROCESSING_TIMEOUT"
            diag.lease_token = None
            diag.lease_expires_at = None
            diag.updated_at = now

            # Emit single DiagnosisFinished v1
            finished_event_id = uuid.uuid4()
            finished_envelope = {
                "event_id": str(finished_event_id),
                "event_type": "DiagnosisFinished",
                "schema_version": 1,
                "occurred_at": format_utc_iso(now),
                "correlation_id": str(diag.correlation_id or uuid.uuid4()),
                "payload": {
                    "diagnosis_id": str(diag.id),
                    "owner_id": str(diag.owner_id),
                    "final_status": "FALLIDO",
                },
            }

            val_ok, val_err = validate_diagnosis_finished_v1(finished_envelope)
            if not val_ok:
                raise RuntimeError(f"Generated DiagnosisFinished failed validation: {val_err}")

            outbox = DiagnosisOutbox(
                event_id=finished_event_id,
                event_type="DiagnosisFinished",
                schema_version=1,
                routing_key="diagnosis.finished.v1",
                envelope=finished_envelope,
                diagnosis_id=diag.id,
                attempt_number=1,
                created_at=now,
                available_at=now,
            )
            session.add(outbox)

            record_audit_log(
                session=session,
                actor_id=SYSTEM_ACTOR_ID,
                action="RECOVERY_PROCESSING_TIMEOUT",
                target_type="diagnosis",
                correlation_id=diag.correlation_id or finished_event_id,
                target_id=str(diag.id),
                details={
                    "attempt_count": diag.attempt_count,
                    "budget_exhausted": budget_exhausted,
                    "deadline_reached": deadline_reached,
                },
            )

            actions_taken.append({
                "diagnosis_id": diag.id,
                "action": "TIMED_OUT",
                "reason": "budget_exhausted" if budget_exhausted else "deadline_reached",
            })

        else:
            # 1. Enforce minimum recovery wait time after expiration
            wait_seconds = policy.get_recovery_wait_seconds(diag.attempt_count)
            min_recovery_time = lease_exp + timedelta(seconds=wait_seconds)
            if now < min_recovery_time:
                # Has not satisfied minimum post-expiry wait; skip this pass
                continue

            # 2. Check if a recovery signal was already emitted for this generation
            if diag.recovery_signaled_at is not None:
                sig_at = ensure_utc(diag.recovery_signaled_at)
                if sig_at is not None and sig_at >= lease_exp:
                    # Already signaled for this expired lease; skip
                    continue

            # Emit new generation DiagnosisRequested v2 signal
            diag.recovery_signaled_at = now
            diag.updated_at = now

            req_event_id = uuid.uuid4()
            next_attempt_number = diag.attempt_count + 1
            req_envelope = {
                "event_id": str(req_event_id),
                "event_type": "DiagnosisRequested",
                "schema_version": 2,
                "occurred_at": format_utc_iso(now),
                "correlation_id": str(diag.correlation_id or uuid.uuid4()),
                "payload": {
                    "diagnosis_id": str(diag.id),
                    "owner_id": str(diag.owner_id),
                    "object_key": diag.object_key,
                },
            }

            outbox = DiagnosisOutbox(
                event_id=req_event_id,
                event_type="DiagnosisRequested",
                schema_version=2,
                routing_key="diagnosis.requested.v2",
                envelope=req_envelope,
                diagnosis_id=diag.id,
                attempt_number=next_attempt_number,
                created_at=now,
                available_at=now,
            )
            session.add(outbox)

            record_audit_log(
                session=session,
                actor_id=SYSTEM_ACTOR_ID,
                action="RECOVERY_SIGNAL_EMITTED",
                target_type="diagnosis",
                correlation_id=diag.correlation_id or req_event_id,
                target_id=str(diag.id),
                details={
                    "current_attempt": diag.attempt_count,
                    "next_attempt_number": next_attempt_number,
                },
            )

            actions_taken.append({
                "diagnosis_id": diag.id,
                "action": "SIGNAL_EMITTED",
                "attempt_number": next_attempt_number,
            })

    # Keep all selected row locks until every transition and its outbox are durable.
    session.commit()
    return actions_taken
