"""add_job_progress_telemetry

Revision ID: 4c8e2a7d9b10
Revises: 2e6f9a1b4c7d
Create Date: 2026-09-15 22:00:00.000000

Adds durable phase and API-wait state so a sync UI can distinguish useful
work from intentional provider pacing or retry backoff.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c8e2a7d9b10"
down_revision: Union[str, None] = "2e6f9a1b4c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job_run" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("job_run")}
    for name, column_type in (
        ("phase", sa.String()),
        ("wait_provider", sa.String()),
        ("wait_reason", sa.String()),
        ("wait_until", sa.DateTime()),
    ):
        if name not in existing:
            op.add_column("job_run", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    # Existing additive revisions deliberately leave SQLite columns in place.
    # Dropping nullable observability fields is not worth a table recreation.
    pass
