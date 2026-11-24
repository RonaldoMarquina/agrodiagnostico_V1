"""Independent validation and RBAC authorization policy engine for provider outputs (INV-01..INV-10, ADR-0015)."""
import re
from typing import Any

from pydantic import ValidationError

from app.domain.explanations import (
    CLARIFICATION_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    get_approved_explanation,
    get_deferred_message,
)
from app.domain.registry import (
    ALLOWED_TARGETS,
    INTENT_REGISTRY,
    OFFICIAL_DIAGNOSIS_STATUSES,
)
from app.domain.schemas import AssistantAction, AssistantCandidate, AssistantResponse
from app.infrastructure.tokens import Principal

_UNSAFE_VALUE_PATTERNS = (
    re.compile(r"(?i)(?:https?://|javascript:|data:|file://)"),
    re.compile(r"(?i)<\s*(?:script|iframe|object|embed|a\b|img\b)"),
    re.compile(r"(?i)\b(?:select\s+.+\s+from|drop\s+table|delete\s+from|insert\s+into|update\s+\w+\s+set)\b"),
    re.compile(r"(?:\.\./|/internal/|/health/)"),
)


class ProviderOutputInvalidError(Exception):
    """Raised when provider output violates closed schema, registry, or safety constraints."""


class AssistantForbiddenError(Exception):
    """Raised when the authenticated principal lacks permission for the interpreted intent."""

    def __init__(self, intent: str, message: str = "No tienes permisos para acceder a esa funcionalidad."):
        super().__init__(message)
        self.intent = intent
        self.message = message


def _contains_unsafe_artifact(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _UNSAFE_VALUE_PATTERNS)
    if isinstance(value, dict):
        return any(
            _contains_unsafe_artifact(k) or _contains_unsafe_artifact(v)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_unsafe_artifact(item) for item in value)
    return False


def validate_and_authorize_candidate(
    raw_candidate: Any,
    principal: Principal,
    request_id: str,
) -> AssistantResponse:
    """Validate an untrusted provider candidate and enforce local RBAC & availability policy.

    Gemini interprets; AgroDiagnóstico validates and authorizes.
    """
    if isinstance(raw_candidate, AssistantCandidate):
        candidate = raw_candidate
    else:
        try:
            candidate = AssistantCandidate.model_validate(raw_candidate)
        except ValidationError as exc:
            raise ProviderOutputInvalidError("Malformed provider candidate") from exc

    if _contains_unsafe_artifact(candidate.parameters):
        raise ProviderOutputInvalidError("Unsafe artifact detected in provider parameters")
    if candidate.intent is not None and _contains_unsafe_artifact(candidate.intent):
        raise ProviderOutputInvalidError("Unsafe artifact detected in provider intent")

    if candidate.disposition == "CLARIFICATION_REQUIRED":
        if candidate.intent is not None or candidate.parameters:
            raise ProviderOutputInvalidError("Clarification must not carry intent or parameters")
        return AssistantResponse(
            request_id=request_id,
            status="CLARIFICATION_REQUIRED",
            intent=None,
            message=CLARIFICATION_MESSAGE,
            action=None,
        )

    if candidate.disposition == "OUT_OF_SCOPE":
        if candidate.parameters:
            raise ProviderOutputInvalidError("Out-of-scope response must not carry parameters")
        if candidate.intent is not None:
            raise ProviderOutputInvalidError("Out-of-scope candidate must not carry an executable intent")
        return AssistantResponse(
            request_id=request_id,
            status="OUT_OF_SCOPE",
            intent=None,
            message=OUT_OF_SCOPE_MESSAGE,
            action=None,
        )

    # disposition == "INTENT"
    if not candidate.intent or candidate.intent not in INTENT_REGISTRY:
        raise ProviderOutputInvalidError("Unknown or missing intent from provider")

    spec = INTENT_REGISTRY[candidate.intent]

    # Independent RBAC check using verified JWT role (never trusts provider claims)
    if principal.role not in spec.allowed_roles:
        raise AssistantForbiddenError(intent=spec.intent)

    # Strict parameter validation per intent kind
    status_param = None
    if spec.kind == "NAVIGATE":
        if candidate.parameters:
            raise ProviderOutputInvalidError("Navigation intents do not accept parameters")
    elif spec.intent == "EXPLAIN_DIAGNOSIS_STATUS":
        extra_keys = set(candidate.parameters.keys()) - {"status"}
        if extra_keys:
            raise ProviderOutputInvalidError("Unexpected parameters for EXPLAIN_DIAGNOSIS_STATUS")
        if "status" in candidate.parameters and candidate.parameters["status"] is not None:
            raw_status = candidate.parameters["status"]
            if not isinstance(raw_status, str):
                raise ProviderOutputInvalidError("Status parameter must be a string")
            normalized_status = raw_status.strip().upper().replace(" ", "_")
            if normalized_status not in OFFICIAL_DIAGNOSIS_STATUSES:
                raise ProviderOutputInvalidError("Unknown diagnosis status in provider output")
            status_param = normalized_status
    else:
        if candidate.parameters:
            raise ProviderOutputInvalidError("Explanation intent does not accept parameters")

    # Deferred / unavailable destinations never emit executable actions (AT-09)
    if not spec.available:
        return AssistantResponse(
            request_id=request_id,
            status="OUT_OF_SCOPE",
            intent=spec.intent,
            message=get_deferred_message(spec.intent),
            action=None,
        )

    if spec.kind == "EXPLAIN":
        return AssistantResponse(
            request_id=request_id,
            status="SUCCESS",
            intent=spec.intent,
            message=get_approved_explanation(spec.intent, status_code=status_param),
            action=None,
        )

    # Authorized and available NAVIGATE intent
    if not spec.target or spec.target not in ALLOWED_TARGETS:
        raise ProviderOutputInvalidError("Navigation target is not registered as available")

    return AssistantResponse(
        request_id=request_id,
        status="SUCCESS",
        intent=spec.intent,
        message=spec.nav_message or "Te llevo a la sección solicitada.",
        action=AssistantAction(type="NAVIGATE", target=spec.target),
    )
