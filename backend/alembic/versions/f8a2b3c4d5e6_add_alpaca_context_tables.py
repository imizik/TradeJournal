"""add_alpaca_context_tables

Revision ID: f8a2b3c4d5e6
Revises: c4d2e9f8a731
Create Date: 2026-05-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a2b3c4d5e6"
down_revision: Union[str, None] = "c4d2e9f8a731"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_table_names()

    if "fill_market_context" not in existing:
        op.create_table(
            "fill_market_context",
            sa.Column("fill_id", sa.Uuid(), nullable=False),
            sa.Column("data_source", sa.String(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            # Underlying price context
            sa.Column("entry_underlying_price", sa.Float(), nullable=True),
            sa.Column("entry_vwap", sa.Float(), nullable=True),
            sa.Column("entry_vs_vwap_pct", sa.Float(), nullable=True),
            sa.Column("entry_volume", sa.Integer(), nullable=True),
            sa.Column("cumulative_volume_at_entry", sa.Integer(), nullable=True),
            sa.Column("avg_daily_volume_20", sa.Float(), nullable=True),
            sa.Column("simple_relative_volume", sa.Float(), nullable=True),
            # Daily indicators
            sa.Column("entry_sma_20", sa.Float(), nullable=True),
            sa.Column("entry_sma_50", sa.Float(), nullable=True),
            sa.Column("entry_ema_9", sa.Float(), nullable=True),
            sa.Column("entry_ema_20", sa.Float(), nullable=True),
            sa.Column("entry_rsi_14", sa.Float(), nullable=True),
            sa.Column("entry_macd", sa.Float(), nullable=True),
            sa.Column("entry_macd_signal", sa.Float(), nullable=True),
            sa.Column("entry_macd_histogram", sa.Float(), nullable=True),
            sa.Column("entry_atr_14", sa.Float(), nullable=True),
            sa.Column("entry_vs_ema9_pct", sa.Float(), nullable=True),
            sa.Column("entry_vs_ema20_pct", sa.Float(), nullable=True),
            # Intraday structure
            sa.Column("entry_day_high_so_far", sa.Float(), nullable=True),
            sa.Column("entry_day_low_so_far", sa.Float(), nullable=True),
            sa.Column("entry_day_range_used_pct", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_day_high_pct", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_day_low_pct", sa.Float(), nullable=True),
            sa.Column("premarket_high", sa.Float(), nullable=True),
            sa.Column("premarket_low", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_premarket_high_pct", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_premarket_low_pct", sa.Float(), nullable=True),
            sa.Column("opening_range_5m_high", sa.Float(), nullable=True),
            sa.Column("opening_range_5m_low", sa.Float(), nullable=True),
            sa.Column("opening_range_15m_high", sa.Float(), nullable=True),
            sa.Column("opening_range_15m_low", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_or5_high_pct", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_or5_low_pct", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_or15_high_pct", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_or15_low_pct", sa.Float(), nullable=True),
            sa.Column("previous_day_high", sa.Float(), nullable=True),
            sa.Column("previous_day_low", sa.Float(), nullable=True),
            sa.Column("previous_day_close", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_prev_high_pct", sa.Float(), nullable=True),
            sa.Column("entry_distance_from_prev_low_pct", sa.Float(), nullable=True),
            sa.Column("entry_gap_pct", sa.Float(), nullable=True),
            # Behavioral flags (0/1 int; None = could not compute)
            sa.Column("is_chase_entry", sa.Integer(), nullable=True),
            sa.Column("is_trend_aligned", sa.Integer(), nullable=True),
            sa.Column("is_late_move", sa.Integer(), nullable=True),
            sa.Column("is_vwap_reclaim", sa.Integer(), nullable=True),
            sa.Column("is_opening_range_breakout", sa.Integer(), nullable=True),
            sa.Column("is_premarket_breakout", sa.Integer(), nullable=True),
            sa.Column("is_near_resistance_on_call_entry", sa.Integer(), nullable=True),
            sa.Column("is_near_support_on_put_entry", sa.Integer(), nullable=True),
            sa.Column("is_overnight", sa.Integer(), nullable=True),
            sa.Column("entry_time_bucket", sa.String(), nullable=True),
            sa.Column("dte_bucket", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("fill_id"),
            sa.ForeignKeyConstraint(["fill_id"], ["fill.id"]),
        )

    if "trade_path_metrics" not in existing:
        op.create_table(
            "trade_path_metrics",
            sa.Column("trade_id", sa.Uuid(), nullable=False),
            sa.Column("data_source", sa.String(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            sa.Column("hold_duration_bucket", sa.String(), nullable=True),
            sa.Column("exit_time_bucket", sa.String(), nullable=True),
            # Underlying path metrics
            sa.Column("underlying_mfe_pct", sa.Float(), nullable=True),
            sa.Column("underlying_mae_pct", sa.Float(), nullable=True),
            sa.Column("time_to_underlying_mfe_minutes", sa.Integer(), nullable=True),
            sa.Column("time_to_underlying_mae_minutes", sa.Integer(), nullable=True),
            sa.Column("underlying_exit_efficiency", sa.Float(), nullable=True),
            sa.Column("underlying_giveback_pct", sa.Float(), nullable=True),
            sa.Column("moved_in_favor_first", sa.Integer(), nullable=True),
            # Option path metrics (Phase 3 — nullable until then)
            sa.Column("option_mfe_pct", sa.Float(), nullable=True),
            sa.Column("option_mae_pct", sa.Float(), nullable=True),
            sa.Column("option_max_price_seen", sa.Float(), nullable=True),
            sa.Column("option_min_price_seen", sa.Float(), nullable=True),
            sa.Column("time_to_option_mfe_minutes", sa.Integer(), nullable=True),
            sa.Column("option_exit_efficiency", sa.Float(), nullable=True),
            sa.Column("option_giveback_pct", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("trade_id"),
            sa.ForeignKeyConstraint(["trade_id"], ["trade.id"]),
        )


def downgrade() -> None:
    op.drop_table("trade_path_metrics")
    op.drop_table("fill_market_context")
