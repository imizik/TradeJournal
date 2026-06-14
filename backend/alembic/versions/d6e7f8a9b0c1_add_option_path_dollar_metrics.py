"""add_option_path_dollar_metrics

Revision ID: d6e7f8a9b0c1
Revises: b1c2d3e4f5a6
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_col_if_missing(inspector, table: str, col: str, col_type) -> None:
    existing = {c["name"] for c in inspector.get_columns(table)}
    if col not in existing:
        op.add_column(table, sa.Column(col, col_type, nullable=True))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "trade_path_metrics" not in inspector.get_table_names():
        return

    for col in [
        "option_peak_unrealized_pnl",
        "option_worst_unrealized_pnl",
        "option_giveback_from_peak",
    ]:
        _add_col_if_missing(inspector, "trade_path_metrics", col, sa.Numeric(18, 6))


def downgrade() -> None:
    # SQLite does not support DROP COLUMN in older versions; skip for safety.
    pass
