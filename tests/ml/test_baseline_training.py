"""Pruebas unitarias para línea base conjunta, semillas, checkpoints y procedencia."""
import json
from pathlib import Path
import random
import tempfile
import unittest

from agro_ml.config import ModelConfig
from agro_ml.models.baseline import JointBaselineClassifier

ROOT = Path(__file__).resolve().parents[2]


class TestBaselineTraining(unittest.TestCase):
    def setUp(self):
        self.config_path = ROOT / "ml/configs/baseline_mobilenetv3.json"
        self.config = ModelConfig.from_file(self.config_path)

    def test_deterministic_initialization_with_seed(self):
        model1 = JointBaselineClassifier(architecture="mobilenet_v3_small", seed=42)
        model2 = JointBaselineClassifier(architecture="mobilenet_v3_small", seed=42)
        model3 = JointBaselineClassifier(architecture="mobilenet_v3_small", seed=99)

        self.assertEqual(model1.weights, model2.weights)
        self.assertNotEqual(model1.weights, model3.weights)

    def test_forward_and_prediction_contract(self):
        model = JointBaselineClassifier(architecture="mobilenet_v3_small", seed=42)
        features = [0.5] * 64
        pred = model.predict(features)

        self.assertIn("class_code", pred)
        self.assertIn("crop_code", pred)
        self.assertIn(pred["crop_code"], ("POTATO", "MAIZE"))
        self.assertGreaterEqual(pred["raw_score"], 0.0)
        self.assertLessEqual(pred["raw_score"], 1.0)
        self.assertAlmostEqual(sum(pred["probabilities"]), 1.0, places=4)

    def test_training_decreases_loss_on_fixture_dataset(self):
        model = JointBaselineClassifier(architecture="mobilenet_v3_small", seed=42)

        # Crear conjunto fixture sintético separable
        rng = random.Random(42)
        samples = []
        for i in range(20):
            target_class = i % 7
            # Vector con señal clara en la posición target_class
            feats = [0.1 * rng.random() for _ in range(64)]
            feats[target_class] = 1.0
            samples.append((feats, target_class))

        initial_loss = model.train_epoch(samples, learning_rate=0.05)
        for _ in range(10):
            last_loss = model.train_epoch(samples, learning_rate=0.05)

        self.assertLess(last_loss, initial_loss)

    def test_checkpoint_saving_and_loading_with_sha256(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ckpt_path = Path(temp_dir) / "baseline_ckpt.json"
            model = JointBaselineClassifier(architecture="mobilenet_v3_small", seed=42)
            model.save_checkpoint(
                output_path=ckpt_path,
                config=self.config,
                epochs_trained=5,
                loss=0.35,
                is_synthetic_fixture=True,
            )

            self.assertTrue(ckpt_path.is_file())
            data = json.loads(ckpt_path.read_text(encoding="utf-8"))

            # Verificar procedencia y tipo explícito
            self.assertEqual(data["execution_type"], "FIXTURE_DRY_RUN")
            self.assertEqual(data["architecture_provenance"]["license"], "PENDING_REVIEW")
            self.assertEqual(len(data["weights_sha256"]), 64)

            # Cargar y verificar predicciones idénticas
            loaded_model, loaded_meta = JointBaselineClassifier.load_checkpoint(ckpt_path)
            self.assertEqual(loaded_model.weights, model.weights)
            self.assertEqual(loaded_model.bias, model.bias)

            test_feats = [0.2] * 64
            pred_orig = model.predict(test_feats)
            pred_loaded = loaded_model.predict(test_feats)
            self.assertEqual(pred_orig, pred_loaded)

    def test_checkpoint_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ckpt_path = Path(temp_dir) / "baseline_ckpt.json"
            model = JointBaselineClassifier(architecture="mobilenet_v3_small", seed=42)
            model.save_checkpoint(
                output_path=ckpt_path,
                config=self.config,
                epochs_trained=5,
                loss=0.35,
            )

            # Alterar un peso en el archivo
            raw_text = ckpt_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            data["bias"][0] += 1.0  # alteración
            ckpt_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Integridad de checkpoint comprometida"):
                JointBaselineClassifier.load_checkpoint(ckpt_path)


if __name__ == "__main__":
    unittest.main()
