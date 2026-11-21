"""Build a private G1 candidate partition plan; never admit or seal TEST.

The proposed G0 v1.3.1 minimums are deliberately hardcoded only for a
read-only feasibility check. Approval and a separate admission step are needed.
"""

from collections import Counter
import argparse
import csv
import hashlib
import json
from pathlib import Path
import zipfile


MINIMUMS = {
    "POTATO_EARLY_BLIGHT": {"TRAIN": (150, 50), "VAL": (40, 20), "TEST": (30, 15)},
    "POTATO_LATE_BLIGHT": {"TRAIN": (150, 50), "VAL": (40, 20), "TEST": (30, 15)},
    "POTATO_HEALTHY": {"TRAIN": (80, 20), "VAL": (28, 7), "TEST": (32, 8)},
    "OTHER_CROP": {"TRAIN": (150, 50), "VAL": (40, 20), "TEST": (30, 15)},
}
FIELDS = ("sha256", "source", "source_revision", "source_path", "license", "leaf_id",
          "split_group", "source_label", "class_code", "split", "review_evidence",
          "admission_decision")


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_isolation(rows, old_test_hashes, old_test_groups):
    if len({row["sha256"] for row in rows}) != len(rows):
        raise ValueError("Exact duplicate in partition plan")
    splits_by_group = {}
    for row in rows:
        prior = splits_by_group.setdefault(row["split_group"], row["split"])
        if prior != row["split"]:
            raise ValueError("Leaf group crosses partitions")
        if row["split"] == "TEST" and (row["sha256"] in old_test_hashes or
                                       row["split_group"] in old_test_groups):
            raise ValueError("New TEST reuses historical TEST image or group")
    return len(splits_by_group)


def plan(source, historical, resolved, review, output):
    if output.exists():
        raise FileExistsError(output)
    if sha((source / "README.md").read_bytes()) != "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb":
        raise ValueError("Pinned distribution rights declaration changed")
    resolved_report = json.loads((resolved / "summary.json").read_text())
    if sha((resolved / "registry.csv").read_bytes()) != resolved_report["registry_sha256"]:
        raise ValueError("Resolved G1 registry changed")
    review_report = json.loads((review / "summary.json").read_text())
    if sha((review / "candidates.csv").read_bytes()) != review_report["candidate_csv_sha256"]:
        raise ValueError("Review candidate selection changed")
    registry = read_csv(resolved / "registry.csv")
    by_sha = {row["sha256"]: row for row in registry}
    if len(by_sha) != len(registry):
        raise ValueError("G1 registry has duplicate SHA")
    reviewed = json.loads((review / "visual-review.json").read_text())
    if reviewed.get("status") != "REVIEWED_NOT_ADMITTED":
        raise ValueError("Visual review not completed")
    review_by_sha = {row["sha256"]: row for row in reviewed["records"]}
    selected = read_csv(review / "candidates.csv")
    if len(selected) != len(review_by_sha):
        raise ValueError("Visual review does not cover selected candidates")
    old_test = read_csv(historical / "test-positives.csv") + read_csv(historical / "test-negatives.csv")
    old_test_hashes = {row["sha256"] for row in old_test}
    old_test_groups = {row["split_group"] for row in old_test}
    block = json.loads((Path(__file__).resolve().parents[1] / "ml/manifests/g1-v1.3-exposure-blocklist.json").read_text())
    blocked = {row["leaf_id"] for row in block["excluded_groups"]}
    batch = read_csv(source / "batch-v1" / "positives.csv") + read_csv(source / "batch-v1" / "negatives.csv")
    batch_by_sha = {row["sha256"]: row for row in batch if row["sha256"]}
    all_rows = []
    source_revision = block["source_revision"]

    def append(item, split, evidence):
        digest = item["sha256"]
        leaf = item["leaf_id"]
        if not leaf or leaf in blocked or digest in old_test_hashes:
            raise ValueError("Exposed, unverifiable or historical TEST candidate")
        code = item["candidate"] if "candidate" in item else item["class_code"]
        row = dict(sha256=digest, source="plantvillage", source_revision=source_revision,
                   source_path=item["path"] if "path" in item else item["source_path"],
                   license="CC-BY-SA-3.0", leaf_id=leaf, split_group="pv:" + leaf,
                   source_label=item["source_label"], class_code=code, split=split,
                   review_evidence=evidence, admission_decision="PENDING_G0_V1_3_1_APPROVAL")
        all_rows.append(row)

    for split in ("train", "val"):
        for kind in ("positives", "negatives"):
            for old in read_csv(historical / f"{split}-{kind}.csv"):
                item = batch_by_sha.get(old["sha256"])
                if item is None or "pv:" + item["leaf_id"] != old["split_group"]:
                    raise ValueError("Historical row not linked to publisher leaf")
                append(item, split.upper(), "pilot-v1.2/evidence.json; readmission_required")
    for item in selected:
        original = by_sha.get(item["sha256"])
        review_row = review_by_sha.get(item["sha256"])
        if original != item or item["decision"] != "PENDING" or not review_row or \
                review_row["quality_decision"] != "PASSED_INTERNAL_VISUAL_SCREEN":
            raise ValueError("Selected candidate lacks valid review")
        code = item["class_code"]
        if code == "POTATO_HEALTHY":
            if item["source_split"] == "AUTHOR_COLOR_TEST":
                split = "TEST"
            else:
                old = batch_by_sha.get(item["sha256"])
                if old is None or old["leaf_id"] != item["leaf_id"]:
                    raise ValueError("Healthy source split does not match original inventory")
                split = "TRAIN" if old["split"] == "TRAIN" else "VAL"
        else:
            if item["source_split"] != "AUTHOR_COLOR_TEST":
                raise ValueError("New TEST candidate not from official source holdout")
            split = "TEST"
        append(item, split, "g1-v1.3-review-candidates/visual-review.json; no specialist review")
    group_count = verify_isolation(all_rows, old_test_hashes, old_test_groups)
    with zipfile.ZipFile(source / "data.zip") as archive:
        for row in all_rows:
            if sha(archive.read(row["source_path"])) != row["sha256"]:
                raise ValueError("Pinned original bytes changed")
    counts = {}
    for code, splits in MINIMUMS.items():
        counts[code] = {}
        for split, (minimum_photos, minimum_groups) in splits.items():
            subset = [row for row in all_rows if row["class_code"] == code and row["split"] == split]
            photos, groups = len(subset), len({row["split_group"] for row in subset})
            if photos < minimum_photos or groups < minimum_groups:
                raise ValueError(f"Proposed minimum unmet: {code} {split}")
            counts[code][split] = {"photos": photos, "groups": groups,
                                   "proposed_min_photos": minimum_photos,
                                   "proposed_min_groups": minimum_groups}
    output.mkdir(parents=True, mode=0o700)
    with (output / "candidate-partitions.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    report = {"status": "FEASIBLE_CANDIDATE_PLAN_NOT_ADMITTED_OR_SEALED",
              "proposed_protocol_version": "1.3.1", "counts": counts,
              "rows": len(all_rows), "leaf_groups": group_count,
              "candidate_manifest_sha256": sha((output / "candidate-partitions.csv").read_bytes()),
              "excluded_historical_test_sha_overlap": 0,
              "excluded_historical_test_group_overlap": 0,
              "cross_partition_leaf_groups": 0,
              "decision_counts": dict(Counter(row["admission_decision"] for row in all_rows)),
              "caveat": "G0 numeric table awaits owner approval; no G1 admission or TEST seal."}
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("historical_dir", type=Path)
    parser.add_argument("resolved_audit_dir", type=Path)
    parser.add_argument("visual_review_dir", type=Path)
    parser.add_argument("new_output_dir", type=Path)
    args = parser.parse_args()
    plan(args.source_dir, args.historical_dir, args.resolved_audit_dir,
         args.visual_review_dir, args.new_output_dir)
