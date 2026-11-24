"""Unit tests for assistant config, health, JWT Ed25519, transport limits, secrets guard, rate limiter, and telemetry."""
from datetime import datetime, timedelta, timezone
import logging
import unittest
import uuid

import jwt

from app.config import AssistantSettings, parse_rate_limit, set_settings
from app.infrastructure.rate_limit import InMemoryRateLimiter
from app.infrastructure.secrets_guard import detect_sensitive_secret
from app.infrastructure.telemetry import MetricsRegistry, log_assistant_event
from app.infrastructure.tokens import (
    TokenExpiredError,
    TokenInvalidError,
    TokenVerifier,
    generate_ed25519_keypair,
)
from app.main import app
from tests.client import TestClient


def _sign_token(
    private_key_pem: str,
    *,
    sub: str = None,
    role: str = "USER",
    iss: str = "agrodiagnostico-identity",
    aud: str = "agrodiagnostico-api",
    expires_delta: timedelta = timedelta(minutes=15),
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "role": role,
        "iss": iss,
        "aud": aud,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, private_key_pem, algorithm="EdDSA")


class SecurityAndLimitsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()
        cls.other_priv_pem, _ = generate_ed25519_keypair()
        cls.client = TestClient(app)

    def tearDown(self):
        set_settings(None)

    def test_health_live_and_ready_states_never_leak_secrets(self):
        secret_sentinel = "AIzaSyFakeSecretValueForUnitTestOnly123456"
        set_settings(
            AssistantSettings(
                enabled=False,
                provider="gemini",
                gemini_api_key=secret_sentinel,
                jwt_public_key_pem=self.pub_pem,
            )
        )
        live = self.client.get("/health/live")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json(), {"status": "alive", "service": "assistant"})
        self.assertEqual(live.headers["cache-control"], "private, no-store")
        uuid.UUID(live.headers["x-correlation-id"])

        # Disabled -> 503 not_ready without leaking secret
        ready_disabled = self.client.get("/health/ready")
        self.assertEqual(ready_disabled.status_code, 503)
        self.assertEqual(ready_disabled.json(), {"status": "not_ready", "service": "assistant"})
        self.assertNotIn(secret_sentinel, ready_disabled.text)

        # Enabled gemini without API key -> 503 not_ready (no silent fake fallback)
        set_settings(
            AssistantSettings(
                enabled=True,
                provider="gemini",
                gemini_api_key=None,
                jwt_public_key_pem=self.pub_pem,
            )
        )
        self.assertEqual(self.client.get("/health/ready").status_code, 503)

        # Enabled fake without JWT public key -> 503 not_ready
        set_settings(
            AssistantSettings(
                enabled=True,
                provider="fake",
                jwt_public_key_pem=None,
            )
        )
        self.assertEqual(self.client.get("/health/ready").status_code, 503)

        # Enabled fake with valid Ed25519 key -> 200 ready
        set_settings(
            AssistantSettings(
                enabled=True,
                provider="fake",
                jwt_public_key_pem=self.pub_pem,
            )
        )
        ready_fake = self.client.get("/health/ready")
        self.assertEqual(ready_fake.status_code, 200)
        self.assertEqual(ready_fake.json(), {"status": "ready", "service": "assistant"})

        # Enabled gemini with API key and model -> 200 ready
        set_settings(
            AssistantSettings(
                enabled=True,
                provider="gemini",
                gemini_api_key=secret_sentinel,
                gemini_model="gemini-2.5-flash",
                jwt_public_key_pem=self.pub_pem,
            )
        )
        self.assertEqual(self.client.get("/health/ready").status_code, 200)
        self.assertNotIn(secret_sentinel, repr(AssistantSettings(gemini_api_key=secret_sentinel)))

    def test_correlation_id_echo_and_rejection(self):
        set_settings(AssistantSettings(enabled=True, provider="fake", jwt_public_key_pem=self.pub_pem))
        cid = str(uuid.uuid4())
        ok = self.client.get("/health/live", headers={"X-Correlation-ID": cid})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.headers["x-correlation-id"], cid)

        bad = self.client.get("/health/live", headers={"X-Correlation-ID": "not-a-uuid"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["code"], "INVALID_CORRELATION_ID")
        self.assertEqual(bad.headers["cache-control"], "private, no-store")
        uuid.UUID(bad.headers["x-correlation-id"])

    def test_transport_size_limit_returns_413(self):
        set_settings(
            AssistantSettings(
                enabled=True,
                provider="fake",
                max_transport_bytes=512,
                jwt_public_key_pem=self.pub_pem,
            )
        )
        oversized = b'{"message":"' + (b"a" * 600) + b'"}'
        resp = self.client.post("/api/v1/assistant/messages", raw_body=oversized)
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], "PAYLOAD_TOO_LARGE")
        self.assertEqual(resp.headers["cache-control"], "private, no-store")
        uuid.UUID(resp.headers["x-correlation-id"])

    def test_jwt_verification_positive_and_negative(self):
        verifier = TokenVerifier(public_key_pem=self.pub_pem)
        uid = str(uuid.uuid4())

        user_token = _sign_token(self.priv_pem, sub=uid, role="USER")
        principal = verifier.verify_principal(f"Bearer {user_token}")
        self.assertEqual(str(principal.id), uid)
        self.assertEqual(principal.role, "USER")
        self.assertFalse(principal.is_admin)

        admin_token = _sign_token(self.priv_pem, sub=uid, role="ADMIN")
        admin = verifier.verify_principal(f"Bearer {admin_token}")
        self.assertTrue(admin.is_admin)

        # Missing / bad scheme
        with self.assertRaises(TokenInvalidError):
            verifier.verify_principal(None)
        with self.assertRaises(TokenInvalidError):
            verifier.verify_principal("Basic abc123")

        # Expired
        expired = _sign_token(self.priv_pem, expires_delta=timedelta(seconds=-10))
        with self.assertRaises(TokenExpiredError):
            verifier.verify_principal(f"Bearer {expired}")

        # Wrong signing key
        wrong_sig = _sign_token(self.other_priv_pem)
        with self.assertRaises(TokenInvalidError):
            verifier.verify_principal(f"Bearer {wrong_sig}")

        # Wrong issuer / audience / internal service token / invalid role
        internal_tok = _sign_token(
            self.priv_pem,
            iss="agrodiagnostico-internal",
            aud="identity-internal",
            role="USER",
        )
        with self.assertRaises(TokenInvalidError):
            verifier.verify_principal(f"Bearer {internal_tok}")

        wrong_aud = _sign_token(self.priv_pem, aud="other-api")
        with self.assertRaises(TokenInvalidError):
            verifier.verify_principal(f"Bearer {wrong_aud}")

        bad_role = _sign_token(self.priv_pem, role="SUPERADMIN")
        with self.assertRaises(TokenInvalidError):
            verifier.verify_principal(f"Bearer {bad_role}")

    def test_secrets_guard_detects_credentials_and_allows_normal_spanish(self):
        fake_jwt = _sign_token(self.priv_pem)
        self.assertEqual(detect_sensitive_secret(f"Usa este token {fake_jwt}"), "JWT_TOKEN")
        self.assertEqual(
            detect_sensitive_secret("Mi clave es AIzaSyFakeKeyValueForTestingOnly99999"),
            "GOOGLE_API_KEY",
        )
        self.assertEqual(
            detect_sensitive_secret("Authorization: Bearer abcdef1234567890abcdef"),
            "BEARER_TOKEN",
        )
        self.assertEqual(
            detect_sensitive_secret("-----BEGIN PRIVATE KEY-----\nMIIE..."),
            "PRIVATE_KEY",
        )
        self.assertEqual(
            detect_sensitive_secret("mi password=SuperSecretPassword123"),
            "CREDENTIAL_ASSIGNMENT",
        )
        self.assertIsNone(detect_sensitive_secret("Llévame a mi historial de diagnósticos"))
        self.assertIsNone(detect_sensitive_secret("¿Qué significa NO_CONCLUYENTE en un análisis?"))
        self.assertIsNone(detect_sensitive_secret("¿Cómo tomo una buena fotografía de papa?"))

    def test_rate_limiter_enforces_per_identity_window(self):
        self.assertEqual(parse_rate_limit("20/60s"), (20, 60))
        with self.assertRaises(ValueError):
            parse_rate_limit("invalid")

        now = [100.0]
        limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60, clock=lambda: now[0])

        self.assertEqual(limiter.check_and_record("user-a"), (True, 0))
        self.assertEqual(limiter.check_and_record("user-a"), (True, 0))
        allowed, retry_after = limiter.check_and_record("user-a")
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)

        # Independent user is not blocked
        self.assertEqual(limiter.check_and_record("user-b"), (True, 0))

        # Window advances -> allowed again
        now[0] += 61.0
        self.assertEqual(limiter.check_and_record("user-a"), (True, 0))

    def test_telemetry_emits_only_safe_fields_and_blocks_user_id_labels(self):
        cid = str(uuid.uuid4())
        with self.assertLogs("agrodiagnostico.assistant", level="INFO") as captured:
            record = log_assistant_event(
                level=logging.INFO,
                event="assistant_request",
                correlation_id=cid,
                role="USER",
                intent="OPEN_HISTORY",
                decision="ALLOW",
                http_status=200,
                latency_ms=12.345,
                provider="fake",
            )
        self.assertEqual(record["correlation_id"], cid)
        self.assertEqual(record["intent"], "OPEN_HISTORY")
        self.assertEqual(record["latency_ms"], 12.35)
        self.assertEqual(len(captured.output), 1)
        self.assertNotIn("message", captured.output[0])
        self.assertNotIn("prompt", captured.output[0])

        metrics = MetricsRegistry()
        metrics.increment("assistant_requests_total", status="200", decision="ALLOW")
        self.assertEqual(metrics.snapshot()["assistant_requests_total{decision=ALLOW,status=200}"], 1)
        with self.assertRaises(ValueError):
            metrics.increment("assistant_requests_total", user_id="secret-user-id")


if __name__ == "__main__":
    unittest.main()
