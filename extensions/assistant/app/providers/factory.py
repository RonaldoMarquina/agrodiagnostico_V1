"""Provider factory with strict no-silent-fallback guarantee (ADR-0015 D5)."""
from typing import Optional

from app.config import AssistantSettings
from app.providers.base import (
    AssistantProvider,
    ProviderConfigurationError,
    ProviderUnavailableError,
)
from app.providers.fake import FakeAssistantAdapter
from app.providers.gemini import GeminiAdapter

_PROVIDER_OVERRIDE: Optional[AssistantProvider] = None


def set_provider_override(provider: Optional[AssistantProvider]) -> None:
    """Inject a test provider cleanly during unit tests."""
    global _PROVIDER_OVERRIDE
    _PROVIDER_OVERRIDE = provider


def build_provider(settings: AssistantSettings) -> AssistantProvider:
    """Resolve the configured provider. Never silently falls back from gemini to fake."""
    if not settings.enabled:
        raise ProviderUnavailableError("Assistant extension is disabled")

    if _PROVIDER_OVERRIDE is not None:
        return _PROVIDER_OVERRIDE

    if settings.provider == "fake":
        return FakeAssistantAdapter()

    if settings.provider == "gemini":
        if not settings.gemini_api_key or not settings.gemini_model:
            raise ProviderConfigurationError("Gemini credentials or model are not configured")
        return GeminiAdapter(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
            max_retries=settings.max_retries,
        )

    raise ProviderConfigurationError("Unsupported assistant provider")
