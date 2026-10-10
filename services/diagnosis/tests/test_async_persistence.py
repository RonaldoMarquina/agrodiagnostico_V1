"""Unit tests for Diagnosis async persistence models, constraints, and migration compatibility.

Tests:
- DiagnosisOutbox, DiagnosisInbox, DiagnosisQuarantineMessage tables and relationships.
- Lease and correlation fields on Diagnosis.
- Uniqueness constraints:
  - outbox event_id uniqueness
  - outbox (diagnosis_id, event_type, attempt_number) uniqueness
  - inbox (consumer, event_id) uniqueness
- Non-interference with Incremento 2 data (preservation of image, owner, status, timestamps).
"""
import datetime
import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    Diagnosis,
    DiagnosisInbox,
    DiagnosisOutbox,
    DiagnosisQuarantineMessage,
    IdempotencyKey,
)


class TestDiagnosisAsyncPersistence(unittest.TestCase):
    def setUp(self):
        # Use fresh in-memory SQLite per test
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_async_tables_registered_in_metadata(self):
        expected_tables = {
            "diagnosis_outbox",
            "diagnosis_inbox",
            "diagnosis_quarantine_messages",
        }
        self.assertTrue(expected_tables.issubset(set(Base.metadata.tables.keys())))

    def test_diagnosis_lease_columns_defaults_and_assignment(self):
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc123sha256",
            image_content_type="image/jpeg",
            image_size_bytes=2048,
            image_width=640,
            image_height=480,
            created_at=now,
            updated_at=now,
        )
        self.session.add(diag)
        self.session.commit()

        loaded = self.session.query(Diagnosis).filter_by(id=diag_id).one()
        self.assertEqual(loaded.attempt_count, 0)
        self.assertIsNone(loaded.correlation_id)
        self.assertIsNone(loaded.lease_owner)
        self.assertIsNone(loaded.lease_token)
        self.assertIsNone(loaded.lease_expires_at)
        self.assertIsNone(loaded.processing_deadline_at)
        self.assertIsNone(loaded.recovery_signaled_at)

        # Mutate lease fields
        corr_id = uuid.uuid4()
        lease_tok = uuid.uuid4()
        exp_at = now + datetime.timedelta(seconds=60)
        deadline = now + datetime.timedelta(seconds=300)

        loaded.correlation_id = corr_id
        loaded.lease_owner = "ai_worker_node_1"
        loaded.lease_token = lease_tok
        loaded.lease_expires_at = exp_at
        loaded.attempt_count = 1
        loaded.processing_deadline_at = deadline
        loaded.status = "PROCESANDO"
        self.session.commit()

        reloaded = self.session.query(Diagnosis).filter_by(id=diag_id).one()
        self.assertEqual(reloaded.correlation_id, corr_id)
        self.assertEqual(reloaded.lease_owner, "ai_worker_node_1")
        self.assertEqual(reloaded.lease_token, lease_tok)
        self.assertEqual(reloaded.attempt_count, 1)
        self.assertEqual(reloaded.status, "PROCESANDO")

    def test_outbox_uniqueness_constraint_by_event_id(self):
        event_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        row1 = DiagnosisOutbox(
            event_id=event_id,
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope={"event_id": str(event_id)},
            attempt_number=1,
            created_at=now,
            available_at=now,
        )
        self.session.add(row1)
        self.session.commit()

        row2 = DiagnosisOutbox(
            event_id=event_id,  # duplicate event_id
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope={"event_id": str(event_id)},
            attempt_number=2,
            created_at=now,
            available_at=now,
        )
        self.session.add(row2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_outbox_uniqueness_by_diagnosis_event_attempt(self):
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc123sha256",
            image_content_type="image/jpeg",
            image_size_bytes=2048,
        )
        self.session.add(diag)
        self.session.commit()

        now = datetime.datetime.now(datetime.timezone.utc)
        out1 = DiagnosisOutbox(
            event_id=uuid.uuid4(),
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope={"sample": "data"},
            diagnosis_id=diag_id,
            attempt_number=1,
            created_at=now,
            available_at=now,
        )
        self.session.add(out1)
        self.session.commit()

        # Second outbox row for same diagnosis, same event_type, same attempt_number
        out2 = DiagnosisOutbox(
            event_id=uuid.uuid4(),
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope={"sample": "different"},
            diagnosis_id=diag_id,
            attempt_number=1,  # same attempt number!
            created_at=now,
            available_at=now,
        )
        self.session.add(out2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

        # But attempt_number=2 succeeds (recovery signal for generation 2)
        out3 = DiagnosisOutbox(
            event_id=uuid.uuid4(),
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope={"sample": "recovery_2"},
            diagnosis_id=diag_id,
            attempt_number=2,  # different attempt number
            created_at=now,
            available_at=now,
        )
        self.session.add(out3)
        self.session.commit()
        self.assertEqual(len(diag.outbox_events), 2)

    def test_inbox_uniqueness_constraint_by_consumer_event(self):
        event_id = uuid.uuid4()
        diag_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        inbox1 = DiagnosisInbox(
            consumer="diagnosis_service",
            event_id=event_id,
            canonical_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            diagnosis_id=diag_id,
            status="PROCESSED",
            processed_at=now,
        )
        self.session.add(inbox1)
        self.session.commit()

        # Duplicate (consumer, event_id)
        inbox2 = DiagnosisInbox(
            consumer="diagnosis_service",
            event_id=event_id,
            canonical_hash="differenthash",
            diagnosis_id=diag_id,
            status="PROCESSED",
            processed_at=now,
        )
        self.session.add(inbox2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_increment_2_data_preservation_under_schema(self):
        """Verify that pre-existing Increment 2 diagnosis rows are untouched."""
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        created_time = datetime.datetime(2026, 10, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        updated_time = datetime.datetime(2026, 10, 1, 12, 5, 0, tzinfo=datetime.timezone.utc)

        legacy_row = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.png",
            image_sha256="fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
            image_content_type="image/png",
            image_size_bytes=409600,
            image_width=1024,
            image_height=768,
            created_at=created_time,
            updated_at=updated_time,
            deleted_at=None,
        )
        self.session.add(legacy_row)
        self.session.commit()

        # Read back and assert all Increment 2 attributes are completely identical
        loaded = self.session.query(Diagnosis).filter_by(id=diag_id).one()
        self.assertEqual(loaded.owner_id, owner_id)
        self.assertEqual(loaded.status, "PENDIENTE")
        self.assertEqual(loaded.object_key, f"diagnoses/{diag_id}/original.png")
        self.assertEqual(loaded.image_sha256, "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210")
        self.assertEqual(loaded.image_content_type, "image/png")
        self.assertEqual(loaded.image_size_bytes, 409600)
        self.assertEqual(loaded.image_width, 1024)
        self.assertEqual(loaded.image_height, 768)
        self.assertEqual(loaded.created_at.replace(tzinfo=datetime.timezone.utc), created_time)
        self.assertEqual(loaded.updated_at.replace(tzinfo=datetime.timezone.utc), updated_time)
        self.assertIsNone(loaded.deleted_at)

        # Increment 3 fields are in default uninitialized state
        self.assertEqual(loaded.attempt_count, 0)
        self.assertIsNone(loaded.correlation_id)
        self.assertIsNone(loaded.lease_token)
        self.assertIsNone(loaded.lease_owner)
        self.assertIsNone(loaded.lease_expires_at)
        self.assertIsNone(loaded.processing_deadline_at)
        self.assertIsNone(loaded.recovery_signaled_at)


if __name__ == "__main__":
    unittest.main()
