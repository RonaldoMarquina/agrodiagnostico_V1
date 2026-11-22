"""Evaluate the G1 v1.3.1 sealed TEST once with the exact frozen v1.3.2 bundle.

The preflight reads only the TEST manifest and seal. ``run`` creates a durable
one-attempt marker before reading TEST image bytes. A failed attempt stays spent.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))
sys.path.insert(0, str(ROOT))

import torch
from safetensors.torch import load_file

from agro_ml.data.partitioning import verify_test_partition_seal
from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.pilot_training import build_model
from agro_ml.v13_metrics import DISEASES, OTHER, TARGETS, probabilities, visible_decision
from agro_ml.v13_test_evaluation import EXPECTED_TEST, score_test
from scripts.freeze_v13_candidate import verify as verify_frozen
from scripts.verify_g1_v1_3_1 import verify as verify_g1
from scripts.verify_g0_v1_3_2 import sha256


FROZEN_SHA = "d07dcc40376d4d74e581553c817e4610f7bf7716cae0d6af98a3919930141eb7"
G1_REPORT_SHA = "71c4e34c60eb1b635da58af934b05fd1683728f895e955d8027f7652e91c7a75"
G1_SEAL_SHA = "4f0872f62b58b35df908de8dae3f0577dc425f871e0e74e7fbf26a1afe9489bc"
G0_SHA = "533a8daddba598d810cf6e46cb072a41c54ae5478bfd9ed131b39eb703bfb397"
RIGHTS_SHA = "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb"
SOURCE_REVISION = "9e97599868962bd0079b8db4b7f1efa9185fa1e7"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def preflight(bundle, g1, historical_g1, output):
    if output.exists():
        raise FileExistsError("TEST output already exists")
    ledger = bundle.parent / "test-access-v1.3.2.json"
    if ledger.exists():
        raise FileExistsError("The v1.3.2 TEST attempt has already started")
    if sha256(ROOT / "ml/evaluation/freeze-record.v1.3.2.json") != FROZEN_SHA or \
            sha256(bundle / "freeze.json") != FROZEN_SHA:
        raise ValueError("Frozen root does not match the committed pre-TEST record")
    verify_frozen(bundle, FROZEN_SHA)
    freeze = read_json(bundle / "freeze.json")
    config, protocol = read_json(bundle / "config.json"), read_json(bundle / "protocol-g0.json")
    calibration, thresholds = read_json(bundle / "calibration.json"), read_json(bundle / "thresholds.json")
    mapping = read_json(bundle / "class-map.json")
    report_path, manifest_path = g1 / "g1-report.json", g1 / "strata.csv"
    g1_report = read_json(report_path)
    if (sha256(report_path) != G1_REPORT_SHA or sha256(g1 / "test-seal.json") != G1_SEAL_SHA or
            sha256(ROOT / "ml/evaluation/protocol-g0.v1.3.2.json") != G0_SHA or
            sha256(bundle / "protocol-g0.json") != G0_SHA or
            sha256(manifest_path) != g1_report["manifest_sha256"] or
            sha256(g1 / "evidence.json") != g1_report["evidence_sha256"] or
            sha256(g1 / "rights.md") != RIGHTS_SHA or
            freeze["g1_report_sha256"] != G1_REPORT_SHA or
            freeze["g1_test_seal_sha256"] != G1_SEAL_SHA or
            freeze["status"] != "LOCKED_BEFORE_TEST_NOT_G2" or
            freeze["test_evaluated"] is not False or
            freeze["g2_approval"] is not None or
            protocol["protocol_version"] != "1.3.2" or
            g1_report["test_count"] != 272 or
            config["class_codes"] != list(TARGETS) or
            mapping["technical_class_codes"] != list(TARGETS) or
            mapping["publishable_class_codes"] != list(DISEASES) or
            calibration != {"method": "TEMPERATURE_SCALING_VAL", "temperature": 1.25,
                            "selected_on": "VAL", "ece_technical_potato": calibration.get("ece_technical_potato")} or
            thresholds != {"selected_on": "VAL", "route": "ARGMAX_CONFIDENCE",
                           "min_disease_probability": .9, "healthy_probability_gate": None,
                           "healthy_argmax_action": "NO_CONCLUYENTE",
                           "other_crop_action": "NO_CONCLUYENTE"}):
        raise ValueError("G0/G1 or frozen model policy changed before TEST")
    rows = read_csv(manifest_path)
    test_rows = [row for row in rows if row["split"] == "TEST"]
    seal_rows = [{"image_id": row["image_id"], "sha256": row["sha256"],
                  "class_code": row["stratum_code"], "split_group": row["split_group"],
                  "split": row["split"]} for row in rows]
    if not verify_test_partition_seal(seal_rows, g1 / "test-seal.json") or \
            len(test_rows) != 272 or len({row["image_id"] for row in test_rows}) != 272:
        raise ValueError("TEST manifest no longer matches the G1 seal")
    for code, (photos, groups) in EXPECTED_TEST.items():
        selected = [row for row in test_rows if row["stratum_code"] == code]
        if len(selected) != photos or len({row["split_group"] for row in selected}) != groups:
            raise ValueError("TEST stratum or group count changed")
    return {"bundle": bundle, "g1": g1, "historical_g1": historical_g1,
            "output": output, "ledger": ledger, "freeze": freeze, "config": config,
            "protocol": protocol, "calibration": calibration, "thresholds": thresholds,
            "g1_report": g1_report, "test_rows": test_rows}


def admitted_bytes(row, g1, evidence):
    record = evidence.get(row["sha256"])
    relative = Path(row["relative_path"])
    if (row["split"] != "TEST" or row["stratum_code"] not in (*TARGETS, OTHER) or
            row["source"] != "plantvillage" or row["source_revision"] != SOURCE_REVISION or
            row["license"] != "CC-BY-SA-3.0" or
            relative.parent != Path("images") or not relative.name.startswith(row["sha256"] + ".") or
            record is None or record.get("decision") != "ADMIT" or
            any(record.get(key) != value for key, value in row.items()) or
            record.get("rights", {}).get("decision") != "APPROVED" or
            record["rights"].get("proof_path") != "rights.md" or
            "EVALUATION" not in record["rights"].get("allowed_uses", []) or
            record.get("label_review", {}).get("decision") != "APPROVED"):
        raise ValueError("TEST image lacks admitted rights, label or source")
    raw = (g1 / relative).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError("TEST image changed after admission")
    return raw


def run(plan):
    # This file is the one-shot barrier. It is never removed or reset by this command.
    with plan["ledger"].open("x", encoding="utf-8") as stream:
        json.dump({"status": "STARTED_ONCE", "started_at_utc": datetime.now(timezone.utc).isoformat(),
                   "freeze_sha256": FROZEN_SHA, "seal_sha256": G1_SEAL_SHA,
                   "output": str(plan["output"])}, stream, indent=2, sort_keys=True)
        stream.write("\n")
    plan["output"].mkdir(parents=True, exist_ok=False)
    try:
        # Full G1 verification checks every admitted byte and historical TEST separation.
        verify_g1(plan["g1"], plan["historical_g1"],
                  ROOT / "ml/evaluation/protocol-g0.v1.3.1.json")
        evidence_rows = read_json(plan["g1"] / "evidence.json")["records"]
        evidence = {row["sha256"]: row for row in evidence_rows}
        if len(evidence) != plan["g1_report"]["admitted_photos"]:
            raise ValueError("G1 evidence contains duplicate SHA")
        config = plan["config"]
        torch.set_num_threads(config["cpu_threads"])
        spec = TensorSpec.from_dict(config["preprocessing"])
        model = build_model("mobilenet_v3_small", config["seed"], "GROUP_NORM")
        model.load_state_dict(load_file(str(plan["bundle"] / "weights.safetensors"), device="cpu"),
                              strict=True)
        model.eval()
        with torch.inference_mode():
            model(torch.zeros(1, 3, spec.height, spec.width))
        logits, latencies, rows = [], [], []
        for row in plan["test_rows"]:
            raw = admitted_bytes(row, plan["g1"], evidence)
            started = time.perf_counter_ns()
            tensor = image_to_tensor(raw, spec, split="INFERENCE").unsqueeze(0)
            with torch.inference_mode():
                values = model(tensor)[0].tolist()
            p = probabilities(values, plan["calibration"]["temperature"])
            visible_decision(p, plan["thresholds"]["min_disease_probability"],
                             plan["thresholds"]["route"], plan["thresholds"]["healthy_probability_gate"])
            latency = (time.perf_counter_ns() - started) / 1_000_000
            if len(values) != 3 or any(not math.isfinite(value) for value in values):
                raise ValueError("Nonfinite or incompatible TEST output")
            logits.append(values)
            latencies.append(latency)
            rows.append(row)
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        report, predictions = score_test(rows, logits, latencies, plan["protocol"],
                                         temperature=plan["calibration"]["temperature"],
                                         threshold=plan["thresholds"]["min_disease_probability"],
                                         route=plan["thresholds"]["route"],
                                         healthy_gate=plan["thresholds"]["healthy_probability_gate"],
                                         max_rss_mb=rss_mb)
        report["status"] = "G2_REVIEW_PENDING" if report["g0_numeric_pass"] else "G0_TEST_FAILED_G2_OPEN"
        report["provenance"] = {
            "freeze_sha256": FROZEN_SHA, "weights_sha256": plan["freeze"]["artifact_sha256"]["weights.safetensors"],
            "config_sha256": plan["freeze"]["artifact_sha256"]["config.json"],
            "calibration_sha256": plan["freeze"]["artifact_sha256"]["calibration.json"],
            "thresholds_sha256": plan["freeze"]["artifact_sha256"]["thresholds.json"],
            "class_map_sha256": plan["freeze"]["artifact_sha256"]["class-map.json"],
            "protocol_sha256": G0_SHA, "g1_report_sha256": G1_REPORT_SHA,
            "g1_manifest_sha256": plan["g1_report"]["manifest_sha256"],
            "g1_evidence_sha256": plan["g1_report"]["evidence_sha256"],
            "test_seal_sha256": G1_SEAL_SHA, "evaluation_code_sha256": sha256(Path(__file__)),
            "scoring_code_sha256": sha256(ROOT / "ml/src/agro_ml/v13_test_evaluation.py"),
            "git_head": os.environ.get("AGRO_GIT_HEAD", ""),
            "access_ledger_sha256": sha256(plan["ledger"]),
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        report_path = plan["output"] / "test-report.json"
        prediction_path = plan["output"] / "test-predictions.jsonl"
        write_json(report_path, report)
        with prediction_path.open("x", encoding="utf-8") as stream:
            for row, pred, values, latency in zip(rows, predictions, logits, latencies):
                stream.write(json.dumps({"image_id": row["image_id"], "sha256": row["sha256"],
                                         "stratum_code": row["stratum_code"],
                                         "split_group": row["split_group"], "technical_logits": values,
                                         "published_class": pred["published_class"],
                                         "visible_state": pred["visible_state"],
                                         "calibrated_probabilities": pred["probabilities"],
                                         "latency_ms": latency}, sort_keys=True) + "\n")
        completion = {"status": report["status"], "freeze_sha256": FROZEN_SHA,
                      "report_sha256": sha256(report_path),
                      "predictions_sha256": sha256(prediction_path),
                      "row_count": len(rows), "test_evaluations": 1,
                      "g0_numeric_pass": report["g0_numeric_pass"]}
        write_json(plan["output"] / "test-completion.json", completion)
        return completion
    except Exception as exc:
        write_json(plan["output"] / "test-failure.json",
                   {"status": "TEST_ATTEMPT_FAILED_NO_RETRY", "error_type": type(exc).__name__,
                    "error": str(exc), "freeze_sha256": FROZEN_SHA})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preflight", "run"))
    parser.add_argument("bundle", type=Path)
    parser.add_argument("g1", type=Path)
    parser.add_argument("historical_g1", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepared = preflight(args.bundle, args.g1, args.historical_g1, args.output)
    result = ({"status": "PREFLIGHT_ONLY_NO_TEST_IMAGES", "freeze_sha256": FROZEN_SHA,
               "test_count": len(prepared["test_rows"])} if args.operation == "preflight" else run(prepared))
    print(json.dumps(result, sort_keys=True))
