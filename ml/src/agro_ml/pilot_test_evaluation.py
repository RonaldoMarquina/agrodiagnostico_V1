"""One-shot independent TEST evaluation of the previously frozen potato pilot."""

from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import resource
import statistics
import time

import torch
from safetensors.torch import load_file

from agro_ml.calibration.calibrator import compute_ece
from agro_ml.data.g1_evidence import load_evidence, validate_image_evidence
from agro_ml.data.partitioning import verify_partition_leakage, verify_test_partition_seal
from agro_ml.data.tensor_preprocessing import image_to_tensor
from agro_ml.evaluation.metrics import generate_evaluation_report
from agro_ml.pilot_selection import _calibrate, authorize_pilot_test
from agro_ml.pilot_training import (CLASSES, OTHER_INDEX, _source_inventory,
                                    build_model, read_config, sha256, technical_decision)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = reader.fieldnames
    if not rows or not fields:
        raise ValueError("Manifiesto G1 vacío")
    return rows, fields


def _serialized(rows: list[dict], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _ece_bins(scores: list[float], outcomes: list[int], bins: int = 10) -> list[dict]:
    result = []
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        selected = [(score, correct) for score, correct in zip(scores, outcomes)
                    if lower <= score < upper or (index == bins - 1 and lower <= score <= upper)]
        if selected:
            result.append({"bin": index, "count": len(selected),
                           "sum_confidence": round(sum(score for score, _ in selected), 8),
                           "correct_count": sum(correct for _, correct in selected)})
    return result


def score_frozen_test(rows: list[dict], calibration: dict, thresholds: dict,
                      protocol: dict, latencies: list[float], rss_mb: float) -> dict:
    """Pure report calculation. Input rows are fixed model outputs, never a tuning set."""
    if (not rows or len(rows) != len(latencies)
            or protocol.get("protocol_version") != "1.2.0"
            or calibration.get("selected_on") != "VAL" or thresholds.get("selected_on") != "VAL"
            or thresholds.get("status") != "LOCKED_BEFORE_TEST"
            or set(thresholds.get("per_class", {})) != set(CLASSES)
            or set(calibration.get("class_parameters", {})) != set(CLASSES)
            or any(thresholds["per_class"][code] != .5 for code in CLASSES)):
        raise ValueError("Política congelada incompatible con G0 v1.2.0")
    true, pred, confidence, abstained = [], [], [], []
    negative_published = []
    published_by_negative = {code: 0 for code in CLASSES}
    accepted_scores, accepted_outcomes = [], []
    all_scores, all_outcomes = [], []
    raw_brier_sum = 0.0
    entropy_sum = margin_sum = 0.0
    confusion = {code: {outcome: 0 for outcome in (*CLASSES, "NO_CONCLUYENTE")}
                 for code in (*CLASSES, "OTHER_CROP")}
    abstained_correct_candidate = {code: 0 for code in CLASSES}
    for row in rows:
        probs = row["probabilities"]
        target = row["target"]
        if (type(target) is not int or target not in (0, 1, OTHER_INDEX)
                or not isinstance(probs, list) or len(probs) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       or not 0 <= value <= 1 for value in probs)
                or abs(sum(probs) - 1) > 1e-4):
            raise ValueError("Salida técnica no finita o incompatible")
        candidate = max(range(2), key=lambda index: probs[index])
        code = CLASSES[candidate]
        score = _calibrate(probs[candidate], calibration["class_parameters"][code])
        accepted = technical_decision(probs, thresholds["per_class"][code], score)
        truth_code = CLASSES[target] if target != OTHER_INDEX else "OTHER_CROP"
        published = CLASSES[accepted] if accepted is not None else "NO_CONCLUYENTE"
        confusion[truth_code][published] += 1
        raw_brier_sum += sum((value - int(index == target)) ** 2 for index, value in enumerate(probs))
        entropy_sum -= sum(value * math.log(value) for value in probs if value)
        ordered = sorted(probs, reverse=True)
        margin_sum += ordered[0] - ordered[1]
        if target == OTHER_INDEX:
            negative_published.append(None if accepted is None else CLASSES[accepted])
            if accepted is not None:
                published_by_negative[CLASSES[accepted]] += 1
            continue
        correct_candidate = int(candidate == target)
        all_scores.append(score)
        all_outcomes.append(correct_candidate)
        true.append(target)
        pred.append(candidate)
        confidence.append(score)
        abstained.append(accepted is None)
        if accepted is None and correct_candidate:
            abstained_correct_candidate[CLASSES[target]] += 1
        if accepted is not None:
            accepted_scores.append(score)
            accepted_outcomes.append(correct_candidate)
    valid_latencies = [latency for row, latency in zip(rows, latencies) if row["target"] != OTHER_INDEX]
    report = generate_evaluation_report(
        "TEST", true, pred, confidence, list(CLASSES), abstained=abstained,
        negative_published_classes=negative_published,
        latency_measurements_ms=valid_latencies, measured_peak_rss_mb=rss_mb,
    ).to_dict()
    report["confusion_with_abstention_and_negatives"] = confusion
    report["per_class_negative_false_accepted"] = published_by_negative
    report["per_class_correct_candidate_abstained"] = abstained_correct_candidate
    report["calibration"] = {
        "selected_on": "VAL", "confidence_definition": "Platt-calibrated score of candidate disease",
        "ece_accepted_positives": compute_ece(accepted_scores, accepted_outcomes) if accepted_scores else None,
        "ece_all_positive_candidates": compute_ece(all_scores, all_outcomes) if all_scores else None,
        "accepted_brier_binary": round(sum((score - outcome) ** 2 for score, outcome
                                             in zip(accepted_scores, accepted_outcomes)) / len(accepted_scores), 6)
        if accepted_scores else None,
        "accepted_brier_sum": round(sum((score - outcome) ** 2 for score, outcome
                                        in zip(accepted_scores, accepted_outcomes)), 8),
        "accepted_brier_denominator": len(accepted_scores),
        "ece_bins_accepted": _ece_bins(accepted_scores, accepted_outcomes),
        "ece_bins_all_positive_candidates": _ece_bins(all_scores, all_outcomes),
        "raw_three_target_brier": round(raw_brier_sum / len(rows), 6),
        "raw_three_target_brier_sum": round(raw_brier_sum, 8),
        "raw_three_target_brier_denominator": len(rows),
        "raw_three_target_scope": "Two diseases plus technical OTHER_CROP; uncalibrated model softmax",
    }
    # G0's VAL calibration used all valid positive candidates, including technical
    # abstentions. Preserve that denominator for the independent TEST comparison.
    # Accepted-only calibration is also reported for the visible diagnoses.
    report["ece"] = report["calibration"]["ece_all_positive_candidates"]
    report["brier_score"] = report["calibration"]["accepted_brier_binary"]
    report["mean_entropy"] = round(entropy_sum / len(rows), 6)
    report["mean_margin"] = round(margin_sum / len(rows), 6)
    report["uncertainty_denominator"] = len(rows)
    report["abstained_correct_candidate_total"] = sum(abstained_correct_candidate.values())
    report["rates"] = {
        "accuracy": {"numerator": sum(report["confusion_matrix"][i][i] for i in range(2)),
                     "denominator": len(true), "value": report["accuracy"]},
        "coverage": {"numerator": report["decision_counts"]["accepted_count"],
                     "denominator": len(true), "value": report["selective_coverage"]},
        "abstention": {"numerator": report["decision_counts"]["abstained_count"],
                       "denominator": len(true), "value": report["non_conclusive_rate"]},
        "selective_error": {"numerator": report["decision_counts"]["incorrect_accepted_count"],
                            "denominator": report["decision_counts"]["accepted_count"],
                            "value": report["selective_error_rate"]},
        "negative_acceptance": {"numerator": report["negative_counts"]["accepted_supported_class_count"],
                                "denominator": report["negative_counts"]["negative_evaluated_count"],
                                "value": report["negative_samples_fpr"]},
    }
    for code, metrics in report["per_class"].items():
        tp, fp, fn = (metrics[key] for key in ("true_positive", "false_positive", "false_negative"))
        metrics["precision_counts"] = {"numerator": tp, "denominator": tp + fp}
        metrics["recall_counts"] = {"numerator": tp, "denominator": metrics["support"]}
        metrics["f1_counts"] = {"numerator": 2 * tp, "denominator": 2 * tp + fp + fn}
        metrics["false_negative_due_to_abstention"] = metrics["abstained_count"]
        metrics["false_positive_from_negatives"] = published_by_negative[code]
    limits = protocol["metrics_thresholds"]
    evaluations = {
        "macro_f1_test": (report["macro_f1"], limits["macro_f1_test_min"], ">="),
        "coverage": (report["selective_coverage"], limits["selective_coverage_min"], ">="),
        "selective_error": (report["selective_error_rate"], limits["selective_error_max"], "<="),
        "negative_acceptance": (report["negative_samples_fpr"], limits["negative_samples_fpr_max"], "<="),
        "ece_all_positive_candidates": (report["ece"], limits["calibration_ece_max"], "<="),
    }
    for code in CLASSES:
        evaluations[f"recall_{code}"] = (report["per_class"][code]["recall"],
                                         limits["class_recall_test_min"], ">=")
        evaluations[f"f1_{code}"] = (report["per_class"][code]["f1"],
                                     limits["class_f1_test_min"], ">=")
    budget = protocol["compute_budget_cpu"]
    evaluations["cpu_median_ms"] = (report["latency_median_ms"], budget["latency_median_ms_max"], "<=")
    evaluations["cpu_p95_ms"] = (report["latency_p95_ms"], budget["latency_p95_ms_max"], "<=")
    evaluations["cpu_max_ms"] = (round(max(latencies), 4), budget["latency_hard_limit_ms"], "<=")
    evaluations["cpu_peak_rss_mb"] = (report["max_rss_mb"], budget["max_rss_mb"], "<=")
    report["cpu_latency"] = {"measured_count": len(latencies),
                             "median_all_ms": round(statistics.median(latencies), 4),
                             "p95_all_ms": round(sorted(latencies)[math.ceil(.95 * len(latencies)) - 1], 4),
                             "maximum_all_ms": round(max(latencies), 4),
                             "scope": "Decoding, preprocessing and model call; excludes HTTP/queue/storage"}
    report["g0_checks"] = {key: {"observed": observed, "limit": limit,
                                  "operator": operator,
                                  "passed": observed is not None and
                                  (observed >= limit if operator == ">=" else observed <= limit)}
                           for key, (observed, limit, operator) in evaluations.items()}
    report["g0_numeric_pass"] = all(item["passed"] for item in report["g0_checks"].values())
    report["external"] = {"status": "NOT_AVAILABLE", "reason": "No authorized independent field set for pilot"}
    report["full_flow_latency"] = {"status": "NOT_MEASURED", "reason": "Worker real not activated"}
    report["g2_approval"] = None
    return report


def evaluate_once(freeze_path: Path, split_root: Path, images_root: Path,
                  evidence_path: Path, expected_seal_sha256: str,
                  expected_freeze_sha256: str, output_dir: Path) -> dict:
    """Fail closed, then consume the actual sealed TEST once and persist all results."""
    if output_dir.exists():
        raise FileExistsError("Evaluación de TEST ya iniciada o completada")
    if sha256(freeze_path) != expected_freeze_sha256:
        raise ValueError("Snapshot congelado distinto del aprobado para esta evaluación")
    authorize_pilot_test(freeze_path)
    freeze = _json(freeze_path)
    frozen_dir = freeze_path.parent
    config, spec = read_config(frozen_dir / "config.json")
    calibration = _json(frozen_dir / "calibration.json")
    thresholds = _json(frozen_dir / "thresholds.json")
    protocol = _json(frozen_dir / "protocol-g0.json")
    if (config["architecture"] != "mobilenet_v3_small" or freeze["selected_architecture"] != config["architecture"]
            or config["class_codes"] != list(CLASSES) or freeze["protocol_version"] != "1.2.0"
            or freeze["g1_evidence_sha256"] != sha256(evidence_path)
            or sha256(split_root / "test-seal.json") != expected_seal_sha256):
        raise ValueError("Modelo, G1 o sello no coinciden con el congelamiento")
    seal = _json(split_root / "test-seal.json")
    if (seal.get("protocol_version") != "1.2.0" or seal.get("test_count", 0) <= 0
            or seal.get("external_count") != 0):
        raise ValueError("Sello G1 o disponibilidad EXTERNAL incompatibles")
    output_dir.mkdir(parents=True, exist_ok=False)
    access = output_dir / "test-access.json"
    access.write_text(json.dumps({"status": "STARTED", "at": datetime.now(timezone.utc).isoformat(),
                                  "freeze_sha256": expected_freeze_sha256,
                                  "seal_sha256": expected_seal_sha256}, indent=2) + "\n", encoding="utf-8")
    try:
        positives, positive_fields = _csv(split_root / "positives.csv")
        negatives, negative_fields = _csv(split_root / "negatives.csv")
        verify_partition_leakage(positives + negatives)
        test_positive, _ = _csv(split_root / "test-positives.csv")
        test_negative, _ = _csv(split_root / "test-negatives.csv")
        if (any(row.get("split") != "TEST" for row in test_positive + test_negative)
                or (split_root / "test-positives.csv").read_bytes() !=
                _serialized([row for row in positives if row["split"] == "TEST"], positive_fields)
                or (split_root / "test-negatives.csv").read_bytes() !=
                _serialized([row for row in negatives if row["split"] == "TEST"], negative_fields)
                or not verify_test_partition_seal(test_positive + test_negative, split_root / "test-seal.json")):
            raise ValueError("TEST materializado no coincide con el sello G1")
        if len(test_positive + test_negative) != seal["test_count"]:
            raise ValueError("Conteo TEST distinto del sello")
        for code in CLASSES:
            selected = [row for row in test_positive if row["class_code"] == code]
            if (len(selected) < protocol["partition_minimums"]["test"]["min_samples_per_class"]
                    or len({row["split_group"] for row in selected}) <
                    protocol["partition_minimums"]["test"]["min_groups_per_class"]):
                raise ValueError("TEST no alcanza mínimos G0")
        if ({row.get("class_code") for row in test_positive} != set(CLASSES)
                or {row.get("negative_category") for row in test_negative} != {"OTHER_CROP"}
                or len({row["image_id"] for row in test_positive + test_negative}) != seal["test_count"]):
            raise ValueError("Taxonomía o identidades TEST incompatibles")
        records, evidence_root = load_evidence(evidence_path)
        source = _source_inventory()
        torch.set_num_threads(config["cpu_threads"])
        model = build_model(config["architecture"], config["seed"], config["normalization"])
        model.load_state_dict(load_file(str(frozen_dir / "pilot-weights.safetensors"), device="cpu"), strict=True)
        model.eval()
        with torch.inference_mode():
            model(torch.zeros(1, 3, spec.height, spec.width))
        rows, latency = [], []
        for negative, entries in ((False, test_positive), (True, test_negative)):
            for row in entries:
                if row.get("source") != "plantvillage" or row["image_id"] != row["sha256"]:
                    raise ValueError("Fuente TEST incompatible")
                record = records.get(row["image_id"])
                validate_image_evidence(row, record, evidence_root, images_root, source, negative=negative)
                raw = (images_root / record["relative_path"]).read_bytes()
                started = time.perf_counter_ns()
                tensor = image_to_tensor(raw, spec, split="TEST").unsqueeze(0)
                with torch.inference_mode():
                    probs = torch.softmax(model(tensor), dim=1)[0].tolist()
                latency.append((time.perf_counter_ns() - started) / 1_000_000)
                rows.append({"target": OTHER_INDEX if negative else CLASSES.index(row["class_code"]),
                             "probabilities": probs})
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        report = score_frozen_test(rows, calibration, thresholds, protocol, latency, rss)
        report["provenance"] = {"freeze_sha256": expected_freeze_sha256,
                                "freeze_digest": freeze["freeze_digest"],
                                "weights_sha256": freeze["file_sha256"]["pilot-weights.safetensors"],
                                "config_sha256": freeze["file_sha256"]["config.json"],
                                "calibration_sha256": freeze["file_sha256"]["calibration.json"],
                                "thresholds_sha256": freeze["file_sha256"]["thresholds.json"],
                                "protocol_sha256": freeze["file_sha256"]["protocol-g0.json"],
                                "g1_evidence_sha256": freeze["g1_evidence_sha256"],
                                "test_seal_sha256": expected_seal_sha256,
                                "test_manifest_sha256": {"positives": sha256(split_root / "test-positives.csv"),
                                                         "negatives": sha256(split_root / "test-negatives.csv")},
                                "model_code_sha256": freeze["training_code_sha256"],
                                "preprocessing_code_sha256": freeze["preprocessing_code_sha256"],
                                "evaluation_code_sha256": sha256(Path(__file__)),
                                "lock_sha256": freeze["dependency_lock_sha256"]}
        report_path = output_dir / "test-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
        access.write_text(json.dumps({"status": "COMPLETED", "at": datetime.now(timezone.utc).isoformat(),
                                      "freeze_sha256": expected_freeze_sha256,
                                      "seal_sha256": expected_seal_sha256,
                                      "report_sha256": sha256(report_path)}, indent=2) + "\n", encoding="utf-8")
        return {"report_path": str(report_path), "report_sha256": sha256(report_path),
                "g0_numeric_pass": report["g0_numeric_pass"], "g2_approval": None}
    except Exception as exc:
        access.write_text(json.dumps({"status": "FAILED_AFTER_TEST_ACCESS", "at": datetime.now(timezone.utc).isoformat(),
                                      "error_type": type(exc).__name__, "error": str(exc)}, indent=2) + "\n",
                          encoding="utf-8")
        raise
