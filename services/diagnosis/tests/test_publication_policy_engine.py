"""Integration and unit tests for publication policy decision engine and concurrency serialization.

Verifies Task 7.3 and Task 7.4:
- Invariant: Exact tuple matching (model_id, model_version, dataset_version).
- Reason code precedence:
    1. UNSUPPORTED_CROP
    2. UNSUPPORTED_CLASS (version mismatch, unapproved class, unsupported problem)
    3. LOW_CONFIDENCE (calibrated confidence below inclusive threshold)
    4. CATALOG_UNAVAILABLE (missing active recommendation or unreviewed metadata)
- Inclusive frontier check: score producing calibrated_confidence == min_threshold is accepted.
- Concurrency and serialization:
    - Retired policy fails closed (UNSUPPORTED_CLASS).
    - Terminal states remain strictly immutable even after policy changes.
    - Snapshot persistence: calibrated_confidence, policy_id, policy_version, policy_digest stored in DB.
"""
from datetime import datetime, timezone
import json
import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.policy import (
    activate_publication_policy,
    import_publication_policy,
    retire_publication_policy,
)
from app.consumer import DiagnosisAnalyzedConsumer
from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisOutbox,
    Problem,
    PublicationPolicy,
    Recommendation,
)
from app.infrastructure.cursor import format_utc_iso


class MockAMQPChannel:
    def __init__(self):
        self.acked_tags = []
        self.nacked_tags = []

    def basic_ack(self, delivery_tag, multiple=False):
        self.acked_tags.append(delivery_tag)

    def basic_nack(self, delivery_tag, multiple=False, requeue=True):
        self.nacked_tags.append((delivery_tag, requeue))


class TestPublicationPolicyEngineAndSerialization(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.consumer = DiagnosisAnalyzedConsumer(db_session_factory=self.Session)
        self.session = self.Session()

        # Seed catalog
        now = datetime.now(timezone.utc)
        crop_potato = Crop(code="POTATO", name="Papa", active=True)
        crop_maize = Crop(code="MAIZE", name="Maíz", active=True)
        self.session.add_all([crop_potato, crop_maize])

        # Candidate problems
        prob_eb = Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO", name="Tizón temprano", type="DISEASE", model_supported=False, active=True)
        prob_lb = Problem(code="POTATO_LATE_BLIGHT", crop_code="POTATO", name="Tizón tardío", type="DISEASE", model_supported=False, active=True)
        prob_rust = Problem(code="MAIZE_COMMON_RUST", crop_code="MAIZE", name="Roya común", type="DISEASE", model_supported=False, active=True)
        self.session.add_all([prob_eb, prob_lb, prob_rust])

        # Active reviewed recommendation for POTATO_EARLY_BLIGHT
        rec_eb = Recommendation(
            problem_code="POTATO_EARLY_BLIGHT",
            version=1,
            title="Manejo integrado de tizón temprano",
            summary="Monitoreo constante, rotación de cultivos y ventilación.",
            cultural_practices=["Rotación de cultivo", "Eliminar follaje senescente"],
            biological_control=["Bacillus subtilis"],
            preventive_measures=["Evitar exceso de humedad"],
            source_refs=["Manual Técnico CIP 2024"],
            review_reference="REV-AGRO-CIP-2024-001",
            reviewed_by="Ing. Agrónomo Colegiado",
            reviewed_at=now,
            active=True,
        )
        self.session.add(rec_eb)
        self.session.commit()

        # Import and activate publication policy
        self.policy_id = uuid.UUID("44444444-4444-4444-8444-444444444444")
        self.policy_digest = "b" * 64
        self.policy_payload = {
            "schema_version": 1,
            "policy_id": str(self.policy_id),
            "policy_version": "1.0.0",
            "target_model": {
                "model_id": "agrodiagnostico-mobilenetv3-cpu",
                "model_version": "1.0.0",
                "dataset_version": "2.0.0",
                "bundle_digest": self.policy_digest,
            },
            "approved_classes": [
                {
                    "class_code": "POTATO_EARLY_BLIGHT",
                    "crop_code": "POTATO",
                    "min_confidence_threshold": 0.8500,
                    # z = 2.0 * raw_score; for s=0.8673 -> z=1.7346 -> sigmoid(1.7346)=0.8500
                    "calibration_params": {"slope": 2.0, "intercept": 0.0},
                },
                {
                    "class_code": "MAIZE_COMMON_RUST",
                    "crop_code": "MAIZE",
                    "min_confidence_threshold": 0.8000,
                    "calibration_params": {"slope": 2.0, "intercept": 0.0},
                },
            ],
            "unsupported_classes": [
                {"class_code": "POTATO_LATE_BLIGHT", "reason": "Insufficient external validation"}
            ],
            "catalog_requirements": {
                "require_reviewed_catalog": True,
            },
            "governance": {
                "g0_protocol_version": "1.0.0",
                "g2_approval_reference": "REF-G2-TEST-001",
                "approved_by": "Dr. Fitopatólogo",
                "approved_at": format_utc_iso(now),
            },
            "audit": {
                "imported_by": "qa-engineer",
                "imported_at": format_utc_iso(now),
            },
        }

        import_publication_policy(self.session, "ops", "Initial import", self.policy_payload, apply=True)
        activate_publication_policy(self.session, "ops", "Activate for tests", self.policy_id, apply=True)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _create_processing_diagnosis(self) -> tuple[Diagnosis, uuid.UUID]:
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + 300, tz=timezone.utc)

        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PROCESANDO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc123sha256",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            lease_owner="ai-worker-1",
            lease_token=lease_token,
            lease_expires_at=expires_at,
            attempt_count=1,
            correlation_id=uuid.uuid4(),
        )
        self.session.add(diag)
        self.session.commit()
        return diag, lease_token

    def _build_analyzed_message(
        self,
        diag_id: uuid.UUID,
        lease_token: uuid.UUID,
        outcome: str = "PREDICTION",
        crop_code: str = "POTATO",
        class_code: str = "POTATO_EARLY_BLIGHT",
        raw_score: float = 0.90,
        model_id: str = "agrodiagnostico-mobilenetv3-cpu",
        model_version: str = "1.0.0",
        dataset_version: str = "2.0.0",
    ) -> bytes:
        payload = {
            "diagnosis_id": str(diag_id),
            "lease_token": str(lease_token),
            "outcome": outcome,
            "crop_code": crop_code,
            "class_code": class_code,
            "raw_score": raw_score,
            "model_id": model_id,
            "model_version": model_version,
            "dataset_version": dataset_version,
            "inference_ms": 50,
        }
        envelope = {
            "event_id": str(uuid.uuid4()),
            "event_type": "DiagnosisAnalyzed",
            "schema_version": 1,
            "occurred_at": format_utc_iso(datetime.now(timezone.utc)),
            "correlation_id": str(uuid.uuid4()),
            "payload": payload,
        }
        return json.dumps(envelope).encode("utf-8")

    def test_unknown_model_version_rejected_as_unsupported_class(self):
        diag, token = self._create_processing_diagnosis()
        msg = self._build_analyzed_message(
            diag.id, token, model_version="2.0.0-unauthorized"
        )
        channel = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(channel, 1, msg, "diagnosis.analyzed.v1"))

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_db.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_db.reason_code, "UNSUPPORTED_CLASS")
            self.assertIsNone(diag_db.recommendation_id)

    def test_unapproved_class_rejected_as_unsupported_class(self):
        # POTATO_LATE_BLIGHT was marked unsupported in policy
        diag, token = self._create_processing_diagnosis()
        msg = self._build_analyzed_message(
            diag.id, token, class_code="POTATO_LATE_BLIGHT"
        )
        channel = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(channel, 2, msg, "diagnosis.analyzed.v1"))

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_db.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_db.reason_code, "UNSUPPORTED_CLASS")

    def test_frontier_score_exact_match_accepted(self):
        """Inclusive frontier test: calibrated confidence == 0.8500 exactly meets threshold 0.8500."""
        diag, token = self._create_processing_diagnosis()
        # s=0.8673 -> z = 2.0 * 0.8673 = 1.7346 -> sigmoid = 0.8500
        msg = self._build_analyzed_message(
            diag.id, token, raw_score=0.8673
        )
        channel = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(channel, 3, msg, "diagnosis.analyzed.v1"))

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_db.status, "COMPLETADO")
            self.assertIsNone(diag_db.reason_code)
            self.assertEqual(diag_db.raw_score, 0.8673)
            self.assertEqual(diag_db.calibrated_confidence, 0.8500)
            self.assertEqual(diag_db.estimated_confidence, 0.8500)
            self.assertEqual(diag_db.policy_id, self.policy_id)
            self.assertEqual(diag_db.policy_version, "1.0.0")
            self.assertEqual(diag_db.policy_digest, self.policy_digest)
            self.assertIsNotNone(diag_db.recommendation_id)
            self.assertIn("Monitoreo constante", diag_db.recommendation_text)

    def test_frontier_score_just_below_threshold_rejected_as_low_confidence(self):
        """Score producing calibrated confidence 0.8481 < 0.8500 must abstain with LOW_CONFIDENCE."""
        diag, token = self._create_processing_diagnosis()
        # s=0.8600 -> z = 1.72 -> sigmoid = 0.8481 < 0.8500
        msg = self._build_analyzed_message(
            diag.id, token, raw_score=0.8600
        )
        channel = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(channel, 4, msg, "diagnosis.analyzed.v1"))

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_db.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_db.reason_code, "LOW_CONFIDENCE")
            self.assertEqual(diag_db.calibrated_confidence, 0.8481)
            self.assertEqual(diag_db.policy_id, self.policy_id)
            self.assertIsNone(diag_db.recommendation_id)

    def test_missing_catalog_recommendation_rejected_as_catalog_unavailable(self):
        """MAIZE_COMMON_RUST is in approved policy with high score but has no Recommendation in DB."""
        diag, token = self._create_processing_diagnosis()
        msg = self._build_analyzed_message(
            diag.id, token, crop_code="MAIZE", class_code="MAIZE_COMMON_RUST", raw_score=0.95
        )
        channel = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(channel, 5, msg, "diagnosis.analyzed.v1"))

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_db.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_db.reason_code, "CATALOG_UNAVAILABLE")
            self.assertIsNone(diag_db.recommendation_id)

    def test_retired_policy_fails_closed(self):
        """Retiring policy causes subsequent Analyzed messages to transition to UNSUPPORTED_CLASS."""
        retire_publication_policy(self.session, "ops", "Test retirement", self.policy_id, apply=True)

        diag, token = self._create_processing_diagnosis()
        msg = self._build_analyzed_message(
            diag.id, token, raw_score=0.95
        )
        channel = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(channel, 6, msg, "diagnosis.analyzed.v1"))

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_db.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_db.reason_code, "UNSUPPORTED_CLASS")

    def test_terminal_diagnoses_strictly_immutable_after_policy_changes(self):
        """A diagnosis that reached COMPLETADO retains original policy snapshot and status even if policy is retired."""
        diag, token = self._create_processing_diagnosis()
        msg = self._build_analyzed_message(diag.id, token, raw_score=0.92)
        channel = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(channel, 7, msg, "diagnosis.analyzed.v1"))

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_db.status, "COMPLETADO")
            orig_policy_id = diag_db.policy_id
            orig_confidence = diag_db.calibrated_confidence

        # Now retire the policy
        retire_publication_policy(self.session, "ops", "Emergency rollback", self.policy_id, apply=True)

        # Refresh diagnosis: must remain COMPLETADO with original snapshot
        with self.Session() as s:
            diag_after = s.get(Diagnosis, diag.id)
            self.assertEqual(diag_after.status, "COMPLETADO")
            self.assertEqual(diag_after.policy_id, orig_policy_id)
            self.assertEqual(diag_after.calibrated_confidence, orig_confidence)
