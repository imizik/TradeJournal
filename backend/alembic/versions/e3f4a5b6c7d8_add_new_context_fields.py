"""add_new_context_fields

Adds chase_score, is_above_vwap, setup_quality_score, rvol_time_adjusted,
moneyness_pct, is_itm, is_otm to fill_market_context.
Adds post_exit_mfe_15m/30m/60m, time_to_post_exit_high_minutes to trade_path_metrics.

Revision ID: e3f4a5b6c7d8
Revises: 9d1e2f3a4b5c
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "9d1e2f3a4b5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_col_if_missing(inspector, table: str, col: str, col_type):
    existing = {c["name"] for c in inspector.get_columns(table)}
    if col not in existing:
        op.add_column(table, sa.Column(col, col_type, nullable=True))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # ---- fill_market_context new columns ----
    if "fill_market_context" in existing_tables:
        for col, typ in [
            ("chase_score", sa.Float()),
            ("is_above_vwap", sa.Integer()),
            ("setup_quality_score", sa.Float()),
            ("rvol_time_adjusted", sa.Float()),
            ("moneyness_pct", sa.Float()),
            ("is_itm", sa.Integer()),
            ("is_otm", sa.Integer()),
        ]:
            _add_col_if_missing(inspector, "fill_market_context", col, typ)

    # ---- trade_path_metrics new columns ----
    if "trade_path_metrics" in existing_tables:
        for col, typ in [
            ("post_exit_mfe_15m", sa.Float()),
            ("post_exit_mfe_30m", sa.Float()),
            ("post_exit_mfe_60m", sa.Float()),
            ("time_to_post_exit_high_minutes", sa.Integer()),
        ]:
            _add_col_if_missing(inspector, "trade_path_metrics", col, typ)


def downgrade() -> None:
    # SQLite does not support DROP COLUMN in older versions; skip for safety.
    pass
