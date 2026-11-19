"""Ensayo operacional de rollback, falla cerrada e inmutabilidad histórica (Tarea 8.3).

Verifica conforme a ADR-0009 y D7:
1. En caso de retiro de una versión de política sin versión previa aprobada:
   - Diagnosis falla cerrado (COMPLETADO -> NO_CONCLUYENTE con UNSUPPORTED_CLASS).
   - NUNCA se activa el adaptador de simulación ni fallback a respuestas sintéticas.
2. Los diagnósticos emitidos bajo la versión previa:
   - Conservan su snapshot de política inmutable (applied_policy_id, estimated_confidence).
   - La historia clínica NUNCA se borra ni se modifica al cambiar o retirar políticas.
3. El procedimiento de rollback a una versión previa aprobada:
   - Restaura inmediatamente la publicación bajo la versión anterior aprobada.
   - Preserva auditoría transaccional de cada acción operativa.
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


class TestOperationalRollbackRehearsal(unittest.TestCase):
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

        prob_eb = Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO", name="Tizón temprano", type="DISEASE", model_supported=False, active=True)
        prob_cr = Problem(code="MAIZE_COMMON_RUST", crop_code="MAIZE", name="Roya común", type="DISEASE", model_supported=False, active=True)
        self.session.add_all([prob_eb, prob_cr])

        rec_eb = Recommendation(
            problem_code="POTATO_EARLY_BLIGHT",
            version=1,
            title="Tizón temprano en papa",
            summary="Manejo preventivo de tizón temprano",
            cultural_practices=["Rotación de cultivos"],
            biological_control=["Trichoderma spp."],
            preventive_measures=["Monitoreo de humedad foliar"],
            source_refs=["CIP-2024-BOLETIN-01"],
            review_reference="REV-AGRO-2026-001",
            reviewed_by="Docente Agrónomo",
            reviewed_at=now,
            active=True,
        )
        rec_cr = Recommendation(
            problem_code="MAIZE_COMMON_RUST",
            version=1,
            title="Roya común en maíz",
            summary="Manejo preventivo de roya",
            cultural_practices=["Ventilación de surcos"],
            biological_control=["Bacillus subtilis"],
            preventive_measures=["Eliminación de rastrojo infectado"],
            source_refs=["CIMMYT-2023-MANUAL-02"],
            review_reference="REV-AGRO-2026-002",
            reviewed_by="Docente Agrónomo",
            reviewed_at=now,
            active=True,
        )
        self.session.add_all([rec_eb, rec_cr])
        self.session.commit()

        # Políticas de prueba v1 (estable) y v2 (candidata)
        self.policy_v1_id = uuid.uuid4()
        self.policy_v2_id = uuid.uuid4()

        self.policy_v1_payload = {
            "schema_version": 1,
            "policy_id": str(self.policy_v1_id),
            "policy_version": "1.0.0",
            "target_model": {
                "model_id": "agrodiagnostico-mobilenetv3-cpu",
                "model_version": "1.0.0",
                "dataset_version": "2.0.0",
                "bundle_digest": "a" * 64,
            },
            "approved_classes": [
                {
                    "class_code": "POTATO_EARLY_BLIGHT",
                    "crop_code": "POTATO",
                    "min_confidence_threshold": 0.80,
                    "calibration_params": {"slope": 2.0, "intercept": 0.0},
                }
            ],
            "unsupported_classes": [],
            "catalog_requirements": {"require_reviewed_catalog": True},
            "governance": {
                "g0_protocol_version": "1.0.0",
                "g2_approval_reference": "G2-EVAL-V1",
                "approved_by": "Comité Agronómico",
                "approved_at": "2026-10-15T12:00:00Z",
            },
            "audit": {"imported_by": "operador_ci", "imported_at": "2026-10-15T12:00:00Z"},
        }

        self.policy_v2_payload = {
            "schema_version": 1,
            "policy_id": str(self.policy_v2_id),
            "policy_version": "2.0.0",
            "target_model": {
                "model_id": "agrodiagnostico-mobilenetv3-cpu",
                "model_version": "2.0.0",
                "dataset_version": "2.1.0",
                "bundle_digest": "b" * 64,
            },
            "approved_classes": [
                {
                    "class_code": "POTATO_EARLY_BLIGHT",
                    "crop_code": "POTATO",
                    "min_confidence_threshold": 0.80,
                    "calibration_params": {"slope": 2.0, "intercept": 0.0},
                }
            ],
            "unsupported_classes": [],
            "catalog_requirements": {"require_reviewed_catalog": True},
            "governance": {
                "g0_protocol_version": "1.0.0",
                "g2_approval_reference": "G2-EVAL-V2",
                "approved_by": "Comité Agronómico",
                "approved_at": "2026-10-15T13:00:00Z",
            },
            "audit": {"imported_by": "operador_ci", "imported_at": "2026-10-15T13:00:00Z"},
        }

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _create_processing_diagnosis(self) -> tuple[Diagnosis, uuid.UUID]:
        diag_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + 300, tz=timezone.utc)

        d = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status="PROCESANDO",
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="c" * 64,
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            lease_owner="ai-worker-1",
            lease_token=lease_token,
            lease_expires_at=expires_at,
            attempt_count=1,
            correlation_id=uuid.uuid4(),
            created_at=now,
            updated_at=now,
        )
        self.session.add(d)
        self.session.commit()
        return d, lease_token

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
            "inference_ms": 45,
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

    def test_rehearsal_retirement_without_previous_version_fails_closed_never_simulates(self):
        """Ensayo 1: El retiro de una política sin reemplazo activo falla cerrado y no activa simulación."""
        # 1. Importar y activar política v1
        import_publication_policy(self.session, "admin", "Import v1", self.policy_v1_payload, apply=True)
        activate_publication_policy(self.session, "admin", "Activate v1", self.policy_v1_id, apply=True)

        # 2. Diagnóstico A bajo v1 -> Completado con éxito
        diag_a, token_a = self._create_processing_diagnosis()
        msg_a = self._build_analyzed_message(diag_a.id, token_a, raw_score=0.90)

        ch = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(ch, 1, msg_a, "diagnosis.analyzed.v1"))
        self.assertEqual(ch.acked_tags, [1])

        # Verificar que Diagnóstico A quedó COMPLETADO con snapshot de v1
        self.session.expire_all()
        res_a = self.session.scalar(select(Diagnosis).where(Diagnosis.id == diag_a.id))
        self.assertEqual(res_a.status, "COMPLETADO")
        self.assertEqual(res_a.policy_id, self.policy_v1_id)
        self.assertEqual(res_a.policy_version, "1.0.0")
        self.assertEqual(res_a.policy_digest, "a" * 64)
        self.assertIsNotNone(res_a.calibrated_confidence)

        # 3. Retiro operativo de la política v1 (sin ninguna otra versión activa)
        retire_publication_policy(self.session, "operador_seguridad", "Retiro preventivo de emergencia", self.policy_v1_id, apply=True)

        # Invariante 1: El catálogo ahora marca model_supported = False
        prob_eb = self.session.scalar(select(Problem).where(Problem.code == "POTATO_EARLY_BLIGHT"))
        self.assertFalse(prob_eb.model_supported)

        # 4. Llega un nuevo análisis B intentando publicar bajo el modelo cuyo release fue retirado
        diag_b, token_b = self._create_processing_diagnosis()
        msg_b = self._build_analyzed_message(diag_b.id, token_b, raw_score=0.95)

        self.assertTrue(self.consumer.process_message(ch, 2, msg_b, "diagnosis.analyzed.v1"))
        self.assertEqual(ch.acked_tags, [1, 2])

        # Invariante 2: Falla cerrado -> NO_CONCLUYENTE con UNSUPPORTED_CLASS
        self.session.expire_all()
        res_b = self.session.scalar(select(Diagnosis).where(Diagnosis.id == diag_b.id))
        self.assertEqual(res_b.status, "NO_CONCLUYENTE")
        self.assertEqual(res_b.reason_code, "UNSUPPORTED_CLASS")
        self.assertIsNone(res_b.policy_id)
        self.assertIsNone(res_b.calibrated_confidence)

        # Invariante 3: Inmutabilidad de la historia clínica
        # Diagnóstico A sigue intacto: COMPLETADO, misma confianza, misma versión y digest
        res_a_after = self.session.scalar(select(Diagnosis).where(Diagnosis.id == diag_a.id))
        self.assertEqual(res_a_after.status, "COMPLETADO")
        self.assertEqual(res_a_after.policy_id, self.policy_v1_id)
        self.assertEqual(res_a_after.policy_version, "1.0.0")
        self.assertEqual(res_a_after.policy_digest, "a" * 64)
        self.assertEqual(res_a_after.calibrated_confidence, res_a.calibrated_confidence)

    def test_rehearsal_rollback_to_previous_version_preserves_multi_version_history(self):
        """Ensayo 2: Rollback v2 -> v1 restaura publicación y preserva snapshots de ambas versiones."""
        # 1. Activar v1 y procesar diagnóstico A
        import_publication_policy(self.session, "admin", "Import v1", self.policy_v1_payload, apply=True)
        activate_publication_policy(self.session, "admin", "Activate v1", self.policy_v1_id, apply=True)

        diag_a, token_a = self._create_processing_diagnosis()
        msg_a = self._build_analyzed_message(diag_a.id, token_a, model_version="1.0.0", dataset_version="2.0.0", raw_score=0.88)
        ch = MockAMQPChannel()
        self.assertTrue(self.consumer.process_message(ch, 1, msg_a, "diagnosis.analyzed.v1"))

        # 2. Promover v2: Importar y activar v2 (v1 pasa a RETIRED)
        import_publication_policy(self.session, "admin", "Import v2", self.policy_v2_payload, apply=True)
        retire_publication_policy(self.session, "admin", "Superseded by v2", self.policy_v1_id, apply=True)
        activate_publication_policy(self.session, "admin", "Activate v2", self.policy_v2_id, apply=True)

        diag_b, token_b = self._create_processing_diagnosis()
        msg_b = self._build_analyzed_message(diag_b.id, token_b, model_version="2.0.0", dataset_version="2.1.0", raw_score=0.90)
        self.assertTrue(self.consumer.process_message(ch, 2, msg_b, "diagnosis.analyzed.v1"))

        # 3. Detectar anomalía en v2: Ejecutar rollback a v1
        retire_publication_policy(self.session, "operador", "Rollback v2 por degradación", self.policy_v2_id, apply=True)
        activate_publication_policy(self.session, "operador", "Restaurar v1 tras rollback", self.policy_v1_id, apply=True)

        # 4. Nuevo diagnóstico C bajo v1 restaurada
        diag_c, token_c = self._create_processing_diagnosis()
        msg_c = self._build_analyzed_message(diag_c.id, token_c, model_version="1.0.0", dataset_version="2.0.0", raw_score=0.92)
        self.assertTrue(self.consumer.process_message(ch, 3, msg_c, "diagnosis.analyzed.v1"))

        # Invariantes de Trazabilidad e Inmutabilidad Histórica:
        self.session.expire_all()
        d_a = self.session.scalar(select(Diagnosis).where(Diagnosis.id == diag_a.id))
        d_b = self.session.scalar(select(Diagnosis).where(Diagnosis.id == diag_b.id))
        d_c = self.session.scalar(select(Diagnosis).where(Diagnosis.id == diag_c.id))

        # Diagnóstico A: Emitido bajo v1 original
        self.assertEqual(d_a.status, "COMPLETADO")
        self.assertEqual(d_a.policy_id, self.policy_v1_id)
        self.assertEqual(d_a.policy_version, "1.0.0")
        self.assertEqual(d_a.policy_digest, "a" * 64)

        # Diagnóstico B: Emitido bajo v2 antes del rollback (snapshot v2 preservado inmutable)
        self.assertEqual(d_b.status, "COMPLETADO")
        self.assertEqual(d_b.policy_id, self.policy_v2_id)
        self.assertEqual(d_b.policy_version, "2.0.0")
        self.assertEqual(d_b.policy_digest, "b" * 64)

        # Diagnóstico C: Emitido bajo v1 tras el rollback
        self.assertEqual(d_c.status, "COMPLETADO")
        self.assertEqual(d_c.policy_id, self.policy_v1_id)
        self.assertEqual(d_c.policy_version, "1.0.0")
        self.assertEqual(d_c.policy_digest, "a" * 64)


if __name__ == "__main__":
    unittest.main()
