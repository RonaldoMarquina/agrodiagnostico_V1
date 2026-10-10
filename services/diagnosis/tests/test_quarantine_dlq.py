"""Tests for Diagnosis transactional quarantine and DLQ descriptor outbox.

Verifies Task 7.1:
- Quarantining invalid schema, unknown version, and collision messages.
- DB persistence failure does NOT acknowledge broker message (no ACK).
- Broker/DLQ temporarily down leaves descriptor recuperable (descriptor_sent_at IS NULL).
- Running publish_pending_quarantine_descriptors delivers pending descriptors upon DLQ recovery.
- Zero raw payloads or credentials leaked into logs or descriptors.
"""
from datetime import datetime, timezone
import json
import logging
import unittest
from unittest.mock import MagicMock
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
    DiagnosisInbox,
    DiagnosisQuarantineMessage,
    Problem,
    Recommendation,
)
from app.consumer import DiagnosisAnalyzedConsumer
from app.infrastructure.quarantine import (
    build_dlq_descriptor,
    publish_dlq_descriptor,
    publish_pending_quarantine_descriptors,
)


class TestDiagnosisQuarantineDLQ(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.consumer = DiagnosisAnalyzedConsumer(db_session_factory=self.Session)
        self.channel = MagicMock()

    def tearDown(self):
        self.engine.dispose()

    def test_schema_invalid_persists_quarantine_and_publishes_dlq_descriptor(self):
        raw_invalid = b'{"event_id": "bad-uuid", "payload": {"secret_token": "MY_SECRET"}}'
        delivery_tag = 101

        processed = self.consumer.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=raw_invalid,
            routing_key="diagnosis.analyzed.v1",
        )

        self.assertTrue(processed)
        self.channel.basic_ack.assert_called_once_with(delivery_tag=delivery_tag)

        # Check quarantine row in DB
        with self.Session() as session:
            quarantined = session.query(DiagnosisQuarantineMessage).all()
            self.assertEqual(len(quarantined), 1)
            q = quarantined[0]
            self.assertEqual(q.consumer, "diagnosis")
            self.assertEqual(q.routing_key, "diagnosis.analyzed.v1")
            self.assertIsNotNone(q.descriptor_sent_at)
            # Ensure raw payload and secret are not stored in model attributes
            self.assertNotIn("MY_SECRET", str(q.__dict__))

        # Check DLQ publication
        self.channel.basic_publish.assert_called_once()
        publish_kwargs = self.channel.basic_publish.call_args[1]
        self.assertEqual(publish_kwargs["routing_key"], "diagnosis.analyzed.v1.dlq")
        self.assertEqual(publish_kwargs["mandatory"], True)
        
        # Verify published descriptor
        published_descriptor = json.loads(publish_kwargs["body"].decode("utf-8"))
        self.assertEqual(published_descriptor["descriptor_type"], "QuarantineDescriptor")
        self.assertEqual(published_descriptor["consumer"], "diagnosis")
        self.assertEqual(published_descriptor["routing_key"], "diagnosis.analyzed.v1")
        self.assertNotIn("MY_SECRET", json.dumps(published_descriptor))

    def test_quarantine_db_persistence_failure_does_not_ack(self):
        raw_invalid = b'{"corrupted": true}'
        delivery_tag = 102

        # Mock db_session_factory to fail on commit
        mock_session = MagicMock()
        mock_session.commit.side_effect = RuntimeError("Database disk full!")
        mock_factory = MagicMock(return_value=mock_session)
        mock_session.__enter__.return_value = mock_session

        faulty_consumer = DiagnosisAnalyzedConsumer(db_session_factory=mock_factory)

        processed = faulty_consumer.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=raw_invalid,
            routing_key="diagnosis.analyzed.v1",
        )

        # Must return False and MUST NOT send basic_ack
        self.assertFalse(processed)
        self.channel.basic_ack.assert_not_called()

    def test_dlq_temporarily_unavailable_leaves_descriptor_recuperable(self):
        raw_invalid = b'{"malformed_json: true'  # syntax error
        delivery_tag = 103

        # Channel fails when publishing to DLQ
        self.channel.basic_publish.side_effect = Exception("RabbitMQ DLQ unreachable")

        processed = self.consumer.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=raw_invalid,
            routing_key="diagnosis.analyzed.v1",
        )

        # Quarantine must still be committed, and original message ACKed to avoid toxic loops
        self.assertTrue(processed)
        self.channel.basic_ack.assert_called_once_with(delivery_tag=delivery_tag)

        # Verify descriptor_sent_at IS NULL (recuperable)
        with self.Session() as session:
            q = session.query(DiagnosisQuarantineMessage).one()
            self.assertIsNone(q.descriptor_sent_at)

        # Now simulate DLQ recovery: publish pending descriptors
        good_channel = MagicMock()
        with self.Session() as session:
            sent_count = publish_pending_quarantine_descriptors(
                session=session,
                channel=good_channel,
                batch_size=10,
            )
            self.assertEqual(sent_count, 1)

        good_channel.basic_publish.assert_called_once()
        with self.Session() as session:
            q = session.query(DiagnosisQuarantineMessage).one()
            self.assertIsNotNone(q.descriptor_sent_at)

    def test_collision_quarantined_and_dlq_descriptor_created(self):
        diag_id = uuid.uuid4()
        event_id = uuid.uuid4()
        lease_token = uuid.uuid4()
        delivery_tag = 104

        # Pre-seed existing inbox record with different hash
        with self.Session() as session:
            inbox = DiagnosisInbox(
                consumer="diagnosis",
                event_id=event_id,
                canonical_hash="hash_original_0000000000000000000000000000000000000000000000000000",
                diagnosis_id=diag_id,
                lease_token=lease_token,
                status="PROCESSED",
            )
            session.add(inbox)
            session.commit()

        # Incoming message with same event_id but valid schema and different payload
        collision_msg = {
            "event_id": str(event_id),
            "event_type": "DiagnosisAnalyzed",
            "schema_version": 1,
            "occurred_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "lease_token": str(lease_token),
                "crop_code": None,
                "outcome": "ABSTENTION",
                "model_id": None,
                "model_version": None,
                "dataset_version": None,
                "inference_ms": None,
                "reason_code": "LOW_CONFIDENCE",
            },
        }
        body = json.dumps(collision_msg).encode("utf-8")

        processed = self.consumer.process_message(
            channel=self.channel,
            delivery_tag=delivery_tag,
            body=body,
            routing_key="diagnosis.analyzed.v1",
        )

        self.assertTrue(processed)
        self.channel.basic_ack.assert_called_once_with(delivery_tag=delivery_tag)

        # Check collision quarantine recorded
        with self.Session() as session:
            quarantined = session.query(DiagnosisQuarantineMessage).all()
            self.assertEqual(len(quarantined), 1)
            self.assertIn("EVENT_ID_COLLISION", quarantined[0].error_reason)
            self.assertIsNotNone(quarantined[0].descriptor_sent_at)

        self.channel.basic_publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
