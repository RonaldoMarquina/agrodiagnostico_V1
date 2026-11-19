"""Lectura y verificación de manifiestos de partición."""
import csv
from pathlib import Path
from typing import Dict, List, Set


class ManifestRecord:
    def __init__(self, row: Dict[str, str]):
        self.image_id = row.get("image_id", "").strip()
        self.sha256 = row.get("sha256", "").strip().lower()
        self.crop_code = row.get("crop_code", "").strip()
        self.class_code = row.get("class_code", "").strip()
        self.source = row.get("source", "").strip()
        self.split_group = row.get("split_group", "").strip()
        self.split = row.get("split", "").strip().upper()


def load_manifest(csv_path: str | Path) -> List[ManifestRecord]:
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Manifiesto CSV no encontrado: {path}")

    records = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            records.append(ManifestRecord(row))
    return records


def verify_partition_isolation(records: List[ManifestRecord]) -> None:
    """Verifica que ningún grupo (split_group) o hash cruce entre particiones distintas."""
    group_to_split: Dict[str, str] = {}
    hash_to_split: Dict[str, str] = {}

    for rec in records:
        if not rec.split:
            continue
        # Comprobar split_group
        if rec.split_group in group_to_split:
            if group_to_split[rec.split_group] != rec.split:
                raise ValueError(
                    f"Fuga de partición: split_group '{rec.split_group}' aparece en {group_to_split[rec.split_group]} y en {rec.split}"
                )
        else:
            group_to_split[rec.split_group] = rec.split

        # Comprobar sha256
        if rec.sha256 in hash_to_split:
            if hash_to_split[rec.sha256] != rec.split:
                raise ValueError(
                    f"Fuga de partición: hash '{rec.sha256}' aparece en {hash_to_split[rec.sha256]} y en {rec.split}"
                )
        else:
            hash_to_split[rec.sha256] = rec.split
