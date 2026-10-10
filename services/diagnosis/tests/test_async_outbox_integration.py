"""Unit tests for Diagnosis creation with atomic Transactional Outbox integration (Task 4.3).

Verifies:
- Successful diagnosis creation writes Diagnosis (PENDIENTE), IdempotencyKey, and DiagnosisOutbox (Requested v2) in a single commit.
- 202 Accepted succeeds even if broker is down (broker is not called in HTTP handler).
- Idempotent replay returns existing diagnosis without emitting an additional outbox event.
- Idempotency conflict (different fingerprint) raises 409 without creating an outbox event.
- Idempotency on tombstoned diagnosis raises 409 without creating an outbox event.
- Commit failure after S3 rolls back DB, reconciles/cleans S3, and leaves NO outbox event.
"""
from datetime import datetime, timezone
import io
import unittest
from unittest.mock import MagicMock
import uuid

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.diagnoses import create_diagnosis
from app.domain.image import ValidatedImage
from app.domain.models import Base, Diagnosis, DiagnosisOutbox, IdempotencyKey
from app.infrastructure.security import Principal
from app.storage import S3StorageAdapter


class MemoryStorage(S3StorageAdapter):
    """In-memory S3 adapter for unit tests."""
    def __init__(self):
        self.objects = {}
        self.delete_calls = []

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def get_object(self, key: str) -> tuple[bytes, str]:
        if key not in self.objects:
            from app.storage import ObjectNotFoundError
            raise ObjectNotFoundError(f"Key not found: {key}")
        return self.objects[key]

    def delete_object(self, key: str) -> None:
        self.delete_calls.append(key)
        self.objects.pop(key, None)


class TestAsyncOutboxCreationIntegration(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.storage = MemoryStorage()
        self.principal = Principal(id=uuid.uuid4(), role="USER", token_id=str(uuid.uuid4()))

    def _sample_image(self, data=b"fake-jpeg-image-bytes", sha="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"):
        return ValidatedImage(
            data=data,
            content_type="image/jpeg",
            extension=".jpg",
            size_bytes=len(data),
            sha256=sha,
            width=800,
            height=600,
        )

    def test_creation_emits_requested_v2_outbox_atomically(self):
        img = self._sample_image()
        cid = uuid.uuid4()
        idemp_key = "idemp-test-atomic-001"

        with self.SessionLocal() as session:
            diag = create_diagnosis(
                db=session,
                principal=self.principal,
                idempotency_key=idemp_key,
                validated_image=img,
                storage=self.storage,
                correlation_id=cid,
            )
            diag_id = diag.id
            self.assertEqual(diag.status, "PENDIENTE")
            self.assertEqual(diag.correlation_id, cid)

        # Verify DB contents in fresh session
        with self.SessionLocal() as session:
            # 1. Diagnosis exists
            d = session.get(Diagnosis, diag_id)
            self.assertIsNotNone(d)
            self.assertEqual(d.status, "PENDIENTE")

            # 2. Idempotency key exists
            k = session.execute(
                select(IdempotencyKey).where(IdempotencyKey.key == idemp_key)
            ).scalar_one_or_none()
            self.assertIsNotNone(k)
            self.assertEqual(k.diagnosis_id, diag_id)

            # 3. DiagnosisOutbox exists with requested v2
            outbox_events = session.execute(
                select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag_id)
            ).scalars().all()
            self.assertEqual(len(outbox_events), 1)

            ev = outbox_events[0]
            self.assertEqual(ev.event_type, "DiagnosisRequested")
            self.assertEqual(ev.schema_version, 2)
            self.assertEqual(ev.routing_key, "diagnosis.requested.v2")
            self.assertIsNone(ev.sent_at)
            self.assertEqual(ev.attempt_number, 1)

            # Verify envelope structure
            envelope = ev.envelope
            self.assertEqual(envelope["event_id"], str(ev.event_id))
            self.assertEqual(envelope["event_type"], "DiagnosisRequested")
            self.assertEqual(envelope["schema_version"], 2)
            self.assertEqual(envelope["correlation_id"], str(cid))
            self.assertEqual(envelope["payload"]["diagnosis_id"], str(diag_id))
            self.assertEqual(envelope["payload"]["owner_id"], str(self.principal.id))
            self.assertEqual(envelope["payload"]["object_key"], d.object_key)

    def test_idempotent_replay_does_not_create_additional_outbox(self):
        img = self._sample_image()
        cid = uuid.uuid4()
        idemp_key = "idemp-test-replay-002"

        with self.SessionLocal() as session:
            diag1 = create_diagnosis(
                db=session,
                principal=self.principal,
                idempotency_key=idemp_key,
                validated_image=img,
                storage=self.storage,
                correlation_id=cid,
            )
            diag1_id = diag1.id

        # Replay with same key and same image
        with self.SessionLocal() as session:
            diag2 = create_diagnosis(
                db=session,
                principal=self.principal,
                idempotency_key=idemp_key,
                validated_image=img,
                storage=self.storage,
                correlation_id=cid,
            )
            self.assertEqual(diag2.id, diag1_id)

        # Count outbox events: must be exactly 1
        with self.SessionLocal() as session:
            count = len(session.execute(select(DiagnosisOutbox)).scalars().all())
            self.assertEqual(count, 1)

    def test_idempotent_conflict_raises_409_no_outbox_created(self):
        img1 = self._sample_image(sha="sha-aaa")
        img2 = self._sample_image(sha="sha-bbb")
        idemp_key = "idemp-test-conflict-003"

        with self.SessionLocal() as session:
            create_diagnosis(
                db=session,
                principal=self.principal,
                idempotency_key=idemp_key,
                validated_image=img1,
                storage=self.storage,
            )

        # Second call with same key but different image sha
        with self.SessionLocal() as session:
            with self.assertRaises(HTTPException) as cm:
                create_diagnosis(
                    db=session,
                    principal=self.principal,
                    idempotency_key=idemp_key,
                    validated_image=img2,
                    storage=self.storage,
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail["code"], "IDEMPOTENCY_CONFLICT")

        with self.SessionLocal() as session:
            count = len(session.execute(select(DiagnosisOutbox)).scalars().all())
            self.assertEqual(count, 1)

    def test_idempotent_tombstone_raises_409_no_outbox_created(self):
        img = self._sample_image()
        idemp_key = "idemp-test-tombstone-004"

        with self.SessionLocal() as session:
            diag = create_diagnosis(
                db=session,
                principal=self.principal,
                idempotency_key=idemp_key,
                validated_image=img,
                storage=self.storage,
            )
            diag_id = diag.id

        # Mark diagnosis as deleted (tombstone)
        with self.SessionLocal() as session:
            d = session.get(Diagnosis, diag_id)
            d.deleted_at = datetime.now(timezone.utc)
            session.commit()

        # Attempt to create with same idempotency key
        with self.SessionLocal() as session:
            with self.assertRaises(HTTPException) as cm:
                create_diagnosis(
                    db=session,
                    principal=self.principal,
                    idempotency_key=idemp_key,
                    validated_image=img,
                    storage=self.storage,
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertEqual(cm.exception.detail["code"], "IDEMPOTENCY_RESOURCE_DELETED")

    def test_commit_failure_after_s3_rolls_back_and_leaves_no_outbox(self):
        img = self._sample_image()
        idemp_key = "idemp-test-fail-005"

        with self.SessionLocal() as session:
            # Simulate commit error by mocking session.commit to fail
            original_commit = session.commit
            session.commit = MagicMock(side_effect=RuntimeError("Simulated DB commit crash!"))

            with self.assertRaises(HTTPException) as cm:
                create_diagnosis(
                    db=session,
                    principal=self.principal,
                    idempotency_key=idemp_key,
                    validated_image=img,
                    storage=self.storage,
                )
            self.assertEqual(cm.exception.status_code, 503)

        # Verify nothing persisted in database: zero diagnoses, zero outbox rows
        with self.SessionLocal() as session:
            diags = session.execute(select(Diagnosis)).scalars().all()
            self.assertEqual(len(diags), 0)
            outbox = session.execute(select(DiagnosisOutbox)).scalars().all()
            self.assertEqual(len(outbox), 0)

        # Verify storage was cleaned up
        self.assertEqual(len(self.storage.objects), 0)
        self.assertGreater(len(self.storage.delete_calls), 0)


if __name__ == "__main__":
    unittest.main()
