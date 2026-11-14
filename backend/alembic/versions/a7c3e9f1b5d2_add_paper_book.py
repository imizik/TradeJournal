"""The owner's own paper book (additive): ``paper_run`` (one row per run of the paper account) and ``paper_event`` (its
append-only fills). New tables only; nothing existing changes.

Revision ID: a7c3e9f1b5d2
Revises: e2c6a8f4b1d9
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c3e9f1b5d2"
down_revision = "e2c6a8f4b1d9"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "paper_run" not in tables:
        op.create_table(
            "paper_run",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("starting_cash", sa.Float(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_paper_run_started_at", "paper_run", ["started_at"])
    if "paper_event" not in tables:
        op.create_table(
            "paper_event",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("position_id", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("order_key", sa.String(), nullable=False),
            sa.Column("effective_at", sa.DateTime(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("data_json", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["paper_run.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("order_key"),
        )
        op.create_index("ix_paper_event_run_id", "paper_event", ["run_id"])
        op.create_index("ix_paper_event_position_id", "paper_event", ["position_id"])


def downgrade():
    op.drop_index("ix_paper_event_position_id", table_name="paper_event")
    op.drop_index("ix_paper_event_run_id", table_name="paper_event")
    op.drop_table("paper_event")
    op.drop_index("ix_paper_run_started_at", table_name="paper_run")
    op.drop_table("paper_run")
