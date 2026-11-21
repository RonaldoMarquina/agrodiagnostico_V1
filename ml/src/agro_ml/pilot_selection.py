"""VAL-only comparison, calibration and pre-TEST freeze for the G1 potato pilot."""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil

import torch
from torch.nn import functional as F

from agro_ml.calibration.calibrator import compute_ece
from agro_ml.evaluation.freezing import TestEvaluationBlockedError
from agro_ml.pilot_training import CLASSES, _choice_key, _metrics, sha256


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_experiment(directory: Path, config_path: Path) -> tuple[dict, dict, list[dict]]:
    metadata_path = directory / "experiment.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "VAL_EXPLORATION_UNAPPROVED" or metadata.get("test_evaluated") is not False:
        raise ValueError("Experimento ajeno a TRAIN/VAL")
    if metadata.get("class_codes") != list(CLASSES) or metadata.get("config_sha256") != sha256(config_path):
        raise ValueError("Configuración de piloto alterada")
    if metadata.get("weights_sha256") != sha256(directory / "pilot-weights.safetensors"):
        raise ValueError("Pesos de experimento alterados")
    if metadata.get("val_metrics_sha256") != sha256(directory / "val-report.json"):
        raise ValueError("Reporte VAL alterado")
    if metadata.get("val_scores_sha256") != sha256(directory / "val-scores.jsonl"):
        raise ValueError("Puntuaciones VAL alteradas")
    current_code = sha256(Path(__file__).with_name("pilot_training.py"))
    if metadata.get("code", {}).get("pilot_code_sha256") != current_code:
        raise ValueError("Código de entrenamiento cambió; repetir ambos experimentos")
    report = json.loads((directory / "val-report.json").read_text(encoding="utf-8"))
    if report.get("dataset_split") != "VAL" or report.get("total_samples", 0) < 80:
        raise ValueError("Reporte VAL incompleto")
    scores = [json.loads(line) for line in (directory / "val-scores.jsonl").read_text(encoding="utf-8").splitlines()]
    expected_count = report["total_samples"] + report["negative_counts"]["negative_evaluated_count"]
    if (len(scores) != expected_count or len(scores) != metadata.get("val_count")
            or len({row.get("image_id") for row in scores}) != len(scores)):
        raise ValueError("Puntuaciones VAL incompletas")
    for row in scores:
        probs = row.get("probabilities")
        if row.get("true_target") not in {0, 1, 2} or not isinstance(probs, list) or len(probs) != 3:
            raise ValueError("Puntuación VAL inválida")
        if any(not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or value > 1
               for value in probs) or abs(sum(probs) - 1) > 1e-4:
            raise ValueError("Probabilidades VAL inválidas")
    return metadata, report, scores


def _fit_platt(raw_scores: list[float], outcomes: list[int]) -> dict:
    if len(raw_scores) != len(outcomes) or len(raw_scores) < 20 or set(outcomes) != {0, 1}:
        raise ValueError("Calibración por clase sin positivos y negativos suficientes")
    x = torch.tensor([math.log(min(max(score, 1e-6), 1 - 1e-6) /
                               (1 - min(max(score, 1e-6), 1 - 1e-6))) for score in raw_scores], dtype=torch.float64)
    y = torch.tensor(outcomes, dtype=torch.float64)
    log_slope = torch.nn.Parameter(torch.tensor(0., dtype=torch.float64))
    intercept = torch.nn.Parameter(torch.tensor(0., dtype=torch.float64))
    optimizer = torch.optim.LBFGS([log_slope, intercept], lr=.5, max_iter=100,
                                  tolerance_grad=1e-10, tolerance_change=1e-12)

    def closure():
        optimizer.zero_grad()
        slope = torch.exp(log_slope)
        loss = F.binary_cross_entropy_with_logits(slope * x + intercept, y)
        loss = loss + .001 * ((slope - 1) ** 2 + intercept ** 2)
        loss.backward()
        return loss

    optimizer.step(closure)
    slope = float(torch.exp(log_slope.detach()))
    bias = float(intercept.detach())
    if not math.isfinite(slope) or not math.isfinite(bias) or slope <= 0:
        raise ValueError("Calibrador no finito")
    return {"method": "PLATT_LOGIT_L2", "slope": round(slope, 8),
            "intercept": round(bias, 8), "support": len(outcomes),
            "correct": sum(outcomes)}


def _calibrate(raw_score: float, params: dict) -> float:
    if not math.isfinite(raw_score) or not 0 <= raw_score <= 1:
        raise ValueError("raw_score inválido")
    clipped = min(max(raw_score, 1e-6), 1 - 1e-6)
    z = params["slope"] * math.log(clipped / (1 - clipped)) + params["intercept"]
    return 1 / (1 + math.exp(-max(-40., min(40., z))))


def fit_calibration(scores: list[dict]) -> tuple[dict, list[float], dict]:
    parameters = {}
    for class_index, code in enumerate(CLASSES):
        selected = [(row["probabilities"][class_index], int(row["true_target"] == class_index))
                    for row in scores if max(range(2), key=lambda i: row["probabilities"][i]) == class_index]
        parameters[code] = _fit_platt([raw for raw, _ in selected], [label for _, label in selected])
    calibrated = []
    outcomes = []
    for row in scores:
        candidate = max(range(2), key=lambda i: row["probabilities"][i])
        calibrated.append(_calibrate(row["probabilities"][candidate], parameters[CLASSES[candidate]]))
        outcomes.append(int(row["true_target"] == candidate))
    positives = [index for index, row in enumerate(scores) if row["true_target"] != 2]
    quality = {"ece_all_val_candidates": compute_ece(calibrated, outcomes),
               "ece_valid_positive_candidates": compute_ece([calibrated[i] for i in positives],
                                                                [outcomes[i] for i in positives])}
    return parameters, calibrated, quality


def verify_freeze(path: Path) -> bool:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    digest = snapshot.pop("freeze_digest", None)
    if (snapshot.get("status") != "LOCKED_BEFORE_TEST" or snapshot.get("g2_approval") is not None
            or snapshot.get("test_evaluated") is not False):
        raise ValueError("Estado de congelamiento inválido")
    if hashlib.sha256(_json_bytes(snapshot)).hexdigest() != digest:
        raise ValueError("Registro de congelamiento alterado")
    ml_root = Path(__file__).resolve().parents[2]
    current_code = {
        "selection_code_sha256": sha256(Path(__file__)),
        "training_code_sha256": sha256(Path(__file__).with_name("pilot_training.py")),
        "preprocessing_code_sha256": sha256(ml_root / "src/agro_ml/data/tensor_preprocessing.py"),
        "dependency_lock_sha256": sha256(ml_root / "uv.lock"),
    }
    for key, current in current_code.items():
        if snapshot.get(key) != current:
            raise ValueError("Código o lock cambió tras congelamiento: " + key)
    for name, expected in snapshot["file_sha256"].items():
        target = path.parent / name
        if target.is_symlink() or not target.is_file() or sha256(target) != expected:
            raise ValueError("Componente congelado alterado: " + name)
    return True


def authorize_pilot_test(freeze_path: Path) -> bool:
    """Fail closed before any future TEST loader is allowed to read its manifest."""
    try:
        return verify_freeze(freeze_path)
    except (FileNotFoundError, ValueError) as exc:
        raise TestEvaluationBlockedError("TEST bloqueado: candidato no congelado o alterado") from exc


def compare_calibrate_freeze(mobile_dir: Path, mobile_config: Path,
                             resnet_dir: Path, resnet_config: Path,
                             protocol_path: Path, output_dir: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if (protocol.get("protocol_version") != "1.2.0" or protocol.get("status") != "APPROVED_G0_DESIGN"
            or protocol.get("candidate_classes") != list(CLASSES)):
        raise ValueError("Protocolo G0 incompatible")
    mobile = _load_experiment(mobile_dir, mobile_config)
    resnet = _load_experiment(resnet_dir, resnet_config)
    if mobile[0]["architecture"] != "mobilenet_v3_small" or resnet[0]["architecture"] != "resnet18":
        raise ValueError("Se requieren MobileNetV3 y ResNet18")
    for key in ("seed", "preprocessing", "train_manifest_sha256", "val_manifest_sha256",
                "g1_evidence_sha256", "train_count", "val_count", "normalization"):
        if mobile[0][key] != resnet[0][key]:
            raise ValueError("Experimentos no comparables: " + key)
    if [row["image_id"] for row in mobile[2]] != [row["image_id"] for row in resnet[2]]:
        raise ValueError("VAL no coincide entre arquitecturas")
    if any(report["latency_p95_ms"] is None or report["latency_p95_ms"] > 2500
           for _, report, _ in (mobile, resnet)):
        raise ValueError("Medición CPU ausente o fuera de presupuesto")
    scored = [("mobilenet_v3_small", mobile_dir, mobile_config, mobile),
              ("resnet18", resnet_dir, resnet_config, resnet)]
    chosen = max(scored, key=lambda item: (_choice_key(item[3][1]),
                                          -item[3][1]["latency_p95_ms"]))
    name, directory, config_path, (metadata, report, scores) = chosen
    if not _choice_key(report)[0]:
        raise ValueError("Ningún candidato satisface mínimos de selección VAL")
    parameters, calibrated, quality = fit_calibration(scores)
    samples = [{"label": row["true_target"]} for row in scores]
    probabilities = [row["probabilities"] for row in scores]
    options = [_metrics(samples, probabilities, round(step / 100, 2), candidate_scores=calibrated)
               for step in range(50, 100)]
    selected_report = max(options, key=_choice_key)
    if not _choice_key(selected_report)[0] or quality["ece_valid_positive_candidates"] > .15:
        raise ValueError("Calibración VAL no satisface criterios G0")
    threshold = selected_report["threshold"]
    selected_report["threshold_status"] = "LOCKED_BEFORE_TEST"
    selected_report["confidence_source"] = "PLATT_LOGIT_L2_FIT_ON_VAL"
    comparison = {"schema_version": 1, "scope": "VAL_ONLY", "selected_architecture": name,
                  "selection_rule": "Viabilidad G0 VAL primero; luego F1 macro, recall mínimo por clase, cobertura, error selectivo, FPR y p95 CPU",
                  "experiments": {arch: {"weights_sha256": meta["weights_sha256"],
                                          "config_sha256": meta["config_sha256"],
                                          "best_epoch": meta["best_epoch_by_val"],
                                          "macro_f1": val_report["macro_f1"],
                                          "per_class_recall": {code: val_report["per_class"][code]["recall"] for code in CLASSES},
                                          "coverage": val_report["selective_coverage"],
                                          "error": val_report["selective_error_rate"],
                                          "abstained": val_report["decision_counts"]["abstained_count"],
                                          "negative_false_accepted": val_report["negative_counts"]["accepted_supported_class_count"],
                                          "negative_total": val_report["negative_counts"]["negative_evaluated_count"],
                                          "latency_median_ms": val_report["latency_median_ms"],
                                          "latency_p95_ms": val_report["latency_p95_ms"]}
                                  for arch, _, _, (meta, val_report, _) in scored}}
    calibration = {"schema_version": 1, "selected_on": "VAL", "class_parameters": parameters,
                   "quality": quality, "raw_score_definition": "softmax probability of candidate disease before domain rejection"}
    thresholds = {"schema_version": 1, "selected_on": "VAL", "per_class": {code: threshold for code in CLASSES},
                  "domain_reject": "OTHER_CROP logit probability >= candidate disease probability",
                  "status": "LOCKED_BEFORE_TEST", "justification": "Chosen on VAL under G0 coverage, error, F1 and negative limits"}
    selected_report["calibration_ece"] = quality
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(directory / "pilot-weights.safetensors", output_dir / "pilot-weights.safetensors")
    shutil.copyfile(config_path, output_dir / "config.json")
    shutil.copyfile(protocol_path, output_dir / "protocol-g0.json")
    for filename, value in (("comparison.json", comparison), ("calibration.json", calibration),
                            ("thresholds.json", thresholds), ("calibrated-val-report.json", selected_report)):
        (output_dir / filename).write_bytes(_json_bytes(value))
    file_hashes = {path.name: sha256(path) for path in output_dir.iterdir() if path.is_file()}
    snapshot = {"schema_version": 1, "status": "LOCKED_BEFORE_TEST", "g2_approval": None,
                "test_evaluated": False, "frozen_at": datetime.now(timezone.utc).isoformat(),
                "frozen_by": "Codex on project owner's instruction", "selected_architecture": name,
                "source_experiment_sha256": sha256(directory / "experiment.json"),
                "selection_code_sha256": sha256(Path(__file__)),
                "training_code_sha256": metadata["code"]["pilot_code_sha256"],
                "preprocessing_code_sha256": metadata["code"]["preprocessing_code_sha256"],
                "dependency_lock_sha256": metadata["code"]["dependency_lock_sha256"],
                "g1_evidence_sha256": metadata["g1_evidence_sha256"],
                "train_manifest_sha256": metadata["train_manifest_sha256"],
                "val_manifest_sha256": metadata["val_manifest_sha256"],
                "protocol_version": protocol["protocol_version"], "file_sha256": file_hashes}
    snapshot["freeze_digest"] = hashlib.sha256(_json_bytes(snapshot)).hexdigest()
    freeze_path = output_dir / "freeze.json"
    freeze_path.write_bytes(_json_bytes(snapshot))
    verify_freeze(freeze_path)
    for file in output_dir.iterdir():
        file.chmod(0o444)
    return {"freeze": str(freeze_path), "status": "LOCKED_BEFORE_TEST",
            "selected_architecture": name, "threshold": threshold,
            "val_macro_f1_calibrated": selected_report["macro_f1"],
            "val_ece": quality["ece_valid_positive_candidates"]}
