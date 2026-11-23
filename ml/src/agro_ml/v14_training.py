"""Primitivas reproducibles de TRAIN/VAL para el ciclo v1.4.0.

No conoce rutas ni manifiestos EXTERNAL. Las funciones de selección operan
únicamente con logits y etiquetas VAL entregados explícitamente.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import io
import math
import random
from typing import Any, Mapping, Sequence

from PIL import Image, ImageEnhance, ImageOps
import torch
from torchvision.transforms.functional import pil_to_tensor

from agro_ml.data.tensor_preprocessing import ALLOWED_FORMATS, MAX_IMAGE_BYTES, TensorSpec
from agro_ml.v13_metrics import DISEASES, HEALTHY, OTHER, TARGETS, evaluate, probabilities


class V14TrainingError(ValueError):
    """Configuración o datos TRAIN/VAL incompatibles con G0 v1.4.0."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V14TrainingError(message)


def validate_plan(plan: Mapping[str, Any]) -> TensorSpec:
    _require(plan.get("schema_version") == 1, "schema de plan inválido")
    _require(plan.get("status") == "PLANNED_NOT_TRAINED", "plan ya ejecutado o inválido")
    _require(plan.get("protocol_version") == "1.4.0", "protocolo de plan inválido")
    _require(plan.get("architecture") == "mobilenet_v3_small", "arquitectura no aprobada")
    _require(plan.get("base_weights") == "RANDOM_INITIALIZATION_NO_DOWNLOADS",
             "pesos base podrían descargar contenido")
    _require(plan.get("normalization") == "GROUP_NORM", "normalización no aprobada")
    _require(plan.get("class_codes") == list(TARGETS), "clases técnicas inválidas")
    _require(plan.get("publishable_classes") == list(DISEASES), "clases publicables inválidas")
    for key, lower, upper in (("seed", 0, 2**32 - 1), ("epochs", 1, 20),
                              ("cpu_threads", 1, 16)):
        value = plan.get(key)
        _require(type(value) is int and lower <= value <= upper, f"{key} inválido")
    learning_rate = plan.get("learning_rate")
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate)
             and 0 < learning_rate <= .1, "learning_rate inválido")
    strategies = plan.get("strategies_to_compare_on_same_val")
    _require(isinstance(strategies, list) and [item.get("strategy_id") for item in strategies] == [
        "weighted-cross-entropy-full-train", "group-aware-balanced-sampler"
    ], "estrategias de balance inválidas")
    _require(plan.get("external", {}).get("use_during_this_plan") == "NONE",
             "EXTERNAL no está bloqueado en el plan")
    return TensorSpec.from_dict(dict(plan["preprocessing"]))


def strategy_config(plan: Mapping[str, Any], strategy_id: str) -> dict[str, Any]:
    validate_plan(plan)
    matches = [dict(item) for item in plan["strategies_to_compare_on_same_val"]
               if item.get("strategy_id") == strategy_id]
    _require(len(matches) == 1, "estrategia desconocida")
    return matches[0]


def validate_augmentation_request(split: str, class_code: str, enabled: bool) -> None:
    if enabled:
        _require(split == "TRAIN", "aumento fuera de TRAIN")
        _require(class_code == HEALTHY, "aumento permitido solo para POTATO_HEALTHY")


def _decode_rgb(raw: bytes, spec: TensorSpec) -> Image.Image:
    _require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_IMAGE_BYTES, "bytes de imagen inválidos")
    with Image.open(io.BytesIO(raw)) as probe:
        fmt = probe.format
        probe.verify()
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        _require(fmt in ALLOWED_FORMATS, "formato no permitido")
        _require(spec.min_dimension <= image.width <= spec.max_dimension and
                 spec.min_dimension <= image.height <= spec.max_dimension,
                 "dimensiones fuera de rango")
        return ImageOps.exif_transpose(image).convert("RGB")


def healthy_train_tensor(
    raw: bytes,
    spec: TensorSpec,
    *,
    seed: int,
    augmentation: Mapping[str, Any],
) -> tuple[torch.Tensor, dict[str, Any]]:
    """Crea una vista sana TRAIN y devuelve su linaje reproducible."""
    validate_augmentation_request("TRAIN", HEALTHY, True)
    _require(type(seed) is int and seed >= 0, "semilla de aumento inválida")
    operations = augmentation.get("operations", {})
    flip_probability = operations.get("random_horizontal_flip_probability")
    rotation = operations.get("random_rotation_degrees")
    brightness = operations.get("color_jitter_brightness")
    contrast = operations.get("color_jitter_contrast")
    saturation = operations.get("color_jitter_saturation")
    _require(all(type(value) in (int, float) and math.isfinite(value) for value in
                 (flip_probability, rotation, brightness, contrast, saturation)),
             "parámetros de aumento inválidos")
    _require(0 <= flip_probability <= 1 and 0 <= rotation <= 30 and
             0 <= brightness <= .25 and 0 <= contrast <= .25 and 0 <= saturation <= .25,
             "aumento fuera del presupuesto conservador")
    rng = random.Random(seed)
    image = _decode_rgb(raw, spec)
    flipped = rng.random() < flip_probability
    if flipped:
        image = ImageOps.mirror(image)
    angle = rng.uniform(-rotation, rotation)
    fill = tuple(round(channel * 255) for channel in spec.mean)
    image = image.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=fill)
    factors = {
        "brightness": 1 + rng.uniform(-brightness, brightness),
        "contrast": 1 + rng.uniform(-contrast, contrast),
        "saturation": 1 + rng.uniform(-saturation, saturation),
    }
    image = ImageEnhance.Brightness(image).enhance(factors["brightness"])
    image = ImageEnhance.Contrast(image).enhance(factors["contrast"])
    image = ImageEnhance.Color(image).enhance(factors["saturation"])
    image = image.resize((spec.width, spec.height), Image.Resampling.BILINEAR)
    tensor = pil_to_tensor(image).to(dtype=torch.float32).div_(255.0)
    mean = torch.tensor(spec.mean, dtype=torch.float32).view(3, 1, 1)
    std = torch.tensor(spec.std, dtype=torch.float32).view(3, 1, 1)
    tensor = ((tensor - mean) / std).contiguous()
    _require(tensor.shape == (3, spec.height, spec.width) and bool(torch.isfinite(tensor).all()),
             "tensor aumentado inválido")
    return tensor, {"seed": seed, "horizontal_flip": flipped,
                    "rotation_degrees": angle, **factors}


def group_balanced_epoch_indices(
    samples: Sequence[Mapping[str, Any]],
    *,
    samples_per_class: int,
    seed: int,
) -> tuple[list[int], dict[str, Any]]:
    """Muestrea clase→leaf_id→imagen sin convertir vistas en grupos."""
    _require(type(samples_per_class) is int and samples_per_class > 0, "muestras por clase inválidas")
    _require(type(seed) is int and seed >= 0, "semilla de sampler inválida")
    grouped: dict[str, dict[str, list[int]]] = {
        code: defaultdict(list) for code in TARGETS
    }
    for index, sample in enumerate(samples):
        code = sample.get("stratum_code")
        group = sample.get("split_group")
        _require(code in TARGETS and isinstance(group, str) and group and not group.startswith("fallback_"),
                 "muestra o leaf_id inválido")
        grouped[code][group].append(index)
    _require(all(grouped[code] for code in TARGETS), "clase vacía en sampler")
    selected: list[int] = []
    exposure: dict[str, Any] = {}
    for class_index, code in enumerate(TARGETS):
        rng = random.Random(seed + class_index * 100_003)
        groups = sorted(grouped[code])
        selected_groups: list[str] = []
        while len(selected_groups) < samples_per_class:
            cycle = groups.copy()
            rng.shuffle(cycle)
            selected_groups.extend(cycle[:samples_per_class - len(selected_groups)])
        class_indices = [rng.choice(grouped[code][group]) for group in selected_groups]
        selected.extend(class_indices)
        group_counts = Counter(selected_groups)
        exposure[code] = {
            "draws": len(class_indices),
            "unique_leaf_groups": len(set(selected_groups)),
            "available_leaf_groups": len(groups),
            "unique_original_images": len(set(class_indices)),
            "min_draws_per_exposed_group": min(group_counts.values()),
            "max_draws_per_exposed_group": max(group_counts.values()),
        }
    random.Random(seed + 900_001).shuffle(selected)
    return selected, exposure


def choose_temperature(rows: Sequence[Mapping[str, Any]], logits: Sequence[Sequence[float]]) -> float:
    _require(len(rows) == len(logits) and bool(rows), "logits VAL incompletos")
    technical = [(row, values) for row, values in zip(rows, logits)
                 if row.get("stratum_code") in TARGETS]
    options = (.5, .67, .8, 1.0, 1.25, 1.5, 2.0, 3.0)

    def nll(temperature: float) -> float:
        total = 0.0
        for row, values in technical:
            target = TARGETS.index(row["stratum_code"])
            total -= math.log(max(1e-12, probabilities(values, temperature)[target]))
        return total / len(technical)

    return min(options, key=nll)


def add_confusion_matrix(report: dict[str, Any]) -> None:
    rows = (*TARGETS, OTHER)
    columns = (*DISEASES, "NO_CONCLUYENTE")
    matrix = {row: {column: 0 for column in columns} for row in rows}
    for prediction in report["predictions"]:
        column = prediction["published_class"] or "NO_CONCLUYENTE"
        matrix[prediction["stratum_code"]][column] += 1
    report["visible_confusion_matrix"] = {
        "rows_true": list(rows), "columns_published": list(columns), "counts": matrix
    }


def val_conditions(report: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, bool]:
    limits = selection["minimums_before_priority_ranking"]
    healthy = report["counts"][HEALTHY]
    other = report["counts"][OTHER]
    return {
        "macro_f1": report["macro_f1"] >= limits["macro_f1_two_blights_min"],
        "recall_each_blight": all(item["recall"] >= limits["recall_each_blight_min"]
                                    for item in report["per_class"].values()),
        "coverage": report["coverage"]["rate"] is not None and
                    report["coverage"]["rate"] >= limits["selective_coverage_min"],
        "selective_error": report["selective_error"]["rate"] is not None and
                           report["selective_error"]["rate"] <= limits["selective_error_max"],
        "healthy_rejection": healthy["accepted"] <= limits["healthy_visible_blight_max"],
        "other_crop_rejection": other["accepted"] <= limits["other_crop_visible_blight_max"],
        "calibration": report["ece_technical_potato"] <= limits["calibration_ece_max"],
    }


def selection_rank(report: Mapping[str, Any]) -> tuple[Any, ...]:
    conditions = report.get("val_selection", {}).get("conditions", {})
    shortfall = report.get("val_selection", {}).get("normalized_shortfall", math.inf)
    error = report["selective_error"]["rate"]
    coverage = report["coverage"]["rate"]
    return (
        bool(conditions) and all(conditions.values()),
        -shortfall,
        sum(bool(value) for value in conditions.values()),
        -report["counts"][HEALTHY]["accepted"],
        -report["counts"][OTHER]["accepted"],
        min(item["recall"] for item in report["per_class"].values()),
        report["macro_f1"],
        -(error if error is not None else 1.0),
        coverage if coverage is not None else 0.0,
        -report["ece_technical_potato"],
        -report["threshold"],
    )


def normalized_shortfall(report: Mapping[str, Any], selection: Mapping[str, Any]) -> float:
    """Mide distancia a las mínimas para evitar seleccionar abstención total.

    Las prioridades se aplican después de que una opción cumple todos los
    mínimos. Si ninguna los cumple, gana la opción con menor incumplimiento
    relativo agregado, no una política vacía con cobertura cero.
    """
    limits = selection["minimums_before_priority_ranking"]
    error = report["selective_error"]["rate"]
    coverage = report["coverage"]["rate"]
    deficits = [
        max(0.0, limits["macro_f1_two_blights_min"] - report["macro_f1"])
        / limits["macro_f1_two_blights_min"],
        *(max(0.0, limits["recall_each_blight_min"] - item["recall"])
          / limits["recall_each_blight_min"] for item in report["per_class"].values()),
        max(0.0, limits["selective_coverage_min"] - (coverage or 0.0))
        / limits["selective_coverage_min"],
        1.0 if error is None else max(0.0, error - limits["selective_error_max"])
        / max(limits["selective_error_max"], 1e-12),
        max(0, report["counts"][HEALTHY]["accepted"] - limits["healthy_visible_blight_max"])
        / max(1, report["counts"][HEALTHY]["photos"]),
        max(0, report["counts"][OTHER]["accepted"] - limits["other_crop_visible_blight_max"])
        / max(1, report["counts"][OTHER]["photos"]),
        max(0.0, report["ece_technical_potato"] - limits["calibration_ece_max"])
        / max(limits["calibration_ece_max"], 1e-12),
    ]
    return sum(deficits)


def choose_val_policy(
    rows: Sequence[Mapping[str, Any]],
    logits: Sequence[Sequence[float]],
    selection: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    """Selecciona calibración/ruta/umbral con VAL y devuelve opciones evaluadas."""
    temperature = choose_temperature(rows, logits)
    candidates = []
    for route, gates in (("ARGMAX_CONFIDENCE", (None,)), ("HEALTHY_GATE", (.25, .4, .55))):
        for healthy_gate in gates:
            for step in range(10, 100, 5):
                report = evaluate(rows, logits, temperature, step / 100, route, healthy_gate)
                add_confusion_matrix(report)
                conditions = val_conditions(report, selection)
                report["val_selection"] = {
                    "passed": all(conditions.values()),
                    "conditions": conditions,
                    "normalized_shortfall": normalized_shortfall(report, selection),
                    "priority": list(selection["priority_after_minimums"]),
                }
                candidates.append(report)
    return max(candidates, key=selection_rank), len(candidates)
