"""add_path_metrics_fingerprint

Revision ID: c7d8e9f0a1b2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trade_path_metrics" not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns("trade_path_metrics")}
    if "inputs_fingerprint" not in existing:
        op.add_column(
            "trade_path_metrics",
            sa.Column("inputs_fingerprint", sa.String(), nullable=True),
        )
        op.create_index(
            "ix_trade_path_metrics_inputs_fingerprint",
            "trade_path_metrics",
            ["inputs_fingerprint"],
        )


def downgrade() -> None:
    # SQLite does not support DROP COLUMN in older versions; skip for safety.
    pass
