"""Operational Replay and Explicit Reconstruction service for Diagnosis events.

Architectural guarantees (ADR-0008 D5, Tasks 7.2):
- Requires operator context: actor and reason are mandatory and audited before scheduling.
- Immutable envelope: preserves exact event_id and envelope JSON for valid events;
  never alters payload while retaining event_id.
- Terminal replay idempotency: replaying an event for a diagnosis in terminal status
  (COMPLETADO, NO_CONCLUYENTE, FALLIDO, CANCELADO) does NOT alter the terminal status
  nor emit duplicate DiagnosisFinished events.
- Explicit reconstruction of invalid quarantined messages: prohibits blind replay
  of corrupted bytes; constructs a brand new valid DiagnosisRequested v2 with a
  fresh event_id for PENDIENTE diagnoses, validates against JSON Schema, and audits.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import (
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisOutbox,
    DiagnosisQuarantineMessage,
)
from app.infrastructure.event_validation import validate_diagnosis_requested
from app.infrastructure.quarantine import record_audit_log

logger = logging.getLogger("diagnosis.replay")

SYSTEM_OPERATOR_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


@dataclass
class ReplayResult:
    action: str  # "REPLAY" or "RECONSTRUCT"
    status: str  # "SCHEDULED", "DRY_RUN", "SKIPPED_TERMINAL", "FAILED"
    event_id: uuid.UUID
    diagnosis_id: Optional[uuid.UUID]
    details: Dict[str, Any]


def replay_outbox_event(
    db: Session,
    actor: str,
    reason: str,
    event_id: Optional[uuid.UUID] = None,
    diagnosis_id: Optional[uuid.UUID] = None,
    apply: bool = False,
) -> ReplayResult:
    """Schedules operational replay of an existing valid outbox event.
    
    Preserves event_id and envelope strictly. Enforces actor and reason context.
    """
    if not actor or not actor.strip():
        raise ValueError("Operator context required: --actor must be specified")
    if not reason or not reason.strip():
        raise ValueError("Operator context required: --reason must be specified")

    if event_id is None and diagnosis_id is None:
        raise ValueError("Either event_id or diagnosis_id must be provided")

    stmt = select(DiagnosisOutbox)
    if event_id is not None:
        stmt = stmt.where(DiagnosisOutbox.event_id == event_id)
    elif diagnosis_id is not None:
        stmt = stmt.where(DiagnosisOutbox.diagnosis_id == diagnosis_id).order_by(
            DiagnosisOutbox.created_at.desc()
        )

    outbox_event = db.execute(stmt).scalars().first()
    if outbox_event is None:
        raise ValueError(
            f"No outbox event found for event_id={event_id} diagnosis_id={diagnosis_id}"
        )

    # Check diagnosis status if attached
    diag = None
    if outbox_event.diagnosis_id:
        diag = db.execute(
            select(Diagnosis).where(Diagnosis.id == outbox_event.diagnosis_id)
        ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    target_diag_id = outbox_event.diagnosis_id
    corr_id = uuid.uuid4()
    if isinstance(outbox_event.envelope, dict) and "correlation_id" in outbox_event.envelope:
        try:
            corr_id = uuid.UUID(outbox_event.envelope["correlation_id"])
        except Exception:
            pass

    # Audit log recording before mutation
    record_audit_log(
        session=db,
        actor_id=SYSTEM_OPERATOR_ACTOR_ID,
        action="OPERATIONAL_REPLAY",
        target_type="diagnosis_outbox",
        correlation_id=corr_id,
        target_id=str(outbox_event.event_id),
        details={
            "actor": actor,
            "reason": reason,
            "event_type": outbox_event.event_type,
            "diagnosis_id": str(target_diag_id) if target_diag_id else None,
            "diagnosis_status": diag.status if diag else None,
            "apply": apply,
        },
    )

    # Terminal replay check
    if diag and diag.status in ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO", "CANCELADO"):
        # Terminal state cannot be altered, nor can duplicate Finished be emitted
        if apply:
            db.commit()
        return ReplayResult(
            action="REPLAY",
            status="SKIPPED_TERMINAL",
            event_id=outbox_event.event_id,
            diagnosis_id=target_diag_id,
            details={
                "message": f"Diagnosis is in terminal status {diag.status}; state preserved without modifications",
                "diagnosis_status": diag.status,
            },
        )

    if apply:
        # Reset outbox delivery status while keeping event_id and envelope strictly immutable
        outbox_event.sent_at = None
        outbox_event.claim_token = None
        outbox_event.claim_expires_at = None
        outbox_event.available_at = now
        db.commit()
        status_str = "SCHEDULED"
    else:
        db.rollback()
        status_str = "DRY_RUN"

    return ReplayResult(
        action="REPLAY",
        status=status_str,
        event_id=outbox_event.event_id,
        diagnosis_id=target_diag_id,
        details={
            "event_type": outbox_event.event_type,
            "routing_key": outbox_event.routing_key,
            "envelope_preserved": True,
        },
    )


def reconstruct_quarantined_message(
    db: Session,
    actor: str,
    reason: str,
    quarantine_id: uuid.UUID,
    apply: bool = False,
) -> ReplayResult:
    """Explicitly reconstructs an invalid quarantined message without blind replay.
    
    Only PENDIENTE diagnoses can be reconstructed. Generates a fresh DiagnosisRequested v2
    with a new event_id and validates against schema before persisting.
    """
    if not actor or not actor.strip():
        raise ValueError("Operator context required: --actor must be specified")
    if not reason or not reason.strip():
        raise ValueError("Operator context required: --reason must be specified")

    q_entry = db.get(DiagnosisQuarantineMessage, quarantine_id)
    if q_entry is None:
        raise ValueError(f"Quarantine entry not found: {quarantine_id}")

    if not q_entry.diagnosis_id:
        raise ValueError(
            f"Quarantine entry {quarantine_id} does not have an associated diagnosis_id to reconstruct"
        )

    diag = db.execute(
        select(Diagnosis).where(Diagnosis.id == q_entry.diagnosis_id)
    ).scalar_one_or_none()
    if diag is None:
        raise ValueError(f"Diagnosis not found: {q_entry.diagnosis_id}")

    if diag.status != "PENDIENTE":
        return ReplayResult(
            action="RECONSTRUCT",
            status="SKIPPED_NOT_PENDING",
            event_id=uuid.UUID(int=0),
            diagnosis_id=diag.id,
            details={
                "message": f"Diagnosis is in status {diag.status}; only PENDIENTE can be reconstructed",
                "diagnosis_status": diag.status,
            },
        )

    # Generate a brand new valid DiagnosisRequested v2
    new_event_id = uuid.uuid4()
    corr_id = diag.correlation_id or uuid.uuid4()
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    envelope = {
        "event_id": str(new_event_id),
        "event_type": "DiagnosisRequested",
        "schema_version": 2,
        "occurred_at": now_str,
        "correlation_id": str(corr_id),
        "payload": {
            "diagnosis_id": str(diag.id),
            "owner_id": str(diag.owner_id),
            "object_key": diag.object_key,
        },
    }

    # Validate against JSON schema
    is_valid, err_msg, _ = validate_diagnosis_requested(envelope)
    if not is_valid:
        raise RuntimeError(f"Reconstructed event failed schema validation: {err_msg}")

    # Audit reconstruction
    record_audit_log(
        session=db,
        actor_id=SYSTEM_OPERATOR_ACTOR_ID,
        action="EXPLICIT_RECONSTRUCTION",
        target_type="diagnosis_quarantine",
        correlation_id=corr_id,
        target_id=str(quarantine_id),
        details={
            "actor": actor,
            "reason": reason,
            "quarantine_id": str(quarantine_id),
            "original_error_reason": q_entry.error_reason,
            "new_event_id": str(new_event_id),
            "diagnosis_id": str(diag.id),
            "apply": apply,
        },
    )

    if apply:
        # Insert new outbox event
        outbox_event = DiagnosisOutbox(
            event_id=new_event_id,
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope=envelope,
            diagnosis_id=diag.id,
            attempt_number=1,
            created_at=now,
            available_at=now,
        )
        db.add(outbox_event)
        db.commit()
        status_str = "SCHEDULED"
    else:
        db.rollback()
        status_str = "DRY_RUN"

    return ReplayResult(
        action="RECONSTRUCT",
        status=status_str,
        event_id=new_event_id,
        diagnosis_id=diag.id,
        details={
            "new_event_id": str(new_event_id),
            "quarantine_id": str(quarantine_id),
            "routing_key": "diagnosis.requested.v2",
        },
    )

