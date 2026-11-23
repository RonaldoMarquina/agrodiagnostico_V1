#!/usr/bin/env python3
"""Selecciona y materializa en privado un candidato EXTERNAL v1.4.3 revisable."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageOps

from audit_v143_sources import VisualIndex, require


QUOTAS = {
    "POTATO_EARLY_BLIGHT": 50,
    "POTATO_LATE_BLIGHT": 50,
    "POTATO_HEALTHY": 50,
    "OTHER_CROP": 200,
}
CORN_LABEL_QUOTA = {
    "asphalt_stain": 40,
    "bipolaris": 40,
    "common_rust": 40,
    "healthy": 40,
    "stenocarpella": 40,
}
PLDD_SOURCE_URL = "https://data.mendeley.com/datasets/3j4nfkvp2n/1"
CORN_SOURCE_URL = "https://data.mendeley.com/datasets/w56xxnykcc/1"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def round_robin_by_plantation(rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    groups: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: (item["plantation_block"], item["sha256"])):
        groups[row["plantation_block"]].append(row)
    while groups:
        for key in sorted(list(groups)):
            yield groups[key].popleft()
            if not groups[key]:
                del groups[key]


def choose(rows: Iterable[dict[str, Any]], quota: int, visual: VisualIndex,
           excluded: set[str], selected_groups: set[str],
           conflicting_groups: set[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        if row["sha256"] in excluded or row["decision"] != "CANDIDATE_PENDING_INTERNAL_REVIEW":
            continue
        group = str(row.get("visual_group") or row["sha256"])
        value = int(row["dhash64"], 16)
        if group in conflicting_groups or group in selected_groups or visual.near(value):
            continue
        selected.append(row)
        selected_groups.add(group)
        visual.add(row["sha256"], value)
        if len(selected) == quota:
            return selected
    raise ValueError(f"candidatos únicos insuficientes: {len(selected)}/{quota}")


def extract_pldd(row: dict[str, Any], archive_root: Path) -> bytes:
    archive = archive_root / row["archive"]
    with ZipFile(archive) as source:
        content = source.read(row["source_path"])
    require(hashlib.sha256(content).hexdigest() == row["sha256"], "PLDD cambió tras auditoría")
    return content


def read_corn(row: dict[str, Any], source_root: Path) -> bytes:
    suffix = PurePosixPath(row["source_path"]).suffix.lower()
    path = source_root / "images" / f"{row['sha256']}{suffix}"
    content = path.read_bytes()
    require(hashlib.sha256(content).hexdigest() == row["sha256"], "CornLeaf cambió tras auditoría")
    return content


def contact_sheets(rows: list[dict[str, Any]], content_by_sha: dict[str, bytes], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    columns, rows_per_sheet, cell, label_height = 5, 5, 180, 32
    per_sheet = columns * rows_per_sheet
    for page, start in enumerate(range(0, len(rows), per_sheet), start=1):
        sheet = Image.new("RGB", (columns * cell, rows_per_sheet * (cell + label_height)), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, row in enumerate(rows[start:start + per_sheet]):
            with Image.open(io.BytesIO(content_by_sha[row["sha256"]])) as image:
                preview = ImageOps.exif_transpose(image).convert("RGB")
                preview.thumbnail((cell - 8, cell - 8), Image.Resampling.LANCZOS)
            x = (offset % columns) * cell
            y = (offset // columns) * (cell + label_height)
            sheet.paste(preview, (x + (cell - preview.width) // 2, y + (cell - preview.height) // 2))
            draw.text((x + 4, y + cell + 2), f"{start + offset + 1:03d} {row['stratum_code'][:8]}", fill="black")
            draw.text((x + 4, y + cell + 15), row["sha256"][:16], fill="black")
        sheet.save(output / f"contact-sheet-{page:02d}.jpg", quality=92)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pldd-inventory", required=True)
    parser.add_argument("--corn-inventory", required=True)
    parser.add_argument("--pldd-source", required=True)
    parser.add_argument("--corn-source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--exclude-sha")
    parser.add_argument("--approved-review", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    require(not output.exists(), "salida de selección ya existe")
    excluded = set()
    if args.exclude_sha:
        excluded = {line.strip() for line in Path(args.exclude_sha).read_text().splitlines() if line.strip()}

    pldd = read_jsonl(Path(args.pldd_inventory))
    corn = read_jsonl(Path(args.corn_inventory))
    strata_by_group: dict[str, set[str]] = defaultdict(set)
    for row in pldd:
        if row.get("visual_group"):
            strata_by_group[row["visual_group"]].add(row["stratum_code"])
    conflicting_groups = {group for group, strata in strata_by_group.items() if len(strata) > 1}
    visual = VisualIndex()
    selected_groups: set[str] = set()
    selected: list[dict[str, Any]] = []
    for stratum in ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT", "POTATO_HEALTHY"):
        candidates = sorted((row for row in pldd if row["stratum_code"] == stratum),
                            key=lambda item: item["sha256"])
        selected.extend(choose(candidates, QUOTAS[stratum], visual, excluded,
                               selected_groups, conflicting_groups))
    for label, quota in CORN_LABEL_QUOTA.items():
        candidates = round_robin_by_plantation(row for row in corn if row["source_label"] == label)
        selected.extend(choose(candidates, quota, visual, excluded,
                               selected_groups, conflicting_groups))
    require(len(selected) == sum(QUOTAS.values()), "cardinalidad seleccionada incorrecta")
    minimum_visual_distance = min(
        (int(left["dhash64"], 16) ^ int(right["dhash64"], 16)).bit_count()
        for index, left in enumerate(selected)
        for right in selected[index + 1:]
    )
    require(minimum_visual_distance > 6, "selección contiene un duplicado visual cercano")

    files_dir = output / "images" / "files"
    files_dir.mkdir(parents=True, mode=0o700)
    content_by_sha: dict[str, bytes] = {}
    manifest: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        is_pldd = row["source_id"] == "pldd-up"
        content = (extract_pldd(row, Path(args.pldd_source)) if is_pldd
                   else read_corn(row, Path(args.corn_source)))
        content_by_sha[row["sha256"]] = content
        suffix = PurePosixPath(row["source_path"]).suffix.lower()
        relative = f"files/{row['sha256']}{suffix}"
        target = output / "images" / relative
        target.write_bytes(content)
        os.chmod(target, 0o600)
        approved = args.approved_review
        manifest.append({
            "image_id": f"v143-external-{index:04d}-{row['sha256'][:12]}",
            "sha256": row["sha256"],
            "file_size": len(content),
            "source_id": row["source_id"],
            "source_version": row["source_version"],
            "source_url": PLDD_SOURCE_URL if is_pldd else CORN_SOURCE_URL,
            "license": "CC BY 4.0",
            "license_evidence_url": LICENSE_URL,
            "source_path": relative,
            "original_source_path": row["source_path"],
            "source_label": row["source_label"],
            "stratum_code": row["stratum_code"],
            "capture_origin": ("UTTAR_PRADESH_FIELD_UNSPECIFIED" if is_pldd
                               else row["capture_origin"]),
            "independence_unit": f"UNIQUE_IMAGE_SHA256:{row['sha256']}",
            "independence_limitation": "NO_PLANT_OR_SESSION_IDENTIFIER",
            "label_review": ("SOURCE_LABEL_PLUS_INTERNAL_VISUAL_QUALITY_REVIEW"
                             if approved else "PENDING_INTERNAL_VISUAL_QUALITY_REVIEW"),
            "decision": "ADMITTED" if approved else "PENDING_INTERNAL_REVIEW",
            "decision_reason": ("RIGHTS_LABEL_TECHNICAL_QUALITY_AND_DEDUP_PASSED"
                                if approved else "CONTACT_SHEET_REVIEW_REQUIRED"),
            "visual_group": row["visual_group"],
            "dhash64": row["dhash64"],
        })

    output.mkdir(parents=True, exist_ok=True)
    filename = "manifest.jsonl" if args.approved_review else "candidate-manifest.jsonl"
    manifest_bytes = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")) + "\n").encode()
                                for row in manifest)
    (output / filename).write_bytes(manifest_bytes)
    os.chmod(output / filename, 0o600)
    contact_sheets(manifest, content_by_sha, output / "contact-sheets")
    summary = {
        "status": "ADMITTED_MANIFEST" if args.approved_review else "PENDING_CONTACT_SHEET_REVIEW",
        "counts_by_stratum": {key: sum(row["stratum_code"] == key for row in manifest)
                              for key in QUOTAS},
        "counts_by_source": {source: sum(row["source_id"] == source for row in manifest)
                             for source in ("pldd-up", "cornleaf-manabi")},
        "counts_by_corn_label": {label: sum(row["source_label"] == label for row in manifest)
                                 for label in CORN_LABEL_QUOTA},
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "excluded_by_internal_review": sorted(excluded),
        "cross_label_visual_groups_excluded": len(conflicting_groups),
        "minimum_pairwise_dhash_distance": minimum_visual_distance,
        "weights_or_model_loaded": False,
        "predictions_generated": False,
        "metrics_generated": False,
    }
    (output / "selection-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    os.chmod(output / "selection-summary.json", 0o600)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
