"""Línea base conjunta cultivo/clase para inferencia y entrenamiento en CPU.

Implementa:
- Modelo conjunto directo de 7 clases candidatas sobre MobileNetV3-Small / clasificador CPU.
- Inferencia de cultivo derivada automáticamente del código de patología (`POTATO_*` -> POTATO, `MAIZE_*` -> MAIZE).
- Entrenamiento determinista en CPU (SGD con semilla fija y regularización L2).
- Gestión de checkpoints con procedencia de pesos, configuración versionada y hash SHA-256.
- Etiquetado explícito de ejecución (FIXTURE_DRY_RUN vs REAL_DATA_TRAINING) para evitar confusión de datos.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Tuple

from agro_ml.config import ModelConfig
from agro_ml.models.architectures import CLASS_MAPPING, NUM_CLASSES, softmax
from agro_ml.models.provenance import BASE_ARCHITECTURES


class JointBaselineClassifier:
    """Clasificador conjunto cultivo/clase determinista en CPU."""

    def __init__(
        self,
        architecture: str = "mobilenet_v3_small",
        num_classes: int = NUM_CLASSES,
        feature_dim: int = 64,
        seed: int = 42,
    ):
        self.architecture = architecture
        self.num_classes = num_classes
        self.feature_dim = feature_dim
        self.seed = seed
        self.weights: List[List[float]] = []
        self.bias: List[float] = [0.0] * num_classes
        self._init_weights()

    def _init_weights(self) -> None:
        """Inicialización determinista con semilla."""
        rng = random.Random(self.seed)
        self.weights = [
            [round(rng.gauss(0.0, 0.05), 6) for _ in range(self.num_classes)]
            for _ in range(self.feature_dim)
        ]
        self.bias = [0.0] * self.num_classes

    def forward(self, features: List[float]) -> List[float]:
        """Proyección lineal de características a logits."""
        if len(features) != self.feature_dim:
            padded = (features + [0.0] * self.feature_dim)[: self.feature_dim]
        else:
            padded = features

        logits = list(self.bias)
        for i, val in enumerate(padded):
            w_row = self.weights[i]
            for c in range(self.num_classes):
                logits[c] += val * w_row[c]
        return logits

    def predict(self, features: List[float]) -> Dict[str, Any]:
        """Predice clase ganadora, puntuación técnica raw_score y cultivo."""
        logits = self.forward(features)
        probs = softmax(logits)
        best_idx = int(max(range(len(probs)), key=lambda i: probs[i]))
        class_info = CLASS_MAPPING.get(best_idx, {"class_code": "UNKNOWN", "crop_code": "UNKNOWN"})

        return {
            "predicted_idx": best_idx,
            "class_code": class_info["class_code"],
            "crop_code": class_info["crop_code"],
            "raw_score": round(probs[best_idx], 4),
            "probabilities": [round(p, 4) for p in probs],
        }

    def train_epoch(
        self,
        samples: List[Tuple[List[float], int]],
        learning_rate: float = 0.01,
        weight_decay: float = 1e-4,
    ) -> float:
        """Ejecuta una época de entrenamiento determinista mediante SGD con cross-entropy."""
        total_loss = 0.0
        n_samples = len(samples)
        if n_samples == 0:
            return 0.0

        for features, target_idx in samples:
            logits = self.forward(features)
            probs = softmax(logits)

            # Cross-entropy loss
            target_prob = max(probs[target_idx], 1e-12)
            total_loss += -math.log(target_prob)

            # Gradientes respecto a logits: dL/d(logit_c) = prob_c - (1 if c == target else 0)
            grad_logits = [probs[c] - (1.0 if c == target_idx else 0.0) for c in range(self.num_classes)]

            # Actualizar sesgos
            for c in range(self.num_classes):
                self.bias[c] -= learning_rate * grad_logits[c]

            # Actualizar pesos
            for i in range(self.feature_dim):
                feat_val = features[i] if i < len(features) else 0.0
                for c in range(self.num_classes):
                    grad_w = feat_val * grad_logits[c] + weight_decay * self.weights[i][c]
                    self.weights[i][c] -= learning_rate * grad_w

        return round(total_loss / n_samples, 6)

    def save_checkpoint(
        self,
        output_path: Path,
        config: ModelConfig,
        epochs_trained: int,
        loss: float,
        is_synthetic_fixture: bool = True,
    ) -> Dict[str, Any]:
        """Guarda un checkpoint completo inmutable con hash SHA-256 y metadatos de procedencia."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Serialización determinista de pesos para digest
        weights_repr = json.dumps({"weights": self.weights, "bias": self.bias}, sort_keys=True)
        weights_sha256 = hashlib.sha256(weights_repr.encode("utf-8")).hexdigest()

        provenance_info = BASE_ARCHITECTURES.get(self.architecture, {})

        checkpoint_data = {
            "schema_version": 1,
            "model_id": config.model_id,
            "model_version": config.model_version,
            "dataset_version": config.dataset_version,
            "architecture": self.architecture,
            "architecture_provenance": {
                "name": provenance_info.get("name", self.architecture),
                "license": provenance_info.get("license", "UNKNOWN"),
                "source": provenance_info.get("source", "N/A"),
            },
            "seed": self.seed,
            "epochs_trained": epochs_trained,
            "final_loss": loss,
            "execution_type": "FIXTURE_DRY_RUN" if is_synthetic_fixture else "REAL_DATA_TRAINING",
            "weights_sha256": weights_sha256,
            "weights": self.weights,
            "bias": self.bias,
        }

        out.write_text(json.dumps(checkpoint_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return checkpoint_data

    @classmethod
    def load_checkpoint(cls, checkpoint_path: Path) -> Tuple["JointBaselineClassifier", Dict[str, Any]]:
        """Carga y valida la integridad de un checkpoint."""
        p = Path(checkpoint_path)
        if not p.is_file():
            raise FileNotFoundError(f"Checkpoint no encontrado: {p}")

        data = json.loads(p.read_text(encoding="utf-8"))

        # Validar hash SHA-256
        weights_repr = json.dumps({"weights": data["weights"], "bias": data["bias"]}, sort_keys=True)
        computed_sha = hashlib.sha256(weights_repr.encode("utf-8")).hexdigest()
        if computed_sha != data["weights_sha256"]:
            raise ValueError(
                f"Integridad de checkpoint comprometida: hash obtenido {computed_sha} != {data['weights_sha256']}"
            )

        model = cls(
            architecture=data["architecture"],
            num_classes=len(data["bias"]),
            feature_dim=len(data["weights"]),
            seed=data["seed"],
        )
        model.weights = data["weights"]
        model.bias = data["bias"]
        return model, data
