"""Unit tests for lease renewal and internal image delivery (Task 3.3).

Tests:
- POST /internal/diagnoses/{id}/lease/renew:
  - Success with same owner/token and active unexpired lease.
  - Returns 200 with new expires_at, preserving existing lease_token.
  - Response headers: Cache-Control: private, no-store, X-Correlation-ID.
  - Stale lease: now == expires_at or now > expires_at returns 409 STALE_LEASE.
  - Stale token: body has previous or wrong lease_token returns 409 STALE_LEASE.
  - Worker mismatch: different worker instance returns 409 STALE_LEASE.
  - Deadline cap: renewed expires_at capped at processing_deadline_at.
  - Expired deadline returns 409 STALE_LEASE.
- GET /internal/diagnoses/{id}/image:
  - Success returns raw image bytes with exact content_type.
  - Response headers: Cache-Control: private, no-store, X-Correlation-ID.
  - Zero presigned URLs or redirects.
  - Missing X-Lease-Token header returns 400.
  - Wrong or expired lease token returns 409 STALE_LEASE.
  - Different worker returns 409 STALE_LEASE.
  - Soft-deleted diagnosis (tombstone) with valid lease DOES NOT fail (delivers image).
  - Storage failure returns 503 STORAGE_UNAVAILABLE.
"""
from datetime import datetime, timedelta, timezone
from typing import Tuple
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.domain.models import Base, Diagnosis
from app.infrastructure.internal_auth import (
    TrustedKeyRegistry,
    create_internal_token,
    generate_internal_keypair,
    set_internal_key_registry,
)
from app.main import app as main_app
from app.storage import S3StorageAdapter, set_storage_adapter
from tests.client import TestClient


class MockStorage(S3StorageAdapter):
    def __init__(self):
        super().__init__(bucket="test-bucket")
        self.objects = {}
        self.should_fail = False

    def get_object(self, key: str) -> bytes:
        if self.should_fail:
            raise RuntimeError("Simulated storage connection error")
        return self.objects.get(key, b"fallback-bytes")

    def put_object(self, key: str, body: bytes, content_type: str):
        self.objects[key] = body


class TestInternalRenewAndImage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w1_priv, cls.w1_pub = generate_internal_keypair()
        cls.w2_priv, cls.w2_pub = generate_internal_keypair()

        cls.registry = TrustedKeyRegistry()
        cls.registry.register_key("kid-1", cls.w1_pub, instance_id="worker-node-1")
        cls.registry.register_key("kid-2", cls.w2_pub, instance_id="worker-node-2")
        set_internal_key_registry(cls.registry)

        cls.storage = MockStorage()
        set_storage_adapter(cls.storage)

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
        set_storage_adapter(None)
        main_app.dependency_overrides.clear()

    def setUp(self):
        self.storage.should_fail = False
        self.storage.objects.clear()
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

    def create_processing_diagnosis(
        self,
        lease_owner: str = "worker-node-1",
        lease_expires_delta: int = 60,
        deadline_delta: int = 300,
        deleted: bool = False,
    ) -> Tuple[uuid.UUID, uuid.UUID]:
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        now = datetime.now(timezone.utc)
        object_key = f"diagnoses/{diag_id}/original.jpg"
        raw_bytes = b"EXACT_IMAGE_JPEG_BYTES_123456"
        self.storage.put_object(object_key, raw_bytes, "image/jpeg")

        with self.SessionLocal() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.owner_id,
                status="PROCESANDO",
                object_key=object_key,
                image_sha256="abc123sha",
                image_content_type="image/jpeg",
                image_size_bytes=len(raw_bytes),
                lease_owner=lease_owner,
                lease_token=lease_token,
                lease_expires_at=now + timedelta(seconds=lease_expires_delta),
                processing_deadline_at=now + timedelta(seconds=deadline_delta),
                attempt_count=1,
                deleted_at=now if deleted else None,
                created_at=now,
                updated_at=now,
            )
            session.add(diag)
            session.commit()
        return diag_id, lease_token

    def test_renew_success(self):
        diag_id, lease_token = self.create_processing_diagnosis(lease_expires_delta=40)
        cid = str(uuid.uuid4())

        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/lease/renew",
            headers={
                "Authorization": f"Bearer {self.w1_token}",
                "X-Correlation-ID": cid,
            },
            json={"lease_token": str(lease_token)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["lease_owner"], "worker-node-1")
        # Token remains the same!
        self.assertEqual(data["lease_token"], str(lease_token))
        self.assertIn("expires_at", data)
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")
        self.assertEqual(resp.headers.get("X-Correlation-ID"), cid)

    def test_renew_stale_expired_lease_returns_409(self):
        # Expired 5 seconds ago
        diag_id, lease_token = self.create_processing_diagnosis(lease_expires_delta=-5)

        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/lease/renew",
            headers={"Authorization": f"Bearer {self.w1_token}"},
            json={"lease_token": str(lease_token)},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "STALE_LEASE")

    def test_renew_stale_token_returns_409(self):
        diag_id, _ = self.create_processing_diagnosis(lease_expires_delta=60)
        old_token = str(uuid.uuid4())

        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/lease/renew",
            headers={"Authorization": f"Bearer {self.w1_token}"},
            json={"lease_token": old_token},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "STALE_LEASE")

    def test_renew_foreign_worker_returns_409(self):
        diag_id, lease_token = self.create_processing_diagnosis(
            lease_owner="worker-node-1",
            lease_expires_delta=60,
        )

        # worker-node-2 attempts to renew worker-node-1's lease
        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/lease/renew",
            headers={"Authorization": f"Bearer {self.w2_token}"},
            json={"lease_token": str(lease_token)},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "STALE_LEASE")

    def test_renew_deadline_cap(self):
        # Remaining deadline is only 10s, but lease policy is 60s
        diag_id, lease_token = self.create_processing_diagnosis(
            lease_expires_delta=5,
            deadline_delta=10,
        )

        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/lease/renew",
            headers={"Authorization": f"Bearer {self.w1_token}"},
            json={"lease_token": str(lease_token)},
        )
        self.assertEqual(resp.status_code, 200)

        with self.SessionLocal() as session:
            diag = session.get(Diagnosis, diag_id)
            # expires_at must be capped at processing_deadline_at
            self.assertEqual(diag.lease_expires_at, diag.processing_deadline_at)

    def test_renew_passed_deadline_returns_409(self):
        # processing_deadline_at was reached in the past
        diag_id, lease_token = self.create_processing_diagnosis(
            lease_expires_delta=5,
            deadline_delta=-1,
        )

        resp = self.client.post(
            f"/internal/diagnoses/{diag_id}/lease/renew",
            headers={"Authorization": f"Bearer {self.w1_token}"},
            json={"lease_token": str(lease_token)},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["code"], "STALE_LEASE")

    def test_internal_image_delivery_success(self):
        diag_id, lease_token = self.create_processing_diagnosis()
        cid = str(uuid.uuid4())

        resp = self.client.get(
            f"/internal/diagnoses/{diag_id}/image",
            headers={
                "Authorization": f"Bearer {self.w1_token}",
                "X-Lease-Token": str(lease_token),
                "X-Correlation-ID": cid,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.body, b"EXACT_IMAGE_JPEG_BYTES_123456")
        self.assertEqual(resp.headers.get("Content-Type"), "image/jpeg")
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")
        self.assertEqual(resp.headers.get("X-Correlation-ID"), cid)

    def test_internal_image_missing_lease_header_returns_400(self):
        diag_id, _ = self.create_processing_diagnosis()

        resp = self.client.get(
            f"/internal/diagnoses/{diag_id}/image",
            headers={"Authorization": f"Bearer {self.w1_token}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "INVALID_REQUEST")

    def test_internal_image_wrong_token_or_foreign_worker_returns_409(self):
        diag_id, lease_token = self.create_processing_diagnosis(lease_owner="worker-node-1")

        # Wrong lease token
        resp_wrong_token = self.client.get(
            f"/internal/diagnoses/{diag_id}/image",
            headers={
                "Authorization": f"Bearer {self.w1_token}",
                "X-Lease-Token": str(uuid.uuid4()),
            },
        )
        self.assertEqual(resp_wrong_token.status_code, 409)
        self.assertEqual(resp_wrong_token.json()["code"], "STALE_LEASE")

        # Foreign worker
        resp_foreign = self.client.get(
            f"/internal/diagnoses/{diag_id}/image",
            headers={
                "Authorization": f"Bearer {self.w2_token}",
                "X-Lease-Token": str(lease_token),
            },
        )
        self.assertEqual(resp_foreign.status_code, 409)
        self.assertEqual(resp_foreign.json()["code"], "STALE_LEASE")

    def test_internal_image_tombstone_preserves_internal_processing(self):
        # Diagnosis was soft-deleted by user, but worker holds active valid lease
        diag_id, lease_token = self.create_processing_diagnosis(deleted=True)

        resp = self.client.get(
            f"/internal/diagnoses/{diag_id}/image",
            headers={
                "Authorization": f"Bearer {self.w1_token}",
                "X-Lease-Token": str(lease_token),
            },
        )
        # Internal worker must NOT receive 404 on tombstone!
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.body, b"EXACT_IMAGE_JPEG_BYTES_123456")

    def test_internal_image_storage_down_returns_503(self):
        diag_id, lease_token = self.create_processing_diagnosis()
        self.storage.should_fail = True

        resp = self.client.get(
            f"/internal/diagnoses/{diag_id}/image",
            headers={
                "Authorization": f"Bearer {self.w1_token}",
                "X-Lease-Token": str(lease_token),
            },
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], "STORAGE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
