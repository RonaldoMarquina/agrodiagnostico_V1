"""Unit tests for Diagnosis domain models, constraints, and relationships."""
import datetime
import unittest
import uuid
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    Crop,
    Problem,
    Recommendation,
    Diagnosis,
    IdempotencyKey,
    ImageUploadIntent,
    DiagnosisFeedback,
    DiagnosisAuditLog,
)


class TestDiagnosisDomainModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use SQLite in-memory engine to verify schema mapping and relationships
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

    def test_tables_created(self):
        expected_tables = {
            "crops",
            "problems",
            "recommendations",
            "diagnoses",
            "idempotency_keys",
            "image_upload_intents",
            "diagnosis_feedback",
            "diagnosis_audit_logs",
        }
        self.assertTrue(expected_tables.issubset(set(Base.metadata.tables.keys())))

    def test_crop_and_problem_relationship(self):
        session = self.Session()
        crop = Crop(code="POTATO", name="Papa", description="Cultivo de papa", active=True)
        problem = Problem(
            code="POTATO_HEALTHY",
            crop_code="POTATO",
            name="Papa sana",
            type="HEALTHY",
            model_supported=False,
            active=True,
        )
        crop.problems.append(problem)
        session.add(crop)
        session.commit()

        # Query back
        loaded = session.query(Crop).filter_by(code="POTATO").one()
        self.assertEqual(len(loaded.problems), 1)
        self.assertEqual(loaded.problems[0].code, "POTATO_HEALTHY")
        self.assertEqual(loaded.problems[0].type, "HEALTHY")
        session.close()

    def test_recommendation_model_and_json_fields(self):
        session = self.Session()
        crop = session.query(Crop).filter_by(code="POTATO").first()
        if not crop:
            crop = Crop(code="POTATO", name="Papa")
            session.add(crop)
            session.commit()

        problem = session.query(Problem).filter_by(code="POTATO_HEALTHY").first()
        if not problem:
            problem = Problem(
                code="POTATO_HEALTHY",
                crop_code="POTATO",
                name="Papa sana",
                type="HEALTHY",
            )
            session.add(problem)
            session.commit()

        rec_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)
        rec = Recommendation(
            id=rec_id,
            problem_code="POTATO_HEALTHY",
            version=1,
            title="Manejo preventivo para cultivo sano",
            summary="Buenas prácticas agrícolas para mantener el cultivo libre de patógenos.",
            cultural_practices=["Rotación de cultivos", "Riego tecnificado"],
            biological_control=["Monitoreo de fauna benéfica"],
            preventive_measures=["Uso de semilla certificada"],
            source_refs=["Manual CIP 2024"],
            review_reference="REV-2026-001",
            reviewed_by="Ing. Agrónomo Senior",
            reviewed_at=now,
            active=True,
        )
        session.add(rec)
        session.commit()

        loaded_rec = session.query(Recommendation).filter_by(id=rec_id).one()
        self.assertEqual(loaded_rec.version, 1)
        self.assertEqual(loaded_rec.cultural_practices, ["Rotación de cultivos", "Riego tecnificado"])
        self.assertEqual(loaded_rec.problem.name, "Papa sana")
        session.close()

    def test_diagnosis_and_feedback_and_idempotency_relations(self):
        session = self.Session()
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()

        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PENDIENTE",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            image_width=800,
            image_height=600,
        )
        session.add(diag)
        session.commit()

        # Idempotency key
        idem = IdempotencyKey(
            owner_id=owner_id,
            scope="diagnosis_create",
            key="test-key-123",
            fingerprint="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            diagnosis_id=diag_id,
            expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
        )
        session.add(idem)
        session.commit()

        # Feedback
        fb = DiagnosisFeedback(
            diagnosis_id=diag_id,
            owner_id=owner_id,
            useful=True,
            comment="Diagnóstico muy claro",
        )
        session.add(fb)
        session.commit()

        # Query diagnosis with relations
        loaded_diag = session.query(Diagnosis).filter_by(id=diag_id).one()
        self.assertEqual(loaded_diag.feedback.useful, True)
        self.assertEqual(loaded_diag.feedback.comment, "Diagnóstico muy claro")
        self.assertEqual(len(loaded_diag.idempotency_keys), 1)
        self.assertEqual(loaded_diag.idempotency_keys[0].key, "test-key-123")
        session.close()

    def test_upload_intent_and_audit_log(self):
        session = self.Session()
        intent_diag_id = uuid.uuid4()
        intent = ImageUploadIntent(
            diagnosis_id=intent_diag_id,
            object_key=f"diagnoses/{intent_diag_id}/original.png",
            owner_id=uuid.uuid4(),
        )
        session.add(intent)

        audit = DiagnosisAuditLog(
            actor_id=uuid.uuid4(),
            action="create_crop",
            target_type="crop",
            target_id="POTATO",
            correlation_id=uuid.uuid4(),
            details={"description": "Admin created crop"},
        )
        session.add(audit)
        session.commit()

        loaded_intent = session.query(ImageUploadIntent).filter_by(diagnosis_id=intent_diag_id).one()
        self.assertIn("original.png", loaded_intent.object_key)

        loaded_audit = session.query(DiagnosisAuditLog).filter_by(action="create_crop").one()
        self.assertEqual(loaded_audit.target_type, "crop")
        self.assertEqual(loaded_audit.details["description"], "Admin created crop")
        session.close()


if __name__ == "__main__":
    unittest.main()
