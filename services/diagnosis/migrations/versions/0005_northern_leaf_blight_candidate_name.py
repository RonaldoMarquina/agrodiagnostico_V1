"""Correct the candidate display name without changing class code or support.

Revision ID: diagnosis_0005
Revises: diagnosis_0004

The project owner selected the proposed name "Tizón foliar del norte". This
migration only updates the original catalog seed value; a manually edited name
is left untouched. Academic review and model support remain pending.
"""

from alembic import op
import sqlalchemy as sa

revision = "diagnosis_0005"
down_revision = "diagnosis_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(
        sa.text(
            "UPDATE problems SET name = :new_name, updated_at = CURRENT_TIMESTAMP "
            "WHERE code = :code AND name = :old_name"
        ),
        {
            "new_name": "Tizón foliar del norte",
            "code": "MAIZE_LEAF_BLIGHT",
            "old_name": "Tizón foliar del maíz",
        },
    )


def downgrade():
    # No restaurar un nombre impreciso ni sobrescribir una edición posterior.
    pass
