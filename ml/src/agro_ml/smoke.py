"""Smoke CPU con imágenes geométricas sintéticas; nunca constituye G0/G2."""

from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw
import torch

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor, measure_cpu_preprocessing
from agro_ml.models.torch_cpu import (
    CropPolicy, build_model, freeze_feature_extractor, load_fixture_checkpoint,
    predict_image, save_fixture_checkpoint, select_fixture_crop_policy, train_fixture_epoch,
    train_fixture_hierarchical_heads,
)
from agro_ml.models.architectures import CLASS_MAPPING


@dataclass(frozen=True)
class SmokeConfig:
    seed: int
    input_size: tuple[int, int]
    epochs: int
    learning_rate: float
    hierarchical_steps: int
    hierarchical_learning_rate: float

    @classmethod
    def from_file(cls, path: Path) -> "SmokeConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("purpose") != "CPU_FIXTURE_SMOKE_ONLY":
            raise ValueError("Configuración de smoke no autorizada")
        if type(data.get("seed")) is not int or data["seed"] < 0:
            raise ValueError("Semilla inválida")
        if type(data.get("epochs")) is not int or not 1 <= data["epochs"] <= 3:
            raise ValueError("Épocas de smoke fuera de rango")
        lr = data.get("learning_rate")
        if isinstance(lr, bool) or not isinstance(lr, (int, float)) or not math.isfinite(lr) or not 0 < lr <= 0.1:
            raise ValueError("Learning rate inválido")
        size = data.get("input_size")
        if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int for v in size):
            raise ValueError("Tamaño inválido")
        TensorSpec(size[0], size[1])
        head_steps = data.get("hierarchical_steps")
        head_lr = data.get("hierarchical_learning_rate")
        if type(head_steps) is not int or not 1 <= head_steps <= 100:
            raise ValueError("Pasos jerárquicos inválidos")
        if isinstance(head_lr, bool) or not isinstance(head_lr, (int, float)) or not math.isfinite(head_lr) or not 0 < head_lr <= .1:
            raise ValueError("Learning rate jerárquico inválido")
        return cls(data["seed"], tuple(size), data["epochs"], float(lr), head_steps, float(head_lr))


def fixture_image(label: int | None, *, variant: int = 0) -> bytes:
    """Patrón gráfico de prueba; no simula una fotografía de una planta."""
    if label is not None and (type(label) is not int or not 0 <= label < 7):
        raise ValueError("Etiqueta fixture inválida")
    if type(variant) is not int or variant < 0:
        raise ValueError("Variante inválida")
    palette = [(180, 60, 50), (100, 170, 35), (60, 80, 190),
               (190, 150, 35), (140, 50, 180), (40, 165, 170), (160, 95, 70)]
    base = (55, 55, 55) if label is None else palette[label]
    image = Image.new("RGB", (224, 224), color=base)
    draw = ImageDraw.Draw(image)
    step = 20 if label is None else 12 + 2 * label
    for x in range(0, 224, step):
        color = tuple(min(255, channel + 55) for channel in base)
        draw.rectangle((x + variant % 3, 0, min(223, x + 4 + variant % 3), 223), fill=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def run_cpu_smoke(config_path: Path, architecture: str, output_dir: Path) -> dict:
    config = SmokeConfig.from_file(config_path)
    spec = TensorSpec(config.input_size[0], config.input_size[1])
    model = build_model(architecture, seed=config.seed)
    freeze_feature_extractor(model, architecture)
    if architecture == "mobilenet_v3_small":
        tracked_parameter = model.classifier[-1].weight
    else:
        tracked_parameter = model.crop_head.weight
    before = tracked_parameter.detach().clone()
    labels: list[int | None] = list(range(7))
    if architecture == "resnet18_hierarchical":
        labels.append(None)
    training = [(fixture_image(label), label) for label in labels]
    if architecture == "resnet18_hierarchical":
        losses = train_fixture_hierarchical_heads(model, training, spec,
                                                 steps=config.hierarchical_steps,
                                                 learning_rate=config.hierarchical_learning_rate)
    else:
        losses = [train_fixture_epoch(model, architecture, training, spec,
                                      learning_rate=config.learning_rate, seed=config.seed + epoch)
                  for epoch in range(config.epochs)]
    if torch_equal(before, tracked_parameter.detach()):
        raise RuntimeError("El optimizador no actualizó pesos reales")
    validation = [(fixture_image(label, variant=1), label) for label in labels]
    policy = select_fixture_crop_policy(model, validation, spec) if architecture == "resnet18_hierarchical" else None
    manifest = save_fixture_checkpoint(model, architecture, spec, output_dir,
                                       seed=config.seed, train_loss=losses[-1],
                                       train_samples=len(training), crop_policy=policy)
    reloaded, metadata, reloaded_spec = load_fixture_checkpoint(manifest)
    sample = fixture_image(0, variant=1)
    train_tensor = image_to_tensor(sample, spec, split="VAL")
    inference_tensor = image_to_tensor(sample, reloaded_spec, split="INFERENCE")
    if not torch_equal(train_tensor, inference_tensor):
        raise RuntimeError("Preprocesado divergente entre entrenamiento e inferencia")
    prediction = predict_image(reloaded, architecture, sample, reloaded_spec, crop_policy=policy)
    report = {
        "status": "TECHNICAL_FIXTURE_ONLY", "g0_approved": False, "g2_approved": False,
        "architecture": architecture, "seed": config.seed, "losses": losses,
        "weights_changed": True, "tensor_equivalent": True,
        "checkpoint": str(manifest), "weights_sha256": metadata["weights"]["sha256"],
        "prediction": prediction, "fixture_crop_policy": policy.to_dict() if policy else None,
        "preprocessing_cpu": measure_cpu_preprocessing(sample, spec),
    }
    report_path = Path(output_dir) / "smoke-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def torch_equal(left, right) -> bool:
    return bool(torch.equal(left, right))


def infer_fixture_checkpoint(manifest: Path, image_bytes: bytes) -> dict:
    model, metadata, spec = load_fixture_checkpoint(manifest)
    policy_data = metadata.get("fixture_crop_policy")
    policy = CropPolicy(policy_data["min_crop_score"], policy_data["min_margin"],
                        policy_data["selected_on"]) if policy_data else None
    return predict_image(model, metadata["architecture"], image_bytes, spec, crop_policy=policy)


def evaluate_fixture_checkpoint(manifest: Path) -> dict:
    """Evalúa el recorrido técnico en VAL_FIXTURE, jamás en TEST agronómico."""
    model, metadata, spec = load_fixture_checkpoint(manifest)
    policy_data = metadata.get("fixture_crop_policy")
    if metadata["architecture"] == "resnet18_hierarchical" and not policy_data:
        raise ValueError("Falta política técnica de cultivo")
    policy = CropPolicy(policy_data["min_crop_score"], policy_data["min_margin"],
                        policy_data["selected_on"]) if policy_data else None
    cases = []
    for label in [*range(7), None]:
        result = predict_image(model, metadata["architecture"], fixture_image(label, variant=1), spec,
                               crop_policy=policy)
        expected = None if label is None else CLASS_MAPPING[label]["class_code"]
        cases.append({"fixture_label": "OTHER" if label is None else label,
                      "expected_class_code": expected, "status": result["status"],
                      "predicted_class_code": result["class_code"],
                      "reason_code": result["reason_code"]})
    return {
        "schema_version": 1, "status": "TECHNICAL_FIXTURE_ONLY", "scope": "VAL_FIXTURE_ONLY",
        "approval": None, "selected_for_release": None, "g0_approved": False, "g2_approved": False,
        "architecture": metadata["architecture"], "weights_sha256": metadata["weights"]["sha256"],
        "correct_positive_patterns_of_7": sum(case["predicted_class_code"] == case["expected_class_code"]
                                              for case in cases if case["fixture_label"] != "OTHER"),
        "rejected_negative_patterns_of_1": int(cases[-1]["status"] == "ABSTENTION"),
        "cases": cases,
    }


def package_fixture_checkpoint(manifest: Path, evaluation_path: Path, output: Path) -> dict:
    """Archiva pesos y evaluación de fixture con nombres fijos; no crea bundle G2."""
    manifest = Path(manifest)
    evaluation_path = Path(evaluation_path)
    output = Path(output)
    if manifest.is_symlink() or evaluation_path.is_symlink():
        raise ValueError("Rutas simbólicas no permitidas")
    if evaluation_path.stat().st_size > 1024 * 1024:
        raise ValueError("Evaluación de fixture excesiva")
    _, metadata, _ = load_fixture_checkpoint(manifest)
    expected = evaluate_fixture_checkpoint(manifest)
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    if evaluation != expected:
        raise ValueError("Evaluación de fixture ausente, alterada o de otro checkpoint")
    weights = manifest.parent / metadata["weights"]["filename"]
    if output.exists() or output.is_symlink():
        raise ValueError("El archivo de salida ya existe")
    files = {
        "fixture-checkpoint.json": manifest.read_bytes(),
        "fixture-weights.safetensors": weights.read_bytes(),
        "fixture-evaluation.json": evaluation_path.read_bytes(),
    }
    index = {
        "schema_version": 1, "status": "FIXTURE_ONLY", "approval": None,
        "selected_for_release": None, "scope": "VAL_FIXTURE_ONLY",
        "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with zipfile.ZipFile(output, mode="x", compression=zipfile.ZIP_STORED) as archive:
            created = True
            for name, data in files.items():
                archive.writestr(name, data)
            archive.writestr("fixture-index.json", json.dumps(index, sort_keys=True, indent=2) + "\n")
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    return {"status": "TECHNICAL_FIXTURE_ONLY", "package": str(output),
            "weights_sha256": metadata["weights"]["sha256"], "selected_for_release": None}


def compare_fixture_models(joint_manifest: Path, hierarchical_manifest: Path) -> dict:
    """Comparación VAL_FIXTURE técnica; nunca selecciona release agronómico."""
    joint_model, joint_meta, joint_spec = load_fixture_checkpoint(joint_manifest)
    hier_model, hier_meta, hier_spec = load_fixture_checkpoint(hierarchical_manifest)
    if joint_meta["architecture"] != "mobilenet_v3_small" or hier_meta["architecture"] != "resnet18_hierarchical":
        raise ValueError("Se requieren ambos checkpoints técnicos correspondientes")
    policy_data = hier_meta.get("fixture_crop_policy")
    if not policy_data or policy_data.get("selected_on") != "VAL_FIXTURE":
        raise ValueError("La alternativa no tiene política seleccionada en VAL_FIXTURE")
    policy = CropPolicy(policy_data["min_crop_score"], policy_data["min_margin"], "VAL_FIXTURE")
    results = {}
    for name, model, architecture, spec, crop_policy in (
        ("joint", joint_model, "mobilenet_v3_small", joint_spec, None),
        ("hierarchical", hier_model, "resnet18_hierarchical", hier_spec, policy),
    ):
        correct_classes = accepted_positives = negative_rejections = 0
        for label in [*range(7), None]:
            prediction = predict_image(model, architecture, fixture_image(label, variant=1), spec,
                                       crop_policy=crop_policy)
            if label is None:
                negative_rejections += prediction["status"] == "ABSTENTION"
            else:
                accepted_positives += prediction["status"] == "PREDICTION"
                correct_classes += prediction["class_code"] == CLASS_MAPPING[label]["class_code"]
        results[name] = {
            "correct_classes_of_7": correct_classes,
            "accepted_positives_of_7": accepted_positives,
            "negative_rejections_of_1": negative_rejections,
            "technical_correct_of_8": correct_classes + negative_rejections,
        }
    winner = max(results, key=lambda name: (results[name]["technical_correct_of_8"],
                                             results[name]["accepted_positives_of_7"]))
    return {
        "scope": "VAL_FIXTURE_ONLY", "g0_approved": False, "g2_approved": False,
        "selected_for_release": None, "technical_fixture_winner": winner,
        "results": results,
    }
