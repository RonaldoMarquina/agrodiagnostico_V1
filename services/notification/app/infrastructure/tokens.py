"""Ed25519 (EdDSA) JWT verification for Notification service (ADR-0004 & ADR-0014).

Verification only: uses only the Ed25519 public key from Identity.
Never queries Identity's database or handles private user-signing keys.
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import jwt

DEFAULT_ISSUER = "agrodiagnostico-identity"
DEFAULT_AUDIENCE = "agrodiagnostico-api"
VALID_ROLES = {"USER", "ADMIN"}


class TokenError(Exception):
    """Base class for token verification errors."""


class TokenExpiredError(TokenError):
    """Raised when an access token has expired."""


class TokenInvalidError(TokenError):
    """Raised when an access token is structurally invalid or fails signature checks."""


def generate_ed25519_keypair() -> Tuple[str, str]:
    """Generate a new Ed25519 keypair encoded as PEM strings (for testing)."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


class TokenVerifier:
    """Verifies Ed25519 user access tokens issued by Identity."""

    def __init__(
        self,
        public_key_pem: Optional[str] = None,
        issuer: str = DEFAULT_ISSUER,
        audience: str = DEFAULT_AUDIENCE,
    ):
        self.issuer = issuer
        self.audience = audience
        self._public_key_pem = public_key_pem

        if self._public_key_pem:
            try:
                key_obj = serialization.load_pem_public_key(self._public_key_pem.encode("utf-8"))
                if not isinstance(key_obj, ed25519.Ed25519PublicKey):
                    raise TokenError("Ed25519 public key required")
            except Exception as exc:
                raise TokenError(f"Invalid public key: {exc}") from exc

    @classmethod
    def from_environment(cls) -> "TokenVerifier":
        pub_pem = os.environ.get("JWT_PUBLIC_KEY")
        pub_path = os.environ.get("JWT_PUBLIC_KEY_PATH")
        if not pub_pem and pub_path and Path(pub_path).is_file():
            pub_pem = Path(pub_path).read_text().strip()

        issuer = os.environ.get("JWT_ISSUER", DEFAULT_ISSUER)
        audience = os.environ.get("JWT_AUDIENCE", DEFAULT_AUDIENCE)
        return cls(public_key_pem=pub_pem, issuer=issuer, audience=audience)

    def decode_access_token(self, token: str) -> Dict[str, Any]:
        if not self._public_key_pem:
            raise TokenError("Public key is not configured for verifying access tokens")

        try:
            payload = jwt.decode(
                token,
                self._public_key_pem,
                algorithms=["EdDSA"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "require": ["sub", "role", "iss", "aud", "exp", "iat", "jti"],
                    "verify_signature": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("Access token has expired") from exc
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise TokenInvalidError(f"Access token is invalid: {exc}") from exc

        sub = payload.get("sub")
        if not sub:
            raise TokenInvalidError("Token missing subject")
        try:
            uuid.UUID(str(sub))
        except (ValueError, TypeError) as exc:
            raise TokenInvalidError("Invalid user id in token") from exc

        role = payload.get("role")
        if role not in VALID_ROLES:
            raise TokenInvalidError(f"Invalid role: {role}")

        return payload


_GLOBAL_VERIFIER: Optional[TokenVerifier] = None


def get_token_verifier() -> TokenVerifier:
    global _GLOBAL_VERIFIER
    if _GLOBAL_VERIFIER is None:
        _GLOBAL_VERIFIER = TokenVerifier.from_environment()
    return _GLOBAL_VERIFIER


def set_token_verifier(verifier: Optional[TokenVerifier]) -> None:
    global _GLOBAL_VERIFIER
    _GLOBAL_VERIFIER = verifier
