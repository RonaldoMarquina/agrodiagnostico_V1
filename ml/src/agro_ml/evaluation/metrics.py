"""Motor técnico de métricas; sus fixtures no acreditan G0 ni G2.

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
import statistics
from typing import Any, Dict, List, Optional

from agro_ml.calibration.calibrator import compute_ece, is_finite_number


@dataclass
class RiskCoveragePoint:
    threshold: float
    coverage: float
    error_rate: Optional[float]
    accuracy: Optional[float]


@dataclass
class EvaluationReport:
    schema_version: int
    evaluation_id: str
    dataset_split: str
    total_samples: int
    accuracy: Optional[float]
    macro_precision: Optional[float]
    macro_recall: Optional[float]
    macro_f1: Optional[float]
    crop_accuracy: Optional[float]
    unsupported_crop_abstention: Optional[float]
    negative_samples_fpr: Optional[float]
    bad_image_rejection_rate: Optional[float]
    ece: Optional[float]
    brier_score: Optional[float]
    mean_entropy: Optional[float]
    mean_margin: Optional[float]
    non_conclusive_rate: Optional[float]
    selective_coverage: Optional[float]
    selective_error_rate: Optional[float]
    decision_counts: Dict[str, Optional[int]]
    negative_counts: Dict[str, int]
    negative_count_source: str
    per_class: Dict[str, Dict[str, Any]]
    confusion_matrix: List[List[int]]
    crop_confusion_matrix: Dict[str, Dict[str, int]]
    risk_coverage_curve: List[Dict[str, Optional[float]]]
    latency_median_ms: Optional[float]
    latency_p95_ms: Optional[float]
    max_rss_mb: Optional[float]
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_entropy(probs: List[float]) -> float:
    """Calcula la entropía de Shannon de una distribución de probabilidades."""
    if not probs or any(isinstance(p, bool) or not is_finite_number(p) or not 0 <= p <= 1 for p in probs) or abs(sum(probs) - 1.0) > 1e-6:
        raise ValueError("La distribución debe ser finita, no negativa y sumar 1")
    ent = 0.0
    for p in probs:
        if p > 1e-12:
            ent -= p * math.log(p)
    return round(ent, 4)


def compute_class_metrics(
    y_true: List[int],
    y_pred: List[int],
    class_names: List[str],
    abstained: Optional[List[bool]] = None,
) -> Dict[str, Any]:
    """Calcula métricas visibles si se aporta abstención; esta es FN de la clase real."""
    if not class_names or any(not isinstance(name, str) or not name for name in class_names) or len(set(class_names)) != len(class_names):
        raise ValueError("Se requieren nombres de clase únicos")
    if len(y_true) != len(y_pred):
        raise ValueError("Etiquetas y predicciones tienen distintas longitudes")
    publication_known = abstained is not None
    if abstained is None:
        abstained = [False] * len(y_true)
    if len(abstained) != len(y_true) or any(type(value) is not bool for value in abstained):
        raise ValueError("Máscara de abstención inválida")
    num_classes = len(class_names)
    cm = [[0] * num_classes for _ in range(num_classes)]
    abstained_by_class = [0] * num_classes

    for t, p, did_abstain in zip(y_true, y_pred, abstained):
        if type(t) is not int or type(p) is not int or not 0 <= t < num_classes or not 0 <= p < num_classes:
            raise ValueError("Índice de clase inválido")
        if did_abstain:
            abstained_by_class[t] += 1
        else:
            cm[t][p] += 1

    per_class: Dict[str, Dict[str, Any]] = {}
    f1_scores: List[float] = []
    precision_scores: List[float] = []
    recall_scores: List[float] = []
    total_correct = sum(cm[i][i] for i in range(num_classes))
    total_samples = len(y_true)

    for c in range(num_classes):
        name = class_names[c]
        tp = cm[c][c]
        fp = sum(cm[i][c] for i in range(num_classes) if i != c)
        fn = sum(cm[c][j] for j in range(num_classes) if j != c)
        support = tp + fn + abstained_by_class[c]
        fn += abstained_by_class[c]
        accepted = sum(cm[c])

        prec_raw = tp / (tp + fp) if (tp + fp) > 0 else (0.0 if support else None)
        rec_raw = tp / support if support else None
        f1_raw = 2 * tp / (support + tp + fp) if support else None
        prec = round(prec_raw, 4) if prec_raw is not None else None
        rec = round(rec_raw, 4) if rec_raw is not None else None
        f1 = round(f1_raw, 4) if f1_raw is not None else None

        if f1_raw is not None:
            f1_scores.append(f1_raw)
            precision_scores.append(prec_raw)
            recall_scores.append(rec_raw)

        per_class[name] = {
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "support": support,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "accepted_count": accepted if publication_known else None,
            "abstained_count": abstained_by_class[c] if publication_known else None,
            "coverage": round(accepted / support, 4) if publication_known and support else None,
        }

    # No esconder clases sin muestras bajo un promedio de las restantes.
    complete = len(f1_scores) == num_classes
    macro_f1 = round(statistics.mean(f1_scores), 4) if complete else None
    acc = round(total_correct / total_samples, 4) if total_samples > 0 else None

    return {
        "macro_f1": macro_f1,
        "macro_precision": round(statistics.mean(precision_scores), 4) if complete else None,
        "macro_recall": round(statistics.mean(recall_scores), 4) if complete else None,
        "accuracy": acc,
        "per_class": per_class,
        "confusion_matrix": cm,
    }


def compute_risk_coverage(
    confidences: List[float],
    accuracies: List[int],
    num_thresholds: int = 10,
) -> List[Dict[str, Optional[float]]]:
    """Calcula curva de riesgo vs cobertura a distintos umbrales de confianza."""
    if len(confidences) != len(accuracies) or type(num_thresholds) is not int or num_thresholds < 1:
        raise ValueError("Curva de cobertura: longitudes o umbrales inválidos")
    if any(isinstance(c, bool) or not is_finite_number(c) or not 0 <= c <= 1 for c in confidences):
        raise ValueError("Confianza inválida")
    if any(type(correct) is not int or correct not in (0, 1) for correct in accuracies):
        raise ValueError("Acierto inválido")
    if not confidences:
        return []

    n = len(confidences)
    curve = []
    for step in range(num_thresholds + 1):
        thresh = round(step / num_thresholds, 4)
        covered_indices = [i for i, c in enumerate(confidences) if c >= thresh]
        coverage = len(covered_indices) / n

        if not covered_indices:
            acc = None
            err = None
        else:
            correct = sum(accuracies[i] for i in covered_indices)
            acc = correct / len(covered_indices)
            err = 1.0 - acc

        curve.append({
            "threshold": thresh,
            "coverage": round(coverage, 4),
            "accuracy": round(acc, 4) if acc is not None else None,
            "error_rate": round(err, 4) if err is not None else None,
        })
    return curve


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
    negative_published_classes: Optional[List[Optional[str]]] = None,
    bad_image_rejected_count: int = 0,
    bad_image_total: int = 0,
    latency_measurements_ms: Optional[List[float]] = None,
    probability_vectors: Optional[List[List[float]]] = None,
    abstained: Optional[List[bool]] = None,
    measured_peak_rss_mb: Optional[float] = None,
) -> EvaluationReport:
    """Genera reporte técnico; memoria y probabilidades requieren medidas explícitas."""
    if not isinstance(dataset_split, str) or dataset_split.upper() not in {"TRAIN", "VAL", "TEST", "EXTERNAL"}:
        raise ValueError("Partición desconocida")
    total_samples = len(y_true)

    # 1. Métricas de patología
    class_res = compute_class_metrics(y_true, y_pred, class_names, abstained)
    if len(confidences) != total_samples or any(isinstance(c, bool) or not is_finite_number(c) or not 0 <= c <= 1 for c in confidences):
        raise ValueError("Confianzas ausentes, fuera de rango o no finitas")

    # 2. Métricas de cultivo
    crop_acc = None
    crop_cm: Dict[str, Dict[str, int]] = {}
    if (crops_true is None) != (crops_pred is None):
        raise ValueError("Se requieren ambos vectores de cultivo")
    if crops_true is not None and crops_pred is not None:
        if len(crops_true) != total_samples or len(crops_pred) != total_samples:
            raise ValueError("Cultivos y muestras tienen distintas longitudes")
        crop_cm = {crop: {other: 0 for other in ("POTATO", "MAIZE", "OTHER")} for crop in ("POTATO", "MAIZE", "OTHER")}
        correct_crops = 0
        for index, (ct, cp) in enumerate(zip(crops_true, crops_pred)):
            if ct not in crop_cm or cp not in crop_cm:
                raise ValueError("Código de cultivo desconocido")
            if abstained is not None and abstained[index]:
                continue
            crop_cm[ct][cp] += 1
            if ct == cp:
                correct_crops += 1
        crop_acc = round(correct_crops / total_samples, 4) if total_samples else None

    # 3. Calibración y Brier score
    accuracies = [1 if t == p else 0 for t, p in zip(y_true, y_pred)]
    ece_val = compute_ece(confidences, accuracies) if total_samples > 0 else None

    brier = mean_ent = mean_margin = None
    if probability_vectors is not None:
        if len(probability_vectors) != total_samples:
            raise ValueError("Probabilidades y muestras tienen distintas longitudes")
        for vector in probability_vectors:
            if len(vector) != len(class_names):
                raise ValueError("Dimensión de probabilidades incompatible")
            compute_entropy(vector)
        if total_samples:
            # Brier multiclase: suma de errores cuadráticos por clase, por muestra.
            brier = round(sum(sum((p - int(c == truth)) ** 2 for c, p in enumerate(vector)) for truth, vector in zip(y_true, probability_vectors)) / total_samples, 4)
            mean_ent = round(statistics.mean(compute_entropy(vector) for vector in probability_vectors), 4)
            if len(class_names) > 1:
                mean_margin = round(statistics.mean(sorted(vector, reverse=True)[0] - sorted(vector, reverse=True)[1] for vector in probability_vectors), 4)

    # 4. Abstención y negativos
    unsupported_abstention = None
    negative_count_source = "PUBLISHED_CLASSES" if negative_published_classes is not None else "SUPPLIED_COUNTS"
    if negative_published_classes is not None:
        if not isinstance(negative_published_classes, list) or any(value is not None and value not in class_names for value in negative_published_classes):
            raise ValueError("Resultado publicado de negativo inválido")
        derived_total = len(negative_published_classes)
        derived_false_positives = sum(value is not None for value in negative_published_classes)
        if (negative_total or negative_false_positives) and (negative_total, negative_false_positives) != (derived_total, derived_false_positives):
            raise ValueError("Conteos de negativos contradicen resultados publicados")
        negative_total, negative_false_positives = derived_total, derived_false_positives
    for numerator, denominator in ((out_of_domain_rejected_count, out_of_domain_total), (negative_false_positives, negative_total), (bad_image_rejected_count, bad_image_total)):
        if type(numerator) is not int or type(denominator) is not int or not 0 <= numerator <= denominator:
            raise ValueError("Conteo de negativos o rechazos inválido")
    if out_of_domain_total > 0:
        unsupported_abstention = round(out_of_domain_rejected_count / out_of_domain_total, 4)

    neg_fpr = None
    if negative_total > 0:
        neg_fpr = round(negative_false_positives / negative_total, 4)

    bad_img_rate = None
    if bad_image_total > 0:
        bad_img_rate = round(bad_image_rejected_count / bad_image_total, 4)

    # Abstención efectiva: se informa aparte de las predicciones técnicas.
    non_conclusive_rate = selective_error_rate = selective_coverage = None
    decision_counts = {"valid_supported_class_count": total_samples, "accepted_count": None,
                       "incorrect_accepted_count": None, "abstained_count": None}
    if abstained is not None:
        decision_counts["abstained_count"] = sum(abstained)
        decision_counts["accepted_count"] = total_samples - decision_counts["abstained_count"]
        decision_counts["incorrect_accepted_count"] = sum(
            not did_abstain and truth != pred
            for truth, pred, did_abstain in zip(y_true, y_pred, abstained)
        )
        if total_samples:
            non_conclusive_rate = round(sum(abstained) / total_samples, 4)
            selective_coverage = round(decision_counts["accepted_count"] / total_samples, 4)
            if decision_counts["accepted_count"]:
                selective_error_rate = round(
                    decision_counts["incorrect_accepted_count"] / decision_counts["accepted_count"], 4
                )

    # 6. Curva de riesgo-cobertura
    risk_curve = compute_risk_coverage(confidences, accuracies)

    # 7. Latencias
    lat_median = None
    lat_p95 = None
    if latency_measurements_ms is not None:
        if len(latency_measurements_ms) != total_samples or any(isinstance(value, bool) or not is_finite_number(value) or value < 0 for value in latency_measurements_ms):
            raise ValueError("Latencias ausentes o inválidas")
    if latency_measurements_ms:
        sorted_lats = sorted(latency_measurements_ms)
        lat_median = round(statistics.median(sorted_lats), 2)
        p95_idx = math.ceil(0.95 * len(sorted_lats)) - 1
        lat_p95 = round(sorted_lats[min(p95_idx, len(sorted_lats) - 1)], 2)
    if measured_peak_rss_mb is not None and (isinstance(measured_peak_rss_mb, bool) or not is_finite_number(measured_peak_rss_mb) or measured_peak_rss_mb < 0):
        raise ValueError("Memoria medida inválida")

    return EvaluationReport(
        schema_version=1,
        evaluation_id=f"eval_{dataset_split.lower()}",
        dataset_split=dataset_split.upper(),
        total_samples=total_samples,
        accuracy=class_res["accuracy"],
        macro_precision=class_res["macro_precision"],
        macro_recall=class_res["macro_recall"],
        macro_f1=class_res["macro_f1"],
        crop_accuracy=crop_acc,
        unsupported_crop_abstention=unsupported_abstention,
        negative_samples_fpr=neg_fpr,
        bad_image_rejection_rate=bad_img_rate,
        ece=ece_val,
        brier_score=brier,
        mean_entropy=mean_ent,
        mean_margin=mean_margin,
        non_conclusive_rate=non_conclusive_rate,
        selective_coverage=selective_coverage,
        selective_error_rate=selective_error_rate,
        decision_counts=decision_counts,
        negative_counts={"negative_evaluated_count": negative_total,
                         "accepted_supported_class_count": negative_false_positives,
                         "rejected_count": negative_total - negative_false_positives},
        negative_count_source=negative_count_source,
        per_class=class_res["per_class"],
        confusion_matrix=class_res["confusion_matrix"],
        crop_confusion_matrix=crop_cm,
        risk_coverage_curve=risk_curve,
        latency_median_ms=lat_median,
        latency_p95_ms=lat_p95,
        max_rss_mb=round(measured_peak_rss_mb, 2) if measured_peak_rss_mb is not None else None,
    )
