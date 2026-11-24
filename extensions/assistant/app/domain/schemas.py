"""Strict closed Pydantic models for public HTTP contract and internal provider candidates (ADR-0015)."""
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssistantMessageRequest(BaseModel):
    """Public closed request body for POST /api/v1/assistant/messages."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Message must not be empty or whitespace")
        return value


class AssistantAction(BaseModel):
    """Closed navigation action returned only for authorized, available navigation intents."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["NAVIGATE"] = "NAVIGATE"
    target: str = Field(..., min_length=1, max_length=64)


class AssistantResponse(BaseModel):
    """Normalized public 200 response for POST /api/v1/assistant/messages."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: Literal["SUCCESS", "CLARIFICATION_REQUIRED", "OUT_OF_SCOPE"]
    intent: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=2000)
    action: Optional[AssistantAction] = None


class AssistantCandidate(BaseModel):
    """Closed internal schema for untrusted provider interpretations before local policy checks."""

    model_config = ConfigDict(extra="forbid")

    disposition: Literal["INTENT", "CLARIFICATION_REQUIRED", "OUT_OF_SCOPE"]
    intent: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    message: str = Field(default="", max_length=2000)
