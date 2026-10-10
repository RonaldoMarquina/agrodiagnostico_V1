"""SQLAlchemy domain models for AI Inference service.

Strict boundaries:
- AI Inference owns its private persistence: jobs, local claim, inbox, results, outbox, quarantine, audit logs.
- Zero cross-service queries or foreign keys to Diagnosis or Identity.
- Results and outbox uniquely scoped to (diagnosis_id, lease_token).
"""
from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InferenceJob(Base):
    __tablename__ = "inference_jobs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    diagnosis_id = Column(Uuid, nullable=False, unique=True)
    attempt_count = Column(Integer, nullable=False, default=1, server_default="1")
    current_lease_token = Column(Uuid, nullable=True)
    status = Column(String(30), nullable=False, default="QUEUED", server_default="QUEUED")
    local_claim_token = Column(Uuid, nullable=True)
    local_claim_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'CLAIMING', 'PROCESSING', 'COMPLETED', 'FAILED', 'DISCARDED')",
            name="ck_inference_jobs_status",
        ),
        Index("ix_inference_jobs_diagnosis_id", "diagnosis_id"),
        Index("ix_inference_jobs_local_claim", "status", "local_claim_expires_at"),
    )


class InferenceInbox(Base):
    __tablename__ = "inference_inbox"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    consumer = Column(String(50), nullable=False)
    event_id = Column(Uuid, nullable=False)
    canonical_hash = Column(String(64), nullable=False)
    diagnosis_id = Column(Uuid, nullable=False)
    status = Column(String(20), nullable=False, default="PROCESSED", server_default="PROCESSED")
    processed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("consumer", "event_id", name="uq_inference_inbox_consumer_event"),
        Index("ix_inference_inbox_diagnosis_id", "diagnosis_id"),
    )


class InferenceResult(Base):
    __tablename__ = "inference_results"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    diagnosis_id = Column(Uuid, nullable=False)
    lease_token = Column(Uuid, nullable=False)
    outcome = Column(String(30), nullable=False)  # 'PREDICTION', 'ABSTENTION', 'FAILURE'
    crop_code = Column(String(50), nullable=True)
    class_code = Column(String(50), nullable=True)
    raw_score = Column(Float, nullable=True)
    model_id = Column(String(128), nullable=True)
    model_version = Column(String(128), nullable=True)
    dataset_version = Column(String(128), nullable=True)
    reason_code = Column(String(50), nullable=True)
    inference_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("diagnosis_id", "lease_token", name="uq_inference_results_diagnosis_lease"),
        Index("ix_inference_results_diagnosis_id", "diagnosis_id"),
    )


class InferenceOutbox(Base):
    __tablename__ = "inference_outbox"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id = Column(Uuid, nullable=False, unique=True)
    event_type = Column(String(50), nullable=False, default="DiagnosisAnalyzed", server_default="DiagnosisAnalyzed")
    schema_version = Column(Integer, nullable=False, default=1, server_default="1")
    routing_key = Column(
        String(100),
        nullable=False,
        default="diagnosis.analyzed.v1",
        server_default="diagnosis.analyzed.v1",
    )
    envelope = Column(JSON, nullable=False)
    diagnosis_id = Column(Uuid, nullable=False)
    lease_token = Column(Uuid, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    available_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    claim_token = Column(Uuid, nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("diagnosis_id", "lease_token", name="uq_inference_outbox_diagnosis_lease"),
        Index("ix_inference_outbox_publishable", "sent_at", "available_at", "claim_expires_at"),
        Index("ix_inference_outbox_diagnosis_id", "diagnosis_id"),
    )


class InferenceQuarantineMessage(Base):
    __tablename__ = "inference_quarantine_messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    consumer = Column(String(50), nullable=False)
    routing_key = Column(String(100), nullable=False)
    message_hash = Column(String(64), nullable=False)
    error_reason = Column(String(255), nullable=False)
    diagnosis_id = Column(Uuid, nullable=True)
    event_id = Column(Uuid, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    descriptor_sent_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_inference_quarantine_created", "created_at"),
        Index("ix_inference_quarantine_hash", "message_hash"),
    )


class InferenceAuditLog(Base):
    __tablename__ = "inference_audit_logs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    actor = Column(String(100), nullable=False)
    action = Column(String(50), nullable=False)
    target_id = Column(String(100), nullable=True)
    correlation_id = Column(Uuid, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_inference_audit_actor", "actor"),
        Index("ix_inference_audit_action", "action"),
        Index("ix_inference_audit_created_at", "created_at"),
    )

