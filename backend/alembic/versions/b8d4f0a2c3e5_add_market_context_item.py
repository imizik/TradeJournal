"""add_market_context_item

Revision ID: b8d4f0a2c3e5
Revises: a7c3e9f1b2d4
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d4f0a2c3e5"
down_revision: Union[str, None] = "a7c3e9f1b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "market_context_item" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "market_context_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_market_context_item_kind"), "market_context_item", ["kind"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_market_context_item_kind"), table_name="market_context_item")
    op.drop_table("market_context_item")
