"""Pruebas unitarias para calibración escalar, umbrales y manejo de valores no finitos."""
import math
import unittest

from agro_ml.calibration.calibrator import (
    PlattCalibrator,
    compute_ece,
    is_finite_number,
    sigmoid,
)


class TestPlattCalibrator(unittest.TestCase):
    def setUp(self):
        self.calibrator = PlattCalibrator(
            parameters={
                "POTATO_EARLY_BLIGHT": {"slope": 1.25, "intercept": -0.15},
                "POTATO_LATE_BLIGHT": {"slope": 1.10, "intercept": -0.10},
            },
            thresholds={
                "POTATO_EARLY_BLIGHT": 0.70,
                "POTATO_LATE_BLIGHT": 0.65,
            },
            default_threshold=0.60,
        )

    def test_calibrate_valid_class(self):
        conf = self.calibrator.calibrate("POTATO_EARLY_BLIGHT", 0.80)
        self.assertIsNotNone(conf)
        self.assertIsInstance(conf, float)
        expected_z = 1.25 * 0.80 - 0.15
        expected_p = round(sigmoid(expected_z), 4)
        self.assertEqual(conf, expected_p)

    def test_absence_of_calibrator_never_falls_back_to_synthetic_0_9(self):
        """Verifica que la ausencia de calibrador no invente un 0.9 sintético."""
        # Clase sin parámetros configurados
        conf = self.calibrator.calibrate("UNCONFIGURED_CLASS", 0.85)
        self.assertIsNone(conf, "Debe retornar None en ausencia de calibrador, nunca un 0.9 inventado")
        self.assertNotEqual(conf, 0.9)

        decision = self.calibrator.evaluate_publication("UNCONFIGURED_CLASS", 0.75)
        self.assertFalse(decision.calibrated)
        self.assertIsNone(decision.calibrated_confidence)
        self.assertNotEqual(decision.calibrated_confidence, 0.9)

    def test_evaluate_publication_thresholds(self):
        # 1. Score inferior al umbral (0.50 < 0.70)
        dec_low = self.calibrator.evaluate_publication("POTATO_EARLY_BLIGHT", 0.40)
        self.assertFalse(dec_low.is_published)
        self.assertEqual(dec_low.status, "ABSTENTION")
        self.assertEqual(dec_low.reason_code, "LOW_CONFIDENCE")

        # 2. Score igual o superior al umbral
        dec_high = self.calibrator.evaluate_publication("POTATO_EARLY_BLIGHT", 0.95)
        self.assertTrue(dec_high.is_published)
        self.assertEqual(dec_high.status, "PREDICTION")
        self.assertIsNone(dec_high.reason_code)

    def test_reject_non_finite_values(self):
        for bad_val in [float("nan"), float("inf"), float("-inf")]:
            with self.subTest(val=bad_val):
                with self.assertRaisesRegex(ValueError, "no finito"):
                    self.calibrator.calibrate("POTATO_EARLY_BLIGHT", bad_val)

                with self.assertRaisesRegex(ValueError, "no finito"):
                    self.calibrator.evaluate_publication("POTATO_EARLY_BLIGHT", bad_val)

    def test_fit_class_determines_parameters_and_threshold(self):
        calib = PlattCalibrator()
        raw_scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.85, 0.9, 0.95]
        labels = [0, 0, 0, 1, 1, 1, 1, 1]

        slope, intercept, thresh = calib.fit_class(raw_scores, labels, "MAIZE_COMMON_RUST")
        self.assertGreater(slope, 0.0)
        self.assertLess(intercept, 0.0)
        self.assertGreaterEqual(thresh, 0.50)
        self.assertLessEqual(thresh, 0.95)

        # Calibrar ahora con los parámetros aprendidos
        conf = calib.calibrate("MAIZE_COMMON_RUST", 0.90)
        self.assertIsNotNone(conf)
        self.assertGreater(conf, 0.70)

    def test_compute_ece_calculation(self):
        confidences = [0.9, 0.8, 0.7, 0.6, 0.2, 0.1]
        accuracies = [1, 1, 1, 0, 0, 0]
        ece = compute_ece(confidences, accuracies, num_bins=5)
        self.assertGreaterEqual(ece, 0.0)
        self.assertLessEqual(ece, 1.0)

        # Caso vacío retorna 0.0 sin error
        self.assertEqual(compute_ece([], []), 0.0)


if __name__ == "__main__":
    unittest.main()
