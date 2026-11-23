from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import torch
from torch import nn
from torchvision.models import mobilenet_v3_small

from agro_ml.v141_gates import TECHNICAL_CLASSES
from agro_ml.v142_transfer import (
    V142TransferError, backbone_digest, build_pretrained_model, configure_phase,
    set_training_mode, shared_tensor, validate_history_index, validate_plan,
    load_training_resume, save_training_resume, validate_private_roots,
    validate_training_mounts, visible_class,
)

ROOT = Path(__file__).resolve().parents[2]


def image_bytes(mode: str = "RGBA") -> bytes:
    stream = io.BytesIO()
    Image.new(mode, (240, 220), (10, 30, 80, 255)).save(stream, format="PNG")
    return stream.getvalue()


class V142TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((ROOT / "ml/configs/potato-v142-transfer-cpu.plan.json").read_text())
        cls.preprocessing = json.loads((ROOT / "ml/preprocessing/potato-v142-imagenet-compatible.json").read_text())

    def test_plan_and_shared_rgb_imagenet_preprocessing(self):
        spec = validate_plan(self.plan, self.preprocessing)
        train = shared_tensor(image_bytes(), spec, consumer="TRAIN")
        inference = shared_tensor(image_bytes(), spec, consumer="INFERENCE")
        self.assertTrue(torch.equal(train, inference))
        self.assertEqual((3, 224, 224), tuple(train.shape))
        changed = deepcopy(self.preprocessing); changed["tensor"]["mean"][0] = 0.5
        with self.assertRaises(V142TransferError):
            validate_plan(self.plan, changed)

    def test_private_root_cannot_overlap_historical_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            validate_private_roots(base / "v142", base / "v141")
            for current in (base / "v141", base / "v141/new"):
                with self.assertRaises(V142TransferError):
                    validate_private_roots(current, base / "v141")

    def test_history_index_and_protected_mounts_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); repo = base / "repo"; private = base / "g1"
            repo.mkdir(); private.mkdir()
            tracked = repo / "fixed.json"; tracked.write_text("fixed")
            evidence = private / "g1.json"; evidence.write_text("private")
            import hashlib
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            index = {"cycle_version": "1.4.2", "status": "HISTORICAL_BOUNDARY_LOCKED",
                     "baseline_commits": {"a": "a" * 40},
                     "tracked_evidence": {"fixed.json": digest(tracked)},
                     "private_g1_evidence": {"g1.json": digest(evidence)},
                     "comparison_policy": {"forbidden": ["V1_4_1_WEIGHTS", "V1_4_1_PREDICTIONS",
                                                            "HISTORICAL_TEST", "SIKKIM_EXTERNAL"]}}
            validate_history_index(index, repo, private, commit_exists=lambda value: value == "a" * 40)
            tracked.write_text("changed")
            with self.assertRaises(V142TransferError):
                validate_history_index(index, repo, private, commit_exists=lambda value: True)
        for protected in (Path("/data/sikkim"), Path("/data/historical-test"),
                          Path("/output/v1.4.1-train-val")):
            with self.assertRaises(V142TransferError):
                validate_training_mounts([protected])

    def test_head_and_fine_tune_scopes_keep_batchnorm_frozen(self):
        source = mobilenet_v3_small(weights=None).state_dict()
        model = build_pretrained_model(source, seed=42)
        self.assertEqual((1, 4), tuple(model(torch.zeros(1, 3, 224, 224)).shape))
        before = backbone_digest(model)
        head_groups = configure_phase(model, "HEAD")
        self.assertEqual(["classifier"], [group["name"] for group in head_groups])
        self.assertTrue(all(parameter.requires_grad for parameter in model.classifier.parameters()))
        self.assertFalse(any(parameter.requires_grad for parameter in model.features.parameters()))
        self.assertEqual(before, backbone_digest(model))
        fine_groups = configure_phase(model, "FINE_TUNE")
        self.assertEqual([1e-5, 1e-4], [group["lr"] for group in fine_groups])
        self.assertTrue(any(parameter.requires_grad for parameter in list(model.features.children())[-1].parameters()))
        self.assertFalse(any(parameter.requires_grad
                             for block in list(model.features.children())[:-3]
                             for parameter in block.parameters()))
        set_training_mode(model)
        for module in model.modules():
            if isinstance(module, nn.BatchNorm2d):
                self.assertFalse(module.training)
                self.assertFalse(any(parameter.requires_grad for parameter in module.parameters()))

    def test_only_blights_are_publishable(self):
        self.assertEqual(TECHNICAL_CLASSES[0], visible_class([.9, .02, .04, .04], .5))
        self.assertEqual(TECHNICAL_CLASSES[1], visible_class([.02, .9, .04, .04], .5))
        self.assertIsNone(visible_class([.02, .02, .9, .06], .5))
        self.assertIsNone(visible_class([.02, .02, .06, .9], .5))
        self.assertIsNone(visible_class([.3, .25, .25, .2], .5))

    def test_resume_round_trip_is_hash_checked_and_weights_only(self):
        model = build_pretrained_model(mobilenet_v3_small(weights=None).state_dict(), seed=42)
        optimizer = torch.optim.AdamW(configure_phase(model, "HEAD"))
        original = backbone_digest(model)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_training_resume(root, model, optimizer, epoch=1, phase="HEAD", history=[{"epoch": 1}])
            with torch.no_grad():
                next(model.features.parameters()).add_(1)
            self.assertNotEqual(original, backbone_digest(model))
            record = load_training_resume(root, model, optimizer)
            self.assertEqual(1, record["epoch"])
            self.assertEqual(original, backbone_digest(model))
            (root / "resume-optimizer.pt").write_bytes(b"altered")
            with self.assertRaises(V142TransferError):
                load_training_resume(root, model, optimizer)


if __name__ == "__main__":
    unittest.main()
