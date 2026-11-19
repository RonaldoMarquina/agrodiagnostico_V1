"""Modelos y arquitecturas de inferencia para CPU."""
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CLASS_MAPPING = {
    0: {"class_code": "POTATO_HEALTHY", "crop_code": "POTATO"},
    1: {"class_code": "POTATO_EARLY_BLIGHT", "crop_code": "POTATO"},
    2: {"class_code": "POTATO_LATE_BLIGHT", "crop_code": "POTATO"},
    3: {"class_code": "MAIZE_HEALTHY", "crop_code": "MAIZE"},
    4: {"class_code": "MAIZE_COMMON_RUST", "crop_code": "MAIZE"},
    5: {"class_code": "MAIZE_LEAF_BLIGHT", "crop_code": "MAIZE"},
    6: {"class_code": "MAIZE_GRAY_LEAF_SPOT", "crop_code": "MAIZE"},
}

NUM_CLASSES = 7


def softmax(scores: List[float]) -> List[float]:
    max_s = max(scores)
    exps = [math.exp(s - max_s) for s in scores]
    sum_exps = sum(exps) or 1.0
    return [e / sum_exps for e in exps]


class CPUClassifier:
    """Clasificador agronómico ligero ejecutable en CPU.

    Permite inferencia directa sin GPU ni dependencias pesadas obligatorias.
    """

    def __init__(self, architecture: str, num_classes: int = NUM_CLASSES):
        self.architecture = architecture
        self.num_classes = num_classes
        # Pesos lineales de proyección para inferencia CPU (feature dimension 64 -> num_classes)
        self.feature_dim = 64
        # Inicialización determinista
        self.weights = [[0.01 * ((i * 7 + j) % 13 - 6) for j in range(num_classes)] for i in range(self.feature_dim)]
        self.bias = [0.0] * num_classes

    def forward_features(self, features: List[float]) -> List[float]:
        """Proyección lineal de características a logits."""
        if len(features) != self.feature_dim:
            # Rellenar o truncar si difiere
            padded = (features + [0.0] * self.feature_dim)[:self.feature_dim]
        else:
            padded = features

        logits = list(self.bias)
        for i, val in enumerate(padded):
            w_row = self.weights[i]
            for c in range(self.num_classes):
                logits[c] += val * w_row[c]
        return logits

    def predict(self, features: List[float]) -> Tuple[int, float, List[float]]:
        logits = self.forward_features(features)
        probs = softmax(logits)
        best_idx = int(max(range(len(probs)), key=lambda i: probs[i]))
        return best_idx, probs[best_idx], probs

    def save_weights(self, path: str | Path) -> None:
        """Serializa los pesos en formato JSON/binario reproducible."""
        data = {
            "architecture": self.architecture,
            "feature_dim": self.feature_dim,
            "num_classes": self.num_classes,
            "weights": self.weights,
            "bias": self.bias,
        }
        Path(path).write_text(json.dumps(data), encoding="utf-8")

    def load_weights(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.architecture = data["architecture"]
        self.feature_dim = data["feature_dim"]
        self.num_classes = data["num_classes"]
        self.weights = data["weights"]
        self.bias = data["bias"]
