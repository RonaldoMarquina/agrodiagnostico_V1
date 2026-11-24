"""Unit tests for Notification public HTTP endpoints (Task 4.2)."""
from datetime import datetime, timedelta, timezone
import os
import time
import unittest
from unittest.mock import patch
import uuid

import jwt
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base, Notification, NotificationPreference
from app.infrastructure.cursor import encode_cursor
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


def _sign_token(priv_pem: str, user_id: uuid.UUID, role: str = "USER") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "role": role,
            "iss": DEFAULT_ISSUER,
            "aud": DEFAULT_AUDIENCE,
            "iat": now,
            "exp": now + 900,
            "jti": str(uuid.uuid4()),
        },
        priv_pem,
        algorithm="EdDSA",
    )


class TestNotificationsApi(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, expire_on_commit=False, bind=self.engine
        )

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.priv_pem, self.pub_pem = generate_ed25519_keypair()
        set_token_verifier(TokenVerifier(public_key_pem=self.pub_pem))

        self.env_patcher = patch.dict(os.environ, {"CURSOR_SIGNING_KEY": "c" * 64})
        self.env_patcher.start()

        self.user_a = uuid.uuid4()
        self.user_b = uuid.uuid4()
        self.admin_user = uuid.uuid4()
        self.tok_a = _sign_token(self.priv_pem, self.user_a, "USER")
        self.tok_b = _sign_token(self.priv_pem, self.user_b, "USER")
        self.tok_admin = _sign_token(self.priv_pem, self.admin_user, "ADMIN")

    def tearDown(self):
        self.env_patcher.stop()
        app.dependency_overrides.clear()
        set_token_verifier(None)
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _seed_notifications(self):
        t0 = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
        # Same timestamp tie-breaker pair + older items + foreign user item
        n_tie_high = Notification(
            id=uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
            owner_id=self.user_a,
            diagnosis_id=uuid.uuid4(),
            final_status="COMPLETADO",
            created_at=t0 + timedelta(seconds=20),
            correlation_id=uuid.uuid4(),
        )
        n_tie_low = Notification(
            id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            owner_id=self.user_a,
            diagnosis_id=uuid.uuid4(),
            final_status="NO_CONCLUYENTE",
            created_at=t0 + timedelta(seconds=20),
            correlation_id=uuid.uuid4(),
        )
        n_mid = Notification(
            id=uuid.uuid4(),
            owner_id=self.user_a,
            diagnosis_id=uuid.uuid4(),
            final_status="FALLIDO",
            created_at=t0 + timedelta(seconds=10),
            correlation_id=uuid.uuid4(),
        )
        n_old = Notification(
            id=uuid.uuid4(),
            owner_id=self.user_a,
            diagnosis_id=uuid.uuid4(),
            final_status="COMPLETADO",
            created_at=t0,
            correlation_id=uuid.uuid4(),
        )
        n_other = Notification(
            id=uuid.uuid4(),
            owner_id=self.user_b,
            diagnosis_id=uuid.uuid4(),
            final_status="COMPLETADO",
            created_at=t0 + timedelta(seconds=30),
            correlation_id=uuid.uuid4(),
        )
        with self.SessionLocal() as db:
            db.add_all([n_tie_high, n_tie_low, n_mid, n_old, n_other])
            db.commit()
        return [n_tie_high, n_tie_low, n_mid, n_old], n_other

    def test_list_notifications_keyset_pagination_and_isolation(self):
        # Empty list initially
        empty = self.client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json(), {"items": [], "next_cursor": None})

        expected_a, other_b = self._seed_notifications()

        # Paginate with limit=2
        collected = []
        cursor = None
        pages = 0
        while True:
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            resp = self.client.get(
                "/api/v1/notifications",
                params=params,
                headers={"Authorization": f"Bearer {self.tok_a}"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("cache-control"), "private, no-store")
            body = resp.json()
            collected.extend(body["items"])
            cursor = body["next_cursor"]
            pages += 1
            if cursor is None:
                break

        self.assertEqual(pages, 2)
        self.assertEqual([item["id"] for item in collected], [str(n.id) for n in expected_a])
        self.assertNotIn(str(other_b.id), [item["id"] for item in collected])
        for item in collected:
            self.assertEqual(
                set(item.keys()),
                {"id", "diagnosis_id", "final_status", "created_at", "read_at"},
            )
            self.assertTrue(item["created_at"].endswith("Z"))
            self.assertIsNone(item["read_at"])

        # ADMIN sees only own notifications (empty here), never user_a or user_b
        admin_resp = self.client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {self.tok_admin}"},
        )
        self.assertEqual(admin_resp.status_code, 200)
        self.assertEqual(admin_resp.json(), {"items": [], "next_cursor": None})

    def test_list_notifications_rejects_invalid_limit_and_foreign_cursor(self):
        expected_a, _ = self._seed_notifications()
        for bad_limit in (0, -5, 101):
            resp = self.client.get(
                "/api/v1/notifications",
                params={"limit": bad_limit},
                headers={"Authorization": f"Bearer {self.tok_a}"},
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()["code"], "INVALID_PAGINATION")

        # Cursor minted for user_a cannot be used by user_b
        page1 = self.client.get(
            "/api/v1/notifications",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        cursor_a = page1.json()["next_cursor"]
        self.assertIsNotNone(cursor_a)

        resp_b = self.client.get(
            "/api/v1/notifications",
            params={"cursor": cursor_a},
            headers={"Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(resp_b.status_code, 400)
        self.assertEqual(resp_b.json()["code"], "INVALID_PAGINATION")

        # Diagnosis-purpose cursor rejected
        diag_cursor = encode_cursor(
            expected_a[0].created_at, expected_a[0].id, self.user_a, "user_diagnoses"
        )
        resp_wrong_purp = self.client.get(
            "/api/v1/notifications",
            params={"cursor": diag_cursor},
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(resp_wrong_purp.status_code, 400)

    def test_mark_notification_read_is_idempotent_and_isolated(self):
        expected_a, other_b = self._seed_notifications()
        target = expected_a[0]

        # First mark read sets UTC read_at
        r1 = self.client.patch(
            f"/api/v1/notifications/{target.id}/read",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r1.status_code, 200)
        body1 = r1.json()
        self.assertEqual(body1["id"], str(target.id))
        self.assertIsNotNone(body1["read_at"])
        self.assertTrue(body1["read_at"].endswith("Z"))

        # Second mark read preserves exact first read_at
        time.sleep(0.02)
        r2 = self.client.patch(
            f"/api/v1/notifications/{target.id}/read",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["read_at"], body1["read_at"])

        # Foreign user and ADMIN receive generic 404
        for tok in (self.tok_b, self.tok_admin):
            r_foreign = self.client.patch(
                f"/api/v1/notifications/{target.id}/read",
                headers={"Authorization": f"Bearer {tok}"},
            )
            self.assertEqual(r_foreign.status_code, 404)
            self.assertEqual(r_foreign.json()["code"], "NOT_FOUND")

        # Nonexistent UUID returns identical 404
        r_missing = self.client.patch(
            f"/api/v1/notifications/{uuid.uuid4()}/read",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r_missing.status_code, 404)
        self.assertEqual(r_missing.json()["code"], "NOT_FOUND")

        # Unexpected non-empty body returns 400
        r_body = self.client.patch(
            f"/api/v1/notifications/{target.id}/read",
            json={"read": True},
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r_body.status_code, 400)
        self.assertEqual(r_body.json()["code"], "INVALID_REQUEST")

        # Malformed UUID returns 400
        r_bad_uuid = self.client.patch(
            "/api/v1/notifications/not-a-uuid/read",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r_bad_uuid.status_code, 400)

        # Ensure other_b's notification stayed untouched
        with self.SessionLocal() as db:
            refreshed = db.get(Notification, other_b.id)
            self.assertIsNone(refreshed.read_at)

    def test_mark_all_read_idempotent_unread_count_and_isolation(self):
        # Unauthenticated -> 401
        self.assertEqual(self.client.patch("/api/v1/notifications/read-all").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/notifications/unread-count").status_code, 401)

        expected_a, other_b = self._seed_notifications()

        # Initial unread counts: user_a has 4, user_b has 1
        c_a0 = self.client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(c_a0.status_code, 200)
        self.assertEqual(c_a0.headers.get("cache-control"), "private, no-store")
        self.assertEqual(c_a0.json(), {"unread_count": 4})

        c_b0 = self.client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(c_b0.status_code, 200)
        self.assertEqual(c_b0.json(), {"unread_count": 1})

        # Mark one of user_a's notifications read first to verify read_at immutability
        first_read = self.client.patch(
            f"/api/v1/notifications/{expected_a[0].id}/read",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(first_read.status_code, 200)
        original_read_at = first_read.json()["read_at"]
        time.sleep(0.02)

        # Reject non-empty body on read-all with 400
        bad_body = self.client.patch(
            "/api/v1/notifications/read-all",
            json={"all": True},
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(bad_body.status_code, 400)
        self.assertEqual(bad_body.json()["code"], "INVALID_REQUEST")

        # Mark all remaining 3 notifications of user_a read
        ra1 = self.client.patch(
            "/api/v1/notifications/read-all",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(ra1.status_code, 200)
        self.assertEqual(ra1.headers.get("cache-control"), "private, no-store")
        self.assertEqual(ra1.json(), {"updated_count": 3})

        # Repeat call is idempotent -> updated_count == 0
        ra2 = self.client.patch(
            "/api/v1/notifications/read-all",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(ra2.status_code, 200)
        self.assertEqual(ra2.json(), {"updated_count": 0})

        # Original read_at preserved on previously-read notification
        re_read = self.client.patch(
            f"/api/v1/notifications/{expected_a[0].id}/read",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(re_read.json()["read_at"], original_read_at)

        # user_a unread count is now 0, user_b remains isolated at 1
        c_a1 = self.client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(c_a1.json(), {"unread_count": 0})

        c_b1 = self.client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(c_b1.json(), {"unread_count": 1})
        with self.SessionLocal() as db:
            self.assertIsNone(db.get(Notification, other_b.id).read_at)

    def test_preferences_default_false_and_strict_patch_validation(self):
        # Default GET returns email_enabled=false without inserting row
        r_get = self.client.get(
            "/api/v1/notification-preferences",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r_get.status_code, 200)
        self.assertEqual(r_get.json(), {"email_enabled": False})
        with self.SessionLocal() as db:
            self.assertIsNone(db.get(NotificationPreference, self.user_a))

        # Enable email for user_a
        r_enable = self.client.patch(
            "/api/v1/notification-preferences",
            json={"email_enabled": True},
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r_enable.status_code, 200)
        self.assertEqual(r_enable.json(), {"email_enabled": True})

        # User B remains false
        r_b = self.client.get(
            "/api/v1/notification-preferences",
            headers={"Authorization": f"Bearer {self.tok_b}"},
        )
        self.assertEqual(r_b.status_code, 200)
        self.assertEqual(r_b.json(), {"email_enabled": False})

        # Disable email back to false
        r_disable = self.client.patch(
            "/api/v1/notification-preferences",
            json={"email_enabled": False},
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(r_disable.status_code, 200)
        self.assertEqual(r_disable.json(), {"email_enabled": False})

        # Invalid payloads rejected with 400
        for bad_payload in (
            {},
            {"email_enabled": "true"},
            {"email_enabled": 1},
            {"email_enabled": None},
            {"email_enabled": True, "in_app_enabled": False},
        ):
            r_bad = self.client.patch(
                "/api/v1/notification-preferences",
                json=bad_payload,
                headers={"Authorization": f"Bearer {self.tok_a}"},
            )
            self.assertEqual(r_bad.status_code, 400, f"Expected 400 for {bad_payload}")
            self.assertEqual(r_bad.json()["code"], "INVALID_REQUEST")

    def test_persistence_failure_returns_503(self):
        class BrokenSession:
            def get(self, *args, **kwargs):
                raise OperationalError("SELECT 1", {}, Exception("db down"))

        def override_broken():
            yield BrokenSession()

        app.dependency_overrides[get_db] = override_broken
        resp = self.client.get(
            "/api/v1/notification-preferences",
            headers={"Authorization": f"Bearer {self.tok_a}"},
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], "PERSISTENCE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
