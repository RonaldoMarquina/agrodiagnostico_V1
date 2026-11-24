"""Pydantic schemas matching contracts/schemas/common.schema.json exactly."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=12, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(..., min_length=1, max_length=128)


class ProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    email: str
    display_name: str
    role: str
    created_at: str


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 900
    csrf_token: str


class ProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(..., min_length=1, max_length=100)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=12, max_length=128)


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RecoveryConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(..., min_length=1, max_length=255)
    new_password: str = Field(..., min_length=12, max_length=128)


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    email: str
    display_name: str
    role: str
    status: str
    created_at: str


class AdminUserPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[AdminUserResponse]
    next_cursor: Optional[str] = None


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    code: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    correlation_id: UUID
    details: Optional[List[ErrorDetail]] = None


class InternalUserContactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    email: str
    active: bool


class AdminBlockUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=5, max_length=300)

    @field_validator("reason")
    @classmethod
    def strip_and_validate_reason(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 5 or len(stripped) > 300:
            raise ValueError("reason must contain between 5 and 300 non-whitespace characters")
        return stripped


class AdminUserStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int
    active: int
    blocked: int
    admins: int
    users: int


class IdentityAuditEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    action: str
    actor_id: Optional[UUID]
    target_id: Optional[UUID]
    correlation_id: Optional[UUID]
    legacy: bool
    details: Optional[Dict[str, Any]]
    created_at: str


class IdentityAuditPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[IdentityAuditEntryResponse]
    next_cursor: Optional[str] = None
