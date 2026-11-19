"""Pruebas unitarias para la arquitectura alternativa jerárquica y filtros de rechazo técnico."""
import json
from pathlib import Path
import tempfile
import unittest

from agro_ml.config import ModelConfig
from agro_ml.models.hierarchical import (
    HierarchicalAlternativeClassifier,
    MAIZE_CLASSES,
    POTATO_CLASSES,
)

ROOT = Path(__file__).resolve().parents[2]


class TestAlternativeHierarchicalModel(unittest.TestCase):
    def setUp(self):
        self.config_path = ROOT / "ml/configs/alternative_resnet18.json"
        self.config = ModelConfig.from_file(self.config_path)

    def test_quality_filter_rejects_flat_or_blank_image(self):
        model = HierarchicalAlternativeClassifier(crop_detection_threshold=0.75, seed=42)

        # Vector completamente plano (sin textura foliar)
        flat_features = [0.0] * 64
        pred = model.predict(flat_features)
        self.assertEqual(pred["status"], "ABSTENTION")
        self.assertEqual(pred["reason_code"], "BAD_IMAGE")
        self.assertIsNone(pred["class_code"])
        self.assertIsNone(pred["crop_code"])

    def test_out_of_domain_unsupported_crop_rejection(self):
        """Verifica que cultivos desconocidos sean rechazados sin argmax forzado."""
        model = HierarchicalAlternativeClassifier(crop_detection_threshold=0.85, seed=42)

        # Simular señal de "OTHER_CROP" en la Etapa 1
        # Ajustamos los pesos de cultivo para forzar alta probabilidad de OOD
        model.crop_bias = [-2.0, -2.0, 5.0]  # OTHER_CROP gana fuertemente

        test_features = [0.4] * 64
        # Agregar variación para pasar el filtro de calidad
        for i in range(10):
            test_features[i] = 0.8

        pred = model.predict(test_features)
        self.assertEqual(pred["status"], "ABSTENTION")
        self.assertEqual(pred["reason_code"], "UNSUPPORTED_CROP")
        self.assertIsNone(pred["class_code"])
        self.assertIsNone(pred["crop_code"])

    def test_potato_pipeline_routing(self):
        model = HierarchicalAlternativeClassifier(crop_detection_threshold=0.70, seed=42)
        # Forzar reconocimiento de Papa
        model.crop_bias = [5.0, -2.0, -2.0]

        test_features = [0.3] * 64
        for i in range(12):
            test_features[i] = 0.7

        pred = model.predict(test_features)
        self.assertEqual(pred["status"], "PREDICTION")
        self.assertIsNone(pred["reason_code"])
        self.assertEqual(pred["crop_code"], "POTATO")
        self.assertIn(pred["class_code"], POTATO_CLASSES)
        self.assertNotIn(pred["class_code"], MAIZE_CLASSES)

    def test_maize_pipeline_routing(self):
        model = HierarchicalAlternativeClassifier(crop_detection_threshold=0.70, seed=42)
        # Forzar reconocimiento de Maíz
        model.crop_bias = [-2.0, 5.0, -2.0]

        test_features = [0.3] * 64
        for i in range(12):
            test_features[i] = 0.7

        pred = model.predict(test_features)
        self.assertEqual(pred["status"], "PREDICTION")
        self.assertIsNone(pred["reason_code"])
        self.assertEqual(pred["crop_code"], "MAIZE")
        self.assertIn(pred["class_code"], MAIZE_CLASSES)
        self.assertNotIn(pred["class_code"], POTATO_CLASSES)

    def test_checkpoint_saving_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ckpt_path = Path(temp_dir) / "hierarchical_ckpt.json"
            model = HierarchicalAlternativeClassifier(seed=42)
            model.save_checkpoint(
                output_path=ckpt_path,
                config=self.config,
                epochs_trained=3,
                is_synthetic_fixture=True,
            )

            self.assertTrue(ckpt_path.is_file())
            loaded_model, meta = HierarchicalAlternativeClassifier.load_checkpoint(ckpt_path)
            self.assertEqual(meta["model_type"], "HIERARCHICAL_TWO_STAGE")
            self.assertEqual(loaded_model.crop_bias, model.crop_bias)

            # Alterar el archivo
            raw = ckpt_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            data["weights_data"]["crop_bias"][0] += 0.5
            ckpt_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Integridad de checkpoint jerárquico alterada"):
                HierarchicalAlternativeClassifier.load_checkpoint(ckpt_path)


if __name__ == "__main__":
    unittest.main()
