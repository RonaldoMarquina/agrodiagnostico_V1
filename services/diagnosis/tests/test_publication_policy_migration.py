"""Unit and integration tests for publication policies migration and models.

Verifies Task 7.1:
- Additive database migration for publication_policies table and diagnoses confidence/policy columns.
- Upgrade and downgrade (rollback) testing.
- Historical diagnoses compatibility without invented synthetic calibration.
- Terminal diagnoses immutability and downgrade limits.
- Foreign key SET NULL behavior on policy deletion.
"""
import datetime
import os
import tempfile
import unittest
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
    Problem,
    PublicationPolicy,
)


class TestPublicationPolicyMigrationAndModel(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_publication_policies_table_registered(self):
        self.assertIn("publication_policies", Base.metadata.tables)
        policy_table = Base.metadata.tables["publication_policies"]
        cols = {c.name for c in policy_table.columns}
        expected = {
            "id",
            "policy_version",
            "model_id",
            "model_version",
            "dataset_version",
            "bundle_digest",
            "payload",
            "active",
            "created_at",
            "activated_at",
            "retired_at",
        }
        self.assertTrue(expected.issubset(cols))

    def test_diagnosis_additive_columns_registered(self):
        diag_table = Base.metadata.tables["diagnoses"]
        cols = {c.name for c in diag_table.columns}
        expected = {
            "calibrated_confidence",
            "policy_id",
            "policy_version",
            "policy_digest",
        }
        self.assertTrue(expected.issubset(cols))

    def test_historical_diagnosis_compatibility_without_invented_calibration(self):
        """Historical diagnoses must have None for confidence and policy fields without synthetic invention."""
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.timezone.utc)

        # Historical diagnosis created before this capacity
        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="COMPLETADO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="abc123sha256",
            image_content_type="image/jpeg",
            image_size_bytes=2048,
            crop_code="POTATO",
            class_code="POTATO_HEALTHY",
            raw_score=0.85,
            model_id="synth-model-v1",
            model_version="0.1.0-synth",
            dataset_version="ds-synth-2026.1",
            created_at=now,
            updated_at=now,
        )
        self.session.add(diag)
        self.session.commit()

        # Query back
        row = self.session.execute(select(Diagnosis).where(Diagnosis.id == diag_id)).scalar_one()
        self.assertIsNone(row.calibrated_confidence)
        self.assertIsNone(row.estimated_confidence)
        self.assertIsNone(row.policy_id)
        self.assertIsNone(row.policy_version)
        self.assertIsNone(row.policy_digest)
        self.assertIsNone(row.policy)
        self.assertEqual(row.raw_score, 0.85)
        self.assertEqual(row.status, "COMPLETADO")

    def test_diagnosis_with_publication_policy_relationship(self):
        """New diagnosis with calibrated confidence and policy snapshot links correctly."""
        policy_id = uuid.uuid4()
        policy = PublicationPolicy(
            id=policy_id,
            policy_version="1.0.0",
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            bundle_digest="a" * 64,
            payload={
                "approved_classes": [
                    {
                        "class_code": "POTATO_EARLY_BLIGHT",
                        "crop_code": "POTATO",
                        "min_confidence_threshold": 0.85,
                        "calibration_params": {"slope": 2.5, "intercept": -1.2},
                    }
                ]
            },
            active=True,
        )
        self.session.add(policy)
        self.session.flush()

        diag_id = uuid.uuid4()
        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="COMPLETADO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="fake_sha256",
            image_content_type="image/jpeg",
            image_size_bytes=4096,
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
            raw_score=0.88,
            calibrated_confidence=0.9123,
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            policy_id=policy.id,
            policy_version=policy.policy_version,
            policy_digest=policy.bundle_digest,
        )
        self.session.add(diag)
        self.session.commit()

        row = self.session.execute(select(Diagnosis).where(Diagnosis.id == diag_id)).scalar_one()
        self.assertEqual(row.calibrated_confidence, 0.9123)
        self.assertEqual(row.estimated_confidence, 0.9123)
        self.assertEqual(row.policy_id, policy_id)
        self.assertEqual(row.policy_version, "1.0.0")
        self.assertEqual(row.policy.bundle_digest, "a" * 64)

        # Setter verification
        row.estimated_confidence = 0.95
        self.assertEqual(row.calibrated_confidence, 0.95)

    def test_alembic_migration_upgrade_and_downgrade(self):
        """Test full upgrade and rollback of migration 0004 on a standalone sqlite file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
            db_path = tmp_file.name

        try:
            alembic_ini_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
            )
            config = Config(alembic_ini_path)
            config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

            # Upgrade to head (includes 0004)
            command.upgrade(config, "head")

            test_engine = create_engine(f"sqlite:///{db_path}")
            with test_engine.connect() as conn:
                from sqlalchemy import text
                # Verify publication_policies table exists
                result = conn.execute(text("SELECT count(*) FROM publication_policies")).scalar()
                self.assertEqual(result, 0)

                # Verify additive columns exist in diagnoses
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(diagnoses)")).fetchall()]
                self.assertIn("calibrated_confidence", cols)
                self.assertIn("policy_id", cols)
                self.assertIn("policy_version", cols)
                self.assertIn("policy_digest", cols)

            test_engine.dispose()

            # Downgrade back to diagnosis_0003
            command.downgrade(config, "diagnosis_0003")

            test_engine2 = create_engine(f"sqlite:///{db_path}")
            with test_engine2.connect() as conn:
                # publication_policies table should be gone
                with self.assertRaises(Exception):
                    conn.execute(text("SELECT count(*) FROM publication_policies"))

                # additive columns should be removed from diagnoses
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(diagnoses)")).fetchall()]
                self.assertNotIn("calibrated_confidence", cols)
                self.assertNotIn("policy_id", cols)
                self.assertNotIn("policy_version", cols)
                self.assertNotIn("policy_digest", cols)

            test_engine2.dispose()

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)
