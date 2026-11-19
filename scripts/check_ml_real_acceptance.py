#!/usr/bin/env python3
"""Comando de aceptación real separado para releases y datasets ML autorizados.

Conforme al protocolo de gobernanza G3, ADR-0009 y la Tarea 8.2 de Incremento 4:
- Exige artefactos de release y dataset formalmente aprobados.
- Rechaza explícitamente fixtures, datos sintéticos o modelos de prueba como evidencia real.
- Verifica criptográficamente (SHA-256) la inmutabilidad de pesos, bundle y manifiestos.
- Ejecuta inferencia técnica acotada en CPU y valida la congruencia con la política activa.
- Preserva comandos ejecutados, hashes, metadatos y reportes saneados sin filtrar secretos.
- Limpia rigurosamente todos los recursos y archivos temporales generados durante la prueba.
"""
import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "ml" / "src"))
sys.path.insert(0, str(ROOT / "services" / "ai_inference"))

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    Draft202012Validator = None

from app.model_loader import (
    ALLOWED_ARCHITECTURES,
    ALLOWED_FORMATS,
    BundleIntegrityError,
    BundleSecurityError,
    BundleValidationError,
    load_authorized_bundle,
)
from app.inference_adapter import RealModelInferenceAdapter
from ci_support import redact

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ml_real_acceptance")

FIXTURE_PATTERN = re.compile(r"(fixture|synthetic|dummy|fake|mock|^ci-)", re.IGNORECASE)


def sanitize_evidence_text(text: str, extra_secrets: Tuple[str, ...] = ()) -> str:
    """Sanitiza URLs, tokens, contraseñas y parámetros sensibles para reportes seguros."""
    text = redact(text, list(extra_secrets))
    text = re.sub(r'(--(?:token|password|secret|key|api[_-]?key|auth)=)[^\s]+', r'\1[REDACTED]', text, flags=re.IGNORECASE)
    text = re.sub(
        r'(?i)(["\']?(?:token|password|secret|key|api[_-]?key|authorization)["\']?\s*[:=]\s*["\']?)([^"\'\s,;}{]+)(["\']?)',
        r'\1[REDACTED]\3',
        text,
    )
    return text


class RealAcceptanceError(Exception):
    """Error fatal durante el protocolo de aceptación real G3."""
    pass


class FixtureRejectedError(RealAcceptanceError):
    """Un artefacto de prueba/fixture fue rechazado como evidencia agronómica real."""
    pass


class TamperedArtifactError(RealAcceptanceError):
    """La integridad criptográfica del artefacto fue violada (SHA-256 mismatch)."""
    pass


def sha256_file(path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo en disco."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def validate_schema(data: dict, schema_path: Path, context_name: str) -> None:
    """Valida un documento JSON contra su esquema Draft 2020-12."""
    if Draft202012Validator is None:
        return
    if not schema_path.is_file():
        raise RealAcceptanceError(f"No se encontró el esquema para {context_name}: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(data))
    if errors:
        msg = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:3])
        raise RealAcceptanceError(f"Validación de contrato fallida para {context_name}: {msg}")


def assert_not_fixture(data: dict, field_name: str, context: str) -> None:
    """Verifica que un campo no contenga identificadores de fixture o datos sintéticos."""
    val = data.get(field_name)
    if val is not None:
        if isinstance(val, bool) and val and "fixture" in field_name.lower():
            raise FixtureRejectedError(f"FIXTURE_REJECTED: Campo '{field_name}' marcado como fixture en {context}")
        if isinstance(val, str) and FIXTURE_PATTERN.search(val):
            raise FixtureRejectedError(
                f"FIXTURE_REJECTED: '{field_name}' tiene valor '{val}' identificado como prueba/fixture en {context}"
            )


def verify_release_bundle(bundle_path: Path) -> Tuple[dict, str]:
    """Verifica y audita un bundle de release real.

    Returns:
        (bundle_data, bundle_sha256)
    """
    if not bundle_path.is_file():
        raise RealAcceptanceError(f"No se encontró el archivo de bundle: {bundle_path}")

    raw_bytes = bundle_path.read_bytes()
    bundle_digest = hashlib.sha256(raw_bytes).hexdigest()
    try:
        bundle_data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as ex:
        raise RealAcceptanceError(f"Error decodificando bundle JSON: {ex}") from ex

    # 1. Esquema contractual
    schema_path = ROOT / "contracts" / "ml" / "model-bundle.v1.schema.json"
    validate_schema(bundle_data, schema_path, "model-bundle")

    # 2. Rechazo estricto de fixtures como evidencia real
    assert_not_fixture(bundle_data, "model_id", "bundle")
    assert_not_fixture(bundle_data, "model_version", "bundle")
    assert_not_fixture(bundle_data, "dataset_version", "bundle")

    gov = bundle_data.get("governance", {})
    assert_not_fixture(gov, "g2_approval_id", "governance")
    assert_not_fixture(gov, "approved_by", "governance")

    # 3. Integridad de pesos
    weights_meta = bundle_data.get("weights", {})
    weights_filename = weights_meta.get("filename", "")
    weights_path = bundle_path.parent / weights_filename

    if not weights_path.is_file():
        raise RealAcceptanceError(f"No se encontró el archivo de pesos: {weights_path}")

    actual_weights_sha = sha256_file(weights_path)
    expected_weights_sha = weights_meta.get("sha256", "")
    if actual_weights_sha != expected_weights_sha:
        raise TamperedArtifactError(
            f"DIGEST_MISMATCH en pesos: esperado {expected_weights_sha[:16]}..., observado {actual_weights_sha[:16]}..."
        )

    actual_size = weights_path.stat().st_size
    expected_size = weights_meta.get("size_bytes", 0)
    if actual_size != expected_size:
        raise TamperedArtifactError(
            f"SIZE_MISMATCH en pesos: esperado {expected_size} bytes, observado {actual_size} bytes"
        )

    # 4. Carga segura del bundle
    try:
        load_authorized_bundle(bundle_path)
    except (BundleIntegrityError, BundleSecurityError, BundleValidationError) as ex:
        raise RealAcceptanceError(f"Error de validación segura de bundle: {ex}") from ex

    return bundle_data, bundle_digest


def verify_publication_policy(policy_path: Path, bundle_data: dict, bundle_digest: str) -> dict:
    """Verifica y audita la política de publicación real contra el bundle aprobado."""
    if not policy_path.is_file():
        raise RealAcceptanceError(f"No se encontró el archivo de política: {policy_path}")

    try:
        policy_data = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise RealAcceptanceError(f"Error decodificando policy JSON: {ex}") from ex

    # 1. Esquema contractual
    schema_path = ROOT / "contracts" / "ml" / "publication-policy.v1.schema.json"
    validate_schema(policy_data, schema_path, "publication-policy")

    # 2. Rechazo de fixtures en política
    assert_not_fixture(policy_data, "policy_id", "policy")
    target_model = policy_data.get("target_model", {})
    assert_not_fixture(target_model, "model_id", "target_model")

    gov = policy_data.get("governance", {})
    assert_not_fixture(gov, "g2_approval_reference", "policy governance")
    assert_not_fixture(gov, "approved_by", "policy governance")

    audit = policy_data.get("audit", {})
    assert_not_fixture(audit, "imported_by", "policy audit")

    # 3. Correspondencia exacta de tupla modelo/dataset/digest
    if target_model.get("model_id") != bundle_data.get("model_id"):
        raise RealAcceptanceError(
            f"POLICY_TARGET_MISMATCH: model_id en política '{target_model.get('model_id')}' != bundle '{bundle_data.get('model_id')}'"
        )
    if target_model.get("model_version") != bundle_data.get("model_version"):
        raise RealAcceptanceError(
            f"POLICY_TARGET_MISMATCH: model_version en política '{target_model.get('model_version')}' != bundle '{bundle_data.get('model_version')}'"
        )
    if target_model.get("dataset_version") != bundle_data.get("dataset_version"):
        raise RealAcceptanceError(
            f"POLICY_TARGET_MISMATCH: dataset_version en política '{target_model.get('dataset_version')}' != bundle '{bundle_data.get('dataset_version')}'"
        )
    if target_model.get("bundle_digest") != bundle_digest:
        raise TamperedArtifactError(
            f"POLICY_DIGEST_MISMATCH: bundle_digest en política '{target_model.get('bundle_digest')[:16]}...' != digest real '{bundle_digest[:16]}...'"
        )

    # 4. Finitud de parámetros de calibración y umbrales en [0.0, 1.0]
    for cls_item in policy_data.get("approved_classes", []):
        min_conf = cls_item.get("min_confidence_threshold")
        if not (isinstance(min_conf, (int, float)) and math.isfinite(min_conf) and 0.0 <= min_conf <= 1.0):
            raise RealAcceptanceError(f"Umbral de publicación inválido para clase {cls_item.get('class_code')}")
        cal = cls_item.get("calibration_params", {})
        if not (isinstance(cal.get("slope"), (int, float)) and math.isfinite(cal.get("slope"))):
            raise RealAcceptanceError(f"Pendiente de calibración no finita para clase {cls_item.get('class_code')}")
        if not (isinstance(cal.get("intercept"), (int, float)) and math.isfinite(cal.get("intercept"))):
            raise RealAcceptanceError(f"Intercepto de calibración no finito para clase {cls_item.get('class_code')}")

    return policy_data


def verify_dataset_seal(manifest_path: Path, seal_path: Path) -> dict:
    """Verifica el sello criptográfico del conjunto de datos TEST/EXTERNAL."""
    if not manifest_path.is_file():
        raise RealAcceptanceError(f"No se encontró el manifiesto de imágenes: {manifest_path}")
    if not seal_path.is_file():
        raise RealAcceptanceError(f"No se encontró el sello de evaluación: {seal_path}")

    seal_data = json.loads(seal_path.read_text(encoding="utf-8"))
    manifest_sha = sha256_file(manifest_path)

    expected_sha = seal_data.get("manifest_sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise RealAcceptanceError("DATASET_SEAL_MISSING: manifest_sha256 is required")
    if expected_sha and manifest_sha != expected_sha:
        raise TamperedArtifactError(
            f"DATASET_SEAL_MISMATCH: Manifiesto {manifest_path.name} hash {manifest_sha[:16]}... != sello {expected_sha[:16]}..."
        )

    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "seal_path": str(seal_path),
        "seal_verified": True,
    }


def execute_technical_inference_check(bundle_path: Path) -> dict:
    """Ejecuta una comprobación técnica de inferencia CPU acotada con el bundle real."""
    bundle_data, weights_data = load_authorized_bundle(bundle_path)
    adapter = RealModelInferenceAdapter(bundle_data=bundle_data, weights_data=weights_data)

    # Genera un tensor mínimo válido para medir el tiempo CPU
    import zlib, struct
    width, height = 224, 224
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data))
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc
    raw_scanlines = b"\x00" + (b"\x80\x80\x80" * width)
    compressed = zlib.compress(raw_scanlines * height)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed))
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND"))
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc
    png_bytes = signature + ihdr + idat + iend

    import uuid
    diag_id = uuid.uuid4()
    t0 = time.monotonic()
    result = adapter.run_inference(diagnosis_id=diag_id, image_bytes=png_bytes)
    duration_ms = int((time.monotonic() - t0) * 1000)

    if result.get("inference_ms") is None or result.get("inference_ms") < 0:
        raise RealAcceptanceError("inference_ms no medido o negativo en adaptador real")

    return {
        "outcome": result.get("outcome"),
        "class_code": result.get("class_code"),
        "raw_score": result.get("raw_score"),
        "measured_ms": duration_ms,
        "adapter_inference_ms": result.get("inference_ms"),
    }


def run_real_acceptance(
    release_bundle_path: Path,
    policy_file_path: Path,
    dataset_manifest_path: Path,
    seal_path: Path,
    output_report_path: Path,
    command_args: List[str],
) -> dict:
    """Orquesta la suite completa de aceptación real G3 y genera el reporte saneado."""
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report: Dict[str, Any] = {
        "status": "FAILED",
        "stage": "G3_REAL_ACCEPTANCE",
        "started_utc": started_utc,
        "command": sanitize_evidence_text(" ".join(command_args)),
        "checks": [],
    }

    # Recursos propios temporales con limpieza garantizada
    with tempfile.TemporaryDirectory(prefix="agro-real-acc-") as tmp_work_dir:
        report["temp_dir_used"] = str(tmp_work_dir)

        # Paso 1: Verificación de bundle
        bundle_data, bundle_digest = verify_release_bundle(release_bundle_path)
        report["bundle"] = {
            "path": str(release_bundle_path),
            "bundle_digest": bundle_digest,
            "model_id": bundle_data.get("model_id"),
            "model_version": bundle_data.get("model_version"),
            "dataset_version": bundle_data.get("dataset_version"),
            "architecture": bundle_data.get("architecture"),
            "weights_sha256": bundle_data.get("weights", {}).get("sha256"),
        }
        report["checks"].append({"check": "bundle_integrity_and_governance", "status": "PASSED"})

        # Paso 2: Verificación de política
        policy_data = verify_publication_policy(policy_file_path, bundle_data, bundle_digest)
        report["policy"] = {
            "path": str(policy_file_path),
            "policy_id": policy_data.get("policy_id"),
            "policy_version": policy_data.get("policy_version"),
            "approved_classes_count": len(policy_data.get("approved_classes", [])),
            "g2_approval_reference": policy_data.get("governance", {}).get("g2_approval_reference"),
        }
        report["checks"].append({"check": "policy_governance_and_match", "status": "PASSED"})

        # Paso 3: Verificación de conjunto de datos y sello
        dataset_info = verify_dataset_seal(dataset_manifest_path, seal_path)
        report["dataset"] = dataset_info
        report["checks"].append({"check": "dataset_seal_and_integrity", "status": "PASSED"})

        # Paso 4: Inferencia técnica acotada en CPU
        inference_info = execute_technical_inference_check(release_bundle_path)
        report["runtime_inference"] = inference_info
        report["checks"].append({"check": "bounded_cpu_runtime_check", "status": "PASSED"})

        raise RealAcceptanceError(
            "G3_NOT_IMPLEMENTED: synthetic runtime smoke is not real dataset/E2E acceptance"
        )
        report["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Escritura del reporte saneado
    output_report_path.parent.mkdir(parents=True, exist_ok=True)
    sanitized_json = sanitize_evidence_text(json.dumps(report, indent=2) + "\n")
    output_report_path.write_text(sanitized_json, encoding="utf-8")
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-bundle", type=Path, required=True, help="Ruta al archivo bundle.json del modelo")
    parser.add_argument("--policy-file", type=Path, required=True, help="Ruta al archivo de política de publicación")
    parser.add_argument(
        "--dataset-manifest",
        type=Path,
        default=ROOT / "ml" / "manifests" / "images.v2.csv",
        help="Ruta al manifiesto de imágenes",
    )
    parser.add_argument(
        "--test-seal",
        type=Path,
        default=ROOT / "ml" / "manifests" / "test_external_seal.v1.json",
        help="Ruta al sello criptográfico de evaluación",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=ROOT / ".local" / "acceptance" / "ml_real_acceptance_report.json",
        help="Ruta donde guardar el reporte JSON saneado",
    )

    args = parser.parse_args(argv)
    cmd_repr = [sys.executable, str(Path(__file__).resolve())] + (argv if argv is not None else sys.argv[1:])

    try:
        logger.info("Iniciando aceptación real G3 (Tarea 8.2)...")
        report = run_real_acceptance(
            release_bundle_path=args.release_bundle,
            policy_file_path=args.policy_file,
            dataset_manifest_path=args.dataset_manifest,
            seal_path=args.test_seal,
            output_report_path=args.output_report,
            command_args=cmd_repr,
        )
        logger.info(f"PASS G3 Real Acceptance: Reporte guardado en {args.output_report}")
        return 0
    except (RealAcceptanceError, Exception) as ex:
        logger.error(f"FAIL G3 Real Acceptance: {ex}")
        # Guardar reporte de fallo si es posible
        fail_report = {
            "status": "FAILED",
            "error_type": type(ex).__name__,
            "error_message": sanitize_evidence_text(str(ex)),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            args.output_report.parent.mkdir(parents=True, exist_ok=True)
            args.output_report.write_text(json.dumps(fail_report, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
