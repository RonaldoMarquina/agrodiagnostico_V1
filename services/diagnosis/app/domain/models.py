"""SQLAlchemy domain models for Diagnosis service.

In accordance with ADR-0006 and OpenSpec Incremento 2:
- Private image storage reference (object_key); no raw image bytes in PostgreSQL.
- Idempotency key per (owner_id, scope, key) with SHA-256 fingerprint and 24h retention.
- Durable image upload intent tracking.
- Agricultural catalog (Crop, Problem, Recommendation with immutable versions).
- Diagnosis entity with status lifecycle, logical delete tombstone (deleted_at), and result snapshot.
- Diagnosis feedback (1:1 with diagnosis).
- Diagnosis audit log (own table, transactional).
- Strict separation: no foreign keys or cross-service queries to Identity.
"""
from datetime import datetime, timezone
import uuid
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Crop(Base):
    __tablename__ = "crops"

    code = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    problems = relationship("Problem", back_populates="crop", cascade="all, delete-orphan")
    diagnoses = relationship("Diagnosis", back_populates="crop")


class Problem(Base):
    __tablename__ = "problems"

    code = Column(String(50), primary_key=True)
    crop_code = Column(String(50), ForeignKey("crops.code", ondelete="RESTRICT"), nullable=False)
    name = Column(String(100), nullable=False)
    type = Column(String(20), nullable=False)  # 'HEALTHY' | 'DISEASE'
    scientific_name = Column(String(150), nullable=True)
    description = Column(String(1000), nullable=True)
    model_supported = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    crop = relationship("Crop", back_populates="problems")
    recommendations = relationship("Recommendation", back_populates="problem", cascade="all, delete-orphan")
    diagnoses = relationship("Diagnosis", back_populates="problem")

    __table_args__ = (
        CheckConstraint("type IN ('HEALTHY', 'DISEASE')", name="ck_problems_type"),
        Index("ix_problems_crop_code", "crop_code"),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    problem_code = Column(String(50), ForeignKey("problems.code", ondelete="RESTRICT"), nullable=False)
    version = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    summary = Column(String(1000), nullable=False)
    cultural_practices = Column(JSON, nullable=False)  # List[str]
    biological_control = Column(JSON, nullable=False)  # List[str]
    preventive_measures = Column(JSON, nullable=False)  # List[str]
    source_refs = Column(JSON, nullable=False)  # List[str]
    review_reference = Column(String(200), nullable=False)
    reviewed_by = Column(String(100), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    problem = relationship("Problem", back_populates="recommendations")
    diagnoses = relationship("Diagnosis", back_populates="recommendation")

    __table_args__ = (
        UniqueConstraint("problem_code", "version", name="uq_recommendations_problem_version"),
        CheckConstraint("version >= 1", name="ck_recommendations_version_positive"),
        Index("ix_recommendations_problem_version", "problem_code", "version"),
    )


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, nullable=False, index=True)
    status = Column(String(30), nullable=False, default="PENDIENTE")
    object_key = Column(String(255), nullable=False, unique=True)
    image_sha256 = Column(String(64), nullable=False)
    image_content_type = Column(String(50), nullable=False)
    image_size_bytes = Column(Integer, nullable=False)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)

    # Result fields (Incremento 3 / populated on completion)
    crop_code = Column(String(50), ForeignKey("crops.code", ondelete="SET NULL"), nullable=True)
    class_code = Column(String(50), ForeignKey("problems.code", ondelete="SET NULL"), nullable=True)
    raw_score = Column(Float, nullable=True)
    model_id = Column(String(128), nullable=True)
    model_version = Column(String(128), nullable=True)
    dataset_version = Column(String(128), nullable=True)
    recommendation_id = Column(Uuid, ForeignKey("recommendations.id", ondelete="SET NULL"), nullable=True)
    catalog_version = Column(String(128), nullable=True)
    recommendation_text = Column(Text, nullable=True)

    # Terminal reason codes
    reason_code = Column(String(50), nullable=True)
    failure_code = Column(String(50), nullable=True)

    # Incremento 3: Asynchronous processing, leases, and correlation
    correlation_id = Column(Uuid, nullable=True)
    lease_owner = Column(String(100), nullable=True)
    lease_token = Column(Uuid, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    processing_deadline_at = Column(DateTime(timezone=True), nullable=True)
    recovery_signaled_at = Column(DateTime(timezone=True), nullable=True)

    # Logical delete tombstone
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    crop = relationship("Crop", back_populates="diagnoses")
    problem = relationship("Problem", back_populates="diagnoses")
    recommendation = relationship("Recommendation", back_populates="diagnoses")
    feedback = relationship("DiagnosisFeedback", back_populates="diagnosis", uselist=False, cascade="all, delete-orphan")
    idempotency_keys = relationship("IdempotencyKey", back_populates="diagnosis", cascade="all, delete-orphan")
    outbox_events = relationship("DiagnosisOutbox", back_populates="diagnosis", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDIENTE', 'PROCESANDO', 'COMPLETADO', 'NO_CONCLUYENTE', 'FALLIDO', 'CANCELADO')",
            name="ck_diagnoses_status",
        ),
        Index("ix_diagnoses_created_at_id", "created_at", "id"),
        Index("ix_diagnoses_owner_keyset", "owner_id", "deleted_at", "created_at", "id"),
        Index("ix_diagnoses_admin_keyset", "deleted_at", "created_at", "id"),
        Index("ix_diagnoses_lease_expires", "status", "lease_expires_at"),
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id = Column(Uuid, nullable=False)
    scope = Column(String(50), nullable=False, default="diagnosis_create")
    key = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    diagnosis_id = Column(Uuid, ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    diagnosis = relationship("Diagnosis", back_populates="idempotency_keys")

    __table_args__ = (
        UniqueConstraint("owner_id", "scope", "key", name="uq_idempotency_keys_owner_scope_key"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
        Index("ix_idempotency_keys_diagnosis_id", "diagnosis_id"),
    )


class ImageUploadIntent(Base):
    __tablename__ = "image_upload_intents"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    diagnosis_id = Column(Uuid, nullable=False, unique=True)
    object_key = Column(String(255), nullable=False, unique=True)
    owner_id = Column(Uuid, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_image_upload_intents_created_at", "created_at"),
    )


class DiagnosisFeedback(Base):
    __tablename__ = "diagnosis_feedback"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    diagnosis_id = Column(Uuid, ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=False, unique=True)
    owner_id = Column(Uuid, nullable=False, index=True)
    useful = Column(Boolean, nullable=False)
    comment = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    diagnosis = relationship("Diagnosis", back_populates="feedback")


class DiagnosisAuditLog(Base):
    __tablename__ = "diagnosis_audit_logs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id = Column(Uuid, nullable=False)
    action = Column(String(50), nullable=False)
    target_type = Column(String(50), nullable=False)
    target_id = Column(String(100), nullable=True)
    correlation_id = Column(Uuid, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_diagnosis_audit_logs_actor_id", "actor_id"),
        Index("ix_diagnosis_audit_logs_action", "action"),
        Index("ix_diagnosis_audit_logs_created_at", "created_at"),
    )


class DiagnosisOutbox(Base):
    __tablename__ = "diagnosis_outbox"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id = Column(Uuid, nullable=False, unique=True)
    event_type = Column(String(50), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    routing_key = Column(String(100), nullable=False)
    envelope = Column(JSON, nullable=False)
    diagnosis_id = Column(Uuid, ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=True)
    attempt_number = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    available_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    claim_token = Column(Uuid, nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)

    diagnosis = relationship("Diagnosis", back_populates="outbox_events")

    __table_args__ = (
        UniqueConstraint("diagnosis_id", "event_type", "attempt_number", name="uq_diagnosis_outbox_diag_event_attempt"),
        Index("ix_diagnosis_outbox_publishable", "sent_at", "available_at", "claim_expires_at"),
        Index("ix_diagnosis_outbox_diagnosis_id", "diagnosis_id"),
    )


class DiagnosisInbox(Base):
    __tablename__ = "diagnosis_inbox"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    consumer = Column(String(50), nullable=False)
    event_id = Column(Uuid, nullable=False)
    canonical_hash = Column(String(64), nullable=False)
    diagnosis_id = Column(Uuid, nullable=True)
    lease_token = Column(Uuid, nullable=True)
    status = Column(String(20), nullable=False, default="PROCESSED")
    processed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("consumer", "event_id", name="uq_diagnosis_inbox_consumer_event"),
        Index("ix_diagnosis_inbox_diagnosis_lease", "diagnosis_id", "lease_token"),
    )


class DiagnosisQuarantineMessage(Base):
    __tablename__ = "diagnosis_quarantine_messages"

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
        Index("ix_diagnosis_quarantine_created", "created_at"),
        Index("ix_diagnosis_quarantine_hash", "message_hash"),
    )
