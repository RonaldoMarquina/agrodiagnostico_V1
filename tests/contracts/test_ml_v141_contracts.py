from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
HEX = "a" * 64


def bundle():
    return {
        "schema_version": 1, "bundle_id": "11111111-1111-4111-8111-111111111111",
        "model_id": "potato-v141", "model_version": "1.4.1", "dataset_version": "1.4.1",
        "architecture": "mobilenet_v3_small",
        "weights": {"filename": "weights.safetensors", "sha256": HEX,
                    "format": "safetensors", "size_bytes": 2048},
        "manifest_checksums": {"train_manifest_sha256": HEX, "val_manifest_sha256": HEX},
        "artifact_checksums": {key: HEX for key in ("config_sha256", "calibration_sha256",
            "thresholds_sha256", "protocol_sha256", "freeze_sha256", "val_report_sha256",
            "preprocessing_code_sha256", "dependency_lock_sha256")},
        "class_map": {
            "0": {"class_code": "POTATO_EARLY_BLIGHT", "crop_code": "POTATO"},
            "1": {"class_code": "POTATO_LATE_BLIGHT", "crop_code": "POTATO"},
            "2": {"class_code": "POTATO_HEALTHY", "crop_code": "POTATO"},
            "3": {"class_code": "OTHER_CROP", "crop_code": "OTHER"},
        },
        "publishable_classes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"],
        "preprocessing": {"input_size": [224, 224], "channels": 3, "color_space": "RGB",
                          "mean": [.485, .456, .406], "std": [.229, .224, .225]},
        "rejection_components": {"min_confidence_threshold": .5, "identified_crop_required": "POTATO",
            "technical_reject_policy": "NON_PUBLISHABLE_ARGMAX_OR_LOW_CONFIDENCE",
            "min_dimension": 200, "max_dimension": 6000},
        "calibration": {"method": "TEMPERATURE_SCALING", "parameters_per_class": {
            code: {"slope": 1, "intercept": 0} for code in
            ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT", "POTATO_HEALTHY", "OTHER_CROP")}},
        "runtime_environment": {"python_version": "3.12.3", "framework": "pytorch",
                                "framework_version": "2.5", "target_device": "cpu"},
        "governance": {"g0_protocol_version": "1.4.1", "release_status": "PRE_EXTERNAL_FROZEN"},
    }


class V141ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads((ROOT / "contracts/ml/model-bundle.v1.schema.json").read_text())
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        policy = json.loads((ROOT / "contracts/ml/publication-policy.v1.schema.json").read_text())
        cls.policy_validator = Draft202012Validator(policy, format_checker=FormatChecker())

    def test_exact_four_class_bundle_is_valid(self):
        self.assertEqual([], list(self.validator.iter_errors(bundle())))

    def test_incomplete_duplicate_or_publishable_reject_map_fails(self):
        candidates = []
        changed = deepcopy(bundle()); del changed["class_map"]["3"]; candidates.append(changed)
        changed = deepcopy(bundle()); changed["class_map"]["3"] = changed["class_map"]["2"]; candidates.append(changed)
        changed = deepcopy(bundle()); changed["publishable_classes"] = ["POTATO_EARLY_BLIGHT", "POTATO_HEALTHY"]; candidates.append(changed)
        for candidate in candidates:
            self.assertTrue(list(self.validator.iter_errors(candidate)))

    def test_v141_policy_cannot_publish_rejection_classes(self):
        base = {
            "schema_version": 1, "policy_id": "22222222-2222-4222-8222-222222222222",
            "policy_version": "1.4.1", "target_model": {"model_id": "potato-v141",
                "model_version": "1.4.1", "dataset_version": "1.4.1", "bundle_digest": HEX},
            "approved_classes": [{"class_code": "POTATO_EARLY_BLIGHT", "crop_code": "POTATO",
                "min_confidence_threshold": .5, "calibration_params": {"slope": 1, "intercept": 0}}],
            "unsupported_classes": [{"class_code": "POTATO_HEALTHY", "reason": "technical rejection"},
                                    {"class_code": "OTHER_CROP", "reason": "technical rejection"}],
            "catalog_requirements": {"require_reviewed_catalog": True},
            "governance": {"g0_protocol_version": "1.4.1", "g2_approval_reference": "pending",
                           "approved_by": "project-owner", "approved_at": "2026-11-23T00:00:00-05:00"},
            "audit": {"imported_by": "test", "imported_at": "2026-11-23T00:00:00-05:00"},
        }
        self.assertEqual([], list(self.policy_validator.iter_errors(base)))
        changed = deepcopy(base); changed["approved_classes"][0]["class_code"] = "POTATO_HEALTHY"
        self.assertTrue(list(self.policy_validator.iter_errors(changed)))


if __name__ == "__main__":
    unittest.main()
