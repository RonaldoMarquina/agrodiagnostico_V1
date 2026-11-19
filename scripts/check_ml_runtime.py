#!/usr/bin/env python3
"""Mandatory CI stage: ml-contracts-and-runtime.

In accordance with ADR-0009 and Section 8 of Incremento 4:
- Zero GPU requirement: Strictly CPU-only.
- Validates ML contract schemas (model-bundle.v1.schema.json, publication-policy.v1.schema.json).
- Checks safe model loader integrity:
    * Tampered weights (checksum mismatch)
    * Path traversal attacks
    * Non-finite weights (NaN / Inf)
    * Missing or unapproved architecture
- Checks publication policy validation:
    * Missing governance / evidence
    * Non-finite calibration parameters
    * Out-of-bounds thresholds
- Runs CPU inference with an explicitly labeled tensor fixture (never credited as agronomic evidence).
- Runs ML unit and integration test suites.
- Clean execution from checkout without .env or private raw images.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
from typing import Any, Dict, Optional, Tuple
import unittest
import uuid
import zlib

# Ensure CPU-only environment
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["TORCH_DEVICE"] = "cpu"
os.environ["APP_ENV"] = "test"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml" / "src"))
sys.path.insert(0, str(ROOT / "services" / "ai_inference"))

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as ex:
    print(f"FAIL ml-contracts-and-runtime: Missing jsonschema: {ex}", file=sys.stderr)
    sys.exit(1)

from app.model_loader import (
    BundleIntegrityError,
    BundleSecurityError,
    BundleValidationError,
    check_finite_recursive,
    load_authorized_bundle,
    validate_weights_filename_security,
)
from app.inference_adapter import RealModelInferenceAdapter


def _create_minimal_png(width: int, height: int) -> bytes:
    """Generates a valid minimal PNG in pure Python without PIL dependency."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc

    raw_scanlines = b"\x00" + (b"\x00\x00\x00" * width)
    compressed = zlib.compress(raw_scanlines * height)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc

    iend_crc = struct.pack(">I", zlib.crc32(b"IEND"))
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc
    return signature + ihdr + idat + iend


def test_contracts():
    print("[1/5] Validating ML Contract Schemas...", flush=True)
    contracts_dir = ROOT / "contracts" / "ml"
    bundle_schema_path = contracts_dir / "model-bundle.v1.schema.json"
    policy_schema_path = contracts_dir / "publication-policy.v1.schema.json"

    assert bundle_schema_path.is_file(), f"Missing {bundle_schema_path}"
    assert policy_schema_path.is_file(), f"Missing {policy_schema_path}"

    bundle_schema = json.loads(bundle_schema_path.read_text(encoding="utf-8"))
    policy_schema = json.loads(policy_schema_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(bundle_schema)
    Draft202012Validator.check_schema(policy_schema)
    print("  ✓ model-bundle.v1.schema.json and publication-policy.v1.schema.json are valid Draft 2020-12 schemas.")


def _create_fixture_bundle(
    target_dir: Path,
    corrupt_weights: bool = False,
    make_nan: bool = False,
    invalid_arch: bool = False,
) -> tuple[Path, str]:
    """Creates a temporary, identified CPU tensor fixture bundle for testing."""
    weights_path = target_dir / "model_weights.safetensors"
    if make_nan:
        weights_data = {
            "weights": [[float("nan") if i == 0 and j == 0 else 0.05 * ((i * 3 + j) % 7 - 3) for j in range(7)] for i in range(64)],
            "bias": [2.5, 0.2, 0.15, 0.05, 0.1, 0.08, 0.02],
        }
    else:
        weights_data = {
            "weights": [[0.05 * ((i * 3 + j) % 7 - 3) for j in range(7)] for i in range(64)],
            "bias": [2.5, 0.2, 0.15, 0.05, 0.1, 0.08, 0.02],
        }

    weights_bytes = json.dumps(weights_data).encode("utf-8")
    weights_path.write_bytes(weights_bytes)

    if corrupt_weights:
        weights_sha = "0" * 64
    else:
        weights_sha = hashlib.sha256(weights_bytes).hexdigest()

    dummy_manifest_sha = hashlib.sha256(b"dummy_manifest").hexdigest()

    manifest = {
        "schema_version": 1,
        "bundle_id": str(uuid.uuid4()),
        "model_id": "ci-fixture-cpu",
        "model_version": "1.0.0-ci",
        "dataset_version": "2.0.0-ci",
        "architecture": "unapproved_super_net" if invalid_arch else "mobilenet_v3_small",
        "weights": {
            "filename": "model_weights.safetensors",
            "sha256": weights_sha,
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
            "g2_approval_id": "CI-FIXTURE-EVAL-001",
            "approved_by": "CI System",
            "approved_at": "2026-10-15T12:00:00Z",
        },
    }

    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_path = target_dir / "bundle.json"
    manifest_path.write_bytes(manifest_bytes)
    bundle_digest = hashlib.sha256(manifest_bytes).hexdigest()
    return manifest_path, bundle_digest


def test_bundle_loader_and_rejections():
    print("[2/5] Testing Model Loader Integrity & Security...", flush=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Valid bundle load
        valid_dir = tmp_path / "valid"
        valid_dir.mkdir()
        manifest_path, _ = _create_fixture_bundle(valid_dir)
        meta, weights = load_authorized_bundle(manifest_path)
        assert meta["model_id"] == "ci-fixture-cpu"
        assert "weights" in weights
        print("  ✓ Valid CPU fixture bundle loaded successfully.")

        # 2. Corrupt weights rejection (checksum mismatch)
        corrupt_dir = tmp_path / "corrupt"
        corrupt_dir.mkdir()
        manifest_corrupt, _ = _create_fixture_bundle(corrupt_dir, corrupt_weights=True)
        try:
            load_authorized_bundle(manifest_corrupt)
            raise AssertionError("Failed to reject corrupt bundle!")
        except BundleIntegrityError:
            print("  ✓ Correctly rejected bundle with tampered weights digest.")

        # 3. Path traversal attack rejection
        try:
            validate_weights_filename_security("../../etc/passwd")
            raise AssertionError("Failed to reject path traversal in weights path!")
        except BundleSecurityError:
            print("  ✓ Correctly rejected path traversal attempt.")

        # 4. Non-finite weights rejection (NaN / Inf)
        nan_dir = tmp_path / "nan"
        nan_dir.mkdir()
        manifest_nan, _ = _create_fixture_bundle(nan_dir, make_nan=True)
        try:
            load_authorized_bundle(manifest_nan)
            raise AssertionError("Failed to reject non-finite weights!")
        except BundleValidationError as ex:
            assert "finito" in str(ex).lower() or "nan" in str(ex).lower()
            print("  ✓ Correctly rejected non-finite (NaN) weights.")

        # 5. Unapproved architecture rejection
        arch_dir = tmp_path / "arch"
        arch_dir.mkdir()
        manifest_arch, _ = _create_fixture_bundle(arch_dir, invalid_arch=True)
        try:
            load_authorized_bundle(manifest_arch)
            raise AssertionError("Failed to reject unapproved architecture!")
        except BundleValidationError as ex:
            assert "unapproved_super_net" in str(ex) or "not one of" in str(ex).lower() or "arquitectura no autorizada" in str(ex).lower()
            print("  ✓ Correctly rejected unapproved architecture.")


def _validate_policy_payload(payload: dict) -> tuple[bool, Optional[str]]:
    schema_path = ROOT / "contracts" / "ml" / "publication-policy.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(payload))
    if errors:
        return False, f"SCHEMA_VALIDATION_FAILED: {errors[0].message}"

    governance = payload.get("governance", {})
    if not governance.get("g2_approval_reference") or not str(governance["g2_approval_reference"]).strip():
        return False, "EVIDENCE_MISSING: g2_approval_reference is mandatory"

    for cls_item in payload.get("approved_classes", []):
        min_conf = cls_item.get("min_confidence_threshold")
        if not (isinstance(min_conf, (int, float)) and math.isfinite(min_conf) and 0.0 <= min_conf <= 1.0):
            return False, "INVALID_THRESHOLD"
        cal = cls_item.get("calibration_params", {})
        slope = cal.get("slope")
        intercept = cal.get("intercept")
        if not (isinstance(slope, (int, float)) and math.isfinite(slope)):
            return False, "NON_FINITE_CALIBRATION_PARAMS"
        if not (isinstance(intercept, (int, float)) and math.isfinite(intercept)):
            return False, "NON_FINITE_CALIBRATION_PARAMS"
    return True, None


def test_policy_rejections():
    print("[3/5] Testing Publication Policy Validation & Rejections...", flush=True)
    base_policy = {
        "schema_version": 1,
        "policy_id": "55555555-5555-4555-8555-555555555555",
        "policy_version": "1.0.0",
        "target_model": {
            "model_id": "ci-fixture-cpu",
            "model_version": "1.0.0-ci",
            "dataset_version": "2.0.0-ci",
            "bundle_digest": "a" * 64,
        },
        "approved_classes": [
            {
                "class_code": "POTATO_EARLY_BLIGHT",
                "crop_code": "POTATO",
                "min_confidence_threshold": 0.85,
                "calibration_params": {"slope": 2.5, "intercept": -1.0},
            }
        ],
        "unsupported_classes": [],
        "catalog_requirements": {"require_reviewed_catalog": True},
        "governance": {
            "g0_protocol_version": "1.0.0",
            "g2_approval_reference": "G2-REF-001",
            "approved_by": "Dr. Testing",
            "approved_at": "2026-10-15T12:00:00Z",
        },
        "audit": {"imported_by": "ci-agent", "imported_at": "2026-10-15T12:00:00Z"},
    }

    ok, err = _validate_policy_payload(base_policy)
    assert ok, f"Base policy must be valid: {err}"

    # Missing G2 governance
    corrupt_gov = dict(base_policy)
    corrupt_gov["governance"] = dict(base_policy["governance"])
    del corrupt_gov["governance"]["g2_approval_reference"]
    ok, err = _validate_policy_payload(corrupt_gov)
    assert not ok, "Must reject policy missing g2_approval_reference"
    print("  ✓ Correctly rejected policy missing G2 governance evidence.")

    # Non-finite calibration parameter (slope = NaN)
    corrupt_cal = dict(base_policy)
    corrupt_cal["approved_classes"] = [
        {
            "class_code": "POTATO_EARLY_BLIGHT",
            "crop_code": "POTATO",
            "min_confidence_threshold": 0.85,
            "calibration_params": {"slope": float("nan"), "intercept": -1.0},
        }
    ]
    ok, err = _validate_policy_payload(corrupt_cal)
    assert not ok, "Must reject policy with NaN slope"
    print("  ✓ Correctly rejected policy with non-finite calibration parameters.")

    # Threshold > 1.0
    corrupt_thresh = dict(base_policy)
    corrupt_thresh["approved_classes"] = [
        {
            "class_code": "POTATO_EARLY_BLIGHT",
            "crop_code": "POTATO",
            "min_confidence_threshold": 1.5,
            "calibration_params": {"slope": 2.5, "intercept": -1.0},
        }
    ]
    ok, err = _validate_policy_payload(corrupt_thresh)
    assert not ok, "Must reject threshold > 1.0"
    print("  ✓ Correctly rejected out-of-bounds publication threshold.")


def test_cpu_runtime_inference():
    print("[4/5] Testing Real-Mode CPU Runtime Adapter with Fixture...", flush=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        valid_dir = Path(tmp_dir) / "valid"
        valid_dir.mkdir()
        manifest_path, _ = _create_fixture_bundle(valid_dir)

        meta, weights = load_authorized_bundle(manifest_path)
        adapter = RealModelInferenceAdapter(bundle_data=meta, weights_data=weights)

        # Generate minimal valid PNG
        png_bytes = _create_minimal_png(224, 224)
        res = adapter.run_inference(diagnosis_id=uuid.uuid4(), image_bytes=png_bytes)

        assert res["outcome"] in ("PREDICTION", "ABSTENTION"), f"Unexpected outcome: {res['outcome']}"
        assert res["model_id"] == "ci-fixture-cpu"
        assert res["model_version"] == "1.0.0-ci"
        assert res["dataset_version"] == "2.0.0-ci"
        assert res["inference_ms"] is not None and res["inference_ms"] >= 0
        if res["outcome"] == "PREDICTION":
            assert res["class_code"] is not None
            assert res["raw_score"] is not None and 0.0 <= res["raw_score"] <= 1.0

        print(f"  ✓ CPU inference executed in {res['inference_ms']}ms with outcome={res['outcome']}.")


def test_unit_suites():
    print("[5/5] Executing Isolated Test Suites...", flush=True)
    loader = unittest.TestLoader()

    # 1. tests/ml
    suite_ml = loader.discover(str(ROOT / "tests" / "ml"), pattern="test_*.py")
    assert suite_ml.countTestCases() > 0, "No ML tests found!"
    res_ml = unittest.TextTestRunner(verbosity=1).run(suite_ml)
    assert res_ml.wasSuccessful(), f"tests/ml suite failed with {len(res_ml.errors)} errors, {len(res_ml.failures)} failures"

    # 2. ai_inference adapter tests
    import importlib.util
    adapter_test_path = ROOT / "services" / "ai_inference" / "tests" / "test_model_adapter.py"
    spec = importlib.util.spec_from_file_location("test_model_adapter", adapter_test_path)
    assert spec is not None and spec.loader is not None, f"Could not load spec for {adapter_test_path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    suite_inf = loader.loadTestsFromModule(mod)
    assert suite_inf.countTestCases() > 0, "No ai_inference model adapter tests found!"
    res_inf = unittest.TextTestRunner(verbosity=1).run(suite_inf)
    assert res_inf.wasSuccessful(), f"ai_inference test_model_adapter failed"

    print("  ✓ All isolated unit suites passed.")


def main():
    print("=================================================================")
    print("Starting CI Stage: ml-contracts-and-runtime")
    print("=================================================================")
    test_contracts()
    test_bundle_loader_and_rejections()
    test_policy_rejections()
    test_cpu_runtime_inference()
    test_unit_suites()
    print("=================================================================")
    print("PASS: ml-contracts-and-runtime completed successfully.")
    print("=================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
