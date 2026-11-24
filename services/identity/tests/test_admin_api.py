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

    def test_admin_user_stats_counts_and_rbac(self):
        # Unauthenticated -> 401
        res_unauth = self.client.get("/api/v1/admin/users/stats")
        self.assertEqual(res_unauth.status_code, 401)

        # USER -> 403
        res_user = self.client.get("/api/v1/admin/users/stats", headers=self.user_headers)
        self.assertEqual(res_user.status_code, 403)

        # ADMIN -> exact initial counts (1 admin + 1 user, both active)
        res = self.client.get("/api/v1/admin/users/stats", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("cache-control"), "private, no-store")
        self.assertEqual(
            res.json(),
            {"total": 2, "active": 2, "blocked": 0, "admins": 1, "users": 1},
        )

        # Block regular user and re-check counts
        res_blk = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
            json={"reason": "Actividad sospechosa confirmada."},
        )
        self.assertEqual(res_blk.status_code, 200)

        res_after = self.client.get("/api/v1/admin/users/stats", headers=self.admin_headers)
        self.assertEqual(res_after.status_code, 200)
        self.assertEqual(
            res_after.json(),
            {"total": 2, "active": 1, "blocked": 1, "admins": 1, "users": 1},
        )

    def test_admin_self_block_returns_409_without_revoking_sessions(self):
        import datetime

        with self.TestingSessionLocal() as db:
            db.add(
                RefreshSession(
                    user_id=self.admin_id,
                    family_id=uuid.uuid4(),
                    token_hash="fakehash_admin_session_active",
                    expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
                )
            )
            db.commit()

        res = self.client.patch(
            f"/api/v1/admin/users/{self.admin_id}/block",
            headers=self.admin_headers,
            json={"reason": "Intento de auto bloqueo."},
        )
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["code"], "SELF_BLOCK_NOT_ALLOWED")

        with self.TestingSessionLocal() as db:
            admin = db.query(User).filter(User.id == self.admin_id).first()
            self.assertEqual(admin.status, "ACTIVE")
            sess = db.query(RefreshSession).filter(RefreshSession.user_id == self.admin_id).first()
            self.assertIsNone(sess.revoked_at)

    def test_admin_block_reason_persisted_and_invalid_body_rejected(self):
        # Invalid short reason -> 400
        res_short = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
            json={"reason": "abc"},
        )
        self.assertEqual(res_short.status_code, 400)

        # Whitespace only -> 400
        res_ws = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
            json={"reason": "      "},
        )
        self.assertEqual(res_ws.status_code, 400)

        # Extra field -> 400
        res_extra = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
            json={"reason": "Motivo suficiente", "force": True},
        )
        self.assertEqual(res_extra.status_code, 400)

        # Empty object -> 400
        res_empty = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
            json={},
        )
        self.assertEqual(res_empty.status_code, 400)

        # Valid reason -> 200 and persisted in audit_logs.details
        res_ok = self.client.patch(
            f"/api/v1/admin/users/{self.user_id}/block",
            headers=self.admin_headers,
            json={"reason": "  Incumplimiento reiterado de uso  "},
        )
        self.assertEqual(res_ok.status_code, 200)
        with self.TestingSessionLocal() as db:
            audit = db.query(AuditLog).filter(AuditLog.action == "USER_BLOCKED").first()
            self.assertIsNotNone(audit)
            self.assertEqual(audit.details.get("reason"), "Incumplimiento reiterado de uso")

    def test_admin_audit_identity_pagination_filters_and_redaction(self):
        import datetime

        # Unauthenticated -> 401; USER -> 403
        self.assertEqual(self.client.get("/api/v1/admin/audit/identity").status_code, 401)
        self.assertEqual(
            self.client.get("/api/v1/admin/audit/identity", headers=self.user_headers).status_code,
            403,
        )

        # Insert 5 deterministic audit rows including a sensitive field that must be redacted
        base_dt = datetime.datetime(2026, 11, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
        created_ids = []
        with self.TestingSessionLocal() as db:
            for idx in range(5):
                row = AuditLog(
                    id=uuid.uuid4(),
                    user_id=self.admin_id,
                    actor_id=self.admin_id,
                    target_id=self.user_id if idx % 2 == 0 else self.admin_id,
                    action="USER_BLOCKED" if idx % 2 == 0 else "LOGIN_SUCCESS",
                    event_type="USER_BLOCKED" if idx % 2 == 0 else "LOGIN_SUCCESS",
                    correlation_id=uuid.uuid4(),
                    legacy=False,
                    details={
                        "reason": f"Motivo #{idx}",
                        "password_hash": "MUST_NOT_LEAK",
                        "refresh_token": "MUST_NOT_LEAK",
                    },
                    created_at=base_dt + datetime.timedelta(minutes=idx),
                )
                db.add(row)
                created_ids.append(str(row.id))
            db.commit()

        # Paginate with limit=2 -> 3 pages covering all 5 records without duplicates
        seen = []
        cursor = None
        pages = 0
        while True:
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            res = self.client.get("/api/v1/admin/audit/identity", params=params, headers=self.admin_headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.headers.get("cache-control"), "private, no-store")
            payload = res.json()
            for item in payload["items"]:
                seen.append(item["id"])
                self.assertNotIn("password_hash", item["details"] or {})
                self.assertNotIn("refresh_token", item["details"] or {})
                self.assertTrue(item["created_at"].endswith("Z"))
            pages += 1
            cursor = payload["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(pages, 3)
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)
        self.assertEqual(seen, list(reversed(created_ids)))

        # Filter by action and target_id
        res_filt = self.client.get(
            "/api/v1/admin/audit/identity",
            params={"action": "USER_BLOCKED", "target_id": str(self.user_id)},
            headers=self.admin_headers,
        )
        self.assertEqual(res_filt.status_code, 200)
        self.assertEqual(len(res_filt.json()["items"]), 3)

        # Invalid range from > to -> 400
        res_range = self.client.get(
            "/api/v1/admin/audit/identity",
            params={"from": "2026-11-23T00:00:00Z", "to": "2026-11-20T00:00:00Z"},
            headers=self.admin_headers,
        )
        self.assertEqual(res_range.status_code, 400)

        # Tampered cursor -> 400
        res_bad_cur = self.client.get(
            "/api/v1/admin/audit/identity",
            params={"cursor": "tampered.cursor"},
            headers=self.admin_headers,
        )
        self.assertEqual(res_bad_cur.status_code, 400)

        # Cursor bound to filters: cursor from unfiltered query rejected when filter changes
        first_page = self.client.get(
            "/api/v1/admin/audit/identity",
            params={"limit": 2},
            headers=self.admin_headers,
        ).json()
        self.assertIsNotNone(first_page["next_cursor"])
        res_mismatch = self.client.get(
            "/api/v1/admin/audit/identity",
            params={"limit": 2, "action": "USER_BLOCKED", "cursor": first_page["next_cursor"]},
            headers=self.admin_headers,
        )
        self.assertEqual(res_mismatch.status_code, 400)

        # Cursor bound to another admin principal -> 400
        other_admin_id = uuid.uuid4()
        with self.TestingSessionLocal() as db:
            db.add(
                User(
                    id=other_admin_id,
                    email="admin2@example.com",
                    password_hash=hash_password("Admin2SecurePassword123!"),
                    display_name="Admin 2",
                    role="ADMIN",
                    status="ACTIVE",
                )
            )
            db.commit()
        other_admin_token = self.token_manager.create_access_token(user_id=other_admin_id, role="ADMIN")
        res_other = self.client.get(
            "/api/v1/admin/audit/identity",
            params={"limit": 2, "cursor": first_page["next_cursor"]},
            headers={"Authorization": f"Bearer {other_admin_token}"},
        )
        self.assertEqual(res_other.status_code, 400)

        # Limit out of bounds -> 400
        res_limit = self.client.get(
            "/api/v1/admin/audit/identity",
            params={"limit": 101},
            headers=self.admin_headers,
        )
        self.assertEqual(res_limit.status_code, 400)


if __name__ == "__main__":
    unittest.main()
