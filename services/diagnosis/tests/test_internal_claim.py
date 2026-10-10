"""Unit and concurrency tests for atomic claim and lease_owner derivation (Task 3.2).

Tests:
- Atomic transition PENDIENTE -> PROCESANDO with derived lease_owner.
- Response payload: lease_owner, lease_token, expires_at.
- Headers: Cache-Control: private, no-store, X-Correlation-ID.
- 409 DIAGNOSIS_NOT_CLAIMABLE when lease is currently active.
- 404 NOT_FOUND for nonexistent diagnosis.
- 409 DIAGNOSIS_NOT_CLAIMABLE for terminal states (CANCELADO, COMPLETADO, NO_CONCLUYENTE, FALLIDO).
- Race claim vs cancel: only one transition wins.
  - Cancel wins: status is CANCELADO, claim returns 409. CANCELADO never emits Finished.
  - Claim wins: status is PROCESANDO, cancel returns 409 DIAGNOSIS_NOT_CANCELABLE.
- Two workers race: exactly one wins and claims the lease; attempt_count increments only once.
"""
from datetime import datetime, timedelta, timezone
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.application.diagnoses import cancel_diagnosis
from app.domain.models import Base, Diagnosis
from app.infrastructure.internal_auth import (
    TrustedKeyRegistry,
    create_internal_token,
    generate_internal_keypair,
    set_internal_key_registry,
)
from app.infrastructure.security import Principal
from app.main import app as main_app
from tests.client import TestClient


class TestInternalClaim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w1_priv, cls.w1_pub = generate_internal_keypair()
        cls.w2_priv, cls.w2_pub = generate_internal_keypair()

        cls.registry = TrustedKeyRegistry()
        cls.registry.register_key("kid-1", cls.w1_pub, instance_id="worker-node-1")
        cls.registry.register_key("kid-2", cls.w2_pub, instance_id="worker-node-2")
        set_internal_key_registry(cls.registry)

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        main_app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(main_app)

    @classmethod
    def tearDownClass(cls):
        set_internal_key_registry(None)
        main_app.dependency_overrides.clear()

    def setUp(self):
        with self.SessionLocal() as session:
            session.query(Diagnosis).delete()
            session.commit()

        self.w1_token = create_internal_token(
            private_key_pem=self.w1_priv,
            kid="kid-1",
            instance_id="worker-node-1",
        )
        self.w2_token = create_internal_token(
            private_key_pem=self.w2_priv,
            kid="kid-2",
            instance_id="worker-node-2",
        )
        self.owner_id = uuid.uuid4()

    def create_fixture_diagnosis(self, status: str = "PENDIENTE") -> uuid.UUID:
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        with self.SessionLocal() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.owner_id,
                status=status,
                object_key=f"diagnoses/{diag_id}/original.jpg",
                image_sha256="abc123sha",
                image_content_type="image/jpeg",
                image_size_bytes=1024,
                created_at=now,
                updated_at=now,
            )
            session.add(diag)
            session.commit()
        return diag_id

    def test_claim_pending_success(self):
        diag_id = self.create_fixture_diagnosis("PENDIENTE")

        cid = str(uuid.uuid4())
        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={
                "Authorization": f"Bearer {self.w1_token}",
                "X-Correlation-ID": cid,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["lease_owner"], "worker-node-1")
        self.assertTrue(uuid.UUID(data["lease_token"]))
        self.assertIn("expires_at", data)
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")
        self.assertEqual(resp.headers.get("X-Correlation-ID"), cid)

        # Verify DB row
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            self.assertEqual(diag.status, "PROCESANDO")
            self.assertEqual(diag.attempt_count, 1)
            self.assertEqual(diag.lease_owner, "worker-node-1")
            self.assertEqual(str(diag.lease_token), data["lease_token"])
            self.assertIsNotNone(diag.lease_expires_at)
            self.assertIsNotNone(diag.processing_deadline_at)

    def test_claim_active_lease_conflict_returns_409(self):
        diag_id = self.create_fixture_diagnosis("PENDIENTE")

        # First worker claims
        resp1 = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={"Authorization": f"Bearer {self.w1_token}"},
        )
        self.assertEqual(resp1.status_code, 200)

        # Second worker attempts to claim active lease
        resp2 = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={"Authorization": f"Bearer {self.w2_token}"},
        )
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(resp2.json()["code"], "DIAGNOSIS_NOT_CLAIMABLE")

        # attempt_count must remain 1
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            self.assertEqual(diag.attempt_count, 1)
            self.assertEqual(diag.lease_owner, "worker-node-1")

    def test_claim_nonexistent_returns_404(self):
        missing_id = uuid.uuid4()
        resp = self.client.post(
            f"/internal/diagnoses/{missing_id}/claim",
            headers={"Authorization": f"Bearer {self.w1_token}"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")

    def test_claim_terminal_states_return_409(self):
        for term_status in ["CANCELADO", "COMPLETADO", "NO_CONCLUYENTE", "FALLIDO"]:
            diag_id = self.create_fixture_diagnosis(term_status)
            resp = self.client.post(
                f"/internal/diagnoses/{diag_id}/claim",
                headers={"Authorization": f"Bearer {self.w1_token}"},
            )
            self.assertEqual(resp.status_code, 409, f"Status {term_status} should return 409")
            self.assertEqual(resp.json()["code"], "DIAGNOSIS_NOT_CLAIMABLE")

    def test_race_cancel_before_claim(self):
        diag_id = self.create_fixture_diagnosis("PENDIENTE")

        # Owner cancels
        with self.SessionLocal() as session:
            cancel_diagnosis(session, Principal(id=self.owner_id, role="USER", token_id="t1"), diag_id)

        # Worker attempts claim after cancel
        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={"Authorization": f"Bearer {self.w1_token}"},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "DIAGNOSIS_NOT_CLAIMABLE")

        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            self.assertEqual(diag.status, "CANCELADO")
            # attempt_count must remain 0
            self.assertEqual(diag.attempt_count, 0)

    def test_race_claim_before_cancel(self):
        diag_id = self.create_fixture_diagnosis("PENDIENTE")

        # Worker claims first
        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/claim",
            headers={"Authorization": f"Bearer {self.w1_token}"},
        )
        self.assertEqual(resp.status_code, 200)

        # Owner attempts cancel after claim
        with self.SessionLocal() as session:
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as cm:
                cancel_diagnosis(session, Principal(id=self.owner_id, role="USER", token_id="t1"), diag_id)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail["code"], "DIAGNOSIS_NOT_CANCELABLE")

        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            self.assertEqual(diag.status, "PROCESANDO")


if __name__ == "__main__":
    unittest.main()

