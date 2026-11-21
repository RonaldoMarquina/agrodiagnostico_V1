"""Conservatively exclude every candidate group implicated by a visual pair.

This never alters the historical v1.2 manifests or admits an image. The source
registry remains intact; the output is a new, private decision snapshot.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_csv(path, fields, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def resolve(audit_dir, output_dir):
    if output_dir.exists():
        raise FileExistsError(output_dir)
    registry_path = audit_dir / "registry.csv"
    pair_path = audit_dir / "visual-pairs.csv"
    source_report = json.loads((audit_dir / "summary.json").read_text())
    if sha(registry_path) != source_report["registry_sha256"] or sha(pair_path) != source_report["visual_pairs_sha256"]:
        raise ValueError("Audit inputs changed")
    rows = read_csv(registry_path)
    pairs = read_csv(pair_path)
    if len(pairs) != source_report["visual_pairs_for_review"]:
        raise ValueError("Visual pair count changed")
    by_sha = {row["sha256"]: row for row in rows}
    if len(by_sha) != len(rows):
        raise ValueError("Candidate SHA-256 repeated")
    rejected_groups = set()
    decisions = []
    for pair in pairs:
        candidate_hashes = [digest for digest in (pair["sha256_a"], pair["sha256_b"]) if digest in by_sha]
        if not candidate_hashes:
            raise ValueError("Pair without candidate")
        groups = {by_sha[digest]["leaf_id"] for digest in candidate_hashes}
        if "" in groups:
            raise ValueError("Pair has unverifiable group")
        rejected_groups.update(groups)
        decisions.append({**pair, "candidate_groups": "|".join(sorted(groups)),
                          "decision": "EXCLUDE_ALL_CANDIDATE_GROUPS",
                          "reason": "dHash pair; independent leaf identity not proven; conservative G1 exclusion"})
    changed = 0
    for row in rows:
        if row["leaf_id"] in rejected_groups and row["decision"] != "EXCLUDE":
            row["decision"] = "EXCLUDE"
            row["decision_reason"] = "VISUAL_PAIR_GROUP_CONSERVATIVE_EXCLUSION"
            changed += 1
    output_dir.mkdir(mode=0o700, parents=True)
    write_csv(output_dir / "registry.csv", list(rows[0]), rows)
    write_csv(output_dir / "pair-decisions.csv", list(decisions[0]), decisions)
    report = {
        "status": "VISUAL_PAIRS_RESOLVED_BY_GROUP_EXCLUSION_G1_OPEN",
        "source_registry_sha256": sha(registry_path),
        "source_visual_pairs_sha256": sha(pair_path),
        "registry_sha256": sha(output_dir / "registry.csv"),
        "pair_decisions_sha256": sha(output_dir / "pair-decisions.csv"),
        "pairs_resolved": len(decisions), "candidate_groups_excluded": len(rejected_groups),
        "newly_excluded_photos": changed,
        "decision_counts": dict(Counter(row["decision"] for row in rows)),
        "groups_by_class": {code: len({r["leaf_id"] for r in rows if r["class_code"] == code
                                          and r["leaf_id"] in rejected_groups})
                            for code in sorted({r["class_code"] for r in rows})},
        "caveat": "All implicated candidate groups are excluded; no image admitted or TEST sealed.",
    }
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_dir", type=Path)
    parser.add_argument("new_output_dir", type=Path)
    args = parser.parse_args()
    resolve(args.audit_dir, args.new_output_dir)
