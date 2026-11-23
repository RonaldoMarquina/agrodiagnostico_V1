#!/usr/bin/env python3
"""Audita CornLeafDiseaseCollection v1 como candidato OTHER_CROP privado."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_v143_sources import VisualIndex, inspect_bytes, load_protected, require, write_private


DATASET_ID = "w56xxnykcc"
SOURCE_URL = "https://data.mendeley.com/datasets/w56xxnykcc/1"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
CSV_SHA256 = "7153fb6c64ec93105630e5b993bc20974bd99cc261011795a4bfed85d7c11fba"
README_SHA256 = "51c6c977cd1dcdef729ae02b7887f5df7bd1c24c647c2c717df0c09eb2f31d26"


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_csv(path: Path) -> tuple[dict[str, dict[str, str]], int]:
    require(sha256_file(path) == CSV_SHA256, "SHA-256 de Data.csv distinto del oficial")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        raw_rows = [row for row in csv.DictReader(stream, delimiter=";") if row.get("filename")]
    filename_whitespace = sum(row["filename"] != row["filename"].strip() for row in raw_rows)
    rows = [{key: value.strip() for key, value in row.items()} for row in raw_rows]
    require(len(rows) == 1079, "Data.csv no contiene exactamente 1.079 imágenes")
    by_name = {row["filename"]: row for row in rows}
    require(len(by_name) == len(rows), "Data.csv contiene filenames duplicados")
    return by_name, filename_whitespace


def audit(source: Path, protected_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata_path = source / "source-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    require(metadata["id"] == DATASET_ID and metadata["version"] == 1, "revisión Mendeley incorrecta")
    require(metadata["doi"]["id"] == "10.17632/w56xxnykcc.1", "DOI incorrecto")
    require(metadata["data_licence"]["short_name"] == "CC BY 4.0", "licencia inesperada")
    require(sha256_file(source / "Readme.txt") == README_SHA256, "SHA-256 de Readme distinto")
    csv_rows, filename_whitespace = load_csv(source / "Data.csv")
    image_rows = [row for row in metadata["files"]
                  if row["content_details"]["content_type"].startswith("image/")]
    require(len(image_rows) == 1079, "manifiesto oficial no contiene 1.079 imágenes")
    require({row["filename"] for row in image_rows} == set(csv_rows),
            "Data.csv y manifiesto oficial no identifican las mismas imágenes")

    protected_hashes, protected_visual = load_protected(protected_root)
    protected_index = VisualIndex(protected_visual)
    records: list[dict[str, Any]] = []
    for index, row in enumerate(sorted(image_rows, key=lambda item: item["filename"]), start=1):
        details = row["content_details"]
        expected = details["sha256_hash"]
        path = source / "images" / f"{expected}{Path(row['filename']).suffix.lower()}"
        require(path.is_file() and not path.is_symlink(), f"imagen ausente: {row['filename']}")
        content = path.read_bytes()
        result = inspect_bytes(content)
        require(result["sha256"] == expected, f"SHA-256 distinto: {row['filename']}")
        require(len(content) == details["size"], f"tamaño distinto: {row['filename']}")
        csv_row = csv_rows[row["filename"]]
        record: dict[str, Any] = {
            "source_id": "cornleaf-manabi",
            "source_version": "1",
            "source_url": SOURCE_URL,
            "source_file_id": row["id"],
            "source_path": row["filename"],
            "license": "CC BY 4.0",
            "license_url": LICENSE_URL,
            "file_size": len(content),
            "stratum_code": "OTHER_CROP",
            "source_label": csv_row["multiclass_label"],
            "binary_label": csv_row["binary_label"],
            "plantation_block": csv_row["plantation_block"],
            "corn_variety": csv_row["corn_variety"],
            "location_canton": csv_row["location_canton"],
            "capture_origin": (
                f"{csv_row['location_canton']}:{csv_row['plantation_block']}:"
                f"{csv_row['location_latitude']}:{csv_row['location_longitude']}"
            ),
            "independence_unit": f"UNIQUE_IMAGE:{row['id']}",
            "independence_limitation": "NO_PLANT_OR_SESSION_IDENTIFIER",
            **result,
        }
        if result.get("decode_status") != "DECODED":
            record.update(decision="EXCLUDED", decision_reason="NOT_DECODABLE")
        elif not (200 <= result["width"] <= 6000 and 200 <= result["height"] <= 6000):
            record.update(decision="EXCLUDED", decision_reason="DIMENSION_OUT_OF_CONTRACT")
        elif expected in protected_hashes:
            record.update(decision="EXCLUDED", decision_reason="EXACT_DUPLICATE_PROTECTED_TRAIN_VAL")
        else:
            near = protected_index.near(int(result["dhash64"], 16))
            if near:
                record.update(
                    decision="EXCLUDED",
                    decision_reason="VISUAL_NEAR_DUPLICATE_PROTECTED_TRAIN_VAL",
                    protected_near_matches=[{"sha256": digest, "distance": distance}
                                            for digest, distance in near[:10]],
                )
            else:
                record.update(
                    decision="CANDIDATE_PENDING_INTERNAL_REVIEW",
                    decision_reason="AUTHOR_CAPTURE_AND_CC_BY_CONFIRMED_PENDING_VISUAL_REVIEW",
                )
        records.append(record)
        if index % 100 == 0 or index == len(image_rows):
            print(f"AUDIT_PROGRESS cornleaf {index}/{len(image_rows)}", flush=True)

    exact_counts = Counter(record["sha256"] for record in records)
    visual_index = VisualIndex()
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for record in sorted(records, key=lambda item: item["sha256"]):
        if record.get("decode_status") != "DECODED":
            continue
        digest = record["sha256"]
        visual = int(record["dhash64"], 16)
        for other, _ in visual_index.near(visual):
            union(digest, other)
        visual_index.add(digest, visual)
    groups: dict[str, set[str]] = defaultdict(set)
    for digest in visual_index.values:
        groups[find(digest)].add(digest)
    group_for: dict[str, str] = {}
    group_sizes: Counter[str] = Counter()
    for members in groups.values():
        group = "visual:" + min(members)[:16]
        group_sizes[group] = len(members)
        for digest in members:
            group_for[digest] = group
    for record in records:
        digest = record["sha256"]
        group = group_for.get(digest)
        record["visual_group"] = group
        record["visual_group_size"] = group_sizes.get(group, 0)
        if exact_counts[digest] > 1 and record["decision"] != "EXCLUDED":
            record.update(decision="EXCLUDED", decision_reason="EXACT_DUPLICATE_WITHIN_SOURCE")

    summary = {
        "schema_version": 1,
        "source_id": "cornleaf-manabi",
        "source_version": "1",
        "doi": "10.17632/w56xxnykcc.1",
        "source_url": SOURCE_URL,
        "authors": [
            "Leonela Marilù Murillo Parraga",
            "Carlos Alfredo Silva Villafuerte",
        ],
        "license": "CC BY 4.0",
        "license_url": LICENSE_URL,
        "rights_basis": "Dataset description states all photographs were taken for this collection; no file is identified as third-party content",
        "metadata_sha256": sha256_file(metadata_path),
        "csv_sha256": CSV_SHA256,
        "readme_sha256": README_SHA256,
        "csv_filename_whitespace_normalized": filename_whitespace,
        "record_count": len(records),
        "counts_by_source_label": dict(sorted(Counter(r["source_label"] for r in records).items())),
        "counts_by_plantation": dict(sorted(Counter(r["plantation_block"] for r in records).items())),
        "decode_status": dict(sorted(Counter(r["decode_status"] for r in records).items())),
        "formats": dict(sorted(Counter(r.get("format", "UNKNOWN") for r in records).items())),
        "modes": dict(sorted(Counter(r.get("mode", "UNKNOWN") for r in records).items())),
        "decisions": dict(sorted(Counter(r["decision"] for r in records).items())),
        "decision_reasons": dict(sorted(Counter(r["decision_reason"] for r in records).items())),
        "exact_duplicate_hashes": sum(count > 1 for count in exact_counts.values()),
        "visual_groups_multiple": sum(size > 1 for size in group_sizes.values()),
        "protected_reference_count": len(protected_hashes),
        "independence_unit_available": "UNIQUE_IMAGE_ONLY_NOT_PLANT_OR_SESSION",
        "label_review_status": "AUTHOR_METADATA_PLUS_INTERNAL_QUALITY_REVIEW_PENDING",
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    return records, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--protected-images", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    records, summary = audit(Path(args.source), Path(args.protected_images))
    write_private(Path(args.output), records, summary)
    print(json.dumps({"status": "AUDIT_COMPLETE_NO_ADMISSION", "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
