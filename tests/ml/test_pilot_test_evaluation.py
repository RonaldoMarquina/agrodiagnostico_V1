"""Known-output checks for the frozen TEST reporter; no private TEST access."""

import copy
import unittest

from agro_ml.pilot_test_evaluation import evaluate_once, score_frozen_test


CALIBRATION = {"selected_on": "VAL", "class_parameters": {
    "POTATO_EARLY_BLIGHT": {"slope": 1.0, "intercept": 0.0},
    "POTATO_LATE_BLIGHT": {"slope": 1.0, "intercept": 0.0},
}}
THRESHOLDS = {"selected_on": "VAL", "status": "LOCKED_BEFORE_TEST", "per_class": {
    "POTATO_EARLY_BLIGHT": 0.5, "POTATO_LATE_BLIGHT": 0.5,
}}
PROTOCOL = {"protocol_version": "1.2.0", "metrics_thresholds": {
    "macro_f1_test_min": .85, "class_recall_test_min": .8, "class_f1_test_min": .7,
    "selective_coverage_min": .7, "selective_error_max": .1,
    "negative_samples_fpr_max": .05, "calibration_ece_max": .15,
}, "compute_budget_cpu": {
    "latency_median_ms_max": 1000, "latency_p95_ms_max": 2500,
    "latency_hard_limit_ms": 4000, "max_rss_mb": 1024,
}}


class PilotTestReportTests(unittest.TestCase):
    def test_abstention_is_false_negative_even_with_correct_candidate(self):
        rows = [
            {"target": 0, "probabilities": [.7, .2, .1]},
            {"target": 0, "probabilities": [.45, .4, .15]},
            {"target": 1, "probabilities": [.1, .8, .1]},
            {"target": 2, "probabilities": [.7, .2, .1]},
            {"target": 2, "probabilities": [.2, .1, .7]},
        ]
        report = score_frozen_test(rows, CALIBRATION, THRESHOLDS, PROTOCOL,
                                   [5, 6, 7, 8, 9], 350)
        early = report["per_class"]["POTATO_EARLY_BLIGHT"]
        self.assertEqual(early["recall_counts"], {"numerator": 1, "denominator": 2})
        self.assertEqual(early["false_negative_due_to_abstention"], 1)
        self.assertEqual(report["abstained_correct_candidate_total"], 1)
        self.assertEqual(report["rates"]["coverage"]["numerator"], 2)
        self.assertEqual(report["rates"]["coverage"]["denominator"], 3)
        self.assertEqual(report["rates"]["negative_acceptance"]["numerator"], 1)
        self.assertEqual(report["rates"]["negative_acceptance"]["denominator"], 2)
        self.assertEqual(report["confusion_with_abstention_and_negatives"]["POTATO_EARLY_BLIGHT"]["NO_CONCLUYENTE"], 1)
        self.assertEqual(report["calibration"]["accepted_brier_denominator"], 2)
        self.assertEqual(report["calibration"]["raw_three_target_brier_denominator"], 5)
        self.assertFalse(report["g0_numeric_pass"])

    def test_no_accepted_and_no_negatives_cannot_pass(self):
        rows = [{"target": 0, "probabilities": [.45, .4, .15]},
                {"target": 1, "probabilities": [.4, .45, .15]}]
        report = score_frozen_test(rows, CALIBRATION, THRESHOLDS, PROTOCOL,
                                   [1, 2], 350)
        self.assertIsNone(report["rates"]["selective_error"]["value"])
        self.assertEqual(report["rates"]["selective_error"]["denominator"], 0)
        self.assertIsNone(report["rates"]["negative_acceptance"]["value"])
        self.assertEqual(report["rates"]["negative_acceptance"]["denominator"], 0)
        self.assertFalse(report["g0_checks"]["selective_error"]["passed"])
        self.assertFalse(report["g0_checks"]["negative_acceptance"]["passed"])

    def test_changed_threshold_is_rejected_before_scoring(self):
        thresholds = copy.deepcopy(THRESHOLDS)
        thresholds["per_class"]["POTATO_EARLY_BLIGHT"] = .49
        with self.assertRaises(ValueError):
            score_frozen_test([{"target": 0, "probabilities": [.7, .2, .1]}],
                              CALIBRATION, thresholds, PROTOCOL, [5], 350)

    def test_existing_output_refuses_second_test_access(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "used").mkdir()
            with self.assertRaises(FileExistsError):
                evaluate_once(root / "missing-freeze", root / "missing-data",
                              root / "missing-images", root / "missing-evidence",
                              "0" * 64, "0" * 64, root / "used")

    def test_unexpected_freeze_hash_refuses_before_test_access(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze = root / "freeze.json"
            freeze.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Snapshot congelado distinto"):
                evaluate_once(freeze, root / "missing-data", root / "missing-images",
                              root / "missing-evidence", "0" * 64, "0" * 64,
                              root / "unused")
            self.assertFalse((root / "unused").exists())


if __name__ == "__main__":
    unittest.main()
