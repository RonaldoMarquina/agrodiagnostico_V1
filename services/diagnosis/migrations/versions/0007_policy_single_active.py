"""Enforce at most one active publication policy.

Revision ID: diagnosis_0007
Revises: diagnosis_0006
"""

from alembic import op
import sqlalchemy as sa

revision = "diagnosis_0007"
down_revision = "diagnosis_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_publication_policies_one_active", "publication_policies", ["active"],
        unique=True, postgresql_where=sa.text("active"), sqlite_where=sa.text("active"),
    )


def downgrade():
    op.drop_index("uq_publication_policies_one_active", table_name="publication_policies")
