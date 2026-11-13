"""A pre-trade plan's optional profit target (additive): the underlying's price the plan aims for, as its invalidation
is one. Nullable, no default and no backfill: every existing plan keeps no target and reads exactly as before.

Revision ID: d7f3b9e5a1c8
Revises: b4e8d2a6c1f3
"""
from alembic import op
import sqlalchemy as sa

revision = "d7f3b9e5a1c8"
down_revision = "b4e8d2a6c1f3"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "target_price" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("trade_capture")}:
        op.add_column("trade_capture", sa.Column("target_price", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("trade_capture", "target_price")
