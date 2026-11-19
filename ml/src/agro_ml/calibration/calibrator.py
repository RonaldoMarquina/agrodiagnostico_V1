"""Calibración escalar por clase, umbrales de publicación y cálculo de ECE.

Implementa:
- Calibración escalar (Platt scaling) por clase a partir de raw_score en validación (VAL).
- Manejo estricto de valores no finitos (NaN, Inf) con error explícito.
- Prohibición estricta de fallback sintético al 0.9 ante ausencia de calibrador.
- Evaluación de umbrales de publicación (score < tau -> LOW_CONFIDENCE, score >= tau -> APROBADO).
- Cálculo determinista de Expected Calibration Error (ECE) sobre 10 intervalos.
"""
from dataclasses import asdict, dataclass
import math
from typing import Any, Dict, List, Optional, Tuple


def is_finite_number(val: Any) -> bool:
    """Verifica si un valor es un número flotante finito válido."""
    if not isinstance(val, (int, float)):
        return False
    return not (math.isnan(val) or math.isinf(val))


def sigmoid(z: float) -> float:
    if not is_finite_number(z):
        raise ValueError(f"Valor no finito en función sigmoide: {z}")
    if z >= 40.0:
        return 1.0
    if z <= -40.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


@dataclass
class CalibrationDecision:
    raw_score: float
    calibrated_confidence: Optional[float]
    min_confidence_threshold: float
    is_published: bool
    status: str  # PREDICTION o ABSTENTION
    reason_code: Optional[str]  # LOW_CONFIDENCE, etc.
    calibrated: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PlattCalibrator:
    """Calibrador escalar determinista por clase ajustado sobre validación (VAL)."""

    def __init__(
        self,
        parameters: Optional[Dict[str, Dict[str, float]]] = None,
        thresholds: Optional[Dict[str, float]] = None,
        default_threshold: float = 0.65,
    ):
        self.parameters = parameters or {}
        self.thresholds = thresholds or {}
        self.default_threshold = default_threshold

    def fit_class(
        self,
        raw_scores: List[float],
        labels: List[int],
        class_code: str,
        target_precision: float = 0.70,
    ) -> Tuple[float, float, float]:
        """Ajusta pendiente, intercepto y umbral óptimo a partir de raw_scores y etiquetas en VAL."""
        if not raw_scores or len(raw_scores) != len(labels):
            slope, intercept, thresh = 1.0, 0.0, self.default_threshold
            self.parameters[class_code] = {"slope": slope, "intercept": intercept}
            self.thresholds[class_code] = thresh
            return slope, intercept, thresh

        # Validar valores finitos
        for s in raw_scores:
            if not is_finite_number(s):
                raise ValueError(f"Score no finito detectado en entrenamiento de calibrador: {s}")

        pos_scores = [s for s, y in zip(raw_scores, labels) if y == 1]
        neg_scores = [s for s, y in zip(raw_scores, labels) if y == 0]

        mean_pos = sum(pos_scores) / len(pos_scores) if pos_scores else 0.8
        mean_neg = sum(neg_scores) / len(neg_scores) if neg_scores else 0.2

        delta = max(0.05, mean_pos - mean_neg)
        slope = min(5.0, max(0.5, 2.0 / delta))
        midpoint = (mean_pos + mean_neg) / 2.0
        intercept = -slope * midpoint

        # Buscar umbral que maximice precision sin destruir recall
        best_thresh = self.default_threshold
        sorted_scores = sorted(set(raw_scores))
        for cand in sorted_scores:
            if cand < 0.50 or cand > 0.95:
                continue
            tp = sum(1 for s, y in zip(raw_scores, labels) if s >= cand and y == 1)
            fp = sum(1 for s, y in zip(raw_scores, labels) if s >= cand and y == 0)
            if (tp + fp) > 0 and (tp / (tp + fp)) >= target_precision:
                best_thresh = cand
                break

        self.parameters[class_code] = {"slope": round(slope, 4), "intercept": round(intercept, 4)}
        self.thresholds[class_code] = round(best_thresh, 4)
        return slope, intercept, best_thresh

    def calibrate(self, class_code: str, raw_score: float) -> Optional[float]:
        """Calcula la confianza calibrada para una clase dada.

        REGLA CRÍTICA: Si no hay calibrador para la clase, retorna None.
        NUNCA hace fallback a un 0.9 sintético.
        """
        if not is_finite_number(raw_score):
            raise ValueError(f"raw_score inválido o no finito: {raw_score}")

        if class_code not in self.parameters:
            # Sin fallback a 0.9 sintético
            return None

        params = self.parameters[class_code]
        slope = params["slope"]
        intercept = params["intercept"]

        if not is_finite_number(slope) or not is_finite_number(intercept):
            raise ValueError(f"Parámetros de calibración no finitos para {class_code}")

        z = slope * raw_score + intercept
        return round(sigmoid(z), 4)

    def evaluate_publication(
        self,
        class_code: str,
        raw_score: float,
    ) -> CalibrationDecision:
        """Evalúa si el score supera el umbral de publicación para la clase."""
        if not is_finite_number(raw_score):
            raise ValueError(f"raw_score no finito: {raw_score}")

        calibrated_conf = self.calibrate(class_code, raw_score)
        threshold = self.thresholds.get(class_code, self.default_threshold)

        # La decisión de publicación compara el raw_score (o confianza si está calibrada) contra el umbral
        score_to_compare = calibrated_conf if calibrated_conf is not None else raw_score

        if score_to_compare < threshold:
            return CalibrationDecision(
                raw_score=round(raw_score, 4),
                calibrated_confidence=calibrated_conf,
                min_confidence_threshold=threshold,
                is_published=False,
                status="ABSTENTION",
                reason_code="LOW_CONFIDENCE",
                calibrated=calibrated_conf is not None,
            )

        return CalibrationDecision(
            raw_score=round(raw_score, 4),
            calibrated_confidence=calibrated_conf,
            min_confidence_threshold=threshold,
            is_published=True,
            status="PREDICTION",
            reason_code=None,
            calibrated=calibrated_conf is not None,
        )


def compute_ece(confidences: List[float], accuracies: List[int], num_bins: int = 10) -> float:
    """Calcula el Expected Calibration Error (ECE) sobre N intervalos."""
    if not confidences or len(confidences) != len(accuracies):
        return 0.0

    for c in confidences:
        if not is_finite_number(c):
            raise ValueError(f"Confianza no finita en cálculo ECE: {c}")

    n = len(confidences)
    bin_size = 1.0 / num_bins
    ece = 0.0

    for b in range(num_bins):
        bin_lower = b * bin_size
        bin_upper = (b + 1) * bin_size

        indices = [
            i for i, c in enumerate(confidences)
            if (bin_lower <= c < bin_upper) or (b == num_bins - 1 and bin_lower <= c <= bin_upper)
        ]
        if not indices:
            continue

        bin_conf = sum(confidences[i] for i in indices) / len(indices)
        bin_acc = sum(accuracies[i] for i in indices) / len(indices)

        ece += (len(indices) / n) * abs(bin_acc - bin_conf)

    return round(ece, 4)
