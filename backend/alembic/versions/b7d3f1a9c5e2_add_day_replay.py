"""Watch your day (additive): one row per trading day's replay clips, their ping's outbox.

Revision ID: b7d3f1a9c5e2
Revises: e6b1c4d2a7f9
"""
from alembic import op
import sqlalchemy as sa

revision = "b7d3f1a9c5e2"
down_revision = "e6b1c4d2a7f9"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "day_replay" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "day_replay",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("symbols", sa.String(), nullable=True),
        sa.Column("fills", sa.Integer(), nullable=False),
        sa.Column("pings", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day"),
    )
    op.create_index("ix_day_replay_delivery", "day_replay", ["delivery"])


def downgrade():
    op.drop_table("day_replay")
