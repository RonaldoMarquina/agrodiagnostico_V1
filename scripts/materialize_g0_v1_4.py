#!/usr/bin/env python3
"""Materializa G1 v1.4.0 en almacenamiento privado; nunca entrena ni evalúa."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import mkdtemp
from xml.etree import ElementTree
from zipfile import ZipFile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from agro_ml.data.grouping import DEFAULT_HAMMING_THRESHOLD, compute_dhash
from agro_ml.v14_gates import (
    build_external_seal,
    sha256_bytes,
    validate_plantvillage_train_val,
    verify_pretraining_gate,
)


SIKKIM_ARCHIVE_SHA256 = "5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc"
PV_REVISION = "9e97599868962bd0079b8db4b7f1efa9185fa1e7"
PV_RIGHTS_SHA256 = "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb"
PV_SOURCE_URL = "https://huggingface.co/datasets/mohanty/PlantVillage/commit/9e97599868962bd0079b8db4b7f1efa9185fa1e7"
SIKKIM_SOURCE_URL = "https://data.mendeley.com/datasets/4wz7zbk635/1"
SIKKIM_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def jsonl_bytes(records: list[dict]) -> bytes:
    return ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")) + "\n" for row in records)).encode("utf-8")


def read_xlsx_rows(path: Path) -> list[list[str]]:
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as archive:
        shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(node.itertext()) for node in shared_root.findall("x:si", namespace)]
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in sheet.findall(".//x:sheetData/x:row", namespace):
        values: list[str] = []
        for cell in row.findall("x:c", namespace):
            value = cell.find("x:v", namespace)
            raw = "" if value is None or value.text is None else value.text
            values.append(shared[int(raw)] if cell.get("t") == "s" else raw)
        rows.append(values)
    return rows


def potato_labels(root: Path) -> dict[str, str]:
    rows = read_xlsx_rows(root / "Potato_Field_Dataset" / "Annotations.xlsx")
    if not rows or len(rows[0]) < 3:
        raise ValueError("Annotations.xlsx inválido")
    labels: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) < 3:
            raise ValueError("Fila de anotación incompleta")
        labels[row[1]] = row[2]
    return labels


def classify_sikkim(path: Path, root: Path, annotations: dict[str, str]) -> tuple[str, str]:
    relative = path.relative_to(root)
    if relative.parts[0] == "Potato_Field_Dataset":
        label = annotations.get(path.name)
        mapping = {
            "Early Blight": "POTATO_EARLY_BLIGHT",
            "Late Blight": "POTATO_LATE_BLIGHT",
            "Healthy": "POTATO_HEALTHY",
        }
        if label not in mapping:
            raise ValueError(f"Etiqueta de papa desconocida para {relative}: {label}")
        return label, mapping[label]
    if relative.parts[0] == "Tomato_Pepper_Field_Dataset" and len(relative.parts) == 3:
        return relative.parts[1], "OTHER_CROP"
    raise ValueError(f"Ruta Sikkim inesperada: {relative}")


def build_external_registry(sikkim_root: Path) -> list[dict]:
    annotations = potato_labels(sikkim_root)
    paths = sorted(path for path in sikkim_root.rglob("*")
                   if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    records: list[dict] = []
    for path in paths:
        digest = file_sha(path)
        source_label, stratum = classify_sikkim(path, sikkim_root, annotations)
        with Image.open(path) as image:
            image.load()
            width, height = image.size
        relative = path.relative_to(sikkim_root).as_posix()
        records.append({
            "image_id": f"sikkim:{digest}",
            "sha256": digest,
            "source_id": "sikkim-solanaceae-v1",
            "source_revision": "10.17632/4wz7zbk635.1",
            "source_url": SIKKIM_SOURCE_URL,
            "author": "Kishor Chettri; Sikkim University",
            "license": "CC-BY-4.0",
            "license_url": SIKKIM_LICENSE_URL,
            "source_path": relative,
            "split": "EXTERNAL",
            "split_group": f"sikkim-image:{digest}",
            "decision": "ADMIT_EXTERNAL",
            "decision_reason": "Pinned v1 file, applicable CC BY 4.0, decoded bytes and reconciled publisher label",
            "rights_proof_path": "source-proof.json",
            "source_label": source_label,
            "stratum_code": stratum,
            "independence_unit": "UNIQUE_IMAGE_ONLY_NOT_PLANT",
            "plant_id": None,
            "session_id": None,
            "width": width,
            "height": height,
            "file_size": path.stat().st_size,
            "label_review": "PUBLISHER_ANNOTATION_AND_INTERNAL_DECODE_AMBIGUITY_CONTROL; NO_NEW_INDEPENDENT_AGRONOMIC_REVIEW",
        })
    return records


def build_plantvillage_reference(package: Path) -> tuple[list[dict], set[str]]:
    with (package / "strata.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    evidence = {row["sha256"]: row for row in json.loads((package / "evidence.json").read_text())["records"]}
    blocked_test_groups = {row["split_group"] for row in rows if row["split"] == "TEST"}
    selected: list[dict] = []
    for row in rows:
        if row["split"] not in {"TRAIN", "VAL"}:
            continue
        if row["stratum_code"] == "OTHER_CROP" and row["split"] != "VAL":
            continue
        proof = evidence.get(row["sha256"])
        if not proof or proof.get("decision") != "ADMIT":
            raise ValueError("Evidencia PlantVillage por archivo ausente")
        original_proof = package / str(proof.get("rights", {}).get("proof_path", ""))
        if not original_proof.is_file() or file_sha(original_proof) != PV_RIGHTS_SHA256:
            raise ValueError("Comprobante PlantVillage ausente o alterado")
        image_path = package / row["relative_path"]
        if file_sha(image_path) != row["sha256"]:
            raise ValueError("Bytes PlantVillage cambiaron")
        selected.append({
            "image_id": f"plantvillage:{row['sha256']}",
            "sha256": row["sha256"],
            "source_id": "plantvillage",
            "source_revision": PV_REVISION,
            "source_url": PV_SOURCE_URL,
            "author": "David P. Hughes; Marcel Salathé; Sharada P. Mohanty",
            "license": "CC-BY-SA-3.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
            "source_path": proof["source_original_path"],
            "split": row["split"],
            "split_group": row["split_group"],
            "decision": "ADMIT_TRAIN_VAL",
            "decision_reason": proof["decision_reason"],
            "rights_proof_path": "plantvillage-rights.md",
            "source_label": row["source_label"],
            "stratum_code": row["stratum_code"],
        })
    validate_plantvillage_train_val(selected, blocked_test_groups=blocked_test_groups)
    return selected, blocked_test_groups


def compare_visuals(
    external: list[dict],
    sikkim_root: Path,
    plantvillage_reference_images: Path,
    decisions: dict,
) -> dict:
    pv_paths = sorted(path for path in plantvillage_reference_images.iterdir()
                      if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    if len(pv_paths) != 6059:
        raise ValueError(f"Se esperaban 6059 imágenes históricas, hay {len(pv_paths)}")
    pv_hashes = {file_sha(path) for path in pv_paths}
    if pv_hashes.intersection({row["sha256"] for row in external}):
        raise ValueError("Duplicado exacto Sikkim/PlantVillage")
    pv_visual = [(compute_dhash(path), path.name.rsplit(".", 1)[0]) for path in pv_paths]
    cross = []
    external_visual = []
    for row in external:
        path = sikkim_root / row["source_path"]
        value = compute_dhash(path)
        external_visual.append((row["sha256"], value))
        distance, nearest_sha = min(((value ^ candidate).bit_count(), sha)
                                    for candidate, sha in pv_visual)
        if distance <= DEFAULT_HAMMING_THRESHOLD:
            cross.append({"external_sha256": row["sha256"], "plantvillage_sha256": nearest_sha,
                          "distance": distance})
    expected_cross = decisions.get("cross_source_review", {}).get("pairs", [])
    if sorted(cross, key=lambda item: item["external_sha256"]) != \
            sorted(expected_cross, key=lambda item: item["external_sha256"]):
        raise ValueError("Alertas dHash Sikkim/PlantVillage cambiaron o no están revisadas")
    if decisions.get("cross_source_review", {}).get("decision") != "DISTINCT_BY_VISUAL_REVIEW":
        raise ValueError("Alertas dHash cruzadas sin resolución visual")
    internal_pairs = 0
    for index, (_, left) in enumerate(external_visual):
        for _, right in external_visual[index + 1:]:
            if (left ^ right).bit_count() <= DEFAULT_HAMMING_THRESHOLD:
                internal_pairs += 1
    internal_review = decisions.get("internal_review", {})
    if internal_pairs != internal_review.get("alert_pair_count") or \
            internal_review.get("decision") != "RETAIN_UNIQUE_SHA_FILES_WITH_CORRELATION_LIMITATION":
        raise ValueError("Alertas dHash internas cambiaron o no conservan su limitación")
    return {
        "plantvillage_reference_count": len(pv_paths),
        "exact_overlap_count": 0,
        "cross_source_dhash_alert_count": len(cross),
        "cross_source_review_decision": "DISTINCT_BY_VISUAL_REVIEW",
        "internal_dhash_alert_pair_count": internal_pairs,
        "internal_dhash_limit": "Potentially correlated/derived unique files are retained and disclosed; no plant independence claimed",
    }


def materialize(args: argparse.Namespace) -> dict:
    if args.output.exists():
        raise FileExistsError(f"Salida privada ya existe: {args.output}")
    if file_sha(args.sikkim_zip) != SIKKIM_ARCHIVE_SHA256:
        raise ValueError("ZIP Sikkim cambió")
    protocol = json.loads(args.protocol.read_text())
    protocol_bytes = args.protocol.read_bytes()
    protocol_sha = sha256_bytes(protocol_bytes)
    decisions = json.loads(args.visual_decisions.read_text())
    external = build_external_registry(args.sikkim_root)
    plantvillage, blocked_test_groups = build_plantvillage_reference(args.plantvillage_package)
    visual = compare_visuals(external, args.sikkim_root, args.plantvillage_reference_images, decisions)

    stage = Path(mkdtemp(prefix="g1-v14-", dir=str(args.output.parent)))
    try:
        source_proof = {
            "source_id": "sikkim-solanaceae-v1",
            "doi": "10.17632/4wz7zbk635.1",
            "source_url": SIKKIM_SOURCE_URL,
            "archive_name": "Sikkim Solanaceae Leaf Image Dataset.zip",
            "archive_size": args.sikkim_zip.stat().st_size,
            "archive_sha256": SIKKIM_ARCHIVE_SHA256,
            "publisher_file_uuid": "23a902c9-9fea-4113-97db-8fee07632abd",
            "author": "Kishor Chettri; Sikkim University",
            "license": "CC-BY-4.0",
            "license_url": SIKKIM_LICENSE_URL,
            "rights_scope": "The publisher marks dataset version 1 CC BY 4.0; attribution retained. No per-plant independence is asserted.",
            "reviewed_at": "2026-11-22",
        }
        (stage / "source-proof.json").write_text(json.dumps(source_proof, ensure_ascii=False, indent=2) + "\n")
        shutil.copyfile(args.plantvillage_package / "rights.md", stage / "plantvillage-rights.md")
        external_bytes = jsonl_bytes(external)
        (stage / "sikkim-external.jsonl").write_bytes(external_bytes)
        (stage / "plantvillage-train-val.jsonl").write_bytes(jsonl_bytes(plantvillage))
        seal = build_external_seal(external, external_bytes, protocol_sha256=protocol_sha)
        (stage / "external-seal.json").write_text(json.dumps(seal, ensure_ascii=False, indent=2) + "\n")
        verify_pretraining_gate(plantvillage, external, external_bytes, seal, protocol,
                                blocked_test_groups=blocked_test_groups,
                                protocol_sha256=protocol_sha)
        counts = defaultdict(lambda: defaultdict(lambda: {"photos": 0, "groups": set()}))
        for row in plantvillage:
            cell = counts[row["stratum_code"]][row["split"]]
            cell["photos"] += 1
            cell["groups"].add(row["split_group"])
        count_report = {code: {split: {"photos": value["photos"], "groups": len(value["groups"])}
                               for split, value in splits.items()}
                        for code, splits in counts.items()}
        report = {
            "status": "G1_V1_4_0_CLOSED_EXTERNAL_SEALED_NOT_OPENED_FOR_MODELING",
            "protocol_sha256": protocol_sha,
            "sikkim_archive_sha256": SIKKIM_ARCHIVE_SHA256,
            "external_manifest_sha256": sha256_bytes(external_bytes),
            "external_seal_sha256": file_sha(stage / "external-seal.json"),
            "external_counts": dict(sorted(Counter(row["stratum_code"] for row in external).items())),
            "external_unique_hashes": len({row["sha256"] for row in external}),
            "external_independence": "UNIQUE_IMAGE_ONLY_NOT_PLANT",
            "plantvillage_train_val_counts": count_report,
            "plantvillage_manifest_sha256": file_sha(stage / "plantvillage-train-val.jsonl"),
            "historical_test_group_count_blocked": len(blocked_test_groups),
            "visual_audit": visual,
            "training_executed": False,
            "external_opened_for_modeling": False,
        }
        (stage / "g1-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        os.replace(stage, args.output)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sikkim-root", type=Path, required=True)
    parser.add_argument("--sikkim-zip", type=Path, required=True)
    parser.add_argument("--plantvillage-package", type=Path, required=True)
    parser.add_argument("--plantvillage-reference-images", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--visual-decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    namespace = parser.parse_args()
    print(json.dumps(materialize(namespace), ensure_ascii=False))
