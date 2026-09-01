"""Create the model registry tables.

Revision ID: 20260901_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(length=63), nullable=False),
        sa.Column("version", sa.String(length=63), nullable=False),
        sa.Column("runtime_image", sa.String(length=512), nullable=False),
        sa.Column("artifact_digest", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["model_name"], ["models.name"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_name", "version"),
    )
    op.create_index(
        op.f("ix_model_versions_model_name"), "model_versions", ["model_name"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_versions_model_name"), table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_table("models")
