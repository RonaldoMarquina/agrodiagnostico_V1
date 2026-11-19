"""Pruebas unitarias para el motor de evaluación, métricas G0 y casos de tamaño cero."""
import math
import unittest

from agro_ml.evaluation.metrics import (
    compute_class_metrics,
    compute_entropy,
    compute_risk_coverage,
    generate_evaluation_report,
)


class TestEvaluationMetrics(unittest.TestCase):
    def test_hand_crafted_known_case_metrics(self):
        # 3 clases con casos conocidos
        # Clase 0: 2 muestras verdaderas, 2 predichas bien (TP=2, FP=0, FN=0) -> Prec=1.0, Rec=1.0, F1=1.0
        # Clase 1: 2 muestras verdaderas, 1 predicha bien, 1 confundida con clase 2 (TP=1, FP=0, FN=1) -> Prec=1.0, Rec=0.5, F1=0.6667
        # Clase 2: 2 muestras verdaderas, 2 predichas bien, pero recibió 1 FP de clase 1 (TP=2, FP=1, FN=0) -> Prec=2/3=0.6667, Rec=1.0, F1=0.8
        y_true = [0, 0, 1, 1, 2, 2]
        y_pred = [0, 0, 1, 2, 2, 2]
        classes = ["CLASS_A", "CLASS_B", "CLASS_C"]

        metrics = compute_class_metrics(y_true, y_pred, classes)

        self.assertEqual(metrics["per_class"]["CLASS_A"]["precision"], 1.0)
        self.assertEqual(metrics["per_class"]["CLASS_A"]["recall"], 1.0)
        self.assertEqual(metrics["per_class"]["CLASS_A"]["f1"], 1.0)

        self.assertEqual(metrics["per_class"]["CLASS_B"]["precision"], 1.0)
        self.assertEqual(metrics["per_class"]["CLASS_B"]["recall"], 0.5)
        self.assertEqual(metrics["per_class"]["CLASS_B"]["f1"], 0.6667)

        self.assertEqual(metrics["per_class"]["CLASS_C"]["precision"], 0.6667)
        self.assertEqual(metrics["per_class"]["CLASS_C"]["recall"], 1.0)
        self.assertEqual(metrics["per_class"]["CLASS_C"]["f1"], 0.8)

        expected_macro_f1 = round((1.0 + 0.6667 + 0.8) / 3.0, 4)
        self.assertEqual(metrics["macro_f1"], expected_macro_f1)
        self.assertEqual(metrics["accuracy"], round(5 / 6, 4))

    def test_zero_samples_handling_without_fictitious_metrics(self):
        """Verifica que clases o particiones vacías no inventen métricas 1.0 o 0.9."""
        # Clase C no tiene ninguna muestra
        y_true = [0, 0, 1, 1]
        y_pred = [0, 0, 1, 1]
        classes = ["CLASS_A", "CLASS_B", "CLASS_EMPTY"]

        metrics = compute_class_metrics(y_true, y_pred, classes)
        self.assertEqual(metrics["per_class"]["CLASS_EMPTY"]["support"], 0)
        self.assertIsNone(metrics["per_class"]["CLASS_EMPTY"]["f1"])
        self.assertIsNone(metrics["per_class"]["CLASS_EMPTY"]["precision"])
        self.assertIsNone(metrics["per_class"]["CLASS_EMPTY"]["recall"])

        # Evaluación sobre dataset totalmente vacío
        empty_report = generate_evaluation_report(
            dataset_split="TEST",
            y_true=[],
            y_pred=[],
            confidences=[],
            class_names=classes,
        )
        self.assertEqual(empty_report.total_samples, 0)
        self.assertIsNone(empty_report.accuracy)
        self.assertIsNone(empty_report.macro_f1)
        self.assertIsNone(empty_report.crop_accuracy)
        self.assertIsNone(empty_report.unsupported_crop_abstention)
        self.assertIsNone(empty_report.negative_samples_fpr)

    def test_crop_accuracy_and_rejection_metrics(self):
        crops_true = ["POTATO", "POTATO", "MAIZE", "MAIZE"]
        crops_pred = ["POTATO", "MAIZE", "MAIZE", "MAIZE"]

        report = generate_evaluation_report(
            dataset_split="VAL",
            y_true=[0, 1, 2, 3],
            y_pred=[0, 2, 2, 3],
            confidences=[0.9, 0.7, 0.85, 0.95],
            class_names=["P1", "P2", "M1", "M2"],
            crops_true=crops_true,
            crops_pred=crops_pred,
            out_of_domain_rejected_count=19,
            out_of_domain_total=20,
            negative_false_positives=1,
            negative_total=50,
            bad_image_rejected_count=10,
            bad_image_total=10,
            latency_measurements_ms=[40.0, 50.0, 60.0],
        )

        self.assertEqual(report.crop_accuracy, 0.75)  # 3/4 correctos
        self.assertEqual(report.unsupported_crop_abstention, 0.95)  # 19/20
        self.assertEqual(report.negative_samples_fpr, 0.02)  # 1/50
        self.assertEqual(report.bad_image_rejection_rate, 1.0)  # 10/10
        self.assertEqual(report.latency_median_ms, 50.0)
        self.assertIsNotNone(report.brier_score)

    def test_risk_coverage_curve(self):
        confidences = [0.95, 0.85, 0.75, 0.65, 0.55]
        accuracies = [1, 1, 1, 0, 0]

        curve = compute_risk_coverage(confidences, accuracies, num_thresholds=5)
        self.assertEqual(len(curve), 6)
        # A umbral 0.0, cobertura 100% y accuracy 3/5 = 0.60
        self.assertEqual(curve[0]["threshold"], 0.0)
        self.assertEqual(curve[0]["coverage"], 1.0)
        self.assertEqual(curve[0]["accuracy"], 0.6)

    def test_shannon_entropy(self):
        # Distribución uniforme tiene entropía máxima
        ent_uniform = compute_entropy([0.5, 0.5])
        # Distribución con certeza tiene entropía 0
        ent_certain = compute_entropy([1.0, 0.0])

        self.assertAlmostEqual(ent_uniform, math.log(2), places=3)
        self.assertEqual(ent_certain, 0.0)


if __name__ == "__main__":
    unittest.main()
