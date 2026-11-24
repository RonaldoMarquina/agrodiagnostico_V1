"""Application orchestrator for POST /api/v1/assistant/messages (ADR-0015)."""
import logging
import time
import uuid

from fastapi import HTTPException, status

from app.config import AssistantSettings
from app.domain.policy import (
    AssistantForbiddenError,
    ProviderOutputInvalidError,
    validate_and_authorize_candidate,
)
from app.domain.schemas import AssistantMessageRequest, AssistantResponse
from app.infrastructure.rate_limit import get_rate_limiter
from app.infrastructure.secrets_guard import detect_sensitive_secret
from app.infrastructure.telemetry import get_metrics, log_assistant_event
from app.infrastructure.tokens import Principal
from app.providers.base import (
    ProviderConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    SafeContext,
)
from app.providers.factory import build_provider


def process_assistant_message(
    *,
    payload: AssistantMessageRequest,
    principal: Principal,
    correlation_id: str,
    settings: AssistantSettings,
) -> AssistantResponse:
    """Run full trust-boundary pipeline: enabled -> rate limit -> input/secret check -> provider -> RBAC."""
    start = time.monotonic()
    metrics = get_metrics()

    if not settings.enabled:
        metrics.increment("assistant_requests_total", status="503", decision="DISABLED")
        log_assistant_event(
            level=logging.INFO,
            event="assistant_request",
            correlation_id=correlation_id,
            role=principal.role,
            decision="UNAVAILABLE",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=settings.provider,
            reason_code="DISABLED",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ASSISTANT_UNAVAILABLE",
                "message": "El asistente no está disponible en este momento. Puedes continuar usando la navegación manual.",
                "correlation_id": correlation_id,
            },
        )

    # Length guard against runtime-configured ASSISTANT_MAX_INPUT_CHARS (can be stricter than 2000)
    message_text = payload.message.strip()
    if len(message_text) > settings.max_input_chars:
        metrics.increment("assistant_requests_total", status="400", decision="INVALID_INPUT")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_request",
            correlation_id=correlation_id,
            role=principal.role,
            decision="REJECTED",
            http_status=status.HTTP_400_BAD_REQUEST,
            latency_ms=(time.monotonic() - start) * 1000.0,
            reason_code="MAX_INPUT_CHARS_EXCEEDED",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": f"El mensaje excede el límite de {settings.max_input_chars} caracteres.",
                "correlation_id": correlation_id,
                "details": [{"field": "message", "code": "MAX_LENGTH_EXCEEDED"}],
            },
        )

    # Secret detection BEFORE invoking any provider (AT-19, INV-05)
    secret_category = detect_sensitive_secret(message_text)
    if secret_category is not None:
        metrics.increment("assistant_sensitive_rejected_total", category=secret_category)
        metrics.increment("assistant_requests_total", status="400", decision="SENSITIVE_REJECTED")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_sensitive_input_rejected",
            correlation_id=correlation_id,
            role=principal.role,
            decision="REJECTED",
            http_status=status.HTTP_400_BAD_REQUEST,
            latency_ms=(time.monotonic() - start) * 1000.0,
            reason_code=secret_category,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "SENSITIVE_INPUT_REJECTED",
                "message": "Por seguridad, no incluyas tokens, contraseñas ni claves privadas en tu mensaje.",
                "correlation_id": correlation_id,
            },
        )

    # Per-identity rate limit BEFORE invoking provider (AT-16)
    limiter = get_rate_limiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
    allowed, retry_after = limiter.check_and_record(str(principal.id))
    if not allowed:
        metrics.increment("assistant_rate_limited_total", role=principal.role)
        metrics.increment("assistant_requests_total", status="429", decision="RATE_LIMITED")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_rate_limited",
            correlation_id=correlation_id,
            role=principal.role,
            decision="RATE_LIMITED",
            http_status=status.HTTP_429_TOO_MANY_REQUESTS,
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=settings.provider,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": "Has superado el límite de solicitudes al asistente. Intenta nuevamente en unos momentos.",
                "correlation_id": correlation_id,
            },
            headers={"Retry-After": str(retry_after)},
        )

    # Build provider (fail closed; no silent fallback from gemini to fake)
    try:
        provider = build_provider(settings)
    except (ProviderConfigurationError, ProviderUnavailableError) as exc:
        metrics.increment("assistant_provider_errors_total", error_class=type(exc).__name__)
        metrics.increment("assistant_requests_total", status="503", decision="UNAVAILABLE")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_provider_unavailable",
            correlation_id=correlation_id,
            role=principal.role,
            decision="UNAVAILABLE",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=settings.provider,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ASSISTANT_UNAVAILABLE",
                "message": "El asistente no está disponible en este momento. Puedes continuar usando la navegación manual.",
                "correlation_id": correlation_id,
            },
        ) from None

    # Interpret via provider (untrusted output)
    safe_ctx = SafeContext(role=principal.role, correlation_id=correlation_id)
    try:
        raw_candidate = provider.interpret(message_text, safe_ctx)
    except ProviderTimeoutError as exc:
        metrics.increment("assistant_provider_errors_total", error_class=type(exc).__name__)
        metrics.increment("assistant_requests_total", status="504", decision="TIMEOUT")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_provider_timeout",
            correlation_id=correlation_id,
            role=principal.role,
            decision="TIMEOUT",
            http_status=status.HTTP_504_GATEWAY_TIMEOUT,
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=provider.provider_name,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "ASSISTANT_TIMEOUT",
                "message": "El asistente tardó demasiado en responder. Puedes continuar usando la navegación manual.",
                "correlation_id": correlation_id,
            },
        ) from None
    except (ProviderError, ProviderOutputInvalidError) as exc:
        metrics.increment("assistant_provider_errors_total", error_class=type(exc).__name__)
        metrics.increment("assistant_requests_total", status="503", decision="PROVIDER_ERROR")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_provider_error",
            correlation_id=correlation_id,
            role=principal.role,
            decision="UNAVAILABLE",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=provider.provider_name,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ASSISTANT_UNAVAILABLE",
                "message": "El asistente no está disponible en este momento. Puedes continuar usando la navegación manual.",
                "correlation_id": correlation_id,
            },
        ) from None

    # Local validation + independent RBAC authorization
    request_id = str(uuid.uuid4())
    try:
        response = validate_and_authorize_candidate(raw_candidate, principal, request_id)
    except AssistantForbiddenError as exc:
        metrics.increment("assistant_rbac_denials_total", role=principal.role)
        metrics.increment("assistant_requests_total", status="403", decision="FORBIDDEN")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_rbac_denied",
            correlation_id=correlation_id,
            role=principal.role,
            intent=exc.intent,
            decision="FORBIDDEN",
            http_status=status.HTTP_403_FORBIDDEN,
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=provider.provider_name,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": exc.message,
                "correlation_id": correlation_id,
            },
        ) from None
    except ProviderOutputInvalidError as exc:
        metrics.increment("assistant_provider_errors_total", error_class=type(exc).__name__)
        metrics.increment("assistant_requests_total", status="503", decision="INVALID_OUTPUT")
        log_assistant_event(
            level=logging.WARNING,
            event="assistant_invalid_provider_output",
            correlation_id=correlation_id,
            role=principal.role,
            decision="UNAVAILABLE",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            latency_ms=(time.monotonic() - start) * 1000.0,
            provider=provider.provider_name,
            error_class=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ASSISTANT_UNAVAILABLE",
                "message": "El asistente no está disponible en este momento. Puedes continuar usando la navegación manual.",
                "correlation_id": correlation_id,
            },
        ) from None

    metrics.increment("assistant_requests_total", status="200", decision=response.status)
    log_assistant_event(
        level=logging.INFO,
        event="assistant_request",
        correlation_id=correlation_id,
        role=principal.role,
        intent=response.intent,
        decision=response.status,
        http_status=status.HTTP_200_OK,
        latency_ms=(time.monotonic() - start) * 1000.0,
        provider=provider.provider_name,
    )
    return response
