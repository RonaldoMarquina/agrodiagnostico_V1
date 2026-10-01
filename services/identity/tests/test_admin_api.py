"""Integration tests for RBAC, Administrative APIs and initial Admin CLI (Group 6)."""
import unittest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cli import create_initial_admin
from app.domain.models import AuditLog, Base, RefreshSession, User
from app.infrastructure.security import hash_password, verify_password
from app.infrastructure.tokens import TokenManager, generate_ed25519_keypair, set_token_manager
from app.main import app
from app.persistence import get_db
from tests.client import TestClient


class TestAdminApi(unittest.TestCase):
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

        # Create 1 ADMIN user and 1 regular USER
        with self.TestingSessionLocal() as db:
            self.admin = User(
                email="admin@example.com",
                password_hash=hash_password("AdminSecurePassword123!"),
                display_name="Admin Principal",
                role="ADMIN",
                status="ACTIVE",
            )
            self.regular_user = User(
                email="regular@example.com",
                password_hash=hash_password("UserSecurePassword123!"),
                display_name="Regular User",
                role="USER",
                status="ACTIVE",
            )
            db.add_all([self.admin, self.regular_user])
            db.commit()
            db.refresh(self.admin)
            db.refresh(self.regular_user)
            self.admin_id = self.admin.id
            self.user_id = self.regular_user.id

        self.admin_token = self.token_manager.create_access_token(user_id=self.admin_id, role="ADMIN")
        self.user_token = self.token_manager.create_access_token(user_id=self.user_id, role="USER")

        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        self.user_headers = {"Authorization": f"Bearer {self.user_token}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)

    def test_rbac_denies_regular_user_access_to_admin_endpoints(self):
        # Regular user tries to list users -> 403
        res = self.client.get("/api/v1/admin/users", headers=self.user_headers)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["code"], "FORBIDDEN")

        # Regular user tries to block user -> 403
        res = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.user_headers,
        )
        self.assertEqual(res.status_code, 403)

        # Regular user tries to activate user -> 403
        res = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/activate",
            headers=self.user_headers,
        )
        self.assertEqual(res.status_code, 403)

    def test_admin_list_users(self):
        res = self.client.get("/api/v1/admin/users", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("items", data)
        self.assertGreaterEqual(len(data["items"]), 2)
        emails = [u["email"] for u in data["items"]]
        self.assertIn("admin@example.com", emails)
        self.assertIn("regular@example.com", emails)

    def test_admin_block_user_and_revokes_sessions(self):
        # Create an active refresh session for regular_user
        with self.TestingSessionLocal() as db:
            import datetime
            session = RefreshSession(
                user_id=self.user_id,
                family_id=uuid.uuid4(),
                token_hash="fakehash_session_active",
                expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
            )
            db.add(session)
            db.commit()

        # Admin blocks user
        res = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "BLOCKED")

        # Verify DB: status is BLOCKED, session is revoked, audit log exists
        with self.TestingSessionLocal() as db:
            u = db.query(User).filter(User.id == self.user_id).first()
            self.assertEqual(u.status, "BLOCKED")

            s = db.query(RefreshSession).filter(RefreshSession.user_id == self.user_id).first()
            self.assertIsNotNone(s.revoked_at)

            audit = db.query(AuditLog).filter(AuditLog.event_type == "USER_BLOCKED").first()
            self.assertIsNotNone(audit)
            self.assertEqual(audit.user_id, self.admin_id)

    def test_admin_block_unknown_user_returns_404(self):
        random_id = uuid.uuid4()
        res = self.client.patch(
            f"/api/v1/admin/users/{random_id}/block",
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "NOT_FOUND")

    def test_admin_activate_user(self):
        # Block user first
        with self.TestingSessionLocal() as db:
            u = db.query(User).filter(User.id == self.user_id).first()
            u.status = "BLOCKED"
            db.commit()

        # Admin activates user
        res = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/activate",
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ACTIVE")

        with self.TestingSessionLocal() as db:
            u = db.query(User).filter(User.id == self.user_id).first()
            self.assertEqual(u.status, "ACTIVE")

            audit = db.query(AuditLog).filter(AuditLog.event_type == "USER_ACTIVATED").first()
            self.assertIsNotNone(audit)

    def test_cli_initial_admin_creation(self):
        # Test CLI provisioning function with a mock sessionmaker
        from unittest.mock import patch
        with patch("app.cli.get_sessionmaker", return_value=self.TestingSessionLocal):
            code = create_initial_admin(
                email="superadmin@example.com",
                password="SuperAdminPassword123!",
                display_name="Super Admin",
            )
            self.assertEqual(code, 0)

            with self.TestingSessionLocal() as db:
                sa = db.query(User).filter(User.email == "superadmin@example.com").first()
                self.assertIsNotNone(sa)
                self.assertEqual(sa.role, "ADMIN")
                self.assertTrue(verify_password("SuperAdminPassword123!", sa.password_hash))

                audit = db.query(AuditLog).filter(
                    AuditLog.user_id == sa.id,
                    AuditLog.event_type == "INITIAL_ADMIN_PROVISIONED"
                ).first()
                self.assertIsNotNone(audit)

            # Rerunning should be idempotent (return 0)
            code2 = create_initial_admin(
                email="superadmin@example.com",
                password="SuperAdminPassword123!",
                display_name="Super Admin",
            )
            self.assertEqual(code2, 0)


if __name__ == "__main__":
    unittest.main()
