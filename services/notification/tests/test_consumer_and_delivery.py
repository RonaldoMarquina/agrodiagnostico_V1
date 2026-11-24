"""Unit tests for DiagnosisFinished consumer, DLQ quarantine, internal client, and email delivery (Task 5.2)."""
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import MagicMock
import uuid

import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.consumer import CONSUMER_NAME, DiagnosisFinishedConsumer
from app.domain.models import (
    Base,
    Notification,
    NotificationDeliveryAttempt,
    NotificationDlqOutbox,
    NotificationInbox,
    NotificationPreference,
    NotificationQuarantineMessage,
)
from app.infrastructure.email import (
    InMemoryEmailDeliveryAdapter,
    LoggingEmailDeliveryAdapter,
    mask_email,
)
from app.infrastructure.internal_client import (
    ContactLookupResult,
    ContactLookupTransientError,
    INTERNAL_AUDIENCE,
    INTERNAL_ISSUER,
    INTERNAL_PRINCIPAL,
    InternalTokenSigner,
)
from app.infrastructure.quarantine import EXCHANGE_NAME, publish_pending_dlq_outbox
from app.infrastructure.tokens import generate_ed25519_keypair


def _make_finished_event(
    owner_id: uuid.UUID,
    diagnosis_id: uuid.UUID = None,
    final_status: str = "COMPLETADO",
    event_id: uuid.UUID = None,
    schema_version: int = 1,
) -> dict:
    return {
        "event_id": str(event_id or uuid.uuid4()),
        "event_type": "DiagnosisFinished",
        "schema_version": schema_version,
        "occurred_at": "2026-11-23T19:00:00Z",
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "diagnosis_id": str(diagnosis_id or uuid.uuid4()),
            "owner_id": str(owner_id),
            "final_status": final_status,
        },
    }


class _StubContactClient:
    def __init__(self, result: ContactLookupResult = None, error: Exception = None):
        self.result = result
        self.error = error
        self.calls = 0

    def get_user_contact(self, user_id: uuid.UUID, correlation_id: uuid.UUID) -> ContactLookupResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class TestConsumerAndDelivery(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, expire_on_commit=False, bind=self.engine
        )
        self.owner_id = uuid.uuid4()
        self.channel = MagicMock()
        self.contact_client = _StubContactClient(
            result=ContactLookupResult(found=True, active=True, email="agricultor@example.test")
        )
        self.email_adapter = InMemoryEmailDeliveryAdapter()
        self.consumer = DiagnosisFinishedConsumer(
            db_session_factory=self.SessionLocal,
            contact_client=self.contact_client,
            email_adapter=self.email_adapter,
            retry_backoff_seconds=(1, 2, 3),
        )

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_valid_finished_event_creates_notification_and_acks_after_commit(self):
        for status_val in ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO"):
            ev = _make_finished_event(self.owner_id, final_status=status_val)
            body = json.dumps(ev).encode("utf-8")
            ok = self.consumer.process_message(self.channel, 10, body, "diagnosis.finished.v1")
            self.assertTrue(ok)

        self.assertEqual(self.channel.basic_ack.call_count, 3)
        with self.SessionLocal() as db:
            notifs = db.execute(select(Notification)).scalars().all()
            self.assertEqual(len(notifs), 3)
            self.assertEqual({n.final_status for n in notifs}, {"COMPLETADO", "NO_CONCLUYENTE", "FALLIDO"})
            # email_enabled defaults to False -> zero attempts, Identity not called
            attempts = db.execute(select(NotificationDeliveryAttempt)).scalars().all()
            self.assertEqual(len(attempts), 0)
        self.assertEqual(self.contact_client.calls, 0)
        self.assertEqual(len(self.email_adapter.sent), 0)

    def test_duplicate_event_id_and_duplicate_diagnosis_id_are_idempotent(self):
        diag_id = uuid.uuid4()
        event_id = uuid.uuid4()
        ev = _make_finished_event(self.owner_id, diagnosis_id=diag_id, event_id=event_id)
        body = json.dumps(ev).encode("utf-8")

        # Enable email to prove duplicate delivery never duplicates email attempts either
        with self.SessionLocal() as db:
            db.add(NotificationPreference(owner_id=self.owner_id, email_enabled=True))
            db.commit()

        self.assertTrue(self.consumer.process_message(self.channel, 1, body, "diagnosis.finished.v1"))
        # Exact redelivery with same event_id
        self.assertTrue(self.consumer.process_message(self.channel, 2, body, "diagnosis.finished.v1"))
        # Second event with new event_id for the same diagnosis_id
        ev2 = _make_finished_event(self.owner_id, diagnosis_id=diag_id, final_status="COMPLETADO")
        self.assertTrue(
            self.consumer.process_message(
                self.channel, 3, json.dumps(ev2).encode("utf-8"), "diagnosis.finished.v1"
            )
        )

        self.assertEqual(self.channel.basic_ack.call_count, 3)
        with self.SessionLocal() as db:
            self.assertEqual(len(db.execute(select(Notification)).scalars().all()), 1)
            self.assertEqual(len(db.execute(select(NotificationDeliveryAttempt)).scalars().all()), 1)
        self.assertEqual(len(self.email_adapter.sent), 1)

    def test_event_id_collision_is_quarantined_and_published_to_dlq(self):
        event_id = uuid.uuid4()
        ev1 = _make_finished_event(self.owner_id, final_status="COMPLETADO", event_id=event_id)
        ev2 = _make_finished_event(self.owner_id, final_status="FALLIDO", event_id=event_id)

        self.assertTrue(
            self.consumer.process_message(self.channel, 1, json.dumps(ev1).encode("utf-8"), "diagnosis.finished.v1")
        )
        self.assertTrue(
            self.consumer.process_message(self.channel, 2, json.dumps(ev2).encode("utf-8"), "diagnosis.finished.v1")
        )

        with self.SessionLocal() as db:
            notifs = db.execute(select(Notification)).scalars().all()
            self.assertEqual(len(notifs), 1)
            self.assertEqual(notifs[0].final_status, "COMPLETADO")

            quarantined = db.execute(select(NotificationQuarantineMessage)).scalars().all()
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].reason_code, "EVENT_ID_COLLISION")

            outbox = db.execute(select(NotificationDlqOutbox)).scalars().all()
            self.assertEqual(len(outbox), 1)
            self.assertEqual(outbox[0].routing_key, "diagnosis.finished.v1.dlq")
            self.assertIsNotNone(outbox[0].sent_at)

        self.channel.basic_publish.assert_called_once()
        pub_kwargs = self.channel.basic_publish.call_args.kwargs
        self.assertEqual(pub_kwargs["exchange"], EXCHANGE_NAME)
        self.assertEqual(pub_kwargs["routing_key"], "diagnosis.finished.v1.dlq")
        self.assertTrue(pub_kwargs["mandatory"])

    def test_invalid_payloads_unknown_version_and_cancelado_are_quarantined(self):
        invalid_messages = [
            b"{not-valid-json",
            json.dumps(_make_finished_event(self.owner_id, schema_version=2)).encode("utf-8"),
            json.dumps(_make_finished_event(self.owner_id, final_status="CANCELADO")).encode("utf-8"),
        ]
        for idx, raw in enumerate(invalid_messages, start=1):
            self.assertTrue(self.consumer.process_message(self.channel, idx, raw, "diagnosis.finished.v1"))

        with self.SessionLocal() as db:
            self.assertEqual(len(db.execute(select(Notification)).scalars().all()), 0)
            q_rows = db.execute(select(NotificationQuarantineMessage)).scalars().all()
            self.assertEqual(len(q_rows), 3)
            self.assertEqual(
                {q.reason_code for q in q_rows},
                {"MALFORMED_JSON", "UNSUPPORTED_SCHEMA_VERSION", "SCHEMA_VALIDATION_FAILED"},
            )

    def test_quarantine_db_failure_does_not_ack_message(self):
        def broken_factory():
            raise RuntimeError("db unavailable")

        broken_consumer = DiagnosisFinishedConsumer(
            db_session_factory=broken_factory,
            contact_client=self.contact_client,
            email_adapter=self.email_adapter,
        )
        ok = broken_consumer.process_message(self.channel, 99, b"corrupt", "diagnosis.finished.v1")
        self.assertFalse(ok)
        self.channel.basic_ack.assert_not_called()

    def test_email_failure_preserves_notification_and_retries_until_success_or_permanent(self):
        with self.SessionLocal() as db:
            db.add(NotificationPreference(owner_id=self.owner_id, email_enabled=True))
            db.commit()

        # Case 1: fails once, then succeeds on retry
        flaky_adapter = InMemoryEmailDeliveryAdapter(fail_times=1)
        flaky_consumer = DiagnosisFinishedConsumer(
            db_session_factory=self.SessionLocal,
            contact_client=self.contact_client,
            email_adapter=flaky_adapter,
            retry_backoff_seconds=(0, 0, 0),
        )
        ev1 = _make_finished_event(self.owner_id, final_status="COMPLETADO")
        self.assertTrue(
            flaky_consumer.process_message(self.channel, 1, json.dumps(ev1).encode("utf-8"), "diagnosis.finished.v1")
        )

        # Notification is preserved and ACKed despite email failure
        self.channel.basic_ack.assert_called_once_with(delivery_tag=1)
        with self.SessionLocal() as db:
            notif = db.execute(select(Notification)).scalar_one()
            self.assertEqual(notif.final_status, "COMPLETADO")
            att = db.execute(select(NotificationDeliveryAttempt)).scalar_one()
            self.assertEqual(att.status, "FAILED_RETRYABLE")
            self.assertEqual(att.attempt_count, 1)
            self.assertEqual(att.last_error_code, "EMAIL_PROVIDER_UNAVAILABLE")

        # Second sweep succeeds
        stats = flaky_consumer.process_pending_deliveries()
        self.assertEqual(stats["sent"], 1)
        self.assertEqual(len(flaky_adapter.sent), 1)
        with self.SessionLocal() as db:
            att = db.execute(select(NotificationDeliveryAttempt)).scalar_one()
            self.assertEqual(att.status, "SENT")
            self.assertEqual(att.attempt_count, 2)
            self.assertIsNotNone(att.sent_at)

        # Case 2: permanent failure after 3 attempts
        broken_adapter = InMemoryEmailDeliveryAdapter(always_fail=True)
        broken_consumer = DiagnosisFinishedConsumer(
            db_session_factory=self.SessionLocal,
            contact_client=self.contact_client,
            email_adapter=broken_adapter,
            retry_backoff_seconds=(0, 0, 0),
        )
        ev2 = _make_finished_event(self.owner_id, final_status="NO_CONCLUYENTE")
        self.assertTrue(
            broken_consumer.process_message(self.channel, 2, json.dumps(ev2).encode("utf-8"), "diagnosis.finished.v1")
        )
        broken_consumer.process_pending_deliveries()
        broken_consumer.process_pending_deliveries()
        # Extra sweep does not exceed max_attempts
        broken_consumer.process_pending_deliveries()

        with self.SessionLocal() as db:
            att2 = db.execute(
                select(NotificationDeliveryAttempt).order_by(NotificationDeliveryAttempt.created_at.desc())
            ).scalars().first()
            self.assertEqual(att2.status, "FAILED_PERMANENT")
            self.assertEqual(att2.attempt_count, 3)
            self.assertIsNone(att2.next_attempt_at)

    def test_inactive_user_marks_skipped_and_transient_identity_error_retries(self):
        with self.SessionLocal() as db:
            db.add(NotificationPreference(owner_id=self.owner_id, email_enabled=True))
            db.commit()

        # Inactive user -> SKIPPED immediately without retrying
        inactive_client = _StubContactClient(
            result=ContactLookupResult(found=True, active=False, email="blocked@example.test")
        )
        c_inactive = DiagnosisFinishedConsumer(
            db_session_factory=self.SessionLocal,
            contact_client=inactive_client,
            email_adapter=self.email_adapter,
        )
        ev1 = _make_finished_event(self.owner_id)
        self.assertTrue(
            c_inactive.process_message(self.channel, 1, json.dumps(ev1).encode("utf-8"), "diagnosis.finished.v1")
        )
        with self.SessionLocal() as db:
            att = db.execute(select(NotificationDeliveryAttempt)).scalar_one()
            self.assertEqual(att.status, "SKIPPED")
            self.assertEqual(att.last_error_code, "ACCOUNT_INACTIVE_OR_MISSING")
        self.assertEqual(len(self.email_adapter.sent), 0)

        # Transient Identity 503 -> FAILED_RETRYABLE
        down_client = _StubContactClient(error=ContactLookupTransientError("IDENTITY_HTTP_503"))
        c_down = DiagnosisFinishedConsumer(
            db_session_factory=self.SessionLocal,
            contact_client=down_client,
            email_adapter=self.email_adapter,
            retry_backoff_seconds=(5,),
        )
        ev2 = _make_finished_event(self.owner_id)
        self.assertTrue(
            c_down.process_message(self.channel, 2, json.dumps(ev2).encode("utf-8"), "diagnosis.finished.v1")
        )
        with self.SessionLocal() as db:
            att2 = db.execute(
                select(NotificationDeliveryAttempt).order_by(NotificationDeliveryAttempt.created_at.desc())
            ).scalars().first()
            self.assertEqual(att2.status, "FAILED_RETRYABLE")
            self.assertEqual(att2.last_error_code, "IDENTITY_HTTP_503")

    def test_dlq_outbox_retains_unsent_descriptor_when_broker_publish_fails(self):
        failing_channel = MagicMock()
        failing_channel.basic_publish.side_effect = RuntimeError("broker down")

        ev_bad = _make_finished_event(self.owner_id, schema_version=99)
        self.assertTrue(
            self.consumer.process_message(
                self.channel,
                1,
                json.dumps(ev_bad).encode("utf-8"),
                "diagnosis.finished.v1",
                publish_channel=failing_channel,
            )
        )
        with self.SessionLocal() as db:
            row = db.execute(select(NotificationDlqOutbox)).scalar_one()
            self.assertIsNone(row.sent_at)
            self.assertEqual(row.attempt_count, 1)
            # Move available_at to past and publish on recovered channel
            row.available_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            db.commit()

            recovered = MagicMock()
            published = publish_pending_dlq_outbox(db, recovered)
            self.assertEqual(published, 1)
            db.refresh(row)
            self.assertIsNotNone(row.sent_at)

    def test_internal_token_signer_and_logging_adapter_masking(self):
        priv, pub = generate_ed25519_keypair()
        signer = InternalTokenSigner(priv, kid="notification-1-key", instance_id="notification-1")
        tok = signer.issue_token(lifetime_seconds=120)
        headers = jwt.get_unverified_header(tok)
        self.assertEqual(headers["kid"], "notification-1-key")
        self.assertEqual(headers["alg"], "EdDSA")
        decoded = jwt.decode(
            tok,
            pub,
            algorithms=["EdDSA"],
            issuer=INTERNAL_ISSUER,
            audience=INTERNAL_AUDIENCE,
        )
        self.assertEqual(decoded["sub"], INTERNAL_PRINCIPAL)
        self.assertEqual(decoded["instance_id"], "notification-1")
        self.assertLessEqual(decoded["exp"] - decoded["iat"], 60)
        uuid.UUID(decoded["jti"])

        self.assertEqual(mask_email("ronaldo@example.test"), "ro***@example.test")
        LoggingEmailDeliveryAdapter().send_diagnosis_finished(
            "ronaldo@example.test", str(uuid.uuid4()), "COMPLETADO", str(uuid.uuid4())
        )
        self.assertEqual(CONSUMER_NAME, "notification-consumer")


if __name__ == "__main__":
    unittest.main()
