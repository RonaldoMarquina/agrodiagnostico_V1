"""Publication policies table and additive confidence/snapshot fields.

Revision ID: diagnosis_0004
Revises: diagnosis_0003
Create Date: 2026-10-15 14:00:00

Downgrade Limits and Immutability Notice:
- This migration is strictly additive.
- Historical diagnoses retain NULL values for calibrated_confidence, policy_id, policy_version, and policy_digest.
- Reversing this migration (downgrade) removes publication policy definitions and confidence snapshots.
- Per ADR-0008 and ADR-0009, terminal diagnoses (COMPLETADO, NO_CONCLUYENTE, FALLIDO, CANCELADO)
  are strictly immutable and must never be rewritten or retrofitted with synthetic calibrations.
"""
from alembic import op
import sqlalchemy as sa

revision = "diagnosis_0004"
down_revision = "diagnosis_0003"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create publication_policies table
    op.create_table(
        "publication_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("dataset_version", sa.String(length=128), nullable=False),
        sa.Column("bundle_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_publication_policies_active",
        "publication_policies",
        ["active"],
    )
    op.create_index(
        "ix_publication_policies_model_dataset",
        "publication_policies",
        ["model_id", "model_version", "dataset_version"],
    )

    # 2. Add additive columns to diagnoses table
    op.add_column("diagnoses", sa.Column("calibrated_confidence", sa.Float(), nullable=True))
    op.add_column("diagnoses", sa.Column("policy_id", sa.Uuid(), nullable=True))
    op.add_column("diagnoses", sa.Column("policy_version", sa.String(length=50), nullable=True))
    op.add_column("diagnoses", sa.Column("policy_digest", sa.String(length=64), nullable=True))

    with op.batch_alter_table("diagnoses") as batch_op:
        batch_op.create_foreign_key(
            "fk_diagnoses_policy_id",
            "publication_policies",
            ["policy_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("diagnoses") as batch_op:
        batch_op.drop_constraint("fk_diagnoses_policy_id", type_="foreignkey")
        batch_op.drop_column("policy_digest")
        batch_op.drop_column("policy_version")
        batch_op.drop_column("policy_id")
        batch_op.drop_column("calibrated_confidence")

    op.drop_index("ix_publication_policies_model_dataset", table_name="publication_policies")
    op.drop_index("ix_publication_policies_active", table_name="publication_policies")
    op.drop_table("publication_policies")
