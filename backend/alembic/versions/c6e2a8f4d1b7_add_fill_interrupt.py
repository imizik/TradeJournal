"""Fill-time pattern interrupts (additive: a new table).

Revision ID: c6e2a8f4d1b7
Revises: fa98b2a82e10
"""
from alembic import op
import sqlalchemy as sa

revision = "c6e2a8f4d1b7"
down_revision = "fa98b2a82e10"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "fill_interrupt" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "fill_interrupt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("fill_key", sa.String(), nullable=False),
        sa.Column("position_key", sa.String(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("contract", sa.String(), nullable=False),
        sa.Column("kinds", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("noted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "fill_key", name="uq_fill_interrupt_fill"),
    )
    op.create_index("ix_fill_interrupt_fill_key", "fill_interrupt", ["fill_key"])
    op.create_index("ix_fill_interrupt_position_key", "fill_interrupt", ["position_key"])
    op.create_index("ix_fill_interrupt_delivery", "fill_interrupt", ["delivery"])


def downgrade():
    op.drop_table("fill_interrupt")
