"""Unit tests for lease policy configuration, recovery lifecycle, and deadline enforcement (Task 3.4).

Tests:
- Policy validation:
  - Valid defaults: 60s lease, 20s heartbeat, 300s deadline, 3 attempts, 5s/15s recovery waits.
  - Invalid configuration rejection (heartbeat >= lease, non-positive times, deadline < lease).
- Renewal limited by deadline:
  - Lease duration cannot extend past processing_deadline_at.
- PENDIENTE policy:
  - PENDIENTE diagnoses without first claim do not expire and have no deadline.
- Multi-generation recovery cycle:
  - Attempt 1 -> 2 requires 5s wait.
  - Attempt 2 -> 3 requires 15s wait.
  - Attempt 3 cannot be recovered (budget exhausted -> 409).
"""
from datetime import datetime, timedelta, timezone
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.application.internal_diagnoses import claim_diagnosis, ensure_utc, renew_diagnosis_lease
from app.domain.models import Base, Diagnosis
from app.infrastructure.internal_auth import (
    InternalServiceIdentity,
    TrustedKeyRegistry,
    create_internal_token,
    generate_internal_keypair,
    set_internal_key_registry,
)
from app.infrastructure.lease_config import (
    LeaseConfigurationError,
    LeasePolicy,
    set_lease_policy,
)
from app.main import app as main_app
from tests.client import TestClient


class TestLeasePolicyAndRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w1_priv, cls.w1_pub = generate_internal_keypair()
        cls.registry = TrustedKeyRegistry()
        cls.registry.register_key("kid-1", cls.w1_pub, instance_id="worker-node-1")
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

        self.identity = InternalServiceIdentity(instance_id="worker-node-1", kid="kid-1")
        self.owner_id = uuid.uuid4()
        self.custom_policy = LeasePolicy(
            lease_duration_seconds=60,
            heartbeat_seconds=20,
            processing_deadline_seconds=300,
            max_attempt_count=3,
            recovery_wait_seconds_attempt_2=5,
            recovery_wait_seconds_attempt_3=15,
        )
        set_lease_policy(self.custom_policy)

    def test_policy_validation_rejects_invalid_values(self):
        # Heartbeat >= lease duration
        with self.assertRaises(LeaseConfigurationError):
            LeasePolicy(lease_duration_seconds=60, heartbeat_seconds=60)
        with self.assertRaises(LeaseConfigurationError):
            LeasePolicy(lease_duration_seconds=60, heartbeat_seconds=65)

        # Deadline < lease duration
        with self.assertRaises(LeaseConfigurationError):
            LeasePolicy(lease_duration_seconds=60, processing_deadline_seconds=50)

        # Non-positive values
        with self.assertRaises(LeaseConfigurationError):
            LeasePolicy(lease_duration_seconds=0)
        with self.assertRaises(LeaseConfigurationError):
            LeasePolicy(heartbeat_seconds=-5)
        with self.assertRaises(LeaseConfigurationError):
            LeasePolicy(max_attempt_count=0)

        # Negative wait times
        with self.assertRaises(LeaseConfigurationError):
            LeasePolicy(recovery_wait_seconds_attempt_2=-1)

    def test_pending_without_first_claim_never_expires(self):
        diag_id = uuid.uuid4()
        old_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.owner_id,
                status="PENDIENTE",
                object_key=f"diagnoses/{diag_id}/original.jpg",
                image_sha256="abc",
                image_content_type="image/jpeg",
                image_size_bytes=100,
                created_at=old_time,
                updated_at=old_time,
                # Has no deadline and no expires_at
                processing_deadline_at=None,
                lease_expires_at=None,
            )
            session.add(diag)
            session.commit()

        # Claim succeeds despite diagnosis created months ago
        with self.SessionLocal() as session:
            res = claim_diagnosis(session, self.identity, diag_id, self.custom_policy)
            self.assertEqual(res["lease_owner"], "worker-node-1")
            updated = session.get(Diagnosis, diag_id)
            self.assertEqual(updated.status, "PROCESANDO")
            self.assertEqual(updated.attempt_count, 1)
            # Deadline is set only upon first claim
            self.assertIsNotNone(updated.processing_deadline_at)

    def test_renewal_limited_by_deadline(self):
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        now = datetime.now(timezone.utc)
        # Processing deadline in 10s, nominal lease 60s
        deadline = now + timedelta(seconds=10)
        with self.SessionLocal() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.owner_id,
                status="PROCESANDO",
                object_key=f"diagnoses/{diag_id}/original.jpg",
                image_sha256="abc",
                image_content_type="image/jpeg",
                image_size_bytes=100,
                lease_owner="worker-node-1",
                lease_token=lease_token,
                lease_expires_at=now + timedelta(seconds=5),
                processing_deadline_at=deadline,
                attempt_count=1,
                created_at=now,
                updated_at=now,
            )
            session.add(diag)
            session.commit()

        with self.SessionLocal() as session:
            res = renew_diagnosis_lease(session, self.identity, diag_id, lease_token, self.custom_policy)
            updated = session.get(Diagnosis, diag_id)
            # Must be capped exactly at deadline
            self.assertEqual(ensure_utc(updated.lease_expires_at), ensure_utc(deadline))

    def test_multi_generation_recovery_lifecycle(self):
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(seconds=500)

        # Setup: Attempt 1 expired 3 seconds ago (needs 5s wait!)
        with self.SessionLocal() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.owner_id,
                status="PROCESANDO",
                object_key=f"diagnoses/{diag_id}/original.jpg",
                image_sha256="abc",
                image_content_type="image/jpeg",
                image_size_bytes=100,
                lease_owner="worker-node-1",
                lease_token=uuid.uuid4(),
                lease_expires_at=now - timedelta(seconds=3),
                processing_deadline_at=deadline,
                attempt_count=1,
                created_at=now,
                updated_at=now,
            )
            session.add(diag)
            session.commit()

        # Attempt 1 expired but only 3s elapsed (< 5s wait) -> rejected!
        with self.SessionLocal() as session:
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as cm:
                claim_diagnosis(session, self.identity, diag_id, self.custom_policy)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail["code"], "DIAGNOSIS_NOT_CLAIMABLE")

        # Now simulate 6s elapsed (> 5s wait) -> Attempt 2 claim succeeds!
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            diag.lease_expires_at = now - timedelta(seconds=6)
            session.commit()

            res2 = claim_diagnosis(session, self.identity, diag_id, self.custom_policy)
            updated2 = session.get(Diagnosis, diag_id)
            self.assertEqual(updated2.attempt_count, 2)
            token_gen_2 = updated2.lease_token

        # Attempt 2 expired 10s ago (< 15s wait for attempt 3!) -> rejected!
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            diag.lease_expires_at = now - timedelta(seconds=10)
            session.commit()

            with self.assertRaises(HTTPException) as cm:
                claim_diagnosis(session, self.identity, diag_id, self.custom_policy)
            self.assertEqual(cm.exception.status_code, 409)

        # Now simulate 16s elapsed (> 15s wait) -> Attempt 3 claim succeeds!
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            diag.lease_expires_at = now - timedelta(seconds=16)
            session.commit()

            res3 = claim_diagnosis(session, self.identity, diag_id, self.custom_policy)
            updated3 = session.get(Diagnosis, diag_id)
            self.assertEqual(updated3.attempt_count, 3)

        # Attempt 3 expired 20s ago: max_attempt_count (3) reached! -> budget exhausted!
        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            diag.lease_expires_at = now - timedelta(seconds=20)
            session.commit()

            with self.assertRaises(HTTPException) as cm:
                claim_diagnosis(session, self.identity, diag_id, self.custom_policy)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail["code"], "DIAGNOSIS_NOT_CLAIMABLE")


if __name__ == "__main__":
    unittest.main()
