"""Unplanned-entry phone nudges (additive: a new table).

Revision ID: b2c9e4f7a1d3
Revises: e5a1c7d9b3f2
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c9e4f7a1d3"
down_revision = "e5a1c7d9b3f2"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "plan_nudge" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "plan_nudge",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("contract", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("contracts", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "source_key", name="uq_plan_nudge_position"),
    )
    op.create_index("ix_plan_nudge_source_key", "plan_nudge", ["source_key"])
    op.create_index("ix_plan_nudge_delivery", "plan_nudge", ["delivery"])


def downgrade():
    op.drop_table("plan_nudge")
