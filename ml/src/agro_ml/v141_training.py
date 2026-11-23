"""Entrenamiento y selección VAL de cuatro logits para v1.4.1."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
import random
from typing import Any, Mapping, Sequence

import torch
from torch import nn
from torchvision.models import mobilenet_v3_small

from agro_ml.data.tensor_preprocessing import TensorSpec
from agro_ml.v14_training import healthy_train_tensor
from agro_ml.v141_gates import PUBLISHABLE_CLASSES, TECHNICAL_CLASSES

HEALTHY = "POTATO_HEALTHY"
OTHER = "OTHER_CROP"


class V141TrainingError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise V141TrainingError(message)


def validate_plan(plan: Mapping[str, Any]) -> TensorSpec:
    _require(plan.get("status") == "PLANNED_NOT_TRAINED" and
             plan.get("protocol_version") == "1.4.1", "plan v1.4.1 inválido")
    _require(plan.get("architecture") == "mobilenet_v3_small" and
             plan.get("base_weights") == "RANDOM_INITIALIZATION_NO_DOWNLOADS" and
             plan.get("normalization") == "GROUP_NORM", "arquitectura no aprobada")
    _require(tuple(plan.get("technical_class_codes", ())) == TECHNICAL_CLASSES,
             "se requieren cuatro clases técnicas ordenadas")
    _require(tuple(plan.get("publishable_classes", ())) == PUBLISHABLE_CLASSES,
             "clases publicables inválidas")
    sampler = plan.get("sampler", {})
    _require(sampler.get("samples_per_class_per_epoch") == 80 and
             sampler.get("samples_per_epoch") == 320, "sampler debe ser 80x4")
    _require(plan.get("external_access") == "NONE" and
             {"HISTORICAL_TEST", "SIKKIM_EXTERNAL"}.issubset(plan.get("forbidden_inputs", ())),
             "TEST/EXTERNAL no están bloqueados")
    return TensorSpec.from_dict(dict(plan["preprocessing"]))


def _replace_batchnorm(module: nn.Module) -> None:
    for name, child in module.named_children():
        if isinstance(child, nn.BatchNorm2d):
            groups = min(32, child.num_features)
            while child.num_features % groups:
                groups -= 1
            setattr(module, name, nn.GroupNorm(groups, child.num_features))
        else:
            _replace_batchnorm(child)


def build_model(seed: int) -> nn.Module:
    torch.manual_seed(seed)
    model = mobilenet_v3_small(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 4)
    _replace_batchnorm(model)
    return model.cpu()


def balanced_epoch_indices(samples: Sequence[Mapping[str, Any]], *, seed: int,
                           samples_per_class: int = 80) -> tuple[list[int], dict[str, Any]]:
    _require(type(seed) is int and seed >= 0 and samples_per_class == 80,
             "sampler requiere semilla y 80 muestras")
    grouped = {code: defaultdict(list) for code in TECHNICAL_CLASSES}
    for index, sample in enumerate(samples):
        code, group = sample.get("stratum_code"), sample.get("split_group")
        _require(code in grouped and isinstance(group, str) and group and
                 not group.startswith("fallback_"), "clase o leaf_id inválido")
        grouped[code][group].append(index)
    _require(all(grouped[code] for code in TECHNICAL_CLASSES), "clase vacía")
    selected, exposure = [], {}
    for class_index, code in enumerate(TECHNICAL_CLASSES):
        rng = random.Random(seed + class_index * 100_003)
        groups = sorted(grouped[code])
        chosen_groups = []
        while len(chosen_groups) < samples_per_class:
            cycle = groups.copy()
            rng.shuffle(cycle)
            chosen_groups.extend(cycle[:samples_per_class - len(chosen_groups)])
        indices = [rng.choice(grouped[code][group]) for group in chosen_groups]
        selected.extend(indices)
        exposure[code] = {"draws": 80, "available_leaf_groups": len(groups),
                          "unique_leaf_groups": len(set(chosen_groups)),
                          "unique_original_images": len(set(indices))}
    random.Random(seed + 900_001).shuffle(selected)
    return selected, exposure


def validate_augmentation(split: str, class_code: str, enabled: bool) -> None:
    if enabled:
        _require(split == "TRAIN" and class_code == HEALTHY,
                 "aumentos solo para POTATO_HEALTHY TRAIN")


def probabilities(logits: Sequence[float], temperature: float) -> list[float]:
    _require(len(logits) == 4 and math.isfinite(temperature) and temperature > 0,
             "logits o temperatura inválidos")
    values = [float(value) / temperature for value in logits]
    _require(all(math.isfinite(value) for value in values), "logit no finito")
    peak = max(values)
    exponents = [math.exp(value - peak) for value in values]
    total = sum(exponents)
    return [value / total for value in exponents]


def visible_decision(probs: Sequence[float], threshold: float) -> int | None:
    _require(len(probs) == 4 and all(math.isfinite(value) and 0 <= value <= 1 for value in probs)
             and abs(sum(probs) - 1) <= 1e-4 and 0 <= threshold <= 1,
             "probabilidades o umbral inválidos")
    candidate = max(range(4), key=lambda index: probs[index])
    if candidate >= 2 or probs[candidate] < threshold:
        return None
    return candidate


def evaluate(rows: Sequence[Mapping[str, Any]], logits: Sequence[Sequence[float]],
             temperature: float, threshold: float) -> dict[str, Any]:
    _require(len(rows) == len(logits) and bool(rows), "scores VAL incompletos")
    probs = [probabilities(values, temperature) for values in logits]
    decisions = [visible_decision(values, threshold) for values in probs]
    counts = {code: {"photos": 0, "accepted": 0, "correct": 0, "abstained": 0}
              for code in TECHNICAL_CLASSES}
    for row, decision in zip(rows, decisions):
        code = row.get("stratum_code")
        _require(code in counts, "estrato desconocido")
        counts[code]["photos"] += 1
        counts[code]["accepted"] += decision is not None
        counts[code]["abstained"] += decision is None
        if code in PUBLISHABLE_CLASSES:
            counts[code]["correct"] += decision == PUBLISHABLE_CLASSES.index(code)
    per_class = {}
    for index, code in enumerate(PUBLISHABLE_CLASSES):
        tp = counts[code]["correct"]
        fp = sum(decision == index and row["stratum_code"] != code
                 for row, decision in zip(rows, decisions))
        fn = counts[code]["photos"] - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / counts[code]["photos"]
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[code] = {"tp": tp, "fp": fp, "fn": fn,
                           "support": counts[code]["photos"], "precision": precision,
                           "recall": recall, "f1": f1}
    accepted = sum(counts[code]["accepted"] for code in PUBLISHABLE_CLASSES)
    correct = sum(counts[code]["correct"] for code in PUBLISHABLE_CLASSES)
    positive = sum(counts[code]["photos"] for code in PUBLISHABLE_CLASSES)
    ece = 0.0
    for bin_index in range(10):
        items = [(max(p), int(TECHNICAL_CLASSES[max(range(4), key=lambda i: p[i])] == row["stratum_code"]))
                 for p, row in zip(probs, rows) if min(9, int(max(p) * 10)) == bin_index]
        if items:
            ece += len(items) / len(rows) * abs(sum(x for x, _ in items) / len(items) -
                                                 sum(y for _, y in items) / len(items))
    predictions = [{"image_id": row["image_id"], "stratum_code": row["stratum_code"],
                    "split_group": row["split_group"],
                    "technical_argmax": TECHNICAL_CLASSES[max(range(4), key=lambda i: p[i])],
                    "published_class": PUBLISHABLE_CLASSES[decision] if decision is not None else None,
                    "visible_state": "COMPLETADO" if decision is not None else "NO_CONCLUYENTE",
                    "probabilities": p}
                   for row, decision, p in zip(rows, decisions, probs)]
    matrix = {code: {column: 0 for column in (*PUBLISHABLE_CLASSES, "NO_CONCLUYENTE")}
              for code in TECHNICAL_CLASSES}
    for prediction in predictions:
        matrix[prediction["stratum_code"]][prediction["published_class"] or "NO_CONCLUYENTE"] += 1
    return {"split": "VAL", "route": "FOUR_CLASS_ARGMAX_CONFIDENCE", "temperature": temperature,
            "threshold": threshold, "counts": counts, "per_class": per_class,
            "macro_f1": sum(item["f1"] for item in per_class.values()) / 2,
            "coverage": {"numerator": accepted, "denominator": positive,
                         "rate": accepted / positive},
            "selective_error": {"numerator": accepted - correct, "denominator": accepted,
                                "rate": (accepted - correct) / accepted if accepted else None},
            "ece_four_class": ece,
            "visible_confusion_matrix": {"rows_true": list(TECHNICAL_CLASSES),
                "columns_published": [*PUBLISHABLE_CLASSES, "NO_CONCLUYENTE"], "counts": matrix},
            "predictions": predictions}


def choose_temperature(rows: Sequence[Mapping[str, Any]], logits: Sequence[Sequence[float]]) -> float:
    options = (.5, .67, .8, 1.0, 1.25, 1.5, 2.0, 3.0)
    def nll(temp: float) -> float:
        return -sum(math.log(max(1e-12, probabilities(values, temp)[TECHNICAL_CLASSES.index(row["stratum_code"])]))
                    for row, values in zip(rows, logits)) / len(rows)
    return min(options, key=nll)


def conditions(report: Mapping[str, Any], minimums: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "macro_f1": report["macro_f1"] >= minimums["macro_f1_two_blights_min"],
        "recall_each_blight": all(item["recall"] >= minimums["recall_each_blight_min"]
                                  for item in report["per_class"].values()),
        "coverage": report["coverage"]["rate"] >= minimums["selective_coverage_min"],
        "selective_error": report["selective_error"]["rate"] is not None and
                           report["selective_error"]["rate"] <= minimums["selective_error_max"],
        "healthy_rejection": report["counts"][HEALTHY]["accepted"] <= minimums["healthy_visible_blight_max"],
        "other_crop_rejection": report["counts"][OTHER]["accepted"] <= minimums["other_crop_visible_blight_max"],
        "calibration": report["ece_four_class"] <= minimums["calibration_ece_max"],
    }


def choose_val_policy(rows: Sequence[Mapping[str, Any]], logits: Sequence[Sequence[float]],
                      minimums: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    temperature = choose_temperature(rows, logits)
    candidates = []
    for step in range(10, 100, 5):
        report = evaluate(rows, logits, temperature, step / 100)
        checks = conditions(report, minimums)
        report["val_selection"] = {"passed": all(checks.values()), "conditions": checks}
        candidates.append(report)
    def rank(report: Mapping[str, Any]) -> tuple[Any, ...]:
        error = report["selective_error"]["rate"]
        return (report["val_selection"]["passed"], sum(report["val_selection"]["conditions"].values()),
                -report["counts"][HEALTHY]["accepted"], -report["counts"][OTHER]["accepted"],
                min(item["recall"] for item in report["per_class"].values()), report["macro_f1"],
                -(error if error is not None else 1.0), report["coverage"]["rate"],
                -report["ece_four_class"], -report["threshold"])
    return max(candidates, key=rank), len(candidates)
