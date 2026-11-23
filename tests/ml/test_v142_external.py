from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from agro_ml.v142_external import (
    FREEZE_DIGEST, V142ExternalError, build_report, create_access_record,
    g2_decision, validate_frozen_contract, validate_zip_catalog, visible_prediction,
)


def boundary_predictions():
    rows = []
    for index in range(42):
        published = "POTATO_EARLY_BLIGHT" if index < 32 else None
        rows.append({"stratum_code": "POTATO_EARLY_BLIGHT", "published_diagnosis": published,
                     "final_state": "COMPLETADO" if published else "NO_CONCLUYENTE",
                     "inference_ms": 1.0, "end_to_end_ms": 2.0})
    for index in range(76):
        published = "POTATO_LATE_BLIGHT" if index < 57 else None
        rows.append({"stratum_code": "POTATO_LATE_BLIGHT", "published_diagnosis": published,
                     "final_state": "COMPLETADO" if published else "NO_CONCLUYENTE",
                     "inference_ms": 1.0, "end_to_end_ms": 2.0})
    for index in range(50):
        published = "POTATO_EARLY_BLIGHT" if index < 5 else None
        rows.append({"stratum_code": "POTATO_HEALTHY", "published_diagnosis": published,
                     "final_state": "COMPLETADO" if published else "NO_CONCLUYENTE",
                     "inference_ms": 1.0, "end_to_end_ms": 2.0})
    for index in range(194):
        published = "POTATO_LATE_BLIGHT" if index < 9 else None
        rows.append({"stratum_code": "OTHER_CROP", "published_diagnosis": published,
                     "final_state": "COMPLETADO" if published else "NO_CONCLUYENTE",
                     "inference_ms": 1.0, "end_to_end_ms": 2.0})
    return rows


class V142ExternalTests(unittest.TestCase):
    def test_frozen_contract_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "class-map.json").write_text(json.dumps({
                "technical_classes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT", "POTATO_HEALTHY", "OTHER_CROP"],
                "publishable_classes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"]}))
            (root / "calibration.json").write_text(json.dumps({"external_used": False,
                "method": "TEMPERATURE_SCALING", "selected_on": "VAL", "temperature": .5}))
            (root / "thresholds.json").write_text(json.dumps({"external_used": False,
                "selected_on": "VAL", "min_confidence": .8}))
            (root / "preprocessing.json").write_text(json.dumps({"preprocessing_version": "1.4.2",
                "shared_by": ["TRAIN", "VAL", "INFERENCE"],
                "decode": {"color_space": "RGB", "exif_transpose": True},
                "resize": {"method": "DIRECT_RESIZE", "width": 224, "height": 224,
                           "interpolation": "BILINEAR"},
                "tensor": {"mean": [.485, .456, .406], "std": [.229, .224, .225]}}))
            freeze = {"freeze_digest": FREEZE_DIGEST, "temperature": .5, "threshold": .8,
                      "file_sha256": {"weights.safetensors":
                          "e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c"}}
            with patch("agro_ml.v142_external.verify_freeze", return_value=freeze):
                _, spec = validate_frozen_contract(root)
                self.assertEqual((224, 224), (spec.width, spec.height))
                changed = dict(freeze); changed["threshold"] = .81
                with patch("agro_ml.v142_external.verify_freeze", return_value=changed), \
                        self.assertRaises(V142ExternalError):
                    validate_frozen_contract(root)

    def test_access_is_exclusive_and_preserves_first_record(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "once"
            first = create_access_record(output, {"freeze": FREEZE_DIGEST},
                                         started_at="2026-11-23T00:00:00Z")
            before = (output / "access.json").read_bytes()
            self.assertEqual("STARTED", first["status"])
            with self.assertRaises(V142ExternalError):
                create_access_record(output, {})
            self.assertEqual(before, (output / "access.json").read_bytes())

    def test_zip_catalog_checks_paths_sizes_hash_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "sikkim.zip"
            content = b"image fixture"
            name = "Sikkim Solanaceae Leaf Image Dataset/Potato_Field_Dataset/a.jpg"
            with zipfile.ZipFile(archive, "w") as target:
                target.writestr(name, content)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            row = {"source_path": "Potato_Field_Dataset/a.jpg", "file_size": len(content)}
            catalog = validate_zip_catalog([row], archive, expected_size=archive.stat().st_size,
                                           expected_sha256=digest)
            self.assertEqual([name], list(catalog))
            for rows in ([{**row, "source_path": "../a.jpg"}], [row, row],
                         [{**row, "file_size": 1}]):
                with self.subTest(rows=rows), self.assertRaises(V142ExternalError):
                    validate_zip_catalog(rows, archive, expected_size=archive.stat().st_size,
                                         expected_sha256=digest)

    def test_visible_mapping_and_boundary_metrics(self):
        self.assertEqual("POTATO_EARLY_BLIGHT", visible_prediction([10, 0, 0, 0])[1])
        self.assertIsNone(visible_prediction([0, 0, 10, 0])[1])
        self.assertIsNone(visible_prediction([0, 0, 0, 10])[1])
        self.assertIsNone(visible_prediction([1, 1, 1, 1])[1])
        report = build_report(boundary_predictions(), input_hashes={}, predictions_sha256="a" * 64,
                              peak_rss_mb=100)
        self.assertTrue(report["all_criteria_passed"])
        self.assertEqual(32, report["per_class"]["POTATO_EARLY_BLIGHT"]["tp"])
        self.assertEqual(45, report["healthy_no_concluyente"]["numerator"])
        decision = g2_decision(report, freeze_digest=FREEZE_DIGEST,
                               report_sha256="b" * 64, predictions_sha256="a" * 64)
        self.assertEqual("CLOSED_APPROVED_BY_PROJECT_OWNER", decision["status"])
        self.assertEqual("INACTIVE_NOT_AUTHORIZED", decision["worker_status"])
        failed = boundary_predictions(); failed[31]["published_diagnosis"] = None
        failed[31]["final_state"] = "NO_CONCLUYENTE"
        failed_report = build_report(failed, input_hashes={}, predictions_sha256="a" * 64,
                                     peak_rss_mb=100)
        self.assertFalse(failed_report["criteria"]["early_recall"])
        self.assertEqual("OPEN_EXTERNAL_CRITERIA_FAILED",
                         g2_decision(failed_report, freeze_digest=FREEZE_DIGEST,
                                     report_sha256="b" * 64,
                                     predictions_sha256="a" * 64)["status"])


if __name__ == "__main__":
    unittest.main()
