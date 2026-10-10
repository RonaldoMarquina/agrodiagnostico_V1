"""Application service for internal worker diagnosis operations.

Endpoints supported:
- POST /internal/diagnoses/{id}/claim (atomic claim and lease owner derivation)
- POST /internal/diagnoses/{id}/lease/renew (fence-checked lease renewal)
- GET /internal/diagnoses/{id}/image (private byte delivery to verified worker)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.models import Diagnosis
from app.infrastructure.cursor import format_utc_iso
from app.infrastructure.internal_auth import InternalServiceIdentity
from app.infrastructure.lease_config import LeasePolicy, get_lease_policy


def get_db_now(db: Session) -> datetime:
    """Retrieve authoritative clock timestamp from database server."""
    clock = func.clock_timestamp() if db.bind.dialect.name == "postgresql" else func.now()
    now_val = db.execute(select(clock)).scalar_one()
    return ensure_utc(now_val)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware UTC for accurate comparisons."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def claim_diagnosis(
    db: Session,
    identity: InternalServiceIdentity,
    diagnosis_id: uuid.UUID,
    policy: Optional[LeasePolicy] = None,
) -> dict:
    """Atomics claim of diagnosis work by an authenticated AI worker instance.

    Transitions PENDIENTE -> PROCESANDO with new lease token, or recovers
    an expired PROCESANDO lease if attempt budget and processing deadline allow.
    """
    if policy is None:
        policy = get_lease_policy()

    # Lock row exclusively for update
    stmt = select(Diagnosis).where(Diagnosis.id == diagnosis_id).with_for_update()
    diag = db.execute(stmt).scalar_one_or_none()

    if diag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )

    # Terminal states can never be claimed
    if diag.status in ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO", "CANCELADO"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DIAGNOSIS_NOT_CLAIMABLE",
                "details": [{"field": "status", "code": "TERMINAL"}],
                "message": "La operación entra en conflicto con el estado actual o lease vigente.",
            },
        )

    now = get_db_now(db)

    if diag.status == "PENDIENTE":
        new_token = uuid.uuid4()
        diag.status = "PROCESANDO"
        diag.attempt_count = 1
        diag.lease_owner = identity.instance_id
        diag.lease_token = new_token
        diag.lease_expires_at = now + timedelta(seconds=policy.lease_duration_seconds)
        diag.processing_deadline_at = now + timedelta(seconds=policy.processing_deadline_seconds)
        diag.updated_at = now
        db.commit()
        return {
            "lease_owner": diag.lease_owner,
            "lease_token": str(diag.lease_token),
            "expires_at": format_utc_iso(diag.lease_expires_at),
        }

    if diag.status == "PROCESANDO":
        diag_expires = ensure_utc(diag.lease_expires_at)
        diag_deadline = ensure_utc(diag.processing_deadline_at)

        # Check if current lease is still active
        if diag_expires is not None and now < diag_expires:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DIAGNOSIS_NOT_CLAIMABLE",
                    "message": "La operación entra en conflicto con el estado actual o lease vigente.",
                },
            )

        # Budget exhaustion
        if diag.attempt_count >= policy.max_attempt_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DIAGNOSIS_NOT_CLAIMABLE",
                    "message": "La operación entra en conflicto con el estado actual o lease vigente.",
                },
            )

        # Processing deadline reached
        if diag_deadline is not None and now >= diag_deadline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DIAGNOSIS_NOT_CLAIMABLE",
                    "message": "La operación entra en conflicto con el estado actual o lease vigente.",
                },
            )

        # Minimum wait window between attempts
        wait_seconds = policy.get_recovery_wait_seconds(diag.attempt_count)
        if diag_expires is not None and now < diag_expires + timedelta(seconds=wait_seconds):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "DIAGNOSIS_NOT_CLAIMABLE",
                    "message": "La operación entra en conflicto con el estado actual o lease vigente.",
                },
            )

        # Grant recovery lease
        new_token = uuid.uuid4()
        diag.attempt_count += 1
        diag.lease_owner = identity.instance_id
        diag.lease_token = new_token
        nominal_expires = now + timedelta(seconds=policy.lease_duration_seconds)
        if diag_deadline is not None:
            diag.lease_expires_at = min(nominal_expires, diag_deadline)
        else:
            diag.lease_expires_at = nominal_expires
        diag.updated_at = now
        db.commit()
        return {
            "lease_owner": diag.lease_owner,
            "lease_token": str(diag.lease_token),
            "expires_at": format_utc_iso(diag.lease_expires_at),
        }

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "DIAGNOSIS_NOT_CLAIMABLE",
            "message": "La operación entra en conflicto con el estado actual o lease vigente.",
        },
    )


def renew_diagnosis_lease(
    db: Session,
    identity: InternalServiceIdentity,
    diagnosis_id: uuid.UUID,
    lease_token: uuid.UUID,
    policy: Optional[LeasePolicy] = None,
) -> dict:
    """Renews an active work lease for the claiming worker instance."""
    if policy is None:
        policy = get_lease_policy()

    stmt = select(Diagnosis).where(Diagnosis.id == diagnosis_id).with_for_update()
    diag = db.execute(stmt).scalar_one_or_none()

    if diag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )

    if diag.status != "PROCESANDO":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    if diag.lease_owner != identity.instance_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    if diag.lease_token != lease_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    now = get_db_now(db)
    diag_expires = ensure_utc(diag.lease_expires_at)
    diag_deadline = ensure_utc(diag.processing_deadline_at)

    # now >= lease_expires_at is already stale
    if diag_expires is None or now >= diag_expires:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    # Deadline cap
    if diag_deadline is not None and now >= diag_deadline:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    nominal_expires = now + timedelta(seconds=policy.lease_duration_seconds)
    if diag_deadline is not None:
        new_expires = min(nominal_expires, diag_deadline)
    else:
        new_expires = nominal_expires

    diag.lease_expires_at = new_expires
    diag.updated_at = now
    db.commit()
    return {
        "lease_owner": diag.lease_owner,
        "lease_token": str(diag.lease_token),
        "expires_at": format_utc_iso(diag.lease_expires_at),
    }


def get_internal_diagnosis_image(
    db: Session,
    identity: InternalServiceIdentity,
    diagnosis_id: uuid.UUID,
    lease_token: uuid.UUID,
    storage,
) -> Tuple[bytes, str]:
    """Retrieves private raw image bytes for an active, authorized worker lease."""
    stmt = select(Diagnosis).where(Diagnosis.id == diagnosis_id)
    diag = db.execute(stmt).scalar_one_or_none()

    if diag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )

    if diag.status != "PROCESANDO":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    if diag.lease_owner != identity.instance_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    if diag.lease_token != lease_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    now = get_db_now(db)
    diag_expires = ensure_utc(diag.lease_expires_at)
    if diag_expires is None or now >= diag_expires:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "STALE_LEASE", "message": "Lease obsoleto o no renovable."},
        )

    try:
        obj = storage.get_object(diag.object_key)
        if isinstance(obj, tuple):
            image_bytes = obj[0]
        else:
            image_bytes = obj
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "STORAGE_UNAVAILABLE", "message": "Almacenamiento no disponible."},
        ) from exc

    return image_bytes, diag.image_content_type
