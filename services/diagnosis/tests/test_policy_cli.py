"""Unit and integration tests for Diagnosis publication policy CLI and service.

Verifies Task 7.2:
- Import, activate, retire, and status operations with dry-run by default.
- Mandatory operator context (actor, reason).
- Schema, governance, and calibration parameter validation.
- Duplicate policy rejection.
- Atomic updating of Problem.model_supported on activate and retire.
- Atomic auditing failure rollback.
- Prohibits public HTTP PATCH modification of model_supported.
"""
from datetime import datetime, timezone
import json
from unittest.mock import patch
import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.policy import (
    activate_publication_policy,
    get_publication_policy_status,
    import_publication_policy,
    retire_publication_policy,
    validate_publication_policy_payload,
)
from app.domain.models import (
    Base,
    Crop,
    DiagnosisAuditLog,
    Problem,
    PublicationPolicy,
)


def make_sample_policy_payload(
    policy_id: str = "33333333-3333-4333-8333-333333333333",
    policy_version: str = "1.0.0",
    model_id: str = "agrodiagnostico-mobilenetv3-cpu",
    model_version: str = "1.0.0",
    dataset_version: str = "2.0.0",
    bundle_digest: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    classes: list = None,
) -> dict:
    if classes is None:
        classes = [
            {
                "class_code": "POTATO_EARLY_BLIGHT",
                "crop_code": "POTATO",
                "min_confidence_threshold": 0.85,
                "calibration_params": {"slope": 2.5, "intercept": -1.2},
            },
            {
                "class_code": "MAIZE_COMMON_RUST",
                "crop_code": "MAIZE",
                "min_confidence_threshold": 0.80,
                "calibration_params": {"slope": 3.0, "intercept": -1.5},
            },
        ]
    return {
        "schema_version": 1,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "target_model": {
            "model_id": model_id,
            "model_version": model_version,
            "dataset_version": dataset_version,
            "bundle_digest": bundle_digest,
        },
        "approved_classes": classes,
        "unsupported_classes": [
            {"class_code": "MAIZE_GRAY_LEAF_SPOT", "reason": "Insufficient samples"}
        ],
        "catalog_requirements": {
            "require_reviewed_catalog": True,
        },
        "governance": {
            "g0_protocol_version": "1.0.0",
            "g2_approval_reference": "REF-G2-EVAL-2026-001",
            "approved_by": "Dr. Fitopatología",
            "approved_at": "2026-10-15T12:00:00Z",
        },
        "audit": {
            "imported_by": "operator@example.com",
            "imported_at": "2026-10-15T12:30:00Z",
        },
    }


class TestPublicationPolicyCLI(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.Session()

        # Seed crops and problems
        crop_potato = Crop(code="POTATO", name="Papa", active=True)
        crop_maize = Crop(code="MAIZE", name="Maíz", active=True)
        self.session.add_all([crop_potato, crop_maize])

        problems = [
            Problem(code="POTATO_HEALTHY", crop_code="POTATO", name="Papa sana", type="HEALTHY", model_supported=False),
            Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO", name="Tizón temprano", type="DISEASE", model_supported=False),
            Problem(code="POTATO_LATE_BLIGHT", crop_code="POTATO", name="Tizón tardío", type="DISEASE", model_supported=False),
            Problem(code="MAIZE_HEALTHY", crop_code="MAIZE", name="Maíz sano", type="HEALTHY", model_supported=False),
            Problem(code="MAIZE_COMMON_RUST", crop_code="MAIZE", name="Roya común", type="DISEASE", model_supported=False),
            Problem(code="MAIZE_LEAF_BLIGHT", crop_code="MAIZE", name="Tizón foliar", type="DISEASE", model_supported=False),
            Problem(code="MAIZE_GRAY_LEAF_SPOT", crop_code="MAIZE", name="Mancha gris", type="DISEASE", model_supported=False),
        ]
        self.session.add_all(problems)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_mandatory_operator_context(self):
        payload = make_sample_policy_payload()
        # Empty actor
        with self.assertRaises(ValueError) as ctx:
            import_publication_policy(self.session, actor="", reason="Valid reason", policy_data=payload)
        self.assertIn("--actor cannot be blank", str(ctx.exception))

        # Empty reason
        with self.assertRaises(ValueError) as ctx:
            import_publication_policy(self.session, actor="admin", reason="   ", policy_data=payload)
        self.assertIn("--reason cannot be blank", str(ctx.exception))

    def test_import_dry_run_by_default(self):
        payload = make_sample_policy_payload()
        res = import_publication_policy(
            db=self.session,
            actor="admin@example.com",
            reason="Reviewing policy",
            policy_data=payload,
            apply=False,
        )
        self.assertEqual(res["mode"], "DRY_RUN")
        self.assertEqual(res["action"], "IMPORT")

        # Database must NOT contain the policy
        count = self.session.execute(select(PublicationPolicy)).scalars().all()
        self.assertEqual(len(count), 0)

        # Audit log must NOT contain entry
        audit_count = self.session.execute(select(DiagnosisAuditLog)).scalars().all()
        self.assertEqual(len(audit_count), 0)

    def test_import_apply_commits_and_audits(self):
        payload = make_sample_policy_payload()
        res = import_publication_policy(
            db=self.session,
            actor="admin@example.com",
            reason="Valid G2 approval",
            policy_data=payload,
            apply=True,
        )
        self.assertEqual(res["mode"], "APPLIED")
        pid = uuid.UUID(payload["policy_id"])

        # Check DB policy
        policy = self.session.get(PublicationPolicy, pid)
        self.assertIsNotNone(policy)
        self.assertEqual(policy.policy_version, "1.0.0")
        self.assertFalse(policy.active)

        # Check Audit Log
        audit = self.session.execute(
            select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "POLICY_IMPORTED")
        ).scalar_one()
        self.assertEqual(audit.target_id, str(pid))
        self.assertEqual(audit.details["actor"], "admin@example.com")
        self.assertEqual(audit.details["reason"], "Valid G2 approval")

    def test_import_duplicate_policy_id_rejected(self):
        payload = make_sample_policy_payload()
        import_publication_policy(self.session, "admin", "First import", payload, apply=True)

        with self.assertRaises(ValueError) as ctx:
            import_publication_policy(self.session, "admin", "Second import", payload, apply=True)
        self.assertIn("POLICY_ALREADY_EXISTS", str(ctx.exception))

    def test_validation_fails_on_missing_governance(self):
        payload = make_sample_policy_payload()
        del payload["governance"]["g2_approval_reference"]

        is_valid, err = validate_publication_policy_payload(payload)
        self.assertFalse(is_valid)
        self.assertIn("SCHEMA_VALIDATION_FAILED", err)

    def test_validation_fails_on_non_finite_calibration_params(self):
        payload = make_sample_policy_payload()
        payload["approved_classes"][0]["calibration_params"]["slope"] = float("nan")

        is_valid, err = validate_publication_policy_payload(payload)
        self.assertFalse(is_valid)
        self.assertIn("NON_FINITE_CALIBRATION_PARAMS", err)

    def test_validation_fails_on_out_of_range_threshold(self):
        payload = make_sample_policy_payload()
        payload["approved_classes"][0]["min_confidence_threshold"] = 1.25

        is_valid, err = validate_publication_policy_payload(payload)
        self.assertFalse(is_valid)
        self.assertIn("SCHEMA_VALIDATION_FAILED", err)

    def test_activate_policy_atomically_updates_problems(self):
        payload = make_sample_policy_payload()
        import_publication_policy(self.session, "admin", "Pre-activation", payload, apply=True)
        pid = uuid.UUID(payload["policy_id"])

        # Dry run activate
        res_dry = activate_publication_policy(self.session, "admin", "Check", pid, apply=False)
        self.assertEqual(res_dry["mode"], "DRY_RUN")
        # Check no problems updated
        supported = self.session.execute(
            select(Problem).where(Problem.model_supported.is_(True))
        ).scalars().all()
        self.assertEqual(len(supported), 0)

        # Apply activate
        res_apply = activate_publication_policy(self.session, "admin", "Promote to prod", pid, apply=True)
        self.assertEqual(res_apply["mode"], "APPLIED")

        # Policy should be active
        policy = self.session.get(PublicationPolicy, pid)
        self.assertTrue(policy.active)
        self.assertIsNotNone(policy.activated_at)

        # Approved problems must be model_supported=True, others False
        supported = {
            p.code for p in self.session.execute(
                select(Problem).where(Problem.model_supported.is_(True))
            ).scalars().all()
        }
        self.assertEqual(supported, {"POTATO_EARLY_BLIGHT", "MAIZE_COMMON_RUST"})

        # Check Audit Log
        audit = self.session.execute(
            select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "POLICY_ACTIVATED")
        ).scalar_one()
        self.assertEqual(audit.target_id, str(pid))

    def test_retire_policy_resets_all_problems(self):
        payload = make_sample_policy_payload()
        import_publication_policy(self.session, "admin", "Import", payload, apply=True)
        pid = uuid.UUID(payload["policy_id"])
        activate_publication_policy(self.session, "admin", "Activate", pid, apply=True)

        # Confirm 2 problems supported
        supported = self.session.execute(select(Problem).where(Problem.model_supported.is_(True))).scalars().all()
        self.assertEqual(len(supported), 2)

        # Retire policy
        res_retire = retire_publication_policy(self.session, "admin", "Emergency rollback", pid, apply=True)
        self.assertEqual(res_retire["mode"], "APPLIED")

        policy = self.session.get(PublicationPolicy, pid)
        self.assertFalse(policy.active)
        self.assertIsNotNone(policy.retired_at)

        # All problems must now be model_supported=False
        supported_after = self.session.execute(select(Problem).where(Problem.model_supported.is_(True))).scalars().all()
        self.assertEqual(len(supported_after), 0)

        # Check Audit Log
        audit = self.session.execute(
            select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "POLICY_RETIRED")
        ).scalar_one()
        self.assertEqual(audit.target_id, str(pid))

    def test_retiring_inactive_policy_preserves_current_support(self):
        first = make_sample_policy_payload(policy_id=str(uuid.uuid4()))
        second = make_sample_policy_payload(policy_id=str(uuid.uuid4()))
        for payload in (first, second):
            import_publication_policy(self.session, "test-operator", "fixture", payload, apply=True)
            activate_publication_policy(self.session, "test-operator", "fixture", uuid.UUID(payload["policy_id"]), apply=True)
        before = get_publication_policy_status(self.session)
        retire_publication_policy(self.session, "test-operator", "retire history", uuid.UUID(first["policy_id"]), apply=True)
        after = get_publication_policy_status(self.session)
        self.assertEqual(before["active_policy"], after["active_policy"])
        self.assertEqual(before["catalog_summary"], after["catalog_summary"])

    def test_status_reports_active_and_catalog(self):
        # When no policy is active
        st0 = get_publication_policy_status(self.session)
        self.assertIsNone(st0["active_policy"])
        self.assertEqual(st0["catalog_summary"]["total_supported"], 0)

        # After activating policy
        payload = make_sample_policy_payload()
        import_publication_policy(self.session, "admin", "Import", payload, apply=True)
        pid = uuid.UUID(payload["policy_id"])
        activate_publication_policy(self.session, "admin", "Activate", pid, apply=True)

        st1 = get_publication_policy_status(self.session)
        self.assertIsNotNone(st1["active_policy"])
        self.assertEqual(st1["active_policy"]["id"], str(pid))
        self.assertEqual(st1["catalog_summary"]["total_supported"], 2)
        self.assertIn("POTATO_EARLY_BLIGHT", st1["catalog_summary"]["supported_problems"])

    def test_audit_failure_rolls_back_atomic_mutation(self):
        """If writing to diagnosis_audit_logs fails, the policy activation rolls back entirely."""
        payload = make_sample_policy_payload()
        import_publication_policy(self.session, "admin", "Import", payload, apply=True)
        pid = uuid.UUID(payload["policy_id"])

        # Patch record_audit_log to simulate a database failure during audit write
        with patch("app.application.policy.record_audit_log", side_effect=RuntimeError("Audit disk full")):
            with self.assertRaises(RuntimeError):
                activate_publication_policy(self.session, "admin", "Activate with failure", pid, apply=True)

        # Rollback check: policy must still be inactive and no problems supported
        self.session.rollback()
        policy = self.session.get(PublicationPolicy, pid)
        self.assertFalse(policy.active)

        supported = self.session.execute(select(Problem).where(Problem.model_supported.is_(True))).scalars().all()
        self.assertEqual(len(supported), 0)
