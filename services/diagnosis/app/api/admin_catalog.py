"""FastAPI router for administrative agricultural catalog management endpoints."""
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Body, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_admin
from app.application.catalog import (
    create_admin_crop,
    create_admin_problem,
    create_admin_recommendation,
    get_admin_crops,
    get_admin_problems,
    get_admin_recommendations,
    patch_admin_crop,
    patch_admin_problem,
    patch_admin_recommendation,
)
from app.infrastructure.security import Principal
from app.persistence import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin_catalog"])


# --- Crops Admin ---

@router.get("/crops", status_code=status.HTTP_200_OK)
def admin_list_crops_endpoint(
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = get_admin_crops(db=db)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


@router.post("/crops", status_code=status.HTTP_201_CREATED)
def admin_create_crop_endpoint(
    payload: Dict[str, Any] = Body(...),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = create_admin_crop(db=db, principal=principal, correlation_id=cid, data=payload)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


@router.patch("/crops/{code}", status_code=status.HTTP_200_OK)
def admin_patch_crop_endpoint(
    code: str,
    payload: Dict[str, Any] = Body(...),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = patch_admin_crop(db=db, principal=principal, correlation_id=cid, code=code, data=payload)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


# --- Problems Admin ---

@router.get("/problems", status_code=status.HTTP_200_OK)
def admin_list_problems_endpoint(
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = get_admin_problems(db=db)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


@router.post("/problems", status_code=status.HTTP_201_CREATED)
def admin_create_problem_endpoint(
    payload: Dict[str, Any] = Body(...),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = create_admin_problem(db=db, principal=principal, correlation_id=cid, data=payload)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


@router.patch("/problems/{code}", status_code=status.HTTP_200_OK)
def admin_patch_problem_endpoint(
    code: str,
    payload: Dict[str, Any] = Body(...),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = patch_admin_problem(db=db, principal=principal, correlation_id=cid, code=code, data=payload)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


# --- Recommendations Admin ---

@router.get("/recommendations", status_code=status.HTTP_200_OK)
def admin_list_recommendations_endpoint(
    problem_code: Optional[str] = Query(None),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = get_admin_recommendations(db=db, problem_code=problem_code)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


@router.post("/recommendations", status_code=status.HTTP_201_CREATED)
def admin_create_recommendation_endpoint(
    payload: Dict[str, Any] = Body(...),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = create_admin_recommendation(db=db, principal=principal, correlation_id=cid, data=payload)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )


@router.patch("/recommendations/{id}", status_code=status.HTTP_200_OK)
def admin_patch_recommendation_endpoint(
    id: uuid.UUID,
    payload: Dict[str, Any] = Body(...),
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    data = patch_admin_recommendation(db=db, principal=principal, correlation_id=cid, rec_id=id, data=payload)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={"Cache-Control": "private, no-store", "X-Correlation-ID": str(cid)},
    )
