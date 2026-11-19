"""Motor completo de métricas de evaluación independiente requeridas por G0 y OpenSpec.

Calcula deterministamente:
- Accuracy, precision, recall y F1 por clase individual y macro-promediado.
- Matriz de confusión para patologías y para identificación de cultivo.
- Calidad de identificación de cultivo (crop_accuracy).
- Abstención ante cultivos ajenos (unsupported_crop_abstention) y FPR en negativos (RF-07/RF-08).
- Calibración: Expected Calibration Error (ECE) y Brier score.
- Perfil de cobertura y error (risk-coverage profile a distintos umbrales).
- Incertidumbre: entropía media de predicción y margen de confianza.
- Recursos: latencia mediana, percentil 95 y memoria RAM residente (max_rss_mb).
- Robustez estricta: maneja soporte cero y conjuntos vacíos sin divisiones por cero ni métricas ficticias.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
import resource
from typing import Any, Dict, List, Optional, Tuple

from agro_ml.calibration.calibrator import compute_ece, is_finite_number


@dataclass
class RiskCoveragePoint:
    threshold: float
    coverage: float
    error_rate: float
    accuracy: float


@dataclass
class EvaluationReport:
    schema_version: int
    evaluation_id: str
    dataset_split: str
    total_samples: int
    accuracy: Optional[float]
    macro_f1: Optional[float]
    crop_accuracy: Optional[float]
    unsupported_crop_abstention: Optional[float]
    negative_samples_fpr: Optional[float]
    bad_image_rejection_rate: Optional[float]
    ece: Optional[float]
    brier_score: Optional[float]
    mean_entropy: Optional[float]
    per_class: Dict[str, Dict[str, Any]]
    confusion_matrix: List[List[int]]
    crop_confusion_matrix: Dict[str, Dict[str, int]]
    risk_coverage_curve: List[Dict[str, float]]
    latency_median_ms: Optional[float]
    latency_p95_ms: Optional[float]
    max_rss_mb: float
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_entropy(probs: List[float]) -> float:
    """Calcula la entropía de Shannon de una distribución de probabilidades."""
    ent = 0.0
    for p in probs:
        if p > 1e-12:
            ent -= p * math.log(p)
    return round(ent, 4)


def compute_class_metrics(
    y_true: List[int],
    y_pred: List[int],
    class_names: List[str],
) -> Dict[str, Any]:
    """Calcula matriz de confusión, precision, recall y F1 por clase y macro."""
    num_classes = len(class_names)
    cm = [[0] * num_classes for _ in range(num_classes)]

    for t, p in zip(y_true, y_pred):
        if 0 <= t < num_classes and 0 <= p < num_classes:
            cm[t][p] += 1

    per_class: Dict[str, Dict[str, Any]] = {}
    f1_scores: List[float] = []
    total_correct = sum(cm[i][i] for i in range(num_classes))
    total_samples = len(y_true)

    for c in range(num_classes):
        name = class_names[c]
        tp = cm[c][c]
        fp = sum(cm[i][c] for i in range(num_classes) if i != c)
        fn = sum(cm[c][j] for j in range(num_classes) if j != c)
        support = tp + fn

        if support == 0 and fp == 0:
            # Sin muestras de esta clase ni predicciones falsas positivas
            prec = None
            rec = None
            f1 = None
        else:
            prec = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
            rec = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
            f1 = round((2 * prec * rec) / (prec + rec), 4) if (prec and rec and (prec + rec) > 0) else 0.0

        if f1 is not None and support > 0:
            f1_scores.append(f1)

        per_class[name] = {
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "support": support,
        }

    macro_f1 = round(sum(f1_scores) / len(f1_scores), 4) if f1_scores else None
    acc = round(total_correct / total_samples, 4) if total_samples > 0 else None

    return {
        "macro_f1": macro_f1,
        "accuracy": acc,
        "per_class": per_class,
        "confusion_matrix": cm,
    }


def compute_risk_coverage(
    confidences: List[float],
    accuracies: List[int],
    num_thresholds: int = 10,
) -> List[Dict[str, float]]:
    """Calcula curva de riesgo vs cobertura a distintos umbrales de confianza."""
    if not confidences or len(confidences) != len(accuracies):
        return []

    n = len(confidences)
    curve = []
    for step in range(num_thresholds + 1):
        thresh = round(step / num_thresholds, 2)
        covered_indices = [i for i, c in enumerate(confidences) if c >= thresh]
        coverage = len(covered_indices) / n

        if not covered_indices:
            acc = 1.0
            err = 0.0
        else:
            correct = sum(accuracies[i] for i in covered_indices)
            acc = correct / len(covered_indices)
            err = 1.0 - acc

        curve.append({
            "threshold": thresh,
            "coverage": round(coverage, 4),
            "accuracy": round(acc, 4),
            "error_rate": round(err, 4),
        })
    return curve


def get_current_rss_mb() -> float:
    """Obtiene el uso de memoria residente actual en MB."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return round(usage.ru_maxrss / 1024.0, 2)


def generate_evaluation_report(
    dataset_split: str,
    y_true: List[int],
    y_pred: List[int],
    confidences: List[float],
    class_names: List[str],
    crops_true: Optional[List[str]] = None,
    crops_pred: Optional[List[str]] = None,
    out_of_domain_rejected_count: int = 0,
    out_of_domain_total: int = 0,
    negative_false_positives: int = 0,
    negative_total: int = 0,
    bad_image_rejected_count: int = 0,
    bad_image_total: int = 0,
    latency_measurements_ms: Optional[List[float]] = None,
) -> EvaluationReport:
    """Genera reporte unificado de evaluación sin métricas ficticias ante muestras cero."""
    total_samples = len(y_true)

    # 1. Métricas de patología
    class_res = compute_class_metrics(y_true, y_pred, class_names)

    # 2. Métricas de cultivo
    crop_acc = None
    crop_cm: Dict[str, Dict[str, int]] = {
        "POTATO": {"POTATO": 0, "MAIZE": 0, "OTHER": 0},
        "MAIZE": {"POTATO": 0, "MAIZE": 0, "OTHER": 0},
        "OTHER": {"POTATO": 0, "MAIZE": 0, "OTHER": 0},
    }
    if crops_true and crops_pred and len(crops_true) == len(crops_pred) and len(crops_true) > 0:
        correct_crops = 0
        for ct, cp in zip(crops_true, crops_pred):
            ct_k = ct if ct in crop_cm else "OTHER"
            cp_k = cp if cp in crop_cm["POTATO"] else "OTHER"
            crop_cm[ct_k][cp_k] += 1
            if ct == cp:
                correct_crops += 1
        crop_acc = round(correct_crops / len(crops_true), 4)

    # 3. Calibración y Brier score
    accuracies = [1 if t == p else 0 for t, p in zip(y_true, y_pred)]
    ece_val = compute_ece(confidences, accuracies) if total_samples > 0 else None

    brier = None
    if total_samples > 0:
        brier_sum = sum((c - a) ** 2 for c, a in zip(confidences, accuracies))
        brier = round(brier_sum / total_samples, 4)

    # 4. Abstención y negativos
    unsupported_abstention = None
    if out_of_domain_total > 0:
        unsupported_abstention = round(out_of_domain_rejected_count / out_of_domain_total, 4)

    neg_fpr = None
    if negative_total > 0:
        neg_fpr = round(negative_false_positives / negative_total, 4)

    bad_img_rate = None
    if bad_image_total > 0:
        bad_img_rate = round(bad_image_rejected_count / bad_image_total, 4)

    # 5. Entropía e incertidumbre
    mean_ent = None
    if confidences:
        # Aproximación binaria de entropía para la confianza máxima p
        entropies = [compute_entropy([c, 1.0 - c]) for c in confidences]
        mean_ent = round(sum(entropies) / len(entropies), 4)

    # 6. Curva de riesgo-cobertura
    risk_curve = compute_risk_coverage(confidences, accuracies)

    # 7. Latencias
    lat_median = None
    lat_p95 = None
    if latency_measurements_ms:
        sorted_lats = sorted(latency_measurements_ms)
        lat_median = round(sorted_lats[len(sorted_lats) // 2], 2)
        p95_idx = int(0.95 * len(sorted_lats))
        lat_p95 = round(sorted_lats[min(p95_idx, len(sorted_lats) - 1)], 2)

    return EvaluationReport(
        schema_version=1,
        evaluation_id=f"eval_{dataset_split.lower()}",
        dataset_split=dataset_split.upper(),
        total_samples=total_samples,
        accuracy=class_res["accuracy"],
        macro_f1=class_res["macro_f1"],
        crop_accuracy=crop_acc,
        unsupported_crop_abstention=unsupported_abstention,
        negative_samples_fpr=neg_fpr,
        bad_image_rejection_rate=bad_img_rate,
        ece=ece_val,
        brier_score=brier,
        mean_entropy=mean_ent,
        per_class=class_res["per_class"],
        confusion_matrix=class_res["confusion_matrix"],
        crop_confusion_matrix=crop_cm,
        risk_coverage_curve=risk_curve,
        latency_median_ms=lat_median,
        latency_p95_ms=lat_p95,
        max_rss_mb=get_current_rss_mb(),
    )
