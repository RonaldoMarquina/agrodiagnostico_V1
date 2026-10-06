"""FastAPI router for administrative diagnosis supervision endpoints."""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_admin
from app.application.diagnoses import list_admin_diagnoses
from app.infrastructure.security import Principal
from app.persistence import get_db

router = APIRouter(prefix="/api/v1/admin/diagnoses", tags=["admin_diagnoses"])


@router.get("", status_code=status.HTTP_200_OK)
def admin_list_diagnoses_endpoint(
    limit: Optional[int] = Query(20),
    cursor: Optional[str] = Query(None),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    """Supervise diagnoses with keyset pagination, excluding soft-deleted diagnoses and auditing view access."""
    page = list_admin_diagnoses(
        db=db,
        principal=principal,
        correlation_id=cid,
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
