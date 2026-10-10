"""Unit and integration tests for Diagnosis operational replay and reconstruction CLI.

Verifies Task 7.2:
- Mandatory operator context (actor, reason); execution denied if missing.
- Envelope immutability: exact event_id and envelope preserved, never edited.
- Idempotency of replay operations.
- Terminal replay does not revive or modify terminal states (COMPLETADO, NO_CONCLUYENTE, FALLIDO, CANCELADO).
- Explicit reconstruction of invalid quarantined messages creates a brand new valid
  DiagnosisRequested v2 event with fresh event_id for PENDIENTE diagnoses and audits.
"""
from datetime import datetime, timezone
import json
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.replay import replay_outbox_event, reconstruct_quarantined_message
from app.domain.models import (
    Base,
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisOutbox,
    DiagnosisQuarantineMessage,
)


class TestReplayAndReconstruction(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_execution_denied_without_required_context(self):
        # Missing actor
        with self.assertRaises(ValueError) as ctx:
            replay_outbox_event(
                db=self.session,
                actor="",
                reason="Incident fix",
                event_id=uuid.uuid4(),
            )
        self.assertIn("actor must be specified", str(ctx.exception))

        # Missing reason
        with self.assertRaises(ValueError) as ctx:
            replay_outbox_event(
                db=self.session,
                actor="ops-admin",
                reason="   ",
                event_id=uuid.uuid4(),
            )
        self.assertIn("reason must be specified", str(ctx.exception))

    def test_replay_valid_event_preserves_envelope_immutability(self):
        diag_id = uuid.uuid4()
        event_id = uuid.uuid4()
        original_envelope = {
            "event_id": str(event_id),
            "event_type": "DiagnosisRequested",
            "schema_version": 2,
            "occurred_at": "2026-10-08T12:00:00Z",
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "owner_id": str(uuid.uuid4()),
                "object_key": f"diagnoses/{diag_id}/original.jpg",
            },
        }

        # Seed diagnosis and sent outbox event
        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc",
            image_content_type="image/jpeg",
            image_size_bytes=100,
        )
        outbox = DiagnosisOutbox(
            event_id=event_id,
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope=original_envelope,
            diagnosis_id=diag_id,
            attempt_number=1,
            sent_at=datetime.now(timezone.utc),
            claim_token=uuid.uuid4(),
        )
        self.session.add_all([diag, outbox])
        self.session.commit()

        # Replay event in APPLY mode
        result = replay_outbox_event(
            db=self.session,
            actor="operator-alice",
            reason="Network partition recovery",
            event_id=event_id,
            apply=True,
        )

        self.assertEqual(result.action, "REPLAY")
        self.assertEqual(result.status, "SCHEDULED")
        self.assertEqual(result.event_id, event_id)

        # Verify DB: sent_at and claim_token are reset for resend, envelope is untouched
        reloaded = self.session.query(DiagnosisOutbox).filter_by(event_id=event_id).one()
        self.assertIsNone(reloaded.sent_at)
        self.assertIsNone(reloaded.claim_token)
        self.assertEqual(reloaded.envelope, original_envelope)

        # Audit log verified
        audit = self.session.query(DiagnosisAuditLog).filter_by(action="OPERATIONAL_REPLAY").one()
        self.assertEqual(audit.details["actor"], "operator-alice")
        self.assertEqual(audit.details["reason"], "Network partition recovery")
        self.assertEqual(audit.target_id, str(event_id))

    def test_replay_idempotency(self):
        diag_id = uuid.uuid4()
        event_id = uuid.uuid4()
        envelope = {
            "event_id": str(event_id),
            "event_type": "DiagnosisRequested",
            "schema_version": 2,
            "payload": {"diagnosis_id": str(diag_id)},
        }

        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc",
            image_content_type="image/jpeg",
            image_size_bytes=100,
        )
        outbox = DiagnosisOutbox(
            event_id=event_id,
            event_type="DiagnosisRequested",
            schema_version=2,
            routing_key="diagnosis.requested.v2",
            envelope=envelope,
            diagnosis_id=diag_id,
        )
        self.session.add_all([diag, outbox])
        self.session.commit()

        # First replay
        res1 = replay_outbox_event(
            db=self.session,
            actor="operator-1",
            reason="Run 1",
            event_id=event_id,
            apply=True,
        )
        self.assertEqual(res1.status, "SCHEDULED")

        # Second replay of same event
        res2 = replay_outbox_event(
            db=self.session,
            actor="operator-1",
            reason="Run 2",
            event_id=event_id,
            apply=True,
        )
        self.assertEqual(res2.status, "SCHEDULED")

        # Total outbox rows remains exactly 1 (no duplication)
        self.assertEqual(self.session.query(DiagnosisOutbox).count(), 1)

    def test_terminal_replay_does_not_modify_terminal_state(self):
        for terminal_status in ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO", "CANCELADO"):
            with self.subTest(terminal_status=terminal_status):
                diag_id = uuid.uuid4()
                event_id = uuid.uuid4()
                diag = Diagnosis(
                    id=diag_id,
                    owner_id=uuid.uuid4(),
                    status=terminal_status,
                    object_key=f"diagnoses/{diag_id}/original.jpg",
                    image_sha256="abc",
                    image_content_type="image/jpeg",
                    image_size_bytes=100,
                )
                outbox = DiagnosisOutbox(
                    event_id=event_id,
                    event_type="DiagnosisRequested",
                    schema_version=2,
                    routing_key="diagnosis.requested.v2",
                    envelope={"event_id": str(event_id)},
                    diagnosis_id=diag_id,
                    sent_at=datetime.now(timezone.utc),
                )
                self.session.add_all([diag, outbox])
                self.session.commit()

                result = replay_outbox_event(
                    db=self.session,
                    actor="operator-bob",
                    reason="Accidental replay on terminal",
                    event_id=event_id,
                    apply=True,
                )

                self.assertEqual(result.status, "SKIPPED_TERMINAL")

                # Verify diagnosis status is untouched
                reloaded_diag = self.session.query(Diagnosis).filter_by(id=diag_id).one()
                self.assertEqual(reloaded_diag.status, terminal_status)

                # Outbox event was NOT reset to unsent
                reloaded_outbox = self.session.query(DiagnosisOutbox).filter_by(event_id=event_id).one()
                self.assertIsNotNone(reloaded_outbox.sent_at)

    def test_explicit_reconstruction_of_quarantined_message_creates_new_valid_event(self):
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        quarantine_id = uuid.uuid4()

        # Seed PENDIENTE diagnosis and quarantine entry
        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc",
            image_content_type="image/jpeg",
            image_size_bytes=100,
        )
        q_msg = DiagnosisQuarantineMessage(
            id=quarantine_id,
            consumer="diagnosis",
            routing_key="diagnosis.requested.v2",
            message_hash="corrupted_hash",
            error_reason="INVALID_SCHEMA: Malformed JSON",
            diagnosis_id=diag_id,
        )
        self.session.add_all([diag, q_msg])
        self.session.commit()

        # Execute reconstruction in APPLY mode
        result = reconstruct_quarantined_message(
            db=self.session,
            actor="senior-operator",
            reason="Reconstructing request after producer patch",
            quarantine_id=quarantine_id,
            apply=True,
        )

        self.assertEqual(result.action, "RECONSTRUCT")
        self.assertEqual(result.status, "SCHEDULED")
        new_event_id = result.event_id
        self.assertNotEqual(new_event_id, uuid.UUID(int=0))

        # Check that new valid DiagnosisRequested v2 is in outbox
        new_outbox = self.session.query(DiagnosisOutbox).filter_by(event_id=new_event_id).one()
        self.assertEqual(new_outbox.event_type, "DiagnosisRequested")
        self.assertEqual(new_outbox.schema_version, 2)
        self.assertEqual(new_outbox.routing_key, "diagnosis.requested.v2")
        self.assertEqual(new_outbox.envelope["payload"]["diagnosis_id"], str(diag_id))
        self.assertEqual(new_outbox.envelope["payload"]["object_key"], f"diagnoses/{diag_id}/original.jpg")

        # Check audit log
        audit = self.session.query(DiagnosisAuditLog).filter_by(action="EXPLICIT_RECONSTRUCTION").one()
        self.assertEqual(audit.details["actor"], "senior-operator")
        self.assertEqual(audit.details["quarantine_id"], str(quarantine_id))

    def test_reconstruction_skipped_if_diagnosis_not_pending(self):
        diag_id = uuid.uuid4()
        quarantine_id = uuid.uuid4()

        # Diagnosis is PROCESANDO or terminal
        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="PROCESANDO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc",
            image_content_type="image/jpeg",
            image_size_bytes=100,
        )
        q_msg = DiagnosisQuarantineMessage(
            id=quarantine_id,
            consumer="diagnosis",
            routing_key="diagnosis.requested.v2",
            message_hash="some_hash",
            error_reason="INVALID_SCHEMA",
            diagnosis_id=diag_id,
        )
        self.session.add_all([diag, q_msg])
        self.session.commit()

        result = reconstruct_quarantined_message(
            db=self.session,
            actor="operator-1",
            reason="Test non-pending",
            quarantine_id=quarantine_id,
            apply=True,
        )

        self.assertEqual(result.status, "SKIPPED_NOT_PENDING")
        self.assertEqual(self.session.query(DiagnosisOutbox).count(), 0)


if __name__ == "__main__":
    unittest.main()

