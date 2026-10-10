"""Application service for diagnosis creation, idempotency management, and image retrieval."""
import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
import psycopg

from app.domain.image import ValidatedImage
from app.domain.models import (
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisFeedback,
    DiagnosisOutbox,
    IdempotencyKey,
    ImageUploadIntent,
)
from app.infrastructure.cursor import decode_cursor, encode_cursor, format_utc_iso
from app.infrastructure.security import Principal
from app.storage import ObjectNotFoundError, S3StorageAdapter, StorageUnavailableError

logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_REGEX = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def compute_advisory_lock_id(owner_id: uuid.UUID, scope: str, key: str) -> int:
    """Stable signed 64-bit integer for PostgreSQL transaction advisory lock."""
    raw = f"{owner_id}:{scope}:{key}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def create_diagnosis(
    db: Session,
    principal: Principal,
    idempotency_key: str,
    validated_image: ValidatedImage,
    storage: S3StorageAdapter,
    correlation_id: Optional[uuid.UUID] = None,
) -> Diagnosis:
    """Create a diagnosis with advisory locking, idempotency, and durable upload intent protocol."""
    if not IDEMPOTENCY_KEY_REGEX.match(idempotency_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Idempotency-Key inválida o no cumple con el formato contractual."},
        )

    # 1. Non-blocking advisory lock on owner_id/scope/key
    lock_id = compute_advisory_lock_id(principal.id, "diagnosis_create", idempotency_key)
    try:
        if db.bind.dialect.name == "postgresql":
            locked = db.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": lock_id},
            ).scalar()
            if not locked:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_IN_PROGRESS",
                        "message": "Operación concurrente en curso para esta clave de idempotencia.",
                    },
                )

        # 2. Check existing idempotency key
        existing_key = db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.owner_id == principal.id,
                IdempotencyKey.scope == "diagnosis_create",
                IdempotencyKey.key == idempotency_key,
            )
        ).scalar_one_or_none()
    except (SQLAlchemyError, psycopg.Error, OperationalError) as exc:
        logger.error("Database unavailable during advisory lock/idempotency check: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PERSISTENCE_UNAVAILABLE",
                "message": "Persistencia temporalmente no disponible.",
            },
        )

    now = datetime.now(timezone.utc)

    if existing_key is not None:
        diag = db.get(Diagnosis, existing_key.diagnosis_id)

        # Check tombstone during retention
        if now < _ensure_utc(existing_key.expires_at):
            if diag is not None and diag.deleted_at is not None:

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_RESOURCE_DELETED",
                        "message": "El recurso asociado a esta clave de idempotencia fue eliminado.",
                    },
                )

            if existing_key.fingerprint == validated_image.sha256:
                # Replay identical
                return diag
            else:

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "La clave de idempotencia ya fue utilizada con otro contenido.",
                    },
                )
        else:
            # now >= existing_key.expires_at: expired, allow new diagnosis generation
            is_replacement = True
    else:
        is_replacement = False

    new_diag_id = uuid.uuid4()
    object_key = f"diagnoses/{new_diag_id}/original{validated_image.extension}"

    # 3. Create durable intent in separate committed transaction
    try:
        engine = db.get_bind()
        with Session(engine) as intent_session:
            intent = ImageUploadIntent(
                diagnosis_id=new_diag_id,
                object_key=object_key,
                owner_id=principal.id,
                created_at=datetime.now(timezone.utc),
            )
            intent_session.add(intent)
            intent_session.commit()

        # Lock the intent row in main transaction
        intent_stmt = select(ImageUploadIntent).where(ImageUploadIntent.diagnosis_id == new_diag_id)
        if db.bind.dialect.name == "postgresql":
            intent_stmt = intent_stmt.with_for_update()
        locked_intent = db.execute(intent_stmt).scalar_one_or_none()
    except (SQLAlchemyError, psycopg.Error, OperationalError) as exc:
        logger.error("Database unavailable during intent creation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PERSISTENCE_UNAVAILABLE",
                "message": "Persistencia temporalmente no disponible.",
            },
        )
    if locked_intent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PERSISTENCE_UNAVAILABLE",
                "message": "No se pudo asegurar la intención de carga.",
            },
        )

    # 4. Upload to S3
    try:
        storage.put_object(
            key=object_key,
            body=validated_image.data,
            content_type=validated_image.content_type,
        )
    except StorageUnavailableError:
        db.rollback()
        # Compensation: verify no diagnosis references object_key before deleting
        try:
            with Session(engine) as check_session:
                ref = check_session.execute(
                    select(Diagnosis.id).where(Diagnosis.object_key == object_key)
                ).scalar_one_or_none()
                if not ref:
                    storage.delete_object(object_key)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "STORAGE_UNAVAILABLE",
                "message": "Almacenamiento temporalmente no disponible.",
            },
        )

    # 5. Insert diagnosis, idempotency key and delete intent in main transaction commit
    try:
        cid = correlation_id or uuid.uuid4()
        now = datetime.now(timezone.utc)
        new_diag = Diagnosis(
            id=new_diag_id,
            owner_id=principal.id,
            status="PENDIENTE",
            object_key=object_key,
            image_sha256=validated_image.sha256,
            image_content_type=validated_image.content_type,
            image_size_bytes=validated_image.size_bytes,
            image_width=validated_image.width,
            image_height=validated_image.height,
            correlation_id=cid,
            created_at=now,
            updated_at=now,
        )
        db.add(new_diag)

        expires_at = now + timedelta(seconds=86400)
        if is_replacement and existing_key is not None:
            db.delete(existing_key)
            db.flush()

        idemp_record = IdempotencyKey(
            owner_id=principal.id,
            scope="diagnosis_create",
            key=idempotency_key,
            fingerprint=validated_image.sha256,
            diagnosis_id=new_diag_id,
            created_at=now,
            expires_at=expires_at,
        )
        db.add(idemp_record)

        event_id = uuid.uuid4()
        envelope_v2 = {
            "event_id": str(event_id),
            "event_type": "DiagnosisRequested",
            "schema_version": 2,
            "occurred_at": format_utc_iso(now),
            "correlation_id": str(cid),
            "payload": {
                "diagnosis_id": str(new_diag_id),
                "owner_id": str(principal.id),
                "object_key": object_key,
            },
        }

        outbox_event = DiagnosisOutbox(
            id=uuid.uuid4(),
            event_id=event_id,
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope=envelope_v2,
            diagnosis_id=new_diag_id,
            attempt_number=1,
            created_at=now,
            available_at=now,
        )
        db.add(outbox_event)

        db.delete(locked_intent)
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            with Session(engine) as check_session:
                ref = check_session.execute(
                    select(Diagnosis.id).where(Diagnosis.object_key == object_key)
                ).scalar_one_or_none()
                if not ref:
                    storage.delete_object(object_key)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "PERSISTENCE_UNAVAILABLE",
                "message": "Persistencia temporalmente no disponible.",
            },
        )

    return new_diag


def get_diagnosis_image(
    db: Session,
    principal: Principal,
    diagnosis_id: uuid.UUID,
    storage: S3StorageAdapter,
) -> Tuple[bytes, str]:
    """Retrieve private original image bytes and Content-Type with ownership and tombstone enforcement."""
    diag = db.get(Diagnosis, diagnosis_id)
    if diag is None or diag.owner_id != principal.id or diag.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )

    try:
        data, content_type = storage.get_object(diag.object_key)
        return data, diag.image_content_type or content_type
    except ObjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )
    except StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "STORAGE_UNAVAILABLE", "message": "Almacenamiento temporalmente no disponible."},
        )


def cancel_diagnosis(
    db: Session,
    principal: Principal,
    diagnosis_id: uuid.UUID,
) -> dict:
    """Atomic conditional update of non-deleted PENDIENTE diagnosis to CANCELADO.

    Returns dict matching DiagnosisCancelled on success (200).
    Returns 404 for foreign, nonexistent, or already tombstoned diagnosis.
    Returns 409 for non-cancelable statuses (PROCESANDO, COMPLETADO, NO_CONCLUYENTE, FALLIDO, CANCELADO).
    Never emits DiagnosisFinished.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        update(Diagnosis)
        .where(
            Diagnosis.id == diagnosis_id,
            Diagnosis.owner_id == principal.id,
            Diagnosis.deleted_at.is_(None),
            Diagnosis.status == "PENDIENTE",
        )
        .values(
            status="CANCELADO",
            updated_at=now,
        )
    )
    result = db.execute(stmt)
    if result.rowcount == 1:
        db.commit()
        diag = db.get(Diagnosis, diagnosis_id)
        return {
            "id": str(diag.id),
            "status": "CANCELADO",
            "created_at": format_utc_iso(diag.created_at),
            "updated_at": format_utc_iso(diag.updated_at),
        }

    # Conditional update failed; determine reason
    diag = db.get(Diagnosis, diagnosis_id)
    if diag is None or diag.owner_id != principal.id or diag.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "DIAGNOSIS_NOT_CANCELABLE",
            "message": "El diagnóstico no se encuentra en estado cancelable.",
        },
    )


def delete_diagnosis(
    db: Session,
    principal: Principal,
    diagnosis_id: uuid.UUID,
) -> None:
    """Soft delete owned diagnosis idempotently.

    Returns None (for 204 No Content).
    Returns generic 404 for foreign or nonexistent diagnosis.
    Does not delete S3 object and preserves current status.
    """
    stmt = select(Diagnosis).where(Diagnosis.id == diagnosis_id).with_for_update()
    diag = db.execute(stmt).scalar_one_or_none()
    if diag is None or diag.owner_id != principal.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )

    if diag.deleted_at is not None:
        # Idempotent repeat: already deleted
        return

    now = datetime.now(timezone.utc)
    diag.deleted_at = now
    diag.updated_at = now
    db.commit()


def get_diagnosis_detail(
    db: Session,
    principal: Principal,
    diagnosis_id: uuid.UUID,
) -> dict:
    """Retrieve full diagnosis detail matching contractual variant schema.

    Enforces ownership and hides tombstones (404).
    """
    diag = db.get(Diagnosis, diagnosis_id)
    if diag is None or diag.owner_id != principal.id or diag.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recurso no encontrado."},
        )

    data = {
        "id": str(diag.id),
        "status": diag.status,
        "created_at": format_utc_iso(diag.created_at),
        "updated_at": format_utc_iso(diag.updated_at),
    }

    if diag.status in ("NO_CONCLUYENTE", "FALLIDO"):
        data["reason_code"] = diag.reason_code
    elif diag.status == "COMPLETADO":
        data["result"] = {
            "crop_code": diag.crop_code,
            "class_code": diag.class_code,
            "raw_score": diag.raw_score,
            "model": {
                "model_id": diag.model_id,
                "model_version": diag.model_version,
                "dataset_version": diag.dataset_version,
            },
            "recommendation": {
                "catalog_version": diag.catalog_version,
                "recommendation_id": str(diag.recommendation_id) if diag.recommendation_id else None,
                "text": diag.recommendation_text,
            },
        }

    return data


def list_user_diagnoses(
    db: Session,
    principal: Principal,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> dict:
    """Keyset pagination for user diagnoses with HMAC-SHA256 authenticated cursors.

    Ordered strictly by (created_at DESC, id DESC).
    """
    if limit is None or limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PAGINATION", "message": "El parámetro limit debe estar entre 1 y 100."},
        )

    stmt = select(Diagnosis).where(
        Diagnosis.owner_id == principal.id,
        Diagnosis.deleted_at.is_(None),
    )

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(
            cursor_str=cursor,
            expected_principal_id=principal.id,
            expected_purpose="user_diagnoses",
        )
        stmt = stmt.where(
            or_(
                Diagnosis.created_at < cursor_created_at,
                and_(Diagnosis.created_at == cursor_created_at, Diagnosis.id < cursor_id),
            )
        )

    stmt = stmt.order_by(Diagnosis.created_at.desc(), Diagnosis.id.desc()).limit(limit + 1)
    records = db.scalars(stmt).all()

    if len(records) > limit:
        page_items = records[:limit]
        last_item = page_items[-1]
        next_cursor = encode_cursor(
            created_at=last_item.created_at,
            diagnosis_id=last_item.id,
            principal_id=principal.id,
            purpose="user_diagnoses",
        )
    else:
        page_items = records
        next_cursor = None

    items = [
        {
            "id": str(r.id),
            "status": r.status,
            "created_at": format_utc_iso(r.created_at),
        }
        for r in page_items
    ]

    return {"items": items, "next_cursor": next_cursor}


def list_admin_diagnoses(
    db: Session,
    principal: Principal,
    correlation_id: uuid.UUID,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> dict:
    """Keyset pagination for admin supervision with independent cursor purpose and audit logging.

    Returns only minimal fields, excluding images, object_key, feedback, and Identity data.
    """
    if limit is None or limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_PAGINATION", "message": "El parámetro limit debe estar entre 1 y 100."},
        )

    stmt = select(Diagnosis).where(
        Diagnosis.deleted_at.is_(None),
    )

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(
            cursor_str=cursor,
            expected_principal_id=principal.id,
            expected_purpose="admin_supervision",
        )
        stmt = stmt.where(
            or_(
                Diagnosis.created_at < cursor_created_at,
                and_(Diagnosis.created_at == cursor_created_at, Diagnosis.id < cursor_id),
            )
        )

    stmt = stmt.order_by(Diagnosis.created_at.desc(), Diagnosis.id.desc()).limit(limit + 1)
    records = db.scalars(stmt).all()

    if len(records) > limit:
        page_items = records[:limit]
        last_item = page_items[-1]
        next_cursor = encode_cursor(
            created_at=last_item.created_at,
            diagnosis_id=last_item.id,
            principal_id=principal.id,
            purpose="admin_supervision",
        )
    else:
        page_items = records
        next_cursor = None

    items = [
        {
            "id": str(r.id),
            "owner_id": str(r.owner_id),
            "status": r.status,
            "reason_code": r.reason_code if r.reason_code else None,
            "created_at": format_utc_iso(r.created_at),
            "updated_at": format_utc_iso(r.updated_at),
        }
        for r in page_items
    ]

    audit_entry = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_LIST_DIAGNOSES",
        target_type="diagnosis",
        target_id=None,
        correlation_id=correlation_id,
        details={"limit": limit, "has_cursor": cursor is not None},
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit_entry)
    db.commit()

    return {"items": items, "next_cursor": next_cursor}


class DiagnosisFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    useful: StrictBool
    comment: Optional[str] = Field(default=None, max_length=1000)


def submit_diagnosis_feedback(
    db: Session,
    principal: Principal,
    diagnosis_id: uuid.UUID,
    payload: DiagnosisFeedbackInput,
) -> Tuple[dict, int]:
    """Submit or update feedback for own completed or inconclusive diagnosis.

    Requires:
    - Diagnosis owned by caller.
    - Diagnosis NOT soft-deleted.
    - Status in ('COMPLETADO', 'NO_CONCLUYENTE').
    Otherwise raises 404 or 409.

    Returns:
    (feedback_data_dict, status_code: 201 for initial, 200 for update).
    """
    stmt = select(Diagnosis).where(Diagnosis.id == diagnosis_id).with_for_update()
    diag = db.execute(stmt).scalar_one_or_none()

    if diag is None or diag.owner_id != principal.id or diag.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Diagnóstico no encontrado, ajeno o borrado."},
        )

    if diag.status not in ("COMPLETADO", "NO_CONCLUYENTE"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FEEDBACK_NOT_ALLOWED",
                "message": "Feedback solo permitido en estados COMPLETADO o NO_CONCLUYENTE.",
            },
        )

    fb_stmt = select(DiagnosisFeedback).where(DiagnosisFeedback.diagnosis_id == diagnosis_id).with_for_update()
    existing_fb = db.execute(fb_stmt).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing_fb is not None:
        existing_fb.useful = payload.useful
        existing_fb.comment = payload.comment
        existing_fb.updated_at = now
        db.commit()
        db.refresh(existing_fb)
        return {
            "diagnosis_id": str(existing_fb.diagnosis_id),
            "useful": existing_fb.useful,
            "comment": existing_fb.comment,
            "created_at": format_utc_iso(existing_fb.created_at),
            "updated_at": format_utc_iso(existing_fb.updated_at),
        }, status.HTTP_200_OK

    new_fb = DiagnosisFeedback(
        id=uuid.uuid4(),
        diagnosis_id=diagnosis_id,
        owner_id=principal.id,
        useful=payload.useful,
        comment=payload.comment,
        created_at=now,
        updated_at=now,
    )
    db.add(new_fb)
    try:
        db.commit()
        db.refresh(new_fb)
    except IntegrityError:
        db.rollback()
        retry_stmt = select(DiagnosisFeedback).where(DiagnosisFeedback.diagnosis_id == diagnosis_id).with_for_update()
        retry_fb = db.execute(retry_stmt).scalar_one_or_none()
        if retry_fb is not None:
            retry_fb.useful = payload.useful
            retry_fb.comment = payload.comment
            retry_fb.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(retry_fb)
            return {
                "diagnosis_id": str(retry_fb.diagnosis_id),
                "useful": retry_fb.useful,
                "comment": retry_fb.comment,
                "created_at": format_utc_iso(retry_fb.created_at),
                "updated_at": format_utc_iso(retry_fb.updated_at),
            }, status.HTTP_200_OK
        raise

    return {
        "diagnosis_id": str(new_fb.diagnosis_id),
        "useful": new_fb.useful,
        "comment": new_fb.comment,
        "created_at": format_utc_iso(new_fb.created_at),
        "updated_at": format_utc_iso(new_fb.updated_at),
    }, status.HTTP_201_CREATED

