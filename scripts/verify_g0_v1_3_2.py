"""Verify G0 v1.3.2 and reuse the sealed G1 v1.3.1 admission without TEST scoring."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_g1_v1_3_1 import verify as verify_g1


REMOVED_GENERIC_NEGATIVE_LIMITS = {"negative_fpr_per_stratum_max", "negative_rejection_per_stratum_min"}
NEW_SCOPED_NEGATIVE_LIMITS = {
    "negative_fpr_other_crop_max", "negative_rejection_other_crop_min",
    "potato_healthy_test_max_visible_blight_count",
    "potato_healthy_test_min_no_concluyente_count", "potato_healthy_test_denominator",
    "potato_healthy_test_visible_blight_rate_max", "potato_healthy_test_no_concluyente_rate_min",
}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_protocol(current, previous, report, previous_hash, report_hash):
    if current.get("protocol_version") != "1.3.2" or current.get("status") != "APPROVED_G0_DESIGN" or \
            current.get("approval", {}).get("approved_by_role") != "PROJECT_OWNER" or \
            current.get("approval", {}).get("approved_at") != current.get("approved_at") or \
            current.get("gates", {}).get("G0") != "CLOSED_APPROVED" or \
            current.get("gates", {}).get("G1") != "CLOSED_PREVIOUS_ADMISSION_REVALIDATED":
        raise ValueError("G0 v1.3.2 approval or gate state missing")
    reuse = current.get("g1_reuse", {})
    if reuse.get("admission_protocol_sha256") != previous_hash or \
            reuse.get("private_report_sha256") != report_hash or \
            reuse.get("admission_protocol_version") != "1.3.1" or \
            reuse.get("manifest_sha256") != report.get("manifest_sha256") or \
            reuse.get("test_seal_sha256") != report.get("test_seal_sha256") or \
            report.get("protocol_sha256") != previous_hash or \
            report.get("status") != "G1_V1_3_1_ADMITTED_AND_TEST_SEALED":
        raise ValueError("G1 admission lineage or seal changed")
    if current.get("partition_minimums_by_stratum") != previous.get("partition_minimums_by_stratum") or \
            current.get("publishable_classes") != previous.get("publishable_classes") or \
            current.get("technical_rejection_targets") != previous.get("technical_rejection_targets") or \
            current.get("compute_budget_cpu") != previous.get("compute_budget_cpu"):
        raise ValueError("Unapproved change to strata, minima or CPU budget")
    old = previous["metrics_thresholds"]
    new = current["metrics_thresholds"]
    if {key: value for key, value in old.items() if key not in REMOVED_GENERIC_NEGATIVE_LIMITS} != \
            {key: value for key, value in new.items() if key not in NEW_SCOPED_NEGATIVE_LIMITS}:
        raise ValueError("Other performance limits changed")
    if old["negative_fpr_per_stratum_max"] != new.get("negative_fpr_other_crop_max") or \
            old["negative_rejection_per_stratum_min"] != new.get("negative_rejection_other_crop_min"):
        raise ValueError("OTHER_CROP limits were relaxed")
    healthy = report["counts"]["POTATO_HEALTHY"]
    if healthy != {"TRAIN": {"photos": 80, "groups": 20},
                   "VAL": {"photos": 28, "groups": 7},
                   "TEST": {"photos": 32, "groups": 8}} or \
            new.get("potato_healthy_test_denominator") != 32 or \
            new.get("potato_healthy_test_max_visible_blight_count") != 3 or \
            new.get("potato_healthy_test_min_no_concluyente_count") != 29 or \
            new.get("potato_healthy_test_visible_blight_rate_max") != 3 / 32 or \
            new.get("potato_healthy_test_no_concluyente_rate_min") != 29 / 32:
        raise ValueError("Approved healthy TEST count or G1 distribution differs")
    if new["potato_healthy_test_max_visible_blight_count"] + \
            new["potato_healthy_test_min_no_concluyente_count"] != new["potato_healthy_test_denominator"]:
        raise ValueError("Healthy TEST counts are inconsistent")
    for code, splits in report["counts"].items():
        for split, observed in splits.items():
            minimum = current["partition_minimums_by_stratum"][code][split.lower()]
            if observed["photos"] < minimum["min_samples"] or \
                    observed["groups"] < minimum["min_independent_groups"]:
                raise ValueError(f"G1 does not meet G0 v1.3.2: {code} {split}")
    return {"status": "G0_V1_3_2_APPROVED_G1_REUSED", "healthy_test_denominator": 32,
            "healthy_max_visible_blight": 3, "healthy_min_no_concluyente": 29,
            "g1_photos": report["admitted_photos"], "g1_groups": report["admitted_groups"]}


def verify(current_path, previous_path, package, historical):
    current = json.loads(current_path.read_text())
    previous = json.loads(previous_path.read_text())
    report_path = package / "g1-report.json"
    report = json.loads(report_path.read_text())
    result = validate_protocol(current, previous, report, sha256(previous_path), sha256(report_path))
    verify_g1(package, historical, previous_path)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current_protocol", type=Path)
    parser.add_argument("previous_protocol", type=Path)
    parser.add_argument("private_g1_package", type=Path)
    parser.add_argument("historical_v1_2_package", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.current_protocol, args.previous_protocol,
                            args.private_g1_package, args.historical_v1_2_package)))
