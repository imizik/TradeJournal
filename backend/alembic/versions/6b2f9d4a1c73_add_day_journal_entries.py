"""add owner day journal entries

Revision ID: 6b2f9d4a1c73
Revises: c7e2a9d4b1f8
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6b2f9d4a1c73"
down_revision: Union[str, None] = "c7e2a9d4b1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "day_journal_entry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.String(length=100), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=True),
        sa.Column("not_traded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_day_journal_entry_operation_id"),
    )
    op.create_index("ix_day_journal_entry_day", "day_journal_entry", ["day"])


def downgrade() -> None:
    op.drop_index("ix_day_journal_entry_day", table_name="day_journal_entry")
    op.drop_table("day_journal_entry")
