"""Compuertas y configuración de transferencia MobileNetV3 para v1.4.2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import torch
from torch import nn
from torchvision.models import mobilenet_v3_small
from safetensors.torch import load_file, save_file

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.v141_gates import PUBLISHABLE_CLASSES, TECHNICAL_CLASSES
from agro_ml.v141_training import balanced_epoch_indices, visible_decision
from agro_ml.v142_checkpoint import validate_registry


class V142TransferError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise V142TransferError(message)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_private_roots(v142_root: Path, v141_root: Path) -> None:
    current, historical = v142_root.resolve(), v141_root.resolve()
    _require(current != historical and historical not in current.parents and current not in historical.parents,
             "la raíz privada v1.4.2 debe ser independiente de v1.4.1")


def validate_history_index(index: Mapping[str, Any], repo_root: Path, private_g1: Path,
                           *, commit_exists: Callable[[str], bool]) -> None:
    _require(index.get("cycle_version") == "1.4.2" and
             index.get("status") == "HISTORICAL_BOUNDARY_LOCKED", "índice histórico inválido")
    for commit in index.get("baseline_commits", {}).values():
        _require(isinstance(commit, str) and len(commit) == 40 and commit_exists(commit),
                 "commit histórico ausente")
    for relative, digest in index.get("tracked_evidence", {}).items():
        path = repo_root / relative
        _require(path.is_file() and sha256_file(path) == digest, f"evidencia histórica alterada: {relative}")
    for name, digest in index.get("private_g1_evidence", {}).items():
        path = private_g1 / name
        _require(path.is_file() and sha256_file(path) == digest, f"G1 privado alterado: {name}")
    forbidden = set(index.get("comparison_policy", {}).get("forbidden", ()))
    _require({"V1_4_1_WEIGHTS", "V1_4_1_PREDICTIONS", "HISTORICAL_TEST", "SIKKIM_EXTERNAL"}
             <= forbidden, "frontera de comparación incompleta")


def validate_preprocessing_contract(contract: Mapping[str, Any]) -> TensorSpec:
    _require(contract.get("preprocessing_version") == "1.4.2", "preprocesado no versionado")
    _require(contract.get("shared_by") == ["TRAIN", "VAL", "INFERENCE"],
             "entrenamiento e inferencia no comparten contrato")
    decode, resize, tensor = contract.get("decode", {}), contract.get("resize", {}), contract.get("tensor", {})
    _require(decode.get("color_space") == "RGB" and decode.get("exif_transpose") is True,
             "conversión RGB/EXIF incompatible")
    _require(resize.get("method") == "DIRECT_RESIZE" and resize.get("width") == 224 and
             resize.get("height") == 224 and resize.get("interpolation") == "BILINEAR",
             "geometría v1.4.2 incompatible")
    _require(tensor.get("mean") == [0.485, 0.456, 0.406] and
             tensor.get("std") == [0.229, 0.224, 0.225], "normalización ImageNet incompatible")
    return TensorSpec(width=224, height=224, min_dimension=200, max_dimension=6000,
                      mean=tuple(tensor["mean"]), std=tuple(tensor["std"]))


def validate_plan(plan: Mapping[str, Any], preprocessing: Mapping[str, Any]) -> TensorSpec:
    _require(plan.get("status") == "PREFLIGHT_NOT_TRAINED" and
             plan.get("cycle_version") == "1.4.2" and
             plan.get("g0_protocol_version") == "1.4.1", "plan v1.4.2 inválido")
    _require(plan.get("architecture") == "mobilenet_v3_small", "arquitectura no aprobada")
    _require(tuple(plan.get("technical_class_codes", ())) == TECHNICAL_CLASSES and
             tuple(plan.get("publishable_classes", ())) == PUBLISHABLE_CLASSES,
             "mapa técnico/publicable inválido")
    sampler = plan.get("sampler", {})
    _require(sampler.get("samples_per_class_per_epoch") == 80 and
             sampler.get("samples_per_epoch") == 320, "sampler debe ser 80x4")
    phases = plan.get("phases", ())
    _require(len(phases) == 2 and phases[0].get("id") == "HEAD" and phases[0].get("epochs") == 3 and
             phases[1].get("id") == "FINE_TUNE" and phases[1].get("epochs") == 12,
             "fases HEAD/FINE_TUNE inválidas")
    _require(plan.get("external_access") == "NONE" and
             {"HISTORICAL_TEST", "SIKKIM_EXTERNAL", "V1_4_1_WEIGHTS", "V1_4_1_PREDICTIONS"}
             <= set(plan.get("forbidden_inputs", ())), "entradas protegidas no bloqueadas")
    return validate_preprocessing_contract(preprocessing)


def build_pretrained_model(state: Mapping[str, torch.Tensor], *, seed: int) -> nn.Module:
    model = mobilenet_v3_small(weights=None)
    model.load_state_dict(state, strict=True)
    torch.manual_seed(seed)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(TECHNICAL_CLASSES))
    return model.cpu()


def _freeze_batch_norm(model: nn.Module) -> None:
    for module in model.modules():
        if isinstance(module, nn.BatchNorm2d):
            module.eval()
            for parameter in module.parameters():
                parameter.requires_grad = False


def configure_phase(model: nn.Module, phase: str) -> list[dict[str, Any]]:
    _require(phase in {"HEAD", "FINE_TUNE"}, "fase desconocida")
    for parameter in model.parameters():
        parameter.requires_grad = False
    for parameter in model.classifier.parameters():
        parameter.requires_grad = True
    groups: list[dict[str, Any]] = []
    if phase == "HEAD":
        groups.append({"params": list(model.classifier.parameters()), "lr": 1e-3,
                       "name": "classifier"})
    else:
        blocks = list(model.features.children())[-3:]
        backbone_parameters = []
        for block in blocks:
            for parameter in block.parameters():
                parameter.requires_grad = True
                backbone_parameters.append(parameter)
        groups.extend([
            {"params": backbone_parameters, "lr": 1e-5, "name": "features_last_3"},
            {"params": list(model.classifier.parameters()), "lr": 1e-4, "name": "classifier"},
        ])
    _freeze_batch_norm(model)
    return groups


def set_training_mode(model: nn.Module) -> None:
    model.train()
    _freeze_batch_norm(model)


def backbone_digest(model: nn.Module) -> str:
    digest = hashlib.sha256()
    for name, value in model.features.state_dict().items():
        digest.update(name.encode())
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def visible_class(probabilities: list[float], threshold: float) -> str | None:
    decision = visible_decision(probabilities, threshold)
    return PUBLISHABLE_CLASSES[decision] if decision is not None else None


def shared_tensor(image_bytes: bytes, spec: TensorSpec, *, consumer: str) -> torch.Tensor:
    _require(consumer in {"TRAIN", "VAL", "INFERENCE"}, "consumidor no permitido")
    split = consumer if consumer != "INFERENCE" else "INFERENCE"
    return image_to_tensor(image_bytes, spec, split=split)


def validate_training_mounts(paths: list[Path], forbidden_markers: tuple[str, ...] =
                             ("sikkim", "external", "historical-test", "v1.4.1-train-val")) -> None:
    lowered = [str(path.resolve()).lower() for path in paths]
    _require(not any(marker in value for marker in forbidden_markers for value in lowered),
             "montaje protegido o salida histórica detectada")


def validate_private_checkpoint(root: Path) -> tuple[dict[str, Any], Path]:
    registry_path = root / "provenance.json"
    checkpoint = root / "mobilenet_v3_small-047dcff4.pth"
    _require(registry_path.is_file(), "expediente privado del checkpoint ausente")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_registry(registry, checkpoint)
    _require(checkpoint.stat().st_mode & 0o222 == 0, "checkpoint debe ser de solo lectura")
    return registry, checkpoint


def save_training_resume(root: Path, model: nn.Module, optimizer: torch.optim.Optimizer,
                         *, epoch: int, phase: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    _require(epoch >= 1 and phase in {"HEAD", "FINE_TUNE"}, "punto de reanudación inválido")
    weights = root / "resume-weights.safetensors"
    optimizer_path = root / "resume-optimizer.pt"
    save_file({key: value.detach().cpu().contiguous()
               for key, value in model.state_dict().items()}, str(weights))
    torch.save(optimizer.state_dict(), optimizer_path)
    payload = {"epoch": epoch, "phase": phase, "history": history,
               "weights_sha256": sha256_file(weights),
               "optimizer_sha256": sha256_file(optimizer_path)}
    (root / "resume.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def load_training_resume(root: Path, model: nn.Module,
                         optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    record_path = root / "resume.json"
    _require(record_path.is_file(), "registro de reanudación ausente")
    record = json.loads(record_path.read_text())
    weights, optimizer_path = root / "resume-weights.safetensors", root / "resume-optimizer.pt"
    _require(weights.is_file() and sha256_file(weights) == record.get("weights_sha256"),
             "pesos de reanudación alterados")
    _require(optimizer_path.is_file() and sha256_file(optimizer_path) == record.get("optimizer_sha256"),
             "estado de optimizador alterado")
    model.load_state_dict(load_file(str(weights), device="cpu"), strict=True)
    try:
        optimizer_state = torch.load(optimizer_path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise V142TransferError("estado de optimizador no es seguro weights_only") from exc
    _require(isinstance(optimizer_state, Mapping), "estado de optimizador inválido")
    optimizer.load_state_dict(optimizer_state)
    return record
