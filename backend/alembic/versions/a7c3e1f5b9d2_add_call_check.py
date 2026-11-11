"""Checked calls (additive): one row per trade call the owner shared to be checked, with the price at the check.

Revision ID: a7c3e1f5b9d2
Revises: f6b2c8d4a1e7
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c3e1f5b9d2"
down_revision = "f6b2c8d4a1e7"
branch_labels = None
depends_on = None


def upgrade():
    # A new table only: existing tables and rows stay unchanged (and the create_all-before-upgrade path is tolerated).
    if "call_check" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "call_check",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("reading_json", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("card_json", sa.Text(), nullable=False),
        sa.Column("underlying_price", sa.Float(), nullable=True),
        sa.Column("quote_json", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("outcome_at", sa.DateTime(), nullable=True),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_call_check_checked_at", "call_check", ["checked_at"])
    op.create_index("ix_call_check_day", "call_check", ["day"])
    op.create_index("ix_call_check_symbol", "call_check", ["symbol"])


def downgrade():
    op.drop_table("call_check")
