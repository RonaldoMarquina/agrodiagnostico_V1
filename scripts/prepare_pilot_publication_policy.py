#!/usr/bin/env python3
"""Create a private, unimported policy draft from the exact approved G2 bundle."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/diagnosis"))

from app.infrastructure.pilot_policy_evidence import (  # noqa: E402
    APPROVED_BUNDLE_SHA256, APPROVED_G2_ACTA_SHA256, PILOT_CLASSES,
    _read_pinned, verify_pilot_policy_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-bundle", type=Path, required=True)
    parser.add_argument("--g2-approval", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.actor.strip():
        parser.error("--actor no puede estar vacío")
    bundle = _read_pinned(args.release_bundle, APPROVED_BUNDLE_SHA256)
    approval = _read_pinned(args.g2_approval, APPROVED_G2_ACTA_SHA256)
    payload = {
        "schema_version": 1,
        "policy_id": str(uuid.uuid4()),
        "policy_version": "0.1.0-pilot",
        "target_model": {"model_id": bundle["model_id"],
                         "model_version": bundle["model_version"],
                         "dataset_version": bundle["dataset_version"],
                         "bundle_digest": APPROVED_BUNDLE_SHA256},
        "approved_classes": [
            {"class_code": code, "crop_code": "POTATO",
             "min_confidence_threshold": bundle["rejection_components"]["min_confidence_threshold"],
             "calibration_params": bundle["calibration"]["parameters_per_class"][code]}
            for code in PILOT_CLASSES
        ],
        "unsupported_classes": [],
        "catalog_requirements": {"require_reviewed_catalog": True},
        "governance": {"g0_protocol_version": "1.2.0",
                       "g2_approval_reference": approval["approval_id"],
                       "approved_by": approval["approved_by"],
                       "approved_at": approval["approved_at"]},
        "audit": {"imported_by": args.actor,
                  "imported_at": datetime.now(timezone.utc).isoformat()},
    }
    verify_pilot_policy_evidence(payload, args.release_bundle, args.g2_approval)
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("No se sobrescribe una política privada existente")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": "DRAFT_NOT_IMPORTED_OR_ACTIVE",
                      "policy_id": payload["policy_id"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
