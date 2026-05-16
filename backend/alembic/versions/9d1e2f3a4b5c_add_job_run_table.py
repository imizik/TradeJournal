"""add_job_run_table

Revision ID: 9d1e2f3a4b5c
Revises: f8a2b3c4d5e6
Create Date: 2026-05-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d1e2f3a4b5c"
down_revision: Union[str, None] = "f8a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job_run" in inspector.get_table_names():
        return

    op.create_table(
        "job_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("current", sa.String(), nullable=True),
        sa.Column("enriched", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_run_job_type", "job_run", ["job_type"])
    op.create_index("ix_job_run_status", "job_run", ["status"])


def downgrade() -> None:
    op.drop_index("ix_job_run_status", table_name="job_run")
    op.drop_index("ix_job_run_job_type", table_name="job_run")
    op.drop_table("job_run")
