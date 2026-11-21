"""Bind a proposed pilot policy to the exact private G2 release, without ML imports."""

import hashlib
import json
from pathlib import Path


APPROVED_BUNDLE_SHA256 = "93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41"
APPROVED_G2_ACTA_SHA256 = "579404dfe711fcae00c5d8964db669b8a66477f853d48a1fed45f72946d165f9"
PILOT_CLASSES = ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT")


def _read_pinned(path: Path, expected: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("EVIDENCE_MISSING: archivo G2 ausente o enlace simbólico")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("EVIDENCE_MISMATCH: SHA-256 de G2 distinto del aprobado")
    return json.loads(content)


def verify_pilot_policy_evidence(policy: dict, bundle_path: Path, approval_path: Path) -> dict:
    bundle = _read_pinned(bundle_path, APPROVED_BUNDLE_SHA256)
    approval = _read_pinned(approval_path, APPROVED_G2_ACTA_SHA256)
    if (bundle_path.parent.resolve() != approval_path.parent.resolve()
            or bundle.get("governance", {}).get("g0_protocol_version") != "1.2.0"
            or approval.get("status") != "APPROVED_G2"
            or approval.get("approved_by") != "PROJECT_OWNER"
            or approval.get("bundle_sha256") != APPROVED_BUNDLE_SHA256
            or approval.get("approval_id") != bundle["governance"]["g2_approval_id"]
            or approval.get("approved_at") != bundle["governance"]["approved_at"]
            or approval.get("test_report_sha256") != bundle["artifact_checksums"]["test_report_sha256"]
            or not approval.get("test_results", {}).get("g0_numeric_pass")):
        raise ValueError("EVIDENCE_MISMATCH: acta G2 incompatible")
    target = policy["target_model"]
    if target != {"model_id": bundle["model_id"],
                  "model_version": bundle["model_version"],
                  "dataset_version": bundle["dataset_version"],
                  "bundle_digest": APPROVED_BUNDLE_SHA256}:
        raise ValueError("POLICY_TARGET_MISMATCH: modelo, dataset o bundle")
    governance = policy["governance"]
    if governance != {"g0_protocol_version": "1.2.0",
                      "g2_approval_reference": approval["approval_id"],
                      "approved_by": "PROJECT_OWNER",
                      "approved_at": approval["approved_at"]}:
        raise ValueError("EVIDENCE_MISMATCH: aprobación de política")
    classes = policy["approved_classes"]
    if (len(classes) != 2 or {item["class_code"] for item in classes} != set(PILOT_CLASSES)
            or bundle["class_map"] != {str(index): {"class_code": code, "crop_code": "POTATO"}
                                       for index, code in enumerate(PILOT_CLASSES)}):
        raise ValueError("POLICY_SCOPE_MISMATCH: clases del piloto")
    for item in classes:
        code = item["class_code"]
        if (item["crop_code"] != "POTATO"
                or item["min_confidence_threshold"] != bundle["rejection_components"]["min_confidence_threshold"]
                or item["calibration_params"] != bundle["calibration"]["parameters_per_class"][code]):
            raise ValueError("POLICY_CALIBRATION_MISMATCH: umbral o calibrador")
    if policy.get("catalog_requirements") != {"require_reviewed_catalog": True}:
        raise ValueError("POLICY_CATALOG_MISMATCH: requiere catálogo revisado")
    return {"bundle_sha256": APPROVED_BUNDLE_SHA256,
            "approval_sha256": APPROVED_G2_ACTA_SHA256,
            "approval_id": approval["approval_id"],
            "test_report_sha256": approval["test_report_sha256"]}
