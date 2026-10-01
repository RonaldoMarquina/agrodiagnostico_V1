"""Logical-client regression tests in disposable in-memory SQLite.

These clients share a Python app. Real process/DB/proxy acceptance is in
scripts/check_identity_integration.py; this suite never connects to DB_HOST.
"""
import concurrent.futures
import threading
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import AuditLog, Base, RefreshSession, User
from app.infrastructure.email import InMemoryEmailSender, set_email_sender
from app.infrastructure.security import hash_password, verify_password
from app.infrastructure.tokens import TokenManager, generate_ed25519_keypair, set_token_manager
from app.main import app
from app.persistence import get_db
from tests.client import TestClient


class TestMultiInstance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Generate asymmetric Ed25519 keypair shared across all instances
        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()

    def setUp(self):
        self.is_postgres = False
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


        # Shared TokenManager (cryptographically compatible configuration)
        self.shared_token_manager = TokenManager(
            private_key_pem=self.priv_pem,
            public_key_pem=self.pub_pem,
        )
        set_token_manager(self.shared_token_manager)

        self.email_sender = InMemoryEmailSender()
        set_email_sender(self.email_sender)

        # Three logical independent instances sharing DB and crypto
        self.identity_1 = TestClient(app)
        self.identity_2 = TestClient(app)
        self.identity_3 = TestClient(app)

        self.allowed_origin = "http://localhost:3000"

        # Seed initial test user and admin
        with self.TestingSessionLocal() as db:
            self.user = User(
                email="multi_user@example.com",
                password_hash=hash_password("UserPassword123!"),
                display_name="Multi User",
                role="USER",
                status="ACTIVE",
            )
            self.admin = User(
                email="multi_admin@example.com",
                password_hash=hash_password("AdminPassword123!"),
                display_name="Multi Admin",
                role="ADMIN",
                status="ACTIVE",
            )
            db.add_all([self.user, self.admin])
            db.commit()
            db.refresh(self.user)
            db.refresh(self.admin)
            self.user_id = self.user.id
            self.admin_id = self.admin.id

        self.admin_token = self.shared_token_manager.create_access_token(user_id=self.admin_id, role="ADMIN")
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        if not getattr(self, "is_postgres", False):
            Base.metadata.drop_all(self.engine)
        else:
            from sqlalchemy import text
            with self.engine.connect() as conn:
                conn.execute(text("TRUNCATE TABLE audit_logs, refresh_sessions, password_recovery_tokens, users CASCADE;"))
                conn.commit()

    def test_multi_instance_login_refresh_logout_lifecycle(self):
        """
        Flow:
        1. Login on identity-1
        2. Refresh on identity-3
        3. Logout on identity-2
        4. Re-check on identity-1
        """
        # Step 1: Login on identity-1
        login_res = self.identity_1.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "multi_user@example.com", "password": "UserPassword123!"},
        )
        self.assertEqual(login_res.status_code, 200)
        refresh_cookie_1 = login_res.cookies["__Secure-agro_refresh"]
        csrf_token_1 = login_res.json()["csrf_token"]

        # Step 2: Refresh on identity-3 (different instance!)
        refresh_res = self.identity_3.post(
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
        self.assertEqual(refresh_res.status_code, 200)
        refresh_cookie_2 = refresh_res.cookies["__Secure-agro_refresh"]
        csrf_token_2 = refresh_res.json()["csrf_token"]
        self.assertNotEqual(refresh_cookie_1, refresh_cookie_2)

        # Step 3: Logout on identity-2 (yet another instance!)
        logout_res = self.identity_2.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": self.allowed_origin,
                "X-CSRF-Token": csrf_token_2,
            },
            cookies={
                "__Secure-agro_refresh": refresh_cookie_2,
                "csrf_token": csrf_token_2,
            },
        )
        self.assertEqual(logout_res.status_code, 204)

        # Step 4: Verify identity-1 sees session is revoked
        check_res = self.identity_1.post(
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
        self.assertEqual(check_res.status_code, 401)

    def test_concurrent_refresh_race_condition(self):
        """
        Two simultaneous refresh calls with the exact same token arriving at identity-1 and identity-2.
        Only one must succeed; the other must fail or detect rotation/reuse without corrupting state.
        """
        if not getattr(self, "is_postgres", False):
            self.skipTest("Concurrent race condition testing requires real PostgreSQL row-level locks")

        # Login
        login_res = self.identity_1.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "multi_user@example.com", "password": "UserPassword123!"},
        )
        refresh_cookie = login_res.cookies["__Secure-agro_refresh"]
        csrf_token = login_res.json()["csrf_token"]

        results = []

        def call_refresh(client):
            res = client.post(
                "/api/v1/auth/refresh",
                headers={
                    "Origin": self.allowed_origin,
                    "X-CSRF-Token": csrf_token,
                },
                cookies={
                    "__Secure-agro_refresh": refresh_cookie,
                    "csrf_token": csrf_token,
                },
            )
            return res.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(call_refresh, self.identity_1)
            f2 = executor.submit(call_refresh, self.identity_2)
            results = [f1.result(), f2.result()]

        # Exactly one call must succeed with 200; the competing call must not succeed with 200
        self.assertEqual(results.count(200), 1, f"Expected exactly one 200, got {results}")
        self.assertEqual(results.count(401), 1, f"Expected competing call to receive 401, got {results}")

    def test_reuse_detection_and_full_family_revocation_across_instances(self):
        """
        Token rotated at identity-1.
        Attacker replays old token at identity-2.
        Reuse is detected, whole family revoked.
        Legitimate user's new token on identity-3 is now also rejected.
        """
        # Login on identity-1
        login_res = self.identity_1.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "multi_user@example.com", "password": "UserPassword123!"},
        )
        token_A = login_res.cookies["__Secure-agro_refresh"]
        csrf_A = login_res.json()["csrf_token"]

        # Rotation 1 on identity-1 -> generates token_B
        rot_res = self.identity_1.post(
            "/api/v1/auth/refresh",
            headers={"Origin": self.allowed_origin, "X-CSRF-Token": csrf_A},
            cookies={"__Secure-agro_refresh": token_A, "csrf_token": csrf_A},
        )
        self.assertEqual(rot_res.status_code, 200)
        token_B = rot_res.cookies["__Secure-agro_refresh"]
        csrf_B = rot_res.json()["csrf_token"]

        # Replay token_A at identity-2!
        replay_res = self.identity_2.post(
            "/api/v1/auth/refresh",
            headers={"Origin": self.allowed_origin, "X-CSRF-Token": csrf_A},
            cookies={"__Secure-agro_refresh": token_A, "csrf_token": csrf_A},
        )
        self.assertEqual(replay_res.status_code, 401)
        self.assertEqual(replay_res.json()["code"], "SESSION_REUSE_DETECTED")

        # Now legitimate user on identity-3 attempts to use token_B
        legit_res = self.identity_3.post(
            "/api/v1/auth/refresh",
            headers={"Origin": self.allowed_origin, "X-CSRF-Token": csrf_B},
            cookies={"__Secure-agro_refresh": token_B, "csrf_token": csrf_B},
        )
        self.assertEqual(legit_res.status_code, 401)

        # Audit log verifies reuse detection
        with self.TestingSessionLocal() as db:
            audit = db.query(AuditLog).filter(AuditLog.event_type == "REFRESH_TOKEN_REUSE_DETECTED").first()
            self.assertIsNotNone(audit)

    def test_password_change_revokes_sessions_across_instances(self):
        """
        Login on identity-1.
        Password changed on identity-2.
        Refresh attempt on identity-3 is rejected.
        """
        login_res = self.identity_1.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "multi_user@example.com", "password": "UserPassword123!"},
        )
        refresh_token = login_res.cookies["__Secure-agro_refresh"]
        csrf_token = login_res.json()["csrf_token"]
        access_token = login_res.json()["access_token"]

        # Change password on identity-2
        change_res = self.identity_2.put(
            "/api/v1/profile/password",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"current_password": "UserPassword123!", "new_password": "NewUserPassword123!"},
        )
        self.assertEqual(change_res.status_code, 200)

        # Attempt to use previous refresh token on identity-3
        refresh_res = self.identity_3.post(
            "/api/v1/auth/refresh",
            headers={"Origin": self.allowed_origin, "X-CSRF-Token": csrf_token},
            cookies={"__Secure-agro_refresh": refresh_token, "csrf_token": csrf_token},
        )
        self.assertEqual(refresh_res.status_code, 401)

    def test_password_recovery_revokes_sessions_across_instances(self):
        """
        Login on identity-1.
        Recovery confirmed on identity-2.
        Refresh attempt on identity-3 is rejected.
        """
        login_res = self.identity_1.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "multi_user@example.com", "password": "UserPassword123!"},
        )
        refresh_token = login_res.cookies["__Secure-agro_refresh"]
        csrf_token = login_res.json()["csrf_token"]

        # Request recovery on identity-1
        self.identity_1.post(
            "/api/v1/auth/password-recovery",
            json={"email": "multi_user@example.com"},
        )
        raw_token = self.email_sender.sent_messages[-1]["token"]

        # Confirm recovery on identity-2
        confirm_res = self.identity_2.post(
            "/api/v1/auth/password-recovery/confirm",
            json={"token": raw_token, "new_password": "RecoveredPassword123!"},
        )
        self.assertEqual(confirm_res.status_code, 200)

        # Refresh on identity-3
        refresh_res = self.identity_3.post(
            "/api/v1/auth/refresh",
            headers={"Origin": self.allowed_origin, "X-CSRF-Token": csrf_token},
            cookies={"__Secure-agro_refresh": refresh_token, "csrf_token": csrf_token},
        )
        self.assertEqual(refresh_res.status_code, 401)

    def test_admin_block_revokes_sessions_across_instances(self):
        """
        Login on identity-1.
        Admin blocks user on identity-2.
        Refresh attempt on identity-3 is rejected.
        """
        login_res = self.identity_1.post(
            "/api/v1/auth/login",
            headers={"Origin": self.allowed_origin},
            json={"email": "multi_user@example.com", "password": "UserPassword123!"},
        )
        refresh_token = login_res.cookies["__Secure-agro_refresh"]
        csrf_token = login_res.json()["csrf_token"]

        # Admin blocks user on identity-2
        block_res = self.identity_2.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
        )
        self.assertEqual(block_res.status_code, 200)

        # Refresh on identity-3
        refresh_res = self.identity_3.post(
            "/api/v1/auth/refresh",
            headers={"Origin": self.allowed_origin, "X-CSRF-Token": csrf_token},
            cookies={"__Secure-agro_refresh": refresh_token, "csrf_token": csrf_token},
        )
        self.assertEqual(refresh_res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
