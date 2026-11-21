"""Real PostgreSQL serialization of DiagnosisFinished and policy promotion.

Run only against a disposable database with TEST_POLICY_PG_URL set.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.application.policy import (activate_publication_policy,
                                    import_publication_policy, retire_publication_policy)
from app.consumer import DiagnosisAnalyzedConsumer
from app.domain.models import (Base, Crop, Diagnosis, DiagnosisAuditLog,
                               DiagnosisInbox, DiagnosisOutbox, Problem,
                               PublicationPolicy, Recommendation)
from app.infrastructure.cursor import format_utc_iso
from app.infrastructure.publication_policy import evaluate_publication


class AckChannel:
    def __init__(self):
        self.acked = []

    def basic_ack(self, delivery_tag, multiple=False):
        self.acked.append(delivery_tag)

    def basic_nack(self, delivery_tag, multiple=False, requeue=True):
        raise AssertionError("El consumidor no debe reencolar")


@unittest.skipUnless(os.environ.get("TEST_POLICY_PG_URL"), "Requiere PostgreSQL aislado")
class TestPolicyConcurrencyPostgres(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["TEST_POLICY_PG_URL"], pool_size=5)
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.first_id, self.second_id = uuid.uuid4(), uuid.uuid4()
        with self.Session() as db:
            now = datetime.now(timezone.utc)
            db.add(Crop(code="POTATO", name="Papa", active=True))
            db.add(Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO",
                           name="Fixture tizón", type="DISEASE", model_supported=False))
            db.add(Recommendation(
                problem_code="POTATO_EARLY_BLIGHT", version=1, title="Fixture revisado",
                summary="Contenido exclusivo de prueba", cultural_practices=[],
                biological_control=[], preventive_measures=[], source_refs=["fixture"],
                review_reference="FIXTURE-REVIEW", reviewed_by="fixture", reviewed_at=now,
                active=True))
            db.commit()
            for pid, version in ((self.first_id, "1.0.0"), (self.second_id, "2.0.0")):
                import_publication_policy(db, "test", "ensayo aislado", self._policy(pid, version), apply=True)
            activate_publication_policy(db, "test", "versión inicial", self.first_id, apply=True)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    @staticmethod
    def _policy(pid, version):
        return {
            "schema_version": 1, "policy_id": str(pid), "policy_version": version,
            "target_model": {"model_id": "fixture-model", "model_version": "1.0.0",
                             "dataset_version": "1.0.0-fixture", "bundle_digest": "a" * 64},
            "approved_classes": [{"class_code": "POTATO_EARLY_BLIGHT",
                                  "crop_code": "POTATO", "min_confidence_threshold": 0.5,
                                  "calibration_params": {"slope": 1.0, "intercept": 0.0}}],
            "unsupported_classes": [], "catalog_requirements": {"require_reviewed_catalog": True},
            "governance": {"g0_protocol_version": "1.0.0", "g2_approval_reference": "FIXTURE-G2",
                           "approved_by": "fixture", "approved_at": "2026-01-01T00:00:00Z"},
            "audit": {"imported_by": "fixture", "imported_at": "2026-01-01T00:00:00Z"},
        }

    def test_finalization_serializes_with_activation_and_keeps_snapshot(self):
        self._run_race(retire=False)

    def test_finalization_serializes_with_retirement_and_keeps_snapshot(self):
        self._run_race(retire=True)

    def _run_race(self, *, retire: bool):
        diagnosis_id, lease_token = uuid.uuid4(), uuid.uuid4()
        now = datetime.now(timezone.utc)
        with self.Session() as db:
            db.add(Diagnosis(
                id=diagnosis_id, owner_id=uuid.uuid4(), status="PROCESANDO",
                object_key=f"fixture/{diagnosis_id}.jpg", image_sha256="b" * 64,
                image_content_type="image/jpeg", image_size_bytes=100,
                lease_owner="fixture-worker", lease_token=lease_token,
                lease_expires_at=now + timedelta(minutes=5), attempt_count=1,
                correlation_id=uuid.uuid4(), created_at=now, updated_at=now))
            db.commit()
        body = json.dumps({
            "event_id": str(uuid.uuid4()), "event_type": "DiagnosisAnalyzed",
            "schema_version": 1, "occurred_at": format_utc_iso(now),
            "correlation_id": str(uuid.uuid4()),
            "payload": {"diagnosis_id": str(diagnosis_id), "lease_token": str(lease_token),
                        "outcome": "PREDICTION", "crop_code": "POTATO",
                        "class_code": "POTATO_EARLY_BLIGHT", "raw_score": 0.9,
                        "model_id": "fixture-model", "model_version": "1.0.0",
                        "dataset_version": "1.0.0-fixture", "inference_ms": 10},
        }).encode()
        decision_made, release_finalization, switch_started = (threading.Event() for _ in range(3))

        def gated_evaluation(*args, **kwargs):
            decision = evaluate_publication(*args, **kwargs)
            decision_made.set()
            if not release_finalization.wait(10):
                raise TimeoutError("Finalización retenida demasiado tiempo")
            return decision

        def finalize():
            channel = AckChannel()
            result = DiagnosisAnalyzedConsumer(self.Session).process_message(
                channel, 1, body, "diagnosis.analyzed.v1")
            return result, channel.acked

        def switch():
            switch_started.set()
            with self.Session() as db:
                if retire:
                    return retire_publication_policy(
                        db, "test", "retiro concurrente", self.first_id, apply=True)
                return activate_publication_policy(
                    db, "test", "cambio concurrente", self.second_id, apply=True)

        try:
            with patch("app.consumer.evaluate_publication", side_effect=gated_evaluation):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(finalize)
                    self.assertTrue(decision_made.wait(10))
                    second = pool.submit(switch)
                    self.assertTrue(switch_started.wait(10))
                    # An exclusive switch cannot commit while Finished owns the
                    # shared transaction lock, including catalog snapshot/outbox.
                    deadline = time.monotonic() + 5
                    waiting = 0
                    while time.monotonic() < deadline:
                        with self.engine.connect() as observer:
                            waiting = observer.scalar(text(
                                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"))
                        if waiting:
                            break
                        time.sleep(0.02)
                    self.assertGreater(waiting, 0, "El cambio nunca esperó el lock de Finished")
                    self.assertFalse(second.done())
                    release_finalization.set()
                    self.assertEqual(first.result(timeout=10), (True, [1]))
                    self.assertEqual(second.result(timeout=10)["mode"], "APPLIED")
        finally:
            release_finalization.set()

        with self.Session() as db:
            diagnosis = db.get(Diagnosis, diagnosis_id)
            self.assertEqual(diagnosis.status, "COMPLETADO")
            self.assertEqual(diagnosis.policy_id, self.first_id)
            self.assertEqual(diagnosis.policy_version, "1.0.0")
            self.assertEqual(diagnosis.policy_digest, "a" * 64)
            self.assertIsNotNone(diagnosis.calibrated_confidence)
            self.assertEqual(diagnosis.catalog_version, "1")
            self.assertEqual(diagnosis.recommendation_text, "Contenido exclusivo de prueba")
            active = db.scalar(select(PublicationPolicy).where(
                PublicationPolicy.active.is_(True)))
            self.assertIsNone(active) if retire else self.assertEqual(active.id, self.second_id)
            self.assertEqual(db.query(DiagnosisInbox).count(), 1)
            self.assertEqual(db.query(DiagnosisOutbox).count(), 1)
            self.assertEqual(db.query(DiagnosisAuditLog).filter_by(action="DIAGNOSIS_FINALIZED").count(), 1)
