"""Admit and seal G1 v1.3.1 only after explicit G0 owner approval.

No training or model evaluation occurs. The source archive and all photographs
stay private. Run only after the proposed protocol records the owner's numeric
approval; this script fails closed while it remains a proposal.
"""

from collections import Counter
from datetime import date
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml" / "src"))
from scripts.plan_g1_v1_3_1 import verify_isolation
STRATA = ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT", "POTATO_HEALTHY", "OTHER_CROP")
MAPPING_PATH = ROOT / "ml/manifests/g1-v1.3.1-source-labels.json"
FIELDS = ("image_id", "sha256", "stratum_code", "source", "source_revision", "source_label",
          "license", "capture_context", "split_group", "split", "relative_path")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def require_approved_protocol(protocol):
    if protocol.get("protocol_version") != "1.3.1" or protocol.get("status") != "APPROVED_G0_DESIGN" or \
            protocol.get("gates", {}).get("G0") != "CLOSED_APPROVED":
        raise ValueError("G0 v1.3.1 numeric table is not approved")
    approval = protocol.get("approval")
    if not isinstance(approval, dict) or approval.get("approved_by_role") != "PROJECT_OWNER" or \
            not approval.get("decision_evidence") or not approval.get("approved_at") or \
            protocol.get("approved_at") != approval.get("approved_at"):
        raise ValueError("G0 v1.3.1 lacks explicit owner approval evidence")
    date.fromisoformat(approval["approved_at"])
    if date.fromisoformat(approval["approved_at"]) > date.today():
        raise ValueError("G0 owner approval date is in the future")
    minima = protocol.get("partition_minimums_by_stratum")
    if not isinstance(minima, dict) or set(minima) != set(STRATA):
        raise ValueError("G0 v1.3.1 has incomplete stratum minima")
    for code in STRATA:
        for split in ("train", "val", "test"):
            point = minima[code].get(split)
            if not isinstance(point, dict) or type(point.get("min_samples")) is not int or \
                    type(point.get("min_independent_groups")) is not int or \
                    point["min_samples"] <= 0 or point["min_independent_groups"] <= 0:
                raise ValueError("G0 v1.3.1 has invalid minima")
    return minima


def validate_rows(rows, protocol, historical, review, resolved):
    minima = require_approved_protocol(protocol)
    mapping = json.loads(MAPPING_PATH.read_text())["source_labels"]
    if len({r["sha256"] for r in rows}) != len(rows):
        raise ValueError("Duplicate candidate SHA")
    old_test = read_csv(historical / "test-positives.csv") + read_csv(historical / "test-negatives.csv")
    old_hashes = {r["sha256"] for r in old_test}
    old_groups = {r["split_group"] for r in old_test}
    verify_isolation(rows, old_hashes, old_groups)
    blocked = json.loads((ROOT / "ml/manifests/g1-v1.3-exposure-blocklist.json").read_text())
    blocked_groups = {"pv:" + x["leaf_id"] for x in blocked["excluded_groups"]}
    if any(r["split_group"] in blocked_groups for r in rows):
        raise ValueError("G3 exposed group in G1")
    resolved_report = json.loads((resolved / "summary.json").read_text())
    resolved_bytes = (resolved / "registry.csv").read_bytes()
    if sha(resolved_bytes) != resolved_report["registry_sha256"]:
        raise ValueError("Resolved visual-pair registry changed")
    resolved_by_sha = {r["sha256"]: r for r in read_csv(resolved / "registry.csv")}
    visual = json.loads((review / "visual-review.json").read_text())
    visual_by_sha = {r["sha256"]: r for r in visual["records"]}
    old_evidence = json.loads((historical / "evidence.json").read_text())
    old_by_sha = {r["sha256"]: r for r in old_evidence["records"]}
    for row in rows:
        if row["class_code"] not in STRATA or row["split"] not in {"TRAIN", "VAL", "TEST"} or \
                row["admission_decision"] != "PENDING_G0_V1_3_1_APPROVAL" or \
                row["source"] != "plantvillage" or row["license"] != "CC-BY-SA-3.0" or \
                row["split_group"] != "pv:" + row["leaf_id"] or \
                mapping.get(row["source_label"]) != row["class_code"]:
            raise ValueError("Candidate row invalid")
        if row["split"] == "TEST" or row["class_code"] == "POTATO_HEALTHY":
            reviewed = visual_by_sha.get(row["sha256"])
            resolved_row = resolved_by_sha.get(row["sha256"])
            if not reviewed or reviewed["quality_decision"] != "PASSED_INTERNAL_VISUAL_SCREEN" or \
                    reviewed["admission_decision"] != "PENDING_G0_V1_3_1_APPROVAL" or \
                    not resolved_row or resolved_row["decision"] != "PENDING":
                raise ValueError("Candidate lacks individual internal quality review")
        else:
            previous = old_by_sha.get(row["sha256"])
            if not previous or previous["decision"] != "ADMIT" or \
                    previous.get("label_review", previous.get("category_review", {})).get("decision") != "APPROVED":
                raise ValueError("Historical TRAIN/VAL row lacks reviewed G1 evidence")
    counts = {}
    for code in STRATA:
        counts[code] = {}
        for split in ("TRAIN", "VAL", "TEST"):
            subset = [r for r in rows if r["class_code"] == code and r["split"] == split]
            photos = len(subset)
            groups = len({r["split_group"] for r in subset})
            required = minima[code][split.lower()]
            if photos < required["min_samples"] or groups < required["min_independent_groups"]:
                raise ValueError(f"G0 minimum unmet: {code} {split}")
            counts[code][split] = {"photos": photos, "groups": groups}
    return counts, old_by_sha, visual_by_sha


def finalize(source, historical, resolved, review, candidate_plan, protocol_path, output):
    if output.exists():
        raise FileExistsError(output)
    protocol = json.loads(protocol_path.read_text())
    require_approved_protocol(protocol)  # Fail before touching files or creating output.
    plan_report = json.loads((candidate_plan / "summary.json").read_text())
    plan_path = candidate_plan / "candidate-partitions.csv"
    if plan_report.get("status") != "FEASIBLE_CANDIDATE_PLAN_NOT_ADMITTED_OR_SEALED" or \
            sha(plan_path.read_bytes()) != plan_report.get("candidate_manifest_sha256"):
        raise ValueError("Candidate plan changed")
    rows = read_csv(plan_path)
    counts, old_by_sha, visual_by_sha = validate_rows(rows, protocol, historical, review, resolved)
    if sha((source / "README.md").read_bytes()) != "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb":
        raise ValueError("Pinned PlantVillage rights declaration changed")
    parent = output.parent.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="g1-v1.3.1-stage-", dir=parent) as temporary:
        stage = Path(temporary)
        images = stage / "images"
        images.mkdir(mode=0o700)
        shutil.copyfile(source / "README.md", stage / "rights.md")
        admitted, evidence = [], []
        with zipfile.ZipFile(source / "data.zip") as archive:
            for row in rows:
                raw = archive.read(row["source_path"])
                if sha(raw) != row["sha256"]:
                    raise ValueError("Original image bytes changed")
                suffix = Path(row["source_path"]).suffix.lower()
                if suffix not in {".jpg", ".jpeg", ".png"}:
                    raise ValueError("Unrecognized image extension")
                path = images / (row["sha256"] + suffix)
                path.write_bytes(raw)
                with Image.open(path) as image:
                    image.load()
                    if image.width < 128 or image.height < 128:
                        raise ValueError("Image too small")
                common = {"image_id": row["sha256"], "sha256": row["sha256"],
                          "stratum_code": row["class_code"], "source": "plantvillage",
                          "source_revision": row["source_revision"], "source_label": row["source_label"],
                          "license": "CC-BY-SA-3.0", "capture_context": "CONTROLLED_LEAF",
                          "split_group": row["split_group"], "split": row["split"],
                          "relative_path": "images/" + path.name}
                admitted.append(common)
                reviewer = ("PlantVillage expert provenance + Codex internal visual quality screen"
                            if row["sha256"] in visual_by_sha else
                            "PlantVillage expert provenance + historical v1.2 G1 internal quality review")
                record = {**common, "decision": "ADMIT", "decision_at": protocol["approved_at"],
                          "source_original_path": row["source_path"],
                          "decision_by": "Codex G1 review under approved project-owner G0",
                          "decision_reason": "Pinned publisher file, applicable license, verified leaf ID, reviewed label and quality",
                          "rights": {"decision": "APPROVED", "allowed_uses": ["TRAINING", "EVALUATION"],
                                     "reviewed_at": protocol["approved_at"], "reviewer": reviewer,
                                     "proof_path": "rights.md", "attribution": "Mohanty, Hughes and Salathé; PlantVillage",
                                     "restrictions": "CC BY-SA 3.0; attribution and ShareAlike, including publisher-stated trained-algorithm condition"},
                          "label_review": {"decision": "APPROVED", "reviewed_at": protocol["approved_at"],
                                           "reviewer": reviewer, "source_label": row["source_label"],
                                           "stratum_code": row["class_code"],
                                           "evidence_note": "Publisher expert-curated label plus internal image quality/ambiguity review; no new independent agronomist"}}
                if row["sha256"] in visual_by_sha:
                    record["label_review"]["evidence_note"] += "; " + visual_by_sha[row["sha256"]]["ambiguity_note"]
                evidence.append(record)
        write_csv(stage / "strata.csv", admitted)
        for code, name in (("POTATO_EARLY_BLIGHT", "potato-early-blight"),
                           ("POTATO_LATE_BLIGHT", "potato-late-blight"),
                           ("POTATO_HEALTHY", "potato-healthy"),
                           ("OTHER_CROP", "other-crop")):
            write_csv(stage / (name + ".csv"), [r for r in admitted if r["stratum_code"] == code])
        (stage / "evidence.json").write_text(json.dumps({"schema_version": 1, "records": evidence},
                                                      ensure_ascii=False, indent=2) + "\n")
        # Seal uses the four technical strata, including both negative targets.
        from agro_ml.data.partitioning import seal_test_partitions, verify_test_partition_seal
        seal_rows = [{"image_id": r["image_id"], "sha256": r["sha256"],
                      "class_code": r["stratum_code"], "split_group": r["split_group"],
                      "split": r["split"]} for r in admitted]
        seal_test_partitions(seal_rows, stage / "test-seal.json", protocol_version="1.3.1")
        verify_test_partition_seal(seal_rows, stage / "test-seal.json")
        with (source / "data.zip").open("rb") as stream:
            archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if archive_sha != "fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84":
            raise ValueError("Pinned PlantVillage archive changed")
        report = {"status": "G1_V1_3_1_ADMITTED_AND_TEST_SEALED", "protocol_sha256": sha(protocol_path.read_bytes()),
                  "source_archive_sha256": archive_sha,
                  "source_label_mapping_sha256": sha(MAPPING_PATH.read_bytes()),
                  "counts": counts, "admitted_photos": len(admitted),
                  "admitted_groups": len({r["split_group"] for r in admitted}),
                  "test_count": sum(r["split"] == "TEST" for r in admitted),
                  "historical_test_overlap": 0, "cross_partition_group_overlap": 0,
                  "manifest_sha256": sha((stage / "strata.csv").read_bytes()),
                  "evidence_sha256": sha((stage / "evidence.json").read_bytes()),
                  "test_seal_sha256": sha((stage / "test-seal.json").read_bytes()),
                  "model_training_or_test_evaluation": False}
        (stage / "g1-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        os.replace(stage, output)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source_dir", "historical_dir", "resolved_dir", "review_dir", "candidate_plan_dir",
                 "protocol_path", "new_output_dir"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    finalize(args.source_dir, args.historical_dir, args.resolved_dir, args.review_dir,
             args.candidate_plan_dir, args.protocol_path, args.new_output_dir)
