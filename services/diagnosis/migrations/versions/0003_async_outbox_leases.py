"""Asynchronous outbox, inbox, leases, and quarantine messages.

Revision ID: diagnosis_0003
Revises: diagnosis_0002
Create Date: 2026-10-07 10:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "diagnosis_0003"
down_revision = "diagnosis_0002"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add asynchronous processing and lease columns to diagnoses table
    op.add_column("diagnoses", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.add_column("diagnoses", sa.Column("lease_owner", sa.String(length=100), nullable=True))
    op.add_column("diagnoses", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column("diagnoses", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "diagnoses",
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("diagnoses", sa.Column("processing_deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("diagnoses", sa.Column("recovery_signaled_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        "ix_diagnoses_lease_expires",
        "diagnoses",
        ["status", "lease_expires_at"],
    )

    # 2. diagnosis_outbox
    op.create_table(
        "diagnosis_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("routing_key", sa.String(length=100), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["diagnosis_id"], ["diagnoses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_diagnosis_outbox_event_id"),
        sa.UniqueConstraint(
            "diagnosis_id", "event_type", "attempt_number",
            name="uq_diagnosis_outbox_diag_event_attempt",
        ),
    )
    op.create_index(
        "ix_diagnosis_outbox_publishable",
        "diagnosis_outbox",
        ["sent_at", "available_at", "claim_expires_at"],
    )
    op.create_index(
        "ix_diagnosis_outbox_diagnosis_id",
        "diagnosis_outbox",
        ["diagnosis_id"],
    )

    # 3. diagnosis_inbox
    op.create_table(
        "diagnosis_inbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.String(length=50), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="PROCESSED", nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumer", "event_id", name="uq_diagnosis_inbox_consumer_event"),
    )
    op.create_index(
        "ix_diagnosis_inbox_diagnosis_lease",
        "diagnosis_inbox",
        ["diagnosis_id", "lease_token"],
    )

    # 4. diagnosis_quarantine_messages
    op.create_table(
        "diagnosis_quarantine_messages",
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
        "ix_diagnosis_quarantine_created",
        "diagnosis_quarantine_messages",
        ["created_at"],
    )
    op.create_index(
        "ix_diagnosis_quarantine_hash",
        "diagnosis_quarantine_messages",
        ["message_hash"],
    )


def downgrade():
    op.drop_table("diagnosis_quarantine_messages")
    op.drop_table("diagnosis_inbox")
    op.drop_table("diagnosis_outbox")
    op.drop_index("ix_diagnoses_lease_expires", table_name="diagnoses")
    op.drop_column("diagnoses", "recovery_signaled_at")
    op.drop_column("diagnoses", "processing_deadline_at")
    op.drop_column("diagnoses", "attempt_count")
    op.drop_column("diagnoses", "lease_expires_at")
    op.drop_column("diagnoses", "lease_token")
    op.drop_column("diagnoses", "lease_owner")
    op.drop_column("diagnoses", "correlation_id")

