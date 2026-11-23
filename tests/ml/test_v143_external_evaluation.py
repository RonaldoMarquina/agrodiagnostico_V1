from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agro_ml.v143_external_evaluation import (
    FREEZE_DIGEST,
    V143ExternalEvaluationError,
    build_report,
    create_access_record,
    g2_decision,
    validate_frozen_inputs,
    validate_image_catalog,
    visible_prediction,
)


def boundary_predictions() -> list[dict]:
    rows: list[dict] = []
    for code, correct in (("POTATO_EARLY_BLIGHT", 38), ("POTATO_LATE_BLIGHT", 38)):
        for index in range(50):
            published = code if index < correct else None
            rows.append({"stratum_code": code, "published_diagnosis": published,
                         "final_state": "COMPLETADO" if published else "NO_CONCLUYENTE",
                         "inference_ms": 1.0, "end_to_end_ms": 2.0})
    for index in range(50):
        published = "POTATO_EARLY_BLIGHT" if index < 5 else None
        rows.append({"stratum_code": "POTATO_HEALTHY", "published_diagnosis": published,
                     "final_state": "COMPLETADO" if published else "NO_CONCLUYENTE",
                     "inference_ms": 1.0, "end_to_end_ms": 2.0})
    for index in range(200):
        published = "POTATO_LATE_BLIGHT" if index < 10 else None
        rows.append({"stratum_code": "OTHER_CROP", "published_diagnosis": published,
                     "final_state": "COMPLETADO" if published else "NO_CONCLUYENTE",
                     "inference_ms": 1.0, "end_to_end_ms": 2.0})
    return rows


class V143ExternalEvaluationTests(unittest.TestCase):
    def test_frozen_contract_preserves_parameters_and_class_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "class-map.json").write_text(json.dumps({
                "technical_classes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT",
                                      "POTATO_HEALTHY", "OTHER_CROP"],
                "publishable_classes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"],
                "rejection_classes": ["POTATO_HEALTHY", "OTHER_CROP"]}))
            (root / "calibration.json").write_text(json.dumps({"external_used": False,
                "method": "TEMPERATURE_SCALING", "selected_on": "VAL", "temperature": .5}))
            (root / "thresholds.json").write_text(json.dumps({"external_used": False,
                "selected_on": "VAL", "min_confidence": .8}))
            contract = root / "contract.json"
            contract.write_text(json.dumps({"preprocessing_version": "1.4.3",
                "frozen_model_parameters": {"freeze_digest": FREEZE_DIGEST,
                    "weights_sha256": "e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c",
                    "temperature": .5, "threshold": .8,
                    "technical_classes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT",
                                          "POTATO_HEALTHY", "OTHER_CROP"],
                    "publishable_classes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"]}}))
            freeze = {"freeze_digest": FREEZE_DIGEST, "temperature": .5, "threshold": .8,
                      "file_sha256": {"weights.safetensors":
                          "e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c"}}
            digest = hashlib.sha256(contract.read_bytes()).hexdigest()
            with patch("agro_ml.v143_external_evaluation.verify_freeze", return_value=freeze), \
                    patch("agro_ml.v143_external_evaluation.CONTRACT_SHA256", digest):
                _, spec = validate_frozen_inputs(root, contract)
                self.assertEqual((224, 224), (spec.width, spec.height))
                changed = dict(freeze); changed["threshold"] = .81
                with patch("agro_ml.v143_external_evaluation.verify_freeze", return_value=changed), \
                        self.assertRaises(V143ExternalEvaluationError):
                    validate_frozen_inputs(root, contract)

    def test_catalog_rejects_missing_extra_mutated_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = root / "files"; files.mkdir()
            image = files / "a.jpg"; image.write_bytes(b"fixture")
            row = {"source_path": "files/a.jpg", "file_size": 7,
                   "sha256": hashlib.sha256(b"fixture").hexdigest()}
            self.assertEqual(1, len(validate_image_catalog([row], root)))
            (files / "extra.jpg").write_bytes(b"extra")
            with self.assertRaisesRegex(V143ExternalEvaluationError, "extra"):
                validate_image_catalog([row], root)
            (files / "extra.jpg").unlink(); image.write_bytes(b"changed")
            with self.assertRaisesRegex(V143ExternalEvaluationError, "SHA-256"):
                validate_image_catalog([row], root)
            image.unlink()
            with self.assertRaisesRegex(V143ExternalEvaluationError, "ausente"):
                validate_image_catalog([row], root)
            with self.assertRaisesRegex(V143ExternalEvaluationError, "inseguro"):
                validate_image_catalog([{**row, "source_path": "../a.jpg"}], root)

    def test_access_record_is_exclusive_and_first_record_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "once"
            first = create_access_record(output, {"seal": "a" * 64},
                                         started_at="2026-11-23T00:00:00Z")
            before = (output / "access.json").read_bytes()
            self.assertEqual("STARTED", first["status"])
            with self.assertRaises(V143ExternalEvaluationError):
                create_access_record(output, {})
            self.assertEqual(before, (output / "access.json").read_bytes())

    def test_visible_mapping_metrics_boundaries_and_g2(self):
        self.assertEqual("POTATO_EARLY_BLIGHT", visible_prediction([10, 0, 0, 0])[1])
        self.assertEqual("POTATO_LATE_BLIGHT", visible_prediction([0, 10, 0, 0])[1])
        self.assertIsNone(visible_prediction([0, 0, 10, 0])[1])
        self.assertIsNone(visible_prediction([0, 0, 0, 10])[1])
        self.assertIsNone(visible_prediction([1, 1, 1, 1])[1])
        report = build_report(boundary_predictions(), input_hashes={},
                              predictions_sha256="a" * 64, peak_rss_mb=100)
        self.assertTrue(report["all_criteria_passed"])
        self.assertEqual(38, report["per_class"]["POTATO_EARLY_BLIGHT"]["tp"])
        self.assertEqual(12, report["per_class"]["POTATO_EARLY_BLIGHT"]["fn"])
        self.assertEqual(45, report["healthy_no_concluyente"]["numerator"])
        self.assertEqual(10, report["other_crop_false_publication"]["numerator"])
        decision = g2_decision(report, report_sha256="b" * 64,
                               predictions_sha256="a" * 64)
        self.assertEqual("CLOSED_APPROVED_BY_PROJECT_OWNER", decision["status"])
        self.assertEqual("INACTIVE_NOT_AUTHORIZED", decision["worker_status"])
        failed = boundary_predictions()
        failed[37]["published_diagnosis"] = None
        failed[37]["final_state"] = "NO_CONCLUYENTE"
        failed_report = build_report(failed, input_hashes={}, predictions_sha256="a" * 64,
                                     peak_rss_mb=100)
        self.assertFalse(failed_report["criteria"]["early_recall"])
        self.assertEqual("OPEN_EXTERNAL_CRITERIA_FAILED",
                         g2_decision(failed_report, report_sha256="b" * 64,
                                     predictions_sha256="a" * 64)["status"])

    def test_incomplete_denominators_are_rejected(self):
        with self.assertRaisesRegex(V143ExternalEvaluationError, "incompletas"):
            build_report(boundary_predictions()[:-1], input_hashes={},
                         predictions_sha256="a" * 64, peak_rss_mb=100)


if __name__ == "__main__":
    unittest.main()
