import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Column, Index, Numeric, Text, UniqueConstraint, text
from sqlalchemy.orm import defer
from sqlmodel import Field, Relationship, SQLModel

DECIMAL_18_6 = Numeric(18, 6)
DECIMAL_18_4 = Numeric(18, 4)


class Account(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    type: str   # "roth_ira"
    last4: str = Field(index=True, unique=True)  # "8267"

    # Broker linkage (additive; nullable). Populated for non-Robinhood ingest
    # paths such as Webull where account identity is an opaque broker id, not
    # a 4-digit suffix. Robinhood fills leave these NULL.
    broker: Optional[str] = Field(default=None, index=True)              # "robinhood" | "webull" | ...
    broker_account_id: Optional[str] = Field(default=None, index=True)   # raw broker account id

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


class FillOut(SQLModel):
    """API shape for a fill without the raw-email payload columns.

    Endpoints return this instead of ``Fill`` so response serialization never
    touches the deferred ``email_subject``/``email_body_text`` attributes —
    each access would lazy-load a full email body per row.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    instrument_type: str
    side: str
    contracts: float
    price: float
    executed_at: datetime
    raw_email_id: str
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[date] = None
    iv_at_fill: Optional[float] = None
    delta_at_fill: Optional[float] = None
    iv_rank_at_fill: Optional[float] = None
    underlying_price_at_fill: Optional[float] = None
    gamma_at_fill: Optional[float] = None
    theta_at_fill: Optional[float] = None
    vega_at_fill: Optional[float] = None
    sma_20_at_fill: Optional[float] = None
    ema_20_at_fill: Optional[float] = None
    rsi_14_at_fill: Optional[float] = None
    macd_at_fill: Optional[float] = None
    macd_signal_at_fill: Optional[float] = None
    vwap_at_fill: Optional[float] = None
    ema_9_at_fill: Optional[float] = None
    sma_50_at_fill: Optional[float] = None
    ema_9h_at_fill: Optional[float] = None


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


class ResearchWorkspace(SQLModel, table=True):
    """Durable editable state for a research module (e.g. the AI Buildout
    cockpit). Single-user, local-first: the whole workspace is one JSON blob
    plus a monotonically increasing ``revision`` used for optimistic-concurrency
    checks on save. ``schema_version`` tracks the seed shape so newer seed
    defaults can be deep-merged into saved data without clobbering user edits."""

    __tablename__ = "research_workspace"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(index=True, unique=True)          # "ai-buildout"
    schema_version: int = Field(default=1)
    data_json: str = Field(sa_column=Column(Text, nullable=False))
    revision: int = Field(default=0)                    # bumped on every save
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyDefinition(SQLModel, table=True):
    """Named Pine strategy whose code and assumptions evolve through versions."""

    __tablename__ = "strategy_definition"
    __table_args__ = (
        UniqueConstraint("name", name="uq_strategy_definition_name"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    setup_type: str = Field(default="custom", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyVersion(SQLModel, table=True):
    """Immutable-after-use Pine source plus the hypothesis and test assumptions."""

    __tablename__ = "strategy_version"
    __table_args__ = (
        UniqueConstraint(
            "strategy_definition_id",
            "version_label",
            name="uq_strategy_version_definition_label",
        ),
        CheckConstraint(
            "status IN ('draft', 'challenger', 'champion', 'shadow', 'retired')",
            name="ck_strategy_version_status",
        ),
        CheckConstraint(
            "parent_version_id IS NULL OR parent_version_id <> id",
            name="ck_strategy_version_not_own_parent",
        ),
        CheckConstraint("pyramiding >= 0", name="ck_strategy_version_pyramiding"),
        Index(
            "uq_strategy_version_one_champion",
            "strategy_definition_id",
            unique=True,
            sqlite_where=text("status = 'champion'"),
            postgresql_where=text("status = 'champion'"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    strategy_definition_id: uuid.UUID = Field(
        foreign_key="strategy_definition.id", index=True
    )
    parent_version_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="strategy_version.id", index=True
    )
    version_label: str
    pine_source: str = Field(sa_column=Column(Text, nullable=False))
    source_fingerprint: str = Field(index=True)
    source_reference: Optional[str] = None
    change_summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    hypothesis: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    parameters_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    entry_rule_summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    exit_rule_summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    execution_timing: str = "unknown"  # bar_close|next_bar|intrabar|unknown
    session_mode: str = "regular"      # regular|extended|custom
    commission_type: str = "none"
    commission_value: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    slippage_type: str = "none"
    slippage_value: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    pyramiding: int = 0
    known_limitations: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    repainting_risk_notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    lookahead_risk_notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(default="draft", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyRun(SQLModel, table=True):
    """One TradingView backtest tied to the exact StrategyVersion that produced it."""

    __tablename__ = "strategy_run"
    __table_args__ = (
        UniqueConstraint(
            "strategy_version_id",
            "source_sha256",
            name="uq_strategy_run_version_source_sha256",
        ),
        CheckConstraint("pyramiding >= 0", name="ck_strategy_run_pyramiding"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    strategy_version_id: uuid.UUID = Field(foreign_key="strategy_version.id", index=True)
    version_fingerprint: str = Field(index=True)
    source: str = Field(default="tradingview", index=True)
    symbol: str = Field(index=True)
    timeframe: str
    source_timezone: str
    backtest_start: Optional[date] = None
    backtest_end: Optional[date] = None
    initial_capital: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    currency: str = "USD"
    commission_type: str = "none"
    commission_value: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    slippage_type: str = "none"
    slippage_value: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    execution_timing: str = "unknown"
    session_mode: str = "regular"
    extended_hours: bool = False
    pyramiding: int = 0
    parameters_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    source_file_name: Optional[str] = None
    source_sha256: Optional[str] = Field(default=None, index=True)
    source_headers_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    source_mapping_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    source_warnings_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    source_csv_text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    imported_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyRunTrade(SQLModel, table=True):
    """A simulated trade reconstructed from a TradingView Entry/Exit row pair."""

    __tablename__ = "strategy_run_trade"
    __table_args__ = (
        UniqueConstraint("run_id", "trade_number", name="uq_strategy_run_trade_number"),
        CheckConstraint("direction IN ('long', 'short')", name="ck_strategy_run_trade_direction"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="strategy_run.id", index=True)
    trade_number: int
    direction: str = Field(index=True)
    entry_at: Optional[datetime] = Field(default=None, index=True)
    exit_at: Optional[datetime] = Field(default=None, index=True)
    entry_at_raw: Optional[str] = None
    exit_at_raw: Optional[str] = None
    entry_price: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    exit_price: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    quantity: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    net_pnl: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    return_pct: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    mfe: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    mfe_pct: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    mae: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    mae_pct: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    cumulative_pnl: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    cumulative_return_pct: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    duration_bars: Optional[int] = None
    duration_minutes: Optional[int] = None
    entry_signal: Optional[str] = None
    exit_signal: Optional[str] = None
    entry_comment: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    exit_comment: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    feature_snapshot_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    raw_entry_row_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    raw_exit_row_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StrategyRunMetrics(SQLModel, table=True):
    """Versioned, recalculable summary derived from StrategyRunTrade rows."""

    __tablename__ = "strategy_run_metrics"

    run_id: uuid.UUID = Field(primary_key=True, foreign_key="strategy_run.id")
    calculation_version: str
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
    trade_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    average_winner: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    average_loser: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    payoff_ratio: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    expectancy: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    profit_factor: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    total_net_pnl: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    net_return_pct: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    max_drawdown: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    max_drawdown_pct: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    average_mfe: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    median_mfe: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    average_mae: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    median_mae: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    average_holding_minutes: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    top_1_profit_contribution_pct: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    top_3_profit_contribution_pct: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    top_5_profit_contribution_pct: Optional[Decimal] = Field(
        default=None, sa_column=Column(DECIMAL_18_6, nullable=True)
    )
    long_summary_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    short_summary_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    time_bucket_summary_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    coverage_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    equity_curve_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    drawdown_curve_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    findings_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))


class StrategyExperiment(SQLModel, table=True):
    """Lightweight record of a controlled baseline/challenger hypothesis."""

    __tablename__ = "strategy_experiment"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'running', 'passed', 'failed', 'inconclusive', 'deployed')",
            name="ck_strategy_experiment_status",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    strategy_definition_id: uuid.UUID = Field(
        foreign_key="strategy_definition.id", index=True
    )
    baseline_version_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="strategy_version.id", index=True
    )
    challenger_version_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="strategy_version.id", index=True
    )
    baseline_run_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="strategy_run.id", index=True
    )
    challenger_run_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="strategy_run.id", index=True
    )
    title: str
    hypothesis: str = Field(sa_column=Column(Text, nullable=False))
    variable_changed: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    expected_effect: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    training_start: Optional[date] = None
    training_end: Optional[date] = None
    validation_start: Optional[date] = None
    validation_end: Optional[date] = None
    test_start: Optional[date] = None
    test_end: Optional[date] = None
    status: str = Field(default="proposed", index=True)
    conclusion: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    metrics_snapshot_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
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

    # Trader-state sequence metrics at fill time, derived from the journal's
    # own fill/trade history (no external data). Same-day, same-account scope.
    entries_today_before: Optional[int] = None       # entry fills earlier the same day
    trades_closed_today_before: Optional[int] = None # trades already closed that day
    realized_pnl_today_before: Optional[float] = None  # sum of those trades' PnL
    loss_streak_today_before: Optional[int] = None   # consecutive losses ending at last close
    minutes_since_last_exit: Optional[int] = None    # since last same-day trade close
    open_positions_count: Optional[int] = None       # other trades open at fill time
    is_reentry_after_loss: Optional[int] = None      # same ticker lost within prior 60m


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
    option_peak_unrealized_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    option_worst_unrealized_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    option_giveback_from_peak: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))

    # ATR-normalized excursions: MFE/MAE as multiples of the entry-day ATR%
    # (ATR from the last completed daily bar / entry price), so a 1% move on a
    # quiet mega-cap and a volatile small-cap are comparable.
    mfe_atr_multiple: Optional[float] = None
    mae_atr_multiple: Optional[float] = None

    # First-order greeks PnL attribution (options only, dollars, position-signed):
    # realized_pnl ≈ delta + gamma + theta + vega + residual. Computed from the
    # entry fill's Black-Scholes greeks and entry/exit IV; residual absorbs
    # higher-order terms, intraday path effects, and spread/slippage.
    attr_delta_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    attr_gamma_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    attr_theta_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    attr_vega_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    attr_residual_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    entry_iv: Optional[float] = None          # BS implied vol at entry fill (decimal)
    exit_iv: Optional[float] = None           # BS implied vol at last exit fill (decimal)

    # Hash of the trade's inputs (status + fills) when these metrics were
    # computed. A rebuild reuses this row only when the rebuilt trade's
    # fingerprint still matches; otherwise the row is dropped and recomputed.
    inputs_fingerprint: Optional[str] = Field(default=None, index=True)


class WebullRawEvent(SQLModel, table=True):
    """
    Raw Webull trade-event payload, stored before any normalization attempt.

    The envelope `id` from Webull is the natural idempotency key — repeated
    deliveries hit the primary key and are short-circuited. Normalization
    (Fill creation) only runs after the raw save succeeds.
    """
    __tablename__ = "webull_raw_event"

    event_id: str = Field(primary_key=True)                    # envelope "id"
    event_type: str = Field(index=True)                        # "TRADE" | other
    scene_type: Optional[str] = Field(default=None, index=True)  # "FILLED" | "FINAL_FILLED" | other
    order_status: Optional[str] = None                         # e.g. "PARTIAL_FILLED"
    account_id: Optional[str] = Field(default=None, index=True)
    client_order_id: Optional[str] = Field(default=None, index=True)
    symbol: Optional[str] = None
    category: Optional[str] = None                             # "US_STOCK" | "US_OPTION" | ...
    received_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    filled_time: Optional[datetime] = None
    payload_json: str = Field(sa_column=Column(Text, nullable=False))

    # Set True once we've routed the event (either normalized into a Fill,
    # or explicitly decided it does not need to become a Fill).
    normalized: bool = Field(default=False, index=True)
    fill_id: Optional[uuid.UUID] = Field(default=None, foreign_key="fill.id")
    normalize_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    normalize_reason: Optional[str] = None                     # "fill" | "non_trade" | "non_execution" | "duplicate" | "error"


# Loader options for bulk Fill queries: skip the legacy raw-email payload
# columns (write-only history; nothing reads them back). Keeps multi-KB email
# bodies per row off the wire — metered egress on hosted Postgres. Every
# multi-row `select(Fill)` should pass `.options(*FILL_LIGHT)`.
# Defined last: touching Fill's instrumented attributes configures the mappers,
# which requires every related model above to exist already.
FILL_LIGHT = (defer(Fill.email_subject), defer(Fill.email_body_text))
STRATEGY_VERSION_LIGHT = (defer(StrategyVersion.pine_source),)
STRATEGY_RUN_LIGHT = (
    defer(StrategyRun.source_csv_text),
    defer(StrategyRun.source_headers_json),
    defer(StrategyRun.source_mapping_json),
    defer(StrategyRun.source_warnings_json),
    defer(StrategyRun.notes),
)
STRATEGY_RUN_DETAIL_LIGHT = (
    defer(StrategyRun.source_csv_text),
    defer(StrategyRun.source_headers_json),
    defer(StrategyRun.source_mapping_json),
    defer(StrategyRun.source_warnings_json),
)
STRATEGY_RUN_TRADE_LIGHT = (
    defer(StrategyRunTrade.entry_comment),
    defer(StrategyRunTrade.exit_comment),
    defer(StrategyRunTrade.feature_snapshot_json),
    defer(StrategyRunTrade.raw_entry_row_json),
    defer(StrategyRunTrade.raw_exit_row_json),
)
