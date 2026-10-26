"""Notification policy (additive): one row per copilot-side phone ping and its decision.

Revision ID: f3b7d1e9a2c4
Revises: f3b9d7e1a4c6
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b7d1e9a2c4"
down_revision = "f3b9d7e1a4c6"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "phone_ping" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "phone_ping",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("anchor", sa.String(), nullable=True),
        sa.Column("trade_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("merged_into", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("then", sa.String(), nullable=True),
        sa.Column("then_minutes", sa.Integer(), nullable=True),
        sa.Column("judged_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sender", "source_id", name="uq_phone_ping_source"),
    )
    op.create_index("ix_phone_ping_anchor", "phone_ping", ["anchor"])
    op.create_index("ix_phone_ping_decision", "phone_ping", ["decision"])
    op.create_index("ix_phone_ping_decided_at", "phone_ping", ["decided_at"])


def downgrade():
    op.drop_table("phone_ping")
