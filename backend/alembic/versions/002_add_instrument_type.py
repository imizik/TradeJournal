"""Add instrument_type; make option fields nullable

Revision ID: 002
Revises: 001
Create Date: 2026-03-31
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recreate fill table with instrument_type + nullable option fields
    op.rename_table("fill", "fill_old")
    op.create_table(
        "fill",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("instrument_type", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("contracts", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_email_id", sa.String(), nullable=False),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("expiration", sa.Date(), nullable=True),
        sa.Column("iv_at_fill", sa.Float(), nullable=True),
        sa.Column("delta_at_fill", sa.Float(), nullable=True),
        sa.Column("iv_rank_at_fill", sa.Float(), nullable=True),
        sa.Column("underlying_price_at_fill", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("""
        INSERT INTO fill (id, account_id, ticker, instrument_type, side, contracts,
                          price, executed_at, raw_email_id, option_type, strike, expiration,
                          iv_at_fill, delta_at_fill, iv_rank_at_fill, underlying_price_at_fill)
        SELECT id, account_id, ticker, 'option', side, contracts,
               price, executed_at, raw_email_id, option_type, strike, expiration,
               iv_at_fill, delta_at_fill, iv_rank_at_fill, underlying_price_at_fill
        FROM fill_old
    """)
    op.drop_table("fill_old")

    # Recreate trade table with instrument_type + nullable option fields
    op.execute("DROP TABLE IF EXISTS tradefill")
    op.execute("DROP TABLE IF EXISTS tradetag")
    op.execute("DROP TABLE IF EXISTS trade")
    op.create_table(
        "trade",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("instrument_type", sa.String(), nullable=False),
        sa.Column("contracts", sa.Integer(), nullable=False),
        sa.Column("avg_entry_premium", sa.Float(), nullable=False),
        sa.Column("avg_exit_premium", sa.Float(), nullable=True),
        sa.Column("total_premium_paid", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("pnl_pct", sa.Float(), nullable=True),
        sa.Column("hold_duration_mins", sa.Integer(), nullable=True),
        sa.Column("entry_time_bucket", sa.String(), nullable=True),
        sa.Column("expired_worthless", sa.Boolean(), nullable=False),
        sa.Column("roll_group_id", sa.Uuid(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("ai_review", sa.Text(), nullable=True),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("expiration", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tradefill",
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("fill_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trade.id"]),
        sa.ForeignKeyConstraint(["fill_id"], ["fill.id"]),
        sa.PrimaryKeyConstraint("trade_id", "fill_id"),
    )
    op.create_table(
        "tradetag",
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trade.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"]),
        sa.PrimaryKeyConstraint("trade_id", "tag_id"),
    )


def downgrade() -> None:
    pass  # not supported — re-run migration 001 from scratch
