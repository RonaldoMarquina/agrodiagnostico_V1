"""Deterministic detection of secrets and credentials in user messages (AT-19, INV-05).

Returns only a safe category identifier; never echoes or logs matched secret material.
"""
import re
from typing import Optional, Tuple

_SECRET_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    (
        "PRIVATE_KEY",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    ),
    (
        "JWT_TOKEN",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "GOOGLE_API_KEY",
        re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    ),
    (
        "BEARER_TOKEN",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    ),
    (
        "PROVIDER_SECRET_KEY",
        re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,})\b"),
    ),
    (
        "CREDENTIAL_ASSIGNMENT",
        re.compile(
            r"(?i)\b(?:password|passwd|contrase[nñ]a|api[_-]?key|gemini[_-]?api[_-]?key|"
            r"secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*['\"]?\S{6,}"
        ),
    ),
)


def detect_sensitive_secret(text: str) -> Optional[str]:
    """Return a safe secret category label if sensitive material is detected, else None."""
    if not text:
        return None
    for category, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return category
    return None
