"""add owner day journal entries

Revision ID: 6b2f9d4a1c73
Revises: d4f1a7c3e9b2
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "6b2f9d4a1c73"
down_revision: Union[str, None] = "d4f1a7c3e9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "day_journal_entry" not in inspect(op.get_bind()).get_table_names():
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
    else:
        expected = {"id", "operation_id", "day", "kind", "text", "symbol", "not_traded", "created_at", "actor"}
        found = {column["name"] for column in inspect(op.get_bind()).get_columns("day_journal_entry")}
        if not expected <= found:
            raise RuntimeError(f"Existing day_journal_entry is missing column(s): {', '.join(sorted(expected - found))}")

    indexes = {item["name"]: item for item in inspect(op.get_bind()).get_indexes("day_journal_entry")}
    if "ix_day_journal_entry_day" in indexes:
        if indexes["ix_day_journal_entry_day"]["column_names"] != ["day"]:
            raise RuntimeError("Existing day_journal_entry day index is incompatible")
    else:
        op.create_index("ix_day_journal_entry_day", "day_journal_entry", ["day"])


def downgrade() -> None:
    op.drop_index("ix_day_journal_entry_day", table_name="day_journal_entry")
    op.drop_table("day_journal_entry")
