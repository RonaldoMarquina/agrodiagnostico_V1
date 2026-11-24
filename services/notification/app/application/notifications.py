"""Application services for Notification listing, idempotent read, and preferences (ADR-0014)."""
from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.models import Notification, NotificationPreference
from app.infrastructure.cursor import (
    CURSOR_PURPOSE_USER_NOTIFICATIONS,
    decode_cursor,
    encode_cursor,
    format_utc_iso,
)
from app.infrastructure.security import Principal


class NotificationPreferencesPatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email_enabled: StrictBool


def _serialize_notification(notif: Notification) -> dict:
    return {
        "id": str(notif.id),
        "diagnosis_id": str(notif.diagnosis_id),
        "final_status": notif.final_status,
        "created_at": format_utc_iso(notif.created_at),
        "read_at": format_utc_iso(notif.read_at) if notif.read_at is not None else None,
    }


def list_user_notifications(
    db: Session,
    principal: Principal,
    limit: Optional[int] = 20,
    cursor: Optional[str] = None,
) -> dict:
    """List authenticated user's notifications with keyset pagination (created_at DESC, id DESC)."""
    if limit is None:
        limit = 20
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_PAGINATION",
                "message": "El parámetro limit debe estar entre 1 y 100.",
            },
        )

    stmt = select(Notification).where(Notification.owner_id == principal.id)

    if cursor is not None:
        cursor_dt, cursor_id = decode_cursor(
            cursor_str=cursor,
            expected_principal_id=principal.id,
            expected_purpose=CURSOR_PURPOSE_USER_NOTIFICATIONS,
        )
        dialect_name = db.bind.dialect.name if db.bind is not None else ""
        compare_dt = cursor_dt.replace(tzinfo=None) if dialect_name == "sqlite" else cursor_dt
        stmt = stmt.where(
            or_(
                Notification.created_at < compare_dt,
                and_(
                    Notification.created_at == compare_dt,
                    Notification.id < cursor_id,
                ),
            )
        )

    stmt = stmt.order_by(desc(Notification.created_at), desc(Notification.id)).limit(limit + 1)
    rows = db.execute(stmt).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_serialize_notification(n) for n in page_rows]

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            created_at=last.created_at,
            notification_id=last.id,
            principal_id=principal.id,
            purpose=CURSOR_PURPOSE_USER_NOTIFICATIONS,
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


def mark_notification_read(
    db: Session,
    principal: Principal,
    notification_id: uuid.UUID,
) -> dict:
    """Idempotently mark an own notification as read, preserving the original read_at timestamp."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.owner_id == principal.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.execute(stmt)
    db.commit()

    notif = db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.owner_id == principal.id,
        )
    ).scalar_one_or_none()

    if notif is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "Recurso no encontrado.",
            },
        )

    return _serialize_notification(notif)


def mark_all_notifications_read(
    db: Session,
    principal: Principal,
) -> dict:
    """Idempotently mark all unread notifications of the authenticated owner as read (ADR-0016)."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(Notification)
        .where(
            Notification.owner_id == principal.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    result = db.execute(stmt)
    db.commit()
    return {"updated_count": int(result.rowcount or 0)}


def get_unread_notifications_count(
    db: Session,
    principal: Principal,
) -> dict:
    """Return exact count of unread notifications belonging to the authenticated owner (ADR-0016)."""
    count = db.execute(
        select(func.count(Notification.id)).where(
            Notification.owner_id == principal.id,
            Notification.read_at.is_(None),
        )
    ).scalar_one()
    return {"unread_count": int(count or 0)}


def get_user_preferences(
    db: Session,
    principal: Principal,
) -> dict:
    """Return effective email notification preference (default opt-in false, ADR-0014)."""
    pref = db.get(NotificationPreference, principal.id)
    if pref is None:
        return {"email_enabled": False}
    return {"email_enabled": bool(pref.email_enabled)}


def patch_user_preferences(
    db: Session,
    principal: Principal,
    payload: NotificationPreferencesPatchInput,
) -> dict:
    """Create or update own email preference."""
    now = datetime.now(timezone.utc)
    pref = db.get(NotificationPreference, principal.id)
    if pref is None:
        pref = NotificationPreference(
            owner_id=principal.id,
            email_enabled=bool(payload.email_enabled),
            created_at=now,
            updated_at=now,
        )
        db.add(pref)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            pref = db.get(NotificationPreference, principal.id)
            if pref is None:
                raise
            pref.email_enabled = bool(payload.email_enabled)
            pref.updated_at = now
            db.commit()
    else:
        pref.email_enabled = bool(payload.email_enabled)
        pref.updated_at = now
        db.commit()

    db.refresh(pref)
    return {"email_enabled": bool(pref.email_enabled)}
