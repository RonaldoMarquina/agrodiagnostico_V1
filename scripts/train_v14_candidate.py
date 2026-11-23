"""Ejecuta un candidato v1.4.0 exclusivamente con PlantVillage TRAIN/VAL.

El proceso no conoce rutas del conjunto sellado. Debe ejecutarse en un
contenedor sin red y sin montar datos protegidos de evaluación externa.
"""

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
import statistics
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))
sys.path.insert(0, str(ROOT))

from safetensors.torch import save_file
import torch
from torch.nn import functional as F

from agro_ml.data.tensor_preprocessing import image_to_tensor
from agro_ml.pilot_training import build_model
from agro_ml.v13_metrics import HEALTHY, TARGETS
from agro_ml.v14_gates import validate_plantvillage_train_val
from agro_ml.v14_training import (
    choose_val_policy,
    group_balanced_epoch_indices,
    healthy_train_tensor,
    selection_rank,
    strategy_config,
    validate_plan,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Se esperaba objeto JSON: {path.name}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL inválido en línea {line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Fila no es objeto en línea {line_number}")
            rows.append(value)
    return rows


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def verify_inputs(plan_path: Path, protocol_path: Path, gate_path: Path,
                  private_root: Path) -> tuple[dict[str, Any], Any, list[dict[str, Any]], dict[str, Any]]:
    plan = read_json(plan_path)
    spec = validate_plan(plan)
    protocol = read_json(protocol_path)
    gate = read_json(gate_path)
    manifest_path = private_root / "plantvillage-train-val.jsonl"
    rights_path = private_root / "plantvillage-rights.md"
    report_path = private_root / "g1-report.json"
    if protocol.get("protocol_version") != "1.4.0" or \
            protocol.get("status") != "APPROVED_G0_DESIGN" or \
            protocol.get("gates", {}).get("G0") != "CLOSED_APPROVED":
        raise ValueError("G0 v1.4.0 no está aprobado")
    if gate.get("G0") != "CLOSED_APPROVED_BY_PROJECT_OWNER" or \
            gate.get("G1") != "CLOSED_PRIVATE_MANIFESTS_VERIFIED_EXTERNAL_SEALED" or \
            gate.get("external_access") != "SEALED_NOT_OPENED_FOR_MODELING":
        raise ValueError("Compuerta previa o sello protegido no válido")
    expected = {
        protocol_path: gate.get("approved_protocol_sha256"),
        manifest_path: gate.get("plantvillage_train_val_manifest_sha256"),
        report_path: gate.get("G1_private_report_sha256"),
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"Evidencia fijada cambió: {path.name}")
    if sha256(rights_path) != "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb":
        raise ValueError("Comprobante de derechos PlantVillage cambió")
    rows = read_jsonl(manifest_path)
    validate_plantvillage_train_val(rows)
    if any("sikkim" in json.dumps(row, sort_keys=True).lower() for row in rows):
        raise ValueError("El manifiesto TRAIN/VAL contiene una fuente protegida")
    return plan, spec, rows, {
        "protocol_sha256": sha256(protocol_path),
        "plan_sha256": sha256(plan_path),
        "manifest_sha256": sha256(manifest_path),
        "rights_sha256": sha256(rights_path),
    }


def resolve_image(images_root: Path, digest: str) -> Path:
    matches = sorted(images_root.glob(f"{digest}.*"))
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"Byte exacto no resoluble: {digest}")
    if sha256(matches[0]) != digest:
        raise ValueError(f"SHA-256 de imagen cambió: {digest}")
    return matches[0]


def load_samples(rows: list[dict[str, Any]], images_root: Path, spec: Any) -> tuple[list[dict], list[dict]]:
    train, val = [], []
    for row in sorted(rows, key=lambda item: item["image_id"]):
        raw = resolve_image(images_root, row["sha256"]).read_bytes()
        sample = {
            "image_id": row["image_id"],
            "sha256": row["sha256"],
            "stratum_code": row["stratum_code"],
            "split_group": row["split_group"],
        }
        if row["split"] == "TRAIN":
            if row["stratum_code"] not in TARGETS:
                raise ValueError("TRAIN contiene un estrato no supervisado")
            if row["stratum_code"] == HEALTHY:
                sample["raw"] = raw
            else:
                sample["tensor"] = image_to_tensor(raw, spec, split="TRAIN")
            train.append(sample)
        elif row["split"] == "VAL":
            sample["tensor"] = image_to_tensor(raw, spec, split="VAL")
            val.append(sample)
        else:
            raise ValueError("Partición distinta de TRAIN/VAL")
    if len(train) != 1120 or len(val) != 496:
        raise ValueError("Conteos TRAIN/VAL cambiaron")
    return train, val


def model_logits(model: torch.nn.Module, samples: list[dict], batch_size: int) -> list[list[float]]:
    model.eval()
    result: list[list[float]] = []
    with torch.inference_mode():
        for start in range(0, len(samples), batch_size):
            batch = torch.stack([row["tensor"] for row in samples[start:start + batch_size]])
            result.extend(model(batch).tolist())
    return result


def epoch_indices(train: list[dict], strategy: dict[str, Any], seed: int) -> tuple[list[int], dict[str, Any]]:
    if strategy["strategy_id"] == "weighted-cross-entropy-full-train":
        generator = torch.Generator().manual_seed(seed)
        indices = torch.randperm(len(train), generator=generator).tolist()
        exposure = {}
        for code in TARGETS:
            class_indices = [index for index in indices if train[index]["stratum_code"] == code]
            exposure[code] = {
                "draws": len(class_indices),
                "unique_original_images": len({train[index]["sha256"] for index in class_indices}),
                "unique_leaf_groups": len({train[index]["split_group"] for index in class_indices}),
                "augmented_views": len(class_indices) if code == HEALTHY else 0,
            }
        return indices, exposure
    indices, exposure = group_balanced_epoch_indices(
        train,
        samples_per_class=strategy["samples_per_class_per_epoch"],
        seed=seed,
    )
    for code in TARGETS:
        exposure[code]["augmented_views"] = exposure[code]["draws"] if code == HEALTHY else 0
    return indices, exposure


def train_tensor(sample: dict, spec: Any, plan: dict[str, Any], seed: int) -> torch.Tensor:
    if sample["stratum_code"] != HEALTHY:
        return sample["tensor"]
    tensor, _ = healthy_train_tensor(
        sample["raw"], spec, seed=seed,
        augmentation=plan["healthy_train_only_augmentation"],
    )
    return tensor


def measure_latency(model: torch.nn.Module, val: list[dict], iterations: int = 100) -> dict[str, Any]:
    model.eval()
    selected = [val[index % len(val)]["tensor"].unsqueeze(0) for index in range(iterations)]
    values = []
    with torch.inference_mode():
        model(selected[0])
        for tensor in selected:
            started = time.perf_counter_ns()
            model(tensor)
            values.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(values)
    return {
        "iterations": iterations,
        "batch_size": 1,
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[math.ceil(.95 * iterations) - 1], 4),
        "max_ms": round(max(ordered), 4),
    }


def run(plan_path: Path, protocol_path: Path, gate_path: Path, private_root: Path,
        images_root: Path, output: Path, strategy_id: str) -> None:
    if output.exists():
        raise FileExistsError(f"La salida ya existe: {output}")
    plan, spec, rows, hashes = verify_inputs(plan_path, protocol_path, gate_path, private_root)
    strategy = strategy_config(plan, strategy_id)
    torch.set_num_threads(plan["cpu_threads"])
    torch.manual_seed(plan["seed"])
    torch.use_deterministic_algorithms(True)
    train, val = load_samples(rows, images_root, spec)
    output.mkdir(parents=True, exist_ok=False)
    train_rows = [row for row in rows if row["split"] == "TRAIN"]
    val_rows = [row for row in rows if row["split"] == "VAL"]
    for filename, selected in (("train-manifest.jsonl", train_rows), ("val-manifest.jsonl", val_rows)):
        with (output / filename).open("x", encoding="utf-8") as stream:
            for row in selected:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    started = time.perf_counter()
    model = build_model(plan["architecture"], plan["seed"], plan["normalization"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=plan["learning_rate"])
    class_weights = None
    if strategy_id == "weighted-cross-entropy-full-train":
        class_weights = torch.tensor(
            [strategy["class_weights_n_over_k_nclass"][code] for code in TARGETS],
            dtype=torch.float32,
        )
    best_state = None
    best_report = None
    best_logits = None
    best_epoch = None
    history = []
    for epoch in range(1, plan["epochs"] + 1):
        tick = time.perf_counter()
        indices, exposure = epoch_indices(train, strategy, plan["seed"] + epoch)
        model.train()
        losses = []
        for batch_number, start in enumerate(range(0, len(indices), strategy["batch_size"])):
            batch_indices = indices[start:start + strategy["batch_size"]]
            batch = [train[index] for index in batch_indices]
            tensors = [
                train_tensor(
                    sample, spec, plan,
                    plan["seed"] * 1_000_000 + epoch * 10_000 + batch_number * 100 + offset,
                )
                for offset, sample in enumerate(batch)
            ]
            x = torch.stack(tensors)
            y = torch.tensor([TARGETS.index(sample["stratum_code"]) for sample in batch], dtype=torch.long)
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(x), y, weight=class_weights)
            if not bool(torch.isfinite(loss)):
                raise ValueError("Pérdida no finita")
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        logits = model_logits(model, val, strategy["batch_size"])
        report, option_count = choose_val_policy(val, logits, plan["selection"])
        entry = {
            "epoch": epoch,
            "train_loss_mean": sum(losses) / len(losses),
            "train_loss_min": min(losses),
            "train_loss_max": max(losses),
            "epoch_seconds_including_val": time.perf_counter() - tick,
            "peak_rss_mb": rss_mb(),
            "exposure": exposure,
            "val": {
                "macro_f1": report["macro_f1"],
                "recall": {code: value["recall"] for code, value in report["per_class"].items()},
                "coverage": report["coverage"],
                "selective_error": report["selective_error"],
                "healthy": report["counts"][HEALTHY],
                "other_crop": report["counts"]["OTHER_CROP"],
                "ece": report["ece_technical_potato"],
                "route": report["route"],
                "threshold": report["threshold"],
                "temperature": report["temperature"],
                "selection_passed": report["val_selection"]["passed"],
            },
        }
        history.append(entry)
        print(json.dumps({"strategy": strategy_id, **entry}, sort_keys=True), flush=True)
        if best_report is None or selection_rank(report) > selection_rank(best_report):
            best_report = copy.deepcopy(report)
            best_logits = copy.deepcopy(logits)
            best_state = {key: value.detach().cpu().clone().contiguous()
                          for key, value in model.state_dict().items()}
            best_epoch = epoch
            best_option_count = option_count
    assert best_state is not None and best_report is not None and best_logits is not None
    model.load_state_dict(best_state, strict=True)
    latency = measure_latency(model, val)
    predictions = best_report.pop("predictions")
    best_report["cpu_latency"] = latency
    best_report["peak_rss_mb"] = rss_mb()
    best_report["selected_epoch"] = best_epoch
    best_report["policy_options_evaluated_per_epoch"] = best_option_count
    save_file(best_state, str(output / "weights.safetensors"))
    with (output / "val-predictions.jsonl").open("x", encoding="utf-8") as stream:
        for prediction in predictions:
            stream.write(json.dumps(prediction, sort_keys=True) + "\n")
    (output / "val-report.json").write_text(
        json.dumps(best_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    executed_config = {
        "protocol_version": "1.4.0",
        "architecture": plan["architecture"],
        "base_weights": plan["base_weights"],
        "normalization": plan["normalization"],
        "seed": plan["seed"],
        "epochs": plan["epochs"],
        "cpu_threads": plan["cpu_threads"],
        "learning_rate": plan["learning_rate"],
        "preprocessing": plan["preprocessing"],
        "class_codes": plan["class_codes"],
        "publishable_classes": plan["publishable_classes"],
        "strategy": strategy,
        "healthy_train_only_augmentation": plan["healthy_train_only_augmentation"],
        "selection": plan["selection"],
    }
    (output / "candidate-config.json").write_text(
        json.dumps(executed_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    git_head = os.environ.get("AGRO_GIT_HEAD", "")
    if len(git_head) != 40 or any(character not in "0123456789abcdef" for character in git_head):
        raise ValueError("AGRO_GIT_HEAD verificado es obligatorio")
    experiment = {
        "status": "VAL_ONLY_CANDIDATE_NOT_FROZEN_NOT_G2",
        "protected_external_partition_accessed": False,
        "protocol_version": "1.4.0",
        "strategy_id": strategy_id,
        "seed": plan["seed"],
        "best_epoch_selected_on_val": best_epoch,
        "train_original_count": len(train),
        "val_original_count": len(val),
        "hashes": {
            **hashes,
            "train_manifest_sha256": sha256(output / "train-manifest.jsonl"),
            "val_manifest_sha256": sha256(output / "val-manifest.jsonl"),
            "weights_sha256": sha256(output / "weights.safetensors"),
            "candidate_config_sha256": sha256(output / "candidate-config.json"),
            "val_report_sha256": sha256(output / "val-report.json"),
            "val_predictions_sha256": sha256(output / "val-predictions.jsonl"),
        },
        "runtime": {
            "cpu_model": cpu_model(),
            "logical_cpus_visible": os.cpu_count(),
            "threads_used": plan["cpu_threads"],
            "ram_total_mb": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 / 1024, 2),
            "peak_rss_mb": rss_mb(),
            "total_seconds": time.perf_counter() - started,
            "python": platform.python_version(),
            "torch": torch.__version__,
            "torchvision": __import__("torchvision").__version__,
            "pillow": __import__("PIL").__version__,
            "safetensors": __import__("safetensors").__version__,
        },
        "git_head": git_head,
        "history": history,
        "command_contract": "python scripts/train_v14_candidate.py --plan ... --protocol ... --gate-status ... --private-g1 ... --images-root ... --output ... --strategy <id>",
    }
    (output / "experiment.json").write_text(
        json.dumps(experiment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": experiment["status"],
        "strategy": strategy_id,
        "best_epoch": best_epoch,
        "val_selection_passed": best_report["val_selection"]["passed"],
        "weights_sha256": experiment["hashes"]["weights_sha256"],
        "output": str(output),
    }, sort_keys=True), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--gate-status", type=Path, required=True)
    parser.add_argument("--private-g1", type=Path, required=True)
    parser.add_argument("--images-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strategy", choices=(
        "weighted-cross-entropy-full-train", "group-aware-balanced-sampler"
    ), required=True)
    args = parser.parse_args()
    run(args.plan, args.protocol, args.gate_status, args.private_g1,
        args.images_root, args.output, args.strategy)


if __name__ == "__main__":
    main()
