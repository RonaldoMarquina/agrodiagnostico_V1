"""Inventory pinned PlantVillage files for G1 v1.3; never admit or seal TEST.

The private output is an auditable candidate register. ``ELIGIBLE_FOR_REVIEW``
means that mechanical checks passed, not that G1 has admitted the image.
"""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

from PIL import Image, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml" / "src"))
from agro_ml.data.grouping import DEFAULT_HAMMING_THRESHOLD, compute_dhash
from prepare_plantvillage_g1 import PIN, REV, leaf_for

ROOT = Path(__file__).resolve().parents[1]
TEST_PIN = "7a7257dcb5f9456feae6ae81248d29c28f45dc4cd41a00c13a5c5c198c5f2f8b"
LABELS = {
    "Potato___Early_blight": "POTATO_EARLY_BLIGHT",
    "Potato___Late_blight": "POTATO_LATE_BLIGHT",
    "Potato___healthy": "POTATO_HEALTHY",
    "Tomato___healthy": "OTHER_CROP",
}
FIELDS = ("source", "source_revision", "source_split", "source_path", "sha256", "license",
          "license_proof_sha256", "leaf_id", "class_code", "source_label", "partition_candidate",
          "label_review", "quality_review", "decision", "decision_reason")


def sha_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dhash(image):
    gray = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            offset = row * 9 + col
            bits = (bits << 1) | (pixels[offset] > pixels[offset + 1])
    return bits


def inspect_image(raw):
    with Image.open(BytesIO(raw)) as image:
        image.load()
        gray = image.convert("L").resize((64, 64))
        contrast = ImageStat.Stat(gray).stddev[0]
        good = image.width >= 128 and image.height >= 128 and contrast >= 8
        return good, dhash(image), round(contrast, 2)


def register(source, output, historical):
    if output.exists():
        raise FileExistsError(output)
    for name, digest in {**PIN, "color_test.txt": TEST_PIN}.items():
        if sha_file(source / name) != digest:
            raise ValueError(f"Pinned source changed: {name}")
    leaf_map = json.loads((source / "leaf-map.json").read_text())
    source_train = set((source / "color_train.txt").read_text().splitlines())
    source_test = set((source / "color_test.txt").read_text().splitlines())
    if source_train & source_test:
        raise ValueError("Official source splits overlap")
    train_groups = {leaf_for(Path(path), leaf_map) for path in source_train
                    if Path(path).parent.name in LABELS}
    test_groups = {leaf_for(Path(path), leaf_map) for path in source_test
                   if Path(path).parent.name in LABELS}
    if (train_groups & test_groups) - {""}:
        raise ValueError("Official source leaf groups overlap")
    blocklist = json.loads((ROOT / "ml/manifests/g1-v1.3-exposure-blocklist.json").read_text())
    exposed_groups = {entry["leaf_id"] for entry in blocklist["excluded_groups"]}
    exposed_hashes = {digest for entry in blocklist["excluded_groups"] for digest in entry["sha256"]}
    old_test = []
    old_selection = []
    for filename in ("train-positives.csv", "train-negatives.csv", "val-positives.csv",
                     "val-negatives.csv", "test-positives.csv", "test-negatives.csv"):
        with (historical / filename).open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
            old_selection.extend(rows)
            if filename.startswith("test-"):
                old_test.extend(rows)
    old_groups = {r["split_group"].removeprefix("pv:") for r in old_test}
    old_hashes = {r["sha256"] for r in old_test}
    old_visual = []
    for r in old_selection:
        file = source / "batch-v1" / "images" / (r["sha256"] + ".jpg")
        if not file.exists():
            file = source / "batch-v1" / "images" / (r["sha256"] + ".png")
        if not file.exists():
            raise FileNotFoundError(f"Historical TEST bytes missing: {r['sha256']}")
        if sha_file(file) != r["sha256"]:
            raise ValueError("Historical TEST bytes changed")
        old_visual.append((r["sha256"], compute_dhash(file)))
    paths = sorted(path for path in source_test if Path(path).parent.name in LABELS)
    paths += sorted(path for path in source_train if Path(path).parent.name == "Potato___healthy")
    records, hashes, visuals = [], defaultdict(list), []
    with zipfile.ZipFile(source / "data.zip") as archive:
        for path in paths:
            source_label = Path(path).parent.name
            raw = archive.read(path)
            digest = hashlib.sha256(raw).hexdigest()
            leaf_id = leaf_for(Path(path), leaf_map)
            original_split = "AUTHOR_COLOR_TEST" if path in source_test else "AUTHOR_COLOR_TRAIN"
            partition = "TEST_CANDIDATE" if path in source_test else "REPARTITION_REQUIRED"
            reason = ""
            if leaf_id in exposed_groups or digest in exposed_hashes:
                reason = "G3_EXPOSED_GROUP"
            elif not leaf_id:
                reason = "NO_VERIFIABLE_LEAF_ID"
            elif leaf_id in old_groups or digest in old_hashes:
                reason = "HISTORICAL_TEST_OVERLAP"
            try:
                good, visual, contrast = inspect_image(raw)
                if not good and not reason:
                    reason = "LOW_DIMENSION_OR_CONTRAST"
                quality = f"DECODED; contrast_64px={contrast}; mechanical_screen_only"
            except (OSError, ValueError):
                visual = None
                quality = "DECODE_FAILED"
                reason = reason or "DECODE_FAILED"
            row = dict(source="PlantVillage/mohanty", source_revision=REV,
                       source_split=original_split, source_path=path, sha256=digest,
                       license="CC-BY-SA-3.0", license_proof_sha256=PIN["README.md"],
                       leaf_id=leaf_id, class_code=LABELS[source_label],
                       source_label=source_label, partition_candidate=partition,
                       label_review="EXPERT_SOURCE; INTERNAL_VISUAL_REVIEW_PENDING",
                       quality_review=quality, decision="EXCLUDE" if reason else "PENDING",
                       decision_reason=reason or "ELIGIBLE_FOR_INTERNAL_VISUAL_REVIEW")
            hashes[digest].append(len(records))
            records.append(row)
            visuals.append(visual)
    for indexes in hashes.values():
        if len(indexes) > 1:
            for index in indexes:
                records[index]["decision"] = "EXCLUDE"
                records[index]["decision_reason"] = "EXACT_DUPLICATE_CANDIDATE"
    pairs = []
    for i, a in enumerate(visuals):
        if a is None or records[i]["decision"] == "EXCLUDE":
            continue
        for old_sha, old_dhash in old_visual:
            if (a ^ old_dhash).bit_count() <= DEFAULT_HAMMING_THRESHOLD:
                records[i]["decision_reason"] = "VISUAL_MATCH_HISTORICAL_PARTITION_PENDING"
                pairs.append((records[i]["sha256"], old_sha, "HISTORICAL_PARTITION"))
        for j in range(i):
            b = visuals[j]
            if b is None or records[j]["leaf_id"] == records[i]["leaf_id"]:
                continue
            if (a ^ b).bit_count() <= DEFAULT_HAMMING_THRESHOLD:
                if records[i]["decision"] != "EXCLUDE":
                    records[i]["decision_reason"] = "VISUAL_PAIR_GROUP_REVIEW_PENDING"
                if records[j]["decision"] != "EXCLUDE":
                    records[j]["decision_reason"] = "VISUAL_PAIR_GROUP_REVIEW_PENDING"
                pairs.append((records[i]["sha256"], records[j]["sha256"], "CANDIDATE_GROUPS"))
    output.mkdir(mode=0o700, parents=True)
    with (output / "registry.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    with (output / "visual-pairs.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("sha256_a", "sha256_b", "relation"))
        writer.writerows(pairs)
    counts = {}
    for code in LABELS.values():
        counts[code] = {}
        for partition in ("REPARTITION_REQUIRED", "TEST_CANDIDATE"):
            sub = [r for r in records if r["class_code"] == code and r["partition_candidate"] == partition]
            pending = [r for r in sub if r["decision"] == "PENDING" and r["leaf_id"]]
            unresolved_groups = {r["leaf_id"] for r in sub if r["leaf_id"] and
                                 r["decision_reason"] != "ELIGIBLE_FOR_INTERNAL_VISUAL_REVIEW"}
            clear = [r for r in pending if r["leaf_id"] not in unresolved_groups and
                     r["decision_reason"] == "ELIGIBLE_FOR_INTERNAL_VISUAL_REVIEW"]
            counts[code][partition] = {
                "inventoried_photos": len(sub), "inventoried_groups": len({r["leaf_id"] for r in sub if r["leaf_id"]}),
                "pending_photos": len(pending), "pending_groups": len({r["leaf_id"] for r in pending}),
                "mechanically_clear_photos": len(clear),
                "mechanically_clear_groups": len({r["leaf_id"] for r in clear}),
                "excluded_photos": sum(r["decision"] == "EXCLUDE" for r in sub),
                "reasons": dict(Counter(r["decision_reason"] for r in sub)),
            }
    report = {
        "status": "CANDIDATES_ONLY_G1_OPEN", "source_revision": REV,
        "source_test_sha256": TEST_PIN, "archive_sha256": PIN["data.zip"],
        "registry_sha256": sha_file(output / "registry.csv"),
        "visual_pairs_sha256": sha_file(output / "visual-pairs.csv"),
        "source_split_overlap_paths": 0, "source_split_overlap_leaf_groups": 0,
        "historical_test_groups": len(old_groups),
        "historical_test_hashes": len(old_hashes), "historical_all_hashes": len(old_selection),
        "visual_pairs_for_review": len(pairs),
        "counts": counts,
        "caveat": "No admission, partition seal, independent agronomic review, model evaluation or TEST opening.",
    }
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("historical", type=Path)
    parser.add_argument("new_output", type=Path)
    args = parser.parse_args()
    register(args.source, args.new_output, args.historical)
