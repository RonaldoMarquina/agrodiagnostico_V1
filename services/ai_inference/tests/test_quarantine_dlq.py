"""Tests for AI Inference transactional quarantine and DLQ descriptor outbox.

Verifies Task 7.1:
- Quarantining invalid schema, unknown version, and collision messages.
- DB persistence failure does NOT acknowledge broker message (no ACK).
- Broker/DLQ temporarily down leaves descriptor recuperable (descriptor_sent_at IS NULL).
- Running publish_pending_inference_quarantine_descriptors delivers pending descriptors upon DLQ recovery.
- Zero raw payloads or credentials leaked into logs or descriptors.
"""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    InferenceInbox,
    InferenceJob,
    InferenceQuarantineMessage,
)
from app.infrastructure.auth import InternalTokenSigner
from app.infrastructure.quarantine import (
    build_inference_dlq_descriptor,
    publish_inference_dlq_descriptor,
    publish_pending_inference_quarantine_descriptors,
)
from app.worker import InferenceWorker


class TestAIInferenceQuarantineDLQ(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.signer = MagicMock(spec=InternalTokenSigner)
        self.worker = InferenceWorker(
            db_session_factory=self.Session,
            diagnosis_internal_url="http://test-internal",
            token_signer=self.signer,
            http_client=MagicMock(),
        )
        self.channel = MagicMock()

    def tearDown(self):
        self.engine.dispose()

    def test_schema_invalid_persists_quarantine_and_publishes_dlq_descriptor(self):
        raw_invalid = b'{"event_id": "not-a-uuid", "auth_token": "SUPER_SECRET_WORKER_KEY"}'
        delivery_tag = 201

        processed = self.worker.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=raw_invalid,
            routing_key="diagnosis.requested.v2",
        )

        self.assertTrue(processed)
        self.channel.basic_ack.assert_called_once_with(delivery_tag=delivery_tag)

        # Check quarantine row in DB
        with self.Session() as session:
            quarantined = session.query(InferenceQuarantineMessage).all()
            self.assertEqual(len(quarantined), 1)
            q = quarantined[0]
            self.assertEqual(q.consumer, "ai_inference")
            self.assertEqual(q.routing_key, "diagnosis.requested.v2")
            self.assertIsNotNone(q.descriptor_sent_at)
            # Ensure raw payload and secret are not stored in model attributes
            self.assertNotIn("SUPER_SECRET_WORKER_KEY", str(q.__dict__))

        # Check DLQ publication
        self.channel.basic_publish.assert_called_once()
        publish_kwargs = self.channel.basic_publish.call_args[1]
        self.assertEqual(publish_kwargs["routing_key"], "diagnosis.requested.v2.dlq")
        self.assertEqual(publish_kwargs["mandatory"], True)

        published_descriptor = json.loads(publish_kwargs["body"].decode("utf-8"))
        self.assertEqual(published_descriptor["descriptor_type"], "QuarantineDescriptor")
        self.assertEqual(published_descriptor["consumer"], "ai_inference")
        self.assertNotIn("SUPER_SECRET_WORKER_KEY", json.dumps(published_descriptor))

    def test_unknown_version_quarantined_and_dlq_descriptor_created(self):
        raw_unknown = json.dumps({
            "event_id": str(uuid.uuid4()),
            "event_type": "DiagnosisRequested",
            "schema_version": 99,  # Unknown version!
            "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(uuid.uuid4()),
                "owner_id": str(uuid.uuid4()),
                "object_key": f"diagnoses/{uuid.uuid4()}/original.jpg",
            },
        }).encode("utf-8")
        delivery_tag = 202

        processed = self.worker.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=raw_unknown,
            routing_key="diagnosis.requested.v99",
        )

        self.assertTrue(processed)
        self.channel.basic_ack.assert_called_once_with(delivery_tag=delivery_tag)

        with self.Session() as session:
            q = session.query(InferenceQuarantineMessage).one()
            self.assertIn("UNKNOWN_SCHEMA_VERSION", q.error_reason)

    def test_quarantine_db_persistence_failure_does_not_ack(self):
        raw_invalid = b'{"broken_json": true'
        delivery_tag = 203

        # Mock db_session_factory to fail on commit
        mock_session = MagicMock()
        mock_session.commit.side_effect = RuntimeError("Disk IO failure")
        mock_factory = MagicMock(return_value=mock_session)
        mock_session.__enter__.return_value = mock_session

        faulty_worker = InferenceWorker(
            db_session_factory=mock_factory,
            diagnosis_internal_url="http://test-internal",
            token_signer=self.signer,
            http_client=MagicMock(),
        )

        processed = faulty_worker.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=raw_invalid,
            routing_key="diagnosis.requested.v2",
        )

        self.assertFalse(processed)
        self.channel.basic_ack.assert_not_called()

    def test_dlq_temporarily_unavailable_leaves_descriptor_recuperable(self):
        raw_invalid = b'{"corrupted": true}'
        delivery_tag = 204

        self.channel.basic_publish.side_effect = Exception("DLQ Queue full / Broker down")

        processed = self.worker.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=raw_invalid,
            routing_key="diagnosis.requested.v2",
        )

        # Committed in DB and original message ACKed
        self.assertTrue(processed)
        self.channel.basic_ack.assert_called_once_with(delivery_tag=delivery_tag)

        # Descriptor remains with descriptor_sent_at IS NULL
        with self.Session() as session:
            q = session.query(InferenceQuarantineMessage).one()
            self.assertIsNone(q.descriptor_sent_at)

        # Recover DLQ
        good_channel = MagicMock()
        with self.Session() as session:
            sent_count = publish_pending_inference_quarantine_descriptors(
                session=session,
                channel=good_channel,
                batch_size=10,
            )
            self.assertEqual(sent_count, 1)

        good_channel.basic_publish.assert_called_once()
        with self.Session() as session:
            q = session.query(InferenceQuarantineMessage).one()
            self.assertIsNotNone(q.descriptor_sent_at)

    def test_collision_quarantined_and_dlq_descriptor_created(self):
        diag_id = uuid.uuid4()
        event_id = uuid.uuid4()
        delivery_tag = 205

        with self.Session() as session:
            inbox = InferenceInbox(
                consumer="ai_inference",
                event_id=event_id,
                canonical_hash="existing_hash_11111111111111111111111111111111111111111111111111",
                diagnosis_id=diag_id,
                status="PROCESSED",
            )
            session.add(inbox)
            session.commit()

        # Collision message with different content
        collision_msg = {
            "event_id": str(event_id),
            "event_type": "DiagnosisRequested",
            "schema_version": 2,
            "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "owner_id": str(uuid.uuid4()),
                "object_key": f"diagnoses/{diag_id}/original.jpg",
            },
        }
        body = json.dumps(collision_msg).encode("utf-8")

        processed = self.worker.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=body,
            routing_key="diagnosis.requested.v2",
        )

        self.assertTrue(processed)
        self.channel.basic_ack.assert_called_once_with(delivery_tag=delivery_tag)

        with self.Session() as session:
            quarantined = session.query(InferenceQuarantineMessage).all()
            self.assertEqual(len(quarantined), 1)
            self.assertIn("EVENT_ID_COLLISION", quarantined[0].error_reason)
            self.assertIsNotNone(quarantined[0].descriptor_sent_at)

        self.channel.basic_publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
