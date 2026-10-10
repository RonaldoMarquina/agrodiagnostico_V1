"""Dedicated internal authentication client for AI Inference worker.

In accordance with ADR-0008 (D2):
- Loads worker instance's private Ed25519 key.
- Issues short-lived (max 60s) internal JWTs for communication with Diagnosis /internal API.
- Never accesses or stores user tokens or Identity private keys.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional, Tuple
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import jwt

INTERNAL_ISSUER = "agrodiagnostico-internal"
INTERNAL_AUDIENCE = "diagnosis-internal"
INTERNAL_PRINCIPAL = "ai_inference"
MAX_TOKEN_LIFETIME_SECONDS = 60


def generate_worker_keypair() -> Tuple[str, str]:
    """Generate Ed25519 keypair for worker instance."""
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


class InternalTokenSigner:
    """Signs internal service JWTs using the instance's Ed25519 private key."""

    def __init__(self, private_key_pem: str, kid: str, instance_id: str):
        self._private_key_pem = private_key_pem
        self.kid = kid
        self.instance_id = instance_id

    @classmethod
    def from_environment(cls) -> Optional["InternalTokenSigner"]:
        priv_pem = os.environ.get("INTERNAL_WORKER_PRIVATE_KEY")
        priv_file = os.environ.get("INTERNAL_WORKER_PRIVATE_KEY_FILE")
        if not priv_pem and priv_file and Path(priv_file).is_file():
            priv_pem = Path(priv_file).read_text().strip()

        kid = os.environ.get("INTERNAL_WORKER_KID")
        instance_id = os.environ.get("INTERNAL_WORKER_INSTANCE_ID")

        if priv_pem and kid and instance_id:
            return cls(private_key_pem=priv_pem, kid=kid, instance_id=instance_id)
        return None

    def issue_token(self, lifetime_seconds: int = MAX_TOKEN_LIFETIME_SECONDS) -> str:
        """Issue a short-lived internal JWT."""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        payload = {
            "iss": INTERNAL_ISSUER,
            "aud": INTERNAL_AUDIENCE,
            "sub": INTERNAL_PRINCIPAL,
            "instance_id": self.instance_id,
            "iat": now_ts,
            "exp": now_ts + min(lifetime_seconds, MAX_TOKEN_LIFETIME_SECONDS),
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(
            payload,
            self._private_key_pem,
            algorithm="EdDSA",
            headers={"kid": self.kid},
        )

