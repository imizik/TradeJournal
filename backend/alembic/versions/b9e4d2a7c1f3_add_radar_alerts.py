"""Radar phone alerts (additive): the at-most-once outbox for Radar event pings.

Revision ID: b9e4d2a7c1f3
Revises: e5a9c3d7f2b4
"""
from alembic import op
import sqlalchemy as sa

revision = "b9e4d2a7c1f3"
down_revision = "e5a9c3d7f2b4"
branch_labels = None
depends_on = None


def upgrade():
    # A new table only: existing tables and rows stay unchanged (and the create_all-before-upgrade path is tolerated).
    if "radar_alert" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "radar_alert",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("session_date", sa.String(), nullable=False),
        sa.Column("rule_version", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_radar_alert_event"),
    )
    op.create_index("ix_radar_alert_event_id", "radar_alert", ["event_id"])
    op.create_index("ix_radar_alert_session_date", "radar_alert", ["session_date"])
    op.create_index("ix_radar_alert_subject", "radar_alert", ["subject"])
    op.create_index("ix_radar_alert_delivery", "radar_alert", ["delivery"])


def downgrade():
    op.drop_table("radar_alert")
