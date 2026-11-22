"""Synthetic scoring checks; no G1 or sealed TEST images are opened."""

import json
from pathlib import Path
import unittest

from agro_ml.v13_test_evaluation import EXPECTED_TEST, score_test
from agro_ml.v13_metrics import DISEASES, HEALTHY, OTHER


PROTOCOL = json.loads((Path(__file__).resolve().parents[2] /
                       "ml/evaluation/protocol-g0.v1.3.2.json").read_text())


def synthetic_inputs():
    rows, logits = [], []
    for code, (photos, groups) in EXPECTED_TEST.items():
        for index in range(photos):
            rows.append({"image_id": f"{code}-{index}", "stratum_code": code,
                         "split_group": f"{code}-leaf-{index % groups}", "split": "TEST"})
            logits.append([10.0, 0.0, 0.0] if code == DISEASES[0] else
                          [0.0, 10.0, 0.0] if code == DISEASES[1] else [0.0, 0.0, 10.0])
    return rows, logits


def score(rows, logits):
    return score_test(rows, logits, [1.0] * len(rows), PROTOCOL, temperature=1.25,
                      threshold=.9, route="ARGMAX_CONFIDENCE", healthy_gate=None,
                      max_rss_mb=300)


class TestV13TestEvaluation(unittest.TestCase):
    def test_complete_perfect_fixture_passes_and_counts_denominators(self):
        rows, logits = synthetic_inputs()
        report, predictions = score(rows, logits)
        self.assertEqual(len(predictions), 272)
        self.assertEqual(report["group_counts"][HEALTHY], 8)
        self.assertEqual(report["coverage"], {"numerator": 160, "denominator": 160, "rate": 1.0})
        self.assertEqual(report["selective_error"], {"numerator": 0, "denominator": 160, "rate": 0.0})
        self.assertEqual(report["counts"][HEALTHY]["abstained"], 32)
        self.assertEqual(report["counts"][OTHER]["abstained"], 80)
        self.assertTrue(report["g0_numeric_pass"])

    def test_four_healthy_false_publications_fail_even_with_perfect_diseases(self):
        rows, logits = synthetic_inputs()
        for index, row in enumerate(rows):
            if row["stratum_code"] == HEALTHY and row["image_id"].rsplit("-", 1)[1] in {"0", "1", "2", "3"}:
                logits[index] = [0.0, 10.0, 0.0]
        report, _ = score(rows, logits)
        self.assertEqual(report["counts"][HEALTHY]["accepted"], 4)
        self.assertEqual(report["counts"][HEALTHY]["abstained"], 28)
        self.assertFalse(report["g0_checks"]["healthy_visible_blight_count"]["passed"])
        self.assertFalse(report["g0_checks"]["healthy_no_concluyente_count"]["passed"])
        self.assertFalse(report["g0_numeric_pass"])

    def test_abstained_correct_candidates_are_false_negatives(self):
        rows, logits = synthetic_inputs()
        for index, row in enumerate(rows):
            if row["stratum_code"] == DISEASES[0] and int(row["image_id"].rsplit("-", 1)[1]) < 20:
                logits[index] = [1.0, 0.0, 0.0]
        report, _ = score(rows, logits)
        early = report["per_class"][DISEASES[0]]
        self.assertEqual(early["tp"], 60)
        self.assertEqual(early["fn"], 20)
        self.assertEqual(early["false_negative_due_to_abstention"], 20)
        self.assertEqual(report["correct_candidate_abstained"][DISEASES[0]], 20)
        self.assertFalse(report["g0_checks"][f"recall_{DISEASES[0]}"]["passed"])

    def test_five_other_crop_publications_fail_five_percent_limit(self):
        rows, logits = synthetic_inputs()
        for index, row in enumerate(rows):
            if row["stratum_code"] == OTHER and int(row["image_id"].rsplit("-", 1)[1]) < 5:
                logits[index] = [10.0, 0.0, 0.0]
        report, _ = score(rows, logits)
        self.assertEqual(report["counts"][OTHER]["accepted"], 5)
        self.assertFalse(report["g0_checks"]["other_crop_fpr"]["passed"])
        self.assertFalse(report["g0_numeric_pass"])

    def test_incomplete_or_cross_stratum_group_refused(self):
        rows, logits = synthetic_inputs()
        with self.assertRaises(ValueError):
            score(rows[:-1], logits[:-1])
        rows[0]["split_group"] = rows[-1]["split_group"]
        with self.assertRaises(ValueError):
            score(rows, logits)


if __name__ == "__main__":
    unittest.main()
