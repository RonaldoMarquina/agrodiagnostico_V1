"""Package the frozen candidate and its one-shot TEST evidence for G2 review.

This is a private review package, not an approved model-bundle.v1 release.
It reads the completed TEST report, never TEST manifests or images.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from agro_ml.pilot_selection import verify_freeze
from agro_ml.pilot_training import CLASSES, sha256


def prepare(freeze_path: Path, report_path: Path, access_path: Path,
            expected_report_sha256: str, output_dir: Path) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    verify_freeze(freeze_path)
    if sha256(report_path) != expected_report_sha256:
        raise ValueError("Reporte TEST distinto del resultado de evaluación única")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    access = json.loads(access_path.read_text(encoding="utf-8"))
    if (access.get("status") != "COMPLETED" or access.get("report_sha256") != expected_report_sha256
            or report.get("dataset_split") != "TEST" or not report.get("g0_numeric_pass")
            or report.get("g2_approval") is not None
            or report.get("provenance", {}).get("freeze_sha256") != sha256(freeze_path)
            or report["provenance"]["weights_sha256"] != freeze["file_sha256"]["pilot-weights.safetensors"]
            or freeze.get("selected_architecture") != "mobilenet_v3_small"):
        raise ValueError("Candidato o evidencia TEST no elegible para revisión G2")
    output_dir.mkdir(parents=True, exist_ok=False)
    files = {"weights.safetensors": freeze_path.parent / "pilot-weights.safetensors",
             "config.json": freeze_path.parent / "config.json",
             "calibration.json": freeze_path.parent / "calibration.json",
             "thresholds.json": freeze_path.parent / "thresholds.json",
             "protocol-g0.json": freeze_path.parent / "protocol-g0.json",
             "freeze.json": freeze_path,
             "test-report.json": report_path,
             "test-access.json": access_path}
    for name, source in files.items():
        shutil.copyfile(source, output_dir / name)
    manifest = {"schema_version": 1, "status": "READY_FOR_G2_REVIEW_UNAPPROVED",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "model_id": "agrodiagnostico-potato-blights-mobilenetv3-small",
                "architecture": "mobilenet_v3_small",
                "pilot_scope": "identified_crop=POTATO; early and late blight only",
                "published_class_map": {"0": CLASSES[0], "1": CLASSES[1]},
                "technical_reject_index": 2,
                "technical_reject_target": "OTHER_CROP",
                "g0_version": "1.2.0", "g1_evidence_sha256": freeze["g1_evidence_sha256"],
                "manifest_sha256": {"train": freeze["train_manifest_sha256"],
                                    "val": freeze["val_manifest_sha256"],
                                    "test": report["provenance"]["test_manifest_sha256"]},
                "test_seal_sha256": report["provenance"]["test_seal_sha256"],
                "g0_numeric_pass": True, "g2_approval": None,
                "external_status": "NOT_AVAILABLE",
                "full_flow_latency_status": "NOT_MEASURED",
                "file_sha256": {name: sha256(output_dir / name) for name in files}}
    path = output_dir / "review-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"package": str(output_dir), "status": manifest["status"],
            "manifest_sha256": sha256(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--test-report", type=Path, required=True)
    parser.add_argument("--test-access", type=Path, required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.freeze, args.test_report, args.test_access,
                             args.expected_report_sha256, args.output_dir), sort_keys=True))


if __name__ == "__main__":
    main()
