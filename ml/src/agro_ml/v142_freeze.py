"""Congelamiento privado y carga independiente del candidato v1.4.2."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from safetensors.torch import load_file
from torch import nn
from torchvision.models import mobilenet_v3_small

from agro_ml.v141_gates import PUBLISHABLE_CLASSES, TECHNICAL_CLASSES
from agro_ml.v142_checkpoint import EXPECTED_SHA256, validate_registry


class V142FreezeError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise V142FreezeError(message)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def verify_freeze(root: Path, *, load_model: bool = True) -> dict[str, Any]:
    record_path = root / "freeze.json"
    _require(record_path.is_file(), "freeze.json ausente")
    record = json.loads(record_path.read_text())
    digest = record.pop("freeze_digest", None)
    _require(digest == hashlib.sha256(_canonical(record)).hexdigest(), "digest de congelamiento alterado")
    _require(record.get("status") == "FROZEN_VAL_PASSED_EXTERNAL_NOT_OPENED" and
             record.get("cycle_version") == "1.4.2", "estado de congelamiento inválido")
    _require(record.get("base_checkpoint", {}).get("sha256") == EXPECTED_SHA256 and
             record["base_checkpoint"].get("redistributed") is False,
             "checkpoint base no está fijado por referencia")
    for name, expected in record.get("file_sha256", {}).items():
        path = root / name
        _require(path.is_file() and sha256_file(path) == expected, f"artefacto congelado alterado: {name}")
    class_map = json.loads((root / "class-map.json").read_text())
    _require(tuple(class_map["technical_classes"]) == TECHNICAL_CLASSES and
             tuple(class_map["publishable_classes"]) == PUBLISHABLE_CLASSES and
             class_map["rejection_classes"] == ["POTATO_HEALTHY", "OTHER_CROP"],
             "mapa de publicación congelado inválido")
    if load_model:
        model = mobilenet_v3_small(weights=None)
        model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 4)
        model.load_state_dict(load_file(str(root / "weights.safetensors"), device="cpu"), strict=True)
        model.eval()
    record["freeze_digest"] = digest
    return record


def freeze_candidate(candidate: Path, output: Path, *, plan: Path, preprocessing: Path,
                     protocol: Path, checkpoint_root: Path,
                     frozen_at: str | None = None) -> dict[str, Any]:
    _require(not output.exists(), "destino de congelamiento ya existe")
    report = json.loads((candidate / "val-report.json").read_text())
    experiment = json.loads((candidate / "experiment.json").read_text())
    _require(report.get("val_selection", {}).get("passed") is True,
             "no se puede congelar un candidato que falla VAL")
    _require(len(experiment.get("history", ())) == 15 and
             sum(item.get("phase") == "HEAD" for item in experiment["history"]) == 3 and
             sum(item.get("phase") == "FINE_TUNE" for item in experiment["history"]) == 12,
             "corrida HEAD/FINE_TUNE incompleta")
    _require(experiment.get("protected_external_partition_accessed") is False and
             experiment.get("historical_test_accessed") is False and
             experiment.get("network_mode") == "none", "aislamiento de entrenamiento inválido")
    provenance = json.loads((checkpoint_root / "provenance.json").read_text())
    validate_registry(provenance, checkpoint_root / provenance["filename"])
    output.mkdir(parents=True, mode=0o700)
    sources = {
        "weights.safetensors": candidate / "weights.safetensors",
        "candidate-config.json": candidate / "candidate-config.json",
        "experiment.json": candidate / "experiment.json",
        "val-report.json": candidate / "val-report.json",
        "train-manifest.jsonl": candidate / "train-manifest.jsonl",
        "val-manifest.jsonl": candidate / "val-manifest.jsonl",
        "preprocessing.json": preprocessing,
        "training-plan.json": plan,
        "protocol-g0.json": protocol,
        "base-weight-provenance.json": checkpoint_root / "provenance.json",
    }
    for name, source in sources.items():
        _require(source.is_file(), f"fuente de congelamiento ausente: {name}")
        shutil.copyfile(source, output / name)
    generated = {
        "class-map.json": {
            "technical_classes": list(TECHNICAL_CLASSES),
            "publishable_classes": list(PUBLISHABLE_CLASSES),
            "rejection_classes": ["POTATO_HEALTHY", "OTHER_CROP"],
            "visible_policy": "NON_PUBLISHABLE_ARGMAX_OR_LOW_CONFIDENCE_TO_NO_CONCLUYENTE",
        },
        "calibration.json": {"method": "TEMPERATURE_SCALING", "temperature": report["temperature"],
                             "selected_on": "VAL", "external_used": False},
        "thresholds.json": {"route": report["route"], "min_confidence": report["threshold"],
                            "selected_on": "VAL", "external_used": False},
        "dependencies.json": experiment["runtime"],
        "commands.json": {"training": experiment["command_contract"],
                          "network": "NONE", "external_mount": False,
                          "historical_test_mount": False},
    }
    for name, value in generated.items():
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    files = {path.name: sha256_file(path) for path in sorted(output.iterdir()) if path.is_file()}
    record: dict[str, Any] = {
        "schema_version": 1,
        "cycle_version": "1.4.2",
        "g0_protocol_version": "1.4.1",
        "status": "FROZEN_VAL_PASSED_EXTERNAL_NOT_OPENED",
        "frozen_at": frozen_at or datetime.now(timezone.utc).isoformat(),
        "selected_epoch": report["selected_epoch"],
        "selected_phase": report["selected_phase"],
        "temperature": report["temperature"],
        "threshold": report["threshold"],
        "base_checkpoint": {"sha256": EXPECTED_SHA256, "storage": "PRIVATE_READ_ONLY_REFERENCE",
                            "redistributed": False},
        "file_sha256": files,
        "external_access_authorized": False,
        "sikkim_external_status": "SEALED_NOT_OPENED",
        "historical_test_status": "INTACT_NOT_OPENED",
        "g2_status": "OPEN_PENDING_EXTERNAL",
        "commercial_use_authorized": False,
    }
    record["freeze_digest"] = hashlib.sha256(_canonical(record)).hexdigest()
    (output / "freeze.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    verify_freeze(output)
    for path in output.iterdir():
        if path.is_file():
            path.chmod(0o440)
    output.chmod(0o550)
    return record
