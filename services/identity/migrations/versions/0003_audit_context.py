"""Add normative audit context without altering historical audit entries."""
from alembic import op
import sqlalchemy as sa

revision = "identity_0003"
down_revision = "identity_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_logs", sa.Column("actor_id", sa.Uuid(), nullable=True))
    op.add_column("audit_logs", sa.Column("target_id", sa.Uuid(), nullable=True))
    op.add_column("audit_logs", sa.Column("action", sa.String(50), nullable=True))
    op.add_column("audit_logs", sa.Column("correlation_id", sa.Uuid(), nullable=True))
    # Existing rows acquire legacy=true without an UPDATE or fabricated context.
    op.add_column("audit_logs", sa.Column("legacy", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.alter_column("audit_logs", "legacy", server_default=sa.false())
    op.create_check_constraint("ck_audit_normative_fields", "audit_logs",
                               "legacy OR (action IS NOT NULL AND correlation_id IS NOT NULL)")


def downgrade():
    op.drop_constraint("ck_audit_normative_fields", "audit_logs", type_="check")
    for name in ("legacy", "correlation_id", "action", "target_id", "actor_id"):
        op.drop_column("audit_logs", name)
