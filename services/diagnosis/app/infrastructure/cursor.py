"""HMAC-SHA256 authenticated cursor implementation for keyset pagination.

In accordance with ADR-0006 and OpenSpec Incremento 2:
- Cursors are Base64URL-encoded JSON payloads authenticated with HMAC-SHA256.
- Bound to version (v=1), endpoint purpose ('user_diagnoses' | 'admin_supervision'),
  requesting principal ID (sub), item created_at, and item id.
- Any altered, expired secret, wrong-purpose, or wrong-principal cursor
  fails closed with HTTP 400 INVALID_PAGINATION.
"""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Tuple
import uuid

from fastapi import HTTPException, status

from app.infrastructure.security import get_cursor_signing_key


def format_utc_iso(dt: datetime) -> str:
    """Format datetime as strict UTC ISO 8601 with trailing 'Z'."""
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


def parse_utc_iso(s: str) -> datetime:
    """Parse ISO datetime string and ensure timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("Timestamp must be a string")
    s_clean = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s_clean)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def encode_cursor(
    created_at: datetime,
    diagnosis_id: uuid.UUID,
    principal_id: uuid.UUID,
    purpose: str,
) -> str:
    """Generate an HMAC-SHA256 signed Base64URL pagination cursor token."""
    payload = {
        "v": 1,
        "purp": purpose,
        "sub": str(principal_id),
        "created_at": format_utc_iso(created_at),
        "id": str(diagnosis_id),
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = get_cursor_signing_key()
    sig = hmac.new(key, canonical_bytes, hashlib.sha256).digest()

    b64_payload = base64.urlsafe_b64encode(canonical_bytes).decode("ascii").rstrip("=")
    b64_sig = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{b64_payload}.{b64_sig}"


def decode_cursor(
    cursor_str: str,
    expected_principal_id: uuid.UUID,
    expected_purpose: str,
) -> Tuple[datetime, uuid.UUID]:
    """Validate and decode HMAC pagination cursor.

    Fails closed with 400 INVALID_PAGINATION on any format, signature,
    purpose, or principal mismatch.
    """
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
        key = get_cursor_signing_key()
        expected_sig = hmac.new(key, payload_bytes, hashlib.sha256).digest()
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

        item_id = uuid.UUID(data.get("id"))
        created_at = parse_utc_iso(data.get("created_at"))
        return created_at, item_id
    except HTTPException:
        raise
    except Exception:
        raise invalid_exc
