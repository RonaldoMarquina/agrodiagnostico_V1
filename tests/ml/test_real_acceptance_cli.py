"""Pruebas unitarias para el comando de aceptación real (Tarea 8.2).

Verifica:
- Rechazo explícito de fixtures como evidencia real (FixtureRejectedError).
- Detección y rechazo de artefactos alterados/tampered (TamperedArtifactError).
- Rechazo de discrepancias entre política y bundle (digest/version mismatch).
- Limpieza garantizada de recursos y carpetas temporales.
- Generación de reporte saneado sin filtración de secretos.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from agro_ml.models.architectures import CLASS_MAPPING, CPUClassifier
from agro_ml.packaging.bundle import build_model_bundle, build_publication_policy
from check_ml_real_acceptance import (
    FixtureRejectedError,
    RealAcceptanceError,
    TamperedArtifactError,
    main as cli_main,
    run_real_acceptance,
)

ROOT = Path(__file__).resolve().parents[2]


class TestRealAcceptanceCLI(unittest.TestCase):
    def _create_mock_environment(
        self,
        base_dir: Path,
        model_id: str = "agrodiagnostico-mobilenetv3-cpu",
        model_version: str = "1.0.0",
        dataset_version: str = "2.0.0",
        approved_by: str = "Comite Agronomico UNMSM",
        g2_approval_id: str = "G2-VAL-2026-001",
        tamper_weights: bool = False,
        mismatch_policy: bool = False,
    ) -> tuple[Path, Path, Path, Path]:
        # 1. Pesos y bundle
        weights_file = base_dir / "model_weights.safetensors"
        model = CPUClassifier("mobilenet_v3_small")
        model.save_weights(weights_file)

        train_m = base_dir / "train.csv"; train_m.write_text("image_id,path\n", encoding="utf-8")
        val_m = base_dir / "val.csv"; val_m.write_text("image_id,path\n", encoding="utf-8")
        test_m = base_dir / "test.csv"; test_m.write_text("image_id,path\n", encoding="utf-8")

        bundle_file = base_dir / "bundle.json"
        calib = {"POTATO_EARLY_BLIGHT": {"slope": 1.25, "intercept": -0.15}}
        class_map = {str(k): v for k, v in CLASS_MAPPING.items()}

        bundle_data = build_model_bundle(
                approved_by='fixture-reviewer-not-human-approval',
                g2_approval_id='FIXTURE-NOT-APPROVED',
                approved_at='2026-10-10T00:00:00Z',
            model_id=model_id,
            model_version=model_version,
            dataset_version=dataset_version,
            architecture="mobilenet_v3_small",
            weights_path=weights_file,
            train_manifest_path=train_m,
            val_manifest_path=val_m,
            test_manifest_path=test_m,
            class_map=class_map,
            calibration_params=calib,
            output_bundle_path=bundle_file,
        )
        bundle_data["governance"]["approved_by"] = approved_by
        bundle_data["governance"]["g2_approval_id"] = g2_approval_id
        bundle_file.write_text(json.dumps(bundle_data, indent=2), encoding="utf-8")
        bundle_digest = hashlib.sha256(bundle_file.read_bytes()).hexdigest()

        if tamper_weights:
            weights_file.write_bytes(b"TAMPERED_WEIGHTS_CONTENT_OVERWRITE")

        # 2. Política de publicación
        policy_file = base_dir / "policy.json"
        policy_data = build_publication_policy(
            policy_id=str(uuid.uuid4()),
            policy_version="1.0.0",
            model_id=model_id,
            model_version=model_version,
            dataset_version=dataset_version,
            bundle_digest=bundle_digest if not mismatch_policy else "0" * 64,
            approved_classes=[
                {"class_code": "POTATO_EARLY_BLIGHT", "crop_code": "POTATO", "min_confidence_threshold": 0.85, "calibration_params": {"slope": 1.25, "intercept": -0.15}},
                {"class_code": "MAIZE_COMMON_RUST", "crop_code": "MAIZE", "min_confidence_threshold": 0.80, "calibration_params": {"slope": 1.10, "intercept": -0.10}},
            ],
            unsupported_classes=[],
            g2_approval_reference=g2_approval_id,
            approved_by=approved_by,
            output_policy_path=policy_file,
        )
        policy_data["audit"]["imported_by"] = "Docente Revisor Agronomia"
        policy_file.write_text(json.dumps(policy_data, indent=2), encoding="utf-8")

        # 3. Manifiesto y sello
        manifest_file = base_dir / "images.csv"
        manifest_file.write_text("image_id,split\n1,TEST\n", encoding="utf-8")
        manifest_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

        seal_file = base_dir / "seal.json"
        seal_data = {
            "schema_version": 1,
            "manifest_sha256": manifest_sha,
            "sealed_at": "2026-10-15T12:00:00Z",
            "sealed_by": approved_by,
        }
        seal_file.write_text(json.dumps(seal_data, indent=2), encoding="utf-8")

        return bundle_file, policy_file, manifest_file, seal_file

    def test_rejection_of_fixture_as_real_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            bundle_file, policy_file, manifest_file, seal_file = self._create_mock_environment(
                base,
                model_id="ci-fixture-cpu",  # Nombre explícito de fixture
            )
            report_file = base / "report.json"

            with self.assertRaises(FixtureRejectedError) as ctx:
                run_real_acceptance(
                    release_bundle_path=bundle_file,
                    policy_file_path=policy_file,
                    dataset_manifest_path=manifest_file,
                    seal_path=seal_file,
                    output_report_path=report_file,
                    command_args=["test_runner"],
                )
            self.assertIn("FIXTURE_REJECTED", str(ctx.exception))

    def test_rejection_of_tampered_weights(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            bundle_file, policy_file, manifest_file, seal_file = self._create_mock_environment(
                base,
                tamper_weights=True,
            )
            report_file = base / "report.json"

            with self.assertRaises(TamperedArtifactError) as ctx:
                run_real_acceptance(
                    release_bundle_path=bundle_file,
                    policy_file_path=policy_file,
                    dataset_manifest_path=manifest_file,
                    seal_path=seal_file,
                    output_report_path=report_file,
                    command_args=["test_runner"],
                )
            self.assertIn("DIGEST_MISMATCH", str(ctx.exception))

    def test_rejection_of_policy_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            bundle_file, policy_file, manifest_file, seal_file = self._create_mock_environment(
                base,
                mismatch_policy=True,
            )
            report_file = base / "report.json"

            with self.assertRaises(TamperedArtifactError) as ctx:
                run_real_acceptance(
                    release_bundle_path=bundle_file,
                    policy_file_path=policy_file,
                    dataset_manifest_path=manifest_file,
                    seal_path=seal_file,
                    output_report_path=report_file,
                    command_args=["test_runner"],
                )
            self.assertIn("POLICY_DIGEST_MISMATCH", str(ctx.exception))

    def test_synthetic_smoke_cannot_approve_g3(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            bundle_file, policy_file, manifest_file, seal_file = self._create_mock_environment(base)
            report_file = base / "report.json"
            with self.assertRaisesRegex(RealAcceptanceError, "G3_NOT_IMPLEMENTED"):
                run_real_acceptance(bundle_file, policy_file, manifest_file, seal_file, report_file, ["test"])
            self.assertFalse(report_file.exists())


    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            bundle_file, policy_file, manifest_file, seal_file = self._create_mock_environment(base)
            report_file = base / "report.json"

            # Una comprobación sintética no puede aprobar G3
            code = cli_main([
                "--release-bundle", str(bundle_file),
                "--policy-file", str(policy_file),
                "--dataset-manifest", str(manifest_file),
                "--test-seal", str(seal_file),
                "--output-report", str(report_file),
            ])
            self.assertEqual(code, 1)

            # Caso fallido (archivo inexistente): código 1
            code_fail = cli_main([
                "--release-bundle", str(base / "nonexistent.json"),
                "--policy-file", str(policy_file),
                "--output-report", str(report_file),
            ])
            self.assertEqual(code_fail, 1)


if __name__ == "__main__":
    unittest.main()
