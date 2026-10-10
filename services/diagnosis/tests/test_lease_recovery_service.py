"""Unit and integration test suite for lease recovery service (Task 6.3).

Tests:
- Worker dies after attempt 1: after lease expiration and 5s wait, recovery emits
  DiagnosisRequested v2 signal with attempt_number=2; diagnosis stays in PROCESANDO.
- Worker dies after attempt 2: requires 15s wait; recovery emits attempt_number=3.
- Budget exhaustion: when attempt 3 lease expires and wait passes, recovery transitions
  atómicamente to FALLIDO (reason_code=PROCESSING_TIMEOUT) and emits a single DiagnosisFinished v1 event.
- Deadline reached: when processing_deadline_at is exceeded, recovery transitions to FALLIDO/PROCESSING_TIMEOUT.
- Single signal per generation: running recovery repeatedly emits only ONE signal for that generation.
- PENDIENTE without first claim: never expired, has no deadline, and is ignored by the recuperador.
- Race condition between result and recuperador:
  * Result wins: diagnosis transitions to COMPLETADO; recuperador skips it.
  * Recuperador wins: diagnosis transitions to FALLIDO; subsequent result is discarded as late.
"""
from datetime import datetime, timedelta, timezone
import json
import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.lease_recovery import recover_expired_leases
from app.consumer import DiagnosisAnalyzedConsumer
from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisOutbox,
    Problem,
    Recommendation,
)
from app.infrastructure.cursor import format_utc_iso
from app.infrastructure.event_validation import validate_diagnosis_finished_v1
from app.infrastructure.lease_config import LeasePolicy


class MockAMQPChannel:
    def __init__(self):
        self.acked_tags = []
        self.nacked_tags = []

    def basic_ack(self, delivery_tag):
        self.acked_tags.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue=True):
        self.nacked_tags.append((delivery_tag, requeue))


class TestLeaseRecoveryService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        # Policy with short test timeouts: 60s lease, 5s wait att 2, 15s wait att 3, max 3 att, 300s deadline
        self.policy = LeasePolicy(
            lease_duration_seconds=60,
            heartbeat_seconds=20,
            processing_deadline_seconds=300,
            max_attempt_count=3,
            recovery_wait_seconds_attempt_2=5,
            recovery_wait_seconds_attempt_3=15,
        )

        # Seed catalog
        with self.Session() as session:
            crop = Crop(code="POTATO", name="Papa", active=True)
            prob = Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO", name="Tizón", type="DISEASE", model_supported=True, active=True)
            rec = Recommendation(
                problem_code="POTATO_EARLY_BLIGHT",
                version=1,
                title="Manejo Tizón",
                summary="Control cultural.",
                cultural_practices=["Rotación"],
                biological_control=["Bacillus"],
                preventive_measures=["Monitoreo"],
                source_refs=["Fuente"],
                review_reference="REV-1",
                reviewed_by="Ing.",
                reviewed_at=datetime.now(timezone.utc),
                active=True,
            )
            session.add_all([crop, prob, rec])
            session.commit()

    def tearDown(self):
        self.engine.dispose()

    def _create_procesando_diagnosis(
        self,
        attempt_count=1,
        expired_seconds_ago=10,
        deadline_in_seconds=240,
        recovery_signaled_at=None,
    ) -> Diagnosis:
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        expires_at = now - timedelta(seconds=expired_seconds_ago)
        deadline_at = now + timedelta(seconds=deadline_in_seconds)

        with self.Session() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=uuid.uuid4(),
                status="PROCESANDO",
                object_key=f"diagnoses/{diag_id}/original.jpg",
                image_sha256="fake_sha256",
                image_content_type="image/jpeg",
                image_size_bytes=1024,
                lease_owner="ai-worker-1",
                lease_token=uuid.uuid4(),
                lease_expires_at=expires_at,
                attempt_count=attempt_count,
                processing_deadline_at=deadline_at,
                recovery_signaled_at=recovery_signaled_at,
                correlation_id=uuid.uuid4(),
            )
            session.add(diag)
            session.commit()
            return diag

    def test_worker_dies_attempt_1_emits_generation_2_signal(self):
        """Worker dies during attempt 1: after 5s wait, recovery emits DiagnosisRequested v2 with attempt_number=2."""
        # Expired 10s ago (greater than 5s wait for attempt 1 -> 2)
        diag = self._create_procesando_diagnosis(attempt_count=1, expired_seconds_ago=10)

        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action"], "SIGNAL_EMITTED")
            self.assertEqual(actions[0]["attempt_number"], 2)

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            # Status stays PROCESANDO, not reverted to PENDIENTE
            self.assertEqual(diag_rec.status, "PROCESANDO")
            self.assertIsNotNone(diag_rec.recovery_signaled_at)

            # DiagnosisRequested v2 outbox event emitted
            outbox = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).scalar_one()
            self.assertEqual(outbox.event_type, "DiagnosisRequested")
            self.assertEqual(outbox.schema_version, 2)
            self.assertEqual(outbox.attempt_number, 2)

    def test_worker_dies_attempt_1_waits_minimum_5_seconds(self):
        """If expired only 2 seconds ago (less than 5s wait), recovery skips until wait passes."""
        diag = self._create_procesando_diagnosis(attempt_count=1, expired_seconds_ago=2)

        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 0)

        with self.Session() as session:
            outbox_recs = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).all()
            self.assertEqual(len(outbox_recs), 0)

    def test_worker_dies_attempt_2_requires_15_second_wait(self):
        """Attempt 2 requires 15s wait before generation 3 signal is emitted."""
        # Expired 10s ago (less than 15s wait for attempt 2 -> 3)
        diag = self._create_procesando_diagnosis(attempt_count=2, expired_seconds_ago=10)

        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 0)

        # Update expiration to 20s ago (greater than 15s wait)
        with self.Session() as session:
            d = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            d.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=20)
            session.commit()

        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action"], "SIGNAL_EMITTED")
            self.assertEqual(actions[0]["attempt_number"], 3)

    def test_budget_exhaustion_on_attempt_3_transitions_to_fallido(self):
        """When attempt 3 lease expires and wait passes, budget is exhausted: transitions to FALLIDO/PROCESSING_TIMEOUT."""
        # Expired 20s ago on attempt 3 (max_attempts = 3)
        diag = self._create_procesando_diagnosis(attempt_count=3, expired_seconds_ago=20)

        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action"], "TIMED_OUT")
            self.assertEqual(actions[0]["reason"], "budget_exhausted")

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "FALLIDO")
            self.assertEqual(diag_rec.reason_code, "PROCESSING_TIMEOUT")
            self.assertEqual(diag_rec.failure_code, "PROCESSING_TIMEOUT")

            # Emits single DiagnosisFinished v1 event
            outbox = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).scalar_one()
            self.assertEqual(outbox.event_type, "DiagnosisFinished")
            self.assertEqual(outbox.envelope["payload"]["final_status"], "FALLIDO")
            val_ok, val_err = validate_diagnosis_finished_v1(outbox.envelope)
            self.assertTrue(val_ok, f"Finished validation error: {val_err}")

    def test_deadline_reached_transitions_to_fallido(self):
        """When processing_deadline_at is reached even on attempt 1, transitions to FALLIDO/PROCESSING_TIMEOUT."""
        # Deadline was reached 5 seconds ago
        diag = self._create_procesando_diagnosis(attempt_count=1, expired_seconds_ago=10, deadline_in_seconds=-5)

        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]["action"], "TIMED_OUT")
            self.assertEqual(actions[0]["reason"], "deadline_reached")

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "FALLIDO")
            self.assertEqual(diag_rec.reason_code, "PROCESSING_TIMEOUT")

    def test_deadline_still_applies_after_recovery_signal(self):
        diag = self._create_procesando_diagnosis()
        with self.Session() as session:
            self.assertEqual(recover_expired_leases(session, self.policy)[0]["action"], "SIGNAL_EMITTED")
            row = session.get(Diagnosis, diag.id)
            row.processing_deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        with self.Session() as session:
            self.assertEqual(recover_expired_leases(session, self.policy)[0]["action"], "TIMED_OUT")
            self.assertEqual(recover_expired_leases(session, self.policy), [])
            events = session.scalars(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).all()
            self.assertEqual([e.event_type for e in events].count("DiagnosisFinished"), 1)

    def test_deadline_does_not_wait_for_retry_backoff(self):
        self._create_procesando_diagnosis(expired_seconds_ago=1, deadline_in_seconds=-1)
        with self.Session() as session:
            self.assertEqual(recover_expired_leases(session, self.policy)[0]["action"], "TIMED_OUT")

    def test_single_signal_per_generation_idempotent_recovery(self):
        """Repeated passes of recover_expired_leases emit only ONE signal for the expired generation."""
        diag = self._create_procesando_diagnosis(attempt_count=1, expired_seconds_ago=10)

        # 1st pass: emits signal
        with self.Session() as session:
            actions1 = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions1), 1)

        # 2nd pass: signal was already emitted for this generation (recovery_signaled_at >= lease_expires_at)
        with self.Session() as session:
            actions2 = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions2), 0)

        with self.Session() as session:
            outbox_recs = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).all()
            self.assertEqual(len(outbox_recs), 1)

    def test_pendiente_without_first_claim_is_never_recovered_or_timed_out(self):
        """PENDIENTE diagnoses without active lease have no deadline and are ignored by recuperador."""
        now = datetime.now(timezone.utc)
        diag_id = uuid.uuid4()
        with self.Session() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=uuid.uuid4(),
                status="PENDIENTE",
                object_key=f"diagnoses/{diag_id}/original.jpg",
                image_sha256="fake_sha256",
                image_content_type="image/jpeg",
                image_size_bytes=1024,
                attempt_count=0,
                lease_token=None,
                lease_expires_at=None,
                processing_deadline_at=None,
            )
            session.add(diag)
            session.commit()

        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 0)

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag_id)).scalar_one()
            self.assertEqual(diag_rec.status, "PENDIENTE")

    def test_race_between_result_and_recuperador(self):
        """If recuperador times out diagnosis, a concurrent result is discarded as late; exactly 1 Finished exists."""
        diag = self._create_procesando_diagnosis(attempt_count=3, expired_seconds_ago=20)
        lease_token = diag.lease_token

        # 1. Recuperador runs and times out diagnosis to FALLIDO
        with self.Session() as session:
            actions = recover_expired_leases(session, policy=self.policy)
            self.assertEqual(len(actions), 1)

        # 2. Worker result arrives with the same lease_token
        consumer = DiagnosisAnalyzedConsumer(db_session_factory=self.Session)
        channel = MockAMQPChannel()
        evt = {
            "event_id": str(uuid.uuid4()),
            "event_type": "DiagnosisAnalyzed",
            "schema_version": 1,
            "occurred_at": format_utc_iso(datetime.now(timezone.utc)),
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag.id),
                "lease_token": str(lease_token),
                "outcome": "PREDICTION",
                "crop_code": "POTATO",
                "class_code": "POTATO_EARLY_BLIGHT",
                "raw_score": 0.95,
                "model_id": "synth-model-v1",
                "model_version": "0.1.0-synth",
                "dataset_version": "ds-synth-2026.1",
                "inference_ms": 45,
            },
        }

        res = consumer.process_message(channel, 100, json.dumps(evt).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [100])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            # Remains FALLIDO, not overwritten to COMPLETADO
            self.assertEqual(diag_rec.status, "FALLIDO")
            # Result was discarded with audit
            audit = session.execute(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "LATE_RESULT_DISCARDED")).scalar_one()
            self.assertIsNotNone(audit)
            # Exactly 1 Finished outbox event exists
            finished_outbox = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).scalars().all()
            self.assertEqual(len(finished_outbox), 1)
            self.assertEqual(finished_outbox[0].event_type, "DiagnosisFinished")
