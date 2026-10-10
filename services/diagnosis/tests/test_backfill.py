"""Unit tests for legacy PENDIENTE backfill application service and CLI (Task 4.4).

Tests:
- Dry-run mode by default leaves database completely unmodified (zero outbox events, zero audit logs).
- Apply mode creates DiagnosisOutbox (Requested v2) and DiagnosisAuditLog for candidates.
- Double execution is strictly idempotent (zero duplicate outbox records).
- Concurrency with cancellation: non-PENDIENTE diagnoses are skipped.
- Historical absent correlation_id: generates recovery correlation_id.
- Legacy object keys: preserved exactly as-is without moving objects.
- Tombstones: included with is_tombstone=True because deletion does not cancel work.
- Specific --ids filtering targets only requested UUIDs.
- Simulation guard: rejects running with real data in simulation profile.
"""
from datetime import datetime, timezone
import os
import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.backfill import run_backfill
from app.domain.models import Base, Diagnosis, DiagnosisAuditLog, DiagnosisOutbox


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.owner_id = uuid.uuid4()

    def _create_diagnosis(
        self,
        status="PENDIENTE",
        object_key=None,
        correlation_id=None,
        deleted_at=None,
    ):
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        key = object_key or f"diagnoses/{diag_id}/{uuid.uuid4()}"  # Legacy format

        with self.SessionLocal() as session:
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.owner_id,
                status=status,
                object_key=key,
                image_sha256="abc123sha",
                image_content_type="image/jpeg",
                image_size_bytes=2048,
                correlation_id=correlation_id,
                deleted_at=deleted_at,
                created_at=now,
                updated_at=now,
            )
            session.add(diag)
            session.commit()
        return diag_id, key

    def test_dry_run_leaves_database_unmodified(self):
        d1, _ = self._create_diagnosis()
        d2, _ = self._create_diagnosis()

        with self.SessionLocal() as session:
            res = run_backfill(session, apply=False)
            self.assertEqual(res.scanned, 2)
            self.assertEqual(res.candidates, 2)
            self.assertEqual(res.applied, 0)
            self.assertEqual(len(res.details), 2)
            self.assertFalse(res.details[0]["applied"])

        # Verify DB is completely empty of outbox and audit records
        with self.SessionLocal() as session:
            outbox_count = len(session.execute(select(DiagnosisOutbox)).scalars().all())
            audit_count = len(session.execute(select(DiagnosisAuditLog)).scalars().all())
            self.assertEqual(outbox_count, 0)
            self.assertEqual(audit_count, 0)

    def test_apply_mode_creates_outbox_and_audit_with_legacy_keys(self):
        # Create one diagnosis without correlation_id and with legacy object_key
        d1, legacy_key = self._create_diagnosis(correlation_id=None)

        with self.SessionLocal() as session:
            res = run_backfill(session, apply=True)
            self.assertEqual(res.candidates, 1)
            self.assertEqual(res.applied, 1)

        with self.SessionLocal() as session:
            # Check Diagnosis updated with correlation_id
            diag = session.get(Diagnosis, d1)
            self.assertIsNotNone(diag.correlation_id)

            # Check outbox record
            outbox = session.execute(
                select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == d1)
            ).scalar_one()
            self.assertEqual(outbox.event_type, "DiagnosisRequested")
            self.assertEqual(outbox.schema_version, 2)
            self.assertEqual(outbox.routing_key, "diagnosis.requested.v2")
            self.assertEqual(outbox.attempt_number, 1)

            # Envelope payload must use the exact legacy object key
            payload = outbox.envelope["payload"]
            self.assertEqual(payload["object_key"], legacy_key)
            self.assertEqual(payload["diagnosis_id"], str(d1))
            self.assertEqual(payload["owner_id"], str(self.owner_id))

            # Check audit log
            audit = session.execute(
                select(DiagnosisAuditLog).where(DiagnosisAuditLog.target_id == str(d1))
            ).scalar_one()
            self.assertEqual(audit.action, "BACKFILL_REQUESTED")
            self.assertEqual(audit.target_type, "diagnosis")
            self.assertEqual(audit.correlation_id, diag.correlation_id)

    def test_double_execution_is_strictly_idempotent(self):
        d1, _ = self._create_diagnosis()

        with self.SessionLocal() as session:
            res1 = run_backfill(session, apply=True)
            self.assertEqual(res1.applied, 1)

        # Second execution
        with self.SessionLocal() as session:
            res2 = run_backfill(session, apply=True)
            self.assertEqual(res2.scanned, 1)
            self.assertEqual(res2.candidates, 0)
            self.assertEqual(res2.applied, 0)

        # Total outbox count remains 1
        with self.SessionLocal() as session:
            outbox_count = len(session.execute(select(DiagnosisOutbox)).scalars().all())
            self.assertEqual(outbox_count, 1)

    def test_concurrency_with_cancellation_skips_cancelled(self):
        d_pending, _ = self._create_diagnosis(status="PENDIENTE")
        d_cancelled, _ = self._create_diagnosis(status="CANCELADO")
        d_processing, _ = self._create_diagnosis(status="PROCESANDO")

        with self.SessionLocal() as session:
            res = run_backfill(session, apply=True)
            self.assertEqual(res.scanned, 1)  # Only PENDIENTE queried
            self.assertEqual(res.candidates, 1)
            self.assertEqual(res.applied, 1)

        with self.SessionLocal() as session:
            # Only d_pending has outbox
            outbox_pending = session.execute(
                select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == d_pending)
            ).scalar_one_or_none()
            self.assertIsNotNone(outbox_pending)

            outbox_cancelled = session.execute(
                select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == d_cancelled)
            ).scalar_one_or_none()
            self.assertIsNone(outbox_cancelled)

    def test_tombstones_are_included_and_flagged(self):
        now = datetime.now(timezone.utc)
        d_tombstone, _ = self._create_diagnosis(deleted_at=now)

        with self.SessionLocal() as session:
            res = run_backfill(session, apply=True)
            self.assertEqual(res.candidates, 1)
            self.assertEqual(res.tombstones, 1)
            self.assertEqual(res.applied, 1)
            self.assertTrue(res.details[0]["is_tombstone"])

        with self.SessionLocal() as session:
            audit = session.execute(
                select(DiagnosisAuditLog).where(DiagnosisAuditLog.target_id == str(d_tombstone))
            ).scalar_one()
            self.assertTrue(audit.details["is_tombstone"])

    def test_ids_filter_targets_only_specified_subset(self):
        d1, _ = self._create_diagnosis()
        d2, _ = self._create_diagnosis()
        d3, _ = self._create_diagnosis()

        with self.SessionLocal() as session:
            res = run_backfill(session, apply=True, ids=[d1, d3])
            self.assertEqual(res.scanned, 2)
            self.assertEqual(res.applied, 2)

        with self.SessionLocal() as session:
            outbox_d2 = session.execute(
                select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == d2)
            ).scalar_one_or_none()
            self.assertIsNone(outbox_d2)

    def test_simulation_profile_guard_fails_closed_outside_test(self):
        self._create_diagnosis()
        os.environ["ASYNC_SIMULATION_PROFILE"] = "true"
        os.environ["APP_ENV"] = "production"

        try:
            with self.SessionLocal() as session:
                with self.assertRaises(RuntimeError):
                    run_backfill(session, apply=False)
        finally:
            os.environ.pop("ASYNC_SIMULATION_PROFILE", None)
            os.environ["APP_ENV"] = "test"


if __name__ == "__main__":
    unittest.main()

