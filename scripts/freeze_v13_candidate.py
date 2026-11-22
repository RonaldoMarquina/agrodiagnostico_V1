"""Freeze a VAL-passing v1.3.2 CPU candidate without opening or scoring TEST."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))
sys.path.insert(0, str(ROOT))

import torch
from safetensors.torch import load_file

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.pilot_training import build_model
from agro_ml.v13_metrics import DISEASES, TARGETS, val_gate, visible_decision, probabilities
from scripts.verify_g0_v1_3_2 import sha256


def bytes_json(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def measure(model, config, val_manifest, g1_root, protocol):
    spec = TensorSpec.from_dict(config["preprocessing"])
    with val_manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    selected = []
    for code in (*TARGETS, "OTHER_CROP"):
        selected.extend([row for row in rows if row["stratum_code"] == code][:25])
    if len(selected) != 100:
        raise ValueError("VAL latency sample incomplete")
    torch.set_num_threads(config["cpu_threads"])
    model.eval()
    latencies = []
    with torch.inference_mode():
        for row in selected:
            image_path = g1_root / row["relative_path"]
            raw = image_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError("VAL latency sample changed")
            started = time.perf_counter_ns()
            tensor = image_to_tensor(raw, spec, split="INFERENCE").unsqueeze(0)
            logits = model(tensor)[0].tolist()
            if len(logits) != 3 or any(not math.isfinite(x) for x in logits):
                raise ValueError("Independent model load failed")
            latencies.append((time.perf_counter_ns() - started) / 1_000_000)
    values = sorted(latencies)
    result = {"scope": "100_VAL_IMAGES_CPU_PREPROCESS_PLUS_MODEL_NOT_FULL_DIAGNOSIS",
              "sample_count": len(values), "median_ms": statistics.median(values),
              "p95_ms": values[math.ceil(.95 * len(values)) - 1],
              "max_ms": max(values),
              "max_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
              "torch_threads": torch.get_num_threads(), "test_evaluated": False}
    budget = protocol["compute_budget_cpu"]
    result["budget_passed"] = (result["median_ms"] <= budget["latency_median_ms_max"] and
                               result["p95_ms"] <= budget["latency_p95_ms_max"] and
                               result["max_ms"] <= budget["latency_hard_limit_ms"] and
                               result["max_rss_mb"] <= budget["max_rss_mb"])
    return result


def freeze(experiment_dir, config_path, protocol_path, g1_root, output_dir):
    if output_dir.exists():
        raise FileExistsError(output_dir)
    meta_path = experiment_dir / "experiment.json"
    metadata = json.loads(meta_path.read_text())
    protocol = json.loads(protocol_path.read_text())
    val_path = experiment_dir / "val-report.json"
    report = json.loads(val_path.read_text())
    config = json.loads(config_path.read_text())
    expected = {"config_sha256": config_path, "g0_sha256": protocol_path,
                "g1_report_sha256": g1_root / "g1-report.json",
                "g1_manifest_sha256": g1_root / "strata.csv",
                "g1_test_seal_sha256": g1_root / "test-seal.json",
                "train_manifest_sha256": experiment_dir / "train-manifest.csv",
                "val_manifest_sha256": experiment_dir / "val-manifest.csv",
                "weights_sha256": experiment_dir / "weights.safetensors",
                "val_report_sha256": val_path,
                "val_predictions_sha256": experiment_dir / "val-predictions.jsonl",
                "historical_comparison_sha256": experiment_dir / "historical-v1.2-on-val.json",
                "code_sha256": ROOT / "scripts/train_v13_candidate.py",
                "metrics_code_sha256": ROOT / "ml/src/agro_ml/v13_metrics.py",
                "preprocessing_code_sha256": ROOT / "ml/src/agro_ml/data/tensor_preprocessing.py",
                "dependency_lock_sha256": ROOT / "ml/uv.lock"}
    if metadata.get("status") != "VAL_ONLY_CANDIDATE_NOT_G2" or metadata.get("test_evaluated") is not False or \
            metadata.get("g0_protocol_version") != "1.3.2" or \
            metadata.get("class_codes") != list(TARGETS) or \
            metadata.get("publishable_classes") != list(DISEASES) or \
            protocol.get("protocol_version") != "1.3.2" or \
            any(metadata.get(key) != sha256(path) for key, path in expected.items()):
        raise ValueError("Experiment, code, G0, G1 or VAL changed")
    checked = val_gate(report, protocol)
    if checked != report.get("val_gate") or not checked["passed"] or \
            report.get("split") != "VAL" or \
            metadata.get("best_epoch_by_val") not in range(1, config["epochs"] + 1):
        raise ValueError("VAL gates do not authorize freeze")
    model = build_model("mobilenet_v3_small", config["seed"], "GROUP_NORM")
    model.load_state_dict(load_file(str(experiment_dir / "weights.safetensors"), device="cpu"), strict=True)
    cpu = measure(model, config, experiment_dir / "val-manifest.csv", g1_root, protocol)
    if not cpu["budget_passed"]:
        raise ValueError("Independent CPU budget failed; no freeze")
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        for source, target in ((experiment_dir / "weights.safetensors", "weights.safetensors"),
                               (config_path, "config.json"), (protocol_path, "protocol-g0.json"),
                               (val_path, "val-report.json"),
                               (experiment_dir / "historical-v1.2-on-val.json", "historical-v1.2-on-val.json")):
            shutil.copyfile(source, output_dir / target)
        calibration = {"method": "TEMPERATURE_SCALING_VAL", "temperature": report["temperature"],
                       "selected_on": "VAL", "ece_technical_potato": report["ece_technical_potato"]}
        thresholds = {"selected_on": "VAL", "route": report["route"],
                      "min_disease_probability": report["threshold"],
                      "healthy_probability_gate": report["healthy_gate"],
                      "healthy_argmax_action": "NO_CONCLUYENTE", "other_crop_action": "NO_CONCLUYENTE"}
        class_map = {"technical_class_codes": list(TARGETS), "publishable_class_codes": list(DISEASES),
                     "rejection_targets": ["POTATO_HEALTHY", "OTHER_CROP"],
                     "no_concluyente_is_model_class": False}
        (output_dir / "calibration.json").write_bytes(bytes_json(calibration))
        (output_dir / "thresholds.json").write_bytes(bytes_json(thresholds))
        (output_dir / "class-map.json").write_bytes(bytes_json(class_map))
        (output_dir / "cpu-val-inference.json").write_bytes(bytes_json(cpu))
        files = {name: sha256(output_dir / name) for name in
                 ("weights.safetensors", "config.json", "protocol-g0.json", "val-report.json",
                  "historical-v1.2-on-val.json", "calibration.json", "thresholds.json",
                  "class-map.json", "cpu-val-inference.json")}
        freeze_data = {"schema_version": 1, "status": "LOCKED_BEFORE_TEST_NOT_G2",
                       "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
                       "g0_protocol_version": "1.3.2", "g1_admission_version": "1.3.1",
                       "test_evaluated": False, "g2_approval": None,
                       "source_experiment_sha256": sha256(meta_path),
                       "train_manifest_sha256": metadata["train_manifest_sha256"],
                       "val_manifest_sha256": metadata["val_manifest_sha256"],
                       "g1_report_sha256": metadata["g1_report_sha256"],
                       "g1_test_seal_sha256": metadata["g1_test_seal_sha256"],
                       "dependency_lock_sha256": metadata["dependency_lock_sha256"],
                       "training_code_sha256": metadata["code_sha256"],
                       "preprocessing_code_sha256": metadata["preprocessing_code_sha256"],
                       "artifact_sha256": files}
        (output_dir / "freeze.json").write_bytes(bytes_json(freeze_data))
        verify(output_dir)
        return {"status": freeze_data["status"], "freeze_sha256": sha256(output_dir / "freeze.json"),
                "weights_sha256": files["weights.safetensors"], "cpu": cpu,
                "val_macro_f1": report["macro_f1"], "threshold": report["threshold"]}
    except Exception:
        (output_dir / "FAILED").write_text("Freeze failed before TEST\n")
        raise


def verify(directory, expected_sha256=None):
    frozen_sha256 = sha256(directory / "freeze.json")
    if expected_sha256 is not None and frozen_sha256 != expected_sha256:
        raise ValueError("Frozen root SHA-256 does not match the recorded candidate")
    freeze_data = json.loads((directory / "freeze.json").read_text())
    if freeze_data.get("status") != "LOCKED_BEFORE_TEST_NOT_G2" or \
            freeze_data.get("test_evaluated") is not False or freeze_data.get("g2_approval") is not None or \
            any(sha256(directory / name) != digest for name, digest in freeze_data["artifact_sha256"].items()):
        raise ValueError("Frozen candidate altered or falsely approved")
    mapping = json.loads((directory / "class-map.json").read_text())
    if mapping["technical_class_codes"] != list(TARGETS) or \
            mapping["publishable_class_codes"] != list(DISEASES) or \
            mapping["no_concluyente_is_model_class"] is not False:
        raise ValueError("Frozen class map may publish a rejection target")
    config = json.loads((directory / "config.json").read_text())
    thresholds = json.loads((directory / "thresholds.json").read_text())
    calibration = json.loads((directory / "calibration.json").read_text())
    model = build_model("mobilenet_v3_small", config["seed"], "GROUP_NORM")
    model.load_state_dict(load_file(str(directory / "weights.safetensors"), device="cpu"), strict=True)
    model.eval()
    with torch.inference_mode():
        logits = model(torch.zeros(1, 3, 224, 224))[0].tolist()
    p = probabilities(logits, calibration["temperature"])
    decision = visible_decision(p, thresholds["min_disease_probability"], thresholds["route"],
                                thresholds["healthy_probability_gate"])
    if decision is not None and DISEASES[decision] not in mapping["publishable_class_codes"]:
        raise ValueError("Frozen model published technical rejection target")
    if visible_decision([0.01, 0.01, 0.98], 0, thresholds["route"],
                        thresholds["healthy_probability_gate"]) is not None:
        raise ValueError("POTATO_HEALTHY technical prediction was published")
    return {"status": "INDEPENDENT_LOAD_VERIFIED_NO_TEST", "freeze_sha256": frozen_sha256}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    create = sub.add_parser("create")
    for arg in ("experiment_dir", "config", "protocol", "private_g1", "output_dir"):
        create.add_argument(arg, type=Path)
    check = sub.add_parser("verify")
    check.add_argument("directory", type=Path)
    check.add_argument("--expected-sha256")
    args = parser.parse_args()
    result = freeze(args.experiment_dir, args.config, args.protocol, args.private_g1, args.output_dir) \
        if args.operation == "create" else verify(args.directory, args.expected_sha256)
    print(json.dumps(result, sort_keys=True))
