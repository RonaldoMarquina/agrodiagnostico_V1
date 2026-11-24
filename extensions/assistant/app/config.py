"""Configuration and readiness checks for the assistant extension (ADR-0015)."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

SERVICE = "assistant"
VALID_PROVIDERS = {"gemini", "fake"}
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_ISSUER = "agrodiagnostico-identity"
DEFAULT_AUDIENCE = "agrodiagnostico-api"
RATE_LIMIT_PATTERN = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*s?\s*$")


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_secret(env_var: str, file_env_vars: Tuple[str, ...]) -> Optional[str]:
    direct = os.environ.get(env_var)
    if direct and direct.strip():
        return direct.strip()
    for file_var in file_env_vars:
        path_str = os.environ.get(file_var)
        if path_str:
            path = Path(path_str)
            if path.is_file():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
    return None


def parse_rate_limit(spec: str) -> Tuple[int, int]:
    """Parse ASSISTANT_RATE_LIMIT such as '20/60s' -> (20, 60)."""
    match = RATE_LIMIT_PATTERN.match(spec or "")
    if not match:
        raise ValueError("Invalid ASSISTANT_RATE_LIMIT format; expected '<count>/<seconds>s'")
    count = int(match.group(1))
    window = int(match.group(2))
    if count < 1 or window < 1:
        raise ValueError("ASSISTANT_RATE_LIMIT count and window must be positive")
    return count, window


def _is_valid_ed25519_public_key(pem: Optional[str]) -> bool:
    if not pem:
        return False
    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
        return isinstance(key, ed25519.Ed25519PublicKey)
    except Exception:
        return False


@dataclass(frozen=True)
class AssistantSettings:
    """Immutable runtime settings for the assistant extension."""

    app_env: str = "local"
    enabled: bool = False
    provider: str = "gemini"
    gemini_api_key: Optional[str] = field(default=None, repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    timeout_seconds: float = 10.0
    max_input_chars: int = 2000
    max_output_tokens: int = 512
    max_transport_bytes: int = 16384
    rate_limit_requests: int = 20
    rate_limit_window_seconds: int = 60
    max_retries: int = 1
    jwt_public_key_pem: Optional[str] = field(default=None, repr=False)
    jwt_issuer: str = DEFAULT_ISSUER
    jwt_audience: str = DEFAULT_AUDIENCE

    @classmethod
    def from_environment(cls) -> "AssistantSettings":
        app_env = os.environ.get("APP_ENV", "local").strip() or "local"
        enabled = _parse_bool(os.environ.get("ASSISTANT_ENABLED"), default=False)
        provider = os.environ.get("ASSISTANT_PROVIDER", "gemini").strip().lower()
        gemini_api_key = _read_secret("GEMINI_API_KEY", ("GEMINI_API_KEY_FILE",))
        gemini_model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()

        timeout_seconds = float(os.environ.get("ASSISTANT_TIMEOUT_SECONDS", "10.0"))
        timeout_seconds = max(0.5, min(timeout_seconds, 60.0))

        max_input_chars = int(os.environ.get("ASSISTANT_MAX_INPUT_CHARS", "2000"))
        max_input_chars = max(1, min(max_input_chars, 2000))

        max_output_tokens = int(os.environ.get("ASSISTANT_MAX_OUTPUT_TOKENS", "512"))
        max_output_tokens = max(64, min(max_output_tokens, 4096))

        max_transport_bytes = int(os.environ.get("ASSISTANT_MAX_TRANSPORT_BYTES", "16384"))
        max_transport_bytes = max(512, min(max_transport_bytes, 65536))

        rate_limit_spec = os.environ.get("ASSISTANT_RATE_LIMIT", "20/60s")
        try:
            rate_requests, rate_window = parse_rate_limit(rate_limit_spec)
        except ValueError:
            rate_requests, rate_window = 20, 60

        max_retries = int(os.environ.get("ASSISTANT_MAX_RETRIES", "1"))
        max_retries = max(0, min(max_retries, 3))

        jwt_public_key_pem = _read_secret(
            "JWT_PUBLIC_KEY",
            ("JWT_PUBLIC_KEY_PATH", "JWT_PUBLIC_KEY_FILE"),
        )
        jwt_issuer = os.environ.get("JWT_ISSUER", DEFAULT_ISSUER).strip() or DEFAULT_ISSUER
        jwt_audience = os.environ.get("JWT_AUDIENCE", DEFAULT_AUDIENCE).strip() or DEFAULT_AUDIENCE

        return cls(
            app_env=app_env,
            enabled=enabled,
            provider=provider,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            timeout_seconds=timeout_seconds,
            max_input_chars=max_input_chars,
            max_output_tokens=max_output_tokens,
            max_transport_bytes=max_transport_bytes,
            rate_limit_requests=rate_requests,
            rate_limit_window_seconds=rate_window,
            max_retries=max_retries,
            jwt_public_key_pem=jwt_public_key_pem,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def readiness_check(self) -> Tuple[bool, str]:
        """Evaluate readiness without exposing secrets. Fails closed on missing config."""
        if not self.enabled:
            return False, "disabled"
        if not _is_valid_ed25519_public_key(self.jwt_public_key_pem):
            return False, "jwt_public_key_missing"
        if self.provider not in VALID_PROVIDERS:
            return False, "invalid_provider"
        if self.provider == "gemini":
            if not self.gemini_api_key:
                return False, "gemini_api_key_missing"
            if not self.gemini_model:
                return False, "gemini_model_missing"
        return True, "ready"


_SETTINGS_OVERRIDE: Optional[AssistantSettings] = None


def get_settings() -> AssistantSettings:
    if _SETTINGS_OVERRIDE is not None:
        return _SETTINGS_OVERRIDE
    return AssistantSettings.from_environment()


def set_settings(settings: Optional[AssistantSettings]) -> None:
    global _SETTINGS_OVERRIDE
    _SETTINGS_OVERRIDE = settings
