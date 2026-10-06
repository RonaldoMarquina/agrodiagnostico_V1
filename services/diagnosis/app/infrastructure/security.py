"""Security and authorization primitives for Diagnosis service."""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional
import uuid


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity derived strictly from JWT claims."""
    id: uuid.UUID
    role: Literal["USER", "ADMIN"]
    token_id: str

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


class SecurityConfigurationError(Exception):
    """Raised when critical security configuration is missing or invalid."""
    pass


def get_cursor_signing_key() -> bytes:
    """Retrieve HMAC signing key for cursors from environment or file. Fails closed."""
    key = os.environ.get("CURSOR_SIGNING_KEY")
    key_path = os.environ.get("CURSOR_SIGNING_KEY_FILE")
    if not key and key_path and Path(key_path).is_file():
        key = Path(key_path).read_text().strip()

    if not key:
        raise SecurityConfigurationError("CURSOR_SIGNING_KEY_FILE is not configured or empty")

    # If it's a 64-char hex string, decode to 32 bytes; otherwise encode utf-8
    try:
        if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
            return bytes.fromhex(key)
    except Exception:
        pass
    return key.encode("utf-8")
