import io
import json
from pathlib import Path
import unittest

from PIL import Image
import torch

from agro_ml.data.tensor_preprocessing import TensorSpec
from agro_ml.v13_metrics import HEALTHY, OTHER, TARGETS
from agro_ml.v14_training import (
    V14TrainingError,
    choose_val_policy,
    group_balanced_epoch_indices,
    healthy_train_tensor,
    validate_augmentation_request,
    validate_plan,
)


ROOT = Path(__file__).resolve().parents[2]


def image_bytes() -> bytes:
    image = Image.new("RGB", (220, 210), (80, 150, 65))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class V14TrainingPrimitivesTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(
            (ROOT / "ml/configs/potato-v14-balanced-cpu.plan.json").read_text()
        )

    def test_plan_blocks_external_and_downloaded_weights(self):
        spec = validate_plan(self.plan)
        self.assertEqual((224, 224), (spec.width, spec.height))
        for key, value in (
            ("base_weights", "IMAGENET"),
            ("protocol_version", "1.3.2"),
        ):
            changed = json.loads(json.dumps(self.plan))
            changed[key] = value
            with self.assertRaises(V14TrainingError):
                validate_plan(changed)
        changed = json.loads(json.dumps(self.plan))
        changed["external"]["use_during_this_plan"] = "VAL"
        with self.assertRaises(V14TrainingError):
            validate_plan(changed)

    def test_augmentation_is_repeatable_and_healthy_train_only(self):
        spec = TensorSpec.from_dict(self.plan["preprocessing"])
        augmentation = self.plan["healthy_train_only_augmentation"]
        first, lineage = healthy_train_tensor(
            image_bytes(), spec, seed=77, augmentation=augmentation
        )
        repeated, repeated_lineage = healthy_train_tensor(
            image_bytes(), spec, seed=77, augmentation=augmentation
        )
        changed, _ = healthy_train_tensor(
            image_bytes(), spec, seed=78, augmentation=augmentation
        )
        self.assertTrue(torch.equal(first, repeated))
        self.assertEqual(lineage, repeated_lineage)
        self.assertFalse(torch.equal(first, changed))
        self.assertEqual((3, 224, 224), tuple(first.shape))
        self.assertEqual(77, lineage["seed"])
        for split, code in (("VAL", HEALTHY), ("EXTERNAL", HEALTHY),
                            ("TRAIN", TARGETS[0])):
            with self.assertRaises(V14TrainingError):
                validate_augmentation_request(split, code, True)

    def test_sampler_is_leaf_aware_balanced_and_repeatable(self):
        samples = []
        group_counts = {TARGETS[0]: 5, TARGETS[1]: 4, TARGETS[2]: 2}
        for code, groups in group_counts.items():
            for group in range(groups):
                for view in range(3):
                    samples.append({
                        "stratum_code": code,
                        "split_group": f"{code}:leaf-{group}",
                        "image_id": f"{code}-{group}-{view}",
                    })
        selected, exposure = group_balanced_epoch_indices(
            samples, samples_per_class=80, seed=42
        )
        repeated, _ = group_balanced_epoch_indices(
            samples, samples_per_class=80, seed=42
        )
        self.assertEqual(selected, repeated)
        self.assertEqual(240, len(selected))
        selected_codes = [samples[index]["stratum_code"] for index in selected]
        for code in TARGETS:
            self.assertEqual(80, selected_codes.count(code))
            self.assertEqual(group_counts[code], exposure[code]["unique_leaf_groups"])
            self.assertLessEqual(exposure[code]["unique_original_images"], 80)
        self.assertEqual(2, exposure[HEALTHY]["available_leaf_groups"])

    def test_sampler_rejects_fallback_and_empty_class(self):
        with self.assertRaises(V14TrainingError):
            group_balanced_epoch_indices(
                [{"stratum_code": TARGETS[0], "split_group": "fallback_1"}],
                samples_per_class=80,
                seed=42,
            )
        with self.assertRaises(V14TrainingError):
            group_balanced_epoch_indices(
                [{"stratum_code": TARGETS[0], "split_group": "leaf-1"}],
                samples_per_class=80,
                seed=42,
            )

    def test_val_policy_counts_abstention_as_false_negative(self):
        rows = []
        logits = []
        for index in range(10):
            rows.append({"image_id": f"early-{index}", "stratum_code": TARGETS[0],
                         "split_group": f"e-{index}"})
            logits.append([8, 0, 0] if index < 8 else [0, 0, 8])
            rows.append({"image_id": f"late-{index}", "stratum_code": TARGETS[1],
                         "split_group": f"l-{index}"})
            logits.append([0, 8, 0])
        for code, prefix in ((HEALTHY, "h"), (OTHER, "o")):
            rows.append({"image_id": prefix, "stratum_code": code,
                         "split_group": prefix})
            logits.append([0, 0, 8])
        report, evaluated = choose_val_policy(rows, logits, self.plan["selection"])
        self.assertEqual(72, evaluated)
        early = report["per_class"][TARGETS[0]]
        self.assertEqual(2, early["fn"])
        self.assertEqual(.8, early["recall"])
        self.assertEqual(2, report["counts"][TARGETS[0]]["abstained"])
        self.assertIn("visible_confusion_matrix", report)


if __name__ == "__main__":
    unittest.main()
