"""Pruebas de integración del worker con adaptador de modelo real, arranque y resiliencia (Tareas 6.2 y 6.3)."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict
import unittest
from unittest.mock import MagicMock, patch
import uuid

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    InferenceInbox,
    InferenceJob,
    InferenceOutbox,
    InferenceResult,
)
from app.infrastructure.auth import InternalTokenSigner, generate_worker_keypair
from app.inference_adapter import RealModelInferenceAdapter
from app.worker import InferenceWorker, create_configured_inference_adapter
try:
    from tests.test_model_adapter import _create_minimal_png
except ImportError:
    from services.ai_inference.tests.test_model_adapter import _create_minimal_png


class MockAMQPChannel:
    def __init__(self):
        self.acked_tags = []
        self.nacked_tags = []

    def basic_ack(self, delivery_tag: Any) -> None:
        self.acked_tags.append(delivery_tag)

    def basic_nack(self, delivery_tag: Any, requeue: bool = False) -> None:
        self.nacked_tags.append((delivery_tag, requeue))


class TestWorkerRealMode(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        priv_pem, pub_pem = generate_worker_keypair()
        self.signer = InternalTokenSigner(
            private_key_pem=priv_pem,
            kid="test-key",
            instance_id="worker-real-1",
        )

        self.mock_http = MagicMock()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp_dir.name)

        # Crear bundle de modelo real válido
        weights_data = {
            "weights": [[0.05 * ((i * 3 + j) % 7 - 3) for j in range(7)] for i in range(64)],
            "bias": [3.0, 0.2, 0.15, 0.05, 0.1, 0.08, 0.02],
        }
        self.weights_file = self.base_dir / "model_weights.safetensors"
        weights_bytes = json.dumps(weights_data).encode("utf-8")
        self.weights_file.write_bytes(weights_bytes)
        weights_sha = hashlib.sha256(weights_bytes).hexdigest()

        self.bundle_data = {
            "schema_version": 1,
            "bundle_id": str(uuid.uuid4()),
            "model_id": "agrodiagnostico-mobilenetv3-cpu",
            "model_version": "1.0.0",
            "dataset_version": "2.0.0",
            "architecture": "mobilenet_v3_small",
            "weights": {
                "filename": "model_weights.safetensors",
                "sha256": weights_sha,
                "format": "safetensors",
                "size_bytes": len(weights_bytes),
            },
            "manifest_checksums": {
                "train_manifest_sha256": "a" * 64,
                "val_manifest_sha256": "b" * 64,
                "test_manifest_sha256": "c" * 64,
            },
            "class_map": {
                "0": {"class_code": "POTATO_HEALTHY", "crop_code": "POTATO"},
                "1": {"class_code": "POTATO_EARLY_BLIGHT", "crop_code": "POTATO"},
                "2": {"class_code": "POTATO_LATE_BLIGHT", "crop_code": "POTATO"},
                "3": {"class_code": "MAIZE_HEALTHY", "crop_code": "MAIZE"},
                "4": {"class_code": "MAIZE_COMMON_RUST", "crop_code": "MAIZE"},
                "5": {"class_code": "MAIZE_LEAF_BLIGHT", "crop_code": "MAIZE"},
                "6": {"class_code": "MAIZE_GRAY_LEAF_SPOT", "crop_code": "MAIZE"},
            },
            "preprocessing": {
                "input_size": [224, 224],
                "channels": 3,
                "color_space": "RGB",
                "mean": [0.485, 0.456, 0.406],
                "std": [0.229, 0.224, 0.225],
            },
            "rejection_components": {
                "min_confidence_threshold": 0.20,
                "crop_detection_threshold": 0.50,
                "min_dimension": 200,
                "max_dimension": 6000,
            },
            "calibration": {
                "method": "PLATT_SCALING",
                "parameters_per_class": {},
            },
            "runtime_environment": {
                "python_version": "3.12",
                "framework": "pytorch",
                "framework_version": "2.2.0",
                "target_device": "cpu",
            },
            "governance": {
                "g0_protocol_version": "1.0.0",
                "g2_approval_id": "G2-APPROVED-TEST",
                "approved_by": "Asesor Docente",
                "approved_at": "2026-10-15T12:00:00Z",
            },
        }
        self.bundle_file = self.base_dir / "model_bundle.v1.json"
        self.bundle_file.write_text(json.dumps(self.bundle_data, indent=2), encoding="utf-8")

        self.real_adapter = RealModelInferenceAdapter.from_bundle_file(self.bundle_file)
        self.worker = InferenceWorker(
            db_session_factory=self.Session,
            diagnosis_internal_url="http://diagnosis:8000",
            token_signer=self.signer,
            http_client=self.mock_http,
            inference_adapter=self.real_adapter,
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _create_sample_event(self, diag_id: uuid.UUID) -> Dict[str, Any]:
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "DiagnosisRequested",
            "schema_version": 2,
            "occurred_at": "2026-10-08T10:00:00Z",
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "owner_id": str(uuid.uuid4()),
                "object_key": f"diagnoses/{diag_id}/original.jpg",
            },
        }

    def test_real_mode_rejects_unpinned_json_fixture(self):
        with patch.dict(os.environ, {"INFERENCE_MODE": "real", "APP_ENV": "local",
                                  "MODEL_BUNDLE_PATH": str(self.bundle_file), "MODEL_BUNDLE_SHA256": ""}):
            with self.assertRaisesRegex(RuntimeError, "MODEL_BUNDLE_SHA256"):
                create_configured_inference_adapter()

    def test_worker_passes_identified_crop_to_pilot_adapter(self):
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(lease_token)})
        self.mock_http.get.return_value = httpx.Response(200, content=_create_minimal_png(250, 250))
        pilot = MagicMock()
        pilot.requires_identified_crop = True
        pilot.run_inference.return_value = {
            "outcome": "ABSTENTION", "crop_code": None, "class_code": None,
            "raw_score": None, "reason_code": "UNSUPPORTED_CROP",
            "model_id": None, "model_version": None, "dataset_version": None,
            "inference_ms": None,
        }
        self.worker.inference_adapter = pilot
        event = self._create_sample_event(diag_id)
        event["payload"]["identified_crop"] = "POTATO"
        channel = MockAMQPChannel()
        self.assertTrue(self.worker.process_message(
            channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2"))
        self.assertEqual(channel.acked_tags, [1])
        self.assertEqual(pilot.run_inference.call_args.kwargs["identified_crop"], "POTATO")

    def test_pilot_timeout_before_commit_requeues_without_result(self):
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(lease_token)})
        self.mock_http.get.return_value = httpx.Response(200, content=_create_minimal_png(250, 250))
        pilot = MagicMock()
        pilot.requires_identified_crop = True
        pilot.run_inference.side_effect = TimeoutError("synthetic timeout")
        self.worker.inference_adapter = pilot
        event = self._create_sample_event(diag_id)
        event["payload"]["identified_crop"] = "POTATO"
        channel = MockAMQPChannel()
        self.assertFalse(self.worker.process_message(
            channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2"))
        self.assertEqual(channel.acked_tags, [])
        self.assertEqual(channel.nacked_tags, [(1, True)])
        with self.Session() as session:
            self.assertEqual(session.query(InferenceResult).filter_by(diagnosis_id=diag_id).count(), 0)
            self.assertEqual(session.query(InferenceOutbox).filter_by(diagnosis_id=diag_id).count(), 0)
            self.assertEqual(session.query(InferenceInbox).filter_by(event_id=uuid.UUID(event["event_id"])).count(), 0)

    def test_heartbeat_continues_while_cpu_adapter_runs(self):
        engine = create_engine(f"sqlite:///{self.base_dir / 'heartbeat.sqlite'}")
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine)
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        renewals = []

        def post(url, **kwargs):
            if url.endswith("/lease/renew"):
                renewals.append(url)
                return httpx.Response(200, json={"lease_token": str(lease_token)})
            return httpx.Response(200, json={"lease_token": str(lease_token)})

        self.mock_http.post.side_effect = post
        self.mock_http.get.return_value = httpx.Response(200, content=_create_minimal_png(250, 250))
        pilot = MagicMock()
        pilot.requires_identified_crop = True

        def compute(**kwargs):
            time.sleep(.25)
            return {"outcome": "ABSTENTION", "crop_code": "POTATO", "class_code": None,
                    "raw_score": None, "reason_code": "LOW_CONFIDENCE",
                    "model_id": "pilot", "model_version": "0.1.0-pilot",
                    "dataset_version": "1.2.0-pv-color", "inference_ms": 250}

        pilot.run_inference.side_effect = compute
        worker = InferenceWorker(
            session_factory, "http://diagnosis:8000", self.signer,
            http_client=self.mock_http, local_lease_seconds=2,
            heartbeat_seconds=.05, inference_adapter=pilot)
        event = self._create_sample_event(diag_id)
        event["payload"]["identified_crop"] = "POTATO"
        channel = MockAMQPChannel()
        self.assertTrue(worker.process_message(
            channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2"))
        self.assertGreaterEqual(len(renewals), 1)
        with session_factory() as session:
            self.assertEqual(session.query(InferenceResult).filter_by(diagnosis_id=diag_id).count(), 1)
        engine.dispose()

    def test_fixture_mode_requires_explicit_test_guard(self):
        with patch.dict(os.environ, {"INFERENCE_MODE": "fixture", "APP_ENV": "local", "ENABLE_SIMULATED_INFERENCE": "true"}):
            with self.assertRaisesRegex(RuntimeError, "Fixture runtime requires"):
                create_configured_inference_adapter()

    def test_startup_mode_selection_real_mode_success(self):
        """Arranque en modo real inicializa correctamente el adaptador con el release."""
        env = {
            "INFERENCE_MODE": "fixture",
            "MODEL_BUNDLE_PATH": str(self.bundle_file),
            "APP_ENV": "test",
            "ENABLE_SIMULATED_INFERENCE": "true",
        }
        with patch.dict(os.environ, env):
            adapter = create_configured_inference_adapter()
            self.assertIsInstance(adapter, RealModelInferenceAdapter)
            self.assertEqual(adapter.model_id, "agrodiagnostico-mobilenetv3-cpu")

    def test_startup_mode_selection_real_mode_missing_bundle_fails_closed(self):
        """Arranque en modo real con bundle ausente falla inmediatamente sin simular."""
        env = {
            "INFERENCE_MODE": "fixture",
            "MODEL_BUNDLE_PATH": str(self.base_dir / "non_existent_bundle.json"),
            "APP_ENV": "test",
            "ENABLE_SIMULATED_INFERENCE": "true",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(RuntimeError) as ctx:
                create_configured_inference_adapter()
            self.assertIn("Failed to initialize real model bundle", str(ctx.exception))

    def test_startup_mode_selection_real_mode_corrupt_bundle_fails_closed(self):
        """Arranque en modo real con bundle corrupto falla inmediatamente sin simular."""
        # Corromper archivo de pesos
        self.weights_file.write_bytes(b"corrupted_bytes")
        env = {
            "INFERENCE_MODE": "fixture",
            "MODEL_BUNDLE_PATH": str(self.bundle_file),
            "APP_ENV": "test",
            "ENABLE_SIMULATED_INFERENCE": "true",
        }
        with patch.dict(os.environ, env):
            with self.assertRaises(RuntimeError) as ctx:
                create_configured_inference_adapter()
            self.assertIn("Failed to initialize real model bundle", str(ctx.exception))

    def test_process_message_with_real_model_prediction(self):
        """Flujo completo exitoso con modelo real produciendo PREDICTION."""
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        valid_png = _create_minimal_png(250, 250)

        # Mock claim e imagen
        self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(lease_token)})
        self.mock_http.get.return_value = httpx.Response(200, content=valid_png)

        event = self._create_sample_event(diag_id)
        channel = MockAMQPChannel()

        ok = self.worker.process_message(channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2")
        self.assertTrue(ok)
        self.assertEqual(channel.acked_tags, [1])

        # Comprobar resultado persistido en BD
        with self.Session() as session:
            res = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(res.outcome, "PREDICTION")
            self.assertEqual(res.crop_code, "POTATO")
            self.assertEqual(res.model_id, "agrodiagnostico-mobilenetv3-cpu")
            self.assertEqual(res.model_version, "1.0.0")
            self.assertEqual(res.dataset_version, "2.0.0")
            self.assertIsInstance(res.inference_ms, int)
            self.assertGreater(res.raw_score, 0.0)

            # Comprobar outbox
            outbox = session.execute(select(InferenceOutbox).where(InferenceOutbox.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(outbox.envelope["payload"]["outcome"], "PREDICTION")
            self.assertEqual(outbox.envelope["payload"]["model_id"], "agrodiagnostico-mobilenetv3-cpu")

    def test_process_message_with_real_model_bad_image_abstention(self):
        """Flujo con modelo real cuando la imagen es corrupta produce ABSTENTION con BAD_IMAGE y metadatos null."""
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()

        self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(lease_token)})
        self.mock_http.get.return_value = httpx.Response(200, content=b"corrupt_image_bytes")

        event = self._create_sample_event(diag_id)
        channel = MockAMQPChannel()

        ok = self.worker.process_message(channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2")
        self.assertTrue(ok)
        self.assertEqual(channel.acked_tags, [1])

        with self.Session() as session:
            res = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(res.outcome, "ABSTENTION")
            self.assertEqual(res.reason_code, "BAD_IMAGE")
            self.assertIsNone(res.model_id)
            self.assertIsNone(res.model_version)
            self.assertIsNone(res.dataset_version)
            self.assertIsNone(res.inference_ms)

    def test_redelivery_after_commit_is_idempotent(self):
        """La reentrega de un mensaje ya procesado es confirmada sin re-ejecutar inferencia."""
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        valid_png = _create_minimal_png(250, 250)

        self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(lease_token)})
        self.mock_http.get.return_value = httpx.Response(200, content=valid_png)

        event = self._create_sample_event(diag_id)
        body = json.dumps(event).encode()
        channel = MockAMQPChannel()

        # Primera entrega
        ok1 = self.worker.process_message(channel, 1, body, "diagnosis.requested.v2")
        self.assertTrue(ok1)
        self.assertEqual(channel.acked_tags, [1])

        # Segunda entrega (redelivery)
        ok2 = self.worker.process_message(channel, 2, body, "diagnosis.requested.v2")
        self.assertTrue(ok2)
        self.assertEqual(channel.acked_tags, [1, 2])

        # Comprobar que en la base de datos sólo existe un resultado
        with self.Session() as session:
            results = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).scalars().all()
            self.assertEqual(len(results), 1)

    def test_lease_lost_during_heartbeat_aborts_commit(self):
        """Pérdida de lease durante inferencia aborta el commit y rechaza el mensaje."""
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        valid_png = _create_minimal_png(250, 250)

        self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(lease_token)})
        self.mock_http.get.return_value = httpx.Response(200, content=valid_png)

        event = self._create_sample_event(diag_id)
        channel = MockAMQPChannel()

        # Simular que el claim local es revocado/vencido justo antes del commit
        def alter_claim_during_inference(**kwargs):
            with self.Session() as session:
                job = session.scalar(select(InferenceJob).where(InferenceJob.diagnosis_id == diag_id))
                if job:
                    job.local_claim_token = uuid.uuid4()
                    session.commit()
            return self.real_adapter.run_inference(diag_id, valid_png)

        self.worker.inference_adapter.run_inference = alter_claim_during_inference

        ok = self.worker.process_message(channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2")
        self.assertFalse(ok)
        self.assertEqual(channel.acked_tags, [])
        self.assertEqual(channel.nacked_tags, [(1, True)])

        with self.Session() as session:
            results = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).scalars().all()
            self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
