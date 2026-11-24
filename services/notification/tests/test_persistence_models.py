"""Unit tests for Notification persistence models and Alembic revision chain (ADR-0014)."""
import unittest
import uuid

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.models import (
    Base,
    Notification,
    NotificationDeliveryAttempt,
    NotificationDlqOutbox,
    NotificationInbox,
    NotificationPreference,
    NotificationQuarantineMessage,
)
from app.persistence import config as alembic_config


class TestNotificationPersistenceModels(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_alembic_revision_chain_single_head(self):
        script = ScriptDirectory.from_config(alembic_config())
        self.assertEqual(script.get_heads(), ["notification_0002"])
        rev = script.get_revision("notification_0002")
        self.assertEqual(rev.down_revision, "notification_0001")

    def test_notification_uniqueness_and_status_constraint(self):
        owner_id = uuid.uuid4()
        diag_id = uuid.uuid4()
        cid = uuid.uuid4()

        with self.SessionLocal() as db:
            first = Notification(
                owner_id=owner_id,
                diagnosis_id=diag_id,
                final_status="COMPLETADO",
                correlation_id=cid,
            )
            db.add(first)
            db.commit()
            self.assertIsNone(first.read_at)

            dup = Notification(
                owner_id=owner_id,
                diagnosis_id=diag_id,
                final_status="NO_CONCLUYENTE",
                correlation_id=cid,
            )
            db.add(dup)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            invalid_status = Notification(
                owner_id=owner_id,
                diagnosis_id=uuid.uuid4(),
                final_status="CANCELADO",
                correlation_id=cid,
            )
            db.add(invalid_status)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_preference_defaults_to_email_disabled(self):
        owner_id = uuid.uuid4()
        with self.SessionLocal() as db:
            pref = NotificationPreference(owner_id=owner_id)
            db.add(pref)
            db.commit()
            db.refresh(pref)
            self.assertFalse(pref.email_enabled)

    def test_inbox_deduplication_primary_key(self):
        event_id = uuid.uuid4()
        diag_id = uuid.uuid4()
        with self.SessionLocal() as db:
            db.add(
                NotificationInbox(
                    consumer="notification-consumer",
                    event_id=event_id,
                    payload_hash="a" * 64,
                    diagnosis_id=diag_id,
                )
            )
            db.commit()

            db.add(
                NotificationInbox(
                    consumer="notification-consumer",
                    event_id=event_id,
                    payload_hash="b" * 64,
                    diagnosis_id=diag_id,
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_delivery_attempt_constraints_and_quarantine_dlq_outbox(self):
        owner_id = uuid.uuid4()
        with self.SessionLocal() as db:
            notif = Notification(
                owner_id=owner_id,
                diagnosis_id=uuid.uuid4(),
                final_status="FALLIDO",
                correlation_id=uuid.uuid4(),
            )
            db.add(notif)
            db.flush()

            attempt = NotificationDeliveryAttempt(
                notification_id=notif.id,
                owner_id=owner_id,
            )
            db.add(attempt)
            db.commit()
            db.refresh(attempt)
            self.assertEqual(attempt.channel, "EMAIL")
            self.assertEqual(attempt.status, "PENDING")
            self.assertEqual(attempt.attempt_count, 0)
            self.assertEqual(attempt.max_attempts, 3)

            # Duplicate channel for same notification rejected
            db.add(NotificationDeliveryAttempt(notification_id=notif.id, owner_id=owner_id, channel="EMAIL"))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            # Invalid status rejected
            db.add(
                NotificationDeliveryAttempt(
                    notification_id=notif.id,
                    owner_id=owner_id,
                    channel="SMS",
                    status="PENDING",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

            # Quarantine + DLQ outbox
            q = NotificationQuarantineMessage(
                event_id=str(uuid.uuid4()),
                routing_key="diagnosis.finished.v1",
                reason_code="UNSUPPORTED_SCHEMA_VERSION",
                payload_sha256="c" * 64,
                correlation_id=str(uuid.uuid4()),
            )
            db.add(q)
            db.flush()
            outbox = NotificationDlqOutbox(
                quarantine_id=q.id,
                routing_key="diagnosis.finished.v1.dlq",
                descriptor={"quarantine_id": str(q.id), "reason_code": q.reason_code},
            )
            db.add(outbox)
            db.commit()
            self.assertIsNone(outbox.sent_at)


if __name__ == "__main__":
    unittest.main()
