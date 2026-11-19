"""Empaquetado, validación y carga independiente de artefactos inmutables de modelo.

Cumple estrictamente con:
- contracts/ml/model-bundle.v1.schema.json
- contracts/ml/publication-policy.v1.schema.json
- Carga segura de tensores en CPU sin ejecución de código arbitrario ni descargas.
- Comprobación de SHA-256 de pesos y manifiestos.
- Verificación de cobertura de ambos cultivos (POTATO y MAIZE) conforme al protocolo G0.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

import jsonschema

from agro_ml.models.architectures import CPUClassifier
from agro_ml.models.hierarchical import HierarchicalAlternativeClassifier
from agro_ml.models.provenance import BASE_ARCHITECTURES

ROOT = Path(__file__).resolve().parents[4]
BUNDLE_SCHEMA_PATH = ROOT / "contracts/ml/model-bundle.v1.schema.json"
POLICY_SCHEMA_PATH = ROOT / "contracts/ml/publication-policy.v1.schema.json"


class BundleError(Exception):
    """Error base de empaquetado o carga de bundle."""
    pass


class BundleIntegrityError(BundleError):
    """Integridad o checksum del bundle alterado."""
    pass


class BundleSecurityError(BundleError):
    """Intento de acceso a ruta insegura o ejecución no autorizada."""
    pass


def compute_file_sha256(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Archivo no encontrado para hash: {p}")
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def build_model_bundle(
    model_id: str,
    model_version: str,
    dataset_version: str,
    architecture: str,
    weights_path: str | Path,
    train_manifest_path: str | Path,
    val_manifest_path: str | Path,
    test_manifest_path: str | Path,
    class_map: Dict[str, Any],
    calibration_params: Dict[str, Any],
    output_bundle_path: str | Path,
    g0_protocol_version: str = "1.0.0",
    g2_approval_id: str | None = None,
    approved_by: str | None = None,
    approved_at: str | None = None,
) -> Dict[str, Any]:
    """Construye y valida el bundle de modelo conforme a model-bundle.v1.schema.json."""
    if not all(isinstance(v, str) and v.strip() for v in (g2_approval_id, approved_by, approved_at)):
        raise ValueError("Explicit approval metadata required; the builder cannot invent human review")
    weights_p = Path(weights_path)
    weights_sha256 = compute_file_sha256(weights_p)
    weights_size = weights_p.stat().st_size

    train_sha256 = compute_file_sha256(train_manifest_path)
    val_sha256 = compute_file_sha256(val_manifest_path)
    test_sha256 = compute_file_sha256(test_manifest_path)

    bundle_data = {
        "schema_version": 1,
        "bundle_id": str(uuid.uuid4()),
        "model_id": model_id,
        "model_version": model_version,
        "dataset_version": dataset_version,
        "architecture": architecture,
        "weights": {
            "filename": weights_p.name,
            "sha256": weights_sha256,
            "format": "safetensors" if weights_p.suffix == ".safetensors" else "state_dict_weights_only",
            "size_bytes": weights_size,
        },
        "manifest_checksums": {
            "train_manifest_sha256": train_sha256,
            "val_manifest_sha256": val_sha256,
            "test_manifest_sha256": test_sha256,
        },
        "class_map": class_map,
        "preprocessing": {
            "input_size": [224, 224],
            "channels": 3,
            "color_space": "RGB",
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
        },
        "rejection_components": {
            "min_confidence_threshold": 0.65,
            "crop_detection_threshold": 0.85,
            "min_dimension": 200,
            "max_dimension": 6000,
        },
        "calibration": {
            "method": "PLATT_SCALING",
            "parameters_per_class": calibration_params,
        },
        "runtime_environment": {
            "python_version": "3.12",
            "framework": "pytorch",
            "framework_version": "2.2.0",
            "target_device": "cpu",
        },
        "governance": {
            "g0_protocol_version": g0_protocol_version,
            "g2_approval_id": g2_approval_id,
            "approved_by": approved_by,
            "approved_at": approved_at,
        },
    }

    # Validación contra esquema contractual
    if BUNDLE_SCHEMA_PATH.is_file():
        schema = json.loads(BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=bundle_data, schema=schema)

    out_p = Path(output_bundle_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(bundle_data, indent=2), encoding="utf-8")
    return bundle_data


def load_model_bundle(
    bundle_path: str | Path,
    weights_dir: Optional[str | Path] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """Carga de forma segura un bundle de modelo en memoria para inferencia en CPU."""
    b_path = Path(bundle_path)
    if not b_path.is_file():
        raise FileNotFoundError(f"Archivo de bundle no encontrado: {b_path}")

    bundle_data = json.loads(b_path.read_text(encoding="utf-8"))

    # 1. Validar esquema
    if BUNDLE_SCHEMA_PATH.is_file():
        schema = json.loads(BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=bundle_data, schema=schema)

    # 2. Localizar y validar archivo de pesos de forma segura contra path traversal
    weights_filename = bundle_data["weights"]["filename"]
    if "/" in weights_filename or "\\" in weights_filename or ".." in weights_filename:
        raise BundleSecurityError(f"Nombre de archivo de pesos inseguro: {weights_filename}")

    base_w_dir = Path(weights_dir) if weights_dir else b_path.parent
    weights_full_path = (base_w_dir / weights_filename).resolve()

    if not weights_full_path.is_file():
        raise FileNotFoundError(f"Archivo de pesos no encontrado: {weights_full_path}")

    # 3. Comprobar checksum SHA-256
    computed_sha = compute_file_sha256(weights_full_path)
    expected_sha = bundle_data["weights"]["sha256"].lower()
    if computed_sha != expected_sha:
        raise BundleIntegrityError(
            f"Checksum de pesos no coincide: obtenido {computed_sha} != {expected_sha}"
        )

    # 4. Instanciar clasificador según arquitectura
    arch = bundle_data["architecture"]
    if arch not in BASE_ARCHITECTURES:
        raise BundleError(f"Arquitectura no autorizada: {arch}. Permitidas: {list(BASE_ARCHITECTURES)}")

    weights_raw = json.loads(weights_full_path.read_text(encoding="utf-8"))

    if "weights_data" in weights_raw:
        # Modelo jerárquico
        model, _ = HierarchicalAlternativeClassifier.load_checkpoint(weights_full_path)
    else:
        # Clasificador conjunto CPU
        model = CPUClassifier(architecture=arch)
        model.load_weights(weights_full_path)

    return model, bundle_data


def build_publication_policy(
    policy_id: str,
    policy_version: str,
    model_id: str,
    model_version: str,
    dataset_version: str,
    bundle_digest: str,
    approved_classes: List[Dict[str, Any]],
    unsupported_classes: List[Dict[str, Any]],
    output_policy_path: str | Path,
    g0_protocol_version: str = "1.0.0",
    g2_approval_reference: str | None = None,
    approved_by: str | None = None,
    imported_by: str = "cli_admin",
) -> Dict[str, Any]:
    """Construye y valida el contrato de política de publicación (publication-policy.v1)."""
    if not all(isinstance(v, str) and v.strip() for v in (g2_approval_reference, approved_by)):
        raise ValueError("Explicit approval metadata required; no default approver")
    now_iso = datetime.now(timezone.utc).isoformat()

    policy_data = {
        "schema_version": 1,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "target_model": {
            "model_id": model_id,
            "model_version": model_version,
            "dataset_version": dataset_version,
            "bundle_digest": bundle_digest.lower(),
        },
        "approved_classes": approved_classes,
        "unsupported_classes": unsupported_classes,
        "catalog_requirements": {
            "require_reviewed_catalog": True,
        },
        "governance": {
            "g0_protocol_version": g0_protocol_version,
            "g2_approval_reference": g2_approval_reference,
            "approved_by": approved_by,
            "approved_at": now_iso,
        },
        "audit": {
            "imported_by": imported_by,
            "imported_at": now_iso,
        },
    }

    if POLICY_SCHEMA_PATH.is_file():
        schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(instance=policy_data, schema=schema)

    out_p = Path(output_policy_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(policy_data, indent=2), encoding="utf-8")
    return policy_data


def verify_dual_crop_coverage(approved_classes: List[Dict[str, Any]]) -> Dict[str, bool]:
    """Verifica la regla de cierre del protocolo G0: cobertura de ambos cultivos (POTATO y MAIZE)."""
    crops = {c.get("crop_code") for c in approved_classes}
    has_potato = "POTATO" in crops
    has_maize = "MAIZE" in crops
    return {
        "has_potato": has_potato,
        "has_maize": has_maize,
        "meets_closure_requirement": has_potato and has_maize,
    }
