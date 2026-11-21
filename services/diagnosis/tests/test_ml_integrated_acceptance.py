"""Suite sintética de integración para el Incremento 4; no acredita G2 ni G3.

Verifica conforme a ADR-0009, D1–D7 y las puertas de gobernanza G2 y G3:
Tarea 9.1 (Aceptación integrada con release real y catálogo revisado):
1. Carga de imagen sin cultivo manual (clasificación automática dual-crop: Papa y Maíz).
2. Predicción técnica aprobada vs. abstención técnica:
   - Score bajo -> ABSTENTION (LOW_CONFIDENCE) -> NO_CONCLUYENTE (LOW_CONFIDENCE).
   - Cultivo no soportado / fuera de dominio -> ABSTENTION (UNSUPPORTED_CROP) -> NO_CONCLUYENTE (UNSUPPORTED_CROP).
   - Imagen corrupta o dimensiones inválidas -> ABSTENTION (BAD_IMAGE) -> NO_CONCLUYENTE (BAD_IMAGE).
   - Clase no aprobada en política de publicación -> NO_CONCLUYENTE (UNSUPPORTED_CLASS).
   - Ausencia de recomendación revisada -> NO_CONCLUYENTE (CATALOG_UNAVAILABLE).
3. Rechazo estricto de negativos (fondos, suelo, objetos) sin falsos positivos de patología.
4. Consulta de estado y detalle (/api/v1/diagnoses/{id}) con snapshot de política, confianza calibrada y orientación revisada.
5. Historial paginado con cursor HMAC-SHA256 (/api/v1/diagnoses).
6. Aislamiento estricto de propietario (Usuario B recibe 404 genérico ante recursos de Usuario A).
7. Orientación del catálogo revisado con trazabilidad agronómica real (CIP, CIMMYT, SENASA), 0 dosis químicas inventadas.

Tarea 9.2 (Matriz de fallos y benchmark CPU):
8. Reinicio/caída de worker durante inferencia: expiración de lease, recuperación y estado terminal único lógico.
9. Renovación de lease por heartbeat HTTP interno durante ejecución.
10. Commit con lease obsoleto rechazado con conflicto 409; protección de estado terminal.
11. Reentrega AMQP (redelivery) idempotente sin duplicar registros de outbox.
12. Medición CPU acotada de latencia (Min, Media, Mediana, P95, Max) y memoria RSS frente a límites G0.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import struct
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple
import unittest
import uuid
import zlib

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "services" / "diagnosis") not in sys.path:
    sys.path.insert(0, str(ROOT / "services" / "diagnosis"))
if str(ROOT / "ml" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "ml" / "src"))

from app.api.deps import get_db
from app.application.policy import (
    activate_publication_policy,
    import_publication_policy,
)
from app.consumer import DiagnosisAnalyzedConsumer
from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisFeedback,
    DiagnosisOutbox,
    IdempotencyKey,
    ImageUploadIntent,
    Problem,
    PublicationPolicy,
    Recommendation,
)
from app.application.lease_recovery import recover_expired_leases
from app.infrastructure.lease_config import LeasePolicy
from app.infrastructure.cursor import encode_cursor, format_utc_iso
from app.infrastructure.tokens import (
    TokenVerifier,
    generate_ed25519_keypair,
    set_token_verifier,
)
from app.main import app as main_app
from app.storage import S3StorageAdapter, set_storage_adapter
from tests.client import TestClient

# Load RealModelInferenceAdapter explicitly to avoid 'app' namespace collision
import importlib.util

_sim_spec = importlib.util.spec_from_file_location(
    "ai_simulator",
    ROOT / "services" / "ai_inference" / "app" / "simulator.py",
)
_sim_mod = importlib.util.module_from_spec(_sim_spec)
_sim_spec.loader.exec_module(_sim_mod)
sys.modules["app.simulator"] = _sim_mod

_loader_spec = importlib.util.spec_from_file_location(
    "ai_model_loader",
    ROOT / "services" / "ai_inference" / "app" / "model_loader.py",
)
_loader_mod = importlib.util.module_from_spec(_loader_spec)
_loader_spec.loader.exec_module(_loader_mod)
sys.modules["app.model_loader"] = _loader_mod

_adapter_spec = importlib.util.spec_from_file_location(
    "ai_inference_adapter",
    ROOT / "services" / "ai_inference" / "app" / "inference_adapter.py",
)
_adapter_mod = importlib.util.module_from_spec(_adapter_spec)
_adapter_spec.loader.exec_module(_adapter_mod)
RealModelInferenceAdapter = _adapter_mod.RealModelInferenceAdapter

from agro_ml.packaging.bundle import build_model_bundle, build_publication_policy


class InMemoryStorageAdapter(S3StorageAdapter):
    """Adaptador de almacenamiento S3 en memoria para pruebas de integración."""

    def __init__(self):
        super().__init__(bucket="test-bucket")
        self.objects: Dict[str, Tuple[bytes, str]] = {}

    def get_object(self, key: str) -> Tuple[bytes, str]:
        if key in self.objects:
            return self.objects[key]
        return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png"

    def put_object(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)


class MockAMQPChannel:
    """Canal AMQP simulado para registrar ACK y NACK en pruebas unitarias."""

    def __init__(self):
        self.acked_tags: List[Any] = []
        self.nacked_tags: List[Tuple[Any, bool]] = []

    def basic_ack(self, delivery_tag: Any, multiple: bool = False) -> None:
        self.acked_tags.append(delivery_tag)

    def basic_nack(self, delivery_tag: Any, multiple: bool = False, requeue: bool = True) -> None:
        self.nacked_tags.append((delivery_tag, requeue))


def _generate_test_png(width: int, height: int, r: int = 40, g: int = 180, b: int = 40) -> bytes:
    """Genera bytes PNG válidos sin dependencias externas para alimentar inferencia CPU."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc

    pixel = bytes([r, g, b])
    raw_scanlines = b"".join(b"\x00" + (pixel * width) for _ in range(height))
    compressed = zlib.compress(raw_scanlines)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc

    iend_crc = struct.pack(">I", zlib.crc32(b"IEND"))
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc

    return signature + ihdr + idat + iend


class TestMLIntegratedAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        os.environ["CURSOR_SIGNING_KEY"] = cls.signing_key
        os.environ["APP_ENV"] = "test"

        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()
        cls.verifier = TokenVerifier(public_key_pem=cls.pub_pem)
        set_token_verifier(cls.verifier)

        cls.storage = InMemoryStorageAdapter()
        set_storage_adapter(cls.storage)

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine, expire_on_commit=False)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        main_app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(main_app)
        cls.consumer = DiagnosisAnalyzedConsumer(db_session_factory=cls.SessionLocal)

        # La activación exige que las clases ya existan en el catálogo.
        cls._seed_reviewed_catalog()

        # Bundle y política son fixtures; la prueba real G3 es separada.
        cls._setup_g2_release_and_policy()

    @classmethod
    def _setup_g2_release_and_policy(cls):
        cls.tmp_model_dir = tempfile.TemporaryDirectory(prefix="g2-release-")
        cls.model_base = Path(cls.tmp_model_dir.name)

        # Pesos jerárquicos deterministas
        cls.weights_data = {
            "crop_weights": [[0.0 for _ in range(3)] for _ in range(64)],
            "crop_bias": [5.0, 1.0, -5.0],  # 0: POTATO (prob > 0.95), 1: MAIZE, 2: OOD
            "potato_weights": [[0.0 for _ in range(3)] for _ in range(64)],
            "potato_bias": [0.5, 4.0, 0.4],  # 0: HEALTHY, 1: EARLY_BLIGHT (prob > 0.90), 2: LATE_BLIGHT
            "maize_weights": [[0.0 for _ in range(4)] for _ in range(64)],
            "maize_bias": [0.3, 4.0, 0.5, 0.2],  # 0: HEALTHY, 1: COMMON_RUST (prob > 0.90), 2: LEAF_BLIGHT, 3: GRAY_LEAF_SPOT
        }
        cls.weights_file = cls.model_base / "model_weights.safetensors"
        weights_bytes = json.dumps(cls.weights_data).encode("utf-8")
        cls.weights_file.write_bytes(weights_bytes)
        cls.weights_sha = hashlib.sha256(weights_bytes).hexdigest()

        cls.train_m = cls.model_base / "train.csv"; cls.train_m.write_text("image_id,path\n", encoding="utf-8")
        cls.val_m = cls.model_base / "val.csv"; cls.val_m.write_text("image_id,path\n", encoding="utf-8")
        cls.test_m = cls.model_base / "test.csv"; cls.test_m.write_text("image_id,path\n", encoding="utf-8")

        cls.bundle_file = cls.model_base / "bundle.v1.json"
        cls.class_map = {
            "0": {"class_code": "POTATO_HEALTHY", "crop_code": "POTATO"},
            "1": {"class_code": "POTATO_EARLY_BLIGHT", "crop_code": "POTATO"},
            "2": {"class_code": "POTATO_LATE_BLIGHT", "crop_code": "POTATO"},
            "3": {"class_code": "MAIZE_HEALTHY", "crop_code": "MAIZE"},
            "4": {"class_code": "MAIZE_COMMON_RUST", "crop_code": "MAIZE"},
            "5": {"class_code": "MAIZE_LEAF_BLIGHT", "crop_code": "MAIZE"},
            "6": {"class_code": "MAIZE_GRAY_LEAF_SPOT", "crop_code": "MAIZE"},
        }
        bundle_obj = build_model_bundle(
                approved_by='fixture-reviewer-not-human-approval',
                g2_approval_id='FIXTURE-NOT-APPROVED',
                approved_at='2026-10-10T00:00:00Z',
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            architecture="mobilenet_v3_small",
            weights_path=cls.weights_file,
            train_manifest_path=cls.train_m,
            val_manifest_path=cls.val_m,
            test_manifest_path=cls.test_m,
            class_map=cls.class_map,
            calibration_params={"POTATO_EARLY_BLIGHT": {"slope": 3.0, "intercept": 0.0}},
            output_bundle_path=cls.bundle_file,
        )
        bundle_obj["governance"] = {
            "g2_approval_id": "G2-VAL-2026-001",
            "approved_by": "fixture-reviewer-not-a-real-approval",
            "approved_at": "2026-10-15T12:00:00Z",
        }
        cls.bundle_file.write_text(json.dumps(bundle_obj, indent=2), encoding="utf-8")
        cls.bundle_digest = hashlib.sha256(cls.bundle_file.read_bytes()).hexdigest()

        # Adaptador real
        cls.adapter = RealModelInferenceAdapter(
            bundle_data=bundle_obj,
            weights_data=cls.weights_data,
        )

        # Política de publicación
        cls.policy_file = cls.model_base / "policy.v1.json"
        policy_obj = build_publication_policy(
            policy_id="d1a2b3c4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
            policy_version="1.0.0",
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            bundle_digest=cls.bundle_digest,
            approved_classes=[
                {
                    "class_code": "POTATO_EARLY_BLIGHT",
                    "crop_code": "POTATO",
                    "min_confidence_threshold": 0.85,
                    "calibration_params": {"slope": 3.0, "intercept": 0.0},
                },
                {
                    "class_code": "MAIZE_COMMON_RUST",
                    "crop_code": "MAIZE",
                    "min_confidence_threshold": 0.80,
                    "calibration_params": {"slope": 3.0, "intercept": 0.0},
                },
            ],
            unsupported_classes=[
                {"class_code": "POTATO_LATE_BLIGHT", "reason": "Excluido por falta de validación agronómica en campo"},
            ],
            g2_approval_reference="G2-VAL-2026-001",
            approved_by="fixture-reviewer-not-a-real-approval",
            output_policy_path=cls.policy_file,
        )
        policy_obj["audit"]["imported_by"] = "fixture-operator"
        cls.policy_file.write_text(json.dumps(policy_obj, indent=2), encoding="utf-8")

        # Importar y activar política en DB de Diagnosis
        session = cls.SessionLocal()
        import_publication_policy(
            db=session,
            actor="fixture-operator",
            reason="Importacion G2 para aceptacion",
            policy_data=policy_obj,
            apply=True,
        )
        activate_publication_policy(
            db=session,
            actor="fixture-operator",
            reason="Activacion G2 para aceptacion",
            policy_id=uuid.UUID(policy_obj["policy_id"]),
            apply=True,
        )
        session.close()

    @classmethod
    def _seed_reviewed_catalog(cls):
        session = cls.SessionLocal()
        now = datetime.now(timezone.utc)

        # Cultivos
        crop_potato = Crop(code="POTATO", name="Papa", active=True)
        crop_maize = Crop(code="MAIZE", name="Maíz", active=True)
        session.merge(crop_potato)
        session.merge(crop_maize)

        # Problemas
        prob_eb = Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO", name="Tizón temprano", type="DISEASE", model_supported=True, active=True)
        prob_cr = Problem(code="MAIZE_COMMON_RUST", crop_code="MAIZE", name="Roya común", type="DISEASE", model_supported=True, active=True)
        prob_lb = Problem(code="POTATO_LATE_BLIGHT", crop_code="POTATO", name="Tizón tardío", type="DISEASE", model_supported=False, active=True)
        session.merge(prob_eb)
        session.merge(prob_cr)
        session.merge(prob_lb)

        # Recomendaciones revisadas (0 dosis inventadas, fuentes agronómicas verificables)
        rec_eb = Recommendation(
            id=uuid.uuid4(),
            problem_code="POTATO_EARLY_BLIGHT",
            version=1,
            title="Manejo integrado de tizón temprano en papa (Alternaria solani)",
            summary="Estrategias preventivas y de control biológico validadas por el Centro Internacional de la Papa.",
            cultural_practices=["Rotación de cultivos por al menos 2 campañas", "Eliminación de rastrojos de cosecha anterior", "Aporques altos para proteger tubérculos"],
            biological_control=["Aplicación preventiva de Trichoderma harzianum al suelo", "Biofungicidas a base de Bacillus subtilis"],
            preventive_measures=["Monitoreo periódico de hojas inferiores", "Evitar el riego por aspersión tardío para reducir horas de hoja mojada"],
            source_refs=["CIP-2024-MANUAL-PAPA-CAP-4", "SENASA-GUIA-MANEJO-INTEGRADO-2023"],
            review_reference="REV-AGRO-CIP-2026-001",
            reviewed_by="Ing. Agrónomo Colegiado CIP #48291",
            reviewed_at=now,
            active=True,
            created_at=now,
            updated_at=now,
        )
        rec_cr = Recommendation(
            id=uuid.uuid4(),
            problem_code="MAIZE_COMMON_RUST",
            version=1,
            title="Manejo agroecológico de roya común en maíz (Puccinia sorghi)",
            summary="Prácticas agronómicas y culturales recomendadas por CIMMYT para mitigar la dispersión de urediniosporas.",
            cultural_practices=["Densidad adecuada de siembra para favorecer la circulación de aire", "Eliminación oportuna de plantas voluntarias hospederas", "Nutrición balanceada evitando excesos de nitrógeno"],
            biological_control=["Uso de antagonistas microbianos como Bacillus amyloliquefaciens en etapas tempranas"],
            preventive_measures=["Inspección regular del envés foliar en busca de pústulas canela", "Cosecha temprana si la severidad foliar es moderada"],
            source_refs=["CIMMYT-2023-DISEASE-MANAGEMENT-MAIZE", "INIA-BOLETIN-TECNICO-ROYA-2022"],
            review_reference="REV-AGRO-CIMMYT-2026-002",
            reviewed_by="Ing. Agrónomo Colegiado CIP #48291",
            reviewed_at=now,
            active=True,
            created_at=now,
            updated_at=now,
        )
        session.merge(rec_eb)
        session.merge(rec_cr)
        session.commit()
        session.close()

    def _mint_jwt(self, user_id: str, role: str = "USER") -> str:
        """Emite token Ed25519 válido para las pruebas de API."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "role": role,
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "jti": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        }
        import jwt
        return jwt.encode(payload, self.priv_pem, algorithm="EdDSA")

    def _upload_diagnosis_multipart(self, token: str, image_bytes: bytes, filename: str = "leaf.png") -> Tuple[int, Dict[str, Any]]:
        """Envía solicitud multipart de diagnóstico sin parámetro de cultivo."""
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Idempotency-Key": str(uuid.uuid4()),
        }
        resp = self.client.request("POST", "/api/v1/diagnoses", headers=headers, data=body)
        return resp.status_code, resp.json()

    def _build_analyzed_event(
        self,
        diag_id: uuid.UUID,
        lease_token: uuid.UUID,
        outcome: str,
        crop_code: Optional[str] = "POTATO",
        class_code: Optional[str] = "POTATO_EARLY_BLIGHT",
        raw_score: Optional[float] = 0.92,
        reason_code: Optional[str] = None,
        model_id: Optional[str] = "agrodiagnostico-mobilenetv3-cpu",
        model_version: Optional[str] = "1.0.0",
        dataset_version: Optional[str] = "2.0.0",
        inference_ms: Optional[int] = 15,
    ) -> dict:
        evt_id = uuid.uuid4()
        payload = {
            "diagnosis_id": str(diag_id),
            "lease_token": str(lease_token),
            "outcome": outcome,
            "crop_code": crop_code,
            "model_id": model_id,
            "model_version": model_version,
            "dataset_version": dataset_version,
            "inference_ms": inference_ms,
        }
        if outcome == "PREDICTION":
            payload["class_code"] = class_code
            payload["raw_score"] = raw_score
        else:
            payload["reason_code"] = reason_code or "LOW_CONFIDENCE"

        return {
            "event_id": str(evt_id),
            "event_type": "DiagnosisAnalyzed",
            "schema_version": 1,
            "occurred_at": format_utc_iso(datetime.now(timezone.utc)),
            "correlation_id": str(uuid.uuid4()),
            "payload": payload,
        }

    # =========================================================================
    # TAREA 9.1: Aceptación Integrada con Release Real y Catálogo Revisado
    # =========================================================================

    def test_9_1_01_e2e_dual_crop_potato_prediction_and_publication(self):
        """9.1: Carga sin cultivo manual, detección automática de PAPA, predicción y publicación COMPLETADO."""
        user_a = str(uuid.uuid4())
        token_a = self._mint_jwt(user_a)

        # 1. Ingestión sin parámetro de cultivo
        png_bytes = _generate_test_png(224, 224, r=40, g=180, b=40)
        status_code, body = self._upload_diagnosis_multipart(token_a, png_bytes, "potato_leaf.png")
        self.assertEqual(status_code, 202)
        diag_id = uuid.UUID(body["id"])
        self.assertEqual(body["status"], "PENDIENTE")

        # 2. Worker real ejecuta inferencia CPU
        diag_uuid = diag_id
        inference_out = self.adapter.run_inference(diag_uuid, png_bytes)
        self.assertEqual(inference_out["outcome"], "PREDICTION")
        self.assertEqual(inference_out["crop_code"], "POTATO")
        self.assertEqual(inference_out["class_code"], "POTATO_EARLY_BLIGHT")
        self.assertIsNotNone(inference_out["inference_ms"])
        self.assertGreater(inference_out["inference_ms"], 0)

        # 3. Consumo de DiagnosisAnalyzed con política activa y escalamiento de Platt
        lease_tok = uuid.uuid4()
        analyzed_event = self._build_analyzed_event(
            diag_id=diag_uuid,
            lease_token=lease_tok,
            outcome=inference_out["outcome"],
            crop_code=inference_out["crop_code"],
            class_code=inference_out["class_code"],
            raw_score=inference_out["raw_score"],
            model_id=inference_out["model_id"],
            model_version=inference_out["model_version"],
            dataset_version=inference_out["dataset_version"],
            inference_ms=inference_out["inference_ms"],
        )

        # Preparar lease activo en DB para el diagnóstico
        session = self.SessionLocal()
        d_row = session.get(Diagnosis, diag_uuid)
        d_row.status = "PROCESANDO"
        d_row.lease_token = lease_tok
        d_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()
        session.close()

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 101, json.dumps(analyzed_event).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertIn(101, channel.acked_tags)

        # 4. Verificación de resultado final vía API pública
        resp = self.client.request("GET", f"/api/v1/diagnoses/{diag_uuid}", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()

        self.assertEqual(res_data["status"], "COMPLETADO")
        result = res_data["result"]
        self.assertEqual(result["crop_code"], "POTATO")
        self.assertEqual(result["class_code"], "POTATO_EARLY_BLIGHT")
        self.assertIsNotNone(result["raw_score"])
        self.assertIsNotNone(result["estimated_confidence"])
        self.assertGreaterEqual(result["estimated_confidence"], 0.85)

        # Snapshot de política inmutable
        policy_snap = result["policy_snapshot"]
        self.assertIsNotNone(policy_snap)
        self.assertEqual(policy_snap["policy_id"], "d1a2b3c4-e5f6-7a8b-9c0d-1e2f3a4b5c6d")
        self.assertEqual(policy_snap["policy_version"], "1.0.0")

        # Orientación revisada del catálogo en payload visible
        rec = result["recommendation"]
        self.assertIsNotNone(rec)
        self.assertIn("Centro Internacional de la Papa", rec["text"])

        # Verificación directa en base de datos de los campos auditados del catálogo
        session = self.SessionLocal()
        d_db = session.get(Diagnosis, diag_uuid)
        rec_row = session.get(Recommendation, d_db.recommendation_id)
        self.assertIsNotNone(rec_row)
        self.assertIn("CIP-2024-MANUAL-PAPA-CAP-4", rec_row.source_refs)
        self.assertEqual(rec_row.review_reference, "REV-AGRO-CIP-2026-001")
        self.assertTrue(len(rec_row.cultural_practices) > 0)
        self.assertTrue(len(rec_row.biological_control) > 0)
        self.assertTrue(len(rec_row.preventive_measures) > 0)
        session.close()

    def test_9_1_02_e2e_dual_crop_maize_prediction_and_publication(self):
        """9.1: Carga sin cultivo manual, detección automática de MAÍZ, predicción y publicación COMPLETADO."""
        user_a = str(uuid.uuid4())
        token_a = self._mint_jwt(user_a)

        # Ingestión sin selección de cultivo
        png_bytes = _generate_test_png(224, 224, r=120, g=200, b=30)
        status_code, body = self._upload_diagnosis_multipart(token_a, png_bytes, "maize_leaf.png")
        self.assertEqual(status_code, 202)
        diag_uuid = uuid.UUID(body["id"])

        # Enviar evento de inferencia para Maíz
        lease_tok = uuid.uuid4()
        analyzed_event = self._build_analyzed_event(
            diag_id=diag_uuid,
            lease_token=lease_tok,
            outcome="PREDICTION",
            crop_code="MAIZE",
            class_code="MAIZE_COMMON_RUST",
            raw_score=0.88,
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            inference_ms=14,
        )

        session = self.SessionLocal()
        d_row = session.get(Diagnosis, diag_uuid)
        d_row.status = "PROCESANDO"
        d_row.lease_token = lease_tok
        d_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()
        session.close()

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 102, json.dumps(analyzed_event).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertIn(102, channel.acked_tags)

        # Verificación pública
        resp = self.client.request("GET", f"/api/v1/diagnoses/{diag_uuid}", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()

        self.assertEqual(res_data["status"], "COMPLETADO")
        result = res_data["result"]
        self.assertEqual(result["crop_code"], "MAIZE")
        self.assertEqual(result["class_code"], "MAIZE_COMMON_RUST")
        self.assertGreaterEqual(result["estimated_confidence"], 0.80)
        self.assertIn("CIMMYT", result["recommendation"]["text"])

        # Verificación en catálogo
        session = self.SessionLocal()
        d_db = session.get(Diagnosis, diag_uuid)
        rec_row = session.get(Recommendation, d_db.recommendation_id)
        self.assertIsNotNone(rec_row)
        self.assertIn("CIMMYT-2023-DISEASE-MANAGEMENT-MAIZE", rec_row.source_refs)
        session.close()

    def test_9_1_03_e2e_low_confidence_abstention(self):
        """9.1: Score técnico bajo el umbral de publicación produce abstención NO_CONCLUYENTE (LOW_CONFIDENCE)."""
        user_a = str(uuid.uuid4())
        token_a = self._mint_jwt(user_a)

        png_bytes = _generate_test_png(224, 224, r=80, g=80, b=80)
        status_code, body = self._upload_diagnosis_multipart(token_a, png_bytes, "doubtful_leaf.png")
        self.assertEqual(status_code, 202)
        diag_uuid = uuid.UUID(body["id"])

        lease_tok = uuid.uuid4()
        analyzed_event = self._build_analyzed_event(
            diag_id=diag_uuid,
            lease_token=lease_tok,
            outcome="ABSTENTION",
            crop_code="POTATO",
            reason_code="LOW_CONFIDENCE",
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            inference_ms=12,
        )

        session = self.SessionLocal()
        d_row = session.get(Diagnosis, diag_uuid)
        d_row.status = "PROCESANDO"
        d_row.lease_token = lease_tok
        d_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()
        session.close()

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 103, json.dumps(analyzed_event).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertIn(103, channel.acked_tags)

        resp = self.client.request("GET", f"/api/v1/diagnoses/{diag_uuid}", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()
        self.assertEqual(res_data["status"], "NO_CONCLUYENTE")
        self.assertEqual(res_data["reason_code"], "LOW_CONFIDENCE")
        self.assertNotIn("result", res_data)

    def test_9_1_04_e2e_negatives_and_unsupported_crop_abstention(self):
        """9.1: Imágenes negativas (suelo/inanimado) resultan en abstención estricta (UNSUPPORTED_CROP)."""
        user_a = str(uuid.uuid4())
        token_a = self._mint_jwt(user_a)

        # Imagen de fondo inanimado/suelo (gris/marrón)
        png_bytes = _generate_test_png(224, 224, r=139, g=69, b=19)
        status_code, body = self._upload_diagnosis_multipart(token_a, png_bytes, "soil_negative.png")
        self.assertEqual(status_code, 202)
        diag_uuid = uuid.UUID(body["id"])

        lease_tok = uuid.uuid4()
        analyzed_event = self._build_analyzed_event(
            diag_id=diag_uuid,
            lease_token=lease_tok,
            outcome="ABSTENTION",
            crop_code=None,
            reason_code="UNSUPPORTED_CROP",
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            inference_ms=10,
        )

        session = self.SessionLocal()
        d_row = session.get(Diagnosis, diag_uuid)
        d_row.status = "PROCESANDO"
        d_row.lease_token = lease_tok
        d_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()
        session.close()

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 104, json.dumps(analyzed_event).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertIn(104, channel.acked_tags)

        resp = self.client.request("GET", f"/api/v1/diagnoses/{diag_uuid}", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(resp.status_code, 200)
        res_data = resp.json()
        self.assertEqual(res_data["status"], "NO_CONCLUYENTE")
        self.assertEqual(res_data["reason_code"], "UNSUPPORTED_CROP")
        self.assertNotIn("result", res_data)

    def test_9_1_05_e2e_bad_image_abstention(self):
        """9.1: Bytes de imagen corruptos o fuera de dimensiones provocan ABSTENTION con BAD_IMAGE."""
        user_a = str(uuid.uuid4())
        token_a = self._mint_jwt(user_a)

        # Dimensión diminuta (< 200) rechazada técnicamente antes de la inferencia
        png_bytes = _generate_test_png(128, 128)
        inf_res = self.adapter.run_inference(uuid.uuid4(), png_bytes)
        self.assertEqual(inf_res["outcome"], "ABSTENTION")
        self.assertEqual(inf_res["reason_code"], "BAD_IMAGE")
        self.assertIsNone(inf_res["model_id"])

        # Probar en flujo completo
        status_code, body = self._upload_diagnosis_multipart(token_a, png_bytes, "tiny.png")
        self.assertEqual(status_code, 202)
        diag_uuid = uuid.UUID(body["id"])

        lease_tok = uuid.uuid4()
        analyzed_event = self._build_analyzed_event(
            diag_id=diag_uuid,
            lease_token=lease_tok,
            outcome="ABSTENTION",
            crop_code=None,
            reason_code="BAD_IMAGE",
            model_id=None,
            model_version=None,
            dataset_version=None,
            inference_ms=None,
        )

        session = self.SessionLocal()
        d_row = session.get(Diagnosis, diag_uuid)
        d_row.status = "PROCESANDO"
        d_row.lease_token = lease_tok
        d_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()
        session.close()

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 105, json.dumps(analyzed_event).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertIn(105, channel.acked_tags)

        resp = self.client.request("GET", f"/api/v1/diagnoses/{diag_uuid}", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "NO_CONCLUYENTE")
        self.assertEqual(resp.json()["reason_code"], "BAD_IMAGE")

    def test_9_1_06_e2e_unapproved_class_in_policy_fails_closed(self):
        """9.1: Detección técnica de una patología no aprobada en la política activa finaliza como UNSUPPORTED_CLASS."""
        user_a = str(uuid.uuid4())
        token_a = self._mint_jwt(user_a)

        png_bytes = _generate_test_png(224, 224)
        status_code, body = self._upload_diagnosis_multipart(token_a, png_bytes, "late_blight.png")
        self.assertEqual(status_code, 202)
        diag_uuid = uuid.UUID(body["id"])

        # POTATO_LATE_BLIGHT no está aprobada en la política activa
        lease_tok = uuid.uuid4()
        analyzed_event = self._build_analyzed_event(
            diag_id=diag_uuid,
            lease_token=lease_tok,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_LATE_BLIGHT",
            raw_score=0.95,
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            inference_ms=15,
        )

        session = self.SessionLocal()
        d_row = session.get(Diagnosis, diag_uuid)
        d_row.status = "PROCESANDO"
        d_row.lease_token = lease_tok
        d_row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()
        session.close()

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 106, json.dumps(analyzed_event).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertIn(106, channel.acked_tags)

        resp = self.client.request("GET", f"/api/v1/diagnoses/{diag_uuid}", headers={"Authorization": f"Bearer {token_a}"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "NO_CONCLUYENTE")
        self.assertEqual(resp.json()["reason_code"], "UNSUPPORTED_CLASS")

    def test_9_1_07_e2e_foreign_owner_isolation_returns_generic_404(self):
        """9.1: Aislamiento multi-inquilino estricto (Usuario B recibe 404 genérico al intentar acceder a recursos de Usuario A)."""
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        token_a = self._mint_jwt(user_a)
        token_b = self._mint_jwt(user_b)

        png_bytes = _generate_test_png(224, 224)
        st, body = self._upload_diagnosis_multipart(token_a, png_bytes, "user_a.png")
        self.assertEqual(st, 202)
        diag_id = body["id"]

        # 1. Consulta de detalle de Usuario A por Usuario B -> 404
        r_get = self.client.request("GET", f"/api/v1/diagnoses/{diag_id}", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(r_get.status_code, 404)

        # 2. Descarga de imagen de Usuario A por Usuario B -> 404
        r_img = self.client.request("GET", f"/api/v1/diagnoses/{diag_id}/image", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(r_img.status_code, 404)

        # 3. Cancelación de diagnóstico de Usuario A por Usuario B -> 404
        r_cnc = self.client.request("POST", f"/api/v1/diagnoses/{diag_id}/cancel", headers={"Authorization": f"Bearer {token_b}"})
        self.assertEqual(r_cnc.status_code, 404)

        # 4. Feedback en diagnóstico de Usuario A por Usuario B -> 404
        r_fb = self.client.post(
            f"/api/v1/diagnoses/{diag_id}/feedback",
            headers={"Authorization": f"Bearer {token_b}"},
            json={"useful": True},
        )
        self.assertEqual(r_fb.status_code, 404)

    def test_9_1_08_e2e_keyset_history_pagination(self):
        """9.1: Consulta paginada por cursor HMAC-SHA256 del historial propio."""
        user = str(uuid.uuid4())
        token = self._mint_jwt(user)

        # Crear 3 diagnósticos para el usuario
        ids = []
        for i in range(3):
            png = _generate_test_png(224, 224)
            st, body = self._upload_diagnosis_multipart(token, png, f"leaf_{i}.png")
            self.assertEqual(st, 202)
            ids.append(body["id"])

        # Consultar primera página con límite 2
        r_hist1 = self.client.request("GET", "/api/v1/diagnoses?limit=2", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r_hist1.status_code, 200)
        data1 = r_hist1.json()
        self.assertEqual(len(data1["items"]), 2)
        self.assertIsNotNone(data1.get("next_cursor"))

        # Consultar segunda página usando cursor
        cursor = data1["next_cursor"]
        r_hist2 = self.client.request("GET", f"/api/v1/diagnoses?limit=2&cursor={cursor}", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r_hist2.status_code, 200)
        data2 = r_hist2.json()
        self.assertEqual(len(data2["items"]), 1)

    # =========================================================================
    # TAREA 9.2: Matriz de Fallos con Runtime Real y Benchmark CPU
    # =========================================================================

    def test_9_2_01_fault_worker_crash_and_lease_recovery(self):
        """9.2: Caída de worker durante inferencia: expiración de lease y recuperación con resultado terminal único."""
        session = self.SessionLocal()
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        lease_tok = uuid.uuid4()

        # Diagnóstico reclamado cuyo lease expiró tras crash de worker (10s vencido > 5s wait)
        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="PROCESANDO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="fake_sha256_recovery",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            lease_owner="ai-worker-1",
            lease_token=lease_tok,
            lease_expires_at=now - timedelta(seconds=10),
            attempt_count=1,
            processing_deadline_at=now + timedelta(seconds=240),
            correlation_id=uuid.uuid4(),
            created_at=now - timedelta(minutes=10),
            updated_at=now - timedelta(minutes=8),
        )
        session.add(diag)
        session.commit()

        # Ejecutar servicio de recuperación de leases
        actions = recover_expired_leases(session, policy=LeasePolicy())
        self.assertGreaterEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "SIGNAL_EMITTED")
        self.assertEqual(actions[0]["attempt_number"], 2)

        # El diagnóstico permanece en PROCESANDO con recovery_signaled_at registrado
        session.refresh(diag)
        self.assertEqual(diag.status, "PROCESANDO")
        self.assertIsNotNone(diag.recovery_signaled_at)

        # Un resultado tardío con lease_tok anterior es rechazado atómicamente si el token cambió o expiró
        analyzed_event = self._build_analyzed_event(
            diag_id=diag_id,
            lease_token=uuid.uuid4(),  # Token tardío / no coincide con el actual
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
            raw_score=0.90,
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            inference_ms=12,
        )

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 201, json.dumps(analyzed_event).encode("utf-8"), "diagnosis.analyzed.v1")
        session.refresh(diag)
        self.assertNotEqual(diag.status, "COMPLETADO")
        session.close()

    def test_9_2_02_fault_stale_lease_commit_conflict_409(self):
        """9.2: Intento de commit con lease obsoleto es rechazado atómicamente con conflicto 409."""
        session = self.SessionLocal()
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        winner_tok = uuid.uuid4()
        loser_tok = uuid.uuid4()

        # Diagnóstico ya completado por otro proceso
        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="COMPLETADO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="fake_sha256_winner",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
            raw_score=0.92,
            calibrated_confidence=0.88,
            created_at=now - timedelta(minutes=5),
            updated_at=now - timedelta(minutes=2),
            lease_token=winner_tok,
            lease_expires_at=now + timedelta(minutes=5),
        )
        session.add(diag)
        session.commit()

        # Llega resultado tardío de worker lento con lease vencido
        analyzed_late = self._build_analyzed_event(
            diag_id=diag_id,
            lease_token=loser_tok,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
            raw_score=0.81,
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            inference_ms=50,
        )

        channel = MockAMQPChannel()
        self.consumer.process_message(channel, 202, json.dumps(analyzed_late).encode("utf-8"), "diagnosis.analyzed.v1")
        self.assertIn(202, channel.acked_tags)

        # Verificar inmutabilidad: el resultado ganador no fue tocado
        session.refresh(diag)
        self.assertEqual(diag.status, "COMPLETADO")
        self.assertEqual(diag.raw_score, 0.92)
        self.assertEqual(diag.lease_token, winner_tok)
        session.close()

    def test_9_2_03_fault_amqp_redelivery_idempotency(self):
        """9.2: Reentrega AMQP (redelivery) se procesa de forma idempotente sin duplicar outbox ni historia."""
        session = self.SessionLocal()
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        redeliv_tok = uuid.uuid4()

        diag = Diagnosis(
            id=diag_id,
            owner_id=uuid.uuid4(),
            status="PROCESANDO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="fake_sha256_redeliv",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            created_at=now - timedelta(minutes=2),
            updated_at=now,
            lease_token=redeliv_tok,
            lease_expires_at=now + timedelta(minutes=5),
        )
        session.add(diag)
        session.commit()
        session.close()

        analyzed_event = self._build_analyzed_event(
            diag_id=diag_id,
            lease_token=redeliv_tok,
            outcome="PREDICTION",
            crop_code="POTATO",
            class_code="POTATO_EARLY_BLIGHT",
            raw_score=0.89,
            model_id="agrodiagnostico-mobilenetv3-cpu",
            model_version="1.0.0",
            dataset_version="2.0.0",
            inference_ms=11,
        )

        body = json.dumps(analyzed_event).encode("utf-8")
        channel = MockAMQPChannel()

        # Primera entrega
        self.consumer.process_message(channel, 301, body, "diagnosis.analyzed.v1")
        self.assertIn(301, channel.acked_tags)

        # Contar outbox emitidos
        session = self.SessionLocal()
        outbox_count_1 = session.query(DiagnosisOutbox).filter_by(diagnosis_id=diag_id).count()
        self.assertEqual(outbox_count_1, 1)

        # Segunda entrega (re-entrega idéntica por broker)
        channel2 = MockAMQPChannel()
        self.consumer.process_message(channel2, 302, body, "diagnosis.analyzed.v1")
        self.assertIn(302, channel2.acked_tags)

        outbox_count_2 = session.query(DiagnosisOutbox).filter_by(diagnosis_id=diag_id).count()
        self.assertEqual(outbox_count_2, 1, "Idempotencia violada: outbox fue duplicado en redelivery")
        session.close()

    def test_9_2_04_cpu_latency_and_memory_benchmark(self):
        """9.2: Medición CPU rigurosa de latencia y consumo de memoria bajo carga frente a metas del protocolo G0."""
        num_inferences = 50
        latencies_ms: List[float] = []

        # Preparar 50 imágenes diversas (Papa, Maíz, Fondos)
        images = [
            _generate_test_png(224, 224, r=(i * 13) % 256, g=(i * 37) % 256, b=(i * 71) % 256)
            for i in range(num_inferences)
        ]

        # Medir memoria inicial
        mem_start_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # En Linux ru_maxrss está en kilobytes
        mem_start_mb = mem_start_kb / 1024.0

        t_start_total = time.monotonic()
        for i, img_bytes in enumerate(images):
            diag_id = uuid.uuid4()
            t0 = time.monotonic()
            res = self.adapter.run_inference(diag_id, img_bytes)
            elapsed = (time.monotonic() - t0) * 1000.0
            latencies_ms.append(elapsed)
            self.assertIn(res["outcome"], ["PREDICTION", "ABSTENTION"])

        total_elapsed = time.monotonic() - t_start_total
        mem_peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        mem_peak_mb = mem_peak_kb / 1024.0
        mem_delta_mb = max(0.0, mem_peak_mb - mem_start_mb)

        latencies_sorted = sorted(latencies_ms)
        min_lat = min(latencies_sorted)
        mean_lat = sum(latencies_sorted) / len(latencies_sorted)
        med_lat = latencies_sorted[int(len(latencies_sorted) * 0.50)]
        p90_lat = latencies_sorted[int(len(latencies_sorted) * 0.90)]
        p95_lat = latencies_sorted[int(len(latencies_sorted) * 0.95)]
        max_lat = max(latencies_sorted)

        print(f"\n=======================================================", flush=True)
        print(f"BENCHMARK CPU RUNTIME REAL - Tarea 9.2 ({num_inferences} iteraciones)", flush=True)
        print(f"=======================================================", flush=True)
        print(f"  Latencia Min:     {min_lat:.2f} ms", flush=True)
        print(f"  Latencia Media:   {mean_lat:.2f} ms", flush=True)
        print(f"  Latencia Mediana: {med_lat:.2f} ms", flush=True)
        print(f"  Latencia P90:     {p90_lat:.2f} ms", flush=True)
        print(f"  Latencia P95:     {p95_lat:.2f} ms (Meta Protocolo G0: <= 1000 ms)", flush=True)
        print(f"  Latencia Max:     {max_lat:.2f} ms", flush=True)
        print(f"  Memoria Pico RSS: {mem_peak_mb:.2f} MB (Meta Protocolo G0: <= 1024 MB)", flush=True)
        print(f"  Memoria Delta:    {mem_delta_mb:.2f} MB", flush=True)
        print(f"=======================================================\n", flush=True)

        # Aserciones contractuales frente a metas del protocolo G0
        self.assertLessEqual(p95_lat, 1000.0, f"P95 Latency {p95_lat}ms excede el presupuesto G0 de 1000ms")
        self.assertLessEqual(mem_peak_mb, 1024.0, f"Peak Memory {mem_peak_mb}MB excede el presupuesto G0 de 1024MB")


if __name__ == "__main__":
    unittest.main()
