"""Pruebas unitarias para preprocesado único, equivalencia de tensor y restricciones de partición."""
import io
from pathlib import Path
import unittest

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None  # type: ignore
    HAS_PIL = False

from agro_ml.data.preprocessing import (
    apply_transforms,
    augment_image_bytes,
    measure_cpu_preprocessing,
    preprocess_image,
    validate_image_bytes,
)


def create_image_bytes(size=(300, 300), color=(100, 180, 80), fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=fmt)
    return buf.getvalue()


@unittest.skipUnless(HAS_PIL, "Pillow requerido para pruebas de preprocesamiento")
class TestPreprocessing(unittest.TestCase):
    def test_valid_image_features_shape_and_bounds(self):
        # Probar JPEG y PNG, diferentes orientaciones (cuadrada, horizontal, vertical)
        sizes = [(250, 250), (400, 250), (250, 400)]
        for fmt in ["JPEG", "PNG"]:
            for size in sizes:
                with self.subTest(fmt=fmt, size=size):
                    raw = create_image_bytes(size=size, fmt=fmt)
                    w, h, detected_fmt = validate_image_bytes(raw)
                    self.assertEqual(w, size[0])
                    self.assertEqual(h, size[1])
                    self.assertEqual(detected_fmt, fmt)

                    features = preprocess_image(raw)
                    self.assertEqual(len(features), 64)
                    for val in features:
                        self.assertIsInstance(val, float)
                        self.assertFalse(val != val, "El valor es NaN")
                        self.assertGreaterEqual(val, 0.0)
                        self.assertLessEqual(val, 1.0)

    def test_tensor_equivalence_for_same_file(self):
        """Verifica equivalencia de tensor bit a bit e idempotencia."""
        raw = create_image_bytes(size=(320, 320), color=(140, 120, 60))
        features_run1 = preprocess_image(raw)
        features_run2 = preprocess_image(raw)
        features_run3 = preprocess_image(raw)

        self.assertEqual(features_run1, features_run2)
        self.assertEqual(features_run2, features_run3)

    def test_invalid_inputs_rejected(self):
        # 1. Bytes vacíos
        with self.assertRaisesRegex(ValueError, "vacíos"):
            validate_image_bytes(b"")

        # 2. Bytes corruptos
        with self.assertRaises(ValueError):
            validate_image_bytes(b"NotAnImageHeaderDataGarbage" * 5)

        # 3. Dimensión menor al mínimo (200px)
        small_bytes = create_image_bytes(size=(150, 150))
        with self.assertRaisesRegex(ValueError, "insuficiente"):
            validate_image_bytes(small_bytes)

        # 4. Formato no soportado (GIF)
        buf = io.BytesIO()
        im = Image.new("RGB", (250, 250), color=(100, 100, 100))
        im.save(buf, format="GIF")
        with self.assertRaisesRegex(ValueError, "no soportado"):
            validate_image_bytes(buf.getvalue())

    def test_augmentations_exclusive_to_train(self):
        raw = create_image_bytes(size=(250, 250))

        # En TRAIN: permitido
        aug_bytes = augment_image_bytes(raw, split="TRAIN", seed=42)
        self.assertIsInstance(aug_bytes, bytes)
        self.assertGreater(len(aug_bytes), 0)

        feats_aug = apply_transforms(raw, split="TRAIN", augment=True, seed=42)
        self.assertEqual(len(feats_aug), 64)

        # En VAL, TEST, EXTERNAL con augment=True: estrictamente prohibido
        for forbidden_split in ["VAL", "TEST", "EXTERNAL"]:
            with self.subTest(split=forbidden_split):
                with self.assertRaisesRegex(ValueError, "prohibida"):
                    augment_image_bytes(raw, split=forbidden_split)

                with self.assertRaisesRegex(ValueError, "prohibidas"):
                    apply_transforms(raw, split=forbidden_split, augment=True)

        # En VAL, TEST, EXTERNAL con augment=False: permitido
        for eval_split in ["VAL", "TEST", "EXTERNAL"]:
            with self.subTest(split=eval_split):
                feats_eval = apply_transforms(raw, split=eval_split, augment=False)
                self.assertEqual(len(feats_eval), 64)

    def test_cpu_performance_benchmark_within_g0_budget(self):
        raw = create_image_bytes(size=(300, 300))
        benchmark = measure_cpu_preprocessing(raw, iterations=15)

        self.assertTrue(benchmark["meets_budget"])
        self.assertLess(benchmark["latency_median_ms"], 1000.0)
        self.assertLess(benchmark["latency_p95_ms"], 2500.0)


if __name__ == "__main__":
    unittest.main()
