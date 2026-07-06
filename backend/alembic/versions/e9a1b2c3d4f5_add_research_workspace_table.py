"""add_research_workspace_table

Revision ID: e9a1b2c3d4f5
Revises: c7d8e9f0a1b2
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a1b2c3d4f5"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "research_workspace" in inspector.get_table_names():
        return

    op.create_table(
        "research_workspace",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_research_workspace_slug"),
        "research_workspace",
        ["slug"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_research_workspace_slug"), table_name="research_workspace"
    )
    op.drop_table("research_workspace")
