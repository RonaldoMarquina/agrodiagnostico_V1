"""AI Inference domain tables: jobs, inbox, results, outbox, quarantine, and audit.

Revision ID: ai_inference_0002
Revises: ai_inference_0001
Create Date: 2026-10-07 10:15:00
"""
from alembic import op
import sqlalchemy as sa

revision = "ai_inference_0002"
down_revision = "ai_inference_0001"
branch_labels = None
depends_on = None


def upgrade():
    # 1. inference_jobs
    op.create_table(
        "inference_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("current_lease_token", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="QUEUED", nullable=False),
        sa.Column("local_claim_token", sa.Uuid(), nullable=True),
        sa.Column("local_claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("diagnosis_id", name="uq_inference_jobs_diagnosis_id"),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'CLAIMING', 'PROCESSING', 'COMPLETED', 'FAILED', 'DISCARDED')",
            name="ck_inference_jobs_status",
        ),
    )
    op.create_index("ix_inference_jobs_diagnosis_id", "inference_jobs", ["diagnosis_id"])
    op.create_index(
        "ix_inference_jobs_local_claim",
        "inference_jobs",
        ["status", "local_claim_expires_at"],
    )

    # 2. inference_inbox
    op.create_table(
        "inference_inbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.String(length=50), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PROCESSED", nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumer", "event_id", name="uq_inference_inbox_consumer_event"),
    )
    op.create_index("ix_inference_inbox_diagnosis_id", "inference_inbox", ["diagnosis_id"])

    # 3. inference_results
    op.create_table(
        "inference_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("crop_code", sa.String(length=50), nullable=True),
        sa.Column("class_code", sa.String(length=50), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("dataset_version", sa.String(length=128), nullable=True),
        sa.Column("reason_code", sa.String(length=50), nullable=True),
        sa.Column("inference_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("diagnosis_id", "lease_token", name="uq_inference_results_diagnosis_lease"),
    )
    op.create_index("ix_inference_results_diagnosis_id", "inference_results", ["diagnosis_id"])

    # 4. inference_outbox
    op.create_table(
        "inference_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), server_default="DiagnosisAnalyzed", nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "routing_key",
            sa.String(length=100),
            server_default="diagnosis.analyzed.v1",
            nullable=False,
        ),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_inference_outbox_event_id"),
        sa.UniqueConstraint("diagnosis_id", "lease_token", name="uq_inference_outbox_diagnosis_lease"),
    )
    op.create_index(
        "ix_inference_outbox_publishable",
        "inference_outbox",
        ["sent_at", "available_at", "claim_expires_at"],
    )
    op.create_index("ix_inference_outbox_diagnosis_id", "inference_outbox", ["diagnosis_id"])

    # 5. inference_quarantine_messages
    op.create_table(
        "inference_quarantine_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.String(length=50), nullable=False),
        sa.Column("routing_key", sa.String(length=100), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("error_reason", sa.String(length=255), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("descriptor_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inference_quarantine_created",
        "inference_quarantine_messages",
        ["created_at"],
    )
    op.create_index(
        "ix_inference_quarantine_hash",
        "inference_quarantine_messages",
        ["message_hash"],
    )

    # 6. inference_audit_logs
    op.create_table(
        "inference_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inference_audit_actor", "inference_audit_logs", ["actor"])
    op.create_index("ix_inference_audit_action", "inference_audit_logs", ["action"])
    op.create_index("ix_inference_audit_created_at", "inference_audit_logs", ["created_at"])


def downgrade():
    op.drop_table("inference_audit_logs")
    op.drop_table("inference_quarantine_messages")
    op.drop_table("inference_outbox")
    op.drop_table("inference_results")
    op.drop_table("inference_inbox")
    op.drop_table("inference_jobs")

