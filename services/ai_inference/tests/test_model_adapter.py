"""Pruebas unitarias para el cargador seguro de bundles y el adaptador de inferencia real (Tarea 6.1)."""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
import uuid

from app.inference_adapter import RealModelInferenceAdapter, SimulatedInferenceAdapter, extract_image_meta
from app.model_loader import (
    BundleIntegrityError,
    BundleSecurityError,
    BundleValidationError,
    check_finite_recursive,
    load_authorized_bundle,
    validate_weights_filename_security,
)


def _create_minimal_png(width: int, height: int) -> bytes:
    """Crea una estructura de bytes PNG mínima válida con las dimensiones especificadas."""
    import struct
    import zlib
    signature = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: width, height, bit_depth=8, color_type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc

    # Minimal scanlines (all 0)
    raw_scanlines = b"\x00" + (b"\x00\x00\x00" * width)
    compressed = zlib.compress(raw_scanlines * height)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc

    # IEND chunk
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND"))
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc

    return signature + ihdr + idat + iend


class TestModelLoaderAndAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp_dir.name)

        # Crear fixture de pesos CPU deterministas válidos
        self.weights_data = {
            "weights": [[0.05 * ((i * 3 + j) % 7 - 3) for j in range(7)] for i in range(64)],
            "bias": [2.5, 0.2, 0.15, 0.05, 0.1, 0.08, 0.02],
        }
        self.weights_file = self.base_dir / "model_weights.safetensors"
        weights_bytes = json.dumps(self.weights_data).encode("utf-8")
        self.weights_file.write_bytes(weights_bytes)

        self.weights_sha256 = hashlib.sha256(weights_bytes).hexdigest()

        # Dummy manifests
        dummy_manifest = self.base_dir / "manifest.csv"
        dummy_manifest.write_text("dummy", encoding="utf-8")
        dummy_manifest_sha = hashlib.sha256(b"dummy").hexdigest()

        # Bundle JSON válido
        self.bundle_data = {
            "schema_version": 1,
            "bundle_id": str(uuid.uuid4()),
            "model_id": "agrodiagnostico-mobilenetv3-cpu",
            "model_version": "1.0.0",
            "dataset_version": "2.0.0",
            "architecture": "mobilenet_v3_small",
            "weights": {
                "filename": "model_weights.safetensors",
                "sha256": self.weights_sha256,
                "format": "safetensors",
                "size_bytes": len(weights_bytes),
            },
            "manifest_checksums": {
                "train_manifest_sha256": dummy_manifest_sha,
                "val_manifest_sha256": dummy_manifest_sha,
                "test_manifest_sha256": dummy_manifest_sha,
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
                "parameters_per_class": {
                    "POTATO_EARLY_BLIGHT": {"slope": 1.25, "intercept": -0.15}
                },
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

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_bundle_loader_valid(self):
        """Carga exitosa de bundle válido y comprobación de SHA-256."""
        bundle, weights = load_authorized_bundle(self.bundle_file)
        self.assertEqual(bundle["model_id"], "agrodiagnostico-mobilenetv3-cpu")
        self.assertIn("weights", weights)
        self.assertEqual(len(weights["weights"]), 64)

    def test_bundle_loader_checksum_mismatch(self):
        """Fallo por alteración de bytes de pesos (BundleIntegrityError)."""
        # Modificar archivo de pesos en disco
        self.weights_file.write_bytes(b'{"weights": [1, 2, 3]}')
        with self.assertRaises(BundleIntegrityError):
            load_authorized_bundle(self.bundle_file)

    def test_bundle_loader_path_traversal(self):
        """Rechazo estricto de Path Traversal en nombre de archivo de pesos."""
        with self.assertRaises(BundleSecurityError):
            validate_weights_filename_security("../../etc/shadow.pt")

        with self.assertRaises(BundleSecurityError):
            validate_weights_filename_security("/root/weights.safetensors")

        with self.assertRaises(BundleSecurityError):
            validate_weights_filename_security("weights.exe")

    def test_bundle_loader_non_finite_tensors(self):
        """Rechazo estricto de pesos con valores no finitos (NaN / Inf)."""
        weights_with_nan = {"weights": [1.0, float("nan")]}
        with self.assertRaises(BundleValidationError):
            check_finite_recursive(weights_with_nan)

        weights_with_inf = {"weights": [1.0, float("inf")]}
        with self.assertRaises(BundleValidationError):
            check_finite_recursive(weights_with_inf)

    def test_bundle_loader_missing_weights(self):
        """Fallo si el archivo de pesos no existe."""
        self.weights_file.unlink()
        with self.assertRaises(FileNotFoundError):
            load_authorized_bundle(self.bundle_file)

    def test_inference_adapter_prediction(self):
        """Inferencia real produce PREDICTION válida con metadatos reales y tiempo medido."""
        adapter = RealModelInferenceAdapter.from_bundle_file(self.bundle_file)
        valid_img = _create_minimal_png(250, 250)
        res = adapter.run_inference(uuid.uuid4(), valid_img)

        self.assertEqual(res["outcome"], "PREDICTION")
        self.assertIn(res["crop_code"], ("POTATO", "MAIZE"))
        self.assertIsNotNone(res["class_code"])
        self.assertGreater(res["raw_score"], 0.0)
        self.assertEqual(res["model_id"], "agrodiagnostico-mobilenetv3-cpu")
        self.assertEqual(res["model_version"], "1.0.0")
        self.assertEqual(res["dataset_version"], "2.0.0")
        self.assertIsInstance(res["inference_ms"], int)
        self.assertGreaterEqual(res["inference_ms"], 1)
        self.assertIsNone(res["reason_code"])

    def test_inference_adapter_bad_image_pre_rejection(self):
        """Rechazo previo a ejecutar modelo produce ABSTENTION con BAD_IMAGE y metadatos NULL."""
        adapter = RealModelInferenceAdapter.from_bundle_file(self.bundle_file)

        # 1. Bytes corruptos
        res1 = adapter.run_inference(uuid.uuid4(), b"not_an_image_corrupt")
        self.assertEqual(res1["outcome"], "ABSTENTION")
        self.assertEqual(res1["reason_code"], "BAD_IMAGE")
        self.assertIsNone(res1["model_id"])
        self.assertIsNone(res1["model_version"])
        self.assertIsNone(res1["dataset_version"])
        self.assertIsNone(res1["inference_ms"])
        self.assertIsNone(res1["crop_code"])

        # 2. Dimensión visual insuficiente (100x100 < min_dim 200)
        small_img = _create_minimal_png(100, 100)
        res2 = adapter.run_inference(uuid.uuid4(), small_img)
        self.assertEqual(res2["outcome"], "ABSTENTION")
        self.assertEqual(res2["reason_code"], "BAD_IMAGE")
        self.assertIsNone(res2["model_id"])
        self.assertIsNone(res2["inference_ms"])

    def test_inference_adapter_low_confidence(self):
        """Umbral técnico bajo produce ABSTENTION con LOW_CONFIDENCE y metadatos reales."""
        # Forzar umbral alto (0.999) para gatillar LOW_CONFIDENCE
        self.bundle_data["rejection_components"]["min_confidence_threshold"] = 0.999
        self.bundle_file.write_text(json.dumps(self.bundle_data), encoding="utf-8")

        adapter = RealModelInferenceAdapter.from_bundle_file(self.bundle_file)
        valid_img = _create_minimal_png(300, 300)
        res = adapter.run_inference(uuid.uuid4(), valid_img)

        self.assertEqual(res["outcome"], "ABSTENTION")
        self.assertEqual(res["reason_code"], "LOW_CONFIDENCE")
        self.assertIn(res["crop_code"], ("POTATO", "MAIZE"))
        self.assertIsNone(res["class_code"])
        self.assertIsNone(res["raw_score"])
        # Metadatos poblados porque el modelo sí se ejecutó
        self.assertEqual(res["model_id"], "agrodiagnostico-mobilenetv3-cpu")
        self.assertIsNotNone(res["inference_ms"])

    def test_inference_adapter_hierarchical_unsupported_crop(self):
        """Modelo jerárquico rechaza cultivo fuera de dominio con UNSUPPORTED_CROP."""
        hierarchical_bundle = dict(self.bundle_data)
        hierarchical_bundle["model_id"] = "agrodiagnostico-resnet18-cpu"
        hierarchical_bundle["architecture"] = "resnet18"
        hierarchical_bundle["weights"]["filename"] = "hierarchical_weights.safetensors"

        # Pesos jerárquicos donde la clase OOD (índice 2) tiene un sesgo alto para forzar OOD
        h_weights = {
            "weights_data": {
                "crop_weights": [[0.0] * 3 for _ in range(64)],
                "crop_bias": [0.0, 0.0, 5.0],  # OOD domina con softmax
                "potato_weights": [[0.0] * 3 for _ in range(64)],
                "potato_bias": [0.0] * 3,
                "maize_weights": [[0.0] * 4 for _ in range(64)],
                "maize_bias": [0.0] * 4,
            }
        }
        h_bytes = json.dumps(h_weights).encode("utf-8")
        h_weights_file = self.base_dir / "hierarchical_weights.safetensors"
        h_weights_file.write_bytes(h_bytes)
        hierarchical_bundle["weights"]["sha256"] = hashlib.sha256(h_bytes).hexdigest()
        hierarchical_bundle["weights"]["size_bytes"] = len(h_bytes)

        h_bundle_file = self.base_dir / "hierarchical_bundle.json"
        h_bundle_file.write_text(json.dumps(hierarchical_bundle), encoding="utf-8")

        adapter = RealModelInferenceAdapter.from_bundle_file(h_bundle_file)
        valid_img = _create_minimal_png(300, 300)
        res = adapter.run_inference(uuid.uuid4(), valid_img)

        self.assertEqual(res["outcome"], "ABSTENTION")
        self.assertEqual(res["reason_code"], "UNSUPPORTED_CROP")
        self.assertIsNone(res["crop_code"])
        self.assertIsNone(res["class_code"])
        self.assertEqual(res["model_id"], "agrodiagnostico-resnet18-cpu")
        self.assertIsNotNone(res["inference_ms"])


if __name__ == "__main__":
    unittest.main()
