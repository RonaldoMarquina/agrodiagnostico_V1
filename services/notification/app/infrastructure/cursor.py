"""HMAC-SHA256 authenticated keyset cursor for Notification pagination (ADR-0014)."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Tuple
import uuid

from fastapi import HTTPException, status

from app.infrastructure.security import get_cursor_signing_key

CURSOR_PURPOSE_USER_NOTIFICATIONS = "user_notifications"


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
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def encode_cursor(
    created_at: datetime,
    notification_id: uuid.UUID,
    principal_id: uuid.UUID,
    purpose: str = CURSOR_PURPOSE_USER_NOTIFICATIONS,
) -> str:
    payload = {
        "v": 1,
        "purp": purpose,
        "sub": str(principal_id),
        "created_at": format_utc_iso(created_at),
        "id": str(notification_id),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(get_cursor_signing_key(), canonical, hashlib.sha256).digest()
    b64_payload = base64.urlsafe_b64encode(canonical).decode("ascii").rstrip("=")
    b64_sig = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{b64_payload}.{b64_sig}"


def decode_cursor(
    cursor_str: str,
    expected_principal_id: uuid.UUID,
    expected_purpose: str = CURSOR_PURPOSE_USER_NOTIFICATIONS,
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

        item_id = uuid.UUID(data.get("id"))
        created_at = parse_utc_iso(data.get("created_at"))
        return created_at, item_id
    except HTTPException:
        raise
    except Exception:
        raise invalid_exc
