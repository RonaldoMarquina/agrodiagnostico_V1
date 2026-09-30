"""Administrative account management endpoints: list users, block, activate."""
import base64
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_admin
from app.api.schemas import AdminUserPageResponse, AdminUserResponse
from app.domain.models import AuditLog, RefreshSession, User
from app.persistence import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


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
    target.status = "BLOCKED"
    target.updated_at = now

    # Revoke all active refresh sessions immediately in PostgreSQL
    db.query(RefreshSession).filter(
        RefreshSession.user_id == target.id,
        RefreshSession.revoked_at.is_(None),
    ).update({RefreshSession.revoked_at: now}, synchronize_session=False)

    # Insert audit log
    db.add(AuditLog(
        user_id=admin_user.id,
        event_type="USER_BLOCKED",
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
    db.add(AuditLog(
        user_id=admin_user.id,
        event_type="USER_ACTIVATED",
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
