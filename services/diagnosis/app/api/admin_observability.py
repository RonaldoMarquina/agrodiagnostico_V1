"""FastAPI router for administrative metrics, audit, model inventory, and system status (ADR-0016)."""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_admin
from app.application.observability import (
    get_metrics_summary,
    get_models_inventory,
    get_system_status,
    list_diagnosis_audit,
)
from app.infrastructure.security import Principal
from app.persistence import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin_observability"])


@router.get(
    "/metrics/summary",
    status_code=status.HTTP_200_OK,
    operation_id="diagnosis_admin_metrics_summary",
)
def admin_metrics_summary_endpoint(
    from_raw: Optional[str] = Query(None, alias="from"),
    to_raw: Optional[str] = Query(None, alias="to"),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    summary = get_metrics_summary(db=db, from_raw=from_raw, to_raw=to_raw)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=summary,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get(
    "/audit/diagnosis",
    status_code=status.HTTP_200_OK,
    operation_id="diagnosis_admin_list_audit",
)
def admin_list_diagnosis_audit_endpoint(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, min_length=1, max_length=2048),
    action: Optional[str] = Query(None, min_length=1, max_length=100),
    actor_id: Optional[uuid.UUID] = Query(None),
    target_type: Optional[str] = Query(None, min_length=1, max_length=60),
    target_id: Optional[str] = Query(None, min_length=1, max_length=100),
    from_raw: Optional[str] = Query(None, alias="from"),
    to_raw: Optional[str] = Query(None, alias="to"),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    page = list_diagnosis_audit(
        db=db,
        principal=principal,
        limit=limit,
        cursor=cursor,
        action=action,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        from_raw=from_raw,
        to_raw=to_raw,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=page,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get(
    "/models",
    status_code=status.HTTP_200_OK,
    operation_id="diagnosis_admin_list_models",
)
def admin_list_models_endpoint(
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    inventory = get_models_inventory(db=db)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=inventory,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get(
    "/system/status",
    status_code=status.HTTP_200_OK,
    operation_id="diagnosis_admin_system_status",
)
async def admin_system_status_endpoint(
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    payload = await get_system_status(db=db)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=payload,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )
