"""Frozen optional since-entry context on existing position alerts.

Revision ID: 7c3e0a5b2d84
Revises: 6b2f9d4a1c73
"""
from alembic import op
import sqlalchemy as sa

revision = "7c3e0a5b2d84"
down_revision = "6b2f9d4a1c73"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "context_snapshot_json" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("position_alert")}:
        op.add_column("position_alert", sa.Column("context_snapshot_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("position_alert", "context_snapshot_json")
