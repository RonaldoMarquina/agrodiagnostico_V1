"""Tests for Diagnosis quarantine persistence and transactional audit logging.

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

from app.domain.models import Base, Diagnosis, DiagnosisAuditLog, DiagnosisQuarantineMessage
from app.infrastructure.quarantine import record_audit_log, record_quarantine_message, sanitize_details


class TestDiagnosisQuarantineAndAudit(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_quarantine_stores_only_hash_and_metadata_no_raw_payload(self):
        raw_evil_payload = b'{"malicious": "DROP TABLE", "secret_token": "SUPER_SECRET_123"}'
        expected_hash = hashlib.sha256(raw_evil_payload).hexdigest()
        diag_id = uuid.uuid4()
        event_id = uuid.uuid4()

        quarantine = record_quarantine_message(
            session=self.session,
            consumer="diagnosis_consumer",
            routing_key="diagnosis.analyzed.v1",
            raw_payload=raw_evil_payload,
            error_reason="INVALID_SCHEMA_MALFORMED_JSON",
            diagnosis_id=diag_id,
            event_id=event_id,
        )
        self.session.commit()

        loaded = self.session.query(DiagnosisQuarantineMessage).filter_by(id=quarantine.id).one()
        self.assertEqual(loaded.message_hash, expected_hash)
        self.assertEqual(loaded.consumer, "diagnosis_consumer")
        self.assertEqual(loaded.routing_key, "diagnosis.analyzed.v1")
        self.assertEqual(loaded.error_reason, "INVALID_SCHEMA_MALFORMED_JSON")
        self.assertEqual(loaded.diagnosis_id, diag_id)
        self.assertEqual(loaded.event_id, event_id)

        # Raw payload bytes or secrets do not exist on the model
        self.assertFalse(hasattr(loaded, "raw_payload"))
        self.assertNotIn("SUPER_SECRET_123", str(loaded.__dict__))

    def test_audit_log_sanitizes_sensitive_keys(self):
        actor_id = uuid.uuid4()
        corr_id = uuid.uuid4()
        details = {
            "action_desc": "worker claim",
            "password": "secret_db_password",
            "jwt_token": "eyJhbGciOi...",
            "private_key": "-----BEGIN PRIVATE KEY-----",
            "safe_param": 42,
            "nested": {
                "secret_key": "hidden",
                "nested_safe": True,
            },
        }

        entry = record_audit_log(
            session=self.session,
            actor_id=actor_id,
            action="claim_diagnosis",
            target_type="diagnosis",
            correlation_id=corr_id,
            target_id="some-id",
            details=details,
        )
        self.session.commit()

        loaded = self.session.query(DiagnosisAuditLog).filter_by(id=entry.id).one()
        self.assertEqual(loaded.details["password"], "[REDACTED]")
        self.assertEqual(loaded.details["jwt_token"], "[REDACTED]")
        self.assertEqual(loaded.details["private_key"], "[REDACTED]")
        self.assertEqual(loaded.details["safe_param"], 42)
        self.assertEqual(loaded.details["nested"]["secret_key"], "[REDACTED]")
        self.assertEqual(loaded.details["nested"]["nested_safe"], True)

    def test_rollback_on_audit_failure_preserves_atomic_transaction(self):
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="hash123",
            image_content_type="image/jpeg",
            image_size_bytes=100,
        )
        self.session.add(diag)
        self.session.commit()

        # Begin a transactional operation: update diagnosis status AND insert audit log
        try:
            diag_to_update = self.session.query(Diagnosis).filter_by(id=diag_id).one()
            diag_to_update.status = "PROCESANDO"

            # Simulate failure during audit insertion (e.g., None for non-nullable correlation_id or error)
            record_audit_log(
                session=self.session,
                actor_id=uuid.uuid4(),
                action="invalid_audit",
                target_type="diagnosis",
                correlation_id=None,  # Not nullable!
            )
            self.session.commit()
        except Exception:
            self.session.rollback()

        # Diagnosis status MUST NOT have changed to PROCESANDO
        reloaded = self.session.query(Diagnosis).filter_by(id=diag_id).one()
        self.assertEqual(reloaded.status, "PENDIENTE")
        self.assertEqual(self.session.query(DiagnosisAuditLog).count(), 0)


if __name__ == "__main__":
    unittest.main()

