"""Robinhood order-history fills (additive): the executions Robinhood's order history reported, and the outcome of
pairing each order with the journal's fills (docs/robinhood-order-fills.md).

Revision ID: b4e8d2a6c1f3
Revises: a7c3e1f5b9d2
"""
from alembic import op
import sqlalchemy as sa

revision = "b4e8d2a6c1f3"
down_revision = "a7c3e1f5b9d2"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 6)


def upgrade():
    # New tables only: existing tables and rows stay unchanged (and the create_all-before-upgrade path is tolerated).
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "robinhood_execution" not in tables:
        op.create_table(
            "robinhood_execution",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("execution_id", sa.String(), nullable=False),
            sa.Column("order_id", sa.String(), nullable=False),
            sa.Column("account_last4", sa.String(), nullable=False),
            sa.Column("instrument_type", sa.String(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("side", sa.String(), nullable=False),
            sa.Column("option_type", sa.String(), nullable=True),
            sa.Column("strike", MONEY, nullable=True),
            sa.Column("expiration", sa.Date(), nullable=True),
            sa.Column("contracts", MONEY, nullable=False),
            sa.Column("price", MONEY, nullable=False),
            sa.Column("executed_at", sa.DateTime(), nullable=False),
            sa.Column("order_state", sa.String(), nullable=False),
            sa.Column("placed_agent", sa.String(), nullable=True),
            sa.Column("legs", sa.Integer(), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_robinhood_execution_execution_id", "robinhood_execution", ["execution_id"], unique=True)
        op.create_index("ix_robinhood_execution_order_id", "robinhood_execution", ["order_id"])
        op.create_index("ix_robinhood_execution_executed_at", "robinhood_execution", ["executed_at"])
    if "robinhood_reconciliation" not in tables:
        op.create_table(
            "robinhood_reconciliation",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("order_id", sa.String(), nullable=True),
            sa.Column("fill_id", sa.Uuid(), nullable=True),
            sa.Column("outcome", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("account_last4", sa.String(), nullable=False),
            sa.Column("instrument_type", sa.String(), nullable=False),
            sa.Column("ticker", sa.String(), nullable=False),
            sa.Column("side", sa.String(), nullable=False),
            sa.Column("option_type", sa.String(), nullable=True),
            sa.Column("strike", MONEY, nullable=True),
            sa.Column("expiration", sa.Date(), nullable=True),
            sa.Column("placed_agent", sa.String(), nullable=True),
            sa.Column("rh_contracts", MONEY, nullable=True),
            sa.Column("rh_price", MONEY, nullable=True),
            sa.Column("rh_first_at", sa.DateTime(), nullable=True),
            sa.Column("rh_last_at", sa.DateTime(), nullable=True),
            sa.Column("journal_source", sa.String(), nullable=True),
            sa.Column("journal_contracts", MONEY, nullable=True),
            sa.Column("journal_price", MONEY, nullable=True),
            sa.Column("journal_at", sa.DateTime(), nullable=True),
            sa.Column("journal_email_id", sa.String(), nullable=True),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_robinhood_reconciliation_key", "robinhood_reconciliation", ["key"], unique=True)
        op.create_index("ix_robinhood_reconciliation_order_id", "robinhood_reconciliation", ["order_id"])
        op.create_index("ix_robinhood_reconciliation_fill_id", "robinhood_reconciliation", ["fill_id"])
        op.create_index("ix_robinhood_reconciliation_journal_email_id", "robinhood_reconciliation", ["journal_email_id"])


def downgrade():
    op.drop_table("robinhood_reconciliation")
    op.drop_table("robinhood_execution")
