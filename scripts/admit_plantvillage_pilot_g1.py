"""Build private G1 evidence for the two-blight PlantVillage pilot from a pinned candidate batch."""
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import sys

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
POSITIVE_CLASSES = {"POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"}
NEGATIVE_LABEL = "Tomato___healthy"
EXPERT_SOURCE = "https://arxiv.org/pdf/1511.08060#page=9"
HEADERS_POSITIVE = ["image_id", "sha256", "crop_code", "class_code", "source", "license",
                    "capture_context", "label_quality", "split_group", "split"]
HEADERS_NEGATIVE = ["image_id", "sha256", "negative_category", "source", "license",
                    "capture_context", "split_group", "split", "notes"]


def write_csv(path, fields, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build(candidate, destination):
    if destination.exists():
        raise FileExistsError(destination)
    candidate = candidate.resolve(strict=True)
    destination.mkdir(mode=0o700)
    summary = json.loads((candidate / "summary.json").read_text())
    for name, expected in summary["csv_sha256"].items():
        if hashlib.sha256((candidate / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Candidate inventory changed: " + name)
    shutil.copyfile(candidate / "rights.md", destination / "rights.md")
    reviewed = {r["sha256"] for r in csv.DictReader((candidate / "review-queue.csv").open())}
    source_version = json.loads((ROOT / "ml/manifests/sources.v2.json").read_text())["sources"][0]["version"]
    selected = []
    exclusions = []
    for filename in ("positives.csv", "negatives.csv"):
        for item in csv.DictReader((candidate / filename).open(newline="")):
            if item["candidate"] not in POSITIVE_CLASSES and item["source_label"] != NEGATIVE_LABEL:
                continue
            reason = item["exclusion"] or ("VISUAL_AMBIGUITY_INTERNAL" if item["sha256"] in reviewed else "")
            if not reason and not item["leaf_id"]:
                reason = "LEAF_ID_UNRESOLVED"
            if reason:
                exclusions.append({"sha256": item["sha256"], "source_path": item["path"],
                                   "source_label": item["source_label"], "reason": reason})
                continue
            selected.append(item)
    all_hashes = {x["sha256"] for x in selected}
    if len(all_hashes) != len(selected):
        raise ValueError("Hash exacto repetido en selección")
    positives, negatives, decisions = [], [], []
    quality_counts = {"checked": 0, "excluded": 0}
    for item in selected:
        file = candidate / item["relative_path"]
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Archivo ausente o hash cambiado: " + item["sha256"])
        with Image.open(file) as image:
            image.load()
            gray = image.convert("L").resize((64, 64))
            contrast = ImageStat.Stat(gray).stddev[0]
            valid = image.width >= 128 and image.height >= 128 and contrast >= 8
        quality_counts["checked"] += 1
        if not valid:
            quality_counts["excluded"] += 1
            exclusions.append({"sha256": item["sha256"], "source_path": item["path"],
                               "source_label": item["source_label"], "reason": "QUALITY_DIMENSION_OR_CONTRAST"})
            continue
        negative = item["source_label"] == NEGATIVE_LABEL
        image_id = item["sha256"]
        common = {"image_id": image_id, "sha256": item["sha256"], "source": "plantvillage",
                  "license": "CC-BY-SA-3.0", "capture_context": "CONTROLLED_LEAF",
                  "split_group": "pv:" + item["leaf_id"], "split": item["split"]}
        rights = {"decision": "APPROVED", "allowed_uses": ["TRAINING", "EVALUATION"],
                  "reviewer": "project owner G0; Codex file verification", "reviewed_at": str(date.today()),
                  "proof_path": "rights.md", "attribution": "Mohanty, Hughes and Salathé; PlantVillage",
                  "restrictions": "CC BY-SA 3.0, attribution and ShareAlike for derivatives and trained algorithms"}
        record = {key: common[key] for key in ("image_id", "sha256", "source", "split_group")}
        record.update({"source_revision": source_version,
                       "relative_path": item["relative_path"], "decision": "ADMIT",
                       "decision_by": "project owner protocol; Codex internal quality control",
                       "decision_at": str(date.today()),
                       "decision_reason": "PlantVillage expert provenance and internal per-file quality check",
                       "rights": rights})
        note = f"PlantVillage expert source label; original file verified; 64px grayscale contrast {contrast:.1f}; ambiguity screen and visual sample reviewed internally; no independent agronomist"
        review = {"decision": "APPROVED", "reviewer": "PlantVillage expert provenance + Codex internal quality control",
                  "reviewed_at": str(date.today()), "evidence_note": note}
        if negative:
            negatives.append({**common, "negative_category": "OTHER_CROP",
                              "notes": "Tomato leaf only; never potato healthy"})
            record["category_review"] = {**review, "negative_category": "OTHER_CROP",
                                          "quality_decision": "INCLUDE_AS_NEGATIVE",
                                          "ambiguity_note": "Source identifies tomato healthy; internal image checks and visual sample. Other crop only."}
        else:
            positives.append({**common, "crop_code": "POTATO", "class_code": item["candidate"],
                              "label_quality": "REVIEWED"})
            record.update({"source_label": item["source_label"], "class_code": item["candidate"],
                           "crop_code": "POTATO"})
            record["label_review"] = {**review, "source_label": item["source_label"],
                                      "class_code": item["candidate"], "crop_code": "POTATO"}
        decisions.append(record)
    write_csv(destination / "positives.csv", HEADERS_POSITIVE, positives)
    write_csv(destination / "negatives.csv", HEADERS_NEGATIVE, negatives)
    write_csv(destination / "exclusions.csv", ["sha256", "source_path", "source_label", "reason"], exclusions)
    (destination / "evidence.json").write_text(json.dumps({"schema_version": 1, "records": decisions}, ensure_ascii=False, indent=2) + "\n")
    (destination / "prevalidation.json").write_text(json.dumps({"source_expert_reference": EXPERT_SOURCE,
        "scope": sorted(POSITIVE_CLASSES), "negative_source_label": NEGATIVE_LABEL,
        "internal_quality": quality_counts, "positive_rows": len(positives),
        "negative_rows": len(negatives), "exclusions": len(exclusions),
        "status": "AWAITING_VALIDATION_AND_TEST_SEAL"}, indent=2) + "\n")
    print(destination / "prevalidation.json")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
