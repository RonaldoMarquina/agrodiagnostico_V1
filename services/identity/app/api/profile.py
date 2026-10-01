"""User profile management endpoints: get, patch, password change."""
from app.infrastructure.audit import audit_entry
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_correlation_id, get_current_user
from app.api.schemas import (
    MessageResponse,
    PasswordChangeRequest,
    ProfilePatchRequest,
    ProfileResponse,
)
from app.domain.models import RefreshSession, User
from app.infrastructure.security import hash_password, verify_password
from app.persistence import get_db

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ProfileResponse,
    operation_id="identity_get_profile",
)
def get_profile(
    current_user: User = Depends(get_current_user),
    correlation_id: UUID = Depends(get_correlation_id),
):
    return ProfileResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        role=current_user.role,
        created_at=current_user.created_at.isoformat(),
    )


@router.patch(
    "",
    status_code=status.HTTP_200_OK,
    response_model=ProfileResponse,
    operation_id="identity_patch_profile",
)
def patch_profile(
    payload: ProfilePatchRequest,
    current_user: User = Depends(get_current_user),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    new_name = payload.display_name.strip()
    current_user.display_name = new_name
    current_user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)

    return ProfileResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        role=current_user.role,
        created_at=current_user.created_at.isoformat(),
    )


@router.put(
    "/password",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
    operation_id="identity_change_password",
)
def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    correlation_id: UUID = Depends(get_correlation_id),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "La contraseña actual no es correcta.",
                "correlation_id": str(correlation_id),
            },
        )

    try:
        new_pw_hash = hash_password(payload.new_password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": str(e),
                "correlation_id": str(correlation_id),
            },
        )

    now = datetime.now(timezone.utc)

    # 1. Update password
    current_user.password_hash = new_pw_hash
    current_user.updated_at = now

    # 2. Mandatory revocation of all active refresh sessions in PostgreSQL
    db.query(RefreshSession).filter(
        RefreshSession.user_id == current_user.id,
        RefreshSession.revoked_at.is_(None),
    ).update({RefreshSession.revoked_at: now}, synchronize_session=False)

    # 3. Log audit event
    db.add(audit_entry(correlation_id=correlation_id,
        user_id=current_user.id,
        event_type="PASSWORD_CHANGED",
    ))
    db.commit()

    return MessageResponse(message="Contraseña actualizada exitosamente.")
