"""Fail-closed checks for private, per-image G1 evidence; never grants rights itself."""

from datetime import date
import hashlib
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 15 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _review_date(value):
    _require(isinstance(value, str), "fecha de revisión ausente")
    try:
        reviewed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("fecha de revisión inválida") from exc
    _require(reviewed <= date.today(), "fecha de revisión futura")


def _private_file(root, relative, kind):
    _require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
             and ".." not in Path(relative).parts, f"{kind}: ruta insegura")
    root = Path(root).resolve(strict=True)
    target = root / relative
    resolved = target.resolve(strict=True)
    _require(resolved.is_relative_to(root) and resolved.is_file() and not target.is_symlink(),
             f"{kind}: archivo fuera de raíz privada")
    return resolved


def load_evidence(path):
    """Read a versioned private registry; each admitted row must have one decision."""
    path = Path(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    _require(document.get("schema_version") == 1 and isinstance(document.get("records"), list),
             "registro G1 inválido")
    records = {}
    for record in document["records"]:
        _require(isinstance(record, dict) and isinstance(record.get("image_id"), str)
                 and record["image_id"] and record["image_id"] not in records,
                 "registro G1: image_id vacío o duplicado")
        records[record["image_id"]] = record
        _require(record.get("decision") in {"ADMIT", "EXCLUDE", "PENDING"},
                 "registro G1: decisión inválida")
        _require(isinstance(record.get("decision_by"), str) and record["decision_by"].strip()
                 and isinstance(record.get("decision_reason"), str) and record["decision_reason"].strip(),
                 "registro G1: falta responsable o motivo de decisión")
        _review_date(record.get("decision_at"))
    return records, path.parent


def validate_image_evidence(row, record, evidence_root, images_root, source, *, negative=False):
    """Bind reviewed rights and labels to the exact local bytes and intended use."""
    image_id = row["image_id"]
    _require(isinstance(record, dict), f"{image_id}: falta decisión privada por imagen")
    _require(record.get("decision") == "ADMIT", f"{image_id}: imagen no admitida en registro privado")
    for key in ("image_id", "sha256", "source", "split_group"):
        _require(record.get(key) == row[key], f"{image_id}: evidencia G1 no coincide en {key}")
    _require(record.get("source_revision") == source.get("version"),
             f"{image_id}: revisión de fuente no coincide")
    _require(source.get("eligibility") == "ELIGIBLE" and
             source.get("license", {}).get("status") == "VERIFIED_FOR_PROJECT",
             f"{image_id}: fuente pendiente o permiso no verificado")
    _require(row["license"] == source["license"]["identifier"], f"{image_id}: licencia no coincide")
    _require(row["capture_context"] == source["capture_context"],
             f"{image_id}: contexto de captura no coincide")

    rights = record.get("rights")
    _require(isinstance(rights, dict) and rights.get("decision") == "APPROVED",
             f"{image_id}: imagen sin permiso aprobado")
    use = "TRAINING" if row["split"] == "TRAIN" else "EVALUATION"
    _require(isinstance(rights.get("allowed_uses"), list) and use in rights["allowed_uses"],
             f"{image_id}: permiso no cubre {use}")
    for key in ("reviewer", "attribution", "restrictions"):
        _require(isinstance(rights.get(key), str) and rights[key].strip(),
                 f"{image_id}: falta {key} en permiso")
    _review_date(rights.get("reviewed_at"))
    proof = _private_file(evidence_root, rights.get("proof_path"), "comprobante de permiso")
    _require(proof.stat().st_size > 0, f"{image_id}: comprobante de permiso vacío")

    review = record.get("category_review" if negative else "label_review")
    _require(isinstance(review, dict) and review.get("decision") == "APPROVED",
             f"{image_id}: etiqueta/categoría sin revisión")
    for key in ("reviewer", "evidence_note"):
        _require(isinstance(review.get(key), str) and review[key].strip(),
                 f"{image_id}: revisión sin {key}")
    _review_date(review.get("reviewed_at"))
    if negative:
        _require(review.get("negative_category") == row["negative_category"],
                 f"{image_id}: categoría negativa no revisada")
        _require(review.get("quality_decision") == "INCLUDE_AS_NEGATIVE"
                 and isinstance(review.get("ambiguity_note"), str)
                 and review["ambiguity_note"].strip(),
                 f"{image_id}: falta revisión de calidad/ambigüedad")
        _require("class_code" not in record and "class_code" not in review,
                 f"{image_id}: negativo no puede tener clase diagnóstica")
    else:
        _require(review.get("source_label") == record.get("source_label"),
                 f"{image_id}: etiqueta original no revisada")
        for key in ("class_code", "crop_code"):
            _require(review.get(key) == record.get(key) == row[key],
                     f"{image_id}: etiqueta individual no revisada en {key}")
        _require(isinstance(record.get("source_label"), str) and record["source_label"].strip(),
                 f"{image_id}: falta etiqueta original")

    image_path = _private_file(images_root, record.get("relative_path"), "imagen")
    _require(image_path.suffix.lower() in {".jpg", ".jpeg", ".png"},
             f"{image_id}: extensión de imagen inválida")
    size = image_path.stat().st_size
    _require(100 <= size <= MAX_IMAGE_BYTES, f"{image_id}: tamaño de imagen inválido")
    raw = image_path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == row["sha256"],
             f"{image_id}: hash de bytes no coincide")
    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            image.load()
            _require(image.width > 0 and image.height > 0, f"{image_id}: dimensiones inválidas")
            _require(image.format == ("PNG" if image_path.suffix.lower() == ".png" else "JPEG"),
                     f"{image_id}: formato real no coincide")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f"{image_id}: imagen corrupta o formato inválido: {exc}") from exc
    return {"image_id": image_id, "sha256": row["sha256"], "source": row["source"],
            "split": row["split"], "split_group": row["split_group"],
            "category": row["negative_category"] if negative else row["class_code"],
            "capture_context": row["capture_context"]}
