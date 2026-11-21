"""Build and independently verify the private G2 potato-pilot release.

This loader is separate from the historical JSON-weight fixture loader. It
never reads TEST images or manifests and does not activate the real worker.
"""

from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import sys
import uuid

import jsonschema
from PIL import Image
import torch
from torch import nn
from safetensors.torch import load_file
from torchvision.models import mobilenet_v3_small

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.pilot_selection import verify_freeze


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "contracts/ml/model-bundle.v1.schema.json"
CLASSES = ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT")
COMPONENTS = ("pilot-weights.safetensors", "config.json", "calibration.json",
              "thresholds.json", "protocol-g0.json", "freeze.json", "test-report.json",
              "test-access.json", "comparison.json", "calibrated-val-report.json")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def combined_manifest_digest(pair: dict) -> str:
    if set(pair) != {"positives", "negatives"} or any(
            not isinstance(value, str) or len(value) != 64 or
            any(char not in "0123456789abcdef" for char in value) for value in pair.values()):
        raise ValueError("Par de manifiestos inválido")
    return hashlib.sha256(json.dumps(pair, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _groupnorm_model(seed: int) -> nn.Module:
    # Construct independently of pilot_training.build_model, but with the same
    # frozen architecture and layer replacement. No pretrained download.
    torch.manual_seed(seed)
    model = mobilenet_v3_small(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 3)

    def replace(module: nn.Module) -> None:
        for name, child in module.named_children():
            if isinstance(child, nn.BatchNorm2d):
                count = min(32, child.num_features)
                while child.num_features % count:
                    count -= 1
                setattr(module, name, nn.GroupNorm(count, child.num_features))
            else:
                replace(child)

    replace(model)
    return model.cpu().eval()


def validate_finite_state(state: dict[str, torch.Tensor]) -> None:
    if not state or any(not bool(torch.isfinite(value).all()) for value in state.values()):
        raise ValueError("Pesos no finitos o ausentes")


def build_pilot_bundle(review_dir: Path, freeze_path: Path, experiment_path: Path,
                       expected_review_sha256: str, output_dir: Path,
                       approval_id: str, approved_at: str) -> dict:
    """Stage a schema-valid bundle; actual G2 approval follows independent load."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if digest(review_dir / "review-manifest.json") != expected_review_sha256:
        raise ValueError("Expediente privado de revisión alterado")
    review = _load(review_dir / "review-manifest.json")
    if review.get("status") != "READY_FOR_G2_REVIEW_UNAPPROVED" or not review.get("g0_numeric_pass"):
        raise ValueError("Expediente aún no elegible para G2")
    for name, expected in review["file_sha256"].items():
        if digest(review_dir / name) != expected:
            raise ValueError("Componente de revisión alterado: " + name)
    verify_freeze(freeze_path)
    freeze = _load(freeze_path)
    if (digest(review_dir / "freeze.json") != digest(freeze_path)
            or digest(experiment_path) != freeze["source_experiment_sha256"]
            or review["file_sha256"]["test-report.json"] != "b10a6654d64c56e6967f51de28ede65924813b5da8684319ffc16788d71e4e96"):
        raise ValueError("Revisión, experimento o reporte TEST no coinciden")
    experiment = _load(experiment_path)
    report = _load(review_dir / "test-report.json")
    config = _load(review_dir / "config.json")
    calibration = _load(review_dir / "calibration.json")
    thresholds = _load(review_dir / "thresholds.json")
    if (not report.get("g0_numeric_pass") or report.get("g2_approval") is not None
            or report["provenance"]["freeze_sha256"] != digest(freeze_path)
            or review["published_class_map"] != {"0": CLASSES[0], "1": CLASSES[1]}
            or config["architecture"] != "mobilenet_v3_small"
            or config["class_codes"] != list(CLASSES)
            or thresholds["per_class"] != {code: .5 for code in CLASSES}
            or calibration["selected_on"] != "VAL"
            or experiment["runtime"]["torch"] != torch.__version__):
        raise ValueError("Configuración o resultados TEST no coinciden con el piloto")
    output_dir.mkdir(parents=True, exist_ok=False)
    for name in COMPONENTS:
        source = review_dir / name if (review_dir / name).is_file() else freeze_path.parent / name
        if name == "pilot-weights.safetensors":
            source = review_dir / "weights.safetensors"
        shutil.copyfile(source, output_dir / name)
    verify_freeze(output_dir / "freeze.json")
    manifest_pairs = review["manifest_sha256"]
    bundle = {
        "schema_version": 1,
        "bundle_id": str(uuid.uuid5(uuid.NAMESPACE_URL, digest(freeze_path) + digest(review_dir / "test-report.json"))),
        "model_id": review["model_id"], "model_version": "0.1.0-pilot",
        "dataset_version": "1.2.0-pv-color", "architecture": "mobilenet_v3_small",
        "weights": {"filename": "pilot-weights.safetensors", "sha256": digest(output_dir / "pilot-weights.safetensors"),
                    "format": "safetensors", "size_bytes": (output_dir / "pilot-weights.safetensors").stat().st_size},
        "manifest_checksums": {f"{split}_manifest_sha256": combined_manifest_digest(manifest_pairs[split])
                               for split in ("train", "val", "test")},
        "manifest_component_checksums": manifest_pairs,
        "artifact_checksums": {
            "config_sha256": digest(output_dir / "config.json"),
            "calibration_sha256": digest(output_dir / "calibration.json"),
            "thresholds_sha256": digest(output_dir / "thresholds.json"),
            "protocol_sha256": digest(output_dir / "protocol-g0.json"),
            "freeze_sha256": digest(output_dir / "freeze.json"),
            "test_report_sha256": digest(output_dir / "test-report.json"),
            "preprocessing_code_sha256": freeze["preprocessing_code_sha256"],
            "dependency_lock_sha256": freeze["dependency_lock_sha256"]},
        "class_map": {str(index): {"class_code": code, "crop_code": "POTATO"}
                      for index, code in enumerate(CLASSES)},
        "preprocessing": {key: config["preprocessing"][key]
                          for key in ("input_size", "channels", "color_space", "mean", "std")},
        "rejection_components": {"min_confidence_threshold": .5,
                                 "identified_crop_required": "POTATO",
                                 "technical_reject_policy": "OTHER_CROP_LOGIT_GTE_CANDIDATE",
                                 "min_dimension": config["preprocessing"]["min_dimension"],
                                 "max_dimension": config["preprocessing"]["max_dimension"]},
        "calibration": {"method": "PLATT_SCALING",
                        "parameters_per_class": {code: {"slope": calibration["class_parameters"][code]["slope"],
                                                         "intercept": calibration["class_parameters"][code]["intercept"]}
                                                 for code in CLASSES}},
        "runtime_environment": {"python_version": experiment["runtime"]["python"],
                                "framework": "pytorch", "framework_version": experiment["runtime"]["torch"],
                                "target_device": "cpu"},
        "governance": {"g0_protocol_version": "1.2.0", "g2_approval_id": approval_id,
                       "approved_by": "PROJECT_OWNER", "approved_at": approved_at},
    }
    jsonschema.Draft202012Validator(_load(SCHEMA), format_checker=jsonschema.FormatChecker()).validate(bundle)
    target = output_dir / "model-bundle.json"
    target.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"bundle": str(target), "sha256": digest(target), "status": "STAGED_FOR_INDEPENDENT_LOAD"}


def load_pilot_bundle(bundle_path: Path, expected_bundle_sha256: str,
                      *, require_approval_record: bool = False) -> tuple[nn.Module, dict, dict]:
    """Independent fail-closed load of the actual safetensors release."""
    directory = bundle_path.parent.resolve(strict=True)
    if bundle_path.is_symlink() or not bundle_path.is_file() or digest(bundle_path) != expected_bundle_sha256:
        raise ValueError("SHA-256 de bundle no coincide con el registrado")
    bundle = _load(bundle_path)
    jsonschema.Draft202012Validator(_load(SCHEMA), format_checker=jsonschema.FormatChecker()).validate(bundle)
    if (bundle["governance"]["g0_protocol_version"] != "1.2.0"
            or bundle["governance"]["approved_by"] != "PROJECT_OWNER"
            or bundle["architecture"] != "mobilenet_v3_small"
            or bundle["class_map"] != {str(index): {"class_code": code, "crop_code": "POTATO"}
                                       for index, code in enumerate(CLASSES)}
            or bundle["rejection_components"]["identified_crop_required"] != "POTATO"
            or bundle["rejection_components"]["technical_reject_policy"] != "OTHER_CROP_LOGIT_GTE_CANDIDATE"
            or bundle["rejection_components"]["min_confidence_threshold"] != .5
            or bundle["weights"]["format"] != "safetensors"
            or bundle["runtime_environment"]["framework"] != "pytorch"
            or bundle["runtime_environment"]["framework_version"] != torch.__version__
            or bundle["runtime_environment"]["target_device"] != "cpu"
            or tuple(map(int, bundle["runtime_environment"]["python_version"].split(".")[:2])) != sys.version_info[:2]):
        raise ValueError("Alcance o decisión de publicación fuera del piloto")
    filename = bundle["weights"]["filename"]
    if filename != "pilot-weights.safetensors":
        raise ValueError("Nombre de pesos inesperado")
    for name, expected in {
        filename: bundle["weights"]["sha256"],
        "config.json": bundle["artifact_checksums"]["config_sha256"],
        "calibration.json": bundle["artifact_checksums"]["calibration_sha256"],
        "thresholds.json": bundle["artifact_checksums"]["thresholds_sha256"],
        "protocol-g0.json": bundle["artifact_checksums"]["protocol_sha256"],
        "freeze.json": bundle["artifact_checksums"]["freeze_sha256"],
        "test-report.json": bundle["artifact_checksums"]["test_report_sha256"],
    }.items():
        target = directory / name
        if target.is_symlink() or not target.is_file() or target.resolve().parent != directory or digest(target) != expected:
            raise ValueError("Componente ausente o alterado: " + name)
    if (bundle["weights"]["size_bytes"] != (directory / filename).stat().st_size
            or digest(ROOT / "ml/src/agro_ml/data/tensor_preprocessing.py") !=
            bundle["artifact_checksums"]["preprocessing_code_sha256"]
            or digest(ROOT / "ml/uv.lock") != bundle["artifact_checksums"]["dependency_lock_sha256"]):
        raise ValueError("Tamaño, preprocesado o dependencias alterados")
    verify_freeze(directory / "freeze.json")
    freeze = _load(directory / "freeze.json")
    report = _load(directory / "test-report.json")
    config = _load(directory / "config.json")
    calibration = _load(directory / "calibration.json")
    thresholds = _load(directory / "thresholds.json")
    protocol = _load(directory / "protocol-g0.json")
    if (freeze["file_sha256"]["pilot-weights.safetensors"] != bundle["weights"]["sha256"]
            or report.get("provenance", {}).get("freeze_sha256") != digest(directory / "freeze.json")
            or report["provenance"]["weights_sha256"] != bundle["weights"]["sha256"]
            or report.get("dataset_split") != "TEST" or not report.get("g0_numeric_pass")
            or any(not item["passed"] for item in report["g0_checks"].values())
            or report.get("external", {}).get("status") != "NOT_AVAILABLE"
            or report.get("full_flow_latency", {}).get("status") != "NOT_MEASURED"
            or protocol.get("protocol_version") != "1.2.0"
            or config.get("class_codes") != list(CLASSES)
            or config.get("architecture") != bundle["architecture"]
            or config.get("normalization") != "GROUP_NORM"
            or {key: config["preprocessing"][key] for key in bundle["preprocessing"]} != bundle["preprocessing"]
            or thresholds.get("status") != "LOCKED_BEFORE_TEST"
            or thresholds.get("per_class") != {code: .5 for code in CLASSES}
            or calibration.get("selected_on") != "VAL"
            or bundle["calibration"]["parameters_per_class"] != {
                code: {"slope": calibration["class_parameters"][code]["slope"],
                       "intercept": calibration["class_parameters"][code]["intercept"]}
                for code in CLASSES}):
        raise ValueError("Bundle no reproduce configuración o TEST congelado")
    for split in ("train", "val", "test"):
        pair = bundle["manifest_component_checksums"][split]
        if bundle["manifest_checksums"][f"{split}_manifest_sha256"] != combined_manifest_digest(pair):
            raise ValueError("Digest de manifiestos incompatible")
        expected = (freeze[f"{split}_manifest_sha256"] if split != "test"
                    else report["provenance"]["test_manifest_sha256"])
        if pair != expected:
            raise ValueError("Manifiestos distintos del entrenamiento o TEST sellado")
    if require_approval_record:
        approval_path = directory / "g2-approval.json"
        if approval_path.is_symlink() or not approval_path.is_file():
            raise ValueError("Acta G2 ausente")
        approval = _load(approval_path)
        if (approval.get("status") != "APPROVED_G2" or approval.get("bundle_sha256") != expected_bundle_sha256
                or approval.get("approval_id") != bundle["governance"]["g2_approval_id"]
                or approval.get("approved_at") != bundle["governance"]["approved_at"]
                or approval.get("protocol_version") != "1.2.0"
                or approval.get("test_report_sha256") != digest(directory / "test-report.json")):
            raise ValueError("Acta G2 no coincide con bundle o TEST")
    state = load_file(str(directory / filename), device="cpu")
    validate_finite_state(state)
    model = _groupnorm_model(config["seed"])
    model.load_state_dict(state, strict=True)
    return model, bundle, report


def synthetic_inference_check(model: nn.Module, bundle: dict) -> dict:
    """Use generated pixels, not TEST or a user image, to check the loaded path."""
    config_size = bundle["preprocessing"]["input_size"]
    image = Image.new("RGB", (max(224, config_size[0]), max(224, config_size[1])), (92, 146, 75))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    rejection = bundle["rejection_components"]
    spec = TensorSpec(config_size[0], config_size[1], rejection["min_dimension"],
                      rejection["max_dimension"], tuple(bundle["preprocessing"]["mean"]),
                      tuple(bundle["preprocessing"]["std"]))
    tensor = image_to_tensor(stream.getvalue(), spec, split="INFERENCE").unsqueeze(0)
    with torch.inference_mode():
        probs = torch.softmax(model(tensor), dim=1)[0].tolist()
    if len(probs) != 3 or any(not math.isfinite(value) for value in probs):
        raise ValueError("Salida técnica no finita")
    candidate = max(range(2), key=lambda index: probs[index])
    code = bundle["class_map"][str(candidate)]["class_code"]
    params = bundle["calibration"]["parameters_per_class"][code]
    clipped = min(max(probs[candidate], 1e-6), 1 - 1e-6)
    z = params["slope"] * math.log(clipped / (1 - clipped)) + params["intercept"]
    calibrated = 1 / (1 + math.exp(-max(-40, min(40, z))))
    published = (code if probs[2] < probs[candidate] and
                 calibrated >= rejection["min_confidence_threshold"] else None)
    if published is not None and published not in CLASSES:
        raise ValueError("Clase publicada fuera de alcance")
    return {"scope": "SYNTHETIC_LOAD_CHECK_NOT_AGRONOMIC_EVIDENCE",
            "technical_output_count": 3, "published_class_map": list(CLASSES),
            "result": published or "NO_CONCLUYENTE",
            "calibration_applied": True, "identified_crop_required": "POTATO"}
