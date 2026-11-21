"""Pilot bundle contract and isolated loader checks with synthetic data only."""

import json
from pathlib import Path
import tempfile
import unittest

import jsonschema
import torch

from agro_ml.pilot_release import (SCHEMA, _groupnorm_model, combined_manifest_digest,
                                   load_pilot_bundle, synthetic_inference_check,
                                   validate_finite_state)


class PilotReleaseTests(unittest.TestCase):
    def test_manifest_pair_digest_requires_both_valid_components(self):
        pair = {"positives": "a" * 64, "negatives": "b" * 64}
        self.assertEqual(combined_manifest_digest(pair),
                         combined_manifest_digest({"negatives": "b" * 64,
                                                   "positives": "a" * 64}))
        with self.assertRaises(ValueError):
            combined_manifest_digest({"positives": "a" * 64})
        with self.assertRaises(ValueError):
            combined_manifest_digest({"positives": "a" * 64, "negatives": "not-a-hash"})

    def test_synthetic_load_only_has_two_publishable_diseases(self):
        model = _groupnorm_model(42)
        bundle = {"preprocessing": {"input_size": [224, 224],
                                    "mean": [.485, .456, .406],
                                    "std": [.229, .224, .225]},
                  "rejection_components": {"min_dimension": 200, "max_dimension": 6000,
                                           "min_confidence_threshold": .5},
                  "class_map": {"0": {"class_code": "POTATO_EARLY_BLIGHT"},
                                "1": {"class_code": "POTATO_LATE_BLIGHT"}},
                  "calibration": {"parameters_per_class": {
                      "POTATO_EARLY_BLIGHT": {"slope": 1.0, "intercept": 0.0},
                      "POTATO_LATE_BLIGHT": {"slope": 1.0, "intercept": 0.0}}}}
        result = synthetic_inference_check(model, bundle)
        self.assertEqual(result["published_class_map"],
                         ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"])
        self.assertIn(result["result"], result["published_class_map"] + ["NO_CONCLUYENTE"])

    def test_bundle_digest_mismatch_fails_before_loading_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model-bundle.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 de bundle"):
                load_pilot_bundle(path, "0" * 64)

    def test_nonfinite_or_empty_tensor_state_is_rejected(self):
        for state in ({}, {"x": torch.tensor([float("nan")])},
                      {"x": torch.tensor([float("inf")])}):
            with self.assertRaisesRegex(ValueError, "Pesos no finitos"):
                validate_finite_state(state)
        validate_finite_state({"x": torch.tensor([1.0, -1.0])})

    def test_pilot_contract_rejects_automatic_crop_threshold(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        value = {"governance": {"g0_protocol_version": "1.2.0"},
                 "rejection_components": {"crop_detection_threshold": .8}}
        # This sparse value has other schema errors too; inspect the specific
        # pilot conditional so it cannot silently regress to automatic crop.
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(value))
        self.assertTrue(any("rejection_components" in str(error.schema_path)
                            for error in errors))


if __name__ == "__main__":
    unittest.main()
