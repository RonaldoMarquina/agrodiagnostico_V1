#!/usr/bin/env python3
"""Ejecuta HEAD+FINE_TUNE v1.4.2 solo con TRAIN/VAL y checkpoint admitido."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))

from safetensors.torch import load_file, save_file
import torch
from torch.nn import functional as F

from agro_ml.data.tensor_preprocessing import image_to_tensor
from agro_ml.v14_training import healthy_train_tensor
from agro_ml.v141_gates import TECHNICAL_CLASSES, validate_protocol, validate_train_val
from agro_ml.v141_training import HEALTHY, balanced_epoch_indices, choose_val_policy
from agro_ml.v142_checkpoint import validate_checkpoint_file
from agro_ml.v142_transfer import (
    backbone_digest, build_pretrained_model, configure_phase, set_training_mode,
    save_training_resume,
    validate_history_index, validate_plan, validate_private_checkpoint,
    validate_private_roots, validate_training_mounts,
)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def git_commit_exists(repo: Path, commit: str) -> bool:
    if shutil.which("git"):
        result = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                                cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                check=False)
        return result.returncode == 0
    verified = set(os.environ.get("AGRO_VERIFIED_HISTORICAL_COMMITS", "").split(","))
    return commit in verified


def verify_inputs(args: argparse.Namespace) -> tuple[dict, Any, list[dict], dict, dict]:
    if os.environ.get("AGRO_NETWORK_MODE") != "none":
        raise ValueError("el entrenamiento v1.4.2 exige contenedor sin red")
    plan, preprocessing = read_json(args.plan), read_json(args.preprocessing)
    spec = validate_plan(plan, preprocessing)
    protocol, gate, history = read_json(args.protocol), read_json(args.gate_status), read_json(args.history)
    validate_protocol(protocol)
    validate_private_roots(args.private_v142, args.historical_v141_root)
    validate_training_mounts([args.private_v142, args.images_root, args.output, args.base_weight])
    validate_history_index(history, args.repo_root, args.private_g1,
                           commit_exists=lambda commit: git_commit_exists(args.repo_root, commit))
    manifest = args.private_g1 / "plantvillage-train-val.jsonl"
    report = args.private_g1 / "g1-report.json"
    rights = args.private_g1 / "plantvillage-rights.md"
    if gate.get("G1") != "CLOSED_PRIVATE_MANIFEST_VERIFIED" or \
            gate.get("external_access") != "SEALED_NOT_OPENED_FOR_MODELING":
        raise ValueError("G1 o sello externo inválido")
    expected = {
        args.protocol: gate["approved_protocol_sha256"],
        manifest: gate["plantvillage_train_val_manifest_sha256"],
        report: gate["G1_private_report_sha256"],
    }
    for path, digest in expected.items():
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f"evidencia fijada cambió: {path.name}")
    if sha(rights) != "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb":
        raise ValueError("derechos PlantVillage alterados")
    rows = read_jsonl(manifest)
    topology = validate_train_val(rows)
    if any(row["split"] not in {"TRAIN", "VAL"} or row["source_id"] != "plantvillage" for row in rows):
        raise ValueError("TEST/EXTERNAL o fuente no aprobada montada")
    registry, checkpoint = validate_private_checkpoint(args.base_weight)
    state = validate_checkpoint_file(checkpoint)
    return plan, spec, rows, state, {
        "plan_sha256": sha(args.plan), "preprocessing_sha256": sha(args.preprocessing),
        "protocol_sha256": sha(args.protocol), "gate_status_sha256": sha(args.gate_status),
        "history_index_sha256": sha(args.history), "g1_manifest_sha256": sha(manifest),
        "g1_report_sha256": sha(report), "rights_sha256": sha(rights),
        "base_weight_sha256": registry["sha256"], "base_weight_provenance_sha256": sha(args.base_weight / "provenance.json"),
        "topology": topology,
    }


def resolve_image(root: Path, digest: str) -> Path:
    matches = sorted(root.glob(f"{digest}.*"))
    if len(matches) != 1 or sha(matches[0]) != digest:
        raise ValueError(f"imagen no resoluble o alterada: {digest}")
    return matches[0]


def load_samples(rows: list[dict], images_root: Path, spec: Any) -> tuple[list[dict], list[dict]]:
    train, val = [], []
    for row in sorted(rows, key=lambda value: value["image_id"]):
        raw = resolve_image(images_root, row["sha256"]).read_bytes()
        sample = {key: row[key] for key in ("image_id", "sha256", "stratum_code", "split_group")}
        if row["split"] == "TRAIN":
            if row["stratum_code"] == HEALTHY:
                sample["raw"] = raw
            else:
                sample["tensor"] = image_to_tensor(raw, spec, split="TRAIN")
            train.append(sample)
        else:
            sample["tensor"] = image_to_tensor(raw, spec, split="VAL")
            val.append(sample)
    if len(train) != 1623 or len(val) != 496:
        raise ValueError("conteos TRAIN/VAL cambiaron")
    return train, val


def training_tensor(sample: dict, spec: Any, plan: dict, seed: int) -> torch.Tensor:
    if sample["stratum_code"] != HEALTHY:
        return sample["tensor"]
    return healthy_train_tensor(sample["raw"], spec, seed=seed,
                                augmentation=plan["healthy_train_only_augmentation"])[0]


def model_logits(model: torch.nn.Module, samples: list[dict], batch_size: int) -> list[list[float]]:
    values = []
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(samples), batch_size):
            values.extend(model(torch.stack([row["tensor"] for row in samples[start:start + batch_size]])).tolist())
    return values


def policy_rank(report: dict) -> tuple:
    error = report["selective_error"]["rate"]
    return (report["val_selection"]["passed"], sum(report["val_selection"]["conditions"].values()),
            -report["counts"]["POTATO_HEALTHY"]["accepted"],
            -report["counts"]["OTHER_CROP"]["accepted"],
            min(value["recall"] for value in report["per_class"].values()), report["macro_f1"],
            -(error if error is not None else 1.0), report["coverage"]["rate"],
            -report["ece_four_class"], -report["threshold"])


def latency(model: torch.nn.Module, val: list[dict], iterations: int = 100) -> dict:
    tensors = [val[index % len(val)]["tensor"].unsqueeze(0) for index in range(iterations)]
    times = []
    model.eval()
    with torch.inference_mode():
        model(tensors[0])
        for tensor in tensors:
            started = time.perf_counter_ns(); model(tensor)
            times.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(times)
    return {"iterations": iterations, "batch_size": 1,
            "median_ms": round(statistics.median(ordered), 4),
            "p95_ms": round(ordered[math.ceil(.95 * iterations) - 1], 4),
            "max_ms": round(max(ordered), 4)}


def run(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise FileExistsError(f"salida ya existe: {args.output}")
    plan, spec, rows, pretrained_state, hashes = verify_inputs(args)
    if args.preflight_only:
        print(json.dumps({"status": "PREFLIGHT_PASSED_NOT_TRAINED",
                          "train": hashes["topology"]["totals"]["TRAIN"],
                          "val": hashes["topology"]["totals"]["VAL"],
                          "base_weight_sha256": hashes["base_weight_sha256"],
                          "external_accessed": False,
                          "historical_test_accessed": False}, sort_keys=True))
        return
    git_head = os.environ.get("AGRO_GIT_HEAD", "")
    if len(git_head) != 40 or any(value not in "0123456789abcdef" for value in git_head):
        raise ValueError("AGRO_GIT_HEAD verificado es obligatorio")
    torch.set_num_threads(plan["cpu_threads"])
    torch.manual_seed(plan["seed"])
    torch.use_deterministic_algorithms(True)
    train, val = load_samples(rows, args.images_root, spec)
    args.output.mkdir(parents=True)
    for filename, split in (("train-manifest.jsonl", "TRAIN"), ("val-manifest.jsonl", "VAL")):
        (args.output / filename).write_text("".join(json.dumps(row, sort_keys=True) + "\n"
                                                     for row in rows if row["split"] == split))
    model = build_pretrained_model(pretrained_state, seed=plan["seed"])
    initial_backbone = backbone_digest(model)
    history: list[dict] = []
    best_state = best_report = best_logits = None
    best_epoch = option_count = None
    started = time.perf_counter()
    global_epoch = 0
    minimums = plan["selection"]["minimums"]
    phase_backbones: dict[str, str] = {"before_head": initial_backbone}
    for phase_plan in plan["phases"]:
        phase = phase_plan["id"]
        optimizer = torch.optim.AdamW(configure_phase(model, phase))
        for phase_epoch in range(1, phase_plan["epochs"] + 1):
            global_epoch += 1
            tick = time.perf_counter()
            indices, exposure = balanced_epoch_indices(train, seed=plan["seed"] + global_epoch)
            exposure[HEALTHY]["augmented_views"] = 80
            for code in TECHNICAL_CLASSES:
                if code != HEALTHY:
                    exposure[code]["augmented_views"] = 0
            losses = []
            set_training_mode(model)
            for batch_number, start in enumerate(range(0, len(indices), plan["batch_size"])):
                batch = [train[index] for index in indices[start:start + plan["batch_size"]]]
                batch_seed = plan["seed"] * 1_000_000 + global_epoch * 10_000 + batch_number * 100
                torch.manual_seed(batch_seed)
                x = torch.stack([training_tensor(sample, spec, plan, batch_seed + offset)
                                 for offset, sample in enumerate(batch)])
                y = torch.tensor([TECHNICAL_CLASSES.index(sample["stratum_code"]) for sample in batch])
                optimizer.zero_grad(set_to_none=True)
                loss = F.cross_entropy(model(x), y)
                if not bool(torch.isfinite(loss)):
                    raise ValueError("pérdida no finita")
                loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
            if phase == "HEAD" and backbone_digest(model) != initial_backbone:
                raise ValueError("HEAD modificó el backbone congelado")
            logits = model_logits(model, val, plan["batch_size"])
            report, option_count = choose_val_policy(val, logits, minimums)
            entry = {"epoch": global_epoch, "phase": phase, "phase_epoch": phase_epoch,
                     "train_loss_mean": sum(losses) / len(losses), "train_loss_min": min(losses),
                     "train_loss_max": max(losses),
                     "epoch_seconds_including_val": time.perf_counter() - tick,
                     "peak_rss_mb": rss_mb(), "exposure": exposure,
                     "val": {"macro_f1": report["macro_f1"],
                         "recall": {code: value["recall"] for code, value in report["per_class"].items()},
                         "coverage": report["coverage"], "selective_error": report["selective_error"],
                         "healthy": report["counts"]["POTATO_HEALTHY"],
                         "other_crop": report["counts"]["OTHER_CROP"], "ece": report["ece_four_class"],
                         "threshold": report["threshold"], "temperature": report["temperature"],
                         "selection_passed": report["val_selection"]["passed"]}}
            history.append(entry)
            print(json.dumps(entry, sort_keys=True), flush=True)
            save_training_resume(args.output, model, optimizer, epoch=global_epoch,
                                 phase=phase, history=history)
            if best_report is None or policy_rank(report) > policy_rank(best_report):
                best_report, best_logits, best_epoch = copy.deepcopy(report), copy.deepcopy(logits), global_epoch
                best_state = {key: value.detach().cpu().clone().contiguous()
                              for key, value in model.state_dict().items()}
        phase_backbones[f"after_{phase.lower()}"] = backbone_digest(model)
    assert best_state is not None and best_report is not None and best_logits is not None
    model.load_state_dict(best_state)
    predictions = best_report.pop("predictions")
    best_report.update({"selected_epoch": best_epoch,
                        "selected_phase": history[best_epoch - 1]["phase"],
                        "policy_options_evaluated_per_epoch": option_count,
                        "cpu_latency": latency(model, val), "peak_rss_mb": rss_mb()})
    save_file(best_state, str(args.output / "weights.safetensors"))
    (args.output / "val-report.json").write_text(json.dumps(best_report, indent=2, sort_keys=True) + "\n")
    (args.output / "val-predictions.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n"
                                                                 for row in predictions))
    config = {key: plan[key] for key in ("cycle_version", "g0_protocol_version", "architecture",
              "base_weights", "seed", "cpu_threads", "batch_size", "technical_class_codes",
              "publishable_classes", "preprocessing_contract", "sampler",
              "healthy_train_only_augmentation", "phases", "selection")}
    (args.output / "candidate-config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    historical = read_json(args.repo_root / "ml/evaluation/train-val-result.v1.4.1.json")
    comparison = {"source": "TRACKED_AGGREGATE_RESULT_ONLY",
                  "source_sha256": sha(args.repo_root / "ml/evaluation/train-val-result.v1.4.1.json"),
                  "historical_weights_loaded": False, "historical_predictions_loaded": False,
                  "v1_4_1_status": historical.get("decision"),
                  "v1_4_1_selected_val": historical.get("candidate")}
    experiment = {"status": "VAL_ONLY_CANDIDATE_NOT_EXTERNAL_EVALUATED_NOT_G2",
        "cycle_version": "1.4.2", "g0_protocol_version": "1.4.1",
        "protected_external_partition_accessed": False, "historical_test_accessed": False,
        "historical_weights_or_predictions_reused": False, "network_mode": "none",
        "seed": plan["seed"], "best_epoch_selected_on_val": best_epoch,
        "train_original_count": len(train), "val_original_count": len(val), "git_head": git_head,
        "hashes": hashes, "phase_backbone_sha256": phase_backbones,
        "runtime": {"cpu_model": cpu_model(), "threads_used": plan["cpu_threads"],
            "peak_rss_mb": rss_mb(), "total_seconds": time.perf_counter() - started,
            "python": platform.python_version(), "torch": torch.__version__,
            "torchvision": __import__("torchvision").__version__, "pillow": __import__("PIL").__version__,
            "safetensors": __import__("safetensors").__version__},
        "history": history, "historical_comparison": comparison,
        "command_contract": "python scripts/train_v142_candidate.py --plan ... --preprocessing ... --protocol ... --gate-status ... --history ... --private-g1 ... --private-v142 ... --historical-v141-root ... --base-weight ... --images-root ... --repo-root ... --output ..."}
    for name in ("train-manifest.jsonl", "val-manifest.jsonl", "weights.safetensors",
                 "candidate-config.json", "val-report.json", "val-predictions.jsonl"):
        experiment["hashes"][name.replace(".", "_") + "_sha256"] = sha(args.output / name)
    (args.output / "experiment.json").write_text(json.dumps(experiment, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": experiment["status"], "best_epoch": best_epoch,
                      "val_selection_passed": best_report["val_selection"]["passed"],
                      "weights_sha256": sha(args.output / "weights.safetensors")}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "preprocessing", "protocol", "gate-status", "history", "private-g1",
                 "private-v142", "historical-v141-root", "base-weight", "images-root", "repo-root", "output"):
        parser.add_argument(f"--{name}", dest=name.replace("-", "_"), type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    run(parser.parse_args())
