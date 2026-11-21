"""G3 preflight tests use tiny identified fixtures, never private datasets."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from check_ml_real_acceptance import (
    FixtureRejectedError, RealAcceptanceError, TamperedArtifactError,
    run_real_acceptance, verify_g1_directory,
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestRealAcceptanceCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "model-bundle.json"
        self.approval = self.root / "g2-approval.json"
        self.policy = self.root / "policy.json"
        for path in (self.bundle, self.approval, self.policy):
            path.write_text("{}", encoding="utf-8")
        self.policy.write_text(json.dumps({"policy_id": str(uuid.uuid4())}),
                               encoding="utf-8")
        self.output = self.root / "report.json"

    def tearDown(self):
        self.temporary.cleanup()

    def _run(self, bundle: Path | None = None):
        return run_real_acceptance(bundle or self.bundle, self.approval,
                                   self.policy, self.root, self.output,
                                   ["--token=never-persist-this"])

    def test_fixture_rejected_and_failure_report_sanitized(self):
        fixture = self.root / "fixture-bundle.json"
        fixture.write_text("{}", encoding="utf-8")
        with self.assertRaises(FixtureRejectedError):
            self._run(fixture)
        report = self.output.read_text(encoding="utf-8")
        self.assertIn("FAILED_PRECHECK", report)
        self.assertNotIn("never-persist-this", report)
        self.assertEqual(list(self.root.glob("g3-preflight-*")), [])

    def test_bundle_digest_tamper_rejected(self):
        with self.assertRaises(TamperedArtifactError):
            self._run()
        self.assertEqual(json.loads(self.output.read_text())["g3_status"], "NOT_APPROVED")

    def test_successful_preflight_still_cannot_approve_g3(self):
        with (patch("check_ml_real_acceptance.APPROVED_BUNDLE_SHA256", digest(b"{}")),
              patch("check_ml_real_acceptance.APPROVED_G2_ACTA_SHA256", digest(b"{}")),
              patch("check_ml_real_acceptance.verify_pilot_policy_evidence",
                    return_value={"test_report_sha256": "a" * 64}),
              patch("check_ml_real_acceptance.load_pilot_bundle",
                    return_value=(None, {"manifest_component_checksums": {}},
                                  {"g0_numeric_pass": True})),
              patch("check_ml_real_acceptance.verify_g1_directory",
                    return_value={"test_images_read": False})):
            report = self._run()
        self.assertEqual(report["status"], "PREREQUISITES_VERIFIED_G3_PENDING")
        self.assertEqual(report["g3_status"], "NOT_APPROVED")
        self.assertEqual(report["policy_activation"], "NOT_PERFORMED")
        self.assertFalse(report["test_reopened"])
        self.assertEqual(list(self.root.glob("g3-preflight-*")), [])
        with self.assertRaises(FileExistsError):
            self._run()

    def test_g1_manifest_alteration_is_detected_without_images(self):
        report = {"status": "G1_PILOT_VERIFIED", "protocol_version": "1.2.0",
                  "exact_duplicate_hashes": 0, "cross_partition_leaf_ids": 0,
                  "selected_unresolved_visual_pairs": 0,
                  "counts": {code: {split: {"samples": 2, "groups": 1,
                                            "minimum_samples": 1, "minimum_groups": 1}
                                     for split in ("TRAIN", "VAL", "TEST")}
                             for code in ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT")},
                  "manifest_sha256": {}, "test_seal_sha256": ""}
        bundle = {"manifest_component_checksums": {}}
        for split in ("train", "val", "test"):
            bundle["manifest_component_checksums"][split] = {}
            for label in ("positives", "negatives"):
                name = f"{split}-{label}.csv"
                (self.root / name).write_bytes(b"fixture manifest")
                bundle["manifest_component_checksums"][split][label] = digest(b"fixture manifest")
        seal = {"protocol_version": "1.2.0", "test_count": 347}
        (self.root / "test-seal.json").write_text(json.dumps(seal), encoding="utf-8")
        report["test_seal_sha256"] = digest((self.root / "test-seal.json").read_bytes())
        report_path = self.root / "g1-report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with patch("check_ml_real_acceptance.G1_REPORT_SHA256", digest(report_path.read_bytes())):
            self.assertFalse(verify_g1_directory(self.root, bundle)["test_images_read"])
            (self.root / "test-positives.csv").write_bytes(b"altered")
            with self.assertRaises(TamperedArtifactError):
                verify_g1_directory(self.root, bundle)


if __name__ == "__main__":
    unittest.main()
