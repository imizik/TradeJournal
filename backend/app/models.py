import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, Numeric, Text
from sqlmodel import Field, Relationship, SQLModel

DECIMAL_18_6 = Numeric(18, 6)
DECIMAL_18_4 = Numeric(18, 4)


class Account(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    type: str   # "roth_ira"
    last4: str = Field(index=True, unique=True)  # "8267"

    fills: list["Fill"] = Relationship(back_populates="account")
    trades: list["Trade"] = Relationship(back_populates="account")


class Fill(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="account.id", index=True)
    ticker: str                  # underlying only - "NVDA" not "NVDA250328C00900000"
    instrument_type: str         # "option" | "stock"
    side: str                    # "buy_to_open" | "sell_to_close" | "buy_to_close" | "sell_to_open" | "buy" | "sell"
    contracts: float = Field(sa_column=Column(DECIMAL_18_6, nullable=False))
    price: float = Field(sa_column=Column(DECIMAL_18_6, nullable=False))
    executed_at: datetime = Field(index=True)  # tz-aware America/New_York
    raw_email_id: str = Field(index=True, unique=True)  # Gmail message ID for traceability
    # options only
    option_type: Optional[str] = None   # "call" | "put"
    strike: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    expiration: Optional[date] = None

    # Source email (populated on Gmail import, NULL for manual fills)
    email_subject: Optional[str] = None
    email_body_text: Optional[str] = None

    # Enriched after parse - all nullable, never block a fill save
    iv_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    delta_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    iv_rank_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    underlying_price_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    gamma_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    theta_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    vega_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    sma_20_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    ema_20_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    rsi_14_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    macd_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    macd_signal_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    vwap_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    ema_9_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    sma_50_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    ema_9h_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))

    account: Optional[Account] = Relationship(back_populates="fills")
    trade_fills: list["TradeFill"] = Relationship(back_populates="fill")


class Trade(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="account.id", index=True)
    ticker: str
    instrument_type: str         # "option" | "stock"
    contracts: float = Field(sa_column=Column(DECIMAL_18_6, nullable=False))
    # options only
    option_type: Optional[str] = None
    strike: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    expiration: Optional[date] = None
    avg_entry_premium: float = Field(sa_column=Column(DECIMAL_18_6, nullable=False))
    avg_exit_premium: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    total_premium_paid: float = Field(sa_column=Column(DECIMAL_18_6, nullable=False))
    realized_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    pnl_pct: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_4, nullable=True))
    hold_duration_mins: Optional[int] = None
    entry_time_bucket: Optional[str] = None  # "open" | "mid" | "close"
    expired_worthless: bool = False
    roll_group_id: Optional[uuid.UUID] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    status: str = "open"         # "open" | "closed" | "expired"
    ai_review: Optional[str] = None  # raw JSON from reviewer.py

    account: Optional[Account] = Relationship(back_populates="trades")
    trade_fills: list["TradeFill"] = Relationship(back_populates="trade")
    trade_tags: list["TradeTag"] = Relationship(back_populates="trade")


class DailyReviewRecord(SQLModel, table=True):
    __tablename__ = "dailyreview"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    day: date = Field(index=True, unique=True)
    review_json: str = Field(sa_column=Column(Text, nullable=False))
    trade_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class JobRun(SQLModel, table=True):
    """Durable status for import, enrichment, and path computation jobs."""
    __tablename__ = "job_run"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_type: str = Field(index=True)
    status: str = Field(default="queued", index=True)  # queued|running|succeeded|failed
    params_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    total: int = 0
    done: int = 0
    current: Optional[str] = None
    enriched: int = 0
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TradeFill(SQLModel, table=True):
    __tablename__ = "tradefill"
    trade_id: uuid.UUID = Field(primary_key=True, foreign_key="trade.id")
    fill_id: uuid.UUID = Field(primary_key=True, foreign_key="fill.id")
    role: str  # "entry" | "exit"

    trade: Optional[Trade] = Relationship(back_populates="trade_fills")
    fill: Optional[Fill] = Relationship(back_populates="trade_fills")


class Tag(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    source: str  # "manual" | "auto" | "ai"

    trade_tags: list["TradeTag"] = Relationship(back_populates="tag")


class TradeTag(SQLModel, table=True):
    __tablename__ = "tradetag"
    trade_id: uuid.UUID = Field(primary_key=True, foreign_key="trade.id")
    tag_id: uuid.UUID = Field(primary_key=True, foreign_key="tag.id")

    trade: Optional[Trade] = Relationship(back_populates="trade_tags")
    tag: Optional[Tag] = Relationship(back_populates="trade_tags")


class FillMarketContext(SQLModel, table=True):
    """Alpaca-derived market context for a single fill. One row per fill."""
    __tablename__ = "fill_market_context"

    fill_id: uuid.UUID = Field(primary_key=True, foreign_key="fill.id")
    data_source: str                        # alpaca_iex | alpaca_sip
    fetched_at: datetime

    # Underlying price at fill time (from minute bars)
    entry_underlying_price: Optional[float] = None
    entry_vwap: Optional[float] = None      # cumulative RTH VWAP at fill time
    entry_vs_vwap_pct: Optional[float] = None
    entry_volume: Optional[int] = None      # volume of the fill's minute bar
    cumulative_volume_at_entry: Optional[int] = None
    avg_daily_volume_20: Optional[float] = None
    simple_relative_volume: Optional[float] = None

    # Daily indicators (from daily bars, locally computed)
    entry_sma_20: Optional[float] = None
    entry_sma_50: Optional[float] = None
    entry_ema_9: Optional[float] = None
    entry_ema_20: Optional[float] = None
    entry_rsi_14: Optional[float] = None
    entry_macd: Optional[float] = None
    entry_macd_signal: Optional[float] = None
    entry_macd_histogram: Optional[float] = None
    entry_atr_14: Optional[float] = None
    entry_vs_ema9_pct: Optional[float] = None
    entry_vs_ema20_pct: Optional[float] = None

    # Intraday structure (from minute bars)
    entry_day_high_so_far: Optional[float] = None
    entry_day_low_so_far: Optional[float] = None
    entry_day_range_used_pct: Optional[float] = None
    entry_distance_from_day_high_pct: Optional[float] = None
    entry_distance_from_day_low_pct: Optional[float] = None
    premarket_high: Optional[float] = None
    premarket_low: Optional[float] = None
    entry_distance_from_premarket_high_pct: Optional[float] = None
    entry_distance_from_premarket_low_pct: Optional[float] = None
    opening_range_5m_high: Optional[float] = None
    opening_range_5m_low: Optional[float] = None
    opening_range_15m_high: Optional[float] = None
    opening_range_15m_low: Optional[float] = None
    entry_distance_from_or5_high_pct: Optional[float] = None
    entry_distance_from_or5_low_pct: Optional[float] = None
    entry_distance_from_or15_high_pct: Optional[float] = None
    entry_distance_from_or15_low_pct: Optional[float] = None
    previous_day_high: Optional[float] = None
    previous_day_low: Optional[float] = None
    previous_day_close: Optional[float] = None
    entry_distance_from_prev_high_pct: Optional[float] = None
    entry_distance_from_prev_low_pct: Optional[float] = None
    entry_gap_pct: Optional[float] = None

    # Behavioral flags: 0/1 int (None = could not compute)
    is_chase_entry: Optional[int] = None
    chase_score: Optional[float] = None       # 0-100 continuous chase intensity
    is_trend_aligned: Optional[int] = None
    is_late_move: Optional[int] = None
    is_above_vwap: Optional[int] = None       # price on correct side of VWAP at entry
    is_vwap_reclaim: Optional[int] = None     # true reclaim: prev bar below, entry bar above
    is_opening_range_breakout: Optional[int] = None
    is_premarket_breakout: Optional[int] = None
    is_near_resistance_on_call_entry: Optional[int] = None
    is_near_support_on_put_entry: Optional[int] = None
    is_overnight: Optional[int] = None
    entry_time_bucket: Optional[str] = None   # premarket|open|mid|close|afterhours
    dte_bucket: Optional[str] = None          # 0dte|1-3dte|4-7dte|8-21dte|22+dte
    setup_quality_score: Optional[float] = None  # 0-100 aggregate setup quality

    # Relative volume (time-adjusted, uses cached minute bars only)
    rvol_time_adjusted: Optional[float] = None

    # Option moneyness at entry
    moneyness_pct: Optional[float] = None     # (underlying - strike) / strike * 100 for calls, inverted for puts
    is_itm: Optional[int] = None              # 1 if in the money at entry
    is_otm: Optional[int] = None              # 1 if out of the money at entry


class TradePathMetrics(SQLModel, table=True):
    """Underlying and option path metrics for a closed trade. One row per trade."""
    __tablename__ = "trade_path_metrics"

    trade_id: uuid.UUID = Field(primary_key=True, foreign_key="trade.id")
    data_source: str
    fetched_at: datetime

    hold_duration_bucket: Optional[str] = None  # scalp|intraday|swing|multi-day
    exit_time_bucket: Optional[str] = None       # premarket|open|mid|close|afterhours

    # Underlying path (Phase 1/3)
    underlying_mfe_pct: Optional[float] = None
    underlying_mae_pct: Optional[float] = None
    time_to_underlying_mfe_minutes: Optional[int] = None
    time_to_underlying_mae_minutes: Optional[int] = None
    underlying_exit_efficiency: Optional[float] = None
    underlying_giveback_pct: Optional[float] = None
    moved_in_favor_first: Optional[int] = None   # 1 if MFE reached before MAE

    # Post-exit continuation: how much did price move after exit?
    post_exit_mfe_15m: Optional[float] = None    # max favorable % move in 15m after exit
    post_exit_mfe_30m: Optional[float] = None    # max favorable % move in 30m after exit
    post_exit_mfe_60m: Optional[float] = None    # max favorable % move in 60m after exit
    time_to_post_exit_high_minutes: Optional[int] = None  # mins to the post-exit extreme

    # Option path (Phase 3 — all nullable until then)
    option_mfe_pct: Optional[float] = None
    option_mae_pct: Optional[float] = None
    option_max_price_seen: Optional[float] = None
    option_min_price_seen: Optional[float] = None
    time_to_option_mfe_minutes: Optional[int] = None
    option_exit_efficiency: Optional[float] = None
    option_giveback_pct: Optional[float] = None
