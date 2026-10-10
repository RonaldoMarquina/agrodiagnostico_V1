"""FastAPI router for internal diagnosis worker operations.

Endpoints:
- POST /internal/diagnoses/{id}/claim
- POST /internal/diagnoses/{id}/lease/renew
- GET /internal/diagnoses/{id}/image
"""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_internal_service
from app.application.internal_diagnoses import (
    claim_diagnosis,
    get_internal_diagnosis_image,
    renew_diagnosis_lease,
)
from app.infrastructure.internal_auth import InternalServiceIdentity
from app.persistence import get_db
from app.storage import get_storage_adapter

router = APIRouter(prefix="/internal/diagnoses", tags=["internal-diagnoses"])


class LeaseRenewInput(BaseModel):
    lease_token: uuid.UUID = Field(..., description="UUID of current active lease token")


@router.post("/{id}/claim", status_code=status.HTTP_200_OK, operation_id="diagnosis_claim")
def claim_diagnosis_endpoint(
    id: uuid.UUID,
    identity: InternalServiceIdentity = Depends(require_internal_service),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    """Atomic claim of diagnosis work by an authenticated AI worker instance."""
    lease_info = claim_diagnosis(
        db=db,
        identity=identity,
        diagnosis_id=id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=lease_info,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.post("/{id}/lease/renew", status_code=status.HTTP_200_OK, operation_id="diagnosis_renew")
def renew_lease_endpoint(
    id: uuid.UUID,
    body: LeaseRenewInput,
    identity: InternalServiceIdentity = Depends(require_internal_service),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    """Fence-checked renewal of active work lease."""
    lease_info = renew_diagnosis_lease(
        db=db,
        identity=identity,
        diagnosis_id=id,
        lease_token=body.lease_token,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=lease_info,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get("/{id}/image", status_code=status.HTTP_200_OK, operation_id="diagnosis_internal_image")
def get_internal_image_endpoint(
    id: uuid.UUID,
    x_lease_token: Optional[str] = Header(None, alias="X-Lease-Token"),
    identity: InternalServiceIdentity = Depends(require_internal_service),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    """Deliver private original image bytes directly to authenticated worker."""
    if not x_lease_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Cabecera X-Lease-Token obligatoria."},
        )

    try:
        lease_token_uuid = uuid.UUID(x_lease_token)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "X-Lease-Token debe ser un UUID válido."},
        )

    storage = get_storage_adapter()
    image_bytes, content_type = get_internal_diagnosis_image(
        db=db,
        identity=identity,
        diagnosis_id=id,
        lease_token=lease_token_uuid,
        storage=storage,
    )

    return Response(
        content=image_bytes,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )

