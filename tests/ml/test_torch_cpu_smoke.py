"""Recorrido CPU real con pesos tensoriales, identificado como fixture técnico."""

import importlib.util
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    import torch
    from PIL import Image, ImageDraw, ImageOps
    from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor, measure_cpu_preprocessing
    from agro_ml.models.torch_cpu import (
        CropPolicy, build_model, decide_crop, load_fixture_checkpoint, predict_image,
        select_fixture_crop_policy, train_fixture_hierarchical_heads,
    )
    from agro_ml.smoke import (
        compare_fixture_models, evaluate_fixture_checkpoint, fixture_image,
        infer_fixture_checkpoint, package_fixture_checkpoint, run_cpu_smoke,
    )


@unittest.skipUnless(HAS_TORCH, "PyTorch CPU requerido; CI ML instala el lock")
class TestTorchCpuSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.config = Path(__file__).resolve().parents[2] / "ml/configs/cpu-smoke.v1.json"
        cls.joint = run_cpu_smoke(cls.config, "mobilenet_v3_small", cls.root / "joint")
        cls.hierarchical = run_cpu_smoke(cls.config, "resnet18_hierarchical", cls.root / "hierarchical")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_real_weights_are_trained_reloaded_and_labeled_fixture(self):
        for report in (self.joint, self.hierarchical):
            with self.subTest(architecture=report["architecture"]):
                self.assertEqual(report["status"], "TECHNICAL_FIXTURE_ONLY")
                self.assertFalse(report["g0_approved"])
                self.assertFalse(report["g2_approved"])
                self.assertTrue(report["weights_changed"])
                self.assertTrue(report["tensor_equivalent"])
                self.assertEqual(len(report["weights_sha256"]), 64)
                model, metadata, spec = load_fixture_checkpoint(Path(report["checkpoint"]))
                self.assertEqual(metadata["status"], "FIXTURE_ONLY")
                self.assertEqual(metadata["base_weights"]["source"], "RANDOM_INITIALIZATION")
                self.assertFalse(metadata["base_weights"]["downloaded"])
                self.assertEqual(metadata["runtime"]["device"], "cpu")
                self.assertIsInstance(model, torch.nn.Module)
                self.assertEqual(spec.to_dict()["channels"], 3)

    def test_same_tensor_for_train_validation_and_inference(self):
        raw = fixture_image(2, variant=1)
        spec = TensorSpec()
        validation = image_to_tensor(raw, spec, split="VAL")
        inference = image_to_tensor(raw, spec, split="INFERENCE")
        training_without_augmentation = image_to_tensor(raw, spec, split="TRAIN")
        self.assertTrue(torch.equal(validation, inference))
        self.assertTrue(torch.equal(validation, training_without_augmentation))
        self.assertEqual(tuple(validation.shape), (3, 64, 64))
        self.assertEqual(validation.dtype, torch.float32)
        self.assertTrue(bool(torch.isfinite(validation).all()))

    def test_exif_orientation_and_grayscale_to_rgb(self):
        original = Image.new("RGB", (300, 200), (240, 20, 20))
        ImageDraw.Draw(original).rectangle((0, 0, 100, 199), fill=(10, 220, 20))
        exif = Image.Exif()
        exif[274] = 6
        marked = io.BytesIO()
        original.save(marked, format="PNG", exif=exif)
        with Image.open(io.BytesIO(marked.getvalue())) as source:
            rotated = ImageOps.exif_transpose(source)
        canonical = io.BytesIO()
        rotated.save(canonical, format="PNG")
        spec = TensorSpec(mean=(0., 0., 0.), std=(1., 1., 1.))
        self.assertTrue(torch.equal(image_to_tensor(marked.getvalue(), spec, split="VAL"),
                                    image_to_tensor(canonical.getvalue(), spec, split="INFERENCE")))
        grayscale = Image.new("L", (224, 224), 100)
        gray_bytes = io.BytesIO()
        grayscale.save(gray_bytes, format="PNG")
        tensor = image_to_tensor(gray_bytes.getvalue(), spec, split="INFERENCE")
        self.assertTrue(torch.equal(tensor[0], tensor[1]))
        self.assertTrue(torch.equal(tensor[1], tensor[2]))

    def test_cpu_measurement_is_observed_not_an_approved_budget(self):
        measurement = measure_cpu_preprocessing(fixture_image(1), TensorSpec(), iterations=3)
        self.assertEqual(measurement["scope"], "TENSOR_PREPROCESSING_FIXTURE_ONLY")
        self.assertGreaterEqual(measurement["p95_ms"], measurement["median_ms"])
        self.assertGreater(measurement["iterations"], 0)

    def test_rejects_invalid_inputs_and_nontrain_augmentation(self):
        spec = TensorSpec()
        for raw in (b"", b"not an image", fixture_image(0)[:20]):
            with self.subTest(raw=raw[:8]), self.assertRaises(ValueError):
                image_to_tensor(raw, spec, split="INFERENCE")
        with self.assertRaises(ValueError):
            image_to_tensor(fixture_image(0), spec, split="VAL", augment=True)
        with self.assertRaisesRegex(ValueError, "semilla"):
            image_to_tensor(fixture_image(0), spec, split="TRAIN", augment=True)
        augmented = image_to_tensor(fixture_image(0), spec, split="TRAIN", augment=True, seed=1)
        again = image_to_tensor(fixture_image(0), spec, split="TRAIN", augment=True, seed=1)
        self.assertTrue(torch.equal(augmented, again))
        self.assertFalse(torch.equal(augmented, image_to_tensor(fixture_image(0), spec, split="TRAIN")))
        model, _, _ = load_fixture_checkpoint(Path(self.hierarchical["checkpoint"]))
        with self.assertRaisesRegex(ValueError, "política"):
            predict_image(model, "resnet18_hierarchical", fixture_image(0), spec)

    def test_checkpoint_tampering_is_rejected(self):
        manifest = Path(self.joint["checkpoint"])
        weights = manifest.with_name("fixture-weights.safetensors")
        original = weights.read_bytes()
        try:
            weights.write_bytes(original + b"tamper")
            with self.assertRaisesRegex(ValueError, "alterados"):
                load_fixture_checkpoint(manifest)
        finally:
            weights.write_bytes(original)

    def test_checkpoint_rejects_symlinked_weights(self):
        source_manifest = Path(self.joint["checkpoint"])
        target_dir = self.root / "symlinked"
        target_dir.mkdir()
        target_manifest = target_dir / source_manifest.name
        shutil.copyfile(source_manifest, target_manifest)
        (target_dir / "fixture-weights.safetensors").symlink_to(source_manifest.with_name("fixture-weights.safetensors"))
        with self.assertRaisesRegex(ValueError, "Ruta de pesos"):
            load_fixture_checkpoint(target_manifest)

    def test_crop_unknown_and_ambiguous_reject_without_seven_class_argmax(self):
        policy = CropPolicy(.4, .1, "VAL_FIXTURE")
        self.assertEqual(decide_crop(torch.tensor([5., 0., -2.]), policy), "POTATO")
        self.assertEqual(decide_crop(torch.tensor([0., 5., -2.]), policy), "MAIZE")
        self.assertIsNone(decide_crop(torch.tensor([0., 0., 5.]), policy))
        self.assertIsNone(decide_crop(torch.tensor([1., 1., -2.]), policy))
        self.assertIsNone(decide_crop(torch.tensor([.2, .1, 0.]), CropPolicy(.8, .01, "VAL_FIXTURE")))
        with self.assertRaises(ValueError):
            decide_crop(torch.tensor([float("nan"), 0., 1.]), policy)
        with self.assertRaisesRegex(ValueError, "fixtures"):
            CropPolicy(.4, .1, "VAL")

    def test_loaded_model_infers_only_as_fixture(self):
        joint = infer_fixture_checkpoint(Path(self.joint["checkpoint"]), fixture_image(0, variant=1))
        self.assertTrue(joint["fixture_only"])
        self.assertIn(joint["class_code"], {"POTATO_HEALTHY", "POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT",
                                            "MAIZE_HEALTHY", "MAIZE_COMMON_RUST", "MAIZE_LEAF_BLIGHT", "MAIZE_GRAY_LEAF_SPOT"})
        self.assertGreaterEqual(joint["raw_score"], 0)
        hierarchical = infer_fixture_checkpoint(Path(self.hierarchical["checkpoint"]), fixture_image(None, variant=1))
        self.assertTrue(hierarchical["fixture_only"])
        self.assertEqual(hierarchical["status"], "ABSTENTION")
        self.assertEqual(hierarchical["reason_code"], "UNSUPPORTED_CROP")
        self.assertIsNone(hierarchical["class_code"])

    def test_hierarchical_rejects_bad_image_and_unusable_validation(self):
        manifest = Path(self.hierarchical["checkpoint"])
        model, _, spec = load_fixture_checkpoint(manifest)
        flat = Image.new("RGB", (224, 224), (80, 80, 80))
        raw = io.BytesIO()
        flat.save(raw, format="PNG")
        policy_data = self.hierarchical["fixture_crop_policy"]
        policy = CropPolicy(policy_data["min_crop_score"], policy_data["min_margin"], "VAL_FIXTURE")
        result = predict_image(model, "resnet18_hierarchical", raw.getvalue(), spec, crop_policy=policy)
        self.assertEqual((result["status"], result["reason_code"]), ("ABSTENTION", "BAD_IMAGE"))

        class AlwaysOther(torch.nn.Module):
            def forward(self, tensor):
                return (torch.tensor([[0., 0., 9.]]), None, None)

        samples = [(fixture_image(0, variant=1), 0),
                   (fixture_image(3, variant=1), 3),
                   (fixture_image(None, variant=1), None)]
        with self.assertRaisesRegex(ValueError, "sin cobertura correcta"):
            select_fixture_crop_policy(AlwaysOther(), samples, spec)

    def test_invalid_fixture_training_label_fails_cleanly(self):
        model = build_model("resnet18_hierarchical", seed=42)
        with self.assertRaisesRegex(ValueError, "Etiqueta inválida"):
            train_fixture_hierarchical_heads(model, [(fixture_image(0), "POTATO"),
                                                      (fixture_image(3), 3),
                                                      (fixture_image(None), None)],
                                             TensorSpec(), steps=1, learning_rate=.01)

    def test_build_never_downloads_base_weights(self):
        with patch("torch.hub.load_state_dict_from_url", side_effect=AssertionError("download")):
            model = build_model("mobilenet_v3_small", seed=42)
        self.assertIsInstance(model, torch.nn.Module)

    def test_same_config_reproduces_weight_hash(self):
        repeat = run_cpu_smoke(self.config, "mobilenet_v3_small", self.root / "repeat")
        self.assertEqual(repeat["weights_sha256"], self.joint["weights_sha256"])
        self.assertEqual(repeat["losses"], self.joint["losses"])
        hierarchical_repeat = run_cpu_smoke(self.config, "resnet18_hierarchical", self.root / "hierarchical-repeat")
        self.assertEqual(hierarchical_repeat["weights_sha256"], self.hierarchical["weights_sha256"])
        self.assertEqual(hierarchical_repeat["fixture_crop_policy"], self.hierarchical["fixture_crop_policy"])

    def test_validation_comparison_cannot_select_release(self):
        report = compare_fixture_models(Path(self.joint["checkpoint"]), Path(self.hierarchical["checkpoint"]))
        self.assertEqual(report["scope"], "VAL_FIXTURE_ONLY")
        self.assertIsNone(report["selected_for_release"])
        self.assertFalse(report["g0_approved"])
        self.assertFalse(report["g2_approved"])
        self.assertEqual(set(report["results"]), {"joint", "hierarchical"})
        self.assertEqual(report["results"]["joint"]["accepted_positives_of_7"], 7)
        self.assertEqual(report["results"]["hierarchical"]["correct_classes_of_7"], 7)
        self.assertEqual(report["results"]["hierarchical"]["accepted_positives_of_7"], 7)
        self.assertEqual(report["results"]["hierarchical"]["negative_rejections_of_1"], 1)
        self.assertEqual(report["technical_fixture_winner"], "hierarchical")

    def test_fixture_evaluation_and_package_preserve_scope_and_integrity(self):
        manifest = Path(self.hierarchical["checkpoint"])
        report = evaluate_fixture_checkpoint(manifest)
        self.assertEqual(report["scope"], "VAL_FIXTURE_ONLY")
        self.assertIsNone(report["approval"])
        self.assertIsNone(report["selected_for_release"])
        self.assertEqual(report["correct_positive_patterns_of_7"], 7)
        self.assertEqual(report["rejected_negative_patterns_of_1"], 1)
        evaluation = self.root / "hierarchical-evaluation.json"
        evaluation.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        package = self.root / "technical-fixture.zip"
        result = package_fixture_checkpoint(manifest, evaluation, package)
        self.assertEqual(result["status"], "TECHNICAL_FIXTURE_ONLY")
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(set(archive.namelist()), {"fixture-checkpoint.json", "fixture-weights.safetensors",
                                                       "fixture-evaluation.json", "fixture-index.json"})
            index = json.loads(archive.read("fixture-index.json"))
            self.assertEqual(index["status"], "FIXTURE_ONLY")
            self.assertIsNone(index["approval"])
            self.assertIsNone(index["selected_for_release"])
        with self.assertRaisesRegex(ValueError, "ya existe"):
            package_fixture_checkpoint(manifest, evaluation, package)

    def test_fixture_package_rejects_mismatched_evaluation(self):
        manifest = Path(self.hierarchical["checkpoint"])
        evaluation = self.root / "forged-evaluation.json"
        forged = evaluate_fixture_checkpoint(manifest)
        forged["correct_positive_patterns_of_7"] = 0
        evaluation.write_text(json.dumps(forged), encoding="utf-8")
        output = self.root / "forged-fixture.zip"
        with self.assertRaisesRegex(ValueError, "alterada"):
            package_fixture_checkpoint(manifest, evaluation, output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
