"""Tests for correlation headers, error envelopes, and Ed25519 authentication/RBAC in Diagnosis."""
import time
import unittest
import uuid
import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_principal, require_admin, require_user
from app.infrastructure.security import Principal
from app.infrastructure.tokens import (
    TokenVerifier,
    generate_ed25519_keypair,
    set_token_verifier,
)
from app.main import app as main_app
from tests.client import TestClient


class DummyPayload(BaseModel):
    name: str


class TestAuthAndEnvelope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()
        cls.verifier = TokenVerifier(public_key_pem=cls.pub_pem)
        set_token_verifier(cls.verifier)

        # Set up a test sub-router or test endpoints on main_app for auth testing
        @main_app.get("/test/user-only")
        def test_user_endpoint(principal: Principal = Depends(require_user)):
            return {"user_id": str(principal.id), "role": principal.role}

        @main_app.get("/test/admin-only")
        def test_admin_endpoint(principal: Principal = Depends(require_admin)):
            return {"admin_id": str(principal.id), "role": principal.role}

        @main_app.post("/test/validation-body")
        def test_validation_endpoint(payload: DummyPayload):
            return {"received": payload.name}

        @main_app.get("/test/unhandled-error")
        def test_unhandled_endpoint():
            raise RuntimeError("SecretDatabasePassword123 should never leak!")

        cls.client = TestClient(main_app)

    @classmethod
    def tearDownClass(cls):
        set_token_verifier(None)

    def _create_token(
        self,
        sub: str = None,
        role: str = "USER",
        iss: str = "agrodiagnostico-identity",
        aud: str = "agrodiagnostico-api",
        expires_in: int = 60,
        extra_claims: dict = None,
        algorithm: str = "EdDSA",
        key: str = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": str(sub or uuid.uuid4()),
            "role": role,
            "iss": iss,
            "aud": aud,
            "iat": now,
            "exp": now + expires_in,
            "jti": str(uuid.uuid4()),
        }
        if extra_claims:
            claims.update(extra_claims)

        signing_key = key or self.priv_pem
        return jwt.encode(claims, signing_key, algorithm=algorithm)

    def test_correlation_id_generated_when_absent(self):
        resp = self.client.get("/health/live")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("x-correlation-id", resp.headers)
        cid = resp.headers["x-correlation-id"]
        # Ensure it is a valid UUID
        self.assertEqual(str(uuid.UUID(cid)), cid)
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

    def test_correlation_id_propagated_when_valid(self):
        client_cid = str(uuid.uuid4())
        resp = self.client.get("/health/live", headers={"X-Correlation-ID": client_cid})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-correlation-id"), client_cid)
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

    def test_invalid_correlation_id_rejected_with_400(self):
        for bad_cid in ["not-a-uuid", "12345", "", "11111111-2222"]:
            resp = self.client.get("/health/live", headers={"X-Correlation-ID": bad_cid})
            self.assertEqual(resp.status_code, 400)
            data = resp.json()
            self.assertEqual(data["code"], "INVALID_CORRELATION_ID")
            self.assertIn("correlation_id", data)
            # Response must still have a valid UUID in header and body
            self.assertEqual(str(uuid.UUID(data["correlation_id"])), data["correlation_id"])
            self.assertEqual(resp.headers.get("x-correlation-id"), data["correlation_id"])
            self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

    def test_request_validation_error_envelope(self):
        resp = self.client.post("/test/validation-body", json={"wrong_field": 123})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["code"], "INVALID_REQUEST")
        self.assertIn("message", data)
        self.assertIn("correlation_id", data)
        self.assertIn("details", data)
        self.assertIsInstance(data["details"], list)
        self.assertTrue(len(data["details"]) > 0)
        self.assertEqual(data["details"][0]["field"], "name")
        self.assertEqual(data["details"][0]["code"], "INVALID_FIELD")
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

    def test_unhandled_exception_does_not_leak_internals(self):
        resp = self.client.get("/test/unhandled-error")
        self.assertEqual(resp.status_code, 500)
        data = resp.json()
        self.assertEqual(data["code"], "INTERNAL_ERROR")
        self.assertIn("message", data)
        self.assertNotIn("SecretDatabasePassword123", resp.text)
        self.assertNotIn("Traceback", resp.text)
        self.assertIn("correlation_id", data)
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

    def test_user_endpoint_missing_token_returns_401(self):
        resp = self.client.get("/test/user-only")
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertEqual(data["code"], "UNAUTHORIZED")
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

    def test_user_endpoint_valid_token(self):
        user_id = str(uuid.uuid4())
        token = self._create_token(sub=user_id, role="USER")
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["user_id"], user_id)
        self.assertEqual(data["role"], "USER")

    def test_user_endpoint_expired_token(self):
        token = self._create_token(expires_in=-10)
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertEqual(data["code"], "TOKEN_EXPIRED")

    def test_user_endpoint_tampered_token(self):
        token = self._create_token()
        parts = token.split(".")
        tampered = f"{parts[0]}.eyJyYW5kb20iOiJib2d1cyJ9.{parts[2]}"
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {tampered}"})
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertEqual(data["code"], "TOKEN_INVALID")

    def test_user_endpoint_wrong_issuer_and_audience(self):
        token_bad_iss = self._create_token(iss="bad-iss")
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {token_bad_iss}"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "TOKEN_INVALID")

        token_bad_aud = self._create_token(aud="bad-aud")
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {token_bad_aud}"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "TOKEN_INVALID")

    def test_user_endpoint_wrong_algorithm(self):
        claims = {
            "sub": str(uuid.uuid4()),
            "role": "USER",
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "jti": str(uuid.uuid4()),
        }
        hs_token = jwt.encode(claims, "secret", algorithm="HS256")
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {hs_token}"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "TOKEN_INVALID")

    def test_user_endpoint_invalid_sub_or_role(self):
        bad_sub_token = self._create_token(sub="not-uuid")
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {bad_sub_token}"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "TOKEN_INVALID")

        bad_role_token = self._create_token(role="SUPERADMIN")
        resp = self.client.get("/test/user-only", headers={"Authorization": f"Bearer {bad_role_token}"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], "TOKEN_INVALID")

    def test_admin_endpoint_with_user_returns_403(self):
        token = self._create_token(role="USER")
        resp = self.client.get("/test/admin-only", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertEqual(data["code"], "FORBIDDEN")
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

    def test_admin_endpoint_with_admin_returns_200(self):
        admin_id = str(uuid.uuid4())
        token = self._create_token(sub=admin_id, role="ADMIN")
        resp = self.client.get("/test/admin-only", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["admin_id"], admin_id)
        self.assertEqual(data["role"], "ADMIN")


if __name__ == "__main__":
    unittest.main()
