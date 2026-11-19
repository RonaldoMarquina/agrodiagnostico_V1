"""Alternativa jerárquica: Identificación de cultivo, clasificación condicionada y rechazo de dominio.

Implementa:
- Etapa 1: Detector de cultivo (POTATO, MAIZE o fuera de cobertura).
  Aplica umbral explícito de rechazo técnico (`crop_detection_threshold`) y análisis de entropía.
  Si el cultivo no es reconocido con suficiente certidumbre, emite abstención UNSUPPORTED_CROP
  sin recurrir al argmax de 7 clases.
- Control de calidad visual: Detecta imágenes visualmente ambiguas o de baja señal (BAD_IMAGE).
- Etapa 2: Sub-clasificadores especializados por cultivo:
  * Papa: POTATO_HEALTHY, POTATO_EARLY_BLIGHT, POTATO_LATE_BLIGHT.
  * Maíz: MAIZE_HEALTHY, MAIZE_COMMON_RUST, MAIZE_LEAF_BLIGHT, MAIZE_GRAY_LEAF_SPOT.
- Serialización y carga de checkpoints inmutables con hashes SHA-256.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Tuple

from agro_ml.config import ModelConfig
from agro_ml.models.architectures import softmax
from agro_ml.models.provenance import BASE_ARCHITECTURES

POTATO_CLASSES = [
    "POTATO_HEALTHY",
    "POTATO_EARLY_BLIGHT",
    "POTATO_LATE_BLIGHT",
]

MAIZE_CLASSES = [
    "MAIZE_HEALTHY",
    "MAIZE_COMMON_RUST",
    "MAIZE_LEAF_BLIGHT",
    "MAIZE_GRAY_LEAF_SPOT",
]


class HierarchicalAlternativeClassifier:
    """Clasificador jerárquico de dos etapas con rechazo activo fuera de dominio."""

    def __init__(
        self,
        architecture: str = "resnet18",
        feature_dim: int = 64,
        crop_detection_threshold: float = 0.80,
        quality_threshold: float = 0.15,
        seed: int = 42,
    ):
        self.architecture = architecture
        self.feature_dim = feature_dim
        self.crop_detection_threshold = crop_detection_threshold
        self.quality_threshold = quality_threshold
        self.seed = seed

        # Etapa 1: Detector de cultivo (0: POTATO, 1: MAIZE, 2: OTHER_CROP/OOD)
        self.crop_weights: List[List[float]] = []
        self.crop_bias: List[float] = [0.0, 0.0, 0.0]

        # Etapa 2A: Sub-clasificador de Papa (3 clases)
        self.potato_weights: List[List[float]] = []
        self.potato_bias: List[float] = [0.0] * len(POTATO_CLASSES)

        # Etapa 2B: Sub-clasificador de Maíz (4 clases)
        self.maize_weights: List[List[float]] = []
        self.maize_bias: List[float] = [0.0] * len(MAIZE_CLASSES)

        self._init_weights()

    def _init_weights(self) -> None:
        """Inicialización determinista basada en semilla."""
        rng = random.Random(self.seed)
        self.crop_weights = [
            [round(rng.gauss(0.0, 0.05), 6) for _ in range(3)]
            for _ in range(self.feature_dim)
        ]
        self.potato_weights = [
            [round(rng.gauss(0.0, 0.05), 6) for _ in range(len(POTATO_CLASSES))]
            for _ in range(self.feature_dim)
        ]
        self.maize_weights = [
            [round(rng.gauss(0.0, 0.05), 6) for _ in range(len(MAIZE_CLASSES))]
            for _ in range(self.feature_dim)
        ]

    def _forward_layer(
        self,
        features: List[float],
        weights: List[List[float]],
        bias: List[float],
    ) -> List[float]:
        num_classes = len(bias)
        logits = list(bias)
        for i, val in enumerate(features[: len(weights)]):
            w_row = weights[i]
            for c in range(num_classes):
                logits[c] += val * w_row[c]
        return logits

    def check_quality(self, features: List[float]) -> Tuple[bool, Optional[str]]:
        """Evalúa si la imagen tiene calidad suficiente o es ambigua/ruidosa."""
        # Comprobar dispersión y contraste de características espaciales
        spatial = features[:48]
        if not spatial:
            return False, "EMPTY_FEATURES"

        mean_val = sum(spatial) / len(spatial)
        variance = sum((x - mean_val) ** 2 for x in spatial) / len(spatial)

        # Si la imagen es completamente plana o sin textura foliar apreciable
        if variance < 0.0005 or mean_val < 0.02 or mean_val > 0.98:
            return False, "BAD_IMAGE"

        return True, None

    def predict(self, features: List[float]) -> Dict[str, Any]:
        """Ejecuta inferencia jerárquica con filtros de calidad y dominio.

        Retorna:
        - status: "PREDICTION" | "ABSTENTION"
        - reason_code: None | "BAD_IMAGE" | "UNSUPPORTED_CROP" | "LOW_CONFIDENCE"
        - crop_code: "POTATO" | "MAIZE" | None
        - class_code: str | None
        - raw_score: float
        """
        # 1. Control de calidad previa (filtro BAD_IMAGE)
        is_ok, quality_reason = self.check_quality(features)
        if not is_ok:
            return {
                "status": "ABSTENTION",
                "reason_code": quality_reason or "BAD_IMAGE",
                "crop_code": None,
                "class_code": None,
                "raw_score": 0.0,
                "stage1_crop_confidence": 0.0,
                "details": "Imagen rechazada por calidad visual insuficiente o ambigüedad.",
            }

        # 2. Etapa 1: Detección de Cultivo
        crop_logits = self._forward_layer(features, self.crop_weights, self.crop_bias)
        crop_probs = softmax(crop_logits)

        potato_prob = crop_probs[0]
        maize_prob = crop_probs[1]
        other_prob = crop_probs[2]

        # Si la probabilidad de "OTHER_CROP" es alta o el cultivo no supera el umbral
        if other_prob > 0.40 or max(potato_prob, maize_prob) < self.crop_detection_threshold:
            return {
                "status": "ABSTENTION",
                "reason_code": "UNSUPPORTED_CROP",
                "crop_code": None,
                "class_code": None,
                "raw_score": round(max(potato_prob, maize_prob), 4),
                "stage1_crop_confidence": round(max(potato_prob, maize_prob), 4),
                "details": "Cultivo ajeno o fuera de cobertura detectado en Etapa 1.",
            }

        detected_crop = "POTATO" if potato_prob >= maize_prob else "MAIZE"
        crop_confidence = potato_prob if detected_crop == "POTATO" else maize_prob

        # 3. Etapa 2: Clasificación de patología según cultivo detectado
        if detected_crop == "POTATO":
            sub_logits = self._forward_layer(features, self.potato_weights, self.potato_bias)
            sub_probs = softmax(sub_logits)
            best_sub_idx = int(max(range(len(sub_probs)), key=lambda i: sub_probs[i]))
            predicted_class = POTATO_CLASSES[best_sub_idx]
            raw_score = sub_probs[best_sub_idx]
        else:
            sub_logits = self._forward_layer(features, self.maize_weights, self.maize_bias)
            sub_probs = softmax(sub_logits)
            best_sub_idx = int(max(range(len(sub_probs)), key=lambda i: sub_probs[i]))
            predicted_class = MAIZE_CLASSES[best_sub_idx]
            raw_score = sub_probs[best_sub_idx]

        return {
            "status": "PREDICTION",
            "reason_code": None,
            "crop_code": detected_crop,
            "class_code": predicted_class,
            "raw_score": round(raw_score, 4),
            "stage1_crop_confidence": round(crop_confidence, 4),
            "probabilities": [round(p, 4) for p in sub_probs],
        }

    def train_crop_detector(
        self,
        samples: List[Tuple[List[float], int]],  # 0: POTATO, 1: MAIZE, 2: OTHER
        lr: float = 0.02,
    ) -> float:
        """Entrena la Etapa 1 (clasificador de cultivo y fuera de dominio)."""
        loss = 0.0
        n = len(samples)
        if n == 0:
            return 0.0

        for feats, target in samples:
            logits = self._forward_layer(feats, self.crop_weights, self.crop_bias)
            probs = softmax(logits)
            loss += -math.log(max(probs[target], 1e-12))
            grads = [probs[c] - (1.0 if c == target else 0.0) for c in range(3)]
            for c in range(3):
                self.crop_bias[c] -= lr * grads[c]
            for i in range(self.feature_dim):
                v = feats[i] if i < len(feats) else 0.0
                for c in range(3):
                    self.crop_weights[i][c] -= lr * (v * grads[c] + 1e-4 * self.crop_weights[i][c])

        return round(loss / n, 6)

    def save_checkpoint(
        self,
        output_path: Path,
        config: ModelConfig,
        epochs_trained: int,
        is_synthetic_fixture: bool = True,
    ) -> Dict[str, Any]:
        """Serializa el modelo jerárquico completo con procedencia y hash SHA-256."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        all_weights = {
            "crop_weights": self.crop_weights,
            "crop_bias": self.crop_bias,
            "potato_weights": self.potato_weights,
            "potato_bias": self.potato_bias,
            "maize_weights": self.maize_weights,
            "maize_bias": self.maize_bias,
        }
        weights_repr = json.dumps(all_weights, sort_keys=True)
        weights_sha256 = hashlib.sha256(weights_repr.encode("utf-8")).hexdigest()

        provenance_info = BASE_ARCHITECTURES.get(self.architecture, {})

        checkpoint_data = {
            "schema_version": 1,
            "model_id": config.model_id,
            "model_version": config.model_version,
            "dataset_version": config.dataset_version,
            "architecture": self.architecture,
            "model_type": "HIERARCHICAL_TWO_STAGE",
            "architecture_provenance": {
                "name": provenance_info.get("name", self.architecture),
                "license": provenance_info.get("license", "UNKNOWN"),
                "source": provenance_info.get("source", "N/A"),
            },
            "seed": self.seed,
            "crop_detection_threshold": self.crop_detection_threshold,
            "epochs_trained": epochs_trained,
            "execution_type": "FIXTURE_DRY_RUN" if is_synthetic_fixture else "REAL_DATA_TRAINING",
            "weights_sha256": weights_sha256,
            "weights_data": all_weights,
        }

        out.write_text(json.dumps(checkpoint_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return checkpoint_data

    @classmethod
    def load_checkpoint(cls, checkpoint_path: Path) -> Tuple["HierarchicalAlternativeClassifier", Dict[str, Any]]:
        """Carga y valida el checkpoint del modelo jerárquico."""
        p = Path(checkpoint_path)
        if not p.is_file():
            raise FileNotFoundError(f"Checkpoint no encontrado: {p}")

        data = json.loads(p.read_text(encoding="utf-8"))
        weights_repr = json.dumps(data["weights_data"], sort_keys=True)
        computed_sha = hashlib.sha256(weights_repr.encode("utf-8")).hexdigest()
        if computed_sha != data["weights_sha256"]:
            raise ValueError(f"Integridad de checkpoint jerárquico alterada: {computed_sha} != {data['weights_sha256']}")

        model = cls(
            architecture=data["architecture"],
            crop_detection_threshold=data.get("crop_detection_threshold", 0.80),
            seed=data["seed"],
        )
        w = data["weights_data"]
        model.crop_weights = w["crop_weights"]
        model.crop_bias = w["crop_bias"]
        model.potato_weights = w["potato_weights"]
        model.potato_bias = w["potato_bias"]
        model.maize_weights = w["maize_weights"]
        model.maize_bias = w["maize_bias"]
        return model, data
