"""FastAPI router for public agricultural catalog endpoints."""
import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_user
from app.application.catalog import (
    get_public_crop_problems,
    get_public_crops,
    get_public_problem_recommendations,
)
from app.infrastructure.security import Principal
from app.persistence import get_db

router = APIRouter(tags=["catalog"])


@router.get("/api/v1/crops", status_code=status.HTTP_200_OK)
def list_crops_endpoint(
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    """List active crops in the agricultural catalog."""
    data = get_public_crops(db=db)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get("/api/v1/crops/{code}/problems", status_code=status.HTTP_200_OK)
def list_crop_problems_endpoint(
    code: str,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    """List active candidate problems for an active crop."""
    data = get_public_crop_problems(db=db, crop_code=code)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )


@router.get("/api/v1/problems/{code}/recommendations", status_code=status.HTTP_200_OK)
def get_problem_recommendations_endpoint(
    code: str,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
    cid: uuid.UUID = Depends(get_correlation_id),
):
    """Get the latest approved active recommendation version for an active problem."""
    data = get_public_problem_recommendations(db=db, problem_code=code)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=data,
        headers={
            "Cache-Control": "private, no-store",
            "X-Correlation-ID": str(cid),
        },
    )
