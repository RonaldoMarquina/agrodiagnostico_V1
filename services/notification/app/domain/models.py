"""SQLAlchemy domain models for Notification service (ADR-0014)."""
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


VALID_FINAL_STATUSES = ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO")
VALID_DELIVERY_CHANNELS = ("EMAIL",)
VALID_DELIVERY_STATUSES = (
    "PENDING",
    "SENT",
    "FAILED_RETRYABLE",
    "FAILED_PERMANENT",
    "SKIPPED",
)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, nullable=False, index=True)
    diagnosis_id = Column(Uuid, nullable=False)
    final_status = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    read_at = Column(DateTime(timezone=True), nullable=True)
    correlation_id = Column(Uuid, nullable=False)

    delivery_attempts = relationship(
        "NotificationDeliveryAttempt",
        back_populates="notification",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("diagnosis_id", name="uq_notifications_diagnosis_id"),
        CheckConstraint(
            "final_status IN ('COMPLETADO', 'NO_CONCLUYENTE', 'FALLIDO')",
            name="ck_notifications_final_status",
        ),
        Index("ix_notifications_owner_created_id", "owner_id", sa.desc("created_at"), sa.desc("id")),
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    owner_id = Column(Uuid, primary_key=True)
    email_enabled = Column(Boolean, nullable=False, default=False, server_default=sa.false())
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class NotificationInbox(Base):
    __tablename__ = "notification_inbox"

    consumer = Column(String(64), primary_key=True)
    event_id = Column(Uuid, primary_key=True)
    payload_hash = Column(String(64), nullable=False)
    diagnosis_id = Column(Uuid, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_notification_inbox_diagnosis_id", "diagnosis_id"),
    )


class NotificationDeliveryAttempt(Base):
    __tablename__ = "notification_delivery_attempts"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    notification_id = Column(
        Uuid,
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id = Column(Uuid, nullable=False, index=True)
    channel = Column(String(16), nullable=False, default="EMAIL", server_default="EMAIL")
    status = Column(String(32), nullable=False, default="PENDING", server_default="PENDING")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    notification = relationship("Notification", back_populates="delivery_attempts")

    __table_args__ = (
        UniqueConstraint("notification_id", "channel", name="uq_delivery_attempts_notification_channel"),
        CheckConstraint("channel IN ('EMAIL')", name="ck_delivery_attempts_channel"),
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED_RETRYABLE', 'FAILED_PERMANENT', 'SKIPPED')",
            name="ck_delivery_attempts_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_delivery_attempts_count_nonneg"),
        CheckConstraint("max_attempts >= 1", name="ck_delivery_attempts_max_pos"),
        Index("ix_delivery_attempts_status_next", "status", "next_attempt_at"),
    )


class NotificationQuarantineMessage(Base):
    __tablename__ = "notification_quarantine_messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id = Column(String(64), nullable=True)
    routing_key = Column(String(128), nullable=False)
    reason_code = Column(String(80), nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    correlation_id = Column(String(64), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class NotificationDlqOutbox(Base):
    __tablename__ = "notification_dlq_outbox"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    quarantine_id = Column(
        Uuid,
        ForeignKey("notification_quarantine_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    routing_key = Column(String(128), nullable=False)
    descriptor = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    available_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    claim_token = Column(Uuid, nullable=True)
    claimed_until = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_notification_dlq_outbox_pending", "sent_at", "available_at"),
    )
