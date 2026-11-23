"""Compuertas de datos y evaluación para el ciclo G0 v1.4.0.

El módulo no descarga datos ni abre imágenes. Valida registros ya materializados,
el sello EXTERNAL y la frontera entre selección (TRAIN/VAL) y evaluación final.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROVENANCE_FIELDS = (
    "image_id",
    "sha256",
    "source_id",
    "source_revision",
    "source_url",
    "author",
    "license",
    "license_url",
    "source_path",
    "split",
    "split_group",
    "decision",
    "decision_reason",
    "rights_proof_path",
    "source_label",
    "stratum_code",
)
FORBIDDEN_EXTERNAL_PURPOSES = {
    "TRAIN",
    "VAL",
    "CALIBRATION",
    "ARCHITECTURE_SELECTION",
    "BALANCE_SELECTION",
    "HYPERPARAMETER_SELECTION",
    "THRESHOLD_SELECTION",
}
EXTERNAL_COUNTS = {
    "POTATO_EARLY_BLIGHT": 42,
    "POTATO_LATE_BLIGHT": 76,
    "POTATO_HEALTHY": 50,
    "OTHER_CROP": 194,
}
PUBLISHABLE = {"POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"}


class V14GateError(ValueError):
    """La evidencia no satisface una compuerta v1.4.0."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V14GateError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value.lower()))


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_provenance_record(record: Mapping[str, Any]) -> None:
    """Rechaza filas sin procedencia y permiso aplicable por archivo."""
    for field in PROVENANCE_FIELDS:
        _require(_text(record.get(field)), f"registro sin {field}")
    _require(_sha(record["sha256"]), "registro con SHA-256 inválido")
    _require(str(record["source_url"]).startswith("https://"), "URL original no HTTPS")
    _require(str(record["license_url"]).startswith("https://"), "URL de licencia no HTTPS")
    _require(
        record["decision"] in {"ADMIT_TRAIN_VAL", "ADMIT_EXTERNAL"},
        "decisión de admisión inválida",
    )
    # Una URL pública por sí sola no concede derechos.
    _require(record["license"] not in {"PUBLIC", "UNKNOWN", "UNSPECIFIED"},
             "URL pública sin licencia aplicable")


def canonical_manifest_digest(records: Sequence[Mapping[str, Any]]) -> str:
    """Hash de todos los campos de cada fila, independiente del orden de entrada."""
    normalized = [dict(record) for record in records]
    normalized.sort(key=lambda row: (str(row.get("image_id", "")), str(row.get("sha256", ""))))
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def build_external_seal(
    records: Sequence[Mapping[str, Any]],
    manifest_bytes: bytes,
    *,
    protocol_sha256: str,
) -> dict[str, Any]:
    """Construye el contenido determinista del sello; el llamador decide dónde guardarlo."""
    validate_external_registry(records)
    _require(_sha(protocol_sha256), "hash del protocolo inválido")
    return {
        "schema_version": 1,
        "protocol_version": "1.4.0",
        "sealed_at": "2026-11-22",
        "partition": "EXTERNAL",
        "source_id": "sikkim-solanaceae-v1",
        "record_count": len(records),
        "counts_by_stratum": dict(sorted(Counter(r["stratum_code"] for r in records).items())),
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "canonical_records_sha256": canonical_manifest_digest(records),
        "protocol_sha256": protocol_sha256,
        "independence_unit": "UNIQUE_IMAGE_SHA256_ONLY",
        "plant_independence_verified": False,
    }


def validate_external_registry(records: Sequence[Mapping[str, Any]]) -> None:
    _require(len(records) == 362, f"EXTERNAL requiere 362 filas, recibió {len(records)}")
    hashes: set[str] = set()
    ids: set[str] = set()
    for record in records:
        validate_provenance_record(record)
        _require(record["source_id"] == "sikkim-solanaceae-v1", "fuente EXTERNAL no fijada")
        _require(record["source_revision"] == "10.17632/4wz7zbk635.1", "revisión Sikkim distinta")
        _require(record["license"] == "CC-BY-4.0", "licencia Sikkim distinta")
        _require(record["split"] == "EXTERNAL", "Sikkim fuera de EXTERNAL")
        _require(record["decision"] == "ADMIT_EXTERNAL", "Sikkim no admitido como EXTERNAL")
        _require(record["split_group"] == f"sikkim-image:{record['sha256']}",
                 "identidad Sikkim no deriva del SHA-256")
        _require(record.get("independence_unit") == "UNIQUE_IMAGE_ONLY_NOT_PLANT",
                 "registro afirma o no limita independencia por planta")
        _require(record["sha256"] not in hashes, "SHA-256 Sikkim duplicado")
        _require(record["image_id"] not in ids, "image_id Sikkim duplicado")
        hashes.add(record["sha256"])
        ids.add(record["image_id"])
    counts = Counter(record["stratum_code"] for record in records)
    _require(dict(counts) == EXTERNAL_COUNTS, f"conteos EXTERNAL distintos: {dict(counts)}")


def verify_external_seal(
    records: Sequence[Mapping[str, Any]],
    manifest_bytes: bytes,
    seal: Mapping[str, Any],
) -> None:
    validate_external_registry(records)
    _require(seal.get("protocol_version") == "1.4.0", "sello de otro protocolo")
    _require(seal.get("partition") == "EXTERNAL", "sello de otra partición")
    _require(seal.get("record_count") == len(records), "conteo del sello alterado")
    _require(seal.get("counts_by_stratum") == dict(sorted(EXTERNAL_COUNTS.items())),
             "conteos por estrato del sello alterados")
    _require(seal.get("manifest_sha256") == sha256_bytes(manifest_bytes),
             "manifiesto EXTERNAL cambió después del sello")
    _require(seal.get("canonical_records_sha256") == canonical_manifest_digest(records),
             "filas EXTERNAL cambiaron después del sello")
    _require(_sha(seal.get("protocol_sha256")), "sello sin hash de protocolo")


def validate_plantvillage_train_val(
    records: Sequence[Mapping[str, Any]],
    *,
    blocked_test_groups: Iterable[str] = (),
) -> dict[str, dict[str, int]]:
    """Valida la referencia v1.4.0: 3 clases TRAIN/VAL y OTHER_CROP solo VAL."""
    _require(bool(records), "manifiesto PlantVillage vacío")
    blocked = set(blocked_test_groups)
    hashes: set[str] = set()
    group_splits: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(lambda: {"photos": 0, "groups": set()}))
    allowed = {
        ("POTATO_EARLY_BLIGHT", "TRAIN"), ("POTATO_EARLY_BLIGHT", "VAL"),
        ("POTATO_LATE_BLIGHT", "TRAIN"), ("POTATO_LATE_BLIGHT", "VAL"),
        ("POTATO_HEALTHY", "TRAIN"), ("POTATO_HEALTHY", "VAL"),
        ("OTHER_CROP", "VAL"),
    }
    for record in records:
        validate_provenance_record(record)
        _require(record["source_id"] == "plantvillage", "fuente TRAIN/VAL no es PlantVillage")
        _require(record["source_revision"] == "9e97599868962bd0079b8db4b7f1efa9185fa1e7",
                 "revisión PlantVillage distinta")
        _require(record["license"] == "CC-BY-SA-3.0", "licencia PlantVillage distinta")
        _require((record["stratum_code"], record["split"]) in allowed,
                 "estrato o partición PlantVillage no permitido")
        _require(not record["split_group"].startswith("fallback_"), "grupo fallback prohibido")
        _require(record["split_group"] not in blocked, "grupo del TEST histórico reutilizado")
        _require(record["sha256"] not in hashes, "SHA-256 PlantVillage duplicado")
        hashes.add(record["sha256"])
        group_splits[record["split_group"]].add(record["split"])
        cell = counts[record["stratum_code"]][record["split"]]
        cell["photos"] += 1
        cell["groups"].add(record["split_group"])
    _require(all(len(splits) == 1 for splits in group_splits.values()),
             "leaf_id cruza TRAIN y VAL")
    expected = {
        "POTATO_EARLY_BLIGHT": {"TRAIN": (541, 136), "VAL": (165, 42)},
        "POTATO_LATE_BLIGHT": {"TRAIN": (499, 129), "VAL": (153, 39)},
        "POTATO_HEALTHY": {"TRAIN": (80, 20), "VAL": (28, 7)},
        "OTHER_CROP": {"VAL": (150, 38)},
    }
    result: dict[str, dict[str, int]] = {}
    for code, splits in expected.items():
        result[code] = {}
        for split, (photos, groups) in splits.items():
            actual = counts[code][split]
            _require(actual["photos"] == photos and len(actual["groups"]) == groups,
                     f"conteo PlantVillage distinto: {code} {split}")
            result[code][split] = photos
    _require(len(records) == 1616, f"PlantVillage TRAIN/VAL requiere 1616 filas, recibió {len(records)}")
    return result


def verify_pretraining_gate(
    plantvillage_records: Sequence[Mapping[str, Any]],
    external_records: Sequence[Mapping[str, Any]],
    external_manifest_bytes: bytes,
    external_seal: Mapping[str, Any],
    protocol: Mapping[str, Any],
    *,
    blocked_test_groups: Iterable[str] = (),
    protocol_sha256: str | None = None,
) -> None:
    _require(protocol.get("protocol_version") == "1.4.0", "protocolo G0 v1.4.0 ausente")
    _require(protocol.get("status") == "APPROVED_G0_DESIGN", "G0 no aprobado")
    _require(protocol.get("gates", {}).get("G0") == "CLOSED_APPROVED", "G0 no cerrado")
    validate_plantvillage_train_val(plantvillage_records, blocked_test_groups=blocked_test_groups)
    verify_external_seal(external_records, external_manifest_bytes, external_seal)
    pv_hashes = {record["sha256"] for record in plantvillage_records}
    ext_hashes = {record["sha256"] for record in external_records}
    _require(not pv_hashes.intersection(ext_hashes), "SHA-256 mezclado entre PlantVillage y EXTERNAL")
    _require(_sha(protocol_sha256), "hash del protocolo aprobado ausente")
    _require(external_seal.get("protocol_sha256") == protocol_sha256,
             "sello EXTERNAL no referencia el protocolo aprobado")


def authorize_external_access(
    purpose: str,
    records: Sequence[Mapping[str, Any]],
    manifest_bytes: bytes,
    seal: Mapping[str, Any],
    freeze_record: Mapping[str, Any] | None,
) -> None:
    """Autoriza únicamente la evaluación final posterior al congelamiento completo."""
    normalized = purpose.strip().upper()
    _require(normalized not in FORBIDDEN_EXTERNAL_PURPOSES,
             f"EXTERNAL prohibido para {normalized}")
    _require(normalized == "FINAL_EXTERNAL_EVALUATION", "propósito EXTERNAL no permitido")
    verify_external_seal(records, manifest_bytes, seal)
    _require(isinstance(freeze_record, Mapping), "bundle aún no congelado")
    _require(freeze_record.get("status") == "FROZEN", "bundle aún no congelado")
    for field in ("bundle_sha256", "configuration_sha256", "preprocessing_sha256",
                  "class_map_sha256", "calibration_sha256"):
        _require(_sha(freeze_record.get(field)), f"congelamiento sin {field}")
    threshold = freeze_record.get("threshold", {})
    _require(threshold.get("selected_on") == "VAL", "umbral no seleccionado exclusivamente en VAL")
    _require(type(threshold.get("value")) in (int, float), "umbral no congelado")


def calculate_external_metrics(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calcula límites enteros G0; abstenciones/fallos de tizón son falsos negativos."""
    counts = Counter(row.get("stratum_code") for row in results)
    _require(dict(counts) == EXTERNAL_COUNTS, f"denominadores EXTERNAL distintos: {dict(counts)}")
    class_rows = {code: [r for r in results if r.get("stratum_code") == code]
                  for code in EXTERNAL_COUNTS}

    def published(row: Mapping[str, Any]) -> str | None:
        value = row.get("published_diagnosis")
        return value if value in PUBLISHABLE else None

    tp: dict[str, int] = {}
    recall: dict[str, float] = {}
    f1: dict[str, float] = {}
    for code in sorted(PUBLISHABLE):
        tp[code] = sum(published(row) == code for row in class_rows[code])
        fn = EXTERNAL_COUNTS[code] - tp[code]
        fp = sum(published(row) == code for row in results if row.get("stratum_code") != code)
        recall[code] = tp[code] / EXTERNAL_COUNTS[code]
        precision = tp[code] / (tp[code] + fp) if tp[code] + fp else 0.0
        f1[code] = 2 * precision * recall[code] / (precision + recall[code]) if precision + recall[code] else 0.0
        _require(fn >= 0, "conteo de falsos negativos inválido")
    healthy_published = sum(published(row) is not None for row in class_rows["POTATO_HEALTHY"])
    healthy_rejected = sum(row.get("final_state") == "NO_CONCLUYENTE"
                           for row in class_rows["POTATO_HEALTHY"])
    other_published = sum(published(row) is not None for row in class_rows["OTHER_CROP"])
    macro_f1 = sum(f1.values()) / 2
    return {
        "denominators": EXTERNAL_COUNTS.copy(),
        "true_positive": tp,
        "recall": recall,
        "f1": f1,
        "macro_f1": macro_f1,
        "healthy_published_blight": {"numerator": healthy_published, "denominator": 50},
        "healthy_no_concluyente": {"numerator": healthy_rejected, "denominator": 50},
        "other_crop_published_blight": {"numerator": other_published, "denominator": 194},
        "criteria": {
            "macro_f1": macro_f1 >= 0.75,
            "early_recall": tp["POTATO_EARLY_BLIGHT"] >= 32 and recall["POTATO_EARLY_BLIGHT"] >= 0.75,
            "late_recall": tp["POTATO_LATE_BLIGHT"] >= 57 and recall["POTATO_LATE_BLIGHT"] >= 0.75,
            "healthy_published": healthy_published <= 5,
            "healthy_rejected": healthy_rejected >= 45,
            "other_crop_published": other_published <= 9,
        },
    }
