"""Pilot TRAIN/VAL decisions and calibration gates, with synthetic tensors only."""

import math
from pathlib import Path
import tempfile
import unittest

import torch

from agro_ml.pilot_training import _metrics, build_model, technical_decision, _rows
from agro_ml.pilot_selection import _calibrate, authorize_pilot_test, fit_calibration, verify_freeze
from agro_ml.evaluation.freezing import TestEvaluationBlockedError


class PilotTrainingTests(unittest.TestCase):
    def test_three_logits_are_two_diseases_plus_technical_rejection(self):
        for name in ("mobilenet_v3_small", "resnet18"):
            with self.subTest(name=name):
                model = build_model(name, 42, "GROUP_NORM")
                model.eval()
                with torch.inference_mode():
                    output = model(torch.zeros(1, 3, 64, 64))
                self.assertEqual(tuple(output.shape), (1, 3))

    def test_decision_rejects_other_and_ambiguous_score_at_boundary(self):
        self.assertEqual(technical_decision([.7, .2, .1], .7), 0)
        self.assertIsNone(technical_decision([.7, .2, .1], .7001))
        self.assertIsNone(technical_decision([.2, .1, .7], 0))
        self.assertIsNone(technical_decision([.49, .49, .02], .5))
        self.assertIsNone(technical_decision([.7, .2, .1], .5, score=.4999))
        self.assertEqual(technical_decision([.7, .2, .1], .5, score=.5), 0)
        self.assertEqual(technical_decision([.7, .2, .1], .5, score=.5001), 0)
        with self.assertRaises(ValueError):
            technical_decision([math.nan, .2, .8], .5)

    def test_abstention_is_not_correct_and_negatives_have_own_denominator(self):
        samples = [{"label": 0}, {"label": 1}, {"label": 2}]
        probs = [[.7, .2, .1], [.2, .3, .5], [.7, .2, .1]]
        report = _metrics(samples, probs, .7)
        self.assertEqual(report["decision_counts"]["accepted_count"], 1)
        self.assertEqual(report["decision_counts"]["abstained_count"], 1)
        self.assertEqual(report["per_class"]["POTATO_LATE_BLIGHT"]["false_negative"], 1)
        self.assertEqual(report["negative_counts"]["negative_evaluated_count"], 1)
        self.assertEqual(report["negative_counts"]["accepted_supported_class_count"], 1)

    def test_test_csv_is_never_accepted_as_train_or_val(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test-positives.csv"
            path.write_text("split\nTEST\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "TRAIN y VAL"):
                _rows(path, "TEST")

    def test_platt_calibration_is_finite_and_class_specific(self):
        scores = []
        for candidate in (0, 1):
            for index in range(25):
                correct = index < 20
                probs = [.05, .05, .05]
                probs[candidate] = .85 if correct else .55
                probs[1 - candidate] = .05 if correct else .35
                probs[2] = 1 - probs[0] - probs[1]
                scores.append({"image_id": f"{candidate}-{index}",
                               "true_target": candidate if correct else 2,
                               "probabilities": probs})
        params, values, quality = fit_calibration(scores)
        self.assertEqual(set(params), {"POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"})
        self.assertEqual(len(values), len(scores))
        self.assertTrue(all(0 <= value <= 1 for value in values))
        self.assertGreaterEqual(quality["ece_all_val_candidates"], 0)
        with self.assertRaises(ValueError):
            _calibrate(float("nan"), params["POTATO_EARLY_BLIGHT"])
        with self.assertRaises(ValueError):
            fit_calibration([row for row in scores if row["true_target"] == 0])

    def test_freeze_rejects_missing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                verify_freeze(Path(directory) / "freeze.json")
            with self.assertRaises(TestEvaluationBlockedError):
                authorize_pilot_test(Path(directory) / "freeze.json")


if __name__ == "__main__":
    unittest.main()
