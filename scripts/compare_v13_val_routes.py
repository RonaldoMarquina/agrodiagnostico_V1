"""Compare two visible rejection routes using only frozen candidate VAL scores."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))

from agro_ml.v13_metrics import DISEASES, HEALTHY, OTHER, evaluate, val_gate, visible_decision


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank(report):
    return (report["gate"]["passed"], report["macro_f1"],
            min(report["per_class"][code]["recall"] for code in DISEASES),
            -report["counts"][OTHER]["accepted"], -report["counts"][HEALTHY]["accepted"],
            report["coverage"]["rate"], -report["threshold"])


def decision_latency(rows, selected):
    """Measure VAL decision overhead separately from shared model/preprocessing."""
    values = []
    for _ in range(20):
        for row in rows:
            started = time.perf_counter_ns()
            visible_decision(row["probabilities"], selected["threshold"],
                             selected["route"], selected["healthy_gate"])
            values.append((time.perf_counter_ns() - started) / 1_000_000)
    values.sort()
    return {"scope": "CALIBRATED_VAL_SCORES_DECISION_ONLY_NO_MODEL",
            "sample_count": len(values), "median_ms": statistics.median(values),
            "p95_ms": values[math.ceil(.95 * len(values)) - 1], "max_ms": max(values)}


def compare(experiment, protocol_path, output):
    if output.exists():
        raise FileExistsError(output)
    metadata = json.loads((experiment / "experiment.json").read_text())
    if metadata.get("test_evaluated") is not False or \
            metadata.get("val_predictions_sha256") != sha256(experiment / "val-predictions.jsonl"):
        raise ValueError("VAL score lineage changed")
    protocol = json.loads(protocol_path.read_text())
    if metadata["g0_sha256"] != sha256(protocol_path):
        raise ValueError("G0 lineage changed")
    rows = [json.loads(line) for line in (experiment / "val-predictions.jsonl").read_text().splitlines()]
    if len(rows) != metadata["val_count"] or any(row["split_group"] is None for row in rows):
        raise ValueError("VAL score count incomplete")
    logits = [[math.log(max(value, 1e-12)) for value in row["probabilities"]] for row in rows]
    alternatives = []
    for route, gates in (("ARGMAX_CONFIDENCE", (None,)), ("HEALTHY_GATE", (.25, .4, .55))):
        for gate in gates:
            for step in range(10, 100, 5):
                candidate = evaluate(rows, logits, 1.0, round(step / 100, 2), route, gate)
                candidate.pop("predictions")
                candidate["gate"] = val_gate(candidate, protocol)
                alternatives.append(candidate)
    best = {route: max((row for row in alternatives if row["route"] == route), key=rank)
            for route in ("ARGMAX_CONFIDENCE", "HEALTHY_GATE")}
    for point in best.values():
        point["decision_latency"] = decision_latency(rows, point)
    selected = json.loads((experiment / "val-report.json").read_text())
    if (best[selected["route"]]["threshold"] != selected["threshold"] or
            best[selected["route"]]["healthy_gate"] != selected["healthy_gate"] or
            abs(best[selected["route"]]["macro_f1"] - selected["macro_f1"]) > 1e-9):
        raise ValueError("Selected VAL route does not match independent comparison")
    result = {"scope": "VAL_ONLY_SAME_WEIGHTS_PREPROCESSING_AND_CPU_BUDGET",
              "source_weights_sha256": metadata["weights_sha256"],
              "source_predictions_sha256": metadata["val_predictions_sha256"],
              "selected_temperature": selected["temperature"],
              "best_by_route": best, "selected_route": selected["route"],
              "tested_route_threshold_points": len(alternatives), "test_evaluated": False}
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return {"selected_route": selected["route"],
            "argmax_f1": best["ARGMAX_CONFIDENCE"]["macro_f1"],
            "healthy_gate_f1": best["HEALTHY_GATE"]["macro_f1"],
            "both_routes_pass": all(item["gate"]["passed"] for item in best.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.experiment, args.protocol, args.output), sort_keys=True))
