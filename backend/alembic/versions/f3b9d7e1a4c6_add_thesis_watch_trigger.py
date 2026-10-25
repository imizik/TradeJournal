"""Thesis watch triggers (additive: a new table).

Revision ID: f3b9d7e1a4c6
Revises: d4f8b2c6e1a9
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b9d7e1a4c6"
down_revision = "d4f8b2c6e1a9"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "thesis_watch_trigger" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "thesis_watch_trigger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=True),
        sa.Column("memory_id", sa.Uuid(), nullable=True),
        sa.Column("held", sa.Boolean(), nullable=False),
        sa.Column("day", sa.String(), nullable=False),
        sa.Column("fired_at", sa.DateTime(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("delivery", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("reassess_job_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_thesis_watch_trigger_symbol", "thesis_watch_trigger", ["symbol"])
    op.create_index("ix_thesis_watch_trigger_investigation_id", "thesis_watch_trigger", ["investigation_id"])
    op.create_index("ix_thesis_watch_trigger_day", "thesis_watch_trigger", ["day"])
    op.create_index("ix_thesis_watch_trigger_delivery", "thesis_watch_trigger", ["delivery"])


def downgrade():
    op.drop_table("thesis_watch_trigger")
