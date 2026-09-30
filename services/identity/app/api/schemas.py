"""Pydantic schemas matching contracts/schemas/common.schema.json exactly."""
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


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
