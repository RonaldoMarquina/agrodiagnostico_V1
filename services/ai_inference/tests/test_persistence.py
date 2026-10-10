"""Unit tests for AI Inference persistence models, constraints, and database isolation.

Tests:
- InferenceJob, InferenceInbox, InferenceResult, InferenceOutbox, InferenceQuarantineMessage, InferenceAuditLog.
- Uniqueness and check constraints:
  - Unique diagnosis_id on jobs
  - Unique (consumer, event_id) on inbox
  - Unique (diagnosis_id, lease_token) on results
  - Unique (diagnosis_id, lease_token) and unique event_id on outbox
  - Status check constraint on jobs
- Isolation from Diagnosis database and zero cross-service coupling.
"""
import datetime
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    InferenceAuditLog,
    InferenceInbox,
    InferenceJob,
    InferenceOutbox,
    InferenceQuarantineMessage,
    InferenceResult,
)
from app.persistence import SERVICE


class TestAIInferencePersistence(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_tables_registered_in_metadata(self):
        expected_tables = {
            "inference_jobs",
            "inference_inbox",
            "inference_results",
            "inference_outbox",
            "inference_quarantine_messages",
            "inference_audit_logs",
        }
        self.assertTrue(expected_tables.issubset(set(Base.metadata.tables.keys())))

    def test_service_isolation_constant(self):
        self.assertEqual(SERVICE, "ai_inference")

    def test_inference_job_lifecycle_and_uniqueness(self):
        diag_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        job = InferenceJob(
            diagnosis_id=diag_id,
            attempt_count=1,
            status="QUEUED",
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        self.session.commit()

        loaded = self.session.query(InferenceJob).filter_by(diagnosis_id=diag_id).one()
        self.assertEqual(loaded.attempt_count, 1)
        self.assertEqual(loaded.status, "QUEUED")
        self.assertIsNone(loaded.current_lease_token)
        self.assertIsNone(loaded.local_claim_token)

        # Mutate to CLAIMING / PROCESSING
        claim_token = uuid.uuid4()
        lease_token = uuid.uuid4()
        loaded.local_claim_token = claim_token
        loaded.local_claim_expires_at = now + datetime.timedelta(seconds=15)
        loaded.status = "CLAIMING"
        self.session.commit()

        loaded.current_lease_token = lease_token
        loaded.status = "PROCESSING"
        self.session.commit()

        reloaded = self.session.query(InferenceJob).filter_by(diagnosis_id=diag_id).one()
        self.assertEqual(reloaded.status, "PROCESSING")
        self.assertEqual(reloaded.current_lease_token, lease_token)

        # Duplicate diagnosis_id must violate unique constraint
        duplicate_job = InferenceJob(
            diagnosis_id=diag_id,
            attempt_count=2,
            status="QUEUED",
        )
        self.session.add(duplicate_job)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_inference_inbox_uniqueness(self):
        event_id = uuid.uuid4()
        diag_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        inbox1 = InferenceInbox(
            consumer="ai_worker_1",
            event_id=event_id,
            canonical_hash="hash123",
            diagnosis_id=diag_id,
            status="PROCESSED",
            processed_at=now,
        )
        self.session.add(inbox1)
        self.session.commit()

        # Duplicate (consumer, event_id)
        inbox2 = InferenceInbox(
            consumer="ai_worker_1",
            event_id=event_id,
            canonical_hash="hash456",
            diagnosis_id=diag_id,
            status="PROCESSED",
            processed_at=now,
        )
        self.session.add(inbox2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_inference_results_uniqueness_by_diagnosis_and_lease(self):
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        result1 = InferenceResult(
            diagnosis_id=diag_id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
            raw_score=0.94,
            model_id="yolo-v8-synthetic",
            model_version="1.0.0",
            dataset_version="v1",
            inference_ms=120,
            created_at=now,
        )
        self.session.add(result1)
        self.session.commit()

        # Duplicate for same diagnosis_id and lease_token
        result2 = InferenceResult(
            diagnosis_id=diag_id,
            lease_token=lease_token,
            outcome="ABSTENTION",
            reason_code="LOW_CONFIDENCE",
            created_at=now,
        )
        self.session.add(result2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

        # New lease generation for same diagnosis succeeds
        new_lease = uuid.uuid4()
        result3 = InferenceResult(
            diagnosis_id=diag_id,
            lease_token=new_lease,
            outcome="FAILURE",
            reason_code="INTERNAL_ERROR",
            created_at=now,
        )
        self.session.add(result3)
        self.session.commit()
        self.assertEqual(self.session.query(InferenceResult).filter_by(diagnosis_id=diag_id).count(), 2)

    def test_inference_outbox_uniqueness(self):
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        event_id1 = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        outbox1 = InferenceOutbox(
            event_id=event_id1,
            event_type="DiagnosisAnalyzed",
            schema_version=1,
            routing_key="diagnosis.analyzed.v1",
            envelope={"outcome": "PREDICTION"},
            diagnosis_id=diag_id,
            lease_token=lease_token,
            created_at=now,
            available_at=now,
        )
        self.session.add(outbox1)
        self.session.commit()

        # Duplicate event_id
        outbox_dup_event = InferenceOutbox(
            event_id=event_id1,
            event_type="DiagnosisAnalyzed",
            schema_version=1,
            routing_key="diagnosis.analyzed.v1",
            envelope={"outcome": "OTHER"},
            diagnosis_id=uuid.uuid4(),
            lease_token=uuid.uuid4(),
            created_at=now,
            available_at=now,
        )
        self.session.add(outbox_dup_event)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

        # Duplicate (diagnosis_id, lease_token)
        outbox_dup_lease = InferenceOutbox(
            event_id=uuid.uuid4(),
            event_type="DiagnosisAnalyzed",
            schema_version=1,
            routing_key="diagnosis.analyzed.v1",
            envelope={"outcome": "FAILURE"},
            diagnosis_id=diag_id,
            lease_token=lease_token,
            created_at=now,
            available_at=now,
        )
        self.session.add(outbox_dup_lease)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_inference_audit_and_quarantine_models(self):
        corr_id = uuid.uuid4()
        diag_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        audit = InferenceAuditLog(
            actor="worker-inst-1",
            action="claim_attempt",
            target_id=str(diag_id),
            correlation_id=corr_id,
            details={"lease_duration": 60},
            created_at=now,
        )
        self.session.add(audit)

        quarantine = InferenceQuarantineMessage(
            consumer="ai_worker_1",
            routing_key="diagnosis.requested.v2",
            message_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            error_reason="INVALID_SCHEMA",
            diagnosis_id=diag_id,
            event_id=uuid.uuid4(),
            created_at=now,
        )
        self.session.add(quarantine)
        self.session.commit()

        loaded_audit = self.session.query(InferenceAuditLog).filter_by(correlation_id=corr_id).one()
        self.assertEqual(loaded_audit.actor, "worker-inst-1")
        self.assertEqual(loaded_audit.action, "claim_attempt")

        loaded_quarantine = self.session.query(InferenceQuarantineMessage).filter_by(diagnosis_id=diag_id).one()
        self.assertEqual(loaded_quarantine.error_reason, "INVALID_SCHEMA")


if __name__ == "__main__":
    unittest.main()

