"""Integration tests for Authentication API endpoints (Group 4)."""
import unittest
from tests.client import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import DEFAULT_ALLOWED_ORIGINS
from app.domain.models import AuditLog, Base, RefreshSession, User
from app.infrastructure.email import InMemoryEmailSender, set_email_sender
from app.infrastructure.tokens import TokenManager, generate_ed25519_keypair, set_token_manager
from app.main import app
from app.persistence import get_db


class TestAuthApi(unittest.TestCase):
    def setUp(self):
        # In-memory SQLite with StaticPool so all connections share the same memory DB
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Setup cryptographic test keys
        priv, pub = generate_ed25519_keypair()
        self.token_manager = TokenManager(private_key_pem=priv, public_key_pem=pub)
        set_token_manager(self.token_manager)

        # Setup test email sender
        self.email_sender = InMemoryEmailSender()
        set_email_sender(self.email_sender)

        self.allowed_origin = "http://localhost:3000"

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)

    def test_register_success(self):
        res = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "farmer@example.com",
                "password": "ValidPassword123!",
                "display_name": "Agricultor",
            },
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["email"], "farmer@example.com")
        self.assertEqual(data["display_name"], "Agricultor")
        self.assertEqual(data["role"], "USER")
        self.assertIn("Cache-Control", res.headers)
        self.assertEqual(res.headers["Cache-Control"], "private, no-store")
        self.assertIn("X-Correlation-ID", res.headers)

    def test_register_rejects_extra_fields(self):
        res = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "farmer@example.com",
                "password": "ValidPassword123!",
                "display_name": "Agricultor",
                "role": "ADMIN",  # Forbidden extra field
            },
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data["code"], "INVALID_REQUEST")

    def test_register_rejects_short_password(self):
        res = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "farmer@example.com",
                "password": "short",  # < 12 chars
                "display_name": "Agricultor",
            },
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data["code"], "INVALID_REQUEST")

    def test_register_duplicate_returns_409(self):
        payload = {
            "email": "farmer@example.com",
            "password": "ValidPassword123!",
            "display_name": "Agricultor",
        }
        self.client.post("/api/v1/auth/register", json=payload)
        res = self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(res.status_code, 409)
        data = res.json()
        self.assertEqual(data["code"], "ACCOUNT_UNAVAILABLE")

    def test_login_origin_validation(self):
        # Missing Origin -> 400
        res = self.client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "ValidPassword123!"},
        )
        self.assertEqual(res.status_code, 400)

        # Untrusted Origin -> 403
        res = self.client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://malicious-site.example"},
            json={"email": "test@example.com", "password": "ValidPassword123!"},
        )
        self.assertEqual(res.status_code, 403)

    def test_login_flow_and_audit(self):
        # 1. Register user
        self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "user@example.com",
                "password": "ValidPassword123!",
                "display_name": "Usuario Test",
            },
        )

        # 2. Login with wrong password -> 401 & audit log
        res_fail = self.client.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "user@example.com", "password": "WrongPassword123!"},
        )
        self.assertEqual(res_fail.status_code, 401)
        self.assertEqual(res_fail.json()["code"], "INVALID_CREDENTIALS")

        with self.TestingSessionLocal() as db:
            failed_audit = db.query(AuditLog).filter(AuditLog.event_type == "LOGIN_FAILED").first()
            self.assertIsNotNone(failed_audit)

        # 3. Login with correct password -> 200 & cookies & audit log
        res_ok = self.client.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "user@example.com", "password": "ValidPassword123!"},
        )
        self.assertEqual(res_ok.status_code, 200)
        data = res_ok.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["token_type"], "Bearer")
        self.assertIn("csrf_token", data)

        # Check cookies
        cookies = res_ok.cookies
        self.assertIn("__Secure-agro_refresh", cookies)
        self.assertIn("csrf_token", cookies)

        with self.TestingSessionLocal() as db:
            success_audit = db.query(AuditLog).filter(AuditLog.event_type == "LOGIN_SUCCESS").first()
            self.assertIsNotNone(success_audit)
            sessions = db.query(RefreshSession).all()
            self.assertEqual(len(sessions), 1)

    def test_refresh_rotation_and_reuse_detection(self):
        # 1. Register & login
        self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "user@example.com",
                "password": "ValidPassword123!",
                "display_name": "Usuario Test",
            },
        )
        login_res = self.client.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "user@example.com", "password": "ValidPassword123!"},
        )
        refresh_cookie_1 = login_res.cookies["__Secure-agro_refresh"]
        csrf_token_1 = login_res.json()["csrf_token"]

        # 2. Refresh with valid token and matching CSRF header
        refresh_res_1 = self.client.post(
            "/api/v1/auth/refresh",
            headers={
                "Origin": self.allowed_origin,
                "X-CSRF-Token": csrf_token_1,
            },
            cookies={
                "__Secure-agro_refresh": refresh_cookie_1,
                "csrf_token": csrf_token_1,
            },
        )
        self.assertEqual(refresh_res_1.status_code, 200)
        refresh_cookie_2 = refresh_res_1.cookies["__Secure-agro_refresh"]
        csrf_token_2 = refresh_res_1.json()["csrf_token"]
        self.assertNotEqual(refresh_cookie_1, refresh_cookie_2)

        # 3. REUSE DETECTION: Attempt to use old refresh_cookie_1 again!
        reuse_res = self.client.post(
            "/api/v1/auth/refresh",
            headers={
                "Origin": self.allowed_origin,
                "X-CSRF-Token": csrf_token_1,
            },
            cookies={
                "__Secure-agro_refresh": refresh_cookie_1,
                "csrf_token": csrf_token_1,
            },
        )
        self.assertEqual(reuse_res.status_code, 401)
        self.assertEqual(reuse_res.json()["code"], "SESSION_REUSE_DETECTED")

        # 4. Verify that entire family was revoked in DB
        with self.TestingSessionLocal() as db:
            reuse_log = db.query(AuditLog).filter(AuditLog.event_type == "REFRESH_TOKEN_REUSE_DETECTED").first()
            self.assertIsNotNone(reuse_log)

            # Even token 2 should now be revoked!
            sessions = db.query(RefreshSession).all()
            for s in sessions:
                self.assertIsNotNone(s.revoked_at)

        # 5. Subsequent attempt with refresh_cookie_2 must now fail (family was revoked)
        subsequent_res = self.client.post(
            "/api/v1/auth/refresh",
            headers={
                "Origin": self.allowed_origin,
                "X-CSRF-Token": csrf_token_2,
            },
            cookies={
                "__Secure-agro_refresh": refresh_cookie_2,
                "csrf_token": csrf_token_2,
            },
        )
        self.assertEqual(subsequent_res.status_code, 401)

    def test_logout_flow(self):
        # 1. Register & login
        self.client.post(
            "/api/v1/auth/register",
            json={
                "email": "user@example.com",
                "password": "ValidPassword123!",
                "display_name": "Usuario Test",
            },
        )
        login_res = self.client.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "user@example.com", "password": "ValidPassword123!"},
        )
        refresh_cookie = login_res.cookies["__Secure-agro_refresh"]
        csrf_token = login_res.json()["csrf_token"]

        # 2. Logout
        logout_res = self.client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": self.allowed_origin,
                "X-CSRF-Token": csrf_token,
            },
            cookies={
                "__Secure-agro_refresh": refresh_cookie,
                "csrf_token": csrf_token,
            },
        )
        self.assertEqual(logout_res.status_code, 204)

        # Check DB that session is revoked
        with self.TestingSessionLocal() as db:
            s = db.query(RefreshSession).first()
            self.assertIsNotNone(s.revoked_at)
            logout_log = db.query(AuditLog).filter(AuditLog.event_type == "LOGOUT").first()
            self.assertIsNotNone(logout_log)


if __name__ == "__main__":
    unittest.main()
