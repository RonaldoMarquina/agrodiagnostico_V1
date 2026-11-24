"""Signed internal client for resolving user email contact from Identity service (ADR-0014)."""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional
import uuid

import httpx
import jwt

INTERNAL_ISSUER = "agrodiagnostico-internal"
INTERNAL_AUDIENCE = "identity-internal"
INTERNAL_PRINCIPAL = "notification"
MAX_TOKEN_LIFETIME_SECONDS = 60


class ContactLookupTransientError(Exception):
    """Raised when Identity contact lookup fails due to a transient/transport error."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True)
class ContactLookupResult:
    found: bool
    active: bool
    email: Optional[str]


class InternalTokenSigner:
    """Signs short-lived Ed25519 JWTs for Notification -> Identity internal HTTP calls."""

    def __init__(self, private_key_pem: str, kid: str, instance_id: str):
        self._private_key_pem = private_key_pem
        self.kid = kid
        self.instance_id = instance_id

    @classmethod
    def from_environment(cls) -> Optional["InternalTokenSigner"]:
        priv_pem = os.environ.get("INTERNAL_NOTIFICATION_PRIVATE_KEY")
        priv_file = os.environ.get("INTERNAL_NOTIFICATION_PRIVATE_KEY_FILE")
        if not priv_pem and priv_file and Path(priv_file).is_file():
            priv_pem = Path(priv_file).read_text().strip()

        kid = os.environ.get("INTERNAL_NOTIFICATION_KID", "notification-1-key")
        instance_id = os.environ.get("INTERNAL_NOTIFICATION_INSTANCE_ID", "notification-1")

        if priv_pem and kid and instance_id:
            return cls(private_key_pem=priv_pem, kid=kid, instance_id=instance_id)
        return None

    def issue_token(self, lifetime_seconds: int = MAX_TOKEN_LIFETIME_SECONDS) -> str:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        ttl = max(1, min(lifetime_seconds, MAX_TOKEN_LIFETIME_SECONDS))
        payload = {
            "iss": INTERNAL_ISSUER,
            "aud": INTERNAL_AUDIENCE,
            "sub": INTERNAL_PRINCIPAL,
            "instance_id": self.instance_id,
            "iat": now_ts,
            "exp": now_ts + ttl,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(
            payload,
            self._private_key_pem,
            algorithm="EdDSA",
            headers={"kid": self.kid},
        )


class IdentityContactClient:
    """HTTP client calling GET /internal/users/{id}/contact on Identity."""

    def __init__(
        self,
        base_url: str,
        signer: Optional[InternalTokenSigner],
        timeout_seconds: float = 5.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.signer = signer
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> "IdentityContactClient":
        base_url = os.environ.get("IDENTITY_INTERNAL_URL", "http://identity:8000")
        signer = InternalTokenSigner.from_environment()
        timeout = float(os.environ.get("IDENTITY_CONTACT_TIMEOUT_SECONDS", "5.0"))
        return cls(base_url=base_url, signer=signer, timeout_seconds=timeout)

    def get_user_contact(self, user_id: uuid.UUID, correlation_id: uuid.UUID) -> ContactLookupResult:
        if self.signer is None:
            raise ContactLookupTransientError("INTERNAL_SIGNER_UNAVAILABLE")

        token = self.signer.issue_token()
        url = f"{self.base_url}/internal/users/{user_id}/contact"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Correlation-ID": str(correlation_id),
            "Accept": "application/json",
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise ContactLookupTransientError("IDENTITY_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise ContactLookupTransientError("IDENTITY_UNAVAILABLE") from exc

        if resp.status_code == 404:
            return ContactLookupResult(found=False, active=False, email=None)

        if resp.status_code == 200:
            try:
                data = resp.json()
                email = data.get("email")
                active = bool(data.get("active"))
                if not isinstance(email, str) or not email:
                    raise ContactLookupTransientError("IDENTITY_INVALID_RESPONSE")
                return ContactLookupResult(found=True, active=active, email=email)
            except ContactLookupTransientError:
                raise
            except Exception as exc:
                raise ContactLookupTransientError("IDENTITY_INVALID_RESPONSE") from exc

        if resp.status_code in (401, 403):
            raise ContactLookupTransientError("IDENTITY_AUTH_FAILED")
        raise ContactLookupTransientError(f"IDENTITY_HTTP_{resp.status_code}")
