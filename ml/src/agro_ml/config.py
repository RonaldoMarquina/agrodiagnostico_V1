"""Configuración versionada para entrenamiento, evaluación y empaquetado."""
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ModelConfig:
    model_id: str
    model_version: str
    dataset_version: str
    architecture: str
    seed: int = 42
    input_size: List[int] = field(default_factory=lambda: [224, 224])
    channels: int = 3
    mean: List[float] = field(default_factory=lambda: [0.485, 0.456, 0.406])
    std: List[float] = field(default_factory=lambda: [0.229, 0.224, 0.225])
    min_confidence_threshold: float = 0.65
    crop_detection_threshold: float = 0.85
    min_dimension: int = 200
    max_dimension: int = 6000
    epochs: int = 5
    batch_size: int = 16
    learning_rate: float = 0.001
    calibration_method: str = "PLATT_SCALING"
    g0_protocol_version: str = "1.0.0"

    @classmethod
    def from_file(cls, path: str | Path) -> "ModelConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
            "architecture": self.architecture,
            "seed": self.seed,
            "input_size": self.input_size,
            "channels": self.channels,
            "mean": self.mean,
            "std": self.std,
            "min_confidence_threshold": self.min_confidence_threshold,
            "crop_detection_threshold": self.crop_detection_threshold,
            "min_dimension": self.min_dimension,
            "max_dimension": self.max_dimension,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "learning_rate": self.learning_rate,
            "calibration_method": self.calibration_method,
            "g0_protocol_version": self.g0_protocol_version,
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
