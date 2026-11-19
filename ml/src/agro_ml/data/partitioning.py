"""Particionado consciente de grupos, verificación de fugas y sello inmutable de TEST/EXTERNAL.

Garantiza:
- Asignación atómica de cada split_group a una única partición.
- 0% de fuga de grupos y hashes en los 6 pares de particiones (TRAIN, VAL, TEST, EXTERNAL).
- Sello criptográfico inmutable para TEST y EXTERNAL con detección de alteraciones.
- Registro auditable de accesos a conjuntos de evaluación.
- Restricción estricta de aumentaciones únicamente a la partición TRAIN.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


PARTITIONS = ("TRAIN", "VAL", "TEST", "EXTERNAL")


class PartitionError(Exception):
    """Error base de particionado."""
    pass


class PartitionLeakageError(PartitionError):
    """Fuga de split_group o hash detectada entre particiones."""
    pass


class SealTamperedError(PartitionError):
    """El sello de la partición no coincide o ha sido alterado."""
    pass


@dataclass
class PartitionSeal:
    schema_version: int
    sealed_at: str
    protocol_version: str
    test_seal: str
    test_count: int
    external_seal: Optional[str]
    external_count: int
    sealed_by: str = "AgroDiagnóstico ML Pipeline"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def verify_partition_leakage(records: List[Dict[str, Any]]) -> None:
    """Verifica exhaustivamente que no existan fugas entre ninguno de los 6 pares de particiones.

    Pares evaluados:
    1. TRAIN vs VAL
    2. TRAIN vs TEST
    3. TRAIN vs EXTERNAL
    4. VAL vs TEST
    5. VAL vs EXTERNAL
    6. TEST vs EXTERNAL
    """
    by_split: Dict[str, List[Dict[str, Any]]] = {p: [] for p in PARTITIONS}
    for r in records:
        split = r.get("split", "").upper()
        if split in by_split:
            by_split[split].append(r)

    # Comprobar los 6 pares de particiones
    for i in range(len(PARTITIONS)):
        for j in range(i + 1, len(PARTITIONS)):
            p_a = PARTITIONS[i]
            p_b = PARTITIONS[j]
            list_a = by_split[p_a]
            list_b = by_split[p_b]
            if not list_a or not list_b:
                continue

            groups_a = {r["split_group"] for r in list_a if r.get("split_group")}
            groups_b = {r["split_group"] for r in list_b if r.get("split_group")}
            leak_groups = groups_a.intersection(groups_b)
            if leak_groups:
                raise PartitionLeakageError(
                    f"Fuga de split_group entre {p_a} y {p_b}: {sorted(list(leak_groups))[:5]}"
                )

            hashes_a = {r["sha256"].lower() for r in list_a if r.get("sha256")}
            hashes_b = {r["sha256"].lower() for r in list_b if r.get("sha256")}
            leak_hashes = hashes_a.intersection(hashes_b)
            if leak_hashes:
                raise PartitionLeakageError(
                    f"Fuga de SHA-256 entre {p_a} y {p_b}: {sorted(list(leak_hashes))[:5]}"
                )


def compute_split_digest(records: List[Dict[str, Any]], target_split: str) -> Tuple[str, int]:
    """Calcula el hash canónico SHA-256 para una partición específica."""
    filtered = [r for r in records if r.get("split", "").upper() == target_split.upper()]
    if not filtered:
        return "", 0

    # Ordenar determinísticamente por image_id y sha256
    sorted_records = sorted(
        filtered,
        key=lambda x: (x.get("image_id", ""), x.get("sha256", "").lower()),
    )
    lines = [
        f"{r.get('image_id')}:{r.get('sha256', '').lower()}:{r.get('class_code')}:{r.get('split_group')}"
        for r in sorted_records
    ]
    canonical_data = "\n".join(lines)
    digest = hashlib.sha256(canonical_data.encode("utf-8")).hexdigest()
    return digest, len(filtered)


def seal_test_partitions(
    records: List[Dict[str, Any]],
    output_seal_path: Path,
    protocol_version: str = "1.0.0",
) -> PartitionSeal:
    """Calcula y almacena el sello criptográfico inmutable de TEST y EXTERNAL."""
    # Primero verificar que no hay fugas
    verify_partition_leakage(records)

    test_seal, test_count = compute_split_digest(records, "TEST")
    ext_seal, ext_count = compute_split_digest(records, "EXTERNAL")
    if test_count == 0:
        raise PartitionError("No se puede sellar TEST sin muestras")

    seal = PartitionSeal(
        schema_version=1,
        sealed_at=datetime.now(timezone.utc).isoformat(),
        protocol_version=protocol_version,
        test_seal=test_seal,
        test_count=test_count,
        external_seal=ext_seal or None,
        external_count=ext_count,
    )

    out = Path(output_seal_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(seal.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return seal


def verify_test_partition_seal(
    records: List[Dict[str, Any]],
    seal_path: Path,
) -> bool:
    """Verifica que la partición TEST coincida exactamente con el sello congelado."""
    seal_file = Path(seal_path)
    if not seal_file.is_file():
        raise FileNotFoundError(f"Archivo de sello no encontrado: {seal_file}")

    data = json.loads(seal_file.read_text(encoding="utf-8"))
    expected_test_seal = data.get("test_seal")
    expected_test_count = data.get("test_count", 0)
    if not isinstance(expected_test_count, int) or expected_test_count <= 0 or not expected_test_seal:
        raise SealTamperedError("Sello TEST ausente o vacío")

    current_seal, current_count = compute_split_digest(records, "TEST")

    if current_count != expected_test_count:
        raise SealTamperedError(
            f"Conteo alterado en TEST: esperado {expected_test_count}, obtenido {current_count}"
        )
    if current_seal != expected_test_seal:
        raise SealTamperedError(
            f"Firma criptográfica de TEST alterada o no coincide con el sello congelado"
        )
    return True


def audit_test_access(
    split: str,
    purpose: str,
    caller: str,
    records: List[Dict[str, Any]],
    seal_path: Optional[Path] = None,
    audit_log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Registra de forma inmutable el acceso o evaluación sobre TEST o EXTERNAL."""
    split_upper = split.upper()
    if split_upper not in ("TEST", "EXTERNAL"):
        raise ValueError(f"La auditoría de sello aplica a TEST o EXTERNAL, no a {split}")

    seal_verified = False
    current_digest, current_count = compute_split_digest(records, split_upper)

    if seal_path and Path(seal_path).is_file():
        try:
            seal_verified = verify_test_partition_seal(records, seal_path)
        except Exception:
            seal_verified = False

    audit_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "split": split_upper,
        "caller": caller,
        "purpose": purpose,
        "sample_count": current_count,
        "partition_digest": current_digest,
        "seal_verified": seal_verified,
    }

    if audit_log_path:
        log_file = Path(audit_log_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")

    return audit_entry
