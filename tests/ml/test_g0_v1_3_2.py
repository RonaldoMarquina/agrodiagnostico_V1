"""Freeze the approved healthy TEST counts without changing other G0 criteria."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.verify_g0_v1_3_2 import validate_protocol

ROOT = Path(__file__).resolve().parents[2]


class TestG0V132(unittest.TestCase):
    def setUp(self):
        self.old = json.loads((ROOT / "ml/evaluation/protocol-g0.v1.3.1.json").read_text())
        self.new = json.loads((ROOT / "ml/evaluation/protocol-g0.v1.3.2.json").read_text())
        reuse = self.new["g1_reuse"]
        self.report = {
            "status": "G1_V1_3_1_ADMITTED_AND_TEST_SEALED",
            "protocol_sha256": reuse["admission_protocol_sha256"],
            "manifest_sha256": reuse["manifest_sha256"],
            "test_seal_sha256": reuse["test_seal_sha256"],
            "admitted_photos": 2391,
            "admitted_groups": 606,
            "counts": {
                "POTATO_EARLY_BLIGHT": {"TRAIN": {"photos": 541, "groups": 136},
                                         "VAL": {"photos": 165, "groups": 42},
                                         "TEST": {"photos": 80, "groups": 20}},
                "POTATO_LATE_BLIGHT": {"TRAIN": {"photos": 499, "groups": 129},
                                        "VAL": {"photos": 153, "groups": 39},
                                        "TEST": {"photos": 80, "groups": 20}},
                "POTATO_HEALTHY": {"TRAIN": {"photos": 80, "groups": 20},
                                   "VAL": {"photos": 28, "groups": 7},
                                   "TEST": {"photos": 32, "groups": 8}},
                "OTHER_CROP": {"TRAIN": {"photos": 503, "groups": 127},
                               "VAL": {"photos": 150, "groups": 38},
                               "TEST": {"photos": 80, "groups": 20}},
            },
        }

    def validate(self, protocol=None, report=None):
        reuse = self.new["g1_reuse"]
        return validate_protocol(protocol or self.new, self.old, report or self.report,
                                 reuse["admission_protocol_sha256"], reuse["private_report_sha256"])

    def test_approved_protocol_accepts_existing_g1_without_model_results(self):
        result = self.validate()
        self.assertEqual(result["status"], "G0_V1_3_2_APPROVED_G1_REUSED")
        self.assertEqual((result["healthy_max_visible_blight"], result["healthy_min_no_concluyente"]), (3, 29))

    def test_other_crop_threshold_relaxation_is_rejected(self):
        changed = deepcopy(self.new)
        changed["metrics_thresholds"]["negative_fpr_other_crop_max"] = 0.1
        with self.assertRaisesRegex(ValueError, "OTHER_CROP"):
            self.validate(protocol=changed)

    def test_unapproved_healthy_count_is_rejected(self):
        changed = deepcopy(self.new)
        changed["metrics_thresholds"]["potato_healthy_test_max_visible_blight_count"] = 4
        with self.assertRaisesRegex(ValueError, "Approved healthy TEST"):
            self.validate(protocol=changed)

    def test_g1_shortfall_or_different_seal_reopens_gate(self):
        short = deepcopy(self.report)
        short["counts"]["POTATO_HEALTHY"]["TEST"]["groups"] = 7
        with self.assertRaisesRegex(ValueError, "Approved healthy TEST"):
            self.validate(report=short)
        changed = deepcopy(self.report)
        changed["test_seal_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "G1 admission lineage"):
            self.validate(report=changed)


if __name__ == "__main__":
    unittest.main()
