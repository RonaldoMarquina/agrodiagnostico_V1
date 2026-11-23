import io
import json
from pathlib import Path
import unittest

from PIL import Image
import torch

from agro_ml.v141_gates import TECHNICAL_CLASSES
from agro_ml.v141_training import (
    V141TrainingError, balanced_epoch_indices, build_model, choose_val_policy,
    evaluate, validate_augmentation, validate_plan, visible_decision,
)

ROOT = Path(__file__).resolve().parents[2]


class V141TrainingTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((ROOT / "ml/configs/potato-v141-four-class-cpu.plan.json").read_text())

    def test_plan_and_model_are_four_class_offline(self):
        validate_plan(self.plan)
        model = build_model(42)
        self.assertEqual((1, 4), tuple(model(torch.zeros(1, 3, 224, 224)).shape))
        changed = json.loads(json.dumps(self.plan)); changed["external_access"] = "VAL"
        with self.assertRaises(V141TrainingError):
            validate_plan(changed)

    def test_sampler_is_exactly_80_by_four_and_repeatable(self):
        samples = []
        for code_index, code in enumerate(TECHNICAL_CLASSES):
            for group in range(code_index + 2):
                samples.append({"stratum_code": code, "split_group": f"{code}:{group}"})
        selected, exposure = balanced_epoch_indices(samples, seed=42)
        repeated, _ = balanced_epoch_indices(samples, seed=42)
        self.assertEqual(selected, repeated)
        self.assertEqual(320, len(selected))
        for code in TECHNICAL_CLASSES:
            self.assertEqual(80, sum(samples[index]["stratum_code"] == code for index in selected))
            self.assertEqual(80, exposure[code]["draws"])

    def test_only_blights_publish_and_abstention_is_false_negative(self):
        self.assertEqual(0, visible_decision([.9, .03, .04, .03], .5))
        self.assertIsNone(visible_decision([.05, .05, .8, .1], .5))
        self.assertIsNone(visible_decision([.05, .05, .1, .8], .5))
        rows, logits = [], []
        for code_index, code in enumerate(TECHNICAL_CLASSES):
            for index in range(10):
                rows.append({"image_id": f"{code_index}-{index}", "stratum_code": code,
                             "split_group": f"{code_index}-{index}"})
                values = [0.0] * 4; values[code_index] = 8.0
                if code_index == 0 and index >= 8:
                    values = [0.0, 0.0, 8.0, 0.0]
                logits.append(values)
        report = evaluate(rows, logits, 1.0, .5)
        self.assertEqual(2, report["per_class"][TECHNICAL_CLASSES[0]]["fn"])
        self.assertEqual(.8, report["per_class"][TECHNICAL_CLASSES[0]]["recall"])
        self.assertEqual(0, report["counts"]["POTATO_HEALTHY"]["accepted"])
        self.assertEqual(0, report["counts"]["OTHER_CROP"]["accepted"])

    def test_augmentation_is_healthy_train_only(self):
        validate_augmentation("TRAIN", "POTATO_HEALTHY", True)
        for split, code in (("VAL", "POTATO_HEALTHY"), ("TRAIN", "OTHER_CROP"),
                            ("EXTERNAL", "POTATO_HEALTHY")):
            with self.assertRaises(V141TrainingError):
                validate_augmentation(split, code, True)


if __name__ == "__main__":
    unittest.main()
