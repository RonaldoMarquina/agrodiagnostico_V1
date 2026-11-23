#!/usr/bin/env python3
"""Inventario privado reproducible de fuentes candidatas EXTERNAL v1.4.3."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from typing import Any
from zipfile import BadZipFile, ZipFile

from PIL import Image, ImageOps, UnidentifiedImageError


PLDD_ARCHIVES = {
    "POTATO_EARLY_BLIGHT": (
        "EB.zip",
        "cffd37bbb79e75c0e23c1486f88f0a7c873b3fe67f643c41db3abd794bdc01e5",
        4803,
        "EB",
    ),
    "POTATO_LATE_BLIGHT": (
        "LB.zip",
        "f4d31182b5d2f147c256e1c73838eac9b17592b89ed2b1ae394f58863e74a447",
        6116,
        "LB",
    ),
    "POTATO_HEALTHY": (
        "Healthy.zip",
        "2b7e4107d7ba03c0ef9636831aa4de7d333435df238f667f562e27b1e46e59e2",
        4600,
        "Healthy",
    ),
}
POTA_ARCHIVE = (
    "AgroGuard_Dataset.zip",
    "b029b6e8e9ffc1c31125401ddb0ae90afba1feb402f0e687466ef709e0b56090",
)
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


class AuditError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dhash(image: Image.Image) -> str:
    gray = ImageOps.exif_transpose(image).convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = list(gray.get_flattened_data())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return f"{value:016x}"


def inspect_bytes(content: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    try:
        with Image.open(io.BytesIO(content)) as image:
            fmt = image.format
            mode = image.mode
            frames = int(getattr(image, "n_frames", 1))
            width, height = image.size
            image.seek(0)
            image.load()
            visual_hash = dhash(image)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return {
            "sha256": digest,
            "decode_status": "REJECTED_NOT_DECODABLE",
            "decode_error": type(exc).__name__,
        }
    return {
        "sha256": digest,
        "decode_status": "DECODED",
        "format": fmt,
        "mode": mode,
        "width": width,
        "height": height,
        "frames": frames,
        "dhash64": visual_hash,
    }


def load_protected(images_root: Path) -> tuple[set[str], list[tuple[str, int]]]:
    hashes: set[str] = set()
    visual: list[tuple[str, int]] = []
    if not images_root.is_dir():
        return hashes, visual
    for path in sorted(images_root.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        require(path.stem == digest, "imagen protegida no está nombrada por SHA-256")
        result = inspect_bytes(content)
        require(result.get("decode_status") == "DECODED", "imagen protegida no decodificable")
        hashes.add(digest)
        visual.append((digest, int(result["dhash64"], 16)))
    return hashes, visual


class VisualIndex:
    def __init__(self, known: list[tuple[str, int]] | None = None):
        self.values: dict[str, int] = {}
        self.bands: list[dict[int, set[str]]] = [defaultdict(set) for _ in range(8)]
        for key, value in known or ():
            self.add(key, value)

    def add(self, key: str, value: int) -> None:
        self.values[key] = value
        for index in range(8):
            self.bands[index][(value >> (index * 8)) & 0xFF].add(key)

    def near(self, value: int, maximum_distance: int = 6) -> list[tuple[str, int]]:
        candidates: set[str] = set()
        for index in range(8):
            candidates.update(self.bands[index].get((value >> (index * 8)) & 0xFF, ()))
        matches = []
        for key in candidates:
            distance = (value ^ self.values[key]).bit_count()
            if distance <= maximum_distance:
                matches.append((key, distance))
        return sorted(matches, key=lambda item: (item[1], item[0]))


def inventory_pldd(root: Path, protected_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    protected_hashes, protected_visual = load_protected(protected_root)
    protected_index = VisualIndex(protected_visual)
    records: list[dict[str, Any]] = []
    archive_evidence = {}
    for stratum, (filename, expected_sha, expected_count, topdir) in PLDD_ARCHIVES.items():
        archive = root / filename
        require(archive.is_file() and not archive.is_symlink(), f"archivo PLDD-UP ausente: {filename}")
        actual_sha = sha256_file(archive)
        require(actual_sha == expected_sha, f"SHA oficial PLDD-UP distinto: {filename}")
        archive_evidence[filename] = {
            "sha256": actual_sha,
            "size": archive.stat().st_size,
            "expected_count": expected_count,
        }
        try:
            with ZipFile(archive) as source:
                entries = [item for item in source.infolist() if not item.is_dir()]
                require(len(entries) == expected_count, f"conteo PLDD-UP distinto: {filename}")
                for entry_index, item in enumerate(entries, start=1):
                    relative = PurePosixPath(item.filename)
                    require(not relative.is_absolute() and ".." not in relative.parts and
                            relative.parts[0] == topdir,
                            f"ruta PLDD-UP insegura: {item.filename}")
                    content = source.read(item)
                    result = inspect_bytes(content)
                    record = {
                        "source_id": "pldd-up",
                        "source_version": "1",
                        "archive": filename,
                        "archive_sha256": actual_sha,
                        "source_path": relative.as_posix(),
                        "file_size": item.file_size,
                        "compressed_size": item.compress_size,
                        "stratum_code": stratum,
                        "source_label": topdir,
                        **result,
                    }
                    if result.get("decode_status") != "DECODED":
                        record.update(decision="EXCLUDED", decision_reason="NOT_DECODABLE")
                    elif relative.suffix.lower() not in ALLOWED_SUFFIXES:
                        record.update(decision="EXCLUDED", decision_reason="UNSUPPORTED_EXTENSION")
                    elif not (200 <= result["width"] <= 6000 and 200 <= result["height"] <= 6000):
                        record.update(decision="EXCLUDED", decision_reason="DIMENSION_OUT_OF_CONTRACT")
                    elif result["sha256"] in protected_hashes:
                        record.update(decision="EXCLUDED", decision_reason="EXACT_DUPLICATE_PROTECTED_TRAIN_VAL")
                    else:
                        near = protected_index.near(int(result["dhash64"], 16))
                        record.update(
                            decision="CANDIDATE_PENDING_INTERNAL_REVIEW",
                            decision_reason="SOURCE_LABEL_AND_FILE_VALID_PENDING_DEDUP_REVIEW",
                            protected_near_matches=[{"sha256": key, "distance": distance}
                                                    for key, distance in near[:10]],
                        )
                    records.append(record)
                    if entry_index % 250 == 0 or entry_index == len(entries):
                        print(
                            f"AUDIT_PROGRESS {filename} {entry_index}/{len(entries)}",
                            file=sys.stderr,
                            flush=True,
                        )
        except BadZipFile as exc:
            raise AuditError(f"ZIP PLDD-UP inválido: {filename}") from exc

    exact_counts = Counter(record["sha256"] for record in records)
    exact_duplicate_hashes = {digest for digest, count in exact_counts.items() if count > 1}
    visual_index = VisualIndex()
    visual_groups: dict[str, set[str]] = {}

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

    sorted_records = sorted(records, key=lambda item: (item.get("sha256", ""), item["source_path"]))
    for record_index, record in enumerate(sorted_records, start=1):
        if record.get("decode_status") != "DECODED":
            continue
        digest = record["sha256"]
        value = int(record["dhash64"], 16)
        for other, _ in visual_index.near(value):
            union(digest, other)
        visual_index.add(digest, value)
        if record_index % 1000 == 0 or record_index == len(sorted_records):
            print(
                f"AUDIT_PROGRESS visual-dedup {record_index}/{len(sorted_records)}",
                file=sys.stderr,
                flush=True,
            )
    for digest in visual_index.values:
        visual_groups.setdefault(find(digest), set()).add(digest)
    group_id = {}
    for members in visual_groups.values():
        identifier = "visual:" + min(members)[:16]
        for digest in members:
            group_id[digest] = identifier
    group_sizes = Counter(group_id.values())

    for record in records:
        digest = record.get("sha256")
        if not digest:
            continue
        record["visual_group"] = group_id.get(digest)
        record["visual_group_size"] = group_sizes.get(group_id.get(digest), 0)
        if digest in exact_duplicate_hashes and record.get("decision") != "EXCLUDED":
            record.update(decision="EXCLUDED", decision_reason="EXACT_DUPLICATE_WITHIN_PLDD_UP")
        elif record.get("protected_near_matches") and record.get("decision") != "EXCLUDED":
            record.update(decision="EXCLUDED", decision_reason="VISUAL_NEAR_DUPLICATE_PROTECTED_TRAIN_VAL")

    summary = {
        "schema_version": 1,
        "source_id": "pldd-up",
        "source_version": "1",
        "doi": "10.17632/3j4nfkvp2n.1",
        "source_url": "https://data.mendeley.com/datasets/3j4nfkvp2n/1",
        "license": "CC BY 4.0",
        "license_evidence_url": "https://data.mendeley.com/datasets/3j4nfkvp2n/1#licence",
        "archive_evidence": archive_evidence,
        "record_count": len(records),
        "counts_by_stratum": dict(sorted(Counter(r["stratum_code"] for r in records).items())),
        "decode_status": dict(sorted(Counter(r["decode_status"] for r in records).items())),
        "formats": dict(sorted(Counter(r.get("format", "UNKNOWN") for r in records).items())),
        "modes": dict(sorted(Counter(r.get("mode", "UNKNOWN") for r in records).items())),
        "dimensions": dict(sorted(Counter(f'{r.get("width")}x{r.get("height")}' for r in records).items(),
                                  key=lambda item: (-item[1], item[0]))[:30]),
        "decisions": dict(sorted(Counter(r["decision"] for r in records).items())),
        "decision_reasons": dict(sorted(Counter(r["decision_reason"] for r in records).items())),
        "exact_duplicate_hashes": len(exact_duplicate_hashes),
        "visual_groups_multiple": sum(size > 1 for size in group_sizes.values()),
        "protected_reference_count": len(protected_hashes),
        "independence_unit_available": "UNIQUE_IMAGE_ONLY_NOT_PLANT_OR_SESSION",
        "label_review_status": "SOURCE_FOLDER_LABEL_PLUS_INTERNAL_QUALITY_REVIEW_PENDING",
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    return records, summary


def inventory_pota(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filename, expected_sha = POTA_ARCHIVE
    archive = root / filename
    require(archive.is_file() and not archive.is_symlink(), "archivo Pota-Toma-To ausente")
    actual_sha = sha256_file(archive)
    require(actual_sha == expected_sha, "SHA oficial Pota-Toma-To distinto")
    records = []
    with ZipFile(archive) as source:
        raw_entries = [item for item in source.infolist()
                       if not item.is_dir() and "/Raw_Dataset/" in item.filename]
        processed_count = sum(not item.is_dir() and "/Advanced_Processed_Dataset/" in item.filename
                              for item in source.infolist())
        description = source.read("AgroGuard_Dataset/data_description.md").decode("utf-8")
        for item in raw_entries:
            content = source.read(item)
            result = inspect_bytes(content)
            label = PurePosixPath(item.filename).parts[-2]
            records.append({
                "source_id": "pota-toma-to",
                "source_version": "1",
                "archive": filename,
                "archive_sha256": actual_sha,
                "source_path": item.filename,
                "file_size": item.file_size,
                "source_label": label,
                **result,
                "decision": "EXCLUDED",
                "decision_reason": "THIRD_PARTY_ORIGIN_AND_PER_IMAGE_RIGHTS_NOT_DOCUMENTED",
            })
    summary = {
        "schema_version": 1,
        "source_id": "pota-toma-to",
        "source_version": "1",
        "doi": "10.17632/354fsxwccb.1",
        "source_url": "https://data.mendeley.com/datasets/354fsxwccb/1",
        "repository_license": "CC BY 4.0",
        "repository_license_limitation": "Further permission may be required for third-party content",
        "archive_sha256": actual_sha,
        "archive_size": archive.stat().st_size,
        "raw_record_count": len(records),
        "processed_derivative_count": processed_count,
        "raw_counts_by_label": dict(sorted(Counter(r["source_label"] for r in records).items())),
        "formats": dict(sorted(Counter(r.get("format", "UNKNOWN") for r in records).items())),
        "modes": dict(sorted(Counter(r.get("mode", "UNKNOWN") for r in records).items())),
        "decision": "EXCLUDED_SOURCE",
        "decision_reason": "Raw folders identify Google Search and data_description says images were aggregated from public repositories without per-file author, URL or license",
        "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
        "audited_at": datetime.now(timezone.utc).isoformat(),
    }
    return records, summary


def write_private(output: Path, records: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    require(not output.exists(), f"salida privada ya existe: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v143-audit-", dir=output.parent) as temporary:
        stage = Path(temporary)
        inventory = b"".join((json.dumps(record, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")) + "\n").encode()
                             for record in records)
        (stage / "inventory.jsonl").write_bytes(inventory)
        summary["inventory_sha256"] = hashlib.sha256(inventory).hexdigest()
        (stage / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        os.chmod(stage / "inventory.jsonl", 0o600)
        os.chmod(stage / "summary.json", 0o600)
        Path(temporary).rename(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pldd-root", required=True)
    parser.add_argument("--pota-root", required=True)
    parser.add_argument("--protected-images", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    output = Path(args.output_root)
    require(not output.exists(), "raíz de auditoría ya existe")
    output.mkdir(parents=True, mode=0o700)
    try:
        pldd_records, pldd_summary = inventory_pldd(Path(args.pldd_root), Path(args.protected_images))
        write_private(output / "pldd-up-v1", pldd_records, pldd_summary)
        pota_records, pota_summary = inventory_pota(Path(args.pota_root))
        write_private(output / "pota-toma-to-v1", pota_records, pota_summary)
    except Exception:
        (output / "FAILED").write_text("Audit failed before admission. No source is admitted.\n")
        raise
    print(json.dumps({"status": "AUDIT_COMPLETE_NO_ADMISSION",
                      "pldd": pldd_summary, "pota_toma_to": pota_summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
