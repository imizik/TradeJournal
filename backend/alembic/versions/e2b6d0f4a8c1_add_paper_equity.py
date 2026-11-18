"""The paper account's value once a minute (additive): ``paper_equity`` holds one row per paper run and regular-session
minute for the Paper home's portfolio graph. A new table only; nothing existing changes.

Revision ID: e2b6d0f4a8c1
Revises: d7a1c5e9b3f2
"""
from alembic import op
import sqlalchemy as sa

revision = "e2b6d0f4a8c1"
down_revision = "d7a1c5e9b3f2"
branch_labels = None
depends_on = None


def upgrade():
    # Also tolerate the existing supported create_all-before-upgrade path.
    if "paper_equity" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "paper_equity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=True),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("prices_at", sa.DateTime(), nullable=True),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["paper_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "at", name="uq_paper_equity_minute"),
    )
    op.create_index("ix_paper_equity_run_id", "paper_equity", ["run_id"])


def downgrade():
    op.drop_index("ix_paper_equity_run_id", table_name="paper_equity")
    op.drop_table("paper_equity")
