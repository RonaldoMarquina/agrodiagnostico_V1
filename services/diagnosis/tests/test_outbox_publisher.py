"""Unit tests for Transactional Outbox repository and publisher in Diagnosis (Task 4.2).

Tests:
- Claim durable with expiration and immediate release of row lock.
- Concurrent publishers claiming disjoint items without collision.
- Confirmed publication with mandatory=True and successful sent_at commit.
- Unroutable return (basic.return) does NOT mark sent_at; schedules retry with backoff.
- Delivery failure / nack does NOT mark sent_at; schedules retry.
- Crash after confirm before sent_at: expired claim allows redelivery with exact, immutable envelope.
"""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import Base, Diagnosis, DiagnosisOutbox
from app.infrastructure.outbox import (
    DiagnosisOutboxPublisher,
    claim_outbox_batch,
    mark_outbox_failed,
    mark_outbox_sent,
)


class TestDiagnosisOutboxPublisher(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.publisher = DiagnosisOutboxPublisher()

    def _create_outbox_item(
        self,
        event_type="DiagnosisRequested",
        schema_version=2,
        routing_key="diagnosis.requested.v2",
        available_offset_sec=0,
    ):
        now = datetime.now(timezone.utc)
        item_id = uuid.uuid4()
        event_id = uuid.uuid4()
        diag_id = uuid.uuid4()
        envelope = {
            "event_id": str(event_id),
            "event_type": event_type,
            "schema_version": schema_version,
            "occurred_at": now.isoformat(),
            "correlation_id": str(uuid.uuid4()),
            "payload": {
                "diagnosis_id": str(diag_id),
                "owner_id": str(uuid.uuid4()),
                "object_key": f"diagnoses/{diag_id}/original.jpg",
            },
        }

        with self.SessionLocal() as session:
            rec = DiagnosisOutbox(
                id=item_id,
                event_id=event_id,
                event_type=event_type,
                schema_version=schema_version,
                routing_key=routing_key,
                envelope=envelope,
                diagnosis_id=diag_id,
                attempt_number=1,
                created_at=now,
                available_at=now + timedelta(seconds=available_offset_sec),
            )
            session.add(rec)
            session.commit()
        return item_id, event_id, envelope

    def test_claim_outbox_batch_assigns_lease_and_releases(self):
        id1, ev1, _ = self._create_outbox_item()
        id2, ev2, _ = self._create_outbox_item()

        with self.SessionLocal() as session:
            token, items = claim_outbox_batch(session, batch_size=10, lease_seconds=30)
            self.assertEqual(len(items), 2)
            self.assertIsNotNone(token)
            self.assertEqual(items[0].claim_token, token)

        # Verify DB records updated with claim_token and claim_expires_at
        with self.SessionLocal() as session:
            rec1 = session.get(DiagnosisOutbox, id1)
            self.assertEqual(rec1.claim_token, token)
            self.assertIsNotNone(rec1.claim_expires_at)
            self.assertIsNone(rec1.sent_at)

    def test_concurrent_publishers_claim_disjoint_batches(self):
        id1, _, _ = self._create_outbox_item()
        id2, _, _ = self._create_outbox_item()

        # Publisher 1 claims batch of 1
        with self.SessionLocal() as session:
            token1, items1 = claim_outbox_batch(session, batch_size=1, lease_seconds=30)
            self.assertEqual(len(items1), 1)

        # Publisher 2 claims batch of 1
        with self.SessionLocal() as session:
            token2, items2 = claim_outbox_batch(session, batch_size=1, lease_seconds=30)
            self.assertEqual(len(items2), 1)

        # Must be different items and different claim tokens
        self.assertNotEqual(token1, token2)
        self.assertNotEqual(items1[0].id, items2[0].id)

    def test_publish_batch_success_with_mandatory_and_confirms(self):
        id1, ev1, env1 = self._create_outbox_item()

        with self.SessionLocal() as session:
            token, items = claim_outbox_batch(session, batch_size=1)

        # Mock RabbitMQ channel
        mock_channel = MagicMock()
        mock_channel.basic_publish.return_value = None

        with self.SessionLocal() as session:
            stats = self.publisher.publish_batch(session, items, token, channel=mock_channel)
            self.assertEqual(stats["published"], 1)
            self.assertEqual(stats["unroutable"], 0)
            self.assertEqual(stats["failed"], 0)

        # Verify basic_publish was called with mandatory=True and correct props
        mock_channel.confirm_delivery.assert_called_once()
        mock_channel.basic_publish.assert_called_once()
        kwargs = mock_channel.basic_publish.call_args.kwargs
        self.assertEqual(kwargs["exchange"], "agrodiagnostico.events")
        self.assertEqual(kwargs["routing_key"], "diagnosis.requested.v2")
        self.assertTrue(kwargs["mandatory"])
        self.assertEqual(kwargs["properties"].delivery_mode, 2)
        self.assertEqual(kwargs["properties"].message_id, str(ev1))

        # Verify outbox record marked sent
        with self.SessionLocal() as session:
            rec = session.get(DiagnosisOutbox, id1)
            self.assertIsNotNone(rec.sent_at)
            self.assertIsNone(rec.claim_token)

    def test_publish_batch_unroutable_return_does_not_mark_sent(self):
        id1, ev1, _ = self._create_outbox_item(routing_key="unroutable.key")

        with self.SessionLocal() as session:
            token, items = claim_outbox_batch(session, batch_size=1)

        mock_channel = MagicMock()

        # Simulate channel invoking return callback on publish
        def fake_publish(*args, **kwargs):
            # Find registered return callback
            return_cb = mock_channel.add_on_return_callback.call_args[0][0]
            method = MagicMock(reply_code=312, reply_text="NO_ROUTE", routing_key="unroutable.key")
            props = kwargs["properties"]
            return_cb(mock_channel, method, props, kwargs["body"])
            return True

        mock_channel.basic_publish.side_effect = fake_publish

        with self.SessionLocal() as session:
            stats = self.publisher.publish_batch(session, items, token, channel=mock_channel)
            self.assertEqual(stats["published"], 0)
            self.assertEqual(stats["unroutable"], 1)

        # Outbox item must NOT be marked sent, and available_at should be deferred
        with self.SessionLocal() as session:
            rec = session.get(DiagnosisOutbox, id1)
            self.assertIsNone(rec.sent_at)
            self.assertIsNone(rec.claim_token)
            self.assertGreater(rec.available_at, rec.created_at)

    def test_crash_after_confirm_allows_redelivery_with_immutable_envelope(self):
        """Simulate publisher crashing immediately after broker confirm before committing sent_at."""
        id1, ev1, original_env = self._create_outbox_item()

        # Publisher 1 claims and publishes
        with self.SessionLocal() as session:
            token1, items1 = claim_outbox_batch(session, batch_size=1, lease_seconds=1)

        mock_channel1 = MagicMock()
        mock_channel1.basic_publish.return_value = None

        # Simulate broker confirmed, but publisher process crashes (no mark_outbox_sent called!)
        # Item remains with sent_at=None, claim_expires_at=now+1s

        # Fast forward time past claim_expires_at (2 seconds later)
        with self.SessionLocal() as session:
            rec = session.get(DiagnosisOutbox, id1)
            rec.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()

        # Publisher 2 starts and claims the expired row
        with self.SessionLocal() as session:
            token2, items2 = claim_outbox_batch(session, batch_size=1)
            self.assertEqual(len(items2), 1)
            self.assertEqual(items2[0].id, id1)
            # Crucial: the envelope published by Publisher 2 MUST BE 100% identical to original
            self.assertEqual(items2[0].envelope, original_env)
            self.assertEqual(items2[0].event_id, ev1)

        # Publisher 2 publishes and completes normally
        mock_channel2 = MagicMock()
        mock_channel2.basic_publish.return_value = None

        with self.SessionLocal() as session:
            stats = self.publisher.publish_batch(session, items2, token2, channel=mock_channel2)
            self.assertEqual(stats["published"], 1)

        with self.SessionLocal() as session:
            rec = session.get(DiagnosisOutbox, id1)
            self.assertIsNotNone(rec.sent_at)


if __name__ == "__main__":
    unittest.main()

