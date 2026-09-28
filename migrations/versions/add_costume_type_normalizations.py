"""add costume type normalizations

Revision ID: c4e8a7b91d26
Revises: b7c2d9e4f1a3
Create Date: 2026-09-28
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4e8a7b91d26"
down_revision = "b7c2d9e4f1a3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "costume_type_normalizations",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "costume_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "photo_type_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "normalized_type",
            sa.String(length=20),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["costume_id"],
            ["costumes.id"],
            name="fk_costume_type_normalizations_costume_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["photo_type_id"],
            ["photo_types.id"],
            name="fk_costume_type_normalizations_photo_type_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "costume_id",
            "photo_type_id",
            name="uq_costume_type_normalization",
        ),
        sa.CheckConstraint(
            "normalized_type IN ('ヨリ','チュウ','ヒキ','座り')",
            name="check_normalized_type",
        ),
    )

    op.create_index(
        "ix_costume_type_normalizations_costume_id",
        "costume_type_normalizations",
        ["costume_id"],
        unique=False,
    )

    op.create_index(
        "ix_costume_type_normalizations_photo_type_id",
        "costume_type_normalizations",
        ["photo_type_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_costume_type_normalizations_photo_type_id",
        table_name="costume_type_normalizations",
    )

    op.drop_index(
        "ix_costume_type_normalizations_costume_id",
        table_name="costume_type_normalizations",
    )

    op.drop_table("costume_type_normalizations")