"""Unit tests for Notification JWT auth, correlation middleware, and HMAC cursors (Task 4.1)."""
from datetime import datetime, timezone
import os
import time
import unittest
from unittest.mock import patch
import uuid

from fastapi import HTTPException
import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base
from app.infrastructure.cursor import (
    CURSOR_PURPOSE_USER_NOTIFICATIONS,
    decode_cursor,
    encode_cursor,
)
from app.infrastructure.tokens import (
    DEFAULT_AUDIENCE,
    DEFAULT_ISSUER,
    TokenVerifier,
    generate_ed25519_keypair,
    set_token_verifier,
)
from app.main import app
from app.persistence import get_db
from tests.client import TestClient


def _sign_user_token(
    priv_pem: str,
    user_id: uuid.UUID,
    role: str = "USER",
    iss: str = DEFAULT_ISSUER,
    aud: str = DEFAULT_AUDIENCE,
    exp_offset: int = 900,
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + exp_offset,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, priv_pem, algorithm="EdDSA")


class TestAuthAndCursor(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.priv_pem, self.pub_pem = generate_ed25519_keypair()
        self.other_priv_pem, _ = generate_ed25519_keypair()
        set_token_verifier(TokenVerifier(public_key_pem=self.pub_pem))

        self.cursor_key = "a" * 64
        self.env_patcher = patch.dict(os.environ, {"CURSOR_SIGNING_KEY": self.cursor_key})
        self.env_patcher.start()

        self.user_a = uuid.uuid4()
        self.user_b = uuid.uuid4()

    def tearDown(self):
        self.env_patcher.stop()
        app.dependency_overrides.clear()
        set_token_verifier(None)
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_correlation_header_echoed_generated_and_validated(self):
        token = _sign_user_token(self.priv_pem, self.user_a)
        cid = str(uuid.uuid4())

        resp = self.client.get(
            "/api/v1/notification-preferences",
            headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": cid},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-correlation-id"), cid)
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")

        # Auto-generated UUID when omitted
        resp_gen = self.client.get(
            "/api/v1/notification-preferences",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp_gen.status_code, 200)
        uuid.UUID(resp_gen.headers.get("x-correlation-id"))

        # Malformed correlation header rejected with 400
        resp_bad = self.client.get(
            "/api/v1/notification-preferences",
            headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": "not-a-uuid"},
        )
        self.assertEqual(resp_bad.status_code, 400)
        body = resp_bad.json()
        self.assertEqual(body["code"], "INVALID_CORRELATION_ID")
        self.assertEqual(body["correlation_id"], resp_bad.headers.get("x-correlation-id"))

    def test_missing_expired_and_invalid_tokens_return_401(self):
        self.assertEqual(self.client.get("/api/v1/notifications").status_code, 401)

        expired = _sign_user_token(self.priv_pem, self.user_a, exp_offset=-10)
        resp_exp = self.client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {expired}"},
        )
        self.assertEqual(resp_exp.status_code, 401)
        self.assertEqual(resp_exp.json()["code"], "TOKEN_EXPIRED")

        wrong_key = _sign_user_token(self.other_priv_pem, self.user_a)
        resp_key = self.client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {wrong_key}"},
        )
        self.assertEqual(resp_key.status_code, 401)
        self.assertEqual(resp_key.json()["code"], "TOKEN_INVALID")

    def test_internal_service_token_rejected_with_403_on_user_routes(self):
        internal_tok = _sign_user_token(
            self.priv_pem,
            self.user_a,
            iss="agrodiagnostico-internal",
            aud="identity-internal",
        )
        resp = self.client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {internal_tok}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "FORBIDDEN")

    def test_cursor_hmac_integrity_owner_purpose_and_key_rotation(self):
        now = datetime(2026, 11, 23, 18, 0, 0, tzinfo=timezone.utc)
        notif_id = uuid.uuid4()
        cursor = encode_cursor(now, notif_id, self.user_a, CURSOR_PURPOSE_USER_NOTIFICATIONS)

        dec_dt, dec_id = decode_cursor(cursor, self.user_a, CURSOR_PURPOSE_USER_NOTIFICATIONS)
        self.assertEqual(dec_dt, now)
        self.assertEqual(dec_id, notif_id)

        # Foreign user cursor rejected
        with self.assertRaises(HTTPException) as ctx_user:
            decode_cursor(cursor, self.user_b, CURSOR_PURPOSE_USER_NOTIFICATIONS)
        self.assertEqual(ctx_user.exception.status_code, 400)

        # Wrong purpose (e.g. cursor from diagnosis) rejected
        diag_cursor = encode_cursor(now, notif_id, self.user_a, "user_diagnoses")
        with self.assertRaises(HTTPException) as ctx_purp:
            decode_cursor(diag_cursor, self.user_a, CURSOR_PURPOSE_USER_NOTIFICATIONS)
        self.assertEqual(ctx_purp.exception.status_code, 400)

        # Tampered cursor rejected
        tampered = cursor[:-2] + ("AA" if not cursor.endswith("AA") else "BB")
        with self.assertRaises(HTTPException) as ctx_tamper:
            decode_cursor(tampered, self.user_a, CURSOR_PURPOSE_USER_NOTIFICATIONS)
        self.assertEqual(ctx_tamper.exception.status_code, 400)

        # Rotated signing key invalidates prior cursor
        with patch.dict(os.environ, {"CURSOR_SIGNING_KEY": "b" * 64}):
            with self.assertRaises(HTTPException) as ctx_rot:
                decode_cursor(cursor, self.user_a, CURSOR_PURPOSE_USER_NOTIFICATIONS)
            self.assertEqual(ctx_rot.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
