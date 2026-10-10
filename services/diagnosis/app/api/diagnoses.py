"""FastAPI router for diagnoses endpoints."""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_user
from app.application.diagnoses import (
    DiagnosisFeedbackInput,
    cancel_diagnosis,
    create_diagnosis,
    delete_diagnosis,
    get_diagnosis_detail,
    get_diagnosis_image,
    list_user_diagnoses,
    submit_diagnosis_feedback,
)
from app.domain.image import parse_multipart_image
from app.infrastructure.cursor import format_utc_iso
from app.infrastructure.security import Principal
from app.persistence import get_db
from app.storage import get_storage_adapter

router = APIRouter(prefix="/api/v1/diagnoses", tags=["diagnoses"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_diagnosis_endpoint(
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Cabecera Idempotency-Key obligatoria."},
        )

    validated_image = await parse_multipart_image(request)
    storage = get_storage_adapter()

    diagnosis = create_diagnosis(
        db=db,
        principal=principal,
        idempotency_key=idempotency_key,
        validated_image=validated_image,
        storage=storage,
        correlation_id=cid,
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "id": str(diagnosis.id),
            "status": diagnosis.status,
            "created_at": format_utc_iso(diagnosis.created_at),
        },
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get("", status_code=status.HTTP_200_OK)
def list_diagnoses_endpoint(
    limit: Optional[int] = Query(20),
    cursor: Optional[str] = Query(None),
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    page = list_user_diagnoses(
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


@router.get("/{id}", status_code=status.HTTP_200_OK)
def get_diagnosis_detail_endpoint(
    id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    detail = get_diagnosis_detail(
        db=db,
        principal=principal,
        diagnosis_id=id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=detail,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diagnosis_endpoint(
    id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    delete_diagnosis(
        db=db,
        principal=principal,
        diagnosis_id=id,
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.post("/{id}/cancel", status_code=status.HTTP_200_OK)
def cancel_diagnosis_endpoint(
    id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    result = cancel_diagnosis(
        db=db,
        principal=principal,
        diagnosis_id=id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=result,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get("/{id}/image")
def get_diagnosis_image_endpoint(
    id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    storage = get_storage_adapter()
    image_bytes, content_type = get_diagnosis_image(
        db=db,
        principal=principal,
        diagnosis_id=id,
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


@router.post("/{id}/feedback")
def submit_feedback_endpoint(
    id: uuid.UUID,
    payload: DiagnosisFeedbackInput,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    fb_data, status_code = submit_diagnosis_feedback(
        db=db,
        principal=principal,
        diagnosis_id=id,
        payload=payload,
    )
    return JSONResponse(
        status_code=status_code,
        content=fb_data,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )
