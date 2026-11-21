"""Record the project owner's conditional G2 approval after independent load."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import jsonschema

from agro_ml.pilot_release import (SCHEMA, digest, load_pilot_bundle,
                                   synthetic_inference_check)


def record(bundle_path: Path, expected_staged_sha256: str) -> dict:
    directory = bundle_path.parent
    approval_path = directory / "g2-approval.json"
    if approval_path.exists():
        raise FileExistsError("G2 ya tiene acta; no reescribir aprobación")
    model, bundle, report = load_pilot_bundle(bundle_path, expected_staged_sha256)
    check = synthetic_inference_check(model, bundle)
    if (check["published_class_map"] != ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"]
            or check["identified_crop_required"] != "POTATO"
            or not report["g0_numeric_pass"]):
        raise ValueError("La carga independiente no cumple el piloto")
    approved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    bundle["governance"]["approved_at"] = approved_at
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()),
                                    format_checker=jsonschema.FormatChecker()).validate(bundle)
    temp = directory / "model-bundle.json.tmp"
    with temp.open("x", encoding="utf-8") as stream:
        json.dump(bundle, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    os.replace(temp, bundle_path)
    bundle_sha256 = digest(bundle_path)
    # This second load checks the exact bytes that the approval will identify.
    load_pilot_bundle(bundle_path, bundle_sha256)
    rates = report["rates"]
    approval = {
        "schema_version": 1, "status": "APPROVED_G2",
        "approval_id": bundle["governance"]["g2_approval_id"],
        "approved_by": "PROJECT_OWNER", "approved_at": approved_at,
        "decision_basis": "Instrucción expresa del responsable: aprobar G2 si la carga independiente de 5.5 pasa",
        "protocol_version": "1.2.0", "bundle_sha256": bundle_sha256,
        "test_report_sha256": digest(directory / "test-report.json"),
        "test_results": {
            "macro_f1": report["macro_f1"],
            "recall_by_class": {code: report["per_class"][code]["recall"]
                                for code in ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT")},
            "coverage": rates["coverage"], "selective_error": rates["selective_error"],
            "negative_acceptance": rates["negative_acceptance"],
            "ece": report["ece"], "brier": report["brier_score"],
            "g0_numeric_pass": True},
        "approved_scope": {"identified_crop": "POTATO",
                           "class_codes": ["POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"]},
        "limitations": ["EXTERNAL_NOT_AVAILABLE", "FULL_FLOW_LATENCY_NOT_MEASURED",
                        "POTATO_HEALTHY_REJECTION_NOT_MEASURED", "FIELD_GENERALIZATION_NOT_DEMONSTRATED"],
        "worker_real_activated": False,
        "publication_policy_activated": False,
        "g3_status": "PENDING",
    }
    with approval_path.open("x", encoding="utf-8") as stream:
        json.dump(approval, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    load_pilot_bundle(bundle_path, bundle_sha256, require_approval_record=True)
    return {"status": "APPROVED_G2", "approval_id": approval["approval_id"],
            "approved_at": approved_at, "bundle_sha256": bundle_sha256,
            "approval_record_sha256": digest(approval_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-staged-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(record(args.bundle, args.expected_staged_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
