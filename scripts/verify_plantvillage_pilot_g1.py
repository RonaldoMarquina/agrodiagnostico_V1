"""Verify real pilot manifests, group isolation and a private TEST seal."""
import csv
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import sys

from agro_ml.data.partitioning import seal_test_partitions, verify_partition_leakage, verify_test_partition_seal

MINIMUMS = {"TRAIN": (150, 50), "VAL": (40, 20), "TEST": (30, 15)}
CLASSES = {"POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"}


def read(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def serialized_csv(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def verify(directory, candidate):
    directory = directory.resolve(strict=True)
    positives = read(directory / "positives.csv")
    negatives = read(directory / "negatives.csv")
    if {r["class_code"] for r in positives} != CLASSES:
        raise ValueError("Pilot class mismatch")
    if {r["negative_category"] for r in negatives} != {"OTHER_CROP"}:
        raise ValueError("Negative category mismatch")
    all_rows = positives + negatives
    if len({r["image_id"] for r in all_rows}) != len(all_rows):
        raise ValueError("Duplicate image IDs")
    if len({r["sha256"] for r in all_rows}) != len(all_rows):
        raise ValueError("Exact duplicate bytes")
    verify_partition_leakage(all_rows)
    selected = {r["sha256"] for r in all_rows}
    candidates = read(candidate / "positives.csv") + read(candidate / "negatives.csv")
    candidate_by_sha = defaultdict(list)
    for source in candidates:
        candidate_by_sha[source["sha256"]].append(source)
    for row in positives:
        if not any(source["candidate"] == row["class_code"] and source["leaf_id"]
                   and row["split_group"] == "pv:" + source["leaf_id"]
                   and row["split"] == source["split"]
                   for source in candidate_by_sha[row["sha256"]]):
            raise ValueError("Positive row does not match the pinned source and leaf group")
    for row in negatives:
        if not any(source["source_label"] == "Tomato___healthy" and source["leaf_id"]
                   and row["split_group"] == "pv:" + source["leaf_id"]
                   and row["split"] == source["split"]
                   for source in candidate_by_sha[row["sha256"]]):
            raise ValueError("Negative row is not an identified other-crop leaf")
    original_path_to_sha = {r["path"]: r["sha256"] for r in candidates}
    for pair in read(candidate / "visual-pairs.csv"):
        if original_path_to_sha[pair["a"]] in selected and original_path_to_sha[pair["b"]] in selected:
            raise ValueError("Unresolved visual match was selected")
    counts = {}
    for class_code in sorted(CLASSES):
        counts[class_code] = {}
        for split, (samples_min, groups_min) in MINIMUMS.items():
            rows = [r for r in positives if r["class_code"] == class_code and r["split"] == split]
            groups = {r["split_group"] for r in rows}
            counts[class_code][split] = {"samples": len(rows), "groups": len(groups),
                                          "minimum_samples": samples_min, "minimum_groups": groups_min}
            if len(rows) < samples_min or len(groups) < groups_min:
                raise ValueError(f"Minimum not met: {class_code} {split}")
    if not negatives or any("Potato___healthy" in r["notes"] for r in negatives):
        raise ValueError("Negative set invalid")
    seal_path = directory / "test-seal.json"
    if seal_path.exists():
        verify_test_partition_seal(all_rows, seal_path)
    else:
        seal_test_partitions(all_rows, seal_path, protocol_version="1.2.0")
    for split in MINIMUMS:
        for label, rows in (("positives", positives), ("negatives", negatives)):
            target = directory / f"{split.lower()}-{label}.csv"
            expected = [r for r in rows if r["split"] == split]
            expected_bytes = serialized_csv(expected, list(rows[0]))
            if target.exists():
                if target.read_bytes() != expected_bytes:
                    raise ValueError(f"Partition manifest changed: {target.name}")
            else:
                with target.open("xb") as stream:
                    stream.write(expected_bytes)
    report = {"protocol_version": "1.2.0", "status": "G1_PILOT_VERIFIED",
              "counts": counts, "negative_counts": dict(Counter(r["split"] for r in negatives)),
              "exact_duplicate_hashes": 0, "cross_partition_leaf_ids": 0,
              "selected_unresolved_visual_pairs": 0,
              "test_seal_sha256": hashlib.sha256(seal_path.read_bytes()).hexdigest(),
              "manifest_sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                  for name in ("positives.csv", "negatives.csv", "exclusions.csv", "evidence.json")}}
    report_path = directory / "g1-report.json"
    if report_path.exists():
        if json.loads(report_path.read_text()) != report:
            raise ValueError("G1 report changed after sealing")
    else:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"counts": counts, "negative_counts": report["negative_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    verify(Path(sys.argv[1]), Path(sys.argv[2]))
