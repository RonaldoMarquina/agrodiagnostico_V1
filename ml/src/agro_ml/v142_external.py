"""Evaluación EXTERNAL única del bundle congelado v1.4.2."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import resource
import statistics
import time
from typing import Any, Mapping, Sequence
import zipfile

from safetensors.torch import load_file
import torch
from torch import nn
from torchvision.models import mobilenet_v3_small

from agro_ml.data.tensor_preprocessing import image_to_tensor
from agro_ml.v14_gates import (
    EXTERNAL_COUNTS, PUBLISHABLE, calculate_external_metrics,
    sha256_bytes, verify_external_seal,
)
from agro_ml.v141_gates import PUBLISHABLE_CLASSES, TECHNICAL_CLASSES
from agro_ml.v141_training import probabilities, visible_decision
from agro_ml.v142_freeze import verify_freeze
from agro_ml.v142_transfer import validate_preprocessing_contract


FREEZE_DIGEST = "07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a"
WEIGHTS_SHA256 = "e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c"
MANIFEST_SHA256 = "3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992"
SEAL_SHA256 = "ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a"
PROTOCOL_SHA256 = "e3dad24755550c574f33c5fa5b736eec639c9a36b054fcb3fee9e2c3e96550af"
ARCHIVE_SHA256 = "5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc"
ARCHIVE_SIZE = 170_561_971
ZIP_PREFIX = "Sikkim Solanaceae Leaf Image Dataset/"
TEMPERATURE = 0.50
THRESHOLD = 0.80


class V142ExternalError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise V142ExternalError(message)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_jsonl_bytes(content: bytes) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in content.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V142ExternalError("manifiesto EXTERNAL no es JSONL UTF-8 válido") from exc
    _require(bool(rows), "manifiesto EXTERNAL vacío")
    return rows


def validate_frozen_contract(bundle: Path) -> tuple[dict[str, Any], Any]:
    freeze = verify_freeze(bundle, load_model=False)
    _require(freeze.get("freeze_digest") == FREEZE_DIGEST, "freeze v1.4.2 distinto")
    _require(freeze.get("temperature") == TEMPERATURE and freeze.get("threshold") == THRESHOLD,
             "temperatura o umbral congelado cambió")
    _require(freeze.get("file_sha256", {}).get("weights.safetensors") == WEIGHTS_SHA256,
             "pesos congelados distintos")
    class_map = json.loads((bundle / "class-map.json").read_text())
    _require(tuple(class_map.get("technical_classes", ())) == TECHNICAL_CLASSES and
             tuple(class_map.get("publishable_classes", ())) == PUBLISHABLE_CLASSES,
             "mapa de clases congelado distinto")
    calibration = json.loads((bundle / "calibration.json").read_text())
    thresholds = json.loads((bundle / "thresholds.json").read_text())
    _require(calibration == {"external_used": False, "method": "TEMPERATURE_SCALING",
                             "selected_on": "VAL", "temperature": TEMPERATURE},
             "calibración congelada distinta")
    _require(thresholds.get("min_confidence") == THRESHOLD and
             thresholds.get("selected_on") == "VAL" and thresholds.get("external_used") is False,
             "umbral no fue seleccionado exclusivamente en VAL")
    preprocessing = json.loads((bundle / "preprocessing.json").read_text())
    spec = validate_preprocessing_contract(preprocessing)
    return freeze, spec


def validate_zip_catalog(records: Sequence[Mapping[str, Any]], archive: Path, *,
                         expected_size: int = ARCHIVE_SIZE,
                         expected_sha256: str = ARCHIVE_SHA256) -> dict[str, zipfile.ZipInfo]:
    _require(archive.is_file(), "ZIP Sikkim no montado")
    _require(archive.stat().st_size == expected_size and sha256_file(archive) == expected_sha256,
             "ZIP Sikkim cambió")
    expected: dict[str, Mapping[str, Any]] = {}
    for row in records:
        relative = PurePosixPath(str(row.get("source_path", "")))
        _require(not relative.is_absolute() and ".." not in relative.parts and bool(relative.parts),
                 "source_path EXTERNAL inseguro")
        name = ZIP_PREFIX + relative.as_posix()
        _require(name not in expected, "ruta EXTERNAL duplicada")
        expected[name] = row
    catalog: dict[str, zipfile.ZipInfo] = {}
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.filename in expected:
                _require(info.filename not in catalog, "entrada ZIP duplicada")
                _require(not info.is_dir() and info.file_size == expected[info.filename].get("file_size"),
                         "entrada ZIP no es archivo o tiene tamaño distinto")
                catalog[info.filename] = info
    _require(set(catalog) == set(expected), "faltan entradas selladas en el ZIP")
    return catalog


def preflight(bundle: Path, manifest: Path, seal_path: Path, protocol: Path,
              archive: Path, *, purpose: str) -> tuple[dict[str, Any], Any, list[dict[str, Any]]]:
    _require(purpose == "FINAL_EXTERNAL_EVALUATION", "propósito EXTERNAL no permitido")
    _require(os.environ.get("AGRO_NETWORK_MODE") == "none", "evaluación EXTERNAL exige red deshabilitada")
    freeze, spec = validate_frozen_contract(bundle)
    _require(protocol.is_file() and sha256_file(protocol) == PROTOCOL_SHA256,
             "protocolo G0 v1.4.0 cambió")
    manifest_bytes = manifest.read_bytes()
    _require(sha256_bytes(manifest_bytes) == MANIFEST_SHA256, "manifiesto Sikkim cambió")
    _require(seal_path.is_file() and sha256_file(seal_path) == SEAL_SHA256, "sello Sikkim cambió")
    rows = read_jsonl_bytes(manifest_bytes)
    seal = json.loads(seal_path.read_text())
    verify_external_seal(rows, manifest_bytes, seal)
    _require(seal.get("protocol_sha256") == PROTOCOL_SHA256, "sello no referencia el protocolo fijado")
    validate_zip_catalog(rows, archive)
    return freeze, spec, rows


def load_frozen_model(bundle: Path) -> nn.Module:
    model = mobilenet_v3_small(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 4)
    state = load_file(str(bundle / "weights.safetensors"), device="cpu")
    model.load_state_dict(state, strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.eval()
    return model


def create_access_record(output: Path, inputs: Mapping[str, Any], *, started_at: str | None = None) -> dict[str, Any]:
    _require(not output.exists(), "la evaluación EXTERNAL ya fue iniciada")
    output.mkdir(parents=True, mode=0o700)
    record = {"schema_version": 1, "cycle_version": "1.4.2", "purpose": "FINAL_EXTERNAL_EVALUATION",
              "status": "STARTED", "started_at": started_at or datetime.now(timezone.utc).isoformat(),
              "inputs": dict(inputs), "worker_status": "INACTIVE_NOT_AUTHORIZED"}
    descriptor = os.open(output / "access.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True); stream.write("\n")
        stream.flush(); os.fsync(stream.fileno())
    return record


def visible_prediction(logits: Sequence[float]) -> tuple[list[float], str | None, str]:
    probs = probabilities(logits, TEMPERATURE)
    decision = visible_decision(probs, THRESHOLD)
    published = PUBLISHABLE_CLASSES[decision] if decision is not None else None
    return probs, published, "COMPLETADO" if published else "NO_CONCLUYENTE"


def _latency(values: Sequence[float]) -> dict[str, Any]:
    _require(bool(values), "latencias vacías")
    ordered = sorted(values)
    return {"count": len(values), "median_ms": round(statistics.median(ordered), 4),
            "p95_ms": round(ordered[math.ceil(.95 * len(ordered)) - 1], 4),
            "max_ms": round(max(ordered), 4)}


def build_report(predictions: Sequence[Mapping[str, Any]], *, input_hashes: Mapping[str, Any],
                 predictions_sha256: str, peak_rss_mb: float) -> dict[str, Any]:
    base = calculate_external_metrics(predictions)
    per_class: dict[str, Any] = {}
    columns = [*PUBLISHABLE_CLASSES, "NO_CONCLUYENTE"]
    matrix = {code: {column: 0 for column in columns} for code in TECHNICAL_CLASSES}
    for row in predictions:
        visible = row.get("published_diagnosis") or "NO_CONCLUYENTE"
        matrix[row["stratum_code"]][visible] += 1
    for code in PUBLISHABLE_CLASSES:
        tp = base["true_positive"][code]
        fp = sum(row.get("published_diagnosis") == code and row["stratum_code"] != code
                 for row in predictions)
        support = EXTERNAL_COUNTS[code]; fn = support - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[code] = {"tp": tp, "fp": fp, "fn": fn, "support": support,
                           "precision": precision, "recall": recall, "f1": f1,
                           "abstained": sum(row["stratum_code"] == code and
                                            row.get("final_state") == "NO_CONCLUYENTE"
                                            for row in predictions)}
    report = {**base, "schema_version": 1, "cycle_version": "1.4.2", "split": "EXTERNAL",
              "temperature": TEMPERATURE, "threshold": THRESHOLD,
              "per_class": per_class,
              "abstentions": {code: matrix[code]["NO_CONCLUYENTE"] for code in TECHNICAL_CLASSES},
              "visible_confusion_matrix": {"rows_true": list(TECHNICAL_CLASSES),
                  "columns_published": columns, "counts": matrix},
              "latency": {"inference": _latency([float(r["inference_ms"]) for r in predictions]),
                          "end_to_end": _latency([float(r["end_to_end_ms"]) for r in predictions])},
              "peak_rss_mb": peak_rss_mb, "input_hashes": dict(input_hashes),
              "predictions_sha256": predictions_sha256,
              "independence_unit": "UNIQUE_IMAGE_ONLY_NOT_PLANT",
              "plant_independence_verified": False}
    report["all_criteria_passed"] = all(report["criteria"].values())
    return report


def g2_decision(report: Mapping[str, Any], *, freeze_digest: str,
                report_sha256: str, predictions_sha256: str) -> dict[str, Any]:
    passed = bool(report.get("all_criteria_passed")) and all(report.get("criteria", {}).values())
    return {"schema_version": 1, "cycle_version": "1.4.2",
            "status": "CLOSED_APPROVED_BY_PROJECT_OWNER" if passed else "OPEN_EXTERNAL_CRITERIA_FAILED",
            "decision_at": datetime.now(timezone.utc).isoformat(),
            "approval_basis": "Conditional project-owner instruction dated 2026-11-23",
            "freeze_digest": freeze_digest, "external_report_sha256": report_sha256,
            "predictions_sha256": predictions_sha256, "criteria": dict(report.get("criteria", {})),
            "worker_status": "INACTIVE_NOT_AUTHORIZED", "policy_status": "INACTIVE_NOT_IMPORTED",
            "external_reuse_authorized": False}


def _runtime() -> dict[str, Any]:
    model = platform.processor()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                model = line.split(":", 1)[1].strip(); break
    except OSError:
        pass
    return {"cpu_model": model or platform.machine(), "python": platform.python_version(),
            "torch": torch.__version__, "torchvision": __import__("torchvision").__version__,
            "threads": torch.get_num_threads()}


def evaluate_once(bundle: Path, manifest: Path, seal_path: Path, protocol: Path,
                  archive: Path, output: Path) -> dict[str, Any]:
    freeze, spec, rows = preflight(bundle, manifest, seal_path, protocol, archive,
                                   purpose="FINAL_EXTERNAL_EVALUATION")
    model = load_frozen_model(bundle)
    inputs = {"freeze_digest": freeze["freeze_digest"], "weights_sha256": WEIGHTS_SHA256,
              "manifest_sha256": MANIFEST_SHA256, "seal_sha256": SEAL_SHA256,
              "protocol_sha256": PROTOCOL_SHA256, "archive_sha256": ARCHIVE_SHA256,
              "temperature": TEMPERATURE, "threshold": THRESHOLD,
              "preprocessing_sha256": freeze["file_sha256"]["preprocessing.json"]}
    access = create_access_record(output, inputs)
    try:
        predictions = []
        torch.set_num_threads(4)
        with zipfile.ZipFile(archive) as source, torch.inference_mode():
            for row in rows:
                started = time.perf_counter_ns()
                name = ZIP_PREFIX + PurePosixPath(row["source_path"]).as_posix()
                image_bytes = source.read(name)
                _require(len(image_bytes) == row["file_size"] and
                         hashlib.sha256(image_bytes).hexdigest() == row["sha256"],
                         "bytes de imagen EXTERNAL alterados")
                tensor = image_to_tensor(image_bytes, spec, split="EXTERNAL").unsqueeze(0)
                inference_started = time.perf_counter_ns()
                logits = model(tensor)[0].tolist()
                inference_ms = (time.perf_counter_ns() - inference_started) / 1_000_000
                probs, published, state = visible_prediction(logits)
                predictions.append({"image_id": row["image_id"], "sha256": row["sha256"],
                    "stratum_code": row["stratum_code"],
                    "technical_argmax": TECHNICAL_CLASSES[max(range(4), key=lambda i: probs[i])],
                    "published_diagnosis": published, "final_state": state,
                    "probabilities": probs, "inference_ms": inference_ms,
                    "end_to_end_ms": (time.perf_counter_ns() - started) / 1_000_000})
        predictions_path = output / "predictions.jsonl"
        predictions_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in predictions))
        predictions_sha = sha256_file(predictions_path)
        report = build_report(predictions, input_hashes=inputs, predictions_sha256=predictions_sha,
                              peak_rss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2))
        report["runtime"] = _runtime()
        report_path = output / "external-report.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        report_sha = sha256_file(report_path)
        decision = g2_decision(report, freeze_digest=freeze["freeze_digest"],
                               report_sha256=report_sha, predictions_sha256=predictions_sha)
        (output / "g2-decision.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
        access.update({"status": "COMPLETED", "completed_at": datetime.now(timezone.utc).isoformat(),
                       "prediction_count": len(predictions), "predictions_sha256": predictions_sha,
                       "external_report_sha256": report_sha,
                       "g2_decision_sha256": sha256_file(output / "g2-decision.json")})
        (output / "access.json").write_text(json.dumps(access, indent=2, sort_keys=True) + "\n")
        for path in output.iterdir():
            if path.is_file(): path.chmod(0o440)
        output.chmod(0o550)
        return {"report": report, "decision": decision, "access": access}
    except Exception as exc:
        access.update({"status": "FAILED_TECHNICAL", "failed_at": datetime.now(timezone.utc).isoformat(),
                       "error_type": type(exc).__name__, "error": str(exc)})
        (output / "access.json").write_text(json.dumps(access, indent=2, sort_keys=True) + "\n")
        for path in output.iterdir():
            if path.is_file():
                path.chmod(0o440)
        output.chmod(0o550)
        raise


def verify_completed_output(output: Path) -> dict[str, Any]:
    access = json.loads((output / "access.json").read_text())
    _require(access.get("status") == "COMPLETED" and access.get("prediction_count") == 362,
             "evaluación EXTERNAL no completada exactamente una vez")
    predictions_path, report_path = output / "predictions.jsonl", output / "external-report.json"
    decision_path = output / "g2-decision.json"
    _require(sha256_file(predictions_path) == access.get("predictions_sha256") and
             sha256_file(report_path) == access.get("external_report_sha256") and
             sha256_file(decision_path) == access.get("g2_decision_sha256"),
             "evidencia EXTERNAL alterada")
    predictions = [json.loads(line) for line in predictions_path.read_text().splitlines()]
    report = json.loads(report_path.read_text())
    recomputed = build_report(predictions, input_hashes=report["input_hashes"],
                              predictions_sha256=access["predictions_sha256"],
                              peak_rss_mb=report["peak_rss_mb"])
    for key in ("denominators", "true_positive", "recall", "f1", "macro_f1", "criteria",
                "per_class", "abstentions", "visible_confusion_matrix", "all_criteria_passed"):
        _require(recomputed[key] == report[key], f"métrica EXTERNAL no reproducible: {key}")
    decision = json.loads(decision_path.read_text())
    _require(decision.get("worker_status") == "INACTIVE_NOT_AUTHORIZED" and
             decision.get("policy_status") == "INACTIVE_NOT_IMPORTED", "worker o política activados")
    return {"access": access, "report": report, "decision": decision}
