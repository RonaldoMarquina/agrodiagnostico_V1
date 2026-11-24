"""Administrative account management, user statistics, and security audit endpoints."""
import base64
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import case, desc, func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_admin
from app.api.schemas import (
    AdminBlockUserRequest,
    AdminUserPageResponse,
    AdminUserResponse,
    AdminUserStatsResponse,
    IdentityAuditEntryResponse,
    IdentityAuditPageResponse,
)
from app.domain.models import AuditLog, RefreshSession, User
from app.infrastructure.audit import audit_entry
from app.infrastructure.cursor import (
    CURSOR_PURPOSE_ADMIN_IDENTITY_AUDIT,
    compute_filter_hash,
    decode_cursor,
    encode_cursor,
    format_utc_iso,
    parse_utc_iso,
)
from app.persistence import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_SENSITIVE_DETAIL_KEYS = frozenset({
    "password",
    "password_hash",
    "current_password",
    "new_password",
    "token",
    "access_token",
    "refresh_token",
    "token_hash",
    "csrf_token",
    "secret",
    "private_key",
    "authorization",
    "cookie",
})


def _sanitize_audit_details(details: Any) -> Optional[dict[str, Any]]:
    if not isinstance(details, dict):
        return None
    sanitized: dict[str, Any] = {}
    for k, v in details.items():
        if str(k).lower() in _SENSITIVE_DETAIL_KEYS:
            continue
        if isinstance(v, dict):
            nested = _sanitize_audit_details(v)
            if nested is not None:
                sanitized[str(k)] = nested
        else:
            sanitized[str(k)] = v
    return sanitized


def _normalize_db_dt(db: Session, dt: datetime) -> datetime:
    """Align UTC datetime awareness with the underlying DB dialect (SQLite stores naive UTC)."""
    utc_dt = dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        return utc_dt.replace(tzinfo=None)
    return utc_dt


@router.get(
    "/users/stats",
    status_code=status.HTTP_200_OK,
    response_model=AdminUserStatsResponse,
    operation_id="identity_admin_user_stats",
)
def get_user_stats(
    admin_user: User = Depends(require_admin),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    row = (
        db.query(
            func.count(User.id).label("total"),
            func.coalesce(func.sum(case((User.status == "ACTIVE", 1), else_=0)), 0).label("active"),
            func.coalesce(func.sum(case((User.status == "BLOCKED", 1), else_=0)), 0).label("blocked"),
            func.coalesce(func.sum(case((User.role == "ADMIN", 1), else_=0)), 0).label("admins"),
            func.coalesce(func.sum(case((User.role == "USER", 1), else_=0)), 0).label("users"),
        )
        .one()
    )
    return AdminUserStatsResponse(
        total=int(row.total or 0),
        active=int(row.active or 0),
        blocked=int(row.blocked or 0),
        admins=int(row.admins or 0),
        users=int(row.users or 0),
    )


@router.get(
    "/audit/identity",
    status_code=status.HTTP_200_OK,
    response_model=IdentityAuditPageResponse,
    operation_id="identity_admin_list_audit",
)
def list_identity_audit(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, min_length=1, max_length=2048),
    action: Optional[str] = Query(None, min_length=1, max_length=100),
    actor_id: Optional[UUID] = Query(None),
    target_id: Optional[UUID] = Query(None),
    from_raw: Optional[str] = Query(None, alias="from"),
    to_raw: Optional[str] = Query(None, alias="to"),
    admin_user: User = Depends(require_admin),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    parsed_from: Optional[datetime] = None
    parsed_to: Optional[datetime] = None
    try:
        if from_raw is not None:
            parsed_from = parse_utc_iso(from_raw)
        if to_raw is not None:
            parsed_to = parse_utc_iso(to_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Formato de fecha inválido en parámetros from/to.",
                "correlation_id": str(correlation_id),
            },
        )

    if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "El parámetro from no puede ser posterior a to.",
                "correlation_id": str(correlation_id),
            },
        )

    filter_hash = compute_filter_hash({
        "action": action,
        "actor_id": str(actor_id) if actor_id else None,
        "target_id": str(target_id) if target_id else None,
        "from": format_utc_iso(parsed_from) if parsed_from else None,
        "to": format_utc_iso(parsed_to) if parsed_to else None,
    })

    query = db.query(AuditLog).order_by(desc(AuditLog.created_at), desc(AuditLog.id))

    if action is not None:
        query = query.filter(or_(AuditLog.action == action, AuditLog.event_type == action))
    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)
    if target_id is not None:
        query = query.filter(AuditLog.target_id == target_id)
    if parsed_from is not None:
        query = query.filter(AuditLog.created_at >= _normalize_db_dt(db, parsed_from))
    if parsed_to is not None:
        query = query.filter(AuditLog.created_at <= _normalize_db_dt(db, parsed_to))

    if cursor is not None:
        cursor_dt, cursor_id = decode_cursor(
            cursor,
            expected_principal_id=admin_user.id,
            expected_purpose=CURSOR_PURPOSE_ADMIN_IDENTITY_AUDIT,
            expected_filter_hash=filter_hash,
        )
        db_cursor_dt = _normalize_db_dt(db, cursor_dt)
        query = query.filter(
            (AuditLog.created_at < db_cursor_dt)
            | ((AuditLog.created_at == db_cursor_dt) & (AuditLog.id < cursor_id))
        )

    rows = query.limit(limit + 1).all()
    has_next = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor(
            created_at=last.created_at,
            record_id=last.id,
            principal_id=admin_user.id,
            purpose=CURSOR_PURPOSE_ADMIN_IDENTITY_AUDIT,
            filter_hash=filter_hash,
        )

    return IdentityAuditPageResponse(
        items=[
            IdentityAuditEntryResponse(
                id=row.id,
                action=row.action or row.event_type,
                actor_id=row.actor_id,
                target_id=row.target_id,
                correlation_id=row.correlation_id,
                legacy=bool(row.legacy),
                details=_sanitize_audit_details(row.details),
                created_at=format_utc_iso(row.created_at),
            )
            for row in items
        ],
        next_cursor=next_cursor,
    )


@router.get(
    "/users",
    status_code=status.HTTP_200_OK,
    response_model=AdminUserPageResponse,
    operation_id="identity_admin_list_users",
)
def list_users(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, max_length=2048),
    admin_user: User = Depends(require_admin),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    query = db.query(User).order_by(desc(User.created_at), desc(User.id))

    if cursor:
        try:
            decoded = base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
            cursor_dt_str, cursor_id_str = decoded.split("|")
            cursor_dt = datetime.fromisoformat(cursor_dt_str)
            cursor_id = UUID(cursor_id_str)
            query = query.filter(
                (User.created_at < cursor_dt)
                | ((User.created_at == cursor_dt) & (User.id < cursor_id))
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_CURSOR",
                    "message": "Formato de cursor inválido.",
                    "correlation_id": str(correlation_id),
                },
            )

    users = query.limit(limit + 1).all()
    has_next = len(users) > limit
    items_to_return = users[:limit]

    next_cursor = None
    if has_next:
        last = items_to_return[-1]
        raw_cur = f"{last.created_at.isoformat()}|{str(last.id)}"
        next_cursor = base64.b64encode(raw_cur.encode("utf-8")).decode("utf-8")

    return AdminUserPageResponse(
        items=[
            AdminUserResponse(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                role=u.role,
                status=u.status,
                created_at=u.created_at.isoformat(),
            )
            for u in items_to_return
        ],
        next_cursor=next_cursor,
    )


@router.patch(
    "/users/{id}/block",
    status_code=status.HTTP_200_OK,
    response_model=AdminUserResponse,
    operation_id="identity_admin_block_user",
)
def block_user(
    id: UUID,
    body: Optional[AdminBlockUserRequest] = Body(default=None),
    admin_user: User = Depends(require_admin),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    if id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SELF_BLOCK_NOT_ALLOWED",
                "message": "No puedes bloquear tu propia cuenta de administrador.",
                "correlation_id": str(correlation_id),
            },
        )

    target = db.query(User).filter(User.id == id).with_for_update().first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "Usuario no encontrado.",
                "correlation_id": str(correlation_id),
            },
        )

    now = datetime.now(timezone.utc)
    target.status = "BLOCKED"
    target.updated_at = now

    # Revoke all active refresh sessions immediately in PostgreSQL
    db.query(RefreshSession).filter(
        RefreshSession.user_id == target.id,
        RefreshSession.revoked_at.is_(None),
    ).update({RefreshSession.revoked_at: now}, synchronize_session=False)

    audit_details = {"target_user_id": str(target.id), "target_email": target.email}
    if body is not None:
        audit_details["reason"] = body.reason

    # Insert audit log
    db.add(audit_entry(
        correlation_id=correlation_id,
        user_id=admin_user.id,
        event_type="USER_BLOCKED",
        target_id=target.id,
        details=audit_details,
    ))
    db.commit()
    db.refresh(target)

    return AdminUserResponse(
        id=target.id,
        email=target.email,
        display_name=target.display_name,
        role=target.role,
        status=target.status,
        created_at=target.created_at.isoformat(),
    )


@router.patch(
    "/users/{id}/activate",
    status_code=status.HTTP_200_OK,
    response_model=AdminUserResponse,
    operation_id="identity_admin_activate_user",
)
def activate_user(
    id: UUID,
    admin_user: User = Depends(require_admin),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == id).with_for_update().first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "Usuario no encontrado.",
                "correlation_id": str(correlation_id),
            },
        )

    now = datetime.now(timezone.utc)
    target.status = "ACTIVE"
    target.updated_at = now

    # Insert audit log
    db.add(audit_entry(correlation_id=correlation_id,
        user_id=admin_user.id,
        event_type="USER_ACTIVATED", target_id=target.id,
        details={"target_user_id": str(target.id), "target_email": target.email},
    ))
    db.commit()
    db.refresh(target)

    return AdminUserResponse(
        id=target.id,
        email=target.email,
        display_name=target.display_name,
        role=target.role,
        status=target.status,
        created_at=target.created_at.isoformat(),
    )
