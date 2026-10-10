"""Comprehensive unit and integration test suite for AI Inference worker consumer.

Covers Tasks 5.1, 5.2, 5.3, and 5.4:
- 5.1: Pre-validation of Requested v1 and v2, quarantine of invalid/unknown schemas,
  inbox deduplication, collision quarantine, zero direct S3/DB access.
- 5.2: Local exclusive claim, HTTP claim, image fetch, uncertain timeout recovery,
  fencing loss (stale lease 409), worker crash recovery.
- 5.3: Deterministic simulator fail-closed guards, synthetic PREDICTION, ABSTENTION,
  and FAILURE fixtures, rejection in non-test envs.
- 5.4: Single atomic DB commit (Result + Inbox + Outbox + Job) before basic_ack,
  crash before commit vs crash after commit before ACK, duplicate generation fencing,
  single-attempt consumption on transient failure without inner loops.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from typing import Any
import unittest
from unittest.mock import MagicMock, patch
import uuid

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    InferenceAuditLog,
    InferenceInbox,
    InferenceJob,
    InferenceOutbox,
    InferenceQuarantineMessage,
    InferenceResult,
)
from app.infrastructure.auth import InternalTokenSigner, generate_worker_keypair
from app.infrastructure.event_validation import (
    compute_canonical_hash,
    validate_diagnosis_analyzed_v1,
)
from app.simulator import (
    SimulatorScenario,
    clear_fixture_scenarios,
    generate_synthetic_abstention,
    run_simulated_inference,
    set_default_fixture_scenario,
    set_diagnosis_fixture,
)
from app.worker import InferenceWorker


class MockAMQPChannel:
    """Mock Pika channel for recording acks and nacks."""

    def __init__(self):
        self.acked_tags = []
        self.nacked_tags = []

    def basic_ack(self, delivery_tag: Any) -> None:
        self.acked_tags.append(delivery_tag)

    def basic_nack(self, delivery_tag: Any, requeue: bool = True) -> None:
        self.nacked_tags.append((delivery_tag, requeue))


class TestInferenceWorker(unittest.TestCase):
    def setUp(self):
        # Database setup: SQLite in-memory with full domain schema
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        # Ed25519 signer setup
        self.priv_pem, self.pub_pem = generate_worker_keypair()
        self.signer = InternalTokenSigner(
            private_key_pem=self.priv_pem,
            kid="test-worker-kid-1",
            instance_id="ai-worker-instance-1",
        )

        # Test environment configuration for simulator
        os.environ["APP_ENV"] = "test"
        os.environ["ENABLE_SIMULATED_INFERENCE"] = "true"
        clear_fixture_scenarios()

        # Mock HTTP client
        self.mock_http = MagicMock(spec=httpx.Client)

        self.worker = InferenceWorker(
            db_session_factory=self.Session,
            diagnosis_internal_url="http://diagnosis.internal",
            token_signer=self.signer,
            http_client=self.mock_http,
            local_lease_seconds=60,
        )

    def tearDown(self):
        clear_fixture_scenarios()
        self.engine.dispose()
        os.environ.pop("APP_ENV", None)
        os.environ.pop("ENABLE_SIMULATED_INFERENCE", None)
        os.environ.pop("SIMULATED_SCENARIO", None)

    def _create_requested_v1_envelope(self, diag_id=None, evt_id=None):
        diag_id = diag_id or uuid.uuid4()
        evt_id = evt_id or uuid.uuid4()
        return {
            "event_id": str(evt_id),
            "event_type": "DiagnosisRequested",
            "schema_version": 1,
            "occurred_at": "2026-10-08T10:00:00Z",
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "owner_id": str(uuid.uuid4()),
                "object_key": f"diagnoses/{uuid.uuid4()}/{uuid.uuid4()}",
            },
        }

    def _create_requested_v2_envelope(self, diag_id=None, evt_id=None):
        diag_id = diag_id or uuid.uuid4()
        evt_id = evt_id or uuid.uuid4()
        return {
            "event_id": str(evt_id),
            "event_type": "DiagnosisRequested",
            "schema_version": 2,
            "occurred_at": "2026-10-08T10:00:00Z",
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "owner_id": str(uuid.uuid4()),
                "object_key": f"diagnoses/{diag_id}/original.jpg",
            },
        }

    # =========================================================================
    # Task 5.1: Pre-validation, Quarantine, Deduplication, and Contract
    # =========================================================================

    def test_consume_requested_v1_valid(self):
        """Requested v1 message is pre-validated, claimed, analyzed, and acknowledged."""
        channel = MockAMQPChannel()
        diag_id = uuid.uuid4()
        evt = self._create_requested_v1_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        lease_token = uuid.uuid4()

        # Mock claim 200 and image 200
        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.return_value = httpx.Response(
            status_code=200,
            content=b"\xff\xd8\xff\xe0fake_jpeg_bytes",
        )

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=1,
            body=raw_body,
            routing_key="diagnosis.requested.v1",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [1])

        # Verify DB state
        with self.Session() as session:
            # Result exists
            result = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(result.lease_token, lease_token)
            self.assertEqual(result.outcome, "PREDICTION")

            # Inbox exists
            inbox = session.execute(select(InferenceInbox).where(InferenceInbox.event_id == uuid.UUID(evt["event_id"]))).scalar_one()
            self.assertEqual(inbox.consumer, "ai_inference")
            self.assertEqual(inbox.canonical_hash, compute_canonical_hash(evt))

            # Outbox exists with valid DiagnosisAnalyzed v1 envelope
            outbox = session.execute(select(InferenceOutbox).where(InferenceOutbox.diagnosis_id == diag_id)).scalar_one()
            val_ok, val_err = validate_diagnosis_analyzed_v1(outbox.envelope)
            self.assertTrue(val_ok, f"Analyzed envelope invalid: {val_err}")

    def test_consume_requested_v2_valid(self):
        """Requested v2 message (original.jpg key) is successfully processed."""
        channel = MockAMQPChannel()
        diag_id = uuid.uuid4()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        lease_token = uuid.uuid4()

        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.return_value = httpx.Response(
            status_code=200,
            content=b"\xff\xd8\xff\xe0fake_jpeg_bytes",
        )

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=2,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [2])

    def test_consume_invalid_schema_quarantined_and_acked(self):
        """Malformed JSON or schema violation is quarantined in DB and ACKed without processing."""
        channel = MockAMQPChannel()
        bad_payload = b"not-a-valid-json-string"

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=10,
            body=bad_payload,
            routing_key="diagnosis.requested.v1",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [10])

        with self.Session() as session:
            q = session.execute(select(InferenceQuarantineMessage)).scalar_one()
            self.assertEqual(q.consumer, "ai_inference")
            self.assertIn("MALFORMED_JSON", q.error_reason)

    def test_consume_unknown_version_quarantined_and_acked(self):
        """Schema version 3 is rejected, quarantined, and ACKed."""
        channel = MockAMQPChannel()
        evt = self._create_requested_v1_envelope()
        evt["schema_version"] = 3
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=11,
            body=raw_body,
            routing_key="diagnosis.requested.v1",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [11])

        with self.Session() as session:
            q = session.execute(select(InferenceQuarantineMessage)).scalar_one()
            self.assertIn("UNKNOWN_SCHEMA_VERSION", q.error_reason)

    def test_repeated_event_id_same_content_idempotent_dedupe(self):
        """Redelivery with matching event_id and canonical hash is immediately ACKed without HTTP claim."""
        channel = MockAMQPChannel()
        diag_id = uuid.uuid4()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        canonical_hash = compute_canonical_hash(evt)

        # Pre-insert inbox record to simulate prior completed processing
        with self.Session() as session:
            inbox = InferenceInbox(
                consumer="ai_inference",
                event_id=uuid.UUID(evt["event_id"]),
                canonical_hash=canonical_hash,
                diagnosis_id=diag_id,
                status="PROCESSED",
            )
            session.add(inbox)
            session.commit()

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=20,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [20])
        # HTTP client was NEVER called
        self.mock_http.post.assert_not_called()

    def test_repeated_event_id_different_content_collision_quarantined(self):
        """Event ID collision with different payload is quarantined, audited, and ACKed without overwriting inbox."""
        channel = MockAMQPChannel()
        diag_id = uuid.uuid4()
        evt1 = self._create_requested_v2_envelope(diag_id=diag_id)
        canonical_hash1 = compute_canonical_hash(evt1)

        # Pre-insert existing inbox record with original hash
        with self.Session() as session:
            inbox = InferenceInbox(
                consumer="ai_inference",
                event_id=uuid.UUID(evt1["event_id"]),
                canonical_hash=canonical_hash1,
                diagnosis_id=diag_id,
                status="PROCESSED",
            )
            session.add(inbox)
            session.commit()

        # Tampered envelope with same event_id but different correlation_id
        evt2 = dict(evt1)
        evt2["correlation_id"] = str(uuid.uuid4())
        raw_body2 = json.dumps(evt2).encode("utf-8")

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=21,
            body=raw_body2,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [21])

        with self.Session() as session:
            # Original inbox preserved
            inbox_rec = session.execute(select(InferenceInbox).where(InferenceInbox.event_id == uuid.UUID(evt1["event_id"]))).scalar_one()
            self.assertEqual(inbox_rec.canonical_hash, canonical_hash1)

            # Quarantine entry recorded
            q = session.execute(select(InferenceQuarantineMessage)).scalar_one()
            self.assertIn("COLLISION", q.error_reason)

            # Audit log entry recorded
            audit = session.execute(select(InferenceAuditLog).where(InferenceAuditLog.action == "COLLISION_QUARANTINED")).scalar_one()
            self.assertIsNotNone(audit)

    # =========================================================================
    # Task 5.2: Local Exclusive Claim, HTTP Claim, Image Fetch, and Fencing
    # =========================================================================

    def test_local_exclusive_claim_exclusion_between_two_workers(self):
        """If worker 1 is actively claiming/processing a diagnosis, worker 2 rejects concurrent execution with requeue."""
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Pre-seed InferenceJob with active local lease
        with self.Session() as session:
            job = InferenceJob(
                diagnosis_id=diag_id,
                status="CLAIMING",
                local_claim_token=uuid.uuid4(),
                local_claim_expires_at=now + timedelta(seconds=45),
            )
            session.add(job)
            session.commit()

        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=30,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertFalse(res)
        self.assertEqual(channel.nacked_tags, [(30, True)])  # requeued for later

    def test_worker_dies_before_claim_recovery_after_expiry(self):
        """If previous worker died and its local lease expired, new worker takes over local claim and proceeds."""
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Pre-seed InferenceJob with EXPIRED local lease
        with self.Session() as session:
            job = InferenceJob(
                diagnosis_id=diag_id,
                status="CLAIMING",
                local_claim_token=uuid.uuid4(),
                local_claim_expires_at=now - timedelta(seconds=10),
            )
            session.add(job)
            session.commit()

        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        lease_token = uuid.uuid4()

        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.return_value = httpx.Response(
            status_code=200,
            content=b"\xff\xd8\xff\xe0fake_jpeg_bytes",
        )

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=31,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [31])

        with self.Session() as session:
            job_rec = session.execute(select(InferenceJob).where(InferenceJob.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(job_rec.status, "COMPLETED")

    def test_completed_local_result_does_not_discard_new_generation(self):
        diagnosis_id = uuid.uuid4()
        set_default_fixture_scenario(SimulatorScenario.ABSTENTION)
        self.mock_http.get.return_value = httpx.Response(200, content=b"fixture")
        for generation in range(2):
            self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(uuid.uuid4())})
            event = self._create_requested_v2_envelope(diag_id=diagnosis_id)
            self.assertTrue(self.worker.process_message(MockAMQPChannel(), generation, json.dumps(event).encode(), "diagnosis.requested.v2"))
        with self.Session() as session:
            self.assertEqual(len(session.scalars(select(InferenceResult)).all()), 2)
            self.assertEqual(len(session.scalars(select(InferenceOutbox)).all()), 2)

    def test_local_token_takeover_prevents_stale_result_commit(self):
        event = self._create_requested_v2_envelope()
        self.mock_http.post.return_value = httpx.Response(200, json={"lease_token": str(uuid.uuid4())})
        self.mock_http.get.return_value = httpx.Response(200, content=b"fixture")
        def takeover(**kwargs):
            with self.Session() as session:
                job = session.scalar(select(InferenceJob))
                job.local_claim_token = uuid.uuid4()
                session.commit()
            return generate_synthetic_abstention()
        channel = MockAMQPChannel()
        with patch("app.worker.run_simulated_inference", side_effect=takeover):
            self.assertFalse(self.worker.process_message(channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2"))
        self.assertEqual(channel.acked_tags, [])
        with self.Session() as session:
            self.assertEqual(session.scalars(select(InferenceResult)).all(), [])

    def test_invalid_heartbeat_configuration_fails_closed(self):
        for interval in (0, 60, 61):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                InferenceWorker(self.Session, "http://diagnosis", self.signer, heartbeat_seconds=interval)

    def test_local_environment_cannot_execute_simulator(self):
        with patch.dict(os.environ, {"APP_ENV": "local", "ENABLE_SIMULATED_INFERENCE": "true"}):
            with self.assertRaises(RuntimeError):
                run_simulated_inference(uuid.uuid4(), b"fixture")

    def test_worker_claim_conflict_409_permanently_unclaimable(self):
        """409 DIAGNOSIS_NOT_CLAIMABLE (cancelled or terminal) marks job DISCARDED and ACKs message."""
        diag_id = uuid.uuid4()
        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")

        self.mock_http.post.return_value = httpx.Response(
            status_code=409,
            json={"code": "DIAGNOSIS_NOT_CLAIMABLE", "message": "Recurso cancelado o terminal.", "details": [{"field": "status", "code": "TERMINAL"}]},
        )

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=32,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [32])

        with self.Session() as session:
            job_rec = session.execute(select(InferenceJob).where(InferenceJob.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(job_rec.status, "DISCARDED")

    def test_transient_claim_responses_retain_delivery(self):
        for code in (409, 500, 503):
            with self.subTest(code=code):
                channel = MockAMQPChannel()
                self.mock_http.post.return_value = httpx.Response(code, json={"code": "DIAGNOSIS_NOT_CLAIMABLE"})
                event = self._create_requested_v2_envelope(diag_id=uuid.uuid4())
                self.assertFalse(self.worker.process_message(channel, 1, json.dumps(event).encode(), "diagnosis.requested.v2"))
                self.assertEqual(channel.acked_tags, [])
                self.assertEqual(channel.nacked_tags, [(1, True)])

    def test_uncertain_claim_timeout_fails_closed_no_blind_retry(self):
        """Network timeout during HTTP claim marks job FAILED without inner retry loop, retaining the delivery for later recovery."""
        diag_id = uuid.uuid4()
        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")

        self.mock_http.post.side_effect = httpx.ReadTimeout("Timeout connecting to Diagnosis internal API")

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=33,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertFalse(res)
        self.assertEqual(channel.nacked_tags, [(33, True)])

        with self.Session() as session:
            job_rec = session.execute(select(InferenceJob).where(InferenceJob.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(job_rec.status, "FAILED")
            audit = session.execute(select(InferenceAuditLog).where(InferenceAuditLog.action == "CLAIM_TIMEOUT_UNCERTAIN")).scalar_one()
            self.assertIsNotNone(audit)

    def test_image_fetch_stale_lease_409_aborts_processing(self):
        """If image fetch returns 409 STALE_LEASE, processing aborts immediately and no result is published."""
        diag_id = uuid.uuid4()
        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        lease_token = uuid.uuid4()

        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.return_value = httpx.Response(
            status_code=409,
            json={"detail": {"code": "STALE_LEASE", "message": "Lease expired."}},
        )

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=34,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertFalse(res)
        self.assertEqual(channel.acked_tags, [])
        self.assertEqual(channel.nacked_tags, [(34, True)])

        with self.Session() as session:
            job_rec = session.execute(select(InferenceJob).where(InferenceJob.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(job_rec.status, "FAILED")
            results = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).all()
            self.assertEqual(len(results), 0)
            outbox = session.execute(select(InferenceOutbox).where(InferenceOutbox.diagnosis_id == diag_id)).all()
            self.assertEqual(len(outbox), 0)

    # =========================================================================
    # Task 5.3: Deterministic Simulator & Strict Fail-Closed Guards
    # =========================================================================

    def test_simulator_fails_closed_when_app_env_not_test(self):
        """Simulator strictly refuses to run when APP_ENV is not 'test'."""
        os.environ["APP_ENV"] = "production"
        os.environ["ENABLE_SIMULATED_INFERENCE"] = "true"

        with self.assertRaises(RuntimeError) as ctx:
            run_simulated_inference(diagnosis_id=uuid.uuid4(), image_bytes=b"dummy")
        self.assertIn("Simulated inference is strictly prohibited", str(ctx.exception))

    def test_simulator_fails_closed_when_flag_not_true(self):
        """Simulator strictly refuses to run when ENABLE_SIMULATED_INFERENCE is not 'true'."""
        os.environ["APP_ENV"] = "test"
        os.environ["ENABLE_SIMULATED_INFERENCE"] = "false"

        with self.assertRaises(RuntimeError) as ctx:
            run_simulated_inference(diagnosis_id=uuid.uuid4(), image_bytes=b"dummy")
        self.assertIn("Simulated inference is strictly prohibited", str(ctx.exception))

    def test_simulator_deterministic_scenarios(self):
        """Verifies deterministic generation of PREDICTION, ABSTENTION, and FAILURE fixtures."""
        diag_id = uuid.uuid4()

        # 1. Prediction
        set_default_fixture_scenario(SimulatorScenario.PREDICTION)
        pred = run_simulated_inference(diag_id, b"fake_bytes")
        self.assertEqual(pred["outcome"], "PREDICTION")
        self.assertEqual(pred["crop_code"], "POTATO")
        self.assertEqual(pred["class_code"], "POTATO_EARLY_BLIGHT")
        self.assertIsNotNone(pred["raw_score"])
        self.assertIsNotNone(pred["model_id"])

        # 2. Abstention
        set_default_fixture_scenario(SimulatorScenario.ABSTENTION)
        absten = run_simulated_inference(diag_id, b"fake_bytes")
        self.assertEqual(absten["outcome"], "ABSTENTION")
        self.assertIsNone(absten["model_id"])
        self.assertIsNone(absten["model_version"])
        self.assertIsNone(absten["inference_ms"])
        self.assertEqual(absten["reason_code"], "LOW_CONFIDENCE")

        # 3. Failure
        set_default_fixture_scenario(SimulatorScenario.FAILURE)
        fail = run_simulated_inference(diag_id, b"fake_bytes")
        self.assertEqual(fail["outcome"], "FAILURE")
        self.assertIsNone(fail["model_id"])
        self.assertEqual(fail["reason_code"], "INFERENCE_ERROR")

    def test_simulator_explicit_per_diagnosis_fixture(self):
        """Per-diagnosis fixture overrides default scenario."""
        diag_id = uuid.uuid4()
        custom_fixture = generate_synthetic_abstention(reason_code="BAD_IMAGE")
        set_diagnosis_fixture(diag_id, custom_fixture)

        res = run_simulated_inference(diag_id, b"fake_bytes")
        self.assertEqual(res["outcome"], "ABSTENTION")
        self.assertEqual(res["reason_code"], "BAD_IMAGE")

    # =========================================================================
    # Task 5.4: Atomic Commit, Crash Recovery, and Single Attempt Budget
    # =========================================================================

    def test_atomic_commit_abstention_scenario(self):
        """Simulated abstention correctly emits outbox DiagnosisAnalyzed with null model metadata."""
        diag_id = uuid.uuid4()
        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        lease_token = uuid.uuid4()

        set_default_fixture_scenario(SimulatorScenario.ABSTENTION)

        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.return_value = httpx.Response(
            status_code=200,
            content=b"\xff\xd8\xff\xe0fake_jpeg_bytes",
        )

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=40,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [40])

        with self.Session() as session:
            outbox = session.execute(select(InferenceOutbox).where(InferenceOutbox.diagnosis_id == diag_id)).scalar_one()
            payload = outbox.envelope["payload"]
            self.assertEqual(payload["outcome"], "ABSTENTION")
            self.assertIsNone(payload["model_id"])
            self.assertIsNone(payload["model_version"])
            self.assertEqual(payload["reason_code"], "LOW_CONFIDENCE")

            # Contract validation
            val_ok, val_err = validate_diagnosis_analyzed_v1(outbox.envelope)
            self.assertTrue(val_ok, f"Contract validation failed: {val_err}")

    def test_crash_after_commit_before_ack_safely_deduplicates_on_redelivery(self):
        """Worker commits to DB then crashes before broker ACK. Redelivery triggers inbox deduplication and ACKs."""
        diag_id = uuid.uuid4()
        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        lease_token = uuid.uuid4()

        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.return_value = httpx.Response(
            status_code=200,
            content=b"\xff\xd8\xff\xe0fake_jpeg_bytes",
        )

        # First run: worker processes message successfully
        res = self.worker.process_message(
            channel=channel,
            delivery_tag=50,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [50])

        # Second run: simulated broker redelivers message (e.g. channel crashed before ACK acknowledged by RabbitMQ)
        channel2 = MockAMQPChannel()
        self.mock_http.post.reset_mock()
        self.mock_http.get.reset_mock()

        res2 = self.worker.process_message(
            channel=channel2,
            delivery_tag=51,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertTrue(res2)
        self.assertEqual(channel2.acked_tags, [51])
        # HTTP endpoints were NOT called again!
        self.mock_http.post.assert_not_called()
        self.mock_http.get.assert_not_called()

        with self.Session() as session:
            # Result exists exactly once
            results = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).all()
            self.assertEqual(len(results), 1)
            # Outbox exists exactly once
            outbox = session.execute(select(InferenceOutbox).where(InferenceOutbox.diagnosis_id == diag_id)).all()
            self.assertEqual(len(outbox), 1)

    def test_transient_failure_consumes_one_attempt_no_inner_loop(self):
        """Transient error during image fetch consumes exactly 1 attempt; worker does not run an inner retry loop."""
        diag_id = uuid.uuid4()
        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        lease_token = uuid.uuid4()

        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.side_effect = httpx.ConnectError("Failed to connect to image endpoint")

        res = self.worker.process_message(
            channel=channel,
            delivery_tag=60,
            body=raw_body,
            routing_key="diagnosis.requested.v2",
        )
        self.assertFalse(res)
        self.assertEqual(channel.acked_tags, [])
        self.assertEqual(channel.nacked_tags, [(60, True)])
        # HTTP get was called exactly ONCE, no retry loops
        self.assertEqual(self.mock_http.get.call_count, 1)

        with self.Session() as session:
            job_rec = session.execute(select(InferenceJob).where(InferenceJob.diagnosis_id == diag_id)).scalar_one()
            self.assertEqual(job_rec.status, "FAILED")

    def test_zero_direct_access_to_s3_or_foreign_tables(self):
        """Worker has zero imports or connections to Diagnosis DB or S3."""
        # 1. Inspect domain models: only ai_inference private tables exist
        table_names = set(Base.metadata.tables.keys())
        for tbl in table_names:
            self.assertTrue(
                tbl.startswith("inference_"),
                f"Unauthorized foreign table found in AI Inference domain: {tbl}",
            )

        # 2. Inspect worker attributes: no S3 client or credentials
        self.assertFalse(hasattr(self.worker, "s3_client"))
        self.assertFalse(hasattr(self.worker, "s3_bucket"))

        # 3. Execution exclusively queries Diagnosis via HTTP with internal JWT & lease header
        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        raw_body = json.dumps(evt).encode("utf-8")
        channel = MockAMQPChannel()

        self.mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"lease_owner": "ai-worker-instance-1", "lease_token": str(lease_token), "expires_at": "2026-10-08T10:01:00Z"},
        )
        self.mock_http.get.return_value = httpx.Response(
            status_code=200,
            content=b"\xff\xd8\xff\xe0fake_jpeg_bytes",
        )

        self.worker.process_message(channel, 70, raw_body, "diagnosis.requested.v2")

        # Verify HTTP calls
        self.mock_http.get.assert_called_once()
        call_headers = self.mock_http.get.call_args.kwargs["headers"]
        self.assertIn("Authorization", call_headers)
        self.assertTrue(call_headers["Authorization"].startswith("Bearer "))
        self.assertEqual(call_headers["X-Lease-Token"], str(lease_token))

    def test_two_event_ids_for_same_generation_unique_constraint(self):
        """Database constraint uq_inference_results_diagnosis_lease prevents duplicate results for same lease."""
        from sqlalchemy.exc import IntegrityError

        diag_id = uuid.uuid4()
        lease_token = uuid.uuid4()

        with self.Session() as session:
            r1 = InferenceResult(
                diagnosis_id=diag_id,
                lease_token=lease_token,
                outcome="PREDICTION",
                crop_code="POTATO",
                class_code="POTATO_EARLY_BLIGHT",
                raw_score=0.9,
            )
            session.add(r1)
            session.commit()

        with self.Session() as session:
            r2 = InferenceResult(
                diagnosis_id=diag_id,
                lease_token=lease_token,
                outcome="PREDICTION",
                crop_code="POTATO",
                class_code="POTATO_EARLY_BLIGHT",
                raw_score=0.85,
            )
            session.add(r2)
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_simulator_rejects_empty_image_bytes(self):
        """Empty image bytes returns failure outcome with IMAGE_UNAVAILABLE."""
        res = run_simulated_inference(uuid.uuid4(), b"")
        self.assertEqual(res["outcome"], "FAILURE")
        self.assertEqual(res["reason_code"], "IMAGE_UNAVAILABLE")

    def test_simulator_cannot_be_selected_via_tampered_payload(self):
        """Simulator cannot be tampered with via payload: extra properties fail schema validation and quarantine."""
        diag_id = uuid.uuid4()
        channel = MockAMQPChannel()
        evt = self._create_requested_v2_envelope(diag_id=diag_id)
        # Attempt to tamper with scenario in payload; violates additionalProperties: false
        evt["payload"]["scenario"] = "FAILURE"
        raw_body = json.dumps(evt).encode("utf-8")

        res = self.worker.process_message(channel, 80, raw_body, "diagnosis.requested.v2")
        self.assertTrue(res)
        self.assertEqual(channel.acked_tags, [80])

        with self.Session() as session:
            # Quarantined due to schema violation
            q = session.execute(select(InferenceQuarantineMessage)).scalar_one()
            self.assertIn("SCHEMA_VALIDATION_FAILED", q.error_reason)
            # No result was inserted
            results = session.execute(select(InferenceResult).where(InferenceResult.diagnosis_id == diag_id)).all()
            self.assertEqual(len(results), 0)
