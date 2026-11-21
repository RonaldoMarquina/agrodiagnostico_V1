"""Measure selected CPU inference on one fixed VAL image in a fresh process."""

import argparse
import csv
import json
import math
from pathlib import Path
import resource
import statistics
import time

import torch
from safetensors.torch import load_file

from agro_ml.data.g1_evidence import load_evidence, validate_image_evidence
from agro_ml.data.tensor_preprocessing import image_to_tensor
from agro_ml.pilot_selection import verify_freeze
from agro_ml.pilot_training import _source_inventory, build_model, read_config, sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--val-positives", type=Path, required=True)
    parser.add_argument("--images-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.val_positives.name != "val-positives.csv" or not 20 <= args.iterations <= 1000:
        raise ValueError("Solo VAL y 20–1000 iteraciones")
    verify_freeze(args.freeze)
    freeze_dir = args.freeze.parent
    config, spec = read_config(freeze_dir / "config.json")
    torch.set_num_threads(config["cpu_threads"])
    model = build_model(config["architecture"], config["seed"], config["normalization"])
    model.load_state_dict(load_file(str(freeze_dir / "pilot-weights.safetensors"), device="cpu"), strict=True)
    model.eval()
    with args.val_positives.open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    if row["split"] != "VAL" or row["class_code"] not in config["class_codes"]:
        raise ValueError("Muestra de medición fuera de VAL")
    records, evidence_root = load_evidence(args.evidence)
    record = records[row["image_id"]]
    validate_image_evidence(row, record, evidence_root, args.images_root,
                            _source_inventory(), negative=False)
    raw = (args.images_root / record["relative_path"]).read_bytes()
    for _ in range(10):
        tensor = image_to_tensor(raw, spec, split="INFERENCE").unsqueeze(0)
        with torch.inference_mode():
            model(tensor)
    measured = []
    for _ in range(args.iterations):
        tick = time.perf_counter_ns()
        tensor = image_to_tensor(raw, spec, split="INFERENCE").unsqueeze(0)
        with torch.inference_mode():
            model(tensor)
        measured.append((time.perf_counter_ns() - tick) / 1_000_000)
    measured.sort()
    report = {"schema_version": 1, "scope": "ONE_VAL_IMAGE_CPU_MEASUREMENT",
              "test_evaluated": False, "freeze_sha256": sha256(args.freeze),
              "sample_sha256": row["sha256"], "architecture": config["architecture"],
              "iterations": args.iterations, "median_ms": round(statistics.median(measured), 3),
              "p95_ms": round(measured[math.ceil(.95 * len(measured)) - 1], 3),
              "max_ms": round(max(measured), 3),
              "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
              "cpu_threads": torch.get_num_threads()}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
