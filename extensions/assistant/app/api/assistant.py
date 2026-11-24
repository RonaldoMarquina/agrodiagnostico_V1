"""Public HTTP router for POST /api/v1/assistant/messages (ADR-0015)."""
import uuid

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_principal
from app.application.assistant import process_assistant_message
from app.config import get_settings
from app.domain.schemas import AssistantMessageRequest, AssistantResponse
from app.infrastructure.tokens import Principal

router = APIRouter()


@router.post(
    "/api/v1/assistant/messages",
    response_model=AssistantResponse,
    operation_id="assistant_send_message",
)
def send_assistant_message(
    payload: AssistantMessageRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
) -> AssistantResponse:
    cid = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    settings = get_settings()
    return process_assistant_message(
        payload=payload,
        principal=principal,
        correlation_id=cid,
        settings=settings,
    )
