"""Train a three-target MobileNetV3 on admitted TRAIN and select only with VAL.

This command never reads TEST image bytes, never evaluates TEST, and never
modifies the historical v1.2 bundle or G1 seal. Output is private and not G2.
"""

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))
sys.path.insert(0, str(ROOT))

import torch
from torch.nn import functional as F
from safetensors.torch import save_file, load_file

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.pilot_training import build_model, technical_decision
from agro_ml.pilot_selection import _calibrate
from agro_ml.v13_metrics import DISEASES, TARGETS, OTHER, evaluate, probabilities, val_gate
from scripts.verify_g0_v1_3_2 import validate_protocol, sha256


def rss_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def preflight(config_path, current_path, old_path, g1_root):
    config = json.loads(config_path.read_text())
    if config.get("purpose") != "G0_V1_3_2_TRAIN_VAL_ONLY" or \
            config.get("class_codes") != list(TARGETS) or \
            config.get("publishable_classes") != list(DISEASES) or \
            config.get("val_only_negative") != OTHER or \
            config.get("architecture") != "mobilenet_v3_small" or \
            config.get("normalization") != "GROUP_NORM" or \
            config.get("base_weights") != "RANDOM_INITIALIZATION":
        raise ValueError("Unexpected v1.3.2 training configuration")
    for key in ("seed", "epochs", "batch_size", "cpu_threads"):
        if type(config.get(key)) is not int or config[key] < 1:
            raise ValueError(f"Invalid {key}")
    if config["epochs"] > 20 or config["batch_size"] > 64 or config["cpu_threads"] > 16 or \
            not 0 < config.get("learning_rate", 0) <= .1 or \
            config.get("class_weights") != [1.0, 1.0, 6.0] or \
            config.get("other_crop_outlier_exposure_weight") != 1.0:
        raise ValueError("Training budget or weights changed")
    report_path = g1_root / "g1-report.json"
    report = json.loads(report_path.read_text())
    current = json.loads(current_path.read_text())
    previous = json.loads(old_path.read_text())
    validate_protocol(current, previous, report, sha256(old_path), sha256(report_path))
    if sha256(g1_root / "strata.csv") != report["manifest_sha256"] or \
            sha256(g1_root / "evidence.json") != report["evidence_sha256"] or \
            sha256(g1_root / "test-seal.json") != report["test_seal_sha256"]:
        raise ValueError("G1 manifest, evidence or sealed TEST changed")
    return config, TensorSpec.from_dict(config["preprocessing"]), report


def load_rows(g1_root, report):
    rows = read_csv(g1_root / "strata.csv")  # Metadata only; no TEST image is decoded or scored.
    if len(rows) != report["admitted_photos"]:
        raise ValueError("G1 manifest count changed")
    train = [r for r in rows if r["split"] == "TRAIN"]
    val = [r for r in rows if r["split"] == "VAL"]
    if len(train) != 1623 or len(val) != 496 or \
            {r["stratum_code"] for r in train} != set((*TARGETS, OTHER)) or \
            {r["stratum_code"] for r in val} != set((*TARGETS, OTHER)):
        raise ValueError("TRAIN/VAL composition changed")
    if ({r["sha256"] for r in train} & {r["sha256"] for r in val}) or \
            ({r["split_group"] for r in train} & {r["split_group"] for r in val}):
        raise ValueError("TRAIN and VAL groups overlap")
    return train, val


def load_tensors(rows, g1_root, evidence, spec, seed, split):
    samples = []
    proof = g1_root / "rights.md"
    if sha256(proof) != "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb":
        raise ValueError("Rights declaration changed")
    for row in rows:
        if row["split"] != split or row["source"] != "plantvillage" or \
                row["source_revision"] != "9e97599868962bd0079b8db4b7f1efa9185fa1e7" or \
                row["license"] != "CC-BY-SA-3.0" or row["stratum_code"] not in (*TARGETS, OTHER):
            raise ValueError("Unadmitted source or split")
        record = evidence.get(row["sha256"])
        if record is None or record.get("decision") != "ADMIT" or \
                record.get("source_label") != row["source_label"] or \
                record.get("stratum_code") != row["stratum_code"] or \
                record.get("split_group") != row["split_group"] or \
                record.get("split") != split or \
                record.get("rights", {}).get("decision") != "APPROVED" or \
                record.get("rights", {}).get("proof_path") != "rights.md" or \
                ("TRAINING" if split == "TRAIN" else "EVALUATION") not in record["rights"].get("allowed_uses", []) or \
                record.get("label_review", {}).get("decision") != "APPROVED":
            raise ValueError("Individual rights or label review missing")
        relative = Path(row["relative_path"])
        if relative.parent != Path("images") or not relative.name.startswith(row["sha256"] + "."):
            raise ValueError("Unsafe image path")
        raw = (g1_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Image SHA mismatch")
        tensor = image_to_tensor(raw, spec, split=split, augment=split == "TRAIN",
                                 seed=seed + int(row["sha256"][:8], 16) if split == "TRAIN" else None)
        samples.append({"image_id": row["image_id"], "stratum_code": row["stratum_code"],
                        "split_group": row["split_group"], "tensor": tensor, "raw": raw})
    samples.sort(key=lambda item: item["image_id"])
    return samples


def model_logits(model, samples, batch_size):
    model.eval()
    result = []
    with torch.inference_mode():
        for start in range(0, len(samples), batch_size):
            batch = torch.stack([r["tensor"] for r in samples[start:start + batch_size]])
            result.extend(model(batch).tolist())
    return result


def choose_temperature(rows, logits):
    potato = [(row, values) for row, values in zip(rows, logits) if row["stratum_code"] in TARGETS]
    options = (.5, .67, .8, 1.0, 1.25, 1.5, 2.0, 3.0)
    def nll(temp):
        return sum(-math.log(max(1e-12, probabilities(values, temp)[TARGETS.index(row["stratum_code"]) ]))
                   for row, values in potato) / len(potato)
    return min(options, key=nll)


def best_val_point(rows, logits, protocol):
    temperature = choose_temperature(rows, logits)
    candidates = []
    for route, gates in (("ARGMAX_CONFIDENCE", (None,)), ("HEALTHY_GATE", (.25, .4, .55))):
        for gate in gates:
            for step in range(10, 100, 5):
                threshold = round(step / 100, 2)
                report = evaluate(rows, logits, temperature, threshold, route, gate)
                status = val_gate(report, protocol)
                report["val_gate"] = status
                candidates.append(report)
    def rank(item):
        positives = item["per_class"]
        return (item["val_gate"]["passed"], item["macro_f1"],
                min(value["recall"] for value in positives.values()),
                -item["counts"][OTHER]["accepted"], -item["counts"][TARGETS[2]]["accepted"],
                item["coverage"]["rate"] or 0, -(item["selective_error"]["rate"] or 1),
                -item["threshold"])
    return max(candidates, key=rank), candidates


def compare_historical(rows, samples, bundle_root, batch_size, current_spec):
    from agro_ml.pilot_training import read_config
    config, spec = read_config(bundle_root / "config.json")
    if spec.to_dict() != current_spec.to_dict():
        raise ValueError("Historical comparison requires identical VAL preprocessing")
    model = build_model("mobilenet_v3_small", config["seed"], config["normalization"])
    model.load_state_dict(load_file(str(bundle_root / "pilot-weights.safetensors"), device="cpu"), strict=True)
    model.eval()
    logits = model_logits(model, samples, batch_size)
    calibration = json.loads((bundle_root / "calibration.json").read_text())["class_parameters"]
    threshold = json.loads((bundle_root / "thresholds.json").read_text())["per_class"]
    decisions = []
    for values in logits:
        p = probabilities(values, 1.0)
        candidate = max(range(2), key=lambda i: p[i])
        code = DISEASES[candidate]
        score = _calibrate(p[candidate], calibration[code])
        decisions.append(technical_decision(p, threshold[code], score))
    positive = [i for i, row in enumerate(rows) if row["stratum_code"] in DISEASES]
    accepted = [i for i in positive if decisions[i] is not None]
    correct = [i for i in accepted if DISEASES[decisions[i]] == rows[i]["stratum_code"]]
    return {"scope": "SAME_V1_3_2_VAL_ONLY_HISTORICAL_V1_2_BUNDLE_UNCHANGED",
            "bundle_weights_sha256": sha256(bundle_root / "pilot-weights.safetensors"),
            "bundle_config_sha256": sha256(bundle_root / "config.json"),
            "positive_coverage": {"numerator": len(accepted), "denominator": len(positive)},
            "positive_correct_accepted": {"numerator": len(correct), "denominator": len(accepted)},
            "healthy": {"accepted_blight": sum(decisions[i] is not None for i, row in enumerate(rows)
                                             if row["stratum_code"] == TARGETS[2]),
                        "denominator": sum(row["stratum_code"] == TARGETS[2] for row in rows)},
            "other_crop": {"accepted_blight": sum(decisions[i] is not None for i, row in enumerate(rows)
                                                if row["stratum_code"] == OTHER),
                           "denominator": sum(row["stratum_code"] == OTHER for row in rows)}}


def run(config_path, current_path, old_path, g1_root, old_bundle, output):
    config, spec, g1_report = preflight(config_path, current_path, old_path, g1_root)
    if output.exists():
        raise FileExistsError(output)
    protocol = json.loads(current_path.read_text())
    train_rows, val_rows = load_rows(g1_root, g1_report)
    evidence = {r["sha256"]: r for r in json.loads((g1_root / "evidence.json").read_text())["records"]}
    if len(evidence) != g1_report["admitted_photos"]:
        raise ValueError("Duplicate G1 evidence")
    torch.set_num_threads(config["cpu_threads"])
    torch.manual_seed(config["seed"])
    torch.use_deterministic_algorithms(True)
    train = load_tensors(train_rows, g1_root, evidence, spec, config["seed"], "TRAIN")
    val = load_tensors(val_rows, g1_root, evidence, spec, config["seed"], "VAL")
    output.mkdir(parents=True, exist_ok=False)
    try:
        for name, rows in (("train-manifest.csv", train_rows), ("val-manifest.csv", val_rows)):
            with (output / name).open("x", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        started = time.perf_counter()
        supervised = [r for r in train if r["stratum_code"] in TARGETS]
        outliers = [r for r in train if r["stratum_code"] == OTHER]
        if len(supervised) != 1120 or len(outliers) != 503:
            raise ValueError("Supervised or outlier TRAIN count changed")
        model = build_model(config["architecture"], config["seed"], config["normalization"])
        optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"])
        weights = torch.tensor(config["class_weights"], dtype=torch.float32)
        history, candidates = [], []
        for epoch in range(1, config["epochs"] + 1):
            tick = time.perf_counter()
            model.train()
            order = torch.randperm(len(supervised), generator=torch.Generator().manual_seed(config["seed"] + epoch)).tolist()
            ood_order = torch.randperm(len(outliers), generator=torch.Generator().manual_seed(config["seed"] + 1000 + epoch)).tolist()
            losses = []
            for start in range(0, len(order), config["batch_size"]):
                batch = [supervised[i] for i in order[start:start + config["batch_size"]]]
                other_batch = [outliers[ood_order[(start + offset) % len(ood_order)]]
                               for offset in range(len(batch))]
                x = torch.stack([r["tensor"] for r in batch])
                x_other = torch.stack([r["tensor"] for r in other_batch])
                y = torch.tensor([TARGETS.index(r["stratum_code"]) for r in batch], dtype=torch.long)
                optimizer.zero_grad(set_to_none=True)
                logits_main = model(x)
                logits_other = model(x_other)
                supervised_loss = F.cross_entropy(logits_main, y, weight=weights)
                outlier_loss = -F.log_softmax(logits_other, dim=1).mean(dim=1).mean()
                loss = supervised_loss + config["other_crop_outlier_exposure_weight"] * outlier_loss
                if not bool(torch.isfinite(loss)):
                    raise ValueError("Nonfinite training loss")
                loss.backward()
                optimizer.step()
                losses.append(float(loss.detach()))
            logits = model_logits(model, val, config["batch_size"])
            best, options = best_val_point(val, logits, protocol)
            entry = {"epoch": epoch, "train_loss_mean": sum(losses) / len(losses),
                     "epoch_seconds_including_val": time.perf_counter() - tick,
                     "training_peak_rss_mb": rss_mb(), "val_macro_f1": best["macro_f1"],
                     "val_recall": {k: v["recall"] for k, v in best["per_class"].items()},
                     "val_coverage": best["coverage"], "val_selective_error": best["selective_error"],
                     "val_healthy": best["counts"][TARGETS[2]], "val_other": best["counts"][OTHER],
                     "val_gate_passed": best["val_gate"]["passed"],
                     "val_route": best["route"], "val_threshold": best["threshold"]}
            history.append(entry)
            print(json.dumps(entry, sort_keys=True), flush=True)
            candidates.append((best, {k: v.detach().cpu().clone().contiguous() for k, v in model.state_dict().items()}, logits))
        def rank(candidate):
            report = candidate[0]
            return (report["val_gate"]["passed"], report["macro_f1"],
                    min(x["recall"] for x in report["per_class"].values()),
                    -report["counts"][OTHER]["accepted"], -report["counts"][TARGETS[2]]["accepted"])
        best_index = max(range(len(candidates)), key=lambda index: rank(candidates[index]))
        best, state, logits = candidates[best_index]
        best_epoch = best_index + 1
        save_file(state, str(output / "weights.safetensors"))
        predictions = best.pop("predictions")
        with (output / "val-predictions.jsonl").open("x", encoding="utf-8") as stream:
            for row in predictions:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        historical = compare_historical(val, val, old_bundle, config["batch_size"], spec)
        (output / "val-report.json").write_text(json.dumps(best, indent=2, sort_keys=True) + "\n")
        (output / "historical-v1.2-on-val.json").write_text(json.dumps(historical, indent=2, sort_keys=True) + "\n")
        if shutil.which("git"):
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                      capture_output=True, text=True, check=True).stdout.strip()
        else:
            revision = os.environ.get("AGRO_GIT_HEAD", "")
            if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
                raise ValueError("Container requires verified AGRO_GIT_HEAD")
        metadata = {"status": "VAL_ONLY_CANDIDATE_NOT_G2", "test_evaluated": False,
                    "g0_protocol_version": "1.3.2", "g1_admission_version": "1.3.1",
                    "seed": config["seed"], "best_epoch_by_val": best_epoch,
                    "architecture": config["architecture"], "base_weights": config["base_weights"],
                    "class_codes": config["class_codes"], "publishable_classes": config["publishable_classes"],
                    "train_count": len(train), "supervised_train_count": len(supervised),
                    "outlier_exposure_train_count": len(outliers), "val_count": len(val), "history": history,
                    "training_peak_rss_mb": rss_mb(), "total_training_seconds": time.perf_counter() - started,
                    "cpu": {"model": platform.processor(), "logical_cpus": os.cpu_count(),
                            "threads_used": config["cpu_threads"], "python": sys.version.split()[0],
                            "torch": torch.__version__, "torchvision": __import__("torchvision").__version__,
                            "pillow": __import__("PIL").__version__,
                            "safetensors": __import__("safetensors").__version__},
                    "git_head": revision, "code_sha256": sha256(Path(__file__)),
                    "metrics_code_sha256": sha256(ROOT / "ml/src/agro_ml/v13_metrics.py"),
                    "preprocessing_code_sha256": sha256(ROOT / "ml/src/agro_ml/data/tensor_preprocessing.py"),
                    "dependency_lock_sha256": sha256(ROOT / "ml/uv.lock"),
                    "g0_sha256": sha256(current_path), "g1_report_sha256": sha256(g1_root / "g1-report.json"),
                    "g1_manifest_sha256": sha256(g1_root / "strata.csv"),
                    "g1_test_seal_sha256": sha256(g1_root / "test-seal.json"),
                    "config_sha256": sha256(config_path),
                    "train_manifest_sha256": sha256(output / "train-manifest.csv"),
                    "val_manifest_sha256": sha256(output / "val-manifest.csv"),
                    "weights_sha256": sha256(output / "weights.safetensors"),
                    "val_report_sha256": sha256(output / "val-report.json"),
                    "val_predictions_sha256": sha256(output / "val-predictions.jsonl"),
                    "historical_comparison_sha256": sha256(output / "historical-v1.2-on-val.json"),
                    "command": sys.argv}
        (output / "experiment.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        return {"status": metadata["status"], "output": str(output), "best_epoch": best_epoch,
                "val_macro_f1": best["macro_f1"], "val_gate": best["val_gate"]}
    except Exception:
        (output / "FAILED").write_text("Experiment failed before TEST\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("config", "g0_protocol", "previous_g0_protocol", "private_g1", "historical_v1_2_bundle", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.g0_protocol, args.previous_g0_protocol,
                         args.private_g1, args.historical_v1_2_bundle, args.output), sort_keys=True))
