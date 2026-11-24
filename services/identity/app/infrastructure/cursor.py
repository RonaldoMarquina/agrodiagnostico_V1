"""HMAC-SHA256 authenticated keyset cursor for Identity administrative pagination (ADR-0016)."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Tuple
import uuid

from fastapi import HTTPException, status

from app.infrastructure.tokens import get_token_manager

CURSOR_PURPOSE_ADMIN_IDENTITY_AUDIT = "admin_identity_audit"


def format_utc_iso(dt: datetime) -> str:
    """Format datetime as strict UTC RFC3339 with trailing 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    iso = dt.isoformat()
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    elif not iso.endswith("Z"):
        iso = iso + "Z"
    return iso


def parse_utc_iso(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Timestamp must be a non-empty string")
    raw = value.strip()
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_cursor_signing_key() -> bytes:
    """Retrieve HMAC cursor signing key from env/file or derive deterministically from Identity private key."""
    key = os.environ.get("CURSOR_SIGNING_KEY")
    key_path = os.environ.get("CURSOR_SIGNING_KEY_FILE")
    if not key and key_path and Path(key_path).is_file():
        key = Path(key_path).read_text().strip()

    if key:
        if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
            return bytes.fromhex(key)
        return key.encode("utf-8")

    # Fallback: derive a dedicated HMAC subkey from the shared Identity Ed25519 private key
    # so all Identity replicas share the exact same cursor signing secret without exposing the JWT key.
    token_mgr = get_token_manager()
    seed = getattr(token_mgr, "_private_key_pem", None)
    if not seed:
        raise RuntimeError("No CURSOR_SIGNING_KEY or Identity private key available for cursor signing")
    return hmac.new(
        seed.encode("utf-8"),
        b"agrodiagnostico:identity:cursor:v1",
        hashlib.sha256,
    ).digest()


def compute_filter_hash(filters: dict) -> str:
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


def encode_cursor(
    created_at: datetime,
    record_id: uuid.UUID,
    principal_id: uuid.UUID,
    purpose: str = CURSOR_PURPOSE_ADMIN_IDENTITY_AUDIT,
    filter_hash: str = "",
) -> str:
    payload = {
        "v": 1,
        "purp": purpose,
        "sub": str(principal_id),
        "fh": filter_hash,
        "created_at": format_utc_iso(created_at),
        "id": str(record_id),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(get_cursor_signing_key(), canonical, hashlib.sha256).digest()
    b64_payload = base64.urlsafe_b64encode(canonical).decode("ascii").rstrip("=")
    b64_sig = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{b64_payload}.{b64_sig}"


def decode_cursor(
    cursor_str: str,
    expected_principal_id: uuid.UUID,
    expected_purpose: str = CURSOR_PURPOSE_ADMIN_IDENTITY_AUDIT,
    expected_filter_hash: str = "",
) -> Tuple[datetime, uuid.UUID]:
    invalid_exc = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "INVALID_PAGINATION",
            "message": "Cursor de paginación inválido o no autorizado.",
        },
    )

    if not isinstance(cursor_str, str) or not cursor_str or len(cursor_str) > 2048:
        raise invalid_exc

    parts = cursor_str.split(".")
    if len(parts) != 2:
        raise invalid_exc

    try:
        p_b64 = parts[0] + "=" * ((4 - len(parts[0]) % 4) % 4)
        s_b64 = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        payload_bytes = base64.urlsafe_b64decode(p_b64.encode("ascii"))
        provided_sig = base64.urlsafe_b64decode(s_b64.encode("ascii"))
    except Exception:
        raise invalid_exc

    try:
        expected_sig = hmac.new(get_cursor_signing_key(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, provided_sig):
            raise invalid_exc
    except HTTPException:
        raise
    except Exception:
        raise invalid_exc

    try:
        data = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(data, dict):
            raise invalid_exc
        if data.get("v") != 1:
            raise invalid_exc
        if data.get("purp") != expected_purpose:
            raise invalid_exc
        if data.get("sub") != str(expected_principal_id):
            raise invalid_exc
        if data.get("fh") != expected_filter_hash:
            raise invalid_exc

        item_id = uuid.UUID(data.get("id"))
        created_at = parse_utc_iso(data.get("created_at"))
        return created_at, item_id
    except HTTPException:
        raise
    except Exception:
        raise invalid_exc
