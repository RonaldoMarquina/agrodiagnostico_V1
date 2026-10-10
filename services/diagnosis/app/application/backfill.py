"""Backfill application service for legacy PENDIENTE diagnoses without outbox events.

Guarantees:
- Safe dry-run by default (mutations only when apply=True).
- Batch processing and optional ID list targeting.
- Row-level locking to avoid race conditions with concurrent cancellation or claims.
- Generates recovery correlation ID when historically absent without modifying user request.
- Preserves existing object_key without moving or renaming S3 objects.
- Includes tombstones (deleted_at IS NOT NULL) because deletion does not cancel diagnoses.
- Records operational audit log for every backfilled diagnosis.
- Double execution is strictly idempotent (zero duplicate outbox records).
- Fails closed if running with real production data inside simulation test profile.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Diagnosis, DiagnosisAuditLog, DiagnosisOutbox
from app.infrastructure.cursor import format_utc_iso

logger = logging.getLogger("diagnosis_backfill")

SYSTEM_OPERATOR_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


@dataclass
class BackfillResult:
    scanned: int
    candidates: int
    tombstones: int
    applied: int
    skipped_not_pending: int
    details: List[Dict]


def run_backfill(
    db: Session,
    apply: bool = False,
    ids: Optional[List[uuid.UUID]] = None,
    batch_size: int = 50,
) -> BackfillResult:
    """Execute backfill in dry-run (default) or apply mode.
    
    Invariants:
    1. Only targets status='PENDIENTE'.
    2. Verifies that no DiagnosisRequested event exists in DiagnosisOutbox for that diagnosis.
    3. Respects tombstones (flags them in details).
    4. Records DiagnosisAuditLog in apply mode.
    """
    # Guard: never run on real data inside simulation profile
    app_env = os.environ.get("APP_ENV", "development")
    is_simulation = os.environ.get("ASYNC_SIMULATION_PROFILE", "false").lower() == "true"
    if is_simulation and app_env != "test":
        raise RuntimeError("Backfill cannot run on real data in simulation profile")

    # 1. Query PENDIENTE diagnoses
    stmt = (
        select(Diagnosis)
        .where(Diagnosis.status == "PENDIENTE")
        .order_by(Diagnosis.created_at.asc())
    )

    if ids:
        stmt = stmt.where(Diagnosis.id.in_(ids))

    stmt = stmt.limit(batch_size)

    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    else:
        stmt = stmt.with_for_update()

    diagnoses = db.execute(stmt).scalars().all()

    scanned = len(diagnoses)
    candidates = 0
    tombstones = 0
    applied = 0
    skipped_not_pending = 0
    details = []

    now = datetime.now(timezone.utc)

    for diag in diagnoses:
        # Re-verify status under lock
        if diag.status != "PENDIENTE":
            skipped_not_pending += 1
            continue

        # Check if an initial DiagnosisRequested outbox record already exists
        existing_outbox = db.execute(
            select(DiagnosisOutbox.id).where(
                DiagnosisOutbox.diagnosis_id == diag.id,
                DiagnosisOutbox.event_type == "DiagnosisRequested",
            )
        ).scalar_one_or_none()

        if existing_outbox is not None:
            # Already has outbox event, skip
            continue

        candidates += 1
        is_tombstone = diag.deleted_at is not None
        if is_tombstone:
            tombstones += 1

        # Determine recovery correlation_id
        cid = diag.correlation_id or uuid.uuid4()
        event_id = uuid.uuid4()

        envelope_v2 = {
            "event_id": str(event_id),
            "event_type": "DiagnosisRequested",
            "schema_version": 2,
            "occurred_at": format_utc_iso(now),
            "correlation_id": str(cid),
            "payload": {
                "diagnosis_id": str(diag.id),
                "owner_id": str(diag.owner_id),
                "object_key": diag.object_key,
            },
        }

        item_detail = {
            "diagnosis_id": str(diag.id),
            "is_tombstone": is_tombstone,
            "object_key": diag.object_key,
            "correlation_id": str(cid),
            "event_id": str(event_id),
            "applied": apply,
        }
        details.append(item_detail)

        if apply:
            # Update correlation_id if missing
            if diag.correlation_id is None:
                diag.correlation_id = cid

            # Insert DiagnosisOutbox
            outbox_rec = DiagnosisOutbox(
                id=uuid.uuid4(),
                event_id=event_id,
                event_type="DiagnosisRequested",
                schema_version=2,
                routing_key="diagnosis.requested.v2",
                envelope=envelope_v2,
                diagnosis_id=diag.id,
                attempt_number=1,
                created_at=now,
                available_at=now,
            )
            db.add(outbox_rec)

            # Record operational audit log
            audit_log = DiagnosisAuditLog(
                id=uuid.uuid4(),
                actor_id=SYSTEM_OPERATOR_UUID,
                action="BACKFILL_REQUESTED",
                target_type="diagnosis",
                target_id=str(diag.id),
                correlation_id=cid,
                details={
                    "is_tombstone": is_tombstone,
                    "object_key": diag.object_key,
                    "event_id": str(event_id),
                    "action": "BACKFILL_REQUESTED",
                },
                created_at=now,
            )
            db.add(audit_log)
            applied += 1

    if apply:
        db.commit()
    else:
        db.rollback()

    return BackfillResult(
        scanned=scanned,
        candidates=candidates,
        tombstones=tombstones,
        applied=applied,
        skipped_not_pending=skipped_not_pending,
        details=details,
    )

