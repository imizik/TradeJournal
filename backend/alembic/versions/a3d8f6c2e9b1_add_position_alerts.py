"""Open-trade phone alerts: give-back and last-day expiry.

Revision ID: a3d8f6c2e9b1
Revises: c7e2a9d4b1f8
"""
from alembic import op
import sqlalchemy as sa

revision = "a3d8f6c2e9b1"
down_revision = "c7e2a9d4b1f8"
branch_labels = None
depends_on = None


def upgrade():
    # New tables only: existing tables and rows stay unchanged.
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "position_watch" not in tables:
        op.create_table(
            "position_watch",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("account_id", sa.Uuid(), nullable=False),
            sa.Column("source_key", sa.String(), nullable=False),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("contracts", sa.Float(), nullable=False),
            sa.Column("avg_cost", sa.Float(), nullable=False),
            sa.Column("peak_mark", sa.Float(), nullable=True),
            sa.Column("peak_at", sa.DateTime(), nullable=True),
            sa.Column("armed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "source_key", name="uq_position_watch_position"),
        )
    if "position_alert" not in tables:
        op.create_table(
            "position_alert",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("account_id", sa.Uuid(), nullable=False),
            sa.Column("source_key", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("trade_id", sa.Uuid(), nullable=False),
            sa.Column("contract", sa.String(), nullable=False),
            sa.Column("contracts", sa.Float(), nullable=False),
            sa.Column("avg_cost", sa.Float(), nullable=False),
            sa.Column("mark", sa.Float(), nullable=True),
            sa.Column("bid", sa.Float(), nullable=True),
            sa.Column("gain", sa.Float(), nullable=True),
            sa.Column("gain_pct", sa.Float(), nullable=True),
            sa.Column("peak_gain", sa.Float(), nullable=True),
            sa.Column("peak_gain_pct", sa.Float(), nullable=True),
            sa.Column("quoted_at", sa.DateTime(), nullable=True),
            sa.Column("detected_at", sa.DateTime(), nullable=False),
            sa.Column("delivery", sa.String(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "source_key", "kind", "generation", name="uq_position_alert_firing"),
        )
        op.create_index("ix_position_alert_source_key", "position_alert", ["source_key"])
        op.create_index("ix_position_alert_delivery", "position_alert", ["delivery"])


def downgrade():
    op.drop_table("position_alert")
    op.drop_table("position_watch")
