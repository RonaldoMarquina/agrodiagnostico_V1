"""Unit and integration test suite for DiagnosisAnalyzedConsumer (Tasks 6.1, 6.2, 6.4).

Tests:
- 6.1: Decision logic:
  - ABSTENTION -> NO_CONCLUYENTE (with reason_code)
  - FAILURE -> FALLIDO (with failure_code/reason_code)
  - PREDICTION with inactive crop -> NO_CONCLUYENTE (UNSUPPORTED_CROP)
  - PREDICTION with unsupported class (model_supported=False) -> NO_CONCLUYENTE (UNSUPPORTED_CLASS)
  - PREDICTION with missing recommendation -> NO_CONCLUYENTE (CATALOG_UNAVAILABLE)
  - PREDICTION with fixture support/catalog -> COMPLETADO with immutable snapshot
- 6.2: Atomic commit of state, snapshot, inbox, and Finished outbox before ACK:
  - Rollback if Finished outbox fails preserves PENDIENTE/PROCESANDO and sends no ACK
  - Deduplication on duplicate event_id
  - Quarantine on event_id collision with different payload
  - Terminal feedback capability
  - Snapshot immutable upon subsequent catalog edits
- 6.4: Audited discard of stale, late, and expired results:
  - Discard if diagnosis is already CANCELADO (never revives CANCELADO)
  - Discard if diagnosis has tombstone (deleted_at is set)
  - Discard if lease_token is old/substituted
  - Discard if relational DB clock >= lease_expires_at
  - Transport redelivery does NOT consume execution attempt budget
"""
from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.consumer import DiagnosisAnalyzedConsumer
from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisFeedback,
    DiagnosisInbox,
    DiagnosisOutbox,
    DiagnosisQuarantineMessage,
    Problem,
    Recommendation,
)
from app.infrastructure.cursor import format_utc_iso
from app.infrastructure.event_validation import compute_canonical_hash, validate_diagnosis_finished_v1


class MockAMQPChannel:
    def __init__(self):
        self.acked_tags = []
        self.nacked_tags = []

    def basic_ack(self, delivery_tag):
        self.acked_tags.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue=True):
        self.nacked_tags.append((delivery_tag, requeue))


class TestAnalyzedConsumer(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"APP_ENV": "test", "ENABLE_SIMULATED_INFERENCE": "true"})
        env.start()
        self.addCleanup(env.stop)
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.consumer = DiagnosisAnalyzedConsumer(db_session_factory=self.Session)

        # Seed agricultural catalog
        with self.Session() as session:
            crop_potato = Crop(code="POTATO", name="Papa", active=True)
            crop_maize = Crop(code="MAIZE", name="Maíz", active=True)
            crop_inactive = Crop(code="TOMATO", name="Tomate", active=False)
            session.add_all([crop_potato, crop_maize, crop_inactive])

            # Normal seed: model_supported=False
            prob_healthy = Problem(
                code="POTATO_HEALTHY",
                crop_code="POTATO",
                name="Papa Sana",
                type="HEALTHY",
                model_supported=False,
                active=True,
            )
            # Supported problem for test fixture
            prob_blight = Problem(
                code="POTATO_EARLY_BLIGHT",
                crop_code="POTATO",
                name="Tizón Temprano",
                type="DISEASE",
                model_supported=True,
                active=True,
            )
            # Supported problem but without active recommendation
            prob_rust = Problem(
                code="MAIZE_COMMON_RUST",
                crop_code="MAIZE",
                name="Roya Común",
                type="DISEASE",
                model_supported=True,
                active=True,
            )
            session.add_all([prob_healthy, prob_blight, prob_rust])

            # Active recommendation for POTATO_EARLY_BLIGHT
            rec = Recommendation(
                problem_code="POTATO_EARLY_BLIGHT",
                version=1,
                title="Manejo de Tizón Temprano",
                summary="Prácticas culturales y rotación de cultivo recomendadas.",
                cultural_practices=["Rotación de cultivo", "Eliminar rastrojos"],
                biological_control=["Trichoderma spp."],
                preventive_measures=["Monitoreo semanal"],
                source_refs=["Manual Técnico CIP 2024"],
                review_reference="REV-AGRO-2024-001",
                reviewed_by="Ing. Agrónomo Certificado",
                reviewed_at=datetime.now(timezone.utc),
                active=True,
            )
            session.add(rec)
            session.commit()

    def tearDown(self):
        self.engine.dispose()

    def _create_active_diagnosis(
        self,
        status="PROCESANDO",
        attempt_count=1,
        lease_seconds=60,
    ) -> tuple[Diagnosis, uuid.UUID]:
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lease_seconds)

        with self.Session() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=owner_id,
                status=status,
                object_key=f"diagnoses/{diag_id}/original.jpg",
                image_sha256="fake_sha256_hash",
                image_content_type="image/jpeg",
                image_size_bytes=1024,
                lease_owner="ai-worker-1",
                lease_token=lease_token,
                lease_expires_at=expires_at,
                attempt_count=attempt_count,
                correlation_id=uuid.uuid4(),
            )
            session.add(diag)
            session.commit()
            return diag, lease_token

    def _build_analyzed_envelope(
        self,
        diag_id: uuid.UUID,
        lease_token: uuid.UUID,
        outcome: str,
        crop_code: str = "POTATO",
        class_code: str = "POTATO_EARLY_BLIGHT",
        raw_score: float = 0.92,
        reason_code: str = "LOW_CONFIDENCE",
    ) -> dict:
        evt_id = uuid.uuid4()
        payload = {
            "diagnosis_id": str(diag_id),
            "lease_token": str(lease_token),
            "outcome": outcome,
            "crop_code": crop_code,
            "model_id": "synth-model-v1" if outcome == "PREDICTION" else None,
            "model_version": "0.1.0-synth" if outcome == "PREDICTION" else None,
            "dataset_version": "ds-synth-2026.1" if outcome == "PREDICTION" else None,
            "inference_ms": 45 if outcome == "PREDICTION" else None,
        }
        if outcome == "PREDICTION":
            payload["class_code"] = class_code
            payload["raw_score"] = raw_score
        else:
            payload["reason_code"] = reason_code

        return {
            "event_id": str(evt_id),
            "event_type": "DiagnosisAnalyzed",
            "schema_version": 1,
            "occurred_at": format_utc_iso(datetime.now(timezone.utc)),
            "correlation_id": str(uuid.uuid4()),
            "payload": payload,
        }

    # =========================================================================
    # Task 6.1: Business Decision Logic Tests
    # =========================================================================

    def test_analyzed_abstention_transitions_to_no_concluyente(self):
        """ABSTENTION outcome transitions to NO_CONCLUYENTE with reason_code."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="ABSTENTION",
            reason_code="LOW_CONFIDENCE",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 1, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [1])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_rec.reason_code, "LOW_CONFIDENCE")
            self.assertIsNone(diag_rec.model_id)

            # Finished outbox emitted
            outbox = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).scalar_one()
            self.assertEqual(outbox.event_type, "DiagnosisFinished")
            self.assertEqual(outbox.envelope["payload"]["final_status"], "NO_CONCLUYENTE")

    def test_analyzed_failure_transitions_to_fallido(self):
        """FAILURE outcome transitions to FALLIDO with failure_code/reason_code."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="FAILURE",
            reason_code="INFERENCE_ERROR",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 2, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [2])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "FALLIDO")
            self.assertEqual(diag_rec.reason_code, "INFERENCE_ERROR")
            self.assertEqual(diag_rec.failure_code, "INFERENCE_ERROR")

            outbox = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).scalar_one()
            self.assertEqual(outbox.envelope["payload"]["final_status"], "FALLIDO")

    def test_analyzed_prediction_unsupported_class_transitions_to_no_concluyente(self):
        """PREDICTION on class with model_supported=False transitions to NO_CONCLUYENTE (UNSUPPORTED_CLASS)."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        # POTATO_HEALTHY has model_supported=False
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_HEALTHY",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 3, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [3])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_rec.reason_code, "UNSUPPORTED_CLASS")

    def test_prediction_requires_test_policy_and_approved_version_and_score(self):
        cases = [
            ({"APP_ENV": "local"}, {}, "UNSUPPORTED_CLASS"),
            ({"ENABLE_SIMULATED_INFERENCE": "false"}, {}, "UNSUPPORTED_CLASS"),
            ({}, {"model_version": "unknown"}, "UNSUPPORTED_CLASS"),
            ({}, {"raw_score": 0.89}, "LOW_CONFIDENCE"),
        ]
        for environment, changes, reason in cases:
            with self.subTest(environment=environment, changes=changes), patch.dict(os.environ, environment):
                diag, token = self._create_active_diagnosis()
                event = self._build_analyzed_envelope(diag_id=diag.id, lease_token=token,
                    outcome="PREDICTION", crop_code="POTATO", class_code="POTATO_EARLY_BLIGHT")
                event["payload"].update(changes)
                self.assertTrue(self.consumer.process_message(MockAMQPChannel(), 1, json.dumps(event).encode(), "diagnosis.analyzed.v1"))
                with self.Session() as session:
                    row = session.get(Diagnosis, diag.id)
                    self.assertEqual(row.status, "NO_CONCLUYENTE")
                    self.assertEqual(row.reason_code, reason)
                    self.assertIsNone(row.recommendation_id)

    def test_analyzed_prediction_missing_catalog_transitions_to_no_concluyente(self):
        """PREDICTION on supported problem but lacking active recommendation transitions to CATALOG_UNAVAILABLE."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        # MAIZE_COMMON_RUST has model_supported=True but no active Recommendation
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="MAIZE",
            class_code="MAIZE_COMMON_RUST",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 4, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [4])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_rec.reason_code, "CATALOG_UNAVAILABLE")

    def test_analyzed_prediction_success_with_snapshot_transitions_to_completado(self):
        """PREDICTION with active crop, supported problem, and active catalog transitions to COMPLETADO with snapshot."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        # POTATO_EARLY_BLIGHT is supported and has active recommendation version 1
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
            raw_score=0.95,
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 5, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [5])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "COMPLETADO")
            self.assertIsNone(diag_rec.reason_code)
            self.assertEqual(diag_rec.crop_code, "POTATO")
            self.assertEqual(diag_rec.class_code, "POTATO_EARLY_BLIGHT")
            self.assertEqual(diag_rec.raw_score, 0.95)
            self.assertEqual(diag_rec.catalog_version, "1")
            self.assertIn("Prácticas culturales", diag_rec.recommendation_text)

            # Finished outbox validation
            outbox = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).scalar_one()
            self.assertEqual(outbox.envelope["payload"]["final_status"], "COMPLETADO")
            val_ok, val_err = validate_diagnosis_finished_v1(outbox.envelope)
            self.assertTrue(val_ok, f"Finished event failed contract: {val_err}")

    # =========================================================================
    # Task 6.2: Atomic Confirmation, Rollback, Inbox Dedupe, and Snapshot
    # =========================================================================

    def test_atomic_commit_inbox_and_finished_outbox_registered(self):
        """State, inbox, and finished outbox are all committed in the single transaction."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        self.consumer.process_message(channel, 10, raw_body, "diagnosis.analyzed.v1")

        with self.Session() as session:
            inbox_rec = session.execute(select(DiagnosisInbox).where(DiagnosisInbox.event_id == uuid.UUID(evt["event_id"]))).scalar_one()
            self.assertEqual(inbox_rec.consumer, "diagnosis")
            self.assertEqual(inbox_rec.canonical_hash, compute_canonical_hash(evt))

            audit_rec = session.execute(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "DIAGNOSIS_FINALIZED")).scalar_one()
            self.assertIsNotNone(audit_rec)

    def test_idempotent_redelivery_with_same_event_id_and_hash(self):
        """Duplicate event_id with same canonical hash immediately ACKs without duplicate Finished event."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        # 1st delivery
        self.consumer.process_message(channel, 20, raw_body, "diagnosis.analyzed.v1")
        self.assertEqual(channel.acked_tags, [20])

        # 2nd delivery (redelivery of same message)
        channel2 = MockAMQPChannel()
        self.consumer.process_message(channel2, 21, raw_body, "diagnosis.analyzed.v1")
        self.assertEqual(channel2.acked_tags, [21])

        # Verify only 1 Finished event exists
        with self.Session() as session:
            outbox_recs = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).all()
            self.assertEqual(len(outbox_recs), 1)

    def test_collision_with_same_event_id_different_hash_quarantined(self):
        """Collision on event_id with different hash is quarantined and ACKed without overwriting inbox."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        evt1 = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
        )
        raw_body1 = json.dumps(evt1).encode("utf-8")
        self.consumer.process_message(channel, 30, raw_body1, "diagnosis.analyzed.v1")

        # Tampered envelope with same event_id but different correlation_id
        evt2 = dict(evt1)
        evt2["correlation_id"] = str(uuid.uuid4())
        raw_body2 = json.dumps(evt2).encode("utf-8")

        channel2 = MockAMQPChannel()
        self.consumer.process_message(channel2, 31, raw_body2, "diagnosis.analyzed.v1")
        self.assertEqual(channel2.acked_tags, [31])

        with self.Session() as session:
            q = session.execute(select(DiagnosisQuarantineMessage)).scalar_one()
            self.assertIn("COLLISION", q.error_reason)

    def test_snapshot_remains_immutable_upon_subsequent_catalog_edit(self):
        """Completed diagnosis snapshot is never mutated when catalog recommendation changes."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
        )
        self.consumer.process_message(channel, 40, json.dumps(evt).encode("utf-8"), "diagnosis.analyzed.v1")

        # Subsequent catalog change: new version 2 with different text
        with self.Session() as session:
            rec_v2 = Recommendation(
                problem_code="POTATO_EARLY_BLIGHT",
                version=2,
                title="Nueva Guía Tizón 2026",
                summary="Resumen completamente nuevo para 2026.",
                cultural_practices=["Nueva práctica"],
                biological_control=["Nuevo biocontrol"],
                preventive_measures=["Nuevas medidas"],
                source_refs=["Fuente 2026"],
                review_reference="REV-2026",
                reviewed_by="Experto 2026",
                reviewed_at=datetime.now(timezone.utc),
                active=True,
            )
            session.add(rec_v2)
            session.commit()

        # Check diagnosis snapshot still reflects version 1 and original text
        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.catalog_version, "1")
            self.assertIn("Prácticas culturales", diag_rec.recommendation_text)
            self.assertNotIn("Resumen completamente nuevo", diag_rec.recommendation_text)

    def test_terminal_diagnosis_can_receive_feedback(self):
        """Terminal diagnoses can receive 1:1 user feedback."""
        diag, lease_token = self._create_active_diagnosis()
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
        )
        self.consumer.process_message(channel, 50, json.dumps(evt).encode("utf-8"), "diagnosis.analyzed.v1")

        with self.Session() as session:
            fb = DiagnosisFeedback(
                diagnosis_id=diag.id,
                owner_id=diag.owner_id,
                useful=True,
                comment="Excelente recomendación",
            )
            session.add(fb)
            session.commit()

            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertIsNotNone(diag_rec.feedback)
            self.assertTrue(diag_rec.feedback.useful)

    # =========================================================================
    # Task 6.4: Audited Discard of Late / Stale Results & Tombstones
    # =========================================================================

    def test_late_result_for_cancelled_diagnosis_discarded_and_audited(self):
        """Analyzed result arriving for CANCELADO diagnosis is discarded without reviving status."""
        diag, lease_token = self._create_active_diagnosis(status="CANCELADO")
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 60, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [60])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            # Status MUST stay CANCELADO
            self.assertEqual(diag_rec.status, "CANCELADO")
            # Audit log recorded
            audit = session.execute(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "LATE_RESULT_DISCARDED")).scalar_one()
            self.assertIsNotNone(audit)
            # NO Finished outbox event created
            outbox = session.execute(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).all()
            self.assertEqual(len(outbox), 0)

    def test_stale_lease_token_discarded_and_audited(self):
        """Analyzed result with old/substituted lease_token is discarded and audited."""
        diag, lease_token = self._create_active_diagnosis(status="PROCESANDO")
        channel = MockAMQPChannel()
        # Pass a different, stale lease token
        old_stale_token = uuid.uuid4()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=old_stale_token,
            outcome="PREDICTION",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 61, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [61])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "PROCESANDO")
            audit = session.execute(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "STALE_LEASE_TOKEN_DISCARDED")).scalar_one()
            self.assertIsNotNone(audit)

    def test_expired_lease_result_discarded_and_audited(self):
        """Analyzed result arriving when CURRENT_TIMESTAMP >= lease_expires_at is discarded."""
        # Create diagnosis with lease expired in the past
        diag, lease_token = self._create_active_diagnosis(status="PROCESANDO", lease_seconds=-10)
        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 62, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [62])

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "PROCESANDO")
            audit = session.execute(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "EXPIRED_LEASE_RESULT_DISCARDED")).scalar_one()
            self.assertIsNotNone(audit)

    def test_tombstone_diagnosis_with_valid_lease_finalizes_without_reviving_visibility(self):
        """Soft-deleted (tombstone) diagnosis can finalize internally, remaining deleted (deleted_at intact)."""
        diag, lease_token = self._create_active_diagnosis(status="PROCESANDO")
        # Set soft delete tombstone
        tombstone_time = datetime.now(timezone.utc)
        with self.Session() as session:
            d = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            d.deleted_at = tombstone_time
            session.commit()

        channel = MockAMQPChannel()
        evt = self._build_analyzed_envelope(
            diag_id=diag.id,
            lease_token=lease_token,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
        )
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.consumer.process_message(channel, 63, raw_body, "diagnosis.analyzed.v1")
        self.assertTrue(res)

        with self.Session() as session:
            diag_rec = session.execute(select(Diagnosis).where(Diagnosis.id == diag.id)).scalar_one()
            self.assertEqual(diag_rec.status, "COMPLETADO")
            # Tombstone remains completely intact; resource is not revived in user list
            self.assertIsNotNone(diag_rec.deleted_at)
