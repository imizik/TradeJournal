"""add_attribution_and_sequence_metrics

Revision ID: a4b5c6d7e8f9
Revises: e9a1b2c3d4f5
Create Date: 2026-07-06 00:00:00.000000

Adds greeks PnL attribution + ATR-normalized MFE/MAE to trade_path_metrics and
trader-state sequence metrics to fill_market_context.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "e9a1b2c3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_col_if_missing(inspector, table: str, col: str, col_type) -> None:
    existing = {c["name"] for c in inspector.get_columns(table)}
    if col not in existing:
        op.add_column(table, sa.Column(col, col_type, nullable=True))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "trade_path_metrics" in tables:
        _add_col_if_missing(inspector, "trade_path_metrics", "mfe_atr_multiple", sa.Float())
        _add_col_if_missing(inspector, "trade_path_metrics", "mae_atr_multiple", sa.Float())
        for col in [
            "attr_delta_pnl",
            "attr_gamma_pnl",
            "attr_theta_pnl",
            "attr_vega_pnl",
            "attr_residual_pnl",
        ]:
            _add_col_if_missing(inspector, "trade_path_metrics", col, sa.Numeric(18, 6))
        _add_col_if_missing(inspector, "trade_path_metrics", "entry_iv", sa.Float())
        _add_col_if_missing(inspector, "trade_path_metrics", "exit_iv", sa.Float())

    if "fill_market_context" in tables:
        for col in [
            "entries_today_before",
            "trades_closed_today_before",
            "loss_streak_today_before",
            "minutes_since_last_exit",
            "open_positions_count",
            "is_reentry_after_loss",
        ]:
            _add_col_if_missing(inspector, "fill_market_context", col, sa.Integer())
        _add_col_if_missing(
            inspector, "fill_market_context", "realized_pnl_today_before", sa.Float()
        )


def downgrade() -> None:
    # SQLite does not support DROP COLUMN in older versions; skip for safety.
    pass
