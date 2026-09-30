"""Integration tests for User Profile, Password Change and Recovery (Group 5)."""
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import AuditLog, Base, PasswordRecoveryToken, RefreshSession, User
from app.infrastructure.email import InMemoryEmailSender, set_email_sender
from app.infrastructure.security import hash_password, hash_token, verify_password
from app.infrastructure.tokens import TokenManager, generate_ed25519_keypair, set_token_manager
from app.main import app
from app.persistence import get_db
from tests.client import TestClient


class TestProfileApi(unittest.TestCase):
    def setUp(self):
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

        # Create a test user
        with self.TestingSessionLocal() as db:
            self.test_user = User(
                email="profile_user@example.com",
                password_hash=hash_password("InitialPassword123!"),
                display_name="Profile User",
                role="USER",
                status="ACTIVE",
            )
            db.add(self.test_user)
            db.commit()
            db.refresh(self.test_user)
            self.user_id = self.test_user.id

        self.auth_token = self.token_manager.create_access_token(user_id=self.user_id, role="USER")
        self.auth_headers = {"Authorization": f"Bearer {self.auth_token}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)

    def test_get_profile_success(self):
        res = self.client.get("/api/v1/profile", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["email"], "profile_user@example.com")
        self.assertEqual(data["display_name"], "Profile User")
        self.assertEqual(data["role"], "USER")
        self.assertEqual(data["id"], str(self.user_id))

    def test_get_profile_requires_auth(self):
        res = self.client.get("/api/v1/profile")
        self.assertEqual(res.status_code, 401)

    def test_patch_profile_display_name(self):
        res = self.client.patch(
            "/api/v1/profile",
            headers=self.auth_headers,
            json={"display_name": "Nombre Actualizado"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["display_name"], "Nombre Actualizado")

        # Verify DB updated
        with self.TestingSessionLocal() as db:
            u = db.query(User).filter(User.id == self.user_id).first()
            self.assertEqual(u.display_name, "Nombre Actualizado")

    def test_patch_profile_rejects_unmodifiable_fields(self):
        # Attempt to change role or email -> 400
        res = self.client.patch(
            "/api/v1/profile",
            headers=self.auth_headers,
            json={"display_name": "Valido", "role": "ADMIN"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "INVALID_REQUEST")

    def test_change_password_and_revokes_sessions(self):
        # Create an active refresh session for this user
        with self.TestingSessionLocal() as db:
            session = RefreshSession(
                user_id=self.user_id,
                family_id=self.user_id,
                token_hash="fakehash123",
                expires_at=None,
            )
            import datetime
            session.expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
            db.add(session)
            db.commit()

        # Change password with wrong current password -> 401
        res_fail = self.client.put(
            "/api/v1/profile/password",
            headers=self.auth_headers,
            json={
                "current_password": "WrongPassword123!",
                "new_password": "NewValidPassword123!",
            },
        )
        self.assertEqual(res_fail.status_code, 401)
        self.assertEqual(res_fail.json()["code"], "INVALID_CREDENTIALS")

        # Change password with valid credentials -> 200 & revokes sessions
        res_ok = self.client.put(
            "/api/v1/profile/password",
            headers=self.auth_headers,
            json={
                "current_password": "InitialPassword123!",
                "new_password": "NewValidPassword123!",
            },
        )
        self.assertEqual(res_ok.status_code, 200)

        # Verify user password updated and sessions revoked
        with self.TestingSessionLocal() as db:
            u = db.query(User).filter(User.id == self.user_id).first()
            self.assertTrue(verify_password("NewValidPassword123!", u.password_hash))

            s = db.query(RefreshSession).filter(RefreshSession.user_id == self.user_id).first()
            self.assertIsNotNone(s.revoked_at)

            audit = db.query(AuditLog).filter(
                AuditLog.user_id == self.user_id, AuditLog.event_type == "PASSWORD_CHANGE"
            ).first()
            self.assertIsNotNone(audit)

    def test_password_recovery_full_flow(self):
        # 1. Non-existent email still returns 202 generic anti-enumeration
        res_unknown = self.client.post(
            "/api/v1/auth/password-recovery",
            json={"email": "nonexistent@example.com"},
        )
        self.assertEqual(res_unknown.status_code, 202)
        self.assertEqual(len(self.email_sender.sent_messages), 0)

        # 2. Existing user returns 202 and dispatches email
        res_user = self.client.post(
            "/api/v1/auth/password-recovery",
            json={"email": "profile_user@example.com"},
        )
        self.assertEqual(res_user.status_code, 202)
        self.assertEqual(len(self.email_sender.sent_messages), 1)
        raw_token = self.email_sender.sent_messages[0]["token"]

        # Verify token in DB is stored as SHA-256 hash, NOT plaintext!
        with self.TestingSessionLocal() as db:
            token_entry = db.query(PasswordRecoveryToken).first()
            self.assertIsNotNone(token_entry)
            self.assertEqual(token_entry.token_hash, hash_token(raw_token))
            self.assertNotEqual(token_entry.token_hash, raw_token)

        # 3. Confirm recovery with invalid token -> 400
        res_bad_tok = self.client.post(
            "/api/v1/auth/password-recovery/confirm",
            json={"token": "bogus_token", "new_password": "RestoredPassword123!"},
        )
        self.assertEqual(res_bad_tok.status_code, 400)
        self.assertEqual(res_bad_tok.json()["code"], "INVALID_TOKEN")

        # 4. Confirm recovery with valid token -> 200 & update password & consume token
        res_confirm = self.client.post(
            "/api/v1/auth/password-recovery/confirm",
            json={"token": raw_token, "new_password": "RestoredPassword123!"},
        )
        self.assertEqual(res_confirm.status_code, 200)

        with self.TestingSessionLocal() as db:
            u = db.query(User).filter(User.id == self.user_id).first()
            self.assertTrue(verify_password("RestoredPassword123!", u.password_hash))

            tok = db.query(PasswordRecoveryToken).first()
            self.assertIsNotNone(tok.used_at)

            audit = db.query(AuditLog).filter(AuditLog.event_type == "PASSWORD_RECOVERY_CONFIRMED").first()
            self.assertIsNotNone(audit)

        # 5. Replay consumed token -> 400
        res_replay = self.client.post(
            "/api/v1/auth/password-recovery/confirm",
            json={"token": raw_token, "new_password": "AnotherPassword123!"},
        )
        self.assertEqual(res_replay.status_code, 400)


if __name__ == "__main__":
    unittest.main()
