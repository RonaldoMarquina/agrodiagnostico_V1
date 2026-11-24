"""Unit and API tests for GET /internal/users/{id}/contact and internal Ed25519 auth (ADR-0014)."""
from datetime import datetime, timezone
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base, User
from app.infrastructure.internal_auth import (
    TrustedKeyRegistry,
    create_internal_token,
    generate_internal_keypair,
    set_internal_key_registry,
)
from app.infrastructure.security import hash_password
from app.infrastructure.tokens import TokenManager, generate_ed25519_keypair, set_token_manager
from app.main import app
from app.persistence import get_db
from tests.client import TestClient


class TestInternalUserContact(unittest.TestCase):
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

        # User JWT keys
        user_priv, user_pub = generate_ed25519_keypair()
        self.token_manager = TokenManager(private_key_pem=user_priv, public_key_pem=user_pub)
        set_token_manager(self.token_manager)

        # Internal service keys: notification-1 and worker-1
        self.notif_priv, self.notif_pub = generate_internal_keypair()
        self.worker_priv, self.worker_pub = generate_internal_keypair()
        self.untrusted_priv, _ = generate_internal_keypair()

        self.registry = TrustedKeyRegistry()
        self.registry.register_key(
            kid="notification-1-key",
            public_key_pem=self.notif_pub,
            instance_id="notification-1",
            principal="notification",
        )
        self.registry.register_key(
            kid="worker-1-key",
            public_key_pem=self.worker_pub,
            instance_id="worker-1",
            principal="ai_inference",
        )
        set_internal_key_registry(self.registry)

        with self.TestingSessionLocal() as db:
            self.active_user = User(
                email="activo@example.test",
                password_hash=hash_password("StrongPassword123!"),
                display_name="Usuario Activo",
                role="USER",
                status="ACTIVE",
            )
            self.blocked_user = User(
                email="bloqueado@example.test",
                password_hash=hash_password("StrongPassword123!"),
                display_name="Usuario Bloqueado",
                role="USER",
                status="BLOCKED",
            )
            self.admin_user = User(
                email="admin@example.test",
                password_hash=hash_password("StrongPassword123!"),
                display_name="Administrador",
                role="ADMIN",
                status="ACTIVE",
            )
            db.add_all([self.active_user, self.blocked_user, self.admin_user])
            db.commit()
            db.refresh(self.active_user)
            db.refresh(self.blocked_user)
            db.refresh(self.admin_user)

    def tearDown(self):
        app.dependency_overrides.clear()
        set_internal_key_registry(None)
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _notif_token(self, **kwargs) -> str:
        params = dict(
            private_key_pem=self.notif_priv,
            kid="notification-1-key",
            instance_id="notification-1",
            aud="identity-internal",
            sub="notification",
        )
        params.update(kwargs)
        return create_internal_token(**params)

    def test_valid_notification_service_gets_active_and_blocked_contact(self):
        cid = str(uuid.uuid4())
        resp = self.client.get(
            f"/internal/users/{self.active_user.id}/contact",
            headers={
                "Authorization": f"Bearer {self._notif_token()}",
                "X-Correlation-ID": cid,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("cache-control"), "private, no-store")
        self.assertEqual(resp.headers.get("x-correlation-id"), cid)
        self.assertEqual(
            resp.json(),
            {
                "user_id": str(self.active_user.id),
                "email": "activo@example.test",
                "active": True,
            },
        )

        resp_blocked = self.client.get(
            f"/internal/users/{self.blocked_user.id}/contact",
            headers={"Authorization": f"Bearer {self._notif_token()}"},
        )
        self.assertEqual(resp_blocked.status_code, 200)
        self.assertEqual(
            resp_blocked.json(),
            {
                "user_id": str(self.blocked_user.id),
                "email": "bloqueado@example.test",
                "active": False,
            },
        )

    def test_missing_user_returns_404(self):
        missing_id = uuid.uuid4()
        resp = self.client.get(
            f"/internal/users/{missing_id}/contact",
            headers={"Authorization": f"Bearer {self._notif_token()}"},
        )
        self.assertEqual(resp.status_code, 404)
        body = resp.json()
        self.assertEqual(body["code"], "NOT_FOUND")
        self.assertEqual(body["correlation_id"], resp.headers.get("x-correlation-id"))

    def test_invalid_uuid_returns_400(self):
        resp = self.client.get(
            "/internal/users/not-a-uuid/contact",
            headers={"Authorization": f"Bearer {self._notif_token()}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "INVALID_REQUEST")

    def test_missing_or_invalid_service_credentials_return_401(self):
        url = f"/internal/users/{self.active_user.id}/contact"

        # Missing header
        self.assertEqual(self.client.get(url).status_code, 401)

        # Malformed token
        self.assertEqual(
            self.client.get(url, headers={"Authorization": "Bearer malformed.token"}).status_code,
            401,
        )

        # Unknown kid
        unknown_kid = self._notif_token(kid="unknown-key")
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {unknown_kid}"}).status_code,
            401,
        )

        # Wrong signature for registered kid
        wrong_sig = self._notif_token(private_key_pem=self.untrusted_priv)
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {wrong_sig}"}).status_code,
            401,
        )

        # Expired token
        expired = self._notif_token(
            iat=int(datetime.now(timezone.utc).timestamp()) - 120,
            lifetime_seconds=30,
        )
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {expired}"}).status_code,
            401,
        )

        # Lifetime exceeding 60s
        over_ttl = self._notif_token(lifetime_seconds=120)
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {over_ttl}"}).status_code,
            401,
        )

        # Non-UUID jti
        bad_jti = self._notif_token(jti="not-a-uuid")
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {bad_jti}"}).status_code,
            401,
        )

        # Mismatched instance_id
        wrong_inst = self._notif_token(instance_id="notification-2")
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {wrong_inst}"}).status_code,
            401,
        )

    def test_user_and_admin_bearer_tokens_are_forbidden_403(self):
        url = f"/internal/users/{self.active_user.id}/contact"
        user_token = self.token_manager.create_access_token(self.active_user.id, "USER")
        admin_token = self.token_manager.create_access_token(self.admin_user.id, "ADMIN")

        resp_user = self.client.get(url, headers={"Authorization": f"Bearer {user_token}"})
        self.assertEqual(resp_user.status_code, 403)
        self.assertEqual(resp_user.json()["code"], "FORBIDDEN")

        resp_admin = self.client.get(url, headers={"Authorization": f"Bearer {admin_token}"})
        self.assertEqual(resp_admin.status_code, 403)
        self.assertEqual(resp_admin.json()["code"], "FORBIDDEN")

    def test_wrong_internal_principal_or_audience_returns_403(self):
        url = f"/internal/users/{self.active_user.id}/contact"

        # ai_inference worker with diagnosis-internal audience
        worker_diag_tok = create_internal_token(
            private_key_pem=self.worker_priv,
            kid="worker-1-key",
            instance_id="worker-1",
            aud="diagnosis-internal",
            sub="ai_inference",
        )
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {worker_diag_tok}"}).status_code,
            403,
        )

        # ai_inference worker trying identity-internal audience
        worker_id_tok = create_internal_token(
            private_key_pem=self.worker_priv,
            kid="worker-1-key",
            instance_id="worker-1",
            aud="identity-internal",
            sub="ai_inference",
        )
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {worker_id_tok}"}).status_code,
            403,
        )

        # notification service with wrong audience
        wrong_aud_tok = self._notif_token(aud="diagnosis-internal")
        self.assertEqual(
            self.client.get(url, headers={"Authorization": f"Bearer {wrong_aud_tok}"}).status_code,
            403,
        )

    def test_internal_notification_token_cannot_access_user_profile_403(self):
        resp = self.client.get(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {self._notif_token()}"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "FORBIDDEN")

    def test_persistence_error_returns_503(self):
        class BrokenSession:
            def query(self, *args, **kwargs):
                raise OperationalError("SELECT 1", {}, Exception("db down"))

        def override_broken_db():
            yield BrokenSession()

        app.dependency_overrides[get_db] = override_broken_db
        resp = self.client.get(
            f"/internal/users/{self.active_user.id}/contact",
            headers={"Authorization": f"Bearer {self._notif_token()}"},
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], "PERSISTENCE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
