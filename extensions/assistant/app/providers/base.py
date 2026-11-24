"""Provider interface, safe context, and typed error hierarchy (ADR-0015 D5)."""
from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass(frozen=True)
class SafeContext:
    """Minimal non-sensitive context passed to an AssistantProvider (never JWT, email, or history)."""

    role: str
    correlation_id: str


class ProviderError(Exception):
    """Base error raised by assistant providers."""


class ProviderConfigurationError(ProviderError):
    """Raised when provider credentials or model configuration are invalid or missing."""


class ProviderUnavailableError(ProviderError):
    """Raised when the assistant is disabled or the external provider is unavailable."""


class ProviderTimeoutError(ProviderError):
    """Raised when the external provider exceeds the configured timeout budget."""


class AssistantProvider(Protocol):
    """Contract implemented by FakeAssistantAdapter and GeminiAdapter."""

    provider_name: str

    def interpret(self, message: str, safe_context: SafeContext) -> Dict[str, Any]:
        """Interpret a Spanish user message and return an untrusted candidate dict."""
        ...
