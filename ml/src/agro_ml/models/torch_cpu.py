"""Recorrido CPU real con pesos tensoriales, restringido a fixtures técnicos.

No construye un release G2 ni declara clases soportadas. Los constructores usan
weights=None: jamás descargan pesos base de forma implícita.
"""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import torch
from torch import nn
from torch.nn import functional as F
import torchvision
from torchvision.models import mobilenet_v3_small, resnet18
from safetensors.torch import load_file, save_file

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.models.architectures import CLASS_MAPPING


MAX_CHECKPOINT_BYTES = 100 * 1024 * 1024


class CropDiseaseNet(nn.Module):
    """ResNet18 compartida con cabeza de cultivo y dos cabezas de condición."""

    def __init__(self) -> None:
        super().__init__()
        self.backbone = resnet18(weights=None)
        self.backbone.fc = nn.Identity()
        self.crop_head = nn.Linear(512, 3)  # POTATO, MAIZE, OTHER; no es NO_CONCLUYENTE.
        self.potato_head = nn.Linear(512, 3)
        self.maize_head = nn.Linear(512, 4)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        features = self.backbone(x)
        return self.crop_head(features), self.potato_head(features), self.maize_head(features)


def build_model(architecture: str, *, seed: int) -> nn.Module:
    """Instancia pesos aleatorios reproducibles, sin red ni base preentrenada."""
    if type(seed) is not int or seed < 0:
        raise ValueError("Semilla inválida")
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    if architecture == "mobilenet_v3_small":
        model = mobilenet_v3_small(weights=None)
        model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 7)
        return model.cpu()
    if architecture == "resnet18_hierarchical":
        return CropDiseaseNet().cpu()
    raise ValueError("Arquitectura CPU no permitida")


def freeze_feature_extractor(model: nn.Module, architecture: str) -> None:
    """Smoke rápido: optimiza cabezas reales sobre un extractor aleatorio."""
    backbone = model.features if architecture == "mobilenet_v3_small" else model.backbone
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)


def train_fixture_epoch(
    model: nn.Module, architecture: str, samples: Iterable[tuple[bytes, int | None]],
    spec: TensorSpec, *, learning_rate: float, seed: int,
) -> float:
    """Ejecuta SGD real en CPU; None representa negativo solo para el modelo jerárquico."""
    if not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("Learning rate inválido")
    samples = list(samples)
    if not samples:
        raise ValueError("Se requieren fixtures rotulados")
    for _, label in samples:
        if label is None and architecture == "resnet18_hierarchical":
            continue
        if type(label) is not int or not 0 <= label < 7:
            raise ValueError("Etiqueta fuera de taxonomía")
    model.eval()  # BatchNorm/Dropout estables con lote mínimo de smoke.
    optimizer = torch.optim.SGD((p for p in model.parameters() if p.requires_grad), lr=learning_rate)
    losses: list[float] = []
    optimizer.zero_grad(set_to_none=True)
    for index, (image_bytes, label) in enumerate(samples):
        tensor = image_to_tensor(image_bytes, spec, split="TRAIN", augment=False, seed=seed + index).unsqueeze(0)
        if architecture == "mobilenet_v3_small":
            loss = F.cross_entropy(model(tensor), torch.tensor([label], dtype=torch.long))
        elif architecture == "resnet18_hierarchical":
            crop_logits, potato_logits, maize_logits = model(tensor)
            crop_index = 2 if label is None else (0 if label < 3 else 1)
            loss = F.cross_entropy(crop_logits, torch.tensor([crop_index], dtype=torch.long))
            if label is not None:
                condition_logits = potato_logits if label < 3 else maize_logits
                local_index = label if label < 3 else label - 3
                loss = loss + F.cross_entropy(condition_logits, torch.tensor([local_index], dtype=torch.long))
        else:
            raise ValueError("Arquitectura no permitida")
        if not bool(torch.isfinite(loss)):
            raise ValueError("Pérdida no finita")
        (loss / len(samples)).backward()
        losses.append(float(loss.detach()))
    optimizer.step()
    return sum(losses) / len(losses)


def train_fixture_hierarchical_heads(
    model: CropDiseaseNet, samples: Iterable[tuple[bytes, int | None]], spec: TensorSpec,
    *, steps: int, learning_rate: float,
) -> list[float]:
    """Entrena las tres cabezas en lote sobre embeddings CPU de fixtures.

    El extractor aleatorio queda congelado solo para este smoke. Se incluyen
    positivos de ambos cultivos y negativos en la cabeza de cultivo; la clase
    OTHER nunca entra a las cabezas de enfermedad.
    """
    samples = list(samples)
    if type(steps) is not int or not 1 <= steps <= 100:
        raise ValueError("Pasos de smoke inválidos")
    if not math.isfinite(learning_rate) or not 0 < learning_rate <= .1:
        raise ValueError("Learning rate inválido")
    positive = [label for _, label in samples if label is not None]
    if any(type(label) is not int or not 0 <= label < 7 for label in positive):
        raise ValueError("Etiqueta inválida")
    if not samples or not any(label is None for _, label in samples) or not any(label < 3 for label in positive) or not any(label >= 3 for label in positive):
        raise ValueError("Se requieren papa, maíz y negativo de dominio")
    model.eval()
    batch = torch.stack([image_to_tensor(raw, spec, split="TRAIN") for raw, _ in samples])
    with torch.no_grad():
        features = model.backbone(batch).detach()
    crop_target = torch.tensor([2 if label is None else 0 if label < 3 else 1 for _, label in samples], dtype=torch.long)
    potato_indices = [i for i, (_, label) in enumerate(samples) if label is not None and label < 3]
    maize_indices = [i for i, (_, label) in enumerate(samples) if label is not None and label >= 3]
    potato_target = torch.tensor([samples[i][1] for i in potato_indices], dtype=torch.long)
    maize_target = torch.tensor([samples[i][1] - 3 for i in maize_indices], dtype=torch.long)
    parameters = [*model.crop_head.parameters(), *model.potato_head.parameters(), *model.maize_head.parameters()]
    optimizer = torch.optim.Adam(parameters, lr=learning_rate)
    losses: list[float] = []
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = (
            F.cross_entropy(model.crop_head(features), crop_target)
            + F.cross_entropy(model.potato_head(features[potato_indices]), potato_target)
            + F.cross_entropy(model.maize_head(features[maize_indices]), maize_target)
        )
        if not bool(torch.isfinite(loss)):
            raise ValueError("Pérdida no finita")
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    return losses


@dataclass(frozen=True)
class CropPolicy:
    min_crop_score: float
    min_margin: float
    selected_on: str

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (self.min_crop_score, self.min_margin)):
            raise ValueError("Umbral de cultivo inválido")
        if self.selected_on != "VAL_FIXTURE":
            raise ValueError("Solo se acepta política técnica de fixtures en este recorrido")

    def to_dict(self) -> dict:
        return {"min_crop_score": self.min_crop_score, "min_margin": self.min_margin,
                "selected_on": self.selected_on, "approval": None}


def decide_crop(crop_logits: torch.Tensor, policy: CropPolicy) -> str | None:
    """Abstiene frente a OTHER o evidencia insuficiente; nunca usa argmax de siete clases."""
    if crop_logits.numel() != 3 or not bool(torch.isfinite(crop_logits).all()):
        raise ValueError("Logits de cultivo inválidos")
    probs = torch.softmax(crop_logits.reshape(3), dim=0)
    if int(torch.argmax(probs)) == 2:
        return None
    best = max(float(probs[0]), float(probs[1]))
    margin = abs(float(probs[0]) - float(probs[1]))
    if best < policy.min_crop_score or margin < policy.min_margin:
        return None
    return "POTATO" if probs[0] > probs[1] else "MAIZE"


def select_fixture_crop_policy(
    model: CropDiseaseNet, validation: Iterable[tuple[bytes, int | None]], spec: TensorSpec,
) -> CropPolicy:
    """Selecciona en VAL_FIXTURE por exactitud de cultivo/rechazo, sin valor productivo."""
    points: list[tuple[torch.Tensor, str | None]] = []
    model.eval()
    with torch.inference_mode():
        for image_bytes, label in validation:
            if label is not None and (type(label) is not int or not 0 <= label < 7):
                raise ValueError("Etiqueta de validación inválida")
            tensor = image_to_tensor(image_bytes, spec, split="VAL").unsqueeze(0)
            crop_logits, _, _ = model(tensor)
            expected = None if label is None else ("POTATO" if label < 3 else "MAIZE")
            points.append((crop_logits.squeeze(0), expected))
    if not points or not any(expected is None for _, expected in points) or not any(expected is not None for _, expected in points):
        raise ValueError("VAL_FIXTURE debe incluir cultivos y un negativo fuera de dominio")
    scores = [torch.softmax(logits, dim=0) for logits, _ in points]
    score_candidates = {0.0, 1.0, *(float(max(prob[0], prob[1])) for prob in scores)}
    margin_candidates = {0.0, 1.0, *(abs(float(prob[0] - prob[1])) for prob in scores)}
    choices = (
        (sum(decide_crop(logits, CropPolicy(score, margin, "VAL_FIXTURE")) == expected for logits, expected in points),
         sum(decide_crop(logits, CropPolicy(score, margin, "VAL_FIXTURE")) is not None for logits, _ in points),
         score, margin)
        for score in score_candidates for margin in margin_candidates
    )
    _, _, best_score, best_margin = max(choices)
    policy = CropPolicy(best_score, best_margin, "VAL_FIXTURE")
    for crop in ("POTATO", "MAIZE"):
        if not any(expected == crop and decide_crop(logits, policy) == crop for logits, expected in points):
            raise ValueError(f"VAL_FIXTURE sin cobertura correcta para {crop}")
    if not any(expected is None and decide_crop(logits, policy) is None for logits, expected in points):
        raise ValueError("VAL_FIXTURE no rechaza negativo fuera de dominio")
    return policy


def predict_image(
    model: nn.Module, architecture: str, image_bytes: bytes, spec: TensorSpec,
    *, crop_policy: CropPolicy | None = None,
) -> dict:
    """Infiere con el mismo preprocesado del entrenamiento; resultado solo técnico."""
    tensor = image_to_tensor(image_bytes, spec, split="INFERENCE")
    if architecture == "resnet18_hierarchical" and crop_policy is None:
        raise ValueError("La alternativa requiere política seleccionada en VAL")
    if architecture == "resnet18_hierarchical" and float(tensor.flatten(1).std(dim=1).mean()) < 1e-6:
        return {"status": "ABSTENTION", "reason_code": "BAD_IMAGE", "crop_code": None,
                "class_code": None, "raw_score": None, "fixture_only": True}
    model.eval()
    with torch.inference_mode():
        if architecture == "mobilenet_v3_small":
            logits = model(tensor.unsqueeze(0)).squeeze(0)
            probabilities = torch.softmax(logits, dim=0)
            index = int(torch.argmax(probabilities))
            info = CLASS_MAPPING[index]
            return {"status": "PREDICTION", "reason_code": None, **info,
                    "raw_score": float(probabilities[index]), "fixture_only": True}
        if architecture == "resnet18_hierarchical":
            crop_logits, potato_logits, maize_logits = model(tensor.unsqueeze(0))
            crop = decide_crop(crop_logits.squeeze(0), crop_policy)
            if crop is None:
                return {"status": "ABSTENTION", "reason_code": "UNSUPPORTED_CROP", "crop_code": None,
                        "class_code": None, "raw_score": None, "fixture_only": True}
            probabilities = torch.softmax((potato_logits if crop == "POTATO" else maize_logits).squeeze(0), dim=0)
            local_index = int(torch.argmax(probabilities))
            info = CLASS_MAPPING[local_index if crop == "POTATO" else local_index + 3]
            return {"status": "PREDICTION", "reason_code": None, **info,
                    "raw_score": float(probabilities[local_index]), "fixture_only": True}
    raise ValueError("Arquitectura no permitida")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_fixture_checkpoint(model: nn.Module, architecture: str, spec: TensorSpec, output_dir: Path,
                            *, seed: int, train_loss: float, train_samples: int,
                            crop_policy: CropPolicy | None = None) -> Path:
    """Guarda safetensors y manifiesto explícitamente no promocionable."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    weights = output_dir / "fixture-weights.safetensors"
    save_file({name: value.detach().cpu().contiguous() for name, value in model.state_dict().items()}, str(weights))
    metadata = {
        "schema_version": 1, "status": "FIXTURE_ONLY", "approval": None,
        "architecture": architecture, "seed": seed, "train_loss": train_loss,
        "train_samples": train_samples, "preprocessing": spec.to_dict(),
        "base_weights": {"source": "RANDOM_INITIALIZATION", "seed": seed,
                         "downloaded": False, "pretrained": False},
        "weights": {"filename": weights.name, "format": "safetensors", "sha256": _sha256(weights)},
        "runtime": {"torch": torch.__version__, "torchvision": torchvision.__version__, "device": "cpu"},
        "fixture_crop_policy": crop_policy.to_dict() if crop_policy is not None else None,
    }
    manifest = output_dir / "fixture-checkpoint.json"
    manifest.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_fixture_checkpoint(manifest: Path) -> tuple[nn.Module, dict, TensorSpec]:
    """Verifica hash, formato y tensores; nunca interpreta este archivo como release."""
    manifest = Path(manifest)
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("status") != "FIXTURE_ONLY" or metadata.get("approval") is not None:
        raise ValueError("Checkpoint no es fixture técnico")
    weights_info = metadata["weights"]
    if weights_info.get("filename") != "fixture-weights.safetensors" or weights_info.get("format") != "safetensors":
        raise ValueError("Ruta o formato de pesos inválido")
    weights = manifest.parent / weights_info["filename"]
    if weights.is_symlink() or weights.resolve().parent != manifest.parent.resolve():
        raise ValueError("Ruta de pesos fuera del checkpoint")
    if not weights.is_file() or weights.stat().st_size > MAX_CHECKPOINT_BYTES or _sha256(weights) != weights_info["sha256"]:
        raise ValueError("Pesos ausentes, excesivos o alterados")
    spec = TensorSpec.from_dict(metadata["preprocessing"])
    model = build_model(metadata["architecture"], seed=metadata["seed"])
    state = load_file(str(weights), device="cpu")
    if not all(bool(torch.isfinite(value).all()) for value in state.values()):
        raise ValueError("Pesos no finitos")
    model.load_state_dict(state, strict=True)
    model.eval()
    return model, metadata, spec
