#!/usr/bin/env python3
"""Materializa G1 v1.4.1 desde evidencia PlantVillage fijada, sin abrir Sikkim."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))

from agro_ml.v141_gates import validate_train_val, verify_pretraining_gate

PV_REVISION = "9e97599868962bd0079b8db4b7f1efa9185fa1e7"
PV_RIGHTS_SHA256 = "9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb"


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def materialize(args: argparse.Namespace) -> dict:
    if args.output.exists():
        raise FileExistsError(f"salida ya existe: {args.output}")
    protocol, history, parent = map(read_json, (args.protocol, args.history, args.parent_gate))
    with (args.source / "strata.csv").open(newline="", encoding="utf-8") as stream:
        source_rows = list(csv.DictReader(stream))
    evidence = {row["sha256"]: row for row in read_json(args.source / "evidence.json")["records"]}
    blocked = {row["split_group"] for row in source_rows if row["split"] == "TEST"}
    records = []
    for row in source_rows:
        if row["split"] not in {"TRAIN", "VAL"}:
            continue
        proof = evidence.get(row["sha256"])
        if not proof or proof.get("decision") != "ADMIT":
            raise ValueError("archivo sin decisión de admisión")
        rights = args.source / proof["rights"]["proof_path"]
        image = args.source / row["relative_path"]
        if sha(rights) != PV_RIGHTS_SHA256 or sha(image) != row["sha256"]:
            raise ValueError("derechos o bytes PlantVillage alterados")
        records.append({
            "image_id": f"plantvillage:{row['sha256']}", "sha256": row["sha256"],
            "source_id": "plantvillage", "source_revision": PV_REVISION,
            "source_url": f"https://huggingface.co/datasets/mohanty/PlantVillage/commit/{PV_REVISION}",
            "author": "David P. Hughes; Marcel Salathé; Sharada P. Mohanty",
            "license": "CC-BY-SA-3.0", "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
            "source_path": proof["source_original_path"], "split": row["split"],
            "split_group": row["split_group"], "decision": "ADMIT_TRAIN_VAL",
            "decision_reason": proof["decision_reason"], "rights_proof_path": "plantvillage-rights.md",
            "source_label": row["source_label"], "stratum_code": row["stratum_code"],
            "label_review": proof["label_review"]["evidence_note"],
        })
    records.sort(key=lambda row: (row["split"], row["stratum_code"], row["image_id"]))
    counts = verify_pretraining_gate(protocol, history, records, parent,
                                     blocked_test_groups=blocked)
    stage = Path(mkdtemp(prefix="g1-v141-", dir=str(args.output.parent)))
    try:
        manifest = stage / "plantvillage-train-val.jsonl"
        manifest.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")) + "\n" for row in records),
                            encoding="utf-8")
        shutil.copyfile(args.source / "rights.md", stage / "plantvillage-rights.md")
        binding = {
            "status": "INHERITED_SEALED_NOT_OPENED",
            "manifest_sha256": protocol["external_inherited"]["manifest_sha256"],
            "seal_sha256": protocol["external_inherited"]["seal_sha256"],
            "parent_protocol_sha256": protocol["external_inherited"]["seal_protocol_sha256"],
            "external_rows_read": 0,
        }
        (stage / "external-inherited-binding.json").write_text(
            json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = {
            "status": "G1_V1_4_1_CLOSED_PRIVATE_TRAIN_VAL_VERIFIED_EXTERNAL_UNOPENED",
            "protocol_sha256": sha(args.protocol), "history_sha256": sha(args.history),
            "plantvillage_manifest_sha256": sha(manifest), "rights_sha256": PV_RIGHTS_SHA256,
            "historical_test_group_count_blocked": len(blocked), "counts": counts,
            "training_executed": False, "historical_test_opened": False,
            "sikkim_external_opened": False, "external_binding": binding,
        }
        (stage / "g1-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        os.replace(stage, args.output)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--parent-gate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(materialize(parser.parse_args()), sort_keys=True))
