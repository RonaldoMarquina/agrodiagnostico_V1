"""FastAPI router for internal Identity endpoints (never exposed via public proxy)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, require_notification_service
from app.api.schemas import InternalUserContactResponse
from app.domain.models import User
from app.infrastructure.internal_auth import InternalServiceIdentity
from app.persistence import get_db

router = APIRouter(prefix="/internal/users", tags=["internal-users"])


@router.get(
    "/{id}/contact",
    status_code=status.HTTP_200_OK,
    response_model=InternalUserContactResponse,
    operation_id="identity_internal_user_contact",
)
def get_internal_user_contact(
    id: UUID,
    _service: InternalServiceIdentity = Depends(require_notification_service),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    """Return minimal contact details for Notification email delivery (ADR-0014)."""
    user = db.query(User).filter(User.id == id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "Usuario no encontrado.",
                "correlation_id": str(correlation_id),
            },
        )

    return InternalUserContactResponse(
        user_id=user.id,
        email=user.email,
        active=(user.status == "ACTIVE"),
    )
