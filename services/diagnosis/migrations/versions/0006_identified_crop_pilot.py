"""Store user identified crop separately from the published model result.

Revision ID: diagnosis_0006
Revises: diagnosis_0005
"""

from alembic import op
import sqlalchemy as sa

revision = "diagnosis_0006"
down_revision = "diagnosis_0005"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("diagnoses") as batch_op:
        batch_op.add_column(sa.Column("identified_crop", sa.String(50), nullable=True))
        batch_op.create_check_constraint(
            "ck_diagnoses_identified_crop_pilot",
            "identified_crop IS NULL OR identified_crop = 'POTATO'",
        )


def downgrade():
    with op.batch_alter_table("diagnoses") as batch_op:
        batch_op.drop_constraint("ck_diagnoses_identified_crop_pilot", type_="check")
        batch_op.drop_column("identified_crop")
