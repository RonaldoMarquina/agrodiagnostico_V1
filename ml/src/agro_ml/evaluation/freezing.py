"""Congelamiento de candidato a release y control de acceso previo a evaluación en TEST.

Garantiza:
- Congelamiento inmutable de pesos, calibradores, umbrales y versión de protocolo antes de abrir TEST.
- Cálculo de hash digest integral de la tupla de release.
- Control de acceso: La evaluación sobre TEST solo está permitida si el candidato está estrictamente bloqueado (LOCKED_BEFORE_TEST).
- Detección de alteraciones: Cualquier modificación posterior al congelamiento invalida la evaluación y exige un nuevo ciclo experimental independiente.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class FreezingError(Exception):
    """Error base de congelamiento."""
    pass


class FrozenCandidateTamperedError(FreezingError):
    """Alteración detectada en un release candidate congelado."""
    pass


class TestEvaluationBlockedError(FreezingError):
    """Intento de acceder o evaluar en TEST sin candidato congelado y verificado."""
    pass


@dataclass
class FrozenCandidateSnapshot:
    schema_version: int
    freeze_id: str
    model_id: str
    model_version: str
    dataset_version: str
    architecture: str
    protocol_version: str
    weights_sha256: str
    calibration_sha256: str
    thresholds_sha256: str
    freeze_digest: str
    status: str  # LOCKED_BEFORE_TEST
    frozen_at: str
    frozen_by: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _canonical_json_hash(data: Dict[str, Any]) -> str:
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def freeze_release_candidate(
    model_id: str,
    model_version: str,
    dataset_version: str,
    architecture: str,
    weights_path: Path,
    calibration_params: Dict[str, Any],
    thresholds: Dict[str, Any],
    protocol_version: str,
    frozen_by: str,
    output_freeze_path: Path,
) -> FrozenCandidateSnapshot:
    """Congela todos los componentes del modelo antes de autorizar la apertura de TEST."""
    w_path = Path(weights_path)
    if not w_path.is_file():
        raise FileNotFoundError(f"Archivo de pesos no encontrado para congelamiento: {w_path}")

    # Hash de pesos
    h = hashlib.sha256()
    with w_path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    weights_sha = h.hexdigest().lower()

    # Hashes de calibración y umbrales
    calib_sha = _canonical_json_hash(calibration_params)
    thresh_sha = _canonical_json_hash(thresholds)

    # Digest combinado
    combined_raw = f"{weights_sha}:{calib_sha}:{thresh_sha}:{protocol_version}"
    freeze_digest = hashlib.sha256(combined_raw.encode("utf-8")).hexdigest()

    snapshot = FrozenCandidateSnapshot(
        schema_version=1,
        freeze_id=f"freeze_{model_id}_v{model_version}",
        model_id=model_id,
        model_version=model_version,
        dataset_version=dataset_version,
        architecture=architecture,
        protocol_version=protocol_version,
        weights_sha256=weights_sha,
        calibration_sha256=calib_sha,
        thresholds_sha256=thresh_sha,
        freeze_digest=freeze_digest,
        status="LOCKED_BEFORE_TEST",
        frozen_at=datetime.now(timezone.utc).isoformat(),
        frozen_by=frozen_by,
    )

    out = Path(output_freeze_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return snapshot


def verify_frozen_candidate(
    snapshot_path: Path,
    current_weights_path: Path,
    current_calibration_params: Dict[str, Any],
    current_thresholds: Dict[str, Any],
    current_protocol_version: str,
) -> bool:
    """Verifica si los componentes actuales coinciden exactamente con el candidato congelado."""
    snap_p = Path(snapshot_path)
    if not snap_p.is_file():
        raise FileNotFoundError(f"Snapshot de congelamiento no encontrado: {snap_p}")

    data = json.loads(snap_p.read_text(encoding="utf-8"))
    if data.get("status") != "LOCKED_BEFORE_TEST":
        raise FrozenCandidateTamperedError(f"Estado de congelamiento inválido: {data.get('status')}")

    # 1. Verificar pesos
    w_path = Path(current_weights_path)
    if not w_path.is_file():
        raise FileNotFoundError(f"Archivo de pesos actual no encontrado: {w_path}")
    h = hashlib.sha256()
    with w_path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    curr_weights_sha = h.hexdigest().lower()
    if curr_weights_sha != data["weights_sha256"]:
        raise FrozenCandidateTamperedError(
            f"Pesos alterados tras congelamiento. Obtenido {curr_weights_sha} != {data['weights_sha256']}. "
            f"Cualquier modificación motivada por TEST exige un nuevo ciclo experimental independiente."
        )

    # 2. Verificar calibración
    curr_calib_sha = _canonical_json_hash(current_calibration_params)
    if curr_calib_sha != data["calibration_sha256"]:
        raise FrozenCandidateTamperedError(
            f"Parámetros de calibración modificados tras congelamiento. "
            f"Obtenido {curr_calib_sha} != {data['calibration_sha256']}"
        )

    # 3. Verificar umbrales
    curr_thresh_sha = _canonical_json_hash(current_thresholds)
    if curr_thresh_sha != data["thresholds_sha256"]:
        raise FrozenCandidateTamperedError(
            f"Umbrales modificados tras congelamiento. "
            f"Obtenido {curr_thresh_sha} != {data['thresholds_sha256']}"
        )

    # 4. Verificar protocolo
    if current_protocol_version != data["protocol_version"]:
        raise FrozenCandidateTamperedError(
            f"Versión de protocolo alterada: {current_protocol_version} != {data['protocol_version']}"
        )

    # 5. Verificar digest combinado
    combined_raw = f"{curr_weights_sha}:{curr_calib_sha}:{curr_thresh_sha}:{current_protocol_version}"
    recomputed_digest = hashlib.sha256(combined_raw.encode("utf-8")).hexdigest()
    if recomputed_digest != data["freeze_digest"]:
        raise FrozenCandidateTamperedError("Digest criptográfico del congelamiento alterado.")

    return True


def authorize_test_evaluation(
    snapshot_path: Path,
    current_weights_path: Path,
    current_calibration_params: Dict[str, Any],
    current_thresholds: Dict[str, Any],
    current_protocol_version: str,
) -> bool:
    """Control de acceso: autoriza o bloquea la apertura de TEST."""
    try:
        return verify_frozen_candidate(
            snapshot_path=snapshot_path,
            current_weights_path=current_weights_path,
            current_calibration_params=current_calibration_params,
            current_thresholds=current_thresholds,
            current_protocol_version=current_protocol_version,
        )
    except (FileNotFoundError, FrozenCandidateTamperedError) as exc:
        raise TestEvaluationBlockedError(
            f"Evaluación en TEST denegada por control de acceso: {exc}"
        ) from exc
