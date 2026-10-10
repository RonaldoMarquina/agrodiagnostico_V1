"""Unit tests for internal service authentication (Task 3.1).

Tests:
- Ed25519 keypair generation and trusted key registry.
- Internal service JWT issuance and verification:
  - Required claims: iss, aud, sub, instance_id, exp, iat, jti.
  - kid matching and instance_id binding.
  - Max 60s lifetime enforcement.
  - Zero grace period on expiration.
  - Invalid / mismatched instance_id rejection (401).
  - Untrusted kid / signature tampering rejection (401).
- Route isolation:
  - Valid USER / ADMIN token on /internal/* routes returns 403 FORBIDDEN.
  - Internal service token on /api/v1/diagnoses routes returns 403 FORBIDDEN.
"""
from datetime import datetime, timedelta, timezone
import os
from typing import Optional
import unittest
import uuid

import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.domain.models import Base, Diagnosis
from app.infrastructure.internal_auth import (
    INTERNAL_AUDIENCE,
    INTERNAL_ISSUER,
    INTERNAL_PRINCIPAL,
    InternalServiceIdentity,
    InternalTokenExpiredError,
    InternalTokenInvalidError,
    TrustedKeyRegistry,
    create_internal_token,
    generate_internal_keypair,
    set_internal_key_registry,
    verify_internal_token,
)
from app.infrastructure.tokens import (
    TokenVerifier,
    generate_ed25519_keypair as generate_user_keypair,
    set_token_verifier,
)
from app.main import app as main_app
from tests.client import TestClient


class TestInternalAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Setup user identity keys
        cls.user_priv_pem, cls.user_pub_pem = generate_user_keypair()
        cls.user_verifier = TokenVerifier(public_key_pem=cls.user_pub_pem)
        set_token_verifier(cls.user_verifier)

        # 2. Setup internal worker keys
        cls.w1_priv, cls.w1_pub = generate_internal_keypair()
        cls.w2_priv, cls.w2_pub = generate_internal_keypair()

        cls.registry = TrustedKeyRegistry()
        cls.registry.register_key("kid-worker-1", cls.w1_pub, instance_id="worker-inst-1")
        cls.registry.register_key("kid-worker-2", cls.w2_pub, instance_id="worker-inst-2")
        set_internal_key_registry(cls.registry)

        # 3. Setup test database and client
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        main_app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(main_app)

    @classmethod
    def tearDownClass(cls):
        set_token_verifier(None)
        set_internal_key_registry(None)
        main_app.dependency_overrides.clear()

    def make_user_token(self, role: str = "USER", user_id: Optional[uuid.UUID] = None) -> str:
        uid = user_id or uuid.uuid4()
        now = datetime.now(timezone.utc)
        payload = {
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "sub": str(uid),
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, self.user_priv_pem, algorithm="EdDSA")

    def test_internal_token_issuance_and_verification_success(self):
        token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
        )
        identity = verify_internal_token(token, self.registry)
        self.assertEqual(identity.instance_id, "worker-inst-1")
        self.assertEqual(identity.lease_owner, "worker-inst-1")
        self.assertEqual(identity.kid, "kid-worker-1")
        self.assertEqual(identity.principal, INTERNAL_PRINCIPAL)

    def test_internal_token_untrusted_kid_rejected(self):
        token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="unknown-kid",
            instance_id="worker-inst-1",
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token, self.registry)

    def test_internal_token_tampered_signature_rejected(self):
        # Signed with w2 key but claiming kid-worker-1
        token = create_internal_token(
            private_key_pem=self.w2_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token, self.registry)

    def test_internal_token_instance_id_mismatch_rejected(self):
        # Token claims instance worker-inst-2 but signed with kid-worker-1
        token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-2",
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token, self.registry)

    def test_internal_token_wrong_claims_rejected(self):
        # Wrong issuer
        token_bad_iss = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
            iss="wrong-issuer",
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token_bad_iss, self.registry)

        # Wrong audience
        token_bad_aud = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
            aud="wrong-audience",
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token_bad_aud, self.registry)

        # Wrong subject
        token_bad_sub = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
            sub="not_ai_inference",
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token_bad_sub, self.registry)

    def test_internal_token_max_lifetime_exceeded_rejected(self):
        # Lifetime of 61 seconds exceeds maximum of 60 seconds
        token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
            lifetime_seconds=61,
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token, self.registry)

    def test_internal_token_expired_rejected_without_grace(self):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
            iat=now_ts - 100,
            lifetime_seconds=60,  # expired 40s ago
        )
        with self.assertRaises(InternalTokenExpiredError):
            verify_internal_token(token, self.registry)

    def test_internal_token_invalid_jti_rejected(self):
        token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
            jti="not-a-uuid",
        )
        with self.assertRaises(InternalTokenInvalidError):
            verify_internal_token(token, self.registry)

    def test_valid_user_token_on_internal_route_returns_403(self):
        user_token = self.make_user_token(role="USER")
        diag_id = uuid.uuid4()

        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "FORBIDDEN")

        admin_token = self.make_user_token(role="ADMIN")
        resp_admin = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(resp_admin.status_code, 403)
        self.assertEqual(resp_admin.json()["code"], "FORBIDDEN")

    def test_internal_token_on_user_route_returns_403(self):
        internal_token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-worker-1",
            instance_id="worker-inst-1",
        )
        resp = self.client.get(
            "/api/v1/diagnoses",
            headers={"Authorization": f"Bearer {internal_token}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "FORBIDDEN")

    def test_missing_or_malformed_auth_on_internal_route_returns_401(self):
        diag_id = uuid.uuid4()
        # Missing auth header
        resp_none = self.client.post(f"/internal/diagnoses/{diag_id}/claim")
        self.assertEqual(resp_none.status_code, 401)
        self.assertEqual(resp_none.json()["code"], "UNAUTHORIZED")

        # Malformed bearer
        resp_bad = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        self.assertEqual(resp_bad.status_code, 401)
        self.assertEqual(resp_bad.json()["code"], "UNAUTHORIZED")


if __name__ == "__main__":
    unittest.main()
