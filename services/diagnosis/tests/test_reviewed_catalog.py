"""Unit and integration tests for reviewed catalog guidance and CATALOG_UNAVAILABLE invariants.

Verifies Task 7.5:
- Orientation content comes from reviewed sources with human review metadata.
- Zero invented chemical dosages or unapproved treatments.
- Missing recommendation maintains CATALOG_UNAVAILABLE.
- Missing human review metadata (review_reference, reviewed_by, reviewed_at) produces CATALOG_UNAVAILABLE.
- Seed idempotency and version continuity.
"""
from datetime import datetime, timezone
import json
import re
import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.policy import (
    activate_publication_policy,
    import_publication_policy,
)
from app.catalog_seed import REVIEWED_RECOMMENDATIONS, seed_reviewed_recommendations
from app.consumer import DiagnosisAnalyzedConsumer
from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
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


class TestReviewedCatalogGuidance(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()
        self.consumer = DiagnosisAnalyzedConsumer(db_session_factory=self.Session)

        # Seed crops
        crop_potato = Crop(code="POTATO", name="Papa", active=True)
        crop_maize = Crop(code="MAIZE", name="Maíz", active=True)
        self.session.add_all([crop_potato, crop_maize])

        # Seed candidate problems
        problems = [
            Problem(code="POTATO_HEALTHY", crop_code="POTATO", name="Papa sana", type="HEALTHY", model_supported=False),
            Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO", name="Tizón temprano", type="DISEASE", model_supported=False),
            Problem(code="POTATO_LATE_BLIGHT", crop_code="POTATO", name="Tizón tardío", type="DISEASE", model_supported=False),
            Problem(code="MAIZE_HEALTHY", crop_code="MAIZE", name="Maíz sano", type="HEALTHY", model_supported=False),
            Problem(code="MAIZE_COMMON_RUST", crop_code="MAIZE", name="Roya común", type="DISEASE", model_supported=False),
            Problem(code="MAIZE_LEAF_BLIGHT", crop_code="MAIZE", name="Tizón foliar", type="DISEASE", model_supported=False),
            Problem(code="MAIZE_GRAY_LEAF_SPOT", crop_code="MAIZE", name="Mancha gris", type="DISEASE", model_supported=False),
        ]
        self.session.add_all(problems)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_no_unverified_seed_is_published(self):
        self.assertEqual(REVIEWED_RECOMMENDATIONS, [])
        self.assertEqual(seed_reviewed_recommendations(self.session), [])
        self.assertEqual(self.session.execute(select(Recommendation)).scalars().all(), [])

    def test_no_chemical_dosages_or_unapproved_treatments(self):
        """Verify recommendations contain NO arbitrary chemical dosages (e.g. ml/ha, kg/ha, ppm, g/L)."""
        dosage_regex = re.compile(r"\b(\d+(\.\d+)?\s*(ml|l|g|kg|ppm|cc)\s*(/|\s+por\s+)(ha|litro|planta|mochila))\b", re.IGNORECASE)

        for rec_dict in REVIEWED_RECOMMENDATIONS:
            all_text = " ".join([
                rec_dict["title"],
                rec_dict["summary"],
                " ".join(rec_dict["cultural_practices"]),
                " ".join(rec_dict["biological_control"]),
                " ".join(rec_dict["preventive_measures"]),
            ])
            matches = dosage_regex.findall(all_text)
            self.assertEqual(matches, [], f"Prohibited dosage detected in {rec_dict['problem_code']}: {matches}")

    def test_all_recommendations_have_verified_metadata(self):
        """Every reviewed recommendation must have source_refs, review_reference, reviewed_by, and reviewed_at."""
        for rec_dict in REVIEWED_RECOMMENDATIONS:
            self.assertTrue(len(rec_dict["source_refs"]) >= 1)
            self.assertTrue(len(rec_dict["review_reference"].strip()) > 0)
            self.assertTrue(len(rec_dict["reviewed_by"].strip()) > 0)
            self.assertIsInstance(rec_dict["reviewed_at"], datetime)

    def test_seed_reviewed_recommendations_idempotent(self):
        seeded_first = seed_reviewed_recommendations(self.session)
        self.assertEqual(len(seeded_first), len(REVIEWED_RECOMMENDATIONS))

        # Re-running seed must not create duplicate versions
        seeded_second = seed_reviewed_recommendations(self.session)
        self.assertEqual(len(seeded_second), len(REVIEWED_RECOMMENDATIONS))

        total_in_db = self.session.execute(select(Recommendation)).scalars().all()
        self.assertEqual(len(total_in_db), len(REVIEWED_RECOMMENDATIONS))

    def test_unreviewed_recommendation_causes_catalog_unavailable(self):
        """A recommendation missing review_reference or reviewed_by fails policy and causes CATALOG_UNAVAILABLE."""
        policy_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        policy_payload = {
            "schema_version": 1,
            "policy_id": str(policy_id),
            "policy_version": "1.0.0",
            "target_model": {
                "model_id": "test-model",
                "model_version": "1.0.0",
                "dataset_version": "1.0.0",
                "bundle_digest": "c" * 64,
            },
            "approved_classes": [
                {
                    "class_code": "POTATO_EARLY_BLIGHT",
                    "crop_code": "POTATO",
                    "min_confidence_threshold": 0.80,
                    "calibration_params": {"slope": 3.0, "intercept": 0.0},
                }
            ],
            "unsupported_classes": [],
            "catalog_requirements": {
                "require_reviewed_catalog": True,
            },
            "governance": {
                "g0_protocol_version": "1.0.0",
                "g2_approval_reference": "REF-1",
                "approved_by": "Expert",
                "approved_at": format_utc_iso(now),
            },
            "audit": {"imported_by": "qa", "imported_at": format_utc_iso(now)},
        }
        import_publication_policy(self.session, "admin", "Import", policy_payload, apply=True)
        activate_publication_policy(self.session, "admin", "Activate", policy_id, apply=True)

        # Insert unreviewed recommendation (missing review_reference)
        unreviewed_rec = Recommendation(
            id=uuid.uuid4(),
            problem_code="POTATO_EARLY_BLIGHT",
            version=1,
            title="Unreviewed Title",
            summary="Unreviewed Summary",
            cultural_practices=[],
            biological_control=[],
            preventive_measures=[],
            source_refs=[],
            review_reference="",  # BLANK -> NOT REVIEWED
            reviewed_by="",
            reviewed_at=now,
            active=True,
        )
        self.session.add(unreviewed_rec)
        self.session.commit()

        # Send Analyzed message
        diag_id = uuid.uuid4()
        token = uuid.uuid4()
        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="PROCESANDO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="fake_sha256",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            lease_token=token,
            lease_expires_at=datetime.fromtimestamp(now.timestamp() + 300, tz=timezone.utc),
        )
        self.session.add(diag)
        self.session.commit()

        analyzed_envelope = {
            "event_id": str(uuid.uuid4()),
            "event_type": "DiagnosisAnalyzed",
            "schema_version": 1,
            "occurred_at": format_utc_iso(now),
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "lease_token": str(token),
                "outcome": "PREDICTION",
                "crop_code": "POTATO",
                "class_code": "POTATO_EARLY_BLIGHT",
                "raw_score": 0.95,
                "model_id": "test-model",
                "model_version": "1.0.0",
                "dataset_version": "1.0.0",
                "inference_ms": 30,
            },
        }

        channel = MockAMQPChannel()
        self.assertTrue(
            self.consumer.process_message(
                channel, 1, json.dumps(analyzed_envelope).encode("utf-8"), "diagnosis.analyzed.v1"
            )
        )

        with self.Session() as s:
            diag_db = s.get(Diagnosis, diag_id)
            self.assertEqual(diag_db.status, "NO_CONCLUYENTE")
            self.assertEqual(diag_db.reason_code, "CATALOG_UNAVAILABLE")
            self.assertIsNone(diag_db.recommendation_id)
