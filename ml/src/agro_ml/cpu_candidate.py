"""CPU candidate workflow. Its outputs are never a G2 release or published diagnosis."""

import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import tempfile
import zipfile

import torch
from torch.nn import functional as F
from safetensors.torch import load_file, save_file

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.evaluation.metrics import generate_evaluation_report
from agro_ml.models.architectures import CLASS_MAPPING
from agro_ml.models.torch_cpu import build_model


CLASS_CODES = tuple(CLASS_MAPPING[i]["class_code"] for i in range(7))
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_WEIGHTS_BYTES = 100 * 1024 * 1024


def write_fixture_manifests(output_dir: Path) -> dict:
    """Generate explicit graphical fixtures for a reproducible CLI walkthrough."""
    from agro_ml.smoke import fixture_image

    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        image_dir = output_dir / "images"
        image_dir.mkdir()
        paths = {}
        for split, variant in (("TRAIN", 0), ("VAL", 1)):
            records = []
            for label in (0, 3):
                raw = fixture_image(label, variant=variant)
                name = f"{split.lower()}-{label}.png"
                (image_dir / name).write_bytes(raw)
                records.append({"relative_path": name, "sha256": digest_bytes(raw),
                                "class_code": CLASS_CODES[label], "split_group": f"{split}-{label}"})
            path = output_dir / f"{split.lower()}.json"
            path.write_text(json.dumps({"schema_version": 1, "scope": "FIXTURE_ONLY",
                                        "dataset_version": "0.0.0-fixture", "split": split,
                                        "records": records}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            paths[split] = str(path)
        return {"status": "FIXTURE_ONLY", "images_root": str(image_dir), "manifests": paths}
    except Exception:
        shutil.rmtree(output_dir)
        raise


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_config(path: Path) -> tuple[dict, TensorSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("purpose") != "CPU_CANDIDATE_ONLY":
        raise ValueError("Configuración de candidato inválida")
    if data.get("architecture") != "mobilenet_v3_small" or data.get("base_weights") != "RANDOM_INITIALIZATION":
        raise ValueError("Arquitectura o procedencia de pesos no permitida")
    if type(data.get("seed")) is not int or data["seed"] < 0:
        raise ValueError("Semilla inválida")
    if type(data.get("epochs")) is not int or not 1 <= data["epochs"] <= 100:
        raise ValueError("Épocas inválidas")
    lr = data.get("learning_rate")
    if isinstance(lr, bool) or not isinstance(lr, (int, float)) or not math.isfinite(lr) or not 0 < lr <= .1:
        raise ValueError("Tasa de aprendizaje inválida")
    size = data.get("input_size")
    if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int for n in size):
        raise ValueError("Tamaño de tensor inválido")
    return data, TensorSpec(*size)


def read_manifest(path: Path, root: Path, split: str) -> tuple[dict, list[tuple[Path, int, str]], set[str], set[str]]:
    """Read only explicit local files; verify bytes, labels, split and admission evidence."""
    document = json.loads(path.read_text(encoding="utf-8"))
    scope = document.get("scope")
    if document.get("schema_version") != 1 or scope not in {"FIXTURE_ONLY", "G1_ADMITTED"}:
        raise ValueError("Alcance de manifiesto inválido")
    if document.get("split") != split or not isinstance(document.get("dataset_version"), str) or not document["dataset_version"]:
        raise ValueError("Partición o versión inválida")
    if scope == "G1_ADMITTED" and not document.get("g1_evidence_ref"):
        raise ValueError("Falta referencia de admisión G1")
    records = document.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Manifiesto vacío")
    if len(records) > 100000:
        raise ValueError("Manifiesto excesivo")
    root = root.resolve(strict=True)
    samples: list[tuple[Path, int, str]] = []
    hashes: set[str] = set()
    groups: set[str] = set()
    for row in records:
        if not isinstance(row, dict) or row.get("class_code") not in CLASS_CODES:
            raise ValueError("Clase de manifiesto inválida")
        relative = row.get("relative_path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Ruta de imagen insegura")
        target = root / relative
        resolved = target.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file() or target.is_symlink():
            raise ValueError("Imagen fuera del directorio privado")
        if not 100 <= resolved.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("Tamaño de imagen inválido")
        raw = resolved.read_bytes()
        digest = digest_bytes(raw)
        if row.get("sha256") != digest or digest in hashes:
            raise ValueError("Hash ausente, alterado o duplicado")
        group = row.get("split_group")
        if not isinstance(group, str) or not group:
            raise ValueError("Grupo de separación ausente")
        if scope == "G1_ADMITTED" and not all(row.get(key) for key in ("rights_evidence_ref", "label_review_ref")):
            raise ValueError("Imagen sin evidencia de derechos o revisión G1")
        image_to_tensor(raw, TensorSpec(64, 64), split="VAL")  # Decodificación obligatoria.
        hashes.add(digest)
        groups.add(group)
        samples.append((resolved, CLASS_CODES.index(row["class_code"]), digest))
    return document, samples, hashes, groups


def _load_candidate(checkpoint: Path) -> tuple[torch.nn.Module, dict, TensorSpec]:
    metadata = json.loads(checkpoint.read_text(encoding="utf-8"))
    if metadata.get("status") not in {"FIXTURE_ONLY", "UNAPPROVED_CANDIDATE"} or metadata.get("approval") is not None:
        raise ValueError("Checkpoint no es candidato CPU")
    if metadata.get("architecture") != "mobilenet_v3_small":
        raise ValueError("Arquitectura incompatible")
    info = metadata.get("weights", {})
    if info.get("filename") != "candidate-weights.safetensors":
        raise ValueError("Nombre de pesos inseguro")
    path = checkpoint.parent / info["filename"]
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_WEIGHTS_BYTES:
        raise ValueError("Pesos ausentes o inválidos")
    if digest_bytes(path.read_bytes()) != info.get("sha256"):
        raise ValueError("Pesos alterados")
    spec = TensorSpec.from_dict(metadata["preprocessing"])
    model = build_model("mobilenet_v3_small", seed=metadata["seed"])
    state = load_file(str(path), device="cpu")
    if not all(bool(torch.isfinite(tensor).all()) for tensor in state.values()):
        raise ValueError("Pesos no finitos")
    model.load_state_dict(state, strict=True)
    model.eval()
    return model, metadata, spec


def train(config_path: Path, manifest_path: Path, image_root: Path, output_dir: Path) -> dict:
    config, spec = read_config(config_path)
    manifest, samples, _, _ = read_manifest(manifest_path, image_root, "TRAIN")
    torch.manual_seed(config["seed"])
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    model = build_model("mobilenet_v3_small", seed=config["seed"])
    model.eval()  # BatchNorm determinista; se optimiza la cabeza para el candidato CPU.
    for parameter in model.features.parameters():
        parameter.requires_grad_(False)
    optimizer = torch.optim.SGD(model.classifier.parameters(), lr=config["learning_rate"])
    losses: list[float] = []
    for epoch in range(config["epochs"]):
        order = list(range(len(samples)))
        random.Random(config["seed"] + epoch).shuffle(order)
        for index in order:
            image_path, label, expected_hash = samples[index]
            raw = image_path.read_bytes()
            if digest_bytes(raw) != expected_hash:
                raise ValueError("Imagen TRAIN alterada después de verificar manifiesto")
            tensor = image_to_tensor(raw, spec, split="TRAIN").unsqueeze(0)
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(tensor), torch.tensor([label], dtype=torch.long))
            if not bool(torch.isfinite(loss)):
                raise ValueError("Pérdida no finita")
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        weights = output_dir / "candidate-weights.safetensors"
        save_file({name: value.detach().cpu().contiguous() for name, value in model.state_dict().items()}, str(weights))
        metadata = {
            "schema_version": 1,
            "status": "FIXTURE_ONLY" if manifest["scope"] == "FIXTURE_ONLY" else "UNAPPROVED_CANDIDATE",
            "approval": None, "selected_for_release": None,
            "architecture": "mobilenet_v3_small", "seed": config["seed"],
            "dataset_scope": manifest["scope"], "dataset_version": manifest["dataset_version"],
            "train_manifest_sha256": digest_bytes(manifest_path.read_bytes()),
            "config_sha256": digest_bytes(config_path.read_bytes()),
            "preprocessing": spec.to_dict(), "train_count": len(samples), "losses": losses,
            "base_weights": {"source": "RANDOM_INITIALIZATION", "downloaded": False, "pretrained": False},
            "runtime": {"device": "cpu", "torch": torch.__version__},
            "weights": {"filename": weights.name, "sha256": digest_bytes(weights.read_bytes())},
        }
        checkpoint = output_dir / "candidate-checkpoint.json"
        checkpoint.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _load_candidate(checkpoint)
    except Exception:
        shutil.rmtree(output_dir)
        raise
    return {"checkpoint": str(checkpoint), "status": metadata["status"],
            "weights_sha256": metadata["weights"]["sha256"], "train_count": len(samples)}


def evaluate_val(checkpoint: Path, train_manifest: Path, val_manifest: Path, image_root: Path, output: Path) -> dict:
    model, metadata, spec = _load_candidate(checkpoint)
    if digest_bytes(train_manifest.read_bytes()) != metadata["train_manifest_sha256"]:
        raise ValueError("Manifiesto TRAIN alterado")
    train_doc, _, train_hashes, train_groups = read_manifest(train_manifest, image_root, "TRAIN")
    val_doc, samples, val_hashes, val_groups = read_manifest(val_manifest, image_root, "VAL")
    if train_doc["scope"] != val_doc["scope"] or val_doc["scope"] != metadata["dataset_scope"]:
        raise ValueError("Alcance de datos incompatible")
    if train_doc["dataset_version"] != val_doc["dataset_version"] or val_doc["dataset_version"] != metadata["dataset_version"]:
        raise ValueError("Versión de datos incompatible")
    if train_hashes & val_hashes or train_groups & val_groups:
        raise ValueError("Fuga entre TRAIN y VAL")
    truth, pred, scores = [], [], []
    with torch.inference_mode():
        for image_path, label, expected_hash in samples:
            raw = image_path.read_bytes()
            if digest_bytes(raw) != expected_hash:
                raise ValueError("Imagen VAL alterada después de verificar manifiesto")
            logits = model(image_to_tensor(raw, spec, split="VAL").unsqueeze(0)).squeeze(0)
            probs = torch.softmax(logits, dim=0)
            truth.append(label)
            pred.append(int(torch.argmax(probs)))
            scores.append(float(torch.max(probs)))
    metrics = generate_evaluation_report("VAL", truth, pred, scores, list(CLASS_CODES)).to_dict()
    metrics.pop("evaluated_at")  # Salida byte a byte reproducible para las mismas entradas.
    report = {"schema_version": 1, "status": metadata["status"], "scope": "VAL_ONLY",
              "approval": None, "selected_for_release": None,
              "checkpoint_sha256": digest_bytes(checkpoint.read_bytes()),
              "weights_sha256": metadata["weights"]["sha256"],
              "val_manifest_sha256": digest_bytes(val_manifest.read_bytes()),
              "metrics": metrics}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return {"output": str(output), "status": report["status"], "scope": report["scope"]}


def package_candidate(checkpoint: Path, evaluation: Path, output: Path,
                      train_manifest: Path, val_manifest: Path, image_root: Path) -> dict:
    _, metadata, _ = _load_candidate(checkpoint)
    report = json.loads(evaluation.read_text(encoding="utf-8"))
    if report.get("status") != metadata["status"] or report.get("scope") != "VAL_ONLY":
        raise ValueError("Evaluación incompatible")
    if report.get("checkpoint_sha256") != digest_bytes(checkpoint.read_bytes()):
        raise ValueError("Evaluación de otro checkpoint")
    if report.get("weights_sha256") != metadata["weights"]["sha256"]:
        raise ValueError("Evaluación de otros pesos")
    if report.get("approval") is not None or report.get("selected_for_release") is not None:
        raise ValueError("No se admite promoción en paquete candidato")
    with tempfile.TemporaryDirectory(prefix="agro-candidate-check-") as directory:
        expected_path = Path(directory) / "evaluation.json"
        evaluate_val(checkpoint, train_manifest, val_manifest, image_root, expected_path)
        if json.loads(expected_path.read_text(encoding="utf-8")) != report:
            raise ValueError("Evaluación VAL alterada o incompatible con entradas locales")
    if output.exists() or output.is_symlink():
        raise ValueError("Paquete ya existe")
    files = {"candidate-checkpoint.json": checkpoint.read_bytes(),
             "candidate-weights.safetensors": (checkpoint.parent / "candidate-weights.safetensors").read_bytes(),
             "candidate-evaluation.json": evaluation.read_bytes()}
    index = {"schema_version": 1, "status": metadata["status"], "scope": "VAL_ONLY",
             "approval": None, "selected_for_release": None,
             "files_sha256": {name: digest_bytes(raw) for name, raw in files.items()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(output, mode="x", compression=zipfile.ZIP_STORED) as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
            archive.writestr("candidate-index.json", json.dumps(index, indent=2, sort_keys=True) + "\n")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {"package": str(output), "status": metadata["status"], "selected_for_release": None}
