"""Ed25519 (EdDSA) JWT verification for the assistant extension (ADR-0004 & ADR-0015).

Verification only: uses Identity's Ed25519 public key.
Never accesses Identity's database or signs tokens.
"""
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import jwt

from app.config import DEFAULT_AUDIENCE, DEFAULT_ISSUER, AssistantSettings, get_settings

VALID_ROLES = {"USER", "ADMIN"}
INTERNAL_ISSUER = "agrodiagnostico-internal"


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity derived strictly from verified JWT claims."""

    id: uuid.UUID
    role: Literal["USER", "ADMIN"]
    token_id: str

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


class TokenError(Exception):
    """Base error for JWT verification failures."""


class TokenExpiredError(TokenError):
    """Raised when an access token is expired."""


class TokenInvalidError(TokenError):
    """Raised when an access token is missing, malformed, internal, or fails signature checks."""


def generate_ed25519_keypair() -> Tuple[str, str]:
    """Generate an Ed25519 keypair encoded as PEM strings (for testing)."""
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


def extract_bearer_token(authorization_header: Optional[str]) -> str:
    """Extract Bearer token from Authorization header strictly."""
    if not authorization_header:
        raise TokenInvalidError("Missing Authorization header")
    parts = authorization_header.strip().split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise TokenInvalidError("Invalid Authorization scheme")
    return parts[1].strip()


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
            except TokenError:
                raise
            except Exception as exc:
                raise TokenError("Invalid Ed25519 public key") from exc

    @classmethod
    def from_settings(cls, settings: Optional[AssistantSettings] = None) -> "TokenVerifier":
        cfg = settings or get_settings()
        return cls(
            public_key_pem=cfg.jwt_public_key_pem,
            issuer=cfg.jwt_issuer,
            audience=cfg.jwt_audience,
        )

    def decode_access_token(self, token: str) -> Dict[str, Any]:
        if not self._public_key_pem:
            raise TokenInvalidError("Public key is not configured")

        try:
            unverified = jwt.decode(
                token,
                options={"verify_signature": False, "verify_exp": False},
            )
            if isinstance(unverified, dict) and unverified.get("iss") == INTERNAL_ISSUER:
                raise TokenInvalidError("Internal service tokens are not accepted")
        except TokenInvalidError:
            raise
        except Exception:
            pass

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
            raise TokenInvalidError("Access token is invalid") from exc

        sub = payload.get("sub")
        try:
            uuid.UUID(str(sub))
        except (ValueError, TypeError) as exc:
            raise TokenInvalidError("Invalid user id in token") from exc

        role = payload.get("role")
        if role not in VALID_ROLES:
            raise TokenInvalidError("Invalid role in token")

        return payload

    def verify_principal(self, authorization_header: Optional[str]) -> Principal:
        token = extract_bearer_token(authorization_header)
        payload = self.decode_access_token(token)
        return Principal(
            id=uuid.UUID(str(payload["sub"])),
            role=payload["role"],
            token_id=str(payload["jti"]),
        )


_GLOBAL_VERIFIER: Optional[TokenVerifier] = None


def get_token_verifier(settings: Optional[AssistantSettings] = None) -> TokenVerifier:
    if _GLOBAL_VERIFIER is not None:
        return _GLOBAL_VERIFIER
    return TokenVerifier.from_settings(settings)


def set_token_verifier(verifier: Optional[TokenVerifier]) -> None:
    global _GLOBAL_VERIFIER
    _GLOBAL_VERIFIER = verifier
