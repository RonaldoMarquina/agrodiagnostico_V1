"""Real pilot inference decisions on generated pixels, never agronomic evidence."""

import io
import multiprocessing
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from PIL import Image
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/ai_inference"))
from app.pilot_runtime import BoundedPilotInferenceAdapter, PilotModelInferenceAdapter  # noqa: E402


def image_bytes() -> bytes:
    image = Image.new("RGB", (224, 224), (20, 110, 40))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class ConstantModel(torch.nn.Module):
    def __init__(self, logits):
        super().__init__()
        self.logits = logits
        self.calls = 0

    def forward(self, tensor):
        self.calls += 1
        return torch.tensor([self.logits], dtype=torch.float32)


def slow_child(send, bundle_path, expected_sha256, approval_sha256, diagnosis_id, image_bytes, identified_crop):
    time.sleep(3)


def crash_child(send, bundle_path, expected_sha256, approval_sha256, diagnosis_id, image_bytes, identified_crop):
    raise SystemExit(1)


class TestPilotRuntime(unittest.TestCase):
    def setUp(self):
        self.bundle = {
            "model_id": "pilot", "model_version": "0.1.0-pilot",
            "dataset_version": "1.2.0-pv-color",
            "preprocessing": {"input_size": [64, 64], "channels": 3,
                              "color_space": "RGB", "mean": [.485, .456, .406],
                              "std": [.229, .224, .225]},
            "rejection_components": {"min_dimension": 200, "max_dimension": 6000,
                                     "min_confidence_threshold": .5},
            "calibration": {"parameters_per_class": {
                "POTATO_EARLY_BLIGHT": {"slope": 1., "intercept": 0.},
                "POTATO_LATE_BLIGHT": {"slope": 1., "intercept": 0.},
            }},
        }
        self.pixels = image_bytes()

    def test_publishes_only_pilot_disease_and_raw_score(self):
        model = ConstantModel([3., 1., -2.])
        result = PilotModelInferenceAdapter(model, self.bundle).run_inference(
            uuid.uuid4(), self.pixels, identified_crop="POTATO")
        self.assertEqual(result["outcome"], "PREDICTION")
        self.assertEqual(result["class_code"], "POTATO_EARLY_BLIGHT")
        self.assertGreater(result["raw_score"], .8)
        self.assertEqual(result["model_version"], "0.1.0-pilot")
        self.assertEqual(model.calls, 1)

    def test_missing_or_other_crop_never_runs_model(self):
        for crop in (None, "MAIZE"):
            model = ConstantModel([3., 1., -2.])
            result = PilotModelInferenceAdapter(model, self.bundle).run_inference(
                uuid.uuid4(), self.pixels, identified_crop=crop)
            self.assertEqual(result["reason_code"], "UNSUPPORTED_CROP")
            self.assertIsNone(result["model_id"])
            self.assertEqual(model.calls, 0)

    def test_invalid_image_has_jointly_null_metadata(self):
        model = ConstantModel([3., 1., -2.])
        result = PilotModelInferenceAdapter(model, self.bundle).run_inference(
            uuid.uuid4(), b"invalid", identified_crop="POTATO")
        self.assertEqual(result["reason_code"], "BAD_IMAGE")
        self.assertIsNone(result["inference_ms"])
        self.assertEqual(model.calls, 0)

    def test_technical_other_crop_is_abstention_with_model_metadata(self):
        model = ConstantModel([1., 0., 3.])
        result = PilotModelInferenceAdapter(model, self.bundle).run_inference(
            uuid.uuid4(), self.pixels, identified_crop="POTATO")
        self.assertEqual(result["reason_code"], "UNSUPPORTED_CROP")
        self.assertIsNone(result["class_code"])
        self.assertEqual(result["model_id"], "pilot")

    def test_calibrated_threshold_can_abstain_despite_candidate(self):
        self.bundle["calibration"]["parameters_per_class"]["POTATO_EARLY_BLIGHT"]["intercept"] = -10.
        model = ConstantModel([3., 1., -2.])
        result = PilotModelInferenceAdapter(model, self.bundle).run_inference(
            uuid.uuid4(), self.pixels, identified_crop="POTATO")
        self.assertEqual(result["reason_code"], "LOW_CONFIDENCE")
        self.assertEqual(result["crop_code"], "POTATO")
        self.assertIsNone(result["class_code"])

    def test_runtime_requires_pinned_approval_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model-bundle.json"
            (path.parent / "g2-approval.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Acta G2"):
                PilotModelInferenceAdapter.from_bundle_file(path, "0" * 64, "0" * 64)

    def test_bounded_process_terminates_timeout(self):
        adapter = BoundedPilotInferenceAdapter.__new__(BoundedPilotInferenceAdapter)
        adapter.bundle_path = Path("fixture")
        adapter.expected_sha256 = "0" * 64
        adapter.approval_sha256 = "0" * 64
        adapter.timeout_seconds = 1
        with patch("app.pilot_runtime._inference_process", slow_child):
            with self.assertRaises(TimeoutError):
                adapter.run_inference(uuid.uuid4(), self.pixels, identified_crop="POTATO")
        self.assertFalse(any(child.is_alive() for child in multiprocessing.active_children()))

    def test_bounded_process_crash_never_returns_result(self):
        adapter = BoundedPilotInferenceAdapter.__new__(BoundedPilotInferenceAdapter)
        adapter.bundle_path = Path("fixture")
        adapter.expected_sha256 = "0" * 64
        adapter.approval_sha256 = "0" * 64
        adapter.timeout_seconds = 8
        with patch("app.pilot_runtime._inference_process", crash_child):
            with self.assertRaises((EOFError, RuntimeError)):
                adapter.run_inference(uuid.uuid4(), self.pixels, identified_crop="POTATO")


if __name__ == "__main__":
    unittest.main()
