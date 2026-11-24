"""Notification domain tables, inbox, delivery attempts, and DLQ quarantine (ADR-0014)."""
from alembic import op
import sqlalchemy as sa

revision = "notification_0002"
down_revision = "notification_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("final_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("diagnosis_id", name="uq_notifications_diagnosis_id"),
        sa.CheckConstraint(
            "final_status IN ('COMPLETADO', 'NO_CONCLUYENTE', 'FALLIDO')",
            name="ck_notifications_final_status",
        ),
    )
    op.create_index("ix_notifications_owner_id", "notifications", ["owner_id"])
    op.create_index(
        "ix_notifications_owner_created_id",
        "notifications",
        ["owner_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "notification_preferences",
        sa.Column("owner_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "notification_inbox",
        sa.Column("consumer", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("event_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_inbox_diagnosis_id", "notification_inbox", ["diagnosis_id"])

    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False, server_default="EMAIL"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("notification_id", "channel", name="uq_delivery_attempts_notification_channel"),
        sa.CheckConstraint("channel IN ('EMAIL')", name="ck_delivery_attempts_channel"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED_RETRYABLE', 'FAILED_PERMANENT', 'SKIPPED')",
            name="ck_delivery_attempts_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_delivery_attempts_count_nonneg"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_delivery_attempts_max_pos"),
    )
    op.create_index("ix_delivery_attempts_owner_id", "notification_delivery_attempts", ["owner_id"])
    op.create_index(
        "ix_delivery_attempts_status_next",
        "notification_delivery_attempts",
        ["status", "next_attempt_at"],
    )

    op.create_table(
        "notification_quarantine_messages",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("routing_key", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "notification_dlq_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "quarantine_id",
            sa.Uuid(),
            sa.ForeignKey("notification_quarantine_messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("routing_key", sa.String(length=128), nullable=False),
        sa.Column("descriptor", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notification_dlq_outbox_pending",
        "notification_dlq_outbox",
        ["sent_at", "available_at"],
    )


def downgrade():
    op.drop_index("ix_notification_dlq_outbox_pending", table_name="notification_dlq_outbox")
    op.drop_table("notification_dlq_outbox")
    op.drop_table("notification_quarantine_messages")
    op.drop_index("ix_delivery_attempts_status_next", table_name="notification_delivery_attempts")
    op.drop_index("ix_delivery_attempts_owner_id", table_name="notification_delivery_attempts")
    op.drop_table("notification_delivery_attempts")
    op.drop_index("ix_notification_inbox_diagnosis_id", table_name="notification_inbox")
    op.drop_table("notification_inbox")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_owner_created_id", table_name="notifications")
    op.drop_index("ix_notifications_owner_id", table_name="notifications")
    op.drop_table("notifications")
