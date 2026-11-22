"""Visible VAL metrics must count abstentions and separate negative strata."""

import json
from pathlib import Path
import unittest

from agro_ml.v13_metrics import evaluate, val_gate, visible_decision

ROOT = Path(__file__).resolve().parents[2]


class TestV13Metrics(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads((ROOT / "ml/evaluation/protocol-g0.v1.3.2.json").read_text())

    def test_healthy_argmax_is_never_published(self):
        self.assertIsNone(visible_decision([.05, .1, .85], 0, "ARGMAX_CONFIDENCE"))
        self.assertIsNone(visible_decision([.05, .1, .85], 0, "HEALTHY_GATE", .5))

    def test_abstention_is_false_negative_and_negatives_are_separate(self):
        rows = [{"image_id": "e", "stratum_code": "POTATO_EARLY_BLIGHT", "split_group": "e"},
                {"image_id": "l", "stratum_code": "POTATO_LATE_BLIGHT", "split_group": "l"},
                {"image_id": "h", "stratum_code": "POTATO_HEALTHY", "split_group": "h"},
                {"image_id": "o", "stratum_code": "OTHER_CROP", "split_group": "o"}]
        logits = [[4, 0, 0], [0, 0, 4], [0, 0, 4], [4, 0, 0]]
        report = evaluate(rows, logits, 1, .5, "ARGMAX_CONFIDENCE")
        self.assertEqual(report["per_class"]["POTATO_LATE_BLIGHT"]["fn"], 1)
        self.assertEqual(report["counts"]["POTATO_HEALTHY"]["abstained"], 1)
        self.assertEqual(report["counts"]["OTHER_CROP"]["accepted"], 1)
        self.assertEqual(report["coverage"], {"numerator": 1, "denominator": 2, "rate": .5})

    def test_val_gate_uses_28_healthy_and_150_other_denominators(self):
        rows = []
        logits = []
        for code, count, values in (("POTATO_EARLY_BLIGHT", 165, [4, 0, 0]),
                                    ("POTATO_LATE_BLIGHT", 153, [0, 4, 0]),
                                    ("POTATO_HEALTHY", 28, [0, 0, 4]),
                                    ("OTHER_CROP", 150, [0, 0, 4])):
            for i in range(count):
                rows.append({"image_id": f"{code}-{i}", "stratum_code": code, "split_group": f"{code}-{i}"})
                logits.append(values)
        report = evaluate(rows, logits, 1, .5, "ARGMAX_CONFIDENCE")
        gate = val_gate(report, self.protocol)
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["healthy_val_allowed_accepted"], 2)
        self.assertEqual(gate["healthy_val_required_no_concluyente"], 26)
        logits[-1] = [4, 0, 0]
        report = evaluate(rows, logits, 1, .5, "ARGMAX_CONFIDENCE")
        self.assertEqual(report["counts"]["OTHER_CROP"]["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
