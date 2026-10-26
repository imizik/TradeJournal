"""Copilot turn log (additive): each turn's model and estimated cost, for the daily API budget.

Revision ID: e6b1c4d2a7f9
Revises: d2a7e5c9f3b1
"""
from alembic import op
import sqlalchemy as sa

revision = "e6b1c4d2a7f9"
down_revision = "d2a7e5c9f3b1"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "copilot_turn" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "copilot_turn",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("backend", sa.String(), nullable=False),
        sa.Column("billing", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(18, 6), nullable=False),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_copilot_turn_started_at", "copilot_turn", ["started_at"])


def downgrade():
    op.drop_index("ix_copilot_turn_started_at", table_name="copilot_turn")
    op.drop_table("copilot_turn")
