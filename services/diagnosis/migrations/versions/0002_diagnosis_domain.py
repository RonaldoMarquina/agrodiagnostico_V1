"""Diagnosis domain tables, candidate taxonomy seeds, and audit logs.

Revision ID: diagnosis_0002
Revises: diagnosis_0001
Create Date: 2026-10-01 00:40:00
"""
from alembic import op
import sqlalchemy as sa

revision = "diagnosis_0002"
down_revision = "diagnosis_0001"
branch_labels = None
depends_on = None


def upgrade():
    # 1. crops
    crops_table = op.create_table(
        "crops",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )

    # 2. problems
    problems_table = op.create_table(
        "problems",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("crop_code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("scientific_name", sa.String(length=150), nullable=True),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("model_supported", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("type IN ('HEALTHY', 'DISEASE')", name="ck_problems_type"),
        sa.ForeignKeyConstraint(["crop_code"], ["crops.code"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index("ix_problems_crop_code", "problems", ["crop_code"])

    # 3. recommendations
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("problem_code", sa.String(length=50), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("cultural_practices", sa.JSON(), nullable=False),
        sa.Column("biological_control", sa.JSON(), nullable=False),
        sa.Column("preventive_measures", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("review_reference", sa.String(length=200), nullable=False),
        sa.Column("reviewed_by", sa.String(length=100), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_recommendations_version_positive"),
        sa.ForeignKeyConstraint(["problem_code"], ["problems.code"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("problem_code", "version", name="uq_recommendations_problem_version"),
    )
    op.create_index("ix_recommendations_problem_version", "recommendations", ["problem_code", "version"])

    # 4. diagnoses
    op.create_table(
        "diagnoses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="PENDIENTE", nullable=False),
        sa.Column("object_key", sa.String(length=255), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("image_content_type", sa.String(length=50), nullable=False),
        sa.Column("image_size_bytes", sa.Integer(), nullable=False),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("crop_code", sa.String(length=50), nullable=True),
        sa.Column("class_code", sa.String(length=50), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("dataset_version", sa.String(length=128), nullable=True),
        sa.Column("recommendation_id", sa.Uuid(), nullable=True),
        sa.Column("catalog_version", sa.String(length=128), nullable=True),
        sa.Column("recommendation_text", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.String(length=50), nullable=True),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDIENTE', 'PROCESANDO', 'COMPLETADO', 'NO_CONCLUYENTE', 'FALLIDO', 'CANCELADO')",
            name="ck_diagnoses_status",
        ),
        sa.ForeignKeyConstraint(["crop_code"], ["crops.code"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["class_code"], ["problems.code"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_diagnoses_owner_id", "diagnoses", ["owner_id"])
    op.create_index("ix_diagnoses_created_at_id", "diagnoses", ["created_at", "id"])
    op.create_index("ix_diagnoses_owner_keyset", "diagnoses", ["owner_id", "deleted_at", "created_at", "id"])
    op.create_index("ix_diagnoses_admin_keyset", "diagnoses", ["deleted_at", "created_at", "id"])

    # 5. idempotency_keys
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=50), server_default="diagnosis_create", nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["diagnosis_id"], ["diagnoses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "scope", "key", name="uq_idempotency_keys_owner_scope_key"),
    )
    op.create_index("ix_idempotency_keys_expires_at", "idempotency_keys", ["expires_at"])
    op.create_index("ix_idempotency_keys_diagnosis_id", "idempotency_keys", ["diagnosis_id"])

    # 6. image_upload_intents
    op.create_table(
        "image_upload_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("diagnosis_id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_image_upload_intents_created_at", "image_upload_intents", ["created_at"])

    # 7. diagnosis_feedback
    op.create_table(
        "diagnosis_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("useful", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["diagnosis_id"], ["diagnoses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("diagnosis_id"),
    )
    op.create_index("ix_diagnosis_feedback_owner_id", "diagnosis_feedback", ["owner_id"])

    # 8. diagnosis_audit_logs
    op.create_table(
        "diagnosis_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_diagnosis_audit_logs_actor_id", "diagnosis_audit_logs", ["actor_id"])
    op.create_index("ix_diagnosis_audit_logs_action", "diagnosis_audit_logs", ["action"])
    op.create_index("ix_diagnosis_audit_logs_created_at", "diagnosis_audit_logs", ["created_at"])

    # Insert candidate seeds: POTATO and MAIZE
    op.bulk_insert(
        crops_table,
        [
            {
                "code": "POTATO",
                "name": "Papa",
                "description": "Cultivo de papa (Solanum tuberosum)",
                "active": True,
            },
            {
                "code": "MAIZE",
                "name": "Maíz",
                "description": "Cultivo de maíz (Zea mays)",
                "active": True,
            },
        ],
    )

    # Insert 7 candidate conditions: 2 healthy, 5 diseases with model_supported=False
    op.bulk_insert(
        problems_table,
        [
            {
                "code": "POTATO_HEALTHY",
                "crop_code": "POTATO",
                "name": "Papa sana",
                "type": "HEALTHY",
                "scientific_name": None,
                "description": "Follaje de papa sin síntomas de enfermedad infecciosa observada.",
                "model_supported": False,
                "active": True,
            },
            {
                "code": "POTATO_EARLY_BLIGHT",
                "crop_code": "POTATO",
                "name": "Tizón temprano de la papa",
                "type": "DISEASE",
                "scientific_name": "Alternaria solani",
                "description": "Condición foliar caracterizada por lesiones concéntricas oscuras.",
                "model_supported": False,
                "active": True,
            },
            {
                "code": "POTATO_LATE_BLIGHT",
                "crop_code": "POTATO",
                "name": "Tizón tardío de la papa",
                "type": "DISEASE",
                "scientific_name": "Phytophthora infestans",
                "description": "Lesiones acuosas oscuras de rápida dispersión en condiciones húmedas.",
                "model_supported": False,
                "active": True,
            },
            {
                "code": "MAIZE_HEALTHY",
                "crop_code": "MAIZE",
                "name": "Maíz sano",
                "type": "HEALTHY",
                "scientific_name": None,
                "description": "Hojas de maíz sin signos visibles de patologías foliares.",
                "model_supported": False,
                "active": True,
            },
            {
                "code": "MAIZE_COMMON_RUST",
                "crop_code": "MAIZE",
                "name": "Roya común del maíz",
                "type": "DISEASE",
                "scientific_name": "Puccinia sorghi",
                "description": "Pústulas pulverulentas de color canela a marrón oscuro en ambas caras de la hoja.",
                "model_supported": False,
                "active": True,
            },
            {
                "code": "MAIZE_LEAF_BLIGHT",
                "crop_code": "MAIZE",
                "name": "Tizón foliar del maíz",
                "type": "DISEASE",
                "scientific_name": "Exserohilum turcicum",
                "description": "Lesiones alargadas elípticas grisáceas o pajizas a lo largo de las nervaduras.",
                "model_supported": False,
                "active": True,
            },
            {
                "code": "MAIZE_GRAY_LEAF_SPOT",
                "crop_code": "MAIZE",
                "name": "Mancha gris de la hoja del maíz",
                "type": "DISEASE",
                "scientific_name": "Cercospora zeae-maydis",
                "description": "Lesiones rectangulares delimitadas por las nervaduras foliares.",
                "model_supported": False,
                "active": True,
            },
        ],
    )


def downgrade():
    op.drop_table("diagnosis_audit_logs")
    op.drop_table("diagnosis_feedback")
    op.drop_table("image_upload_intents")
    op.drop_table("idempotency_keys")
    op.drop_table("diagnoses")
    op.drop_table("recommendations")
    op.drop_table("problems")
    op.drop_table("crops")
