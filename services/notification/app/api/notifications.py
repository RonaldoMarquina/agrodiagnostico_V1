"""FastAPI router for user notifications and notification preferences (ADR-0014)."""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_user
from app.application.notifications import (
    NotificationPreferencesPatchInput,
    get_unread_notifications_count,
    get_user_preferences,
    list_user_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    patch_user_preferences,
)
from app.infrastructure.security import Principal
from app.persistence import get_db

router = APIRouter(tags=["notifications"])


@router.get("/api/v1/notifications", status_code=status.HTTP_200_OK, operation_id="notification_list")
def list_notifications_endpoint(
    limit: Optional[int] = Query(20),
    cursor: Optional[str] = Query(None),
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    page = list_user_notifications(
        db=db,
        principal=principal,
        limit=limit,
        cursor=cursor,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=page,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.patch(
    "/api/v1/notifications/read-all",
    status_code=status.HTTP_200_OK,
    operation_id="notification_mark_all_read",
)
async def mark_all_notifications_read_endpoint(
    request: Request,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    raw_body = await request.body()
    if raw_body and raw_body.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Esta operación no acepta cuerpo de solicitud.",
            },
        )

    result = mark_all_notifications_read(db=db, principal=principal)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get(
    "/api/v1/notifications/unread-count",
    status_code=status.HTTP_200_OK,
    operation_id="notification_unread_count",
)
def get_unread_notifications_count_endpoint(
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    result = get_unread_notifications_count(db=db, principal=principal)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.patch(
    "/api/v1/notifications/{id}/read",
    status_code=status.HTTP_200_OK,
    operation_id="notification_mark_read",
)
async def mark_notification_read_endpoint(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    raw_body = await request.body()
    if raw_body and raw_body.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Esta operación no acepta cuerpo de solicitud.",
            },
        )

    result = mark_notification_read(
        db=db,
        principal=principal,
        notification_id=id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get(
    "/api/v1/notification-preferences",
    status_code=status.HTTP_200_OK,
    operation_id="notification_get_preferences",
)
def get_preferences_endpoint(
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    prefs = get_user_preferences(db=db, principal=principal)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=prefs,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.patch(
    "/api/v1/notification-preferences",
    status_code=status.HTTP_200_OK,
    operation_id="notification_patch_preferences",
)
def patch_preferences_endpoint(
    payload: NotificationPreferencesPatchInput,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    prefs = patch_user_preferences(db=db, principal=principal, payload=payload)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=prefs,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )
