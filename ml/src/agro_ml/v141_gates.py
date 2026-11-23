"""Compuertas offline de G0/G1 v1.4.1 sin acceso a TEST ni EXTERNAL."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from agro_ml.v14_gates import validate_provenance_record


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TECHNICAL_CLASSES = (
    "POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT", "POTATO_HEALTHY", "OTHER_CROP",
)
PUBLISHABLE_CLASSES = TECHNICAL_CLASSES[:2]
EXPECTED = {
    "POTATO_EARLY_BLIGHT": {"TRAIN": (541, 136), "VAL": (165, 42)},
    "POTATO_LATE_BLIGHT": {"TRAIN": (499, 129), "VAL": (153, 39)},
    "POTATO_HEALTHY": {"TRAIN": (80, 20), "VAL": (28, 7)},
    "OTHER_CROP": {"TRAIN": (503, 127), "VAL": (150, 38)},
}
EXPECTED_TOTALS = {"TRAIN": (1623, 412), "VAL": (496, 126)}


class V141GateError(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise V141GateError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    _require(protocol.get("protocol_version") == "1.4.1", "se requiere G0 v1.4.1")
    _require(protocol.get("status") == "APPROVED_G0_DESIGN", "G0 no aprobado")
    _require(protocol.get("gates", {}).get("G0") == "CLOSED_APPROVED", "G0 no cerrado")
    _require(tuple(protocol.get("technical_class_map", {}).values()) == TECHNICAL_CLASSES,
             "mapa técnico v1.4.1 inválido")
    _require(tuple(protocol.get("publishable_classes", ())) == PUBLISHABLE_CLASSES,
             "solo ambos tizones pueden publicarse")
    _require(protocol.get("training", {}).get("samples_per_class_per_epoch") == 80 and
             protocol.get("training", {}).get("samples_per_epoch") == 320,
             "sampler 80x4 no aprobado")
    inherited = protocol.get("external_inherited", {})
    for key in ("manifest_sha256", "seal_sha256", "seal_protocol_sha256"):
        _require(bool(SHA256_RE.fullmatch(str(inherited.get(key, "")))),
                 f"referencia EXTERNAL sin {key}")
    _require(inherited.get("access") ==
             "FORBIDDEN_UNTIL_V1_4_1_COMPLETE_FREEZE_AND_EXPLICIT_REVIEW",
             "EXTERNAL no está bloqueado")


def validate_history(history: Mapping[str, Any]) -> None:
    _require(history.get("cycle_version") == "1.4.0", "frontera histórica ausente")
    comparison = history.get("comparison", {})
    _require(comparison.get("decision") == "BLOCKED_NO_CANDIDATE_PASSES_VAL",
             "decisión histórica mutable")
    _require(comparison.get("other_crop_published") == 83 and
             comparison.get("other_crop_denominator") == 150 and
             comparison.get("other_crop_maximum") == 7,
             "fallo 83/150 histórico alterado")
    _require(history.get("freeze_created") is False, "v1.4.0 no tuvo bundle congelado")


def validate_train_val(records: Sequence[Mapping[str, Any]],
                       *, blocked_test_groups: Iterable[str] = ()) -> dict[str, Any]:
    """Valida procedencia, topología y conteos exactos del manifiesto privado."""
    blocked = set(blocked_test_groups)
    _require(bool(records), "manifiesto TRAIN/VAL vacío")
    hashes: set[str] = set()
    groups_by_split: dict[str, set[str]] = defaultdict(set)
    groups_by_cell: dict[tuple[str, str], set[str]] = defaultdict(set)
    photos: dict[tuple[str, str], int] = defaultdict(int)
    for row in records:
        validate_provenance_record(row)
        code, split, group = row.get("stratum_code"), row.get("split"), row.get("split_group")
        _require(code in TECHNICAL_CLASSES, "clase técnica no aprobada")
        _require(split in {"TRAIN", "VAL"}, "TEST/EXTERNAL prohibido en manifiesto")
        _require(row.get("source_id") == "plantvillage", "fuente TRAIN/VAL no aprobada")
        _require(row.get("source_revision") == "9e97599868962bd0079b8db4b7f1efa9185fa1e7",
                 "revisión PlantVillage distinta")
        _require(row.get("license") == "CC-BY-SA-3.0", "licencia aplicable ausente")
        _require(isinstance(group, str) and group and not group.startswith("fallback_"),
                 "leaf_id verificable ausente")
        _require(group not in blocked, "grupo TEST histórico reutilizado")
        _require(row["sha256"] not in hashes, "SHA-256 duplicado")
        hashes.add(row["sha256"])
        groups_by_split[group].add(split)
        groups_by_cell[(code, split)].add(group)
        photos[(code, split)] += 1
    _require(all(len(splits) == 1 for splits in groups_by_split.values()),
             "leaf_id cruza TRAIN/VAL")
    report: dict[str, Any] = {"classes": {}, "totals": {}}
    for code, split_values in EXPECTED.items():
        report["classes"][code] = {}
        for split, (want_photos, want_groups) in split_values.items():
            actual = (photos[(code, split)], len(groups_by_cell[(code, split)]))
            _require(actual == (want_photos, want_groups),
                     f"conteo distinto para {code} {split}: {actual}")
            report["classes"][code][split] = {"photos": actual[0], "groups": actual[1]}
    for split, expected in EXPECTED_TOTALS.items():
        actual = (sum(photos[(code, split)] for code in TECHNICAL_CLASSES),
                  len({group for group, splits in groups_by_split.items() if split in splits}))
        _require(actual == expected, f"total {split} distinto: {actual}")
        report["totals"][split] = {"photos": actual[0], "groups": actual[1]}
    _require(len(records) == 2119, f"se esperaban 2119 filas TRAIN/VAL, hay {len(records)}")
    return report


def verify_pretraining_gate(protocol: Mapping[str, Any], history: Mapping[str, Any],
                            records: Sequence[Mapping[str, Any]],
                            parent_gate: Mapping[str, Any],
                            *, blocked_test_groups: Iterable[str] = ()) -> dict[str, Any]:
    validate_protocol(protocol)
    validate_history(history)
    report = validate_train_val(records, blocked_test_groups=blocked_test_groups)
    inherited = protocol["external_inherited"]
    _require(parent_gate.get("sikkim_external_manifest_sha256") == inherited["manifest_sha256"],
             "hash del manifiesto Sikkim alterado")
    _require(parent_gate.get("external_seal_sha256") == inherited["seal_sha256"],
             "hash del sello Sikkim alterado")
    _require(parent_gate.get("approved_protocol_sha256") == inherited["seal_protocol_sha256"],
             "protocolo padre del sello alterado")
    _require(parent_gate.get("external_access") == "SEALED_NOT_OPENED_FOR_MODELING",
             "Sikkim no permanece sellado")
    return report


def canonical_digest(records: Sequence[Mapping[str, Any]]) -> str:
    payload = "".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")) + "\n" for row in records)
    return sha256_bytes(payload.encode())
