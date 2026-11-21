"""CPU experiments for the admitted two-blight pilot. Only TRAIN and VAL are accepted."""

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

import torch
from torch import nn
from torch.nn import functional as F
import torchvision
from torchvision.models import mobilenet_v3_small, resnet18
from safetensors.torch import save_file

from agro_ml.data.g1_evidence import load_evidence, validate_image_evidence
from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.evaluation.metrics import generate_evaluation_report


CLASSES = ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT")
OTHER_INDEX = 2  # Internal rejection target; never a published model class.
ARCHITECTURES = ("mobilenet_v3_small", "resnet18")
SPLITS = ("TRAIN", "VAL")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_inventory() -> dict:
    ml_root = Path(__file__).resolve().parents[2]
    sources = json.loads((ml_root / "manifests/sources.v2.json").read_text(encoding="utf-8"))["sources"]
    return next(source for source in sources if source["source_id"] == "plantvillage")


def read_config(path: Path) -> tuple[dict, TensorSpec]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or config.get("purpose") != "G1_PILOT_VAL_EXPERIMENT":
        raise ValueError("Configuración de piloto inválida")
    if config.get("architecture") not in ARCHITECTURES or config.get("base_weights") != "RANDOM_INITIALIZATION":
        raise ValueError("Arquitectura o pesos base no permitidos")
    if config.get("normalization", "BATCH_NORM") not in {"BATCH_NORM", "GROUP_NORM"}:
        raise ValueError("Normalización de red no permitida")
    for key, lower, upper in (("seed", 0, 2**32 - 1), ("epochs", 1, 20),
                              ("batch_size", 1, 64), ("cpu_threads", 1, 16)):
        value = config.get(key)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"{key} inválido")
    learning_rate = config.get("learning_rate")
    if (isinstance(learning_rate, bool) or not isinstance(learning_rate, (int, float))
            or not math.isfinite(learning_rate) or not 0 < learning_rate <= .1):
        raise ValueError("learning_rate inválido")
    if config.get("class_codes") != list(CLASSES) or config.get("negative_target") != "OTHER_CROP":
        raise ValueError("Taxonomía del piloto incompatible")
    spec = TensorSpec.from_dict(config["preprocessing"])
    return config, spec


def _rows(path: Path, expected_split: str) -> list[dict]:
    if expected_split not in SPLITS or path.name not in {
        f"{expected_split.lower()}-positives.csv", f"{expected_split.lower()}-negatives.csv"
    }:
        raise ValueError("Solo se permiten manifiestos TRAIN y VAL del piloto")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(row.get("split") != expected_split for row in rows):
        raise ValueError("Manifiesto vacío o partición incompatible")
    return rows


def load_split(split_root: Path, images_root: Path, evidence_path: Path,
               split: str, spec: TensorSpec, seed: int) -> tuple[list[dict], dict]:
    """Admit only explicitly named TRAIN/VAL files, exact bytes, and reviewed G1 records."""
    if split not in SPLITS:
        raise ValueError("TEST no puede usarse para entrenamiento ni selección")
    records, evidence_root = load_evidence(evidence_path)
    source = _source_inventory()
    samples = []
    hashes, groups = set(), set()
    digests = {}
    for kind in ("positives", "negatives"):
        path = split_root / f"{split.lower()}-{kind}.csv"
        digests[kind] = sha256(path)
        for row in _rows(path, split):
            if row.get("source") != "plantvillage" or row.get("image_id") != row.get("sha256"):
                raise ValueError("Fuente o identidad de imagen incompatible con G1")
            negative = kind == "negatives"
            if negative:
                if row.get("negative_category") != "OTHER_CROP":
                    raise ValueError("Negativo fuera de alcance")
            elif row.get("crop_code") != "POTATO" or row.get("class_code") not in CLASSES:
                raise ValueError("Clase fuera del piloto")
            record = records.get(row["image_id"])
            validate_image_evidence(row, record, evidence_root, images_root, source, negative=negative)
            if row["sha256"] in hashes:
                raise ValueError("SHA-256 repetido en partición")
            hashes.add(row["sha256"])
            groups.add(row["split_group"])
            raw = (images_root / record["relative_path"]).read_bytes()
            image_seed = seed + int(row["sha256"][:8], 16)
            tensor = image_to_tensor(raw, spec, split=split,
                                     augment=split == "TRAIN", seed=image_seed if split == "TRAIN" else None)
            samples.append({"image_id": row["image_id"], "sha256": row["sha256"],
                            "split_group": row["split_group"], "label": OTHER_INDEX if negative
                            else CLASSES.index(row["class_code"]), "tensor": tensor, "raw": raw})
    samples.sort(key=lambda item: item["image_id"])
    return samples, {"sha256": digests, "hashes": hashes, "groups": groups}


def _replace_batchnorm(module: nn.Module) -> None:
    for name, child in module.named_children():
        if isinstance(child, nn.BatchNorm2d):
            channels = child.num_features
            groups = min(32, channels)
            while channels % groups:
                groups -= 1
            setattr(module, name, nn.GroupNorm(groups, channels))
        else:
            _replace_batchnorm(child)


def build_model(architecture: str, seed: int, normalization: str = "BATCH_NORM") -> nn.Module:
    torch.manual_seed(seed)
    if architecture == "mobilenet_v3_small":
        model = mobilenet_v3_small(weights=None)
        model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 3)
    elif architecture == "resnet18":
        model = resnet18(weights=None)
        model.fc = nn.Linear(model.fc.in_features, 3)
    else:
        raise ValueError("Arquitectura no permitida")
    if normalization == "GROUP_NORM":
        _replace_batchnorm(model)
    elif normalization != "BATCH_NORM":
        raise ValueError("Normalización de red no permitida")
    return model.cpu()


def _probabilities(model: nn.Module, samples: list[dict], batch_size: int) -> list[list[float]]:
    model.eval()
    values = []
    with torch.inference_mode():
        for start in range(0, len(samples), batch_size):
            batch = torch.stack([item["tensor"] for item in samples[start:start + batch_size]])
            values.extend(torch.softmax(model(batch), dim=1).tolist())
    return values


def technical_decision(probs: list[float], threshold: float, score: float | None = None) -> int | None:
    """Publish neither OTHER nor weak/ambiguous evidence as a disease class."""
    if (len(probs) != 3 or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs)
            or abs(sum(probs) - 1) > 1e-4 or not math.isfinite(threshold)
            or not 0 <= threshold <= 1):
        raise ValueError("Probabilidades o umbral inválidos")
    candidate = max(range(2), key=lambda index: probs[index])
    confidence = probs[candidate] if score is None else score
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Score calibrado inválido")
    if probs[OTHER_INDEX] >= probs[candidate] or confidence < threshold:
        return None
    return candidate


def _metrics(samples: list[dict], probabilities: list[list[float]], threshold: float,
             latencies: list[float] | None = None, peak_rss_mb: float | None = None,
             candidate_scores: list[float] | None = None) -> dict:
    if len(samples) != len(probabilities) or (candidate_scores is not None and len(candidate_scores) != len(samples)):
        raise ValueError("VAL: cantidad de puntuaciones incompatible")
    truth, predicted, confidence, abstained = [], [], [], []
    for index, (sample, probs) in enumerate(zip(samples, probabilities)):
        if sample["label"] == OTHER_INDEX:
            continue
        candidate = max(range(2), key=lambda index: probs[index])
        truth.append(sample["label"])
        predicted.append(candidate)
        score = probs[candidate] if candidate_scores is None else candidate_scores[index]
        confidence.append(score)
        abstained.append(technical_decision(probs, threshold, score) is None)
    negative_published = []
    for index, (sample, probs) in enumerate(zip(samples, probabilities)):
        if sample["label"] != OTHER_INDEX:
            continue
        score = None if candidate_scores is None else candidate_scores[index]
        decision = technical_decision(probs, threshold, score)
        negative_published.append(CLASSES[decision] if decision is not None else None)
    report = generate_evaluation_report(
        "VAL", truth, predicted, confidence, list(CLASSES), abstained=abstained,
        negative_published_classes=negative_published, latency_measurements_ms=latencies,
        measured_peak_rss_mb=peak_rss_mb,
    ).to_dict()
    report.pop("evaluated_at")
    report["threshold"] = threshold
    report["threshold_status"] = "VAL_EXPLORATORY_NOT_FROZEN"
    report["negative_rejection_rate"] = round(1 - report["negative_samples_fpr"], 4)
    return report


def _choice_key(report: dict) -> tuple:
    f1 = report["macro_f1"] or 0.0
    recall = min((value["recall"] or 0.0) for value in report["per_class"].values())
    coverage = report["selective_coverage"] or 0.0
    error = report["selective_error_rate"]
    fpr = report["negative_samples_fpr"]
    feasible = (f1 >= .8 and coverage >= .7 and error is not None and error <= .1
                and fpr is not None and fpr <= .05)
    return (feasible, f1, recall, coverage, -(error if error is not None else 1.0),
            -(fpr if fpr is not None else 1.0), -report["threshold"])


def _choose_val_point(samples: list[dict], probabilities: list[list[float]]) -> dict:
    points = [_metrics(samples, probabilities, round(step / 20, 2)) for step in range(0, 20)]
    return max(points, key=_choice_key)


def _rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)


def _hardware() -> dict:
    cpu_name = platform.processor()
    cpu_info = Path("/proc/cpuinfo")
    if cpu_info.exists():
        cpu_name = next((line.split(":", 1)[1].strip() for line in cpu_info.read_text().splitlines()
                         if line.startswith("model name")), cpu_name)
    memory = Path("/proc/meminfo")
    ram_mb = None
    if memory.exists():
        line = next((line for line in memory.read_text().splitlines() if line.startswith("MemTotal:")), None)
        if line:
            ram_mb = round(int(line.split()[1]) / 1024)
    return {"cpu_model": cpu_name, "logical_cpus": os.cpu_count(), "total_ram_mb": ram_mb,
            "machine": platform.machine(), "python": sys.version.split()[0],
            "torch": torch.__version__, "torchvision": torchvision.__version__,
            "pillow": __import__("PIL").__version__, "safetensors": __import__("safetensors").__version__}


def _git_revision() -> dict:
    ml_root = Path(__file__).resolve().parents[2]
    repo_root = ml_root.parent
    if shutil.which("git"):
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                                  capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=repo_root,
                                    capture_output=True, text=True, check=True).stdout.strip())
    else:
        revision = os.environ.get("AGRO_GIT_HEAD", "")
        dirty_value = os.environ.get("AGRO_GIT_DIRTY")
        if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision) or dirty_value not in {"0", "1"}:
            raise ValueError("Falta revisión Git verificable en el contenedor")
        dirty = dirty_value == "1"
    return {"head": revision, "dirty": dirty,
            "pilot_code_sha256": sha256(Path(__file__)),
            "preprocessing_code_sha256": sha256(ml_root / "src/agro_ml/data/tensor_preprocessing.py"),
            "dependency_lock_sha256": sha256(ml_root / "uv.lock")}


def run(config_path: Path, split_root: Path, images_root: Path, evidence_path: Path,
        output_dir: Path) -> dict:
    config, spec = read_config(config_path)
    revision = _git_revision()
    hardware = _hardware()
    torch.set_num_threads(config["cpu_threads"])
    torch.manual_seed(config["seed"])
    torch.use_deterministic_algorithms(True)
    train, train_info = load_split(split_root, images_root, evidence_path, "TRAIN", spec, config["seed"])
    val, val_info = load_split(split_root, images_root, evidence_path, "VAL", spec, config["seed"])
    if train_info["hashes"] & val_info["hashes"] or train_info["groups"] & val_info["groups"]:
        raise ValueError("Fuga entre TRAIN y VAL")
    for label, minimum in ((0, (150, 50)), (1, (150, 50))):
        rows = [item for item in train if item["label"] == label]
        if len(rows) < minimum[0] or len({item["split_group"] for item in rows}) < minimum[1]:
            raise ValueError("TRAIN no cumple mínimos G0")
        rows = [item for item in val if item["label"] == label]
        if len(rows) < 40 or len({item["split_group"] for item in rows}) < 20:
            raise ValueError("VAL no cumple mínimos G0")
    model = build_model(config["architecture"], config["seed"], config.get("normalization", "BATCH_NORM"))
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"])
    output_dir.mkdir(parents=True, exist_ok=False)
    history = []
    best_state = None
    best_report = None
    best_epoch = None
    started = time.perf_counter()
    try:
        for epoch in range(1, config["epochs"] + 1):
            epoch_started = time.perf_counter()
            # GroupNorm mantiene la misma normalización en TRAIN y en inferencia.
            # El recorrido diagnóstico con BatchNorm usa estadísticas fijas.
            if config.get("normalization") == "GROUP_NORM":
                model.train()
            else:
                model.eval()
            generator = torch.Generator().manual_seed(config["seed"] + epoch)
            order = torch.randperm(len(train), generator=generator).tolist()
            losses = []
            for start in range(0, len(order), config["batch_size"]):
                batch = [train[index] for index in order[start:start + config["batch_size"]]]
                images = torch.stack([item["tensor"] for item in batch])
                labels = torch.tensor([item["label"] for item in batch], dtype=torch.long)
                optimizer.zero_grad(set_to_none=True)
                loss = F.cross_entropy(model(images), labels)
                if not bool(torch.isfinite(loss)):
                    raise ValueError("Pérdida no finita")
                loss.backward()
                optimizer.step()
                losses.append(float(loss.detach()))
            probabilities = _probabilities(model, val, config["batch_size"])
            report = _choose_val_point(val, probabilities)
            entry = {"epoch": epoch, "train_loss_mean": round(sum(losses) / len(losses), 6),
                     "epoch_seconds_including_val": round(time.perf_counter() - epoch_started, 3),
                     "peak_rss_mb": _rss_mb(), "val_macro_f1": report["macro_f1"],
                     "val_recall": {code: report["per_class"][code]["recall"] for code in CLASSES},
                     "val_coverage": report["selective_coverage"],
                     "val_selective_error": report["selective_error_rate"],
                     "val_negative_fpr": report["negative_samples_fpr"],
                     "val_threshold_exploratory": report["threshold"]}
            history.append(entry)
            print(json.dumps(entry, sort_keys=True), flush=True)
            if best_report is None or _choice_key(report) > _choice_key(best_report):
                best_report, best_epoch = report, epoch
                best_state = {key: value.detach().cpu().clone().contiguous()
                              for key, value in model.state_dict().items()}
        model.load_state_dict(best_state)
        model.eval()
        latency = []
        for sample in val:
            if sample["label"] == OTHER_INDEX:
                continue
            tick = time.perf_counter_ns()
            tensor = image_to_tensor(sample["raw"], spec, split="INFERENCE").unsqueeze(0)
            with torch.inference_mode():
                model(tensor)
            latency.append((time.perf_counter_ns() - tick) / 1_000_000)
        probabilities = _probabilities(model, val, config["batch_size"])
        final = _metrics(val, probabilities, best_report["threshold"], latency, _rss_mb())
        weights = output_dir / "pilot-weights.safetensors"
        save_file(best_state, str(weights))
        scores = output_dir / "val-scores.jsonl"
        with scores.open("x", encoding="utf-8") as stream:
            for sample, probs in zip(val, probabilities):
                stream.write(json.dumps({"image_id": sample["image_id"], "true_target": sample["label"],
                                         "probabilities": probs}, sort_keys=True) + "\n")
        report_path = output_dir / "val-report.json"
        report_path.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        metadata = {"schema_version": 1, "status": "VAL_EXPLORATION_UNAPPROVED", "g2_approval": None,
                    "test_evaluated": False, "architecture": config["architecture"],
                    "class_codes": list(CLASSES), "technical_reject_target": "OTHER_CROP",
                    "base_weights": "RANDOM_INITIALIZATION", "seed": config["seed"],
                    "normalization": config.get("normalization", "BATCH_NORM"),
                    "best_epoch_by_val": best_epoch, "config_sha256": sha256(config_path),
                    "g1_evidence_sha256": sha256(evidence_path),
                    "train_manifest_sha256": train_info["sha256"],
                    "val_manifest_sha256": val_info["sha256"],
                    "train_count": len(train), "val_count": len(val),
                    "preprocessing": spec.to_dict(), "history": history,
                    "val_selected_threshold_exploratory": best_report["threshold"],
                    "val_metrics_sha256": sha256(report_path), "val_scores_sha256": sha256(scores),
                    "weights_sha256": sha256(weights), "runtime": hardware,
                    "code": revision, "total_seconds": round(time.perf_counter() - started, 3),
                    "peak_rss_mb": _rss_mb(), "command": sys.argv}
        metadata_path = output_dir / "experiment.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"experiment": str(metadata_path), "val_report": str(report_path),
                "best_epoch": best_epoch, "val_macro_f1": final["macro_f1"],
                "val_coverage": final["selective_coverage"], "status": metadata["status"]}
    except Exception:
        # A failed experiment is not silently promoted. Keep partial files for diagnosis.
        (output_dir / "FAILED").write_text("Experiment failed before completion\n", encoding="utf-8")
        raise
