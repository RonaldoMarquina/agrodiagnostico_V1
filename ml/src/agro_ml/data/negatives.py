"""Gestión y validación de manifiesto separado de negativos autorizados.

Los negativos se gestionan de forma estrictamente separada del conjunto de 7 clases candidatas.
Categorías permitidas:
- OTHER_CROP: Cultivos no soportados (ej. tomate, vid, manzano) para evaluar abstención (RF-07).
- BACKGROUND: Fondos inertes, suelo o manos humanas para evaluar rechazo fuera de dominio.
- AMBIGUOUS_LEAF: Hojas deterioradas o no diagnósticas para evaluar BAD_IMAGE.

REGLAS DE CONTRATO:
- Ningún negativo puede tener class_code correspondiente a enfermedades de papa o maíz.
- NO_CONCLUYENTE es un estado del ciclo de vida y no una clase del modelo ni de los datos.
- Las particiones de negativos (TRAIN, VAL, TEST) deben mantener 0% de fuga de split_group y hash.
- Ningún negativo puede compartir hash SHA-256 ni split_group con el manifiesto positivo.
"""
import csv
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agro_ml.data.partitioning import verify_partition_leakage


ALLOWED_NEGATIVE_CATEGORIES = {
    "OTHER_CROP",
    "BACKGROUND",
    "AMBIGUOUS_LEAF",
}

NEGATIVE_CSV_HEADERS = [
    "image_id",
    "sha256",
    "negative_category",
    "source",
    "license",
    "capture_context",
    "split_group",
    "split",
    "notes",
]


class NegativeValidationError(ValueError):
    """Error de validación del manifiesto de negativos."""
    pass


@dataclass
class NegativeRecord:
    image_id: str
    sha256: str
    negative_category: str
    source: str
    license: str
    capture_context: str
    split_group: str
    split: str
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_negatives_manifest(csv_path: Path) -> List[NegativeRecord]:
    """Carga y valida filas del manifiesto de negativos."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Archivo de negativos no encontrado: {path}")

    records: List[NegativeRecord] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if set(fields) != set(NEGATIVE_CSV_HEADERS):
            raise NegativeValidationError(
                f"Cabeceras inválidas en CSV de negativos. Esperadas: {NEGATIVE_CSV_HEADERS}, obtenidas: {fields}"
            )
        for row in reader:
            if not row:
                continue
            records.append(
                NegativeRecord(
                    image_id=row["image_id"].strip(),
                    sha256=row["sha256"].strip().lower(),
                    negative_category=row["negative_category"].strip().upper(),
                    source=row["source"].strip(),
                    license=row["license"].strip(),
                    capture_context=row["capture_context"].strip(),
                    split_group=row["split_group"].strip(),
                    split=row["split"].strip().upper(),
                    notes=row.get("notes", "").strip(),
                )
            )
    return records


def validate_negatives(
    records: List[NegativeRecord],
    positive_records: Optional[List[Dict[str, Any]]] = None,
    allow_empty: bool = True,
) -> int:
    """Valida integridad, categorías permitidas, ausencia de clases de enfermedad y aislamiento total."""
    if not records:
        if allow_empty:
            return 0
        raise NegativeValidationError("El manifiesto de negativos no puede estar vacío")

    seen_ids: Set[str] = set()
    for idx, r in enumerate(records, start=1):
        if not r.image_id:
            raise NegativeValidationError(f"Fila {idx}: image_id vacío")
        if r.image_id in seen_ids:
            raise NegativeValidationError(f"Fila {idx}: image_id duplicado: {r.image_id}")
        seen_ids.add(r.image_id)

        if len(r.sha256) != 64:
            raise NegativeValidationError(f"Fila {idx}: sha256 inválido: {r.sha256}")

        if r.negative_category not in ALLOWED_NEGATIVE_CATEGORIES:
            raise NegativeValidationError(
                f"Fila {idx}: categoría negativa desconocida: '{r.negative_category}'. "
                f"Permitidas: {sorted(list(ALLOWED_NEGATIVE_CATEGORIES))}"
            )

        # Prohibición contractual estricta: nunca usar NO_CONCLUYENTE o nombres de patología
        forbidden_terms = ["NO_CONCLUYENTE", "POTATO", "MAIZE", "BLIGHT", "RUST", "SPOT"]
        if any(term in r.negative_category for term in forbidden_terms):
            raise NegativeValidationError(
                f"Fila {idx}: categoría negativa no puede simular enfermedades ni estado NO_CONCLUYENTE: {r.negative_category}"
            )

    # 1. Comprobar aislamiento interno entre particiones de negativos (0% fuga)
    dict_records = [r.to_dict() for r in records]
    verify_partition_leakage(dict_records)

    # 2. Comprobar no solapamiento con el conjunto positivo (si fue provisto)
    if positive_records:
        pos_hashes = {p["sha256"].lower() for p in positive_records if p.get("sha256")}
        pos_groups = {p["split_group"] for p in positive_records if p.get("split_group")}

        for r in records:
            if r.sha256 in pos_hashes:
                raise NegativeValidationError(
                    f"Conflicto grave: hash {r.sha256} en negativos también está presente en el manifiesto positivo"
                )
            if r.split_group in pos_groups:
                raise NegativeValidationError(
                    f"Conflicto grave: split_group {r.split_group} en negativos también está en el manifiesto positivo"
                )

    return len(records)
