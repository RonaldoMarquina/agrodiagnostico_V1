"""Pruebas unitarias para empaquetado, contratos de bundle y política, carga independiente y cobertura dual."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from agro_ml.models.architectures import CLASS_MAPPING, CPUClassifier
from agro_ml.packaging.bundle import (
    BundleIntegrityError,
    BundleSecurityError,
    build_model_bundle,
    build_publication_policy,
    load_model_bundle,
    verify_dual_crop_coverage,
)


class TestBundlePackaging(unittest.TestCase):
    def test_build_and_load_model_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            weights_file = base / "test_weights.safetensors"
            model = CPUClassifier("mobilenet_v3_small")
            model.save_weights(weights_file)

            # Fixtures de manifiestos
            train_m = base / "train.csv"; train_m.write_text("header\n", encoding="utf-8")
            val_m = base / "val.csv"; val_m.write_text("header\n", encoding="utf-8")
            test_m = base / "test.csv"; test_m.write_text("header\n", encoding="utf-8")

            bundle_file = base / "model_bundle.json"
            calib = {
                "POTATO_EARLY_BLIGHT": {"slope": 1.25, "intercept": -0.15}
            }
            class_map = {str(k): v for k, v in CLASS_MAPPING.items()}

            bundle_data = build_model_bundle(
                approved_by='fixture-reviewer-not-human-approval',
                g2_approval_id='FIXTURE-NOT-APPROVED',
                approved_at='2026-10-10T00:00:00Z',
                model_id="agrodiagnostico-mobilenetv3-cpu",
                model_version="1.0.0",
                dataset_version="2.0.0",
                architecture="mobilenet_v3_small",
                weights_path=weights_file,
                train_manifest_path=train_m,
                val_manifest_path=val_m,
                test_manifest_path=test_m,
                class_map=class_map,
                calibration_params=calib,
                output_bundle_path=bundle_file,
            )

            self.assertTrue(bundle_file.is_file())
            self.assertEqual(bundle_data["schema_version"], 1)

            # Carga independiente
            loaded_model, loaded_bundle = load_model_bundle(bundle_file)
            self.assertEqual(loaded_model.architecture, "mobilenet_v3_small")

            # Inferencia de prueba sobre vector de características
            features = [0.1] * 64
            idx, score, probs = loaded_model.predict(features)
            self.assertIsInstance(idx, int)
            self.assertGreaterEqual(score, 0.0)

    def test_tampered_weights_checksum_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            weights_file = base / "weights.safetensors"
            model = CPUClassifier("mobilenet_v3_small")
            model.save_weights(weights_file)

            train_m = base / "train.csv"; train_m.write_text("h\n", encoding="utf-8")
            val_m = base / "val.csv"; val_m.write_text("h\n", encoding="utf-8")
            test_m = base / "test.csv"; test_m.write_text("h\n", encoding="utf-8")
            bundle_file = base / "bundle.json"

            build_model_bundle(
                approved_by='fixture-reviewer-not-human-approval',
                g2_approval_id='FIXTURE-NOT-APPROVED',
                approved_at='2026-10-10T00:00:00Z',
                model_id="test-model",
                model_version="1.0.0",
                dataset_version="2.0.0",
                architecture="mobilenet_v3_small",
                weights_path=weights_file,
                train_manifest_path=train_m,
                val_manifest_path=val_m,
                test_manifest_path=test_m,
                class_map={str(k): v for k, v in CLASS_MAPPING.items()},
                calibration_params={},
                output_bundle_path=bundle_file,
            )

            # Modificar archivo de pesos después del empaquetado
            weights_file.write_text('{"tampered": true}', encoding="utf-8")

            with self.assertRaises(BundleIntegrityError):
                load_model_bundle(bundle_file)

    def test_path_traversal_in_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            bundle_file = base / "bad_bundle.json"
            bundle_data = {
                "schema_version": 1,
                "bundle_id": str(uuid.uuid4()),
                "model_id": "test-model",
                "model_version": "1.0.0",
                "dataset_version": "2.0.0",
                "architecture": "mobilenet_v3_small",
                "weights": {
                    "filename": "../../../etc/passwd",
                    "sha256": "0" * 64,
                    "format": "safetensors",
                    "size_bytes": 100,
                },
                "manifest_checksums": {
                    "train_manifest_sha256": "0" * 64,
                    "val_manifest_sha256": "0" * 64,
                    "test_manifest_sha256": "0" * 64,
                },
                "class_map": {str(k): v for k, v in CLASS_MAPPING.items()},
                "preprocessing": {"input_size": [224, 224], "channels": 3, "color_space": "RGB", "mean": [0.4, 0.4, 0.4], "std": [0.2, 0.2, 0.2]},
                "rejection_components": {"min_confidence_threshold": 0.6, "crop_detection_threshold": 0.8, "min_dimension": 200, "max_dimension": 6000},
                "calibration": {"method": "PLATT_SCALING", "parameters_per_class": {}},
                "runtime_environment": {"python_version": "3.12", "framework": "pytorch", "framework_version": "2.2.0", "target_device": "cpu"},
                "governance": {"g0_protocol_version": "1.0.0", "g2_approval_id": "G2-1", "approved_by": "Ronald Omar", "approved_at": "2026-10-10T12:00:00Z"},
            }
            bundle_file.write_text(json.dumps(bundle_data), encoding="utf-8")

            import jsonschema
            with self.assertRaises((BundleSecurityError, jsonschema.exceptions.ValidationError)):
                load_model_bundle(bundle_file)

    def test_build_publication_policy_schema_and_dual_crop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            policy_file = base / "publication_policy.json"

            approved = [
                {
                    "class_code": "POTATO_EARLY_BLIGHT",
                    "crop_code": "POTATO",
                    "min_confidence_threshold": 0.70,
                    "calibration_params": {"slope": 1.25, "intercept": -0.15},
                },
                {
                    "class_code": "MAIZE_COMMON_RUST",
                    "crop_code": "MAIZE",
                    "min_confidence_threshold": 0.65,
                    "calibration_params": {"slope": 1.15, "intercept": -0.12},
                },
            ]
            unsupported = [
                {"class_code": "POTATO_LATE_BLIGHT", "reason": "Soporte no evaluado en este release"}
            ]

            policy_data = build_publication_policy(
                approved_by='fixture-reviewer-not-human-approval',
                g2_approval_reference='FIXTURE-NOT-APPROVED',
                policy_id=str(uuid.uuid4()),
                policy_version="1.0.0",
                model_id="agrodiagnostico-mobilenetv3-cpu",
                model_version="1.0.0",
                dataset_version="2.0.0",
                bundle_digest="a" * 64,
                approved_classes=approved,
                unsupported_classes=unsupported,
                output_policy_path=policy_file,
            )

            self.assertTrue(policy_file.is_file())
            self.assertEqual(policy_data["schema_version"], 1)

            # Verificar regla de doble cultivo
            coverage = verify_dual_crop_coverage(approved)
            self.assertTrue(coverage["meets_closure_requirement"])
            self.assertTrue(coverage["has_potato"])
            self.assertTrue(coverage["has_maize"])

            # Si solo se incluye papa, no cumple requisito de cierre
            single_crop_coverage = verify_dual_crop_coverage([approved[0]])
            self.assertFalse(single_crop_coverage["meets_closure_requirement"])


if __name__ == "__main__":
    unittest.main()
