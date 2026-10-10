"""Internal service authentication primitives for Diagnosis service.

In accordance with ADR-0008 (D2):
- Dedicated Ed25519 keypair per AI worker instance, decoupled from Identity keys.
- Trusted key registry in Diagnosis: kid -> (public_key, principal="ai_inference", instance_id).
- Mandatory JWT claims:
    iss: 'agrodiagnostico-internal'
    aud: 'diagnosis-internal'
    sub: 'ai_inference'
    instance_id: matching instance_id registered for kid
    exp: max 60s lifetime from iat, zero grace period
    iat: unix epoch timestamp
    jti: UUID string
- lease_owner derived strictly from verified instance_id.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import jwt

INTERNAL_ISSUER = "agrodiagnostico-internal"
INTERNAL_AUDIENCE = "diagnosis-internal"
INTERNAL_PRINCIPAL = "ai_inference"
MAX_TOKEN_LIFETIME_SECONDS = 60


class InternalAuthError(Exception):
    """Base exception for internal authentication failures."""
    pass


class InternalTokenExpiredError(InternalAuthError):
    """Raised when an internal service token has expired."""
    pass


class InternalTokenInvalidError(InternalAuthError):
    """Raised when an internal service token is invalid or unauthorized."""
    pass


@dataclass(frozen=True)
class InternalServiceIdentity:
    """Verified identity of an internal worker instance."""
    instance_id: str
    kid: str
    principal: str = INTERNAL_PRINCIPAL

    @property
    def lease_owner(self) -> str:
        return self.instance_id


class TrustedKeyRegistry:
    """In-memory registry of trusted public keys for internal services."""

    def __init__(self):
        self._keys: Dict[str, Dict[str, Any]] = {}

    def register_key(
        self,
        kid: str,
        public_key_pem: str,
        instance_id: str,
        principal: str = INTERNAL_PRINCIPAL,
    ) -> None:
        """Register an Ed25519 public key for an instance."""
        try:
            pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
            if not isinstance(pub_key, ed25519.Ed25519PublicKey):
                raise ValueError("Key is not an Ed25519 public key")
        except Exception as exc:
            raise InternalTokenInvalidError(f"Invalid public key for kid '{kid}': {exc}") from exc

        self._keys[kid] = {
            "public_key": pub_key,
            "public_key_pem": public_key_pem,
            "instance_id": instance_id,
            "principal": principal,
        }

    def unregister_key(self, kid: str) -> None:
        self._keys.pop(kid, None)

    def get(self, kid: str) -> Optional[Dict[str, Any]]:
        return self._keys.get(kid)

    def is_trusted(self, kid: str) -> bool:
        return kid in self._keys

    @classmethod
    def from_environment(cls) -> "TrustedKeyRegistry":
        registry = cls()
        keys_json = os.environ.get("INTERNAL_SERVICE_KEYS_JSON")
        keys_file = os.environ.get("INTERNAL_SERVICE_KEYS_FILE")
        if not keys_json and keys_file and Path(keys_file).is_file():
            keys_json = Path(keys_file).read_text().strip()

        if keys_json:
            try:
                data = json.loads(keys_json)
                if isinstance(data, dict):
                    for kid, info in data.items():
                        registry.register_key(
                            kid=kid,
                            public_key_pem=info["public_key_pem"],
                            instance_id=info["instance_id"],
                            principal=info.get("principal", INTERNAL_PRINCIPAL),
                        )
                elif isinstance(data, list):
                    for info in data:
                        registry.register_key(
                            kid=info["kid"],
                            public_key_pem=info["public_key_pem"],
                            instance_id=info["instance_id"],
                            principal=info.get("principal", INTERNAL_PRINCIPAL),
                        )
            except Exception as exc:
                raise InternalAuthError(f"Failed to load trusted internal keys: {exc}") from exc
        return registry


_GLOBAL_REGISTRY: Optional[TrustedKeyRegistry] = None


def get_internal_key_registry() -> TrustedKeyRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = TrustedKeyRegistry.from_environment()
    return _GLOBAL_REGISTRY


def set_internal_key_registry(registry: TrustedKeyRegistry) -> None:
    global _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = registry


def generate_internal_keypair() -> Tuple[str, str]:
    """Generate Ed25519 keypair for internal service authentication."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def create_internal_token(
    private_key_pem: str,
    kid: str,
    instance_id: str,
    lifetime_seconds: int = MAX_TOKEN_LIFETIME_SECONDS,
    jti: Optional[str] = None,
    iat: Optional[int] = None,
    iss: str = INTERNAL_ISSUER,
    aud: str = INTERNAL_AUDIENCE,
    sub: str = INTERNAL_PRINCIPAL,
) -> str:
    """Issue a signed internal JWT for a worker instance."""
    now_ts = int(datetime.now(timezone.utc).timestamp())
    issue_ts = iat if iat is not None else now_ts
    exp_ts = issue_ts + lifetime_seconds

    payload = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "instance_id": instance_id,
        "iat": issue_ts,
        "exp": exp_ts,
        "jti": jti or str(uuid.uuid4()),
    }
    return jwt.encode(
        payload,
        private_key_pem,
        algorithm="EdDSA",
        headers={"kid": kid},
    )


def verify_internal_token(
    token: str,
    registry: Optional[TrustedKeyRegistry] = None,
) -> InternalServiceIdentity:
    """Verify an internal service token against the trusted key registry."""
    if registry is None:
        registry = get_internal_key_registry()

    try:
        unverified_headers = jwt.get_unverified_header(token)
    except Exception as exc:
        raise InternalTokenInvalidError("Invalid token format") from exc

    kid = unverified_headers.get("kid")
    if not kid:
        raise InternalTokenInvalidError("Token missing required 'kid' header")

    alg = unverified_headers.get("alg")
    if alg != "EdDSA":
        raise InternalTokenInvalidError(f"Unsupported algorithm '{alg}', expected EdDSA")

    key_record = registry.get(kid)
    if not key_record:
        raise InternalTokenInvalidError(f"Untrusted or unknown 'kid': {kid}")

    public_key = key_record["public_key"]
    registered_instance_id = key_record["instance_id"]
    registered_principal = key_record["principal"]

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            issuer=INTERNAL_ISSUER,
            audience=INTERNAL_AUDIENCE,
            options={
                "require": ["iss", "aud", "sub", "instance_id", "exp", "iat", "jti"],
                "verify_signature": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise InternalTokenExpiredError("Internal token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InternalTokenInvalidError(f"Internal token validation failed: {exc}") from exc

    # Validate sub
    sub = payload.get("sub")
    if sub != registered_principal:
        raise InternalTokenInvalidError(f"Token sub '{sub}' does not match principal '{registered_principal}'")

    # Validate instance_id matches registration for this kid
    instance_id = payload.get("instance_id")
    if not instance_id or instance_id != registered_instance_id:
        raise InternalTokenInvalidError(
            f"Token instance_id '{instance_id}' does not match registered instance for kid '{registered_instance_id}'"
        )

    # Validate lifetime: cannot exceed MAX_TOKEN_LIFETIME_SECONDS
    iat = payload.get("iat")
    exp = payload.get("exp")
    if not isinstance(iat, (int, float)) or not isinstance(exp, (int, float)):
        raise InternalTokenInvalidError("iat and exp must be numeric timestamps")

    if exp - iat > MAX_TOKEN_LIFETIME_SECONDS:
        raise InternalTokenInvalidError(
            f"Token lifetime {exp - iat}s exceeds maximum permitted {MAX_TOKEN_LIFETIME_SECONDS}s"
        )

    # Validate jti is valid UUID
    jti = payload.get("jti")
    try:
        uuid.UUID(str(jti))
    except (ValueError, TypeError):
        raise InternalTokenInvalidError("jti must be a valid UUID")

    return InternalServiceIdentity(
        instance_id=instance_id,
        kid=kid,
        principal=sub,
    )

