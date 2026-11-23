"""Admisión y preflight v1.4.3 sin cargar el modelo ni ejecutar inferencia."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Mapping, Sequence

from agro_ml.data.tensor_preprocessing import TensorSpec, decode_image_to_rgb, image_to_tensor


CYCLE_VERSION = "1.4.3"
STRATA = (
    "POTATO_EARLY_BLIGHT",
    "POTATO_LATE_BLIGHT",
    "POTATO_HEALTHY",
    "OTHER_CROP",
)
SIKKIM_FORBIDDEN_MARKERS = (
    "sikkim",
    "4wz7zbk635",
    "5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc",
    "3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992",
    "ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a",
)
REQUIRED_FIELDS = (
    "image_id",
    "sha256",
    "file_size",
    "source_id",
    "source_version",
    "source_url",
    "license",
    "license_evidence_url",
    "source_path",
    "source_label",
    "stratum_code",
    "capture_origin",
    "independence_unit",
    "label_review",
    "decision",
    "decision_reason",
)


class V143AdmissionError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V143AdmissionError(message)


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://") and len(value) > 8


def read_manifest(manifest_path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    _require(manifest_path.is_file() and not manifest_path.is_symlink(),
             "manifiesto EXTERNAL ausente o inseguro")
    content = manifest_path.read_bytes()
    try:
        rows = [json.loads(line) for line in content.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V143AdmissionError("manifiesto EXTERNAL no es JSONL UTF-8 válido") from exc
    _require(bool(rows) and all(isinstance(row, dict) for row in rows),
             "manifiesto EXTERNAL vacío o inválido")
    validate_manifest(rows)
    return content, rows


def validate_manifest(rows: Sequence[Mapping[str, Any]]) -> None:
    image_ids: set[str] = set()
    hashes: set[str] = set()
    paths: set[str] = set()
    for row in rows:
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        _require(not missing, f"fila EXTERNAL sin campos requeridos: {','.join(missing)}")
        _require(row.get("decision") == "ADMITTED" and bool(row.get("decision_reason")),
                 "manifiesto sellable contiene una fila no admitida")
        _require(row.get("stratum_code") in STRATA, "estrato EXTERNAL desconocido")
        _require(_is_sha256(row.get("sha256")), "SHA-256 EXTERNAL inválido")
        _require(type(row.get("file_size")) is int and row["file_size"] > 0,
                 "tamaño EXTERNAL inválido")
        for field in ("image_id", "source_id", "source_version", "license", "source_label",
                      "capture_origin", "independence_unit", "label_review", "decision_reason"):
            _require(isinstance(row.get(field), str) and bool(row[field].strip()),
                     f"campo EXTERNAL vacío: {field}")
        _require(_is_https(row.get("source_url")) and _is_https(row.get("license_evidence_url")),
                 "procedencia o evidencia de licencia EXTERNAL inválida")
        relative = PurePosixPath(str(row.get("source_path", "")))
        _require(bool(relative.parts) and not relative.is_absolute() and ".." not in relative.parts,
                 "source_path EXTERNAL inseguro")
        searchable = " ".join(str(row.get(field, "")) for field in row).lower()
        _require(not any(marker in searchable for marker in SIKKIM_FORBIDDEN_MARKERS),
                 "Sikkim no puede reutilizarse en v1.4.3")
        _require(row["image_id"] not in image_ids, "image_id EXTERNAL duplicado")
        _require(row["sha256"] not in hashes, "SHA-256 EXTERNAL duplicado")
        _require(relative.as_posix() not in paths, "source_path EXTERNAL duplicado")
        image_ids.add(row["image_id"])
        hashes.add(row["sha256"])
        paths.add(relative.as_posix())


def _safe_file(images_root: Path, source_path: str) -> Path:
    _require(images_root.is_dir() and not images_root.is_symlink(),
             "raíz EXTERNAL ausente o insegura")
    root = images_root.resolve()
    candidate = images_root.joinpath(*PurePosixPath(source_path).parts)
    _require(candidate.is_file() and not candidate.is_symlink(),
             "archivo EXTERNAL ausente o inseguro")
    resolved = candidate.resolve()
    _require(resolved.is_relative_to(root), "archivo EXTERNAL sale de la raíz privada")
    return candidate


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(json.dumps(dict(value), ensure_ascii=False, indent=2,
                                sort_keys=True).encode("utf-8"))
        stream.write(b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_preflight(manifest_path: Path, images_root: Path, contract_path: Path,
                  output_dir: Path) -> dict[str, Any]:
    """Decodifica el lote completo y solo materializa evidencia si todo pasa."""
    _require(not output_dir.exists(), "salida de preflight ya existe")
    _require(contract_path.is_file() and not contract_path.is_symlink(),
             "contrato de preprocesado ausente o inseguro")
    contract_bytes = contract_path.read_bytes()
    try:
        contract = json.loads(contract_bytes)
    except json.JSONDecodeError as exc:
        raise V143AdmissionError("contrato de preprocesado inválido") from exc
    _require(contract.get("preprocessing_version") == CYCLE_VERSION and
             contract.get("external_policy", {}).get("full_decode_preflight_required_before_seal") is True and
             contract.get("external_policy", {}).get("model_loading_forbidden_during_preflight") is True and
             contract.get("external_policy", {}).get("sikkim_reuse_forbidden") is True,
             "contrato v1.4.3 incompatible")
    frozen = contract.get("frozen_model_parameters", {})
    _require(frozen.get("temperature") == 0.5 and frozen.get("threshold") == 0.8 and
             _is_sha256(frozen.get("weights_sha256")) and _is_sha256(frozen.get("freeze_digest")),
             "parámetros congelados v1.4.2 no preservados")

    manifest_bytes, rows = read_manifest(manifest_path)
    spec = TensorSpec(width=224, height=224, min_dimension=200, max_dimension=6000)
    compatibility: list[dict[str, Any]] = []
    for row in rows:
        path = _safe_file(images_root, row["source_path"])
        _require(path.stat().st_size == row["file_size"], "tamaño EXTERNAL cambió")
        content = path.read_bytes()
        _require(sha256_bytes(content) == row["sha256"], "bytes EXTERNAL cambiaron")
        rgb, decoded = decode_image_to_rgb(content, spec)
        tensor = image_to_tensor(content, spec, split="EXTERNAL")
        _require(rgb.mode == "RGB" and tuple(tensor.shape) == (3, 224, 224),
                 "salida de preprocesado EXTERNAL inválida")
        compatibility.append({
            "image_id": row["image_id"],
            "sha256": row["sha256"],
            "stratum_code": row["stratum_code"],
            **decoded.to_dict(),
            "rgb_mode": rgb.mode,
            "tensor_shape": [3, 224, 224],
            "tensor_finite": True,
            "status": "COMPATIBLE",
        })

    ordered = sorted(compatibility, key=lambda item: (item["image_id"], item["sha256"]))
    compatibility_bytes = b"".join(canonical_json(item) for item in ordered)
    counts = Counter(row["stratum_code"] for row in rows)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "cycle_version": CYCLE_VERSION,
        "status": "PREFLIGHT_COMPLETE_NOT_SEALED",
        "record_count": len(rows),
        "counts_by_stratum": dict(sorted(counts.items())),
        "formats": dict(sorted(Counter(item["format"] for item in ordered).items())),
        "modes": dict(sorted(Counter(item["mode"] for item in ordered).items())),
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "compatibility_jsonl_sha256": sha256_bytes(compatibility_bytes),
        "preprocessing_contract_sha256": sha256_bytes(contract_bytes),
        "all_files_decoded": True,
        "model_loaded": False,
        "predictions_generated": False,
        "metrics_generated": False,
        "external_opened_for_evaluation": False,
        "sikkim_reused": False,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v143-preflight-", dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        compatibility_path = stage / "compatibility.jsonl"
        descriptor = os.open(compatibility_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(compatibility_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        _write_json(stage / "preflight-summary.json", summary)
        Path(temporary).rename(output_dir)
    return summary


def verify_preflight(manifest_path: Path, contract_path: Path, preflight_dir: Path) -> dict[str, Any]:
    manifest_bytes, rows = read_manifest(manifest_path)
    summary_path = preflight_dir / "preflight-summary.json"
    compatibility_path = preflight_dir / "compatibility.jsonl"
    _require(summary_path.is_file() and compatibility_path.is_file(), "preflight incompleto")
    summary = json.loads(summary_path.read_text())
    compatibility_bytes = compatibility_path.read_bytes()
    compatibility = [json.loads(line) for line in compatibility_bytes.decode("utf-8").splitlines()]
    _require(summary.get("status") == "PREFLIGHT_COMPLETE_NOT_SEALED" and
             summary.get("record_count") == len(rows) == len(compatibility),
             "cardinalidad de preflight alterada")
    _require(summary.get("manifest_sha256") == sha256_bytes(manifest_bytes) and
             summary.get("compatibility_jsonl_sha256") == sha256_bytes(compatibility_bytes) and
             summary.get("preprocessing_contract_sha256") == sha256_file(contract_path),
             "hashes de preflight alterados")
    _require({row["sha256"] for row in rows} == {item.get("sha256") for item in compatibility} and
             all(item.get("status") == "COMPATIBLE" for item in compatibility),
             "preflight no cubre exactamente el manifiesto")
    return summary


def seal_external(manifest_path: Path, contract_path: Path, preflight_dir: Path,
                  approval_path: Path, output_path: Path) -> dict[str, Any]:
    """Sella solo un preflight completo y criterios aprobados previamente."""
    _require(not output_path.exists(), "sello EXTERNAL ya existe")
    manifest_bytes, rows = read_manifest(manifest_path)
    summary = verify_preflight(manifest_path, contract_path, preflight_dir)
    _require(approval_path.is_file() and not approval_path.is_symlink(),
             "aprobación G0 v1.4.3 ausente")
    approval = json.loads(approval_path.read_text())
    counts = dict(sorted(Counter(row["stratum_code"] for row in rows).items()))
    _require(approval.get("cycle_version") == CYCLE_VERSION and
             approval.get("status") == "APPROVED_BY_PROJECT_OWNER" and
             approval.get("counts_by_stratum") == counts and
             bool(approval.get("approved_at")) and bool(approval.get("justification")),
             "aprobación G0 v1.4.3 no corresponde al lote")
    criteria = approval.get("external_criteria", {})
    _require(set(criteria) == {"macro_f1_min", "recall_min_by_blight",
                                "healthy_false_publication_max", "healthy_rejection_min",
                                "other_crop_false_publication_max"},
             "criterios EXTERNAL incompletos")
    seal = {
        "schema_version": 1,
        "cycle_version": CYCLE_VERSION,
        "partition": "EXTERNAL",
        "status": "SEALED_NOT_OPENED_FOR_EVALUATION",
        "record_count": len(rows),
        "counts_by_stratum": counts,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "preflight_summary_sha256": sha256_file(preflight_dir / "preflight-summary.json"),
        "compatibility_jsonl_sha256": summary["compatibility_jsonl_sha256"],
        "preprocessing_contract_sha256": sha256_file(contract_path),
        "approval_sha256": sha256_file(approval_path),
        "weights_sha256": json.loads(contract_path.read_text())["frozen_model_parameters"]["weights_sha256"],
        "temperature": 0.5,
        "threshold": 0.8,
        "sikkim_reused": False,
        "opened_for_evaluation": False,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output_path, seal)
    return seal
