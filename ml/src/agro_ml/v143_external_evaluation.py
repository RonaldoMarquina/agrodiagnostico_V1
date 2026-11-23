"""Evaluación EXTERNAL única v1.4.3 con el freeze v1.4.2 intacto."""

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

from safetensors.torch import load_file
import torch
from torch import nn
from torchvision.models import mobilenet_v3_small

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.v141_gates import PUBLISHABLE_CLASSES, TECHNICAL_CLASSES
from agro_ml.v141_training import probabilities, visible_decision
from agro_ml.v142_freeze import verify_freeze
from agro_ml.v143_external_admission import read_manifest, verify_preflight


CYCLE_VERSION = "1.4.3"
FREEZE_DIGEST = "07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a"
WEIGHTS_SHA256 = "e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c"
MANIFEST_SHA256 = "20e0ba6729d08920cae3b93d914ddbaaed6c44c1f3ef6dc8b5c661700bd5e9d1"
PREFLIGHT_SUMMARY_SHA256 = "3104fe4b42cd2166e11bea50ac1af82a2a2d9709b2043285154a86c8df8ab050"
CONTRACT_SHA256 = "76debfc7c16b9d8b9567fca95012e091d0379e4d622ac21b871e9ead9ba0befb"
PROTOCOL_SHA256 = "e5d9288c6cc7c78263d29bd311d9257df503dc39abc3eda4427ada51eee842b7"
SEAL_SHA256 = "d0c76dc4b9d398cb779d71f82e9baaa250ea8a097a2d2b3ad1a8bf89efade7d1"
TEMPERATURE = 0.50
THRESHOLD = 0.80
COUNTS = {
    "POTATO_EARLY_BLIGHT": 50,
    "POTATO_LATE_BLIGHT": 50,
    "POTATO_HEALTHY": 50,
    "OTHER_CROP": 200,
}


class V143ExternalEvaluationError(ValueError):
    """La apertura no satisface el contrato EXTERNAL v1.4.3."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V143ExternalEvaluationError(message)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_frozen_inputs(bundle: Path, contract_path: Path) -> tuple[dict[str, Any], TensorSpec]:
    freeze = verify_freeze(bundle, load_model=False)
    _require(freeze.get("freeze_digest") == FREEZE_DIGEST, "freeze v1.4.2 distinto")
    _require(freeze.get("temperature") == TEMPERATURE and freeze.get("threshold") == THRESHOLD,
             "temperatura o umbral congelado cambió")
    _require(freeze.get("file_sha256", {}).get("weights.safetensors") == WEIGHTS_SHA256,
             "pesos congelados distintos")
    class_map = json.loads((bundle / "class-map.json").read_text())
    _require(tuple(class_map.get("technical_classes", ())) == TECHNICAL_CLASSES and
             tuple(class_map.get("publishable_classes", ())) == PUBLISHABLE_CLASSES and
             class_map.get("rejection_classes") == ["POTATO_HEALTHY", "OTHER_CROP"],
             "mapa de clases congelado distinto")
    calibration = json.loads((bundle / "calibration.json").read_text())
    threshold = json.loads((bundle / "thresholds.json").read_text())
    _require(calibration == {"external_used": False, "method": "TEMPERATURE_SCALING",
                             "selected_on": "VAL", "temperature": TEMPERATURE},
             "calibración congelada distinta")
    _require(threshold.get("min_confidence") == THRESHOLD and
             threshold.get("selected_on") == "VAL" and threshold.get("external_used") is False,
             "umbral congelado distinto")
    _require(contract_path.is_file() and sha256_file(contract_path) == CONTRACT_SHA256,
             "contrato de preprocesado v1.4.3 cambió")
    contract = json.loads(contract_path.read_text())
    frozen = contract.get("frozen_model_parameters", {})
    _require(contract.get("preprocessing_version") == CYCLE_VERSION and
             frozen.get("freeze_digest") == FREEZE_DIGEST and
             frozen.get("weights_sha256") == WEIGHTS_SHA256 and
             frozen.get("temperature") == TEMPERATURE and frozen.get("threshold") == THRESHOLD and
             tuple(frozen.get("technical_classes", ())) == TECHNICAL_CLASSES and
             tuple(frozen.get("publishable_classes", ())) == PUBLISHABLE_CLASSES,
             "contrato v1.4.3 no conserva el freeze")
    return freeze, TensorSpec(width=224, height=224, min_dimension=200, max_dimension=6000)


def _safe_image(images_root: Path, source_path: str) -> Path:
    _require(images_root.is_dir() and not images_root.is_symlink(), "raíz EXTERNAL insegura")
    relative = PurePosixPath(source_path)
    _require(bool(relative.parts) and not relative.is_absolute() and ".." not in relative.parts,
             "source_path EXTERNAL inseguro")
    root = images_root.resolve()
    candidate = images_root.joinpath(*relative.parts)
    _require(candidate.is_file() and not candidate.is_symlink(), "archivo EXTERNAL ausente o inseguro")
    _require(candidate.resolve().is_relative_to(root), "archivo EXTERNAL sale de la raíz")
    return candidate


def validate_image_catalog(rows: Sequence[Mapping[str, Any]], images_root: Path) -> dict[str, Path]:
    expected: dict[str, Path] = {}
    for row in rows:
        path = _safe_image(images_root, str(row.get("source_path", "")))
        relative = path.relative_to(images_root).as_posix()
        _require(relative not in expected, "ruta EXTERNAL duplicada")
        _require(path.stat().st_size == row.get("file_size") and sha256_file(path) == row.get("sha256"),
                 "tamaño o SHA-256 EXTERNAL cambió")
        expected[relative] = path
    actual = {path.relative_to(images_root).as_posix() for path in images_root.rglob("*")
              if path.is_file() and not path.is_symlink()}
    _require(actual == set(expected), "la raíz EXTERNAL contiene archivos ausentes o extra")
    return expected


def preflight(bundle: Path, manifest: Path, seal_path: Path, protocol: Path,
              contract: Path, preflight_dir: Path, images_root: Path, *,
              purpose: str) -> tuple[dict[str, Any], TensorSpec, list[dict[str, Any]]]:
    _require(purpose == "FINAL_EXTERNAL_EVALUATION", "propósito EXTERNAL no permitido")
    _require(os.environ.get("AGRO_NETWORK_MODE") == "none", "evaluación exige red deshabilitada")
    freeze, spec = validate_frozen_inputs(bundle, contract)
    _require(protocol.is_file() and sha256_file(protocol) == PROTOCOL_SHA256,
             "protocolo G0 v1.4.3 cambió")
    manifest_bytes, rows = read_manifest(manifest)
    _require(hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256,
             "manifiesto EXTERNAL cambió")
    _require(len(rows) == 350 and Counter(row["stratum_code"] for row in rows) == Counter(COUNTS),
             "conteos EXTERNAL cambiaron")
    summary = verify_preflight(manifest, contract, preflight_dir)
    _require(sha256_file(preflight_dir / "preflight-summary.json") == PREFLIGHT_SUMMARY_SHA256 and
             summary.get("model_loaded") is False and summary.get("external_opened_for_evaluation") is False,
             "preflight EXTERNAL cambió o ya abrió evaluación")
    _require(seal_path.is_file() and sha256_file(seal_path) == SEAL_SHA256, "sello EXTERNAL cambió")
    seal = json.loads(seal_path.read_text())
    _require(seal.get("status") == "SEALED_NOT_OPENED_FOR_EVALUATION" and
             seal.get("record_count") == 350 and seal.get("counts_by_stratum") == dict(sorted(COUNTS.items())) and
             seal.get("manifest_sha256") == MANIFEST_SHA256 and
             seal.get("preflight_summary_sha256") == PREFLIGHT_SUMMARY_SHA256 and
             seal.get("preprocessing_contract_sha256") == CONTRACT_SHA256 and
             seal.get("approval_sha256") == PROTOCOL_SHA256 and
             seal.get("weights_sha256") == WEIGHTS_SHA256 and
             seal.get("temperature") == TEMPERATURE and seal.get("threshold") == THRESHOLD and
             seal.get("sikkim_reused") is False and seal.get("opened_for_evaluation") is False,
             "contenido del sello EXTERNAL inválido")
    # El sello contiene deliberadamente `sikkim_reused=false`; no debe confundirse
    # con una fuente de entrada. La bandera ya fue validada de forma estructurada.
    searchable = (manifest_bytes + protocol.read_bytes()).lower()
    _require(b"sikkim" not in searchable and b"4wz7zbk635" not in searchable,
             "Sikkim está prohibido en v1.4.3")
    validate_image_catalog(rows, images_root)
    return freeze, spec, rows


def load_frozen_model(bundle: Path) -> nn.Module:
    model = mobilenet_v3_small(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 4)
    model.load_state_dict(load_file(str(bundle / "weights.safetensors"), device="cpu"), strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.eval()
    return model


def create_access_record(output: Path, inputs: Mapping[str, Any], *,
                         started_at: str | None = None) -> dict[str, Any]:
    _require(not output.exists(), "la evaluación EXTERNAL ya fue iniciada")
    output.mkdir(parents=True, mode=0o700)
    record = {"schema_version": 1, "cycle_version": CYCLE_VERSION,
              "purpose": "FINAL_EXTERNAL_EVALUATION", "status": "STARTED",
              "started_at": started_at or datetime.now(timezone.utc).isoformat(),
              "inputs": dict(inputs), "network_mode": "none",
              "training": False, "calibration": False, "selection": False,
              "worker_status": "INACTIVE_NOT_AUTHORIZED"}
    descriptor = os.open(output / "access.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
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
    actual_counts = Counter(row.get("stratum_code") for row in predictions)
    _require(len(predictions) == 350 and actual_counts == Counter(COUNTS),
             "predicciones EXTERNAL incompletas")
    columns = [*PUBLISHABLE_CLASSES, "NO_CONCLUYENTE"]
    matrix = {code: {column: 0 for column in columns} for code in TECHNICAL_CLASSES}
    for row in predictions:
        visible = row.get("published_diagnosis") or "NO_CONCLUYENTE"
        _require(visible in columns and row.get("stratum_code") in matrix, "predicción inválida")
        matrix[row["stratum_code"]][visible] += 1
    per_class: dict[str, Any] = {}
    for code in PUBLISHABLE_CLASSES:
        tp = matrix[code][code]
        fp = sum(matrix[other][code] for other in TECHNICAL_CLASSES if other != code)
        support = COUNTS[code]
        fn = support - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[code] = {"tp": tp, "fp": fp, "fn": fn, "support": support,
                           "precision": precision, "recall": recall, "f1": f1,
                           "abstained": matrix[code]["NO_CONCLUYENTE"]}
    macro_f1 = sum(item["f1"] for item in per_class.values()) / 2
    healthy_false = sum(matrix["POTATO_HEALTHY"][code] for code in PUBLISHABLE_CLASSES)
    healthy_rejected = matrix["POTATO_HEALTHY"]["NO_CONCLUYENTE"]
    other_false = sum(matrix["OTHER_CROP"][code] for code in PUBLISHABLE_CLASSES)
    criteria = {
        "macro_f1": macro_f1 >= .75,
        "early_recall": matrix["POTATO_EARLY_BLIGHT"]["POTATO_EARLY_BLIGHT"] >= 38,
        "late_recall": matrix["POTATO_LATE_BLIGHT"]["POTATO_LATE_BLIGHT"] >= 38,
        "healthy_false_publication": healthy_false <= 5,
        "healthy_rejection": healthy_rejected >= 45,
        "other_crop_false_publication": other_false <= 10,
    }
    report = {
        "schema_version": 1, "cycle_version": CYCLE_VERSION, "split": "EXTERNAL",
        "temperature": TEMPERATURE, "threshold": THRESHOLD,
        "denominators": dict(COUNTS), "per_class": per_class, "macro_f1": macro_f1,
        "healthy_false_publication": {"numerator": healthy_false, "denominator": 50,
                                      "maximum": 5},
        "healthy_no_concluyente": {"numerator": healthy_rejected, "denominator": 50,
                                    "minimum": 45},
        "other_crop_false_publication": {"numerator": other_false, "denominator": 200,
                                         "maximum": 10},
        "abstentions": {code: matrix[code]["NO_CONCLUYENTE"] for code in TECHNICAL_CLASSES},
        "visible_confusion_matrix": {"rows_true": list(TECHNICAL_CLASSES),
                                     "columns_published": columns, "counts": matrix},
        "latency": {"inference": _latency([float(row["inference_ms"]) for row in predictions]),
                    "end_to_end": _latency([float(row["end_to_end_ms"]) for row in predictions])},
        "peak_rss_mb": peak_rss_mb, "input_hashes": dict(input_hashes),
        "predictions_sha256": predictions_sha256, "criteria": criteria,
        "independence_unit": "UNIQUE_IMAGE_ONLY_NOT_PLANT_OR_SESSION",
        "plant_or_session_independence_verified": False,
    }
    report["all_criteria_passed"] = all(criteria.values())
    return report


def g2_decision(report: Mapping[str, Any], *, report_sha256: str,
                predictions_sha256: str) -> dict[str, Any]:
    passed = bool(report.get("all_criteria_passed")) and all(report.get("criteria", {}).values())
    return {"schema_version": 1, "cycle_version": CYCLE_VERSION,
            "status": "CLOSED_APPROVED_BY_PROJECT_OWNER" if passed else "OPEN_EXTERNAL_CRITERIA_FAILED",
            "decision_at": datetime.now(timezone.utc).isoformat(),
            "approval_basis": "Project-owner G0 v1.4.3 approval dated 2026-11-23",
            "freeze_digest": FREEZE_DIGEST, "seal_sha256": SEAL_SHA256,
            "external_report_sha256": report_sha256, "predictions_sha256": predictions_sha256,
            "criteria": dict(report.get("criteria", {})),
            "worker_status": "INACTIVE_NOT_AUTHORIZED",
            "policy_status": "INACTIVE_NOT_IMPORTED", "external_reuse_authorized": False}


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


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def evaluate_once(bundle: Path, manifest: Path, seal_path: Path, protocol: Path,
                  contract: Path, preflight_dir: Path, images_root: Path,
                  output: Path) -> dict[str, Any]:
    freeze, spec, rows = preflight(bundle, manifest, seal_path, protocol, contract,
                                   preflight_dir, images_root,
                                   purpose="FINAL_EXTERNAL_EVALUATION")
    model = load_frozen_model(bundle)
    inputs = {"freeze_digest": freeze["freeze_digest"], "weights_sha256": WEIGHTS_SHA256,
              "manifest_sha256": MANIFEST_SHA256, "preflight_summary_sha256": PREFLIGHT_SUMMARY_SHA256,
              "seal_sha256": SEAL_SHA256, "protocol_sha256": PROTOCOL_SHA256,
              "preprocessing_contract_sha256": CONTRACT_SHA256,
              "temperature": TEMPERATURE, "threshold": THRESHOLD}
    access = create_access_record(output, inputs)
    try:
        predictions: list[dict[str, Any]] = []
        torch.set_num_threads(4)
        with torch.inference_mode():
            for row in rows:
                started = time.perf_counter_ns()
                path = _safe_image(images_root, row["source_path"])
                content = path.read_bytes()
                _require(len(content) == row["file_size"] and
                         hashlib.sha256(content).hexdigest() == row["sha256"],
                         "bytes EXTERNAL cambiaron durante la evaluación")
                tensor = image_to_tensor(content, spec, split="EXTERNAL").unsqueeze(0)
                inference_started = time.perf_counter_ns()
                logits = model(tensor)[0].tolist()
                inference_ms = (time.perf_counter_ns() - inference_started) / 1_000_000
                probs, published, state = visible_prediction(logits)
                predictions.append({"image_id": row["image_id"], "sha256": row["sha256"],
                    "stratum_code": row["stratum_code"],
                    "technical_argmax": TECHNICAL_CLASSES[max(range(4), key=lambda index: probs[index])],
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
        _write_json(report_path, report)
        report_sha = sha256_file(report_path)
        decision = g2_decision(report, report_sha256=report_sha,
                               predictions_sha256=predictions_sha)
        decision_path = output / "g2-decision.json"
        _write_json(decision_path, decision)
        access.update({"status": "COMPLETED", "completed_at": datetime.now(timezone.utc).isoformat(),
                       "prediction_count": len(predictions), "predictions_sha256": predictions_sha,
                       "external_report_sha256": report_sha,
                       "g2_decision_sha256": sha256_file(decision_path)})
        _write_json(output / "access.json", access)
        for path in output.iterdir():
            if path.is_file(): path.chmod(0o440)
        output.chmod(0o550)
        return {"access": access, "report": report, "decision": decision}
    except Exception as exc:
        access.update({"status": "FAILED_TECHNICAL", "failed_at": datetime.now(timezone.utc).isoformat(),
                       "error_type": type(exc).__name__, "error": str(exc)})
        _write_json(output / "access.json", access)
        for path in output.iterdir():
            if path.is_file(): path.chmod(0o440)
        output.chmod(0o550)
        raise


def verify_completed_output(output: Path) -> dict[str, Any]:
    access = json.loads((output / "access.json").read_text())
    _require(access.get("status") == "COMPLETED" and access.get("prediction_count") == 350,
             "evaluación EXTERNAL no se completó exactamente una vez")
    predictions_path = output / "predictions.jsonl"
    report_path = output / "external-report.json"
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
    for key in ("denominators", "per_class", "macro_f1", "healthy_false_publication",
                "healthy_no_concluyente", "other_crop_false_publication", "abstentions",
                "visible_confusion_matrix", "criteria", "all_criteria_passed"):
        _require(recomputed[key] == report[key], f"métrica EXTERNAL no reproducible: {key}")
    decision = json.loads(decision_path.read_text())
    _require(decision.get("worker_status") == "INACTIVE_NOT_AUTHORIZED" and
             decision.get("policy_status") == "INACTIVE_NOT_IMPORTED",
             "worker o política fueron activados")
    return {"access": access, "report": report, "decision": decision}
