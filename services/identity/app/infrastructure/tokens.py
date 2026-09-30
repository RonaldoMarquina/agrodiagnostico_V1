"""Asymmetric JWT token management using Ed25519 (EdDSA algorithm).

In accordance with ADR-0004:
- Algorithm: EdDSA (Ed25519 curve)
- Identity signs access tokens with private key.
- Instances/services verify tokens with public key.
- Mandatory claims: sub, role, iss, aud, exp, iat, jti.
- The private key is never stored in the source code repository.
"""
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

DEFAULT_ISSUER = "agrodiagnostico-identity"
DEFAULT_AUDIENCE = "agrodiagnostico-api"
ACCESS_TOKEN_EXPIRE_SECONDS = 900  # 15 minutes


class TokenError(Exception):
    """Base class for token-related errors."""
    pass


class TokenExpiredError(TokenError):
    """Raised when an access token has expired."""
    pass


class TokenInvalidError(TokenError):
    """Raised when an access token is structurally invalid or fails signature verification."""
    pass


def generate_ed25519_keypair() -> Tuple[str, str]:
    """Generate a new Ed25519 keypair encoded as PEM strings."""
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


class TokenManager:
    """Manages creation and verification of Ed25519 JWT access tokens."""

    def __init__(
        self,
        private_key_pem: Optional[str] = None,
        public_key_pem: Optional[str] = None,
        issuer: str = DEFAULT_ISSUER,
        audience: str = DEFAULT_AUDIENCE,
    ):
        self.issuer = issuer
        self.audience = audience
        self._private_key_pem = private_key_pem
        self._public_key_pem = public_key_pem

        # If private key is provided but public key is not, derive public key
        if self._private_key_pem and not self._public_key_pem:
            priv_obj = serialization.load_pem_private_key(
                self._private_key_pem.encode("utf-8"), password=None
            )
            pub_obj = priv_obj.public_key()
            self._public_key_pem = pub_obj.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")

    @classmethod
    def from_environment(cls) -> "TokenManager":
        """Load keys from environment variables or secret files."""
        priv_pem = os.environ.get("JWT_PRIVATE_KEY")
        priv_path = os.environ.get("JWT_PRIVATE_KEY_PATH")
        if not priv_pem and priv_path and Path(priv_path).is_file():
            priv_pem = Path(priv_path).read_text().strip()

        pub_pem = os.environ.get("JWT_PUBLIC_KEY")
        pub_path = os.environ.get("JWT_PUBLIC_KEY_PATH")
        if not pub_pem and pub_path and Path(pub_path).is_file():
            pub_pem = Path(pub_path).read_text().strip()

        issuer = os.environ.get("JWT_ISSUER", DEFAULT_ISSUER)
        audience = os.environ.get("JWT_AUDIENCE", DEFAULT_AUDIENCE)

        return cls(
            private_key_pem=priv_pem,
            public_key_pem=pub_pem,
            issuer=issuer,
            audience=audience,
        )

    def create_access_token(
        self,
        user_id: str | uuid.UUID,
        role: str,
        expires_in_seconds: int = ACCESS_TOKEN_EXPIRE_SECONDS,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create and sign an Ed25519 JWT access token with all normative claims."""
        if not self._private_key_pem:
            raise TokenError("Private key is not configured for signing access tokens")

        now = int(time.time())
        claims = {
            "sub": str(user_id),
            "role": role,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": now,
            "exp": now + expires_in_seconds,
            "jti": str(uuid.uuid4()),
        }
        if extra_claims:
            for k, v in extra_claims.items():
                if k not in claims:
                    claims[k] = v

        return jwt.encode(claims, self._private_key_pem, algorithm="EdDSA")

    def decode_access_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode an access token using the public key."""
        if not self._public_key_pem:
            raise TokenError("Public key is not configured for verifying access tokens")

        try:
            payload = jwt.decode(
                token,
                self._public_key_pem,
                algorithms=["EdDSA"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["sub", "role", "iss", "aud", "exp", "iat", "jti"]},
            )
            return payload
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Access token has expired") from e
        except (jwt.InvalidTokenError, ValueError) as e:
            raise TokenInvalidError(f"Access token is invalid: {str(e)}") from e


# Global default manager initialized from environment
_GLOBAL_MANAGER: Optional[TokenManager] = None


def get_token_manager() -> TokenManager:
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = TokenManager.from_environment()
    return _GLOBAL_MANAGER


def set_token_manager(manager: TokenManager) -> None:
    global _GLOBAL_MANAGER
    _GLOBAL_MANAGER = manager
