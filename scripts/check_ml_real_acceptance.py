#!/usr/bin/env python3
"""Preflight for real G3 acceptance; never activates a policy or re-evaluates TEST.

It verifies the exact private G2 release and G1 admission record, then writes a
reproducible readiness report. End-to-end acceptance remains task 9.1/G3.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))
sys.path.insert(0, str(ROOT / "services/diagnosis/app/infrastructure"))

from agro_ml.pilot_release import load_pilot_bundle  # noqa: E402
from pilot_policy_evidence import (  # noqa: E402
    APPROVED_BUNDLE_SHA256, APPROVED_G2_ACTA_SHA256, verify_pilot_policy_evidence,
)

G1_REPORT_SHA256 = "cfdf69cf04e813b0e98070a4048bd5ed174eafc36cc7012838e9e2e141655d75"
FIXTURE_PATTERN = re.compile(r"fixture|synthetic|dummy|fake|^ci-", re.IGNORECASE)


class RealAcceptanceError(Exception):
    pass


class FixtureRejectedError(RealAcceptanceError):
    pass


class TamperedArtifactError(RealAcceptanceError):
    pass


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RealAcceptanceError("EVIDENCE_MISSING: archivo ausente o enlace simbólico")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_g1_directory(directory: Path, bundle: dict) -> dict:
    report_path = directory / "g1-report.json"
    if sha256_file(report_path) != G1_REPORT_SHA256:
        raise TamperedArtifactError("G1_REPORT_DIGEST_MISMATCH")
    report = _json(report_path)
    if report.get("status") != "G1_PILOT_VERIFIED" or report.get("protocol_version") != "1.2.0":
        raise FixtureRejectedError("G1_NOT_ADMITTED: registro real de admisión requerido")
    if any(report.get(key) != 0 for key in (
            "exact_duplicate_hashes", "cross_partition_leaf_ids", "selected_unresolved_visual_pairs")):
        raise RealAcceptanceError("G1_INVALID: duplicados o grupos sin resolver")
    for code in ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"):
        for split in ("TRAIN", "VAL", "TEST"):
            item = report["counts"][code][split]
            if item["samples"] < item["minimum_samples"] or item["groups"] < item["minimum_groups"]:
                raise RealAcceptanceError("G1_INVALID: mínimos de clase/grupo incumplidos")
    manifest_hashes = {}
    for name, expected in report["manifest_sha256"].items():
        actual = sha256_file(directory / name)
        if actual != expected:
            raise TamperedArtifactError("G1_MANIFEST_DIGEST_MISMATCH: " + name)
        manifest_hashes[name] = actual
    for split in ("train", "val", "test"):
        for label in ("positives", "negatives"):
            name = f"{split}-{label}.csv"
            actual = sha256_file(directory / name)
            if actual != bundle["manifest_component_checksums"][split][label]:
                raise TamperedArtifactError("G1_SPLIT_DIGEST_MISMATCH: " + name)
            manifest_hashes[name] = actual
    seal_hash = sha256_file(directory / "test-seal.json")
    if seal_hash != report["test_seal_sha256"]:
        raise TamperedArtifactError("G1_TEST_SEAL_DIGEST_MISMATCH")
    seal = _json(directory / "test-seal.json")
    if seal.get("protocol_version") != "1.2.0" or seal.get("test_count") != 347:
        raise RealAcceptanceError("G1_TEST_SEAL_INVALID")
    return {"g1_report_sha256": G1_REPORT_SHA256,
            "test_seal_sha256": seal_hash, "manifest_sha256": manifest_hashes,
            "test_images_read": False}


def _write_once(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError("El reporte ya existe; elegir otra ruta para preservar la evidencia")
    with tempfile.TemporaryDirectory(prefix="g3-preflight-", dir=path.parent) as temporary:
        staged = Path(temporary) / "report.json"
        staged.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                          encoding="utf-8")
        # Same-directory hard link is an atomic create-if-absent. A concurrent
        # invocation cannot replace or truncate an existing evidence report.
        os.link(staged, path)


def run_real_acceptance(release_bundle_path: Path, approval_path: Path,
                        policy_file_path: Path, g1_directory: Path,
                        output_report_path: Path, command_args: list[str]) -> dict:
    """Verify prerequisites and preserve a report; G3 is never approved here."""
    report = {"schema_version": 1, "status": "FAILED_PRECHECK", "g3_status": "NOT_APPROVED",
              "policy_activation": "NOT_PERFORMED", "test_reopened": False,
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "command": "python scripts/check_ml_real_acceptance.py --release-bundle <private-G2> "
                         "--g2-approval <private-G2> --policy-file <draft> "
                         "--g1-directory <private-G1> --output-report <new-path>",
              "input_argument_count": len(command_args)}
    failure = None
    try:
        for path in (release_bundle_path, approval_path, policy_file_path):
            if FIXTURE_PATTERN.search(path.name):
                raise FixtureRejectedError("FIXTURE_REJECTED: artefacto de prueba")
        if sha256_file(release_bundle_path) != APPROVED_BUNDLE_SHA256:
            raise TamperedArtifactError("G2_BUNDLE_DIGEST_MISMATCH")
        if sha256_file(approval_path) != APPROVED_G2_ACTA_SHA256:
            raise TamperedArtifactError("G2_APPROVAL_DIGEST_MISMATCH")
        policy = _json(policy_file_path)
        evidence = verify_pilot_policy_evidence(policy, release_bundle_path, approval_path)
        _model, bundle, test_report = load_pilot_bundle(
            release_bundle_path, APPROVED_BUNDLE_SHA256, require_approval_record=True)
        if not test_report.get("g0_numeric_pass"):
            raise RealAcceptanceError("G2_TEST_NOT_ELIGIBLE")
        dataset = verify_g1_directory(g1_directory, bundle)
        report.update({"status": "PREREQUISITES_VERIFIED_G3_PENDING",
                       "bundle_sha256": APPROVED_BUNDLE_SHA256,
                       "approval_sha256": APPROVED_G2_ACTA_SHA256,
                       "policy_sha256": sha256_file(policy_file_path),
                       "policy_id": policy["policy_id"],
                       "test_report_sha256": evidence["test_report_sha256"],
                       "g1": dataset,
                       "catalog_review": "NOT_VERIFIED",
                       "full_flow_result": "NOT_EXECUTED"})
    except Exception as exc:
        failure = exc
        report["failure_code"] = type(exc).__name__
    _write_once(output_report_path, report)
    if failure is not None:
        if isinstance(failure, RealAcceptanceError):
            raise failure
        raise RealAcceptanceError("PRECHECK_FAILED") from failure
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-bundle", type=Path, required=True)
    parser.add_argument("--g2-approval", type=Path, required=True)
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument("--g1-directory", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_real_acceptance(args.release_bundle, args.g2_approval,
                                     args.policy_file, args.g1_directory,
                                     args.output_report, argv or sys.argv[1:])
    except (RealAcceptanceError, FileExistsError) as exc:
        print(type(exc).__name__ + ": " + str(exc).split(":", 1)[0], file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "g3_status": report["g3_status"],
                      "output_report": str(args.output_report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
