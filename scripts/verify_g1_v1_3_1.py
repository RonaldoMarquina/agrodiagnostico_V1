"""Independently verify a private G1 v1.3.1 admission; never run a model."""

from collections import defaultdict
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml" / "src"))
from agro_ml.data.partitioning import verify_test_partition_seal


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def check_isolation(admitted, historical_test, blocked_groups):
    hashes, group_splits = set(), defaultdict(set)
    old_hashes = {r["sha256"] for r in historical_test}
    old_groups = {r["split_group"] for r in historical_test}
    for row in admitted:
        if row["sha256"] in hashes or row["split_group"] in blocked_groups:
            raise ValueError("Duplicate SHA or exposed leaf group")
        hashes.add(row["sha256"])
        group_splits[row["split_group"]].add(row["split"])
        if row["split"] == "TEST" and (row["sha256"] in old_hashes or row["split_group"] in old_groups):
            raise ValueError("New TEST reuses historical TEST")
    if any(len(splits) != 1 for splits in group_splits.values()):
        raise ValueError("Leaf group crosses partitions")
    return len(group_splits)


def verify(package, historical, protocol_path):
    report = json.loads((package / "g1-report.json").read_text())
    protocol = json.loads(protocol_path.read_text())
    mapping_path = ROOT / "ml/manifests/g1-v1.3.1-source-labels.json"
    mapping = json.loads(mapping_path.read_text())
    if report["status"] != "G1_V1_3_1_ADMITTED_AND_TEST_SEALED" or \
            protocol["status"] != "APPROVED_G0_DESIGN" or \
            report["protocol_sha256"] != digest(protocol_path) or \
            report["source_label_mapping_sha256"] != digest(mapping_path):
        raise ValueError("Protocol, mapping or G1 status mismatch")
    if digest(package / "rights.md") != "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb":
        raise ValueError("Pinned publisher rights declaration changed")
    for name, field in (("strata.csv", "manifest_sha256"), ("evidence.json", "evidence_sha256"),
                        ("test-seal.json", "test_seal_sha256")):
        if digest(package / name) != report[field]:
            raise ValueError(f"Changed G1 file: {name}")
    admitted = rows(package / "strata.csv")
    evidence = json.loads((package / "evidence.json").read_text())["records"]
    if len(admitted) != len(evidence) or len(admitted) != report["admitted_photos"]:
        raise ValueError("G1 evidence count mismatch")
    by_sha = {r["sha256"]: r for r in evidence}
    if len(by_sha) != len(evidence):
        raise ValueError("Duplicate G1 evidence SHA")
    blocked = json.loads((ROOT / "ml/manifests/g1-v1.3-exposure-blocklist.json").read_text())
    blocked_groups = {"pv:" + r["leaf_id"] for r in blocked["excluded_groups"]}
    old_test = rows(historical / "test-positives.csv") + rows(historical / "test-negatives.csv")
    groups = check_isolation(admitted, old_test, blocked_groups)
    if groups != report["admitted_groups"]:
        raise ValueError("G1 group count mismatch")
    counts = defaultdict(lambda: defaultdict(lambda: {"photos": 0, "groups": set()}))
    for row in admitted:
        code, split = row["stratum_code"], row["split"]
        if code not in protocol["partition_minimums_by_stratum"] or split not in {"TRAIN", "VAL", "TEST"}:
            raise ValueError("Unknown G1 stratum or split")
        if row["source"] != "plantvillage" or row["license"] != "CC-BY-SA-3.0" or \
                row["source_revision"] != "9e97599868962bd0079b8db4b7f1efa9185fa1e7" or \
                mapping["source_labels"].get(row["source_label"]) != code:
            raise ValueError("Source, license or label mapping mismatch")
        record = by_sha.get(row["sha256"])
        if record is None or any(record.get(k) != v for k, v in row.items()) or \
                record.get("decision") != "ADMIT" or not record.get("decision_reason") or \
                record.get("rights", {}).get("decision") != "APPROVED" or \
                record.get("label_review", {}).get("decision") != "APPROVED" or \
                record["label_review"].get("source_label") != row["source_label"] or \
                record["label_review"].get("stratum_code") != code:
            raise ValueError("Individual admission evidence incomplete")
        original = record.get("source_original_path", "")
        if not original.startswith("raw/color/") or ".." in Path(original).parts or \
                Path(original).suffix.lower() not in {".jpg", ".jpeg", ".png"} or \
                Path(original).parent.name != row["source_label"] or \
                not row["split_group"].startswith("pv:" + row["source_label"] + ":::"):
            raise ValueError("Original publisher path missing")
        proof = package / record["rights"]["proof_path"]
        if not proof.is_file() or not proof.read_bytes():
            raise ValueError("Rights proof missing")
        relative = Path(row["relative_path"])
        if relative.parent != Path("images") or relative.name != row["sha256"] + Path(original).suffix.lower() or \
                digest(package / relative) != row["sha256"]:
            raise ValueError("Image bytes, path or SHA mismatch")
        counts[code][split]["photos"] += 1
        counts[code][split]["groups"].add(row["split_group"])
    actual = {}
    for code, minima in protocol["partition_minimums_by_stratum"].items():
        actual[code] = {}
        for split in ("TRAIN", "VAL", "TEST"):
            value = counts[code][split]
            photo_count, group_count = value["photos"], len(value["groups"])
            minimum = minima[split.lower()]
            if photo_count < minimum["min_samples"] or group_count < minimum["min_independent_groups"]:
                raise ValueError(f"G0 minimum unmet: {code} {split}")
            actual[code][split] = {"photos": photo_count, "groups": group_count}
    if actual != report["counts"] or sum(r["split"] == "TEST" for r in admitted) != report["test_count"]:
        raise ValueError("G1 counts differ from report")
    for code, filename in (("POTATO_EARLY_BLIGHT", "potato-early-blight.csv"),
                           ("POTATO_LATE_BLIGHT", "potato-late-blight.csv"),
                           ("POTATO_HEALTHY", "potato-healthy.csv"),
                           ("OTHER_CROP", "other-crop.csv")):
        if rows(package / filename) != [r for r in admitted if r["stratum_code"] == code]:
            raise ValueError("Separated stratum manifest differs")
    seal_rows = [{"image_id": r["image_id"], "sha256": r["sha256"],
                  "class_code": r["stratum_code"], "split_group": r["split_group"],
                  "split": r["split"]} for r in admitted]
    if not verify_test_partition_seal(seal_rows, package / "test-seal.json"):
        raise ValueError("New TEST seal invalid")
    return {"status": "VERIFIED", "photos": len(admitted), "groups": groups,
            "test_photos": report["test_count"], "counts": actual}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("historical", type=Path)
    parser.add_argument("protocol", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.package, args.historical, args.protocol), ensure_ascii=False))
