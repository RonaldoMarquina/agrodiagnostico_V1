"""Tests for AI Inference quarantine persistence and transactional audit logging.

Verifies:
- Rollback on audit/commit failure preserves data integrity.
- Absence of raw message payloads or secrets in quarantine and audit logs.
- Sanitization of sensitive keys (passwords, tokens, keys).
"""
import hashlib
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import Base, InferenceAuditLog, InferenceJob, InferenceQuarantineMessage
from app.infrastructure.quarantine import record_audit_log, record_quarantine_message


class TestAIInferenceQuarantineAndAudit(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_quarantine_stores_only_hash_and_metadata_no_raw_payload(self):
        raw_evil_payload = b'{"corrupted": true, "auth_token": "WORKER_INTERNAL_SECRET_99"}'
        expected_hash = hashlib.sha256(raw_evil_payload).hexdigest()
        diag_id = uuid.uuid4()
        event_id = uuid.uuid4()

        quarantine = record_quarantine_message(
            session=self.session,
            consumer="ai_worker_1",
            routing_key="diagnosis.requested.v2",
            raw_payload=raw_evil_payload,
            error_reason="UNKNOWN_SCHEMA_VERSION",
            diagnosis_id=diag_id,
            event_id=event_id,
        )
        self.session.commit()

        loaded = self.session.query(InferenceQuarantineMessage).filter_by(id=quarantine.id).one()
        self.assertEqual(loaded.message_hash, expected_hash)
        self.assertEqual(loaded.consumer, "ai_worker_1")
        self.assertEqual(loaded.routing_key, "diagnosis.requested.v2")
        self.assertEqual(loaded.error_reason, "UNKNOWN_SCHEMA_VERSION")
        self.assertEqual(loaded.diagnosis_id, diag_id)
        self.assertEqual(loaded.event_id, event_id)

        # Raw payload bytes or secrets do not exist on the model
        self.assertFalse(hasattr(loaded, "raw_payload"))
        self.assertNotIn("WORKER_INTERNAL_SECRET_99", str(loaded.__dict__))

    def test_audit_log_sanitizes_sensitive_keys(self):
        corr_id = uuid.uuid4()
        details = {
            "worker": "inst-1",
            "password": "db_secret_pw",
            "access_token": "header.payload.sig",
            "key": "private_ed25519_key_bytes",
            "metric": 100,
        }

        entry = record_audit_log(
            session=self.session,
            actor="worker-inst-1",
            action="claim_attempt",
            correlation_id=corr_id,
            target_id="target-123",
            details=details,
        )
        self.session.commit()

        loaded = self.session.query(InferenceAuditLog).filter_by(id=entry.id).one()
        self.assertEqual(loaded.details["password"], "[REDACTED]")
        self.assertEqual(loaded.details["access_token"], "[REDACTED]")
        self.assertEqual(loaded.details["key"], "[REDACTED]")
        self.assertEqual(loaded.details["metric"], 100)

    def test_rollback_on_audit_failure_preserves_atomic_transaction(self):
        diag_id = uuid.uuid4()
        job = InferenceJob(
            diagnosis_id=diag_id,
            status="QUEUED",
        )
        self.session.add(job)
        self.session.commit()

        # Update job and try to add invalid audit log in same transaction
        try:
            job_to_update = self.session.query(InferenceJob).filter_by(diagnosis_id=diag_id).one()
            job_to_update.status = "PROCESSING"

            # Failure during audit insertion (correlation_id=None violates not-null)
            record_audit_log(
                session=self.session,
                actor="worker",
                action="claim",
                correlation_id=None,
            )
            self.session.commit()
        except Exception:
            self.session.rollback()

        # Job status MUST NOT have changed
        reloaded = self.session.query(InferenceJob).filter_by(diagnosis_id=diag_id).one()
        self.assertEqual(reloaded.status, "QUEUED")
        self.assertEqual(self.session.query(InferenceAuditLog).count(), 0)


if __name__ == "__main__":
    unittest.main()

