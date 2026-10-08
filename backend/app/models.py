import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import defer
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, Relationship, SQLModel

DECIMAL_18_6 = Numeric(18, 6)
DECIMAL_18_4 = Numeric(18, 4)


class ExactDecimal(TypeDecorator):
    """Store exact Decimals without SQLite's float-backed NUMERIC rounding."""

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int, scale: int) -> None:
        self.precision = precision
        self.scale = scale
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            # Includes sign, decimal point, and headroom for future bounds.
            return dialect.type_descriptor(String(48))
        return dialect.type_descriptor(Numeric(self.precision, self.scale))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        if dialect.name == "sqlite":
            return format(decimal_value, "f")
        return decimal_value

    def process_result_value(self, value, _dialect):
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))


TRADINGVIEW_PRICE = ExactDecimal(28, 12)


def utc_now_naive() -> datetime:
    """Current UTC in the repository's existing naive-datetime convention."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    executed_at: datetime = Field(index=True)  # naive America/New_York wall clock
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


class DecisionRecord(SQLModel, table=True):
    """Immutable Practice decision and the exact evidence saved with it."""

    __tablename__ = "decision_record"
    __table_args__ = (UniqueConstraint("operation_id", name="uq_decision_record_operation_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    operation_id: str = Field(index=True)
    opportunity_id: str = Field(index=True)
    actor: str = Field(index=True)  # human | agent:<stable identity>
    decision: str  # take | wait | skip
    symbol: str = Field(index=True)
    context_id: uuid.UUID = Field(foreign_key="decision_context.id", index=True)
    received_at: datetime = Field(index=True)  # UTC, set by the server
    input_cutoff: datetime  # UTC
    policy_version: str
    policy_hash: str
    evidence_json: str = Field(sa_column=Column(Text, nullable=False))
    evidence_sha256: str
    decision_json: str = Field(sa_column=Column(Text, nullable=False))
    record_sha256: str


class DecisionContext(SQLModel, table=True):
    """Durable, server-generated market packet frozen before a choice."""

    __tablename__ = "decision_context"
    __table_args__ = (UniqueConstraint("operation_id", name="uq_decision_context_operation_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    operation_id: str = Field(index=True)
    symbol: str = Field(index=True)
    captured_at: datetime = Field(index=True)
    provider: str
    data_json: str = Field(sa_column=Column(Text, nullable=False))
    context_sha256: str


class DecisionEvent(SQLModel, table=True):
    """One append-only Practice paper event for a decision record (A2).

    ``data_json`` is the economic fact the reducer (``engine/paper_execution.py``)
    returned and is never rewritten; the unique (record, key) pair keeps a retry,
    a restart or a second pass from recording it twice. The delivery columns are
    the phone outbox, operational metadata only: sending or failing to send never
    changes the event."""

    __tablename__ = "decision_event"
    __table_args__ = (
        UniqueConstraint("record_id", "key", name="uq_decision_event_key"),
        UniqueConstraint("record_id", "seq", name="uq_decision_event_seq"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    record_id: uuid.UUID = Field(foreign_key="decision_record.id", index=True)
    seq: int
    key: str
    event_type: str
    effective_at: datetime  # UTC: when the market condition or bar happened
    recorded_at: datetime  # UTC: when this server stored it
    exec_version: str
    source: str  # where the bars came from, e.g. tradier_timesales_1min
    reconstructed: bool = False  # judged well after it happened, e.g. after a restart
    data_json: str = Field(sa_column=Column(Text, nullable=False))
    delivery: str = Field(default="none", index=True)  # none | pending | sending | sent | expired
    attempts: int = 0
    next_attempt_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


class ChartSettingsRecord(SQLModel, table=True):
    """The Charts workspace every browser shares: levels, watchlist, intervals,
    indicators and layout, as one JSON document the frontend validates. The
    symbol on screen stays per device. ``revision`` is bumped on every save and
    a save based on an older revision is refused, so a phone and a desktop
    cannot silently overwrite each other. The app uses the ``default`` row."""

    __tablename__ = "chart_settings"

    name: str = Field(primary_key=True)
    data_json: str = Field(sa_column=Column(Text, nullable=False))
    revision: int = Field(default=0)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OptionChainSnapshot(SQLModel, table=True):
    """Open interest and volume for every contract of one underlying's
    expiration, as one trading session left them (Charts C4.3). Written once by
    ``engine/options_recorder.py`` and never rewritten or backfilled: open
    interest history cannot be fetched later. ``data_json`` is
    ``{"columns": [...], "rows": [[root, "C"|"P", strike, open_interest, volume]]}``
    with null where the provider gave no value."""

    __tablename__ = "option_chain_snapshot"
    __table_args__ = (
        UniqueConstraint("session_date", "underlying", "expiration", name="uq_option_chain_snapshot_session"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_date: date  # the New York trading session captured
    underlying: str
    expiration: date
    provider: str  # "tradier"
    captured_at: datetime  # UTC; when the chain was received
    last_trade_at: Optional[datetime] = None  # UTC; the chain's newest trade, so how current its volume is
    contracts: int
    data_json: str = Field(sa_column=Column(Text, nullable=False))


class OptionSnapshotDay(SQLModel, table=True):
    """What the recorder holds for one underlying and trading session:
    ``recorded`` (every expiration within the horizon), ``partial`` (some are
    missing) or ``unavailable`` (the session passed without a snapshot)."""

    __tablename__ = "option_snapshot_day"

    session_date: date = Field(primary_key=True)
    underlying: str = Field(primary_key=True)
    status: str
    expirations: int = 0  # listed within the horizon that session
    recorded: int = 0
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LevelAlert(SQLModel, table=True):
    """A price alert on the chart (Charts C5.1): one level of one symbol, made
    from a saved level, a horizontal ray or an automatic level, judged by
    ``engine/level_alert_monitor.py`` whether or not a chart is open.
    ``price`` is on the chart's split-adjusted basis as of ``created_on`` (New
    York) and moves with later splits, as a saved level does. ``direction`` is
    the move that fires it, fixed when it is armed. It fires once per arming;
    re-arming bumps ``generation``. ``checked_through`` is the end (epoch
    seconds) of the newest candle the 1-minute sweep has judged."""

    __tablename__ = "level_alert"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    symbol: str = Field(index=True)
    price: float
    created_on: date
    condition: str  # touches | crosses | closes_beyond
    interval: Optional[str] = None  # closes_beyond only: 1m ... 4h
    session: str  # regular | extended: which trades and candles count
    direction: str  # up | down
    source_kind: str  # level | drawing | auto
    source_id: Optional[str] = None
    label: str = ""
    state: str = Field(default="active", index=True)  # active | fired
    generation: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    armed_at: datetime = Field(default_factory=datetime.utcnow)  # UTC
    checked_through: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    fired_at: Optional[datetime] = None  # UTC


class LevelAlertEvent(SQLModel, table=True):
    """One firing of a level alert, written once: the unique (alert, generation)
    pair is what keeps a reconnect, a restart or a second detector from
    recording it twice. Delivery to the phone is an outbox on the same row,
    retried until sent, and is at-least-once: a crash between ntfy accepting
    the message and this row saying so sends it again."""

    __tablename__ = "level_alert_event"
    __table_args__ = (
        UniqueConstraint("alert_id", "generation", name="uq_level_alert_event_firing"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    alert_id: uuid.UUID = Field(sa_column=Column(Uuid, ForeignKey("level_alert.id", ondelete="CASCADE"), nullable=False, index=True))
    generation: int
    level: float  # the alert's price on the basis of the day it fired
    price: float  # the trade, the bar's extreme, or the candle's close
    source: str  # stream | minute_bars | closed_bar
    event_at: datetime  # UTC: the trade, the minute, or the candle's close
    bar_time: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))  # epoch start of the candle or minute, when a bar fired it
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    delivery: str = Field(default="pending", index=True)  # pending | sending | sent | expired
    attempts: int = 0
    next_attempt_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    last_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


class CaptureTemplate(SQLModel, table=True):
    """A favorite pre-trade template (Charts C3.4): the user's setup label and
    their own invalidation/exit wording. Editing bumps ``revision``; a capture
    keeps its own copy of the wording, so an edit never changes an old plan.
    Removing one archives it."""

    __tablename__ = "capture_template"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    position: int = 0
    setup_label: str
    wording: str = Field(sa_column=Column(Text, nullable=False))
    revision: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    archived_at: Optional[datetime] = None


class CaptureProfile(SQLModel, table=True):
    """The one-time capture setup (Charts C3.4): one row, ``id`` 1."""

    __tablename__ = "capture_profile"

    id: int = Field(default=1, primary_key=True)
    default_account_id: Optional[uuid.UUID] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    # Capture adherence (C3.6): counted for trades entered from this moment (UTC), in these accounts (a JSON list of ids).
    tracking_since: Optional[datetime] = None
    tracking_accounts: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


class TradeCapture(SQLModel, table=True):
    """Intent recorded before a trade (Charts C3.4, C3.5): the user's own
    record, never a field on a rebuildable trade. What was submitted is never
    edited afterwards; corrections and reflections are ``TradeCaptureNote``
    rows. ``received_at`` (UTC) is when the server durably held the complete
    intent: the template or text, or the whole audio file. ``client_captured_at``
    is the browser's clock, kept for late uploads and never trusted as proof.
    Audio and the chart image are files in private storage
    (``engine/captures.py``); these rows hold their metadata."""

    __tablename__ = "trade_capture"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_trade_capture_client_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    client_id: str  # idempotency key from the browser: a retry never makes a second capture
    received_at: datetime = Field(index=True)  # UTC
    client_captured_at: Optional[datetime] = None  # UTC, unverified
    account_id: uuid.UUID = Field(index=True)
    account_label: str  # as the account was named when captured
    underlying: str = Field(index=True)
    side: str  # buy_calls | buy_puts | buy_stock | short_stock | sell_calls | sell_puts
    instrument: str  # option | stock
    mode: str  # template | discretionary | voice
    template_id: Optional[uuid.UUID] = None
    template_revision: Optional[int] = None
    setup_label: Optional[str] = None  # copied from the template when captured
    wording: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    # Optional exact contract and sizing; absence is never filled in by a guess.
    strike: Optional[float] = None
    expiration: Optional[date] = None
    quantity: Optional[float] = None
    context_state: str  # captured | unavailable
    context_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    image_state: str  # pending | saved | unavailable
    image_type: Optional[str] = None
    image_bytes: Optional[int] = None
    image_note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    image_received_at: Optional[datetime] = None
    audio_type: Optional[str] = None
    audio_bytes: Optional[int] = None
    audio_ms: Optional[int] = None
    audio_sha256: Optional[str] = None
    transcript_status: Optional[str] = None  # pending | transcribing | ready | failed | not_configured
    transcript_text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    transcript_provider: Optional[str] = None
    transcript_error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    transcribed_at: Optional[datetime] = None
    transcript_job_id: Optional[uuid.UUID] = None
    not_taken_at: Optional[datetime] = None  # "Did not take trade"


class CaptureLink(SQLModel, table=True):
    """A capture linked to the trade it was for (Charts C3.6), anchored in the
    source identity of that trade's first entry fill (account plus the fill's
    dedupe key), never in the trade id alone: trades are rebuilt. The trade is
    resolved through that fill's link on every read; a fill that disappears
    leaves the link unresolved, never pointing at another trade. Links are
    append-only history: unlinking stamps ``unlinked_at`` and a new link is a
    new row. Linking never changes the capture or its time."""

    __tablename__ = "capture_link"
    # One active link per plan and per anchor fill, held by the database, so two devices linking at once cannot both win.
    __table_args__ = (
        Index("uq_capture_link_active_capture", "capture_id", unique=True,
              sqlite_where=text("unlinked_at IS NULL"), postgresql_where=text("unlinked_at IS NULL")),
        Index("uq_capture_link_active_source", "account_id", "source_key", unique=True,
              sqlite_where=text("unlinked_at IS NULL"), postgresql_where=text("unlinked_at IS NULL")),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    capture_id: uuid.UUID = Field(sa_column=Column(Uuid, ForeignKey("trade_capture.id"), nullable=False, index=True))
    account_id: uuid.UUID
    source_key: str = Field(index=True)  # Fill.raw_email_id of the trade's first entry when linked
    method: str  # suggested | manual
    linked_at: datetime = Field(default_factory=datetime.utcnow)  # UTC
    unlinked_at: Optional[datetime] = None  # UTC


class TradeCaptureNote(SQLModel, table=True):
    """Something added to a capture later, never replacing it: a transcript
    correction or a reflection. Always shown as written after the capture."""

    __tablename__ = "trade_capture_note"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    capture_id: uuid.UUID = Field(sa_column=Column(Uuid, ForeignKey("trade_capture.id"), nullable=False, index=True))
    kind: str  # transcript_correction | note
    text: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)


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
    owner_id: Optional[str] = None
    owner_host: Optional[str] = None
    owner_lock_dir: Optional[str] = None
    params_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    total: int = 0
    done: int = 0
    current: Optional[str] = None
    enriched: int = 0
    phase: Optional[str] = None
    wait_provider: Optional[str] = None
    wait_reason: Optional[str] = None
    wait_until: Optional[datetime] = None
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
    calculation_version: Optional[str] = None
    entry_context_as_of: Optional[datetime] = None  # last completed minute end, NY wall time

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
    calculation_version: Optional[str] = None
    market_inputs_fingerprint: Optional[str] = None
    option_path_quality: Optional[str] = None
    option_peak_total_pnl: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))

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


class TradingViewAlert(SQLModel, table=True):
    """One immutable TradingView delivery plus its best-effort analysis state.

    Live signals are an isolated decision-support domain: this model has no
    relationship to journal fills/trades or Strategy Lab simulations. The
    canonical ``alert_id`` is the idempotency key; duplicate/collision
    classification belongs in the persistence service, not in extra database
    uniqueness constraints.
    """

    __tablename__ = "tradingview_alert"
    __table_args__ = (
        CheckConstraint(
            "contract_version >= 1",
            name="ck_tradingview_alert_contract_version",
        ),
        CheckConstraint(
            "side IN ('long', 'short')",
            name="ck_tradingview_alert_side",
        ),
        CheckConstraint(
            "CAST(price AS NUMERIC) > 0",
            name="ck_tradingview_alert_price_positive",
        ),
        CheckConstraint(
            "analysis_attempts >= 0",
            name="ck_tradingview_alert_analysis_attempts",
        ),
        CheckConstraint(
            "analysis_status IN ('pending', 'running', 'done', 'skipped', 'error')",
            name="ck_tradingview_alert_analysis_status",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN "
            "('no_trade', 'wait', 'long_scalp', 'short_scalp')",
            name="ck_tradingview_alert_verdict",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
            name="ck_tradingview_alert_confidence",
        ),
        CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_tradingview_alert_content_sha256",
        ),
        CheckConstraint(
            "length(raw_payload_sha256) = 64",
            name="ck_tradingview_alert_raw_payload_sha256",
        ),
        CheckConstraint(
            "contract_version <> 1 OR "
            "(bar_time_ms >= 946684800000 AND bar_time_ms < 4102444800000)",
            name="ck_tradingview_alert_v1_bar_time",
        ),
        CheckConstraint(
            "contract_version <> 1 OR "
            "(length(alert_id) <= 200 "
            "AND length(indicator_version) <= 32 "
            "AND length(symbol) <= 32 "
            "AND length(timeframe) <= 16 "
            "AND length(setup) <= 64)",
            name="ck_tradingview_alert_v1_text_bounds",
        ),
        Index("ix_tradingview_alert_received_at", "received_at"),
        Index("ix_tradingview_alert_bar_time", "bar_time"),
        Index(
            "ix_tradingview_alert_symbol_received_at",
            "symbol",
            "received_at",
        ),
        Index(
            "ix_tradingview_alert_setup_received_at",
            "setup",
            "received_at",
        ),
        Index(
            "ix_tradingview_alert_analysis_status_updated_at",
            "analysis_status",
            "updated_at",
        ),
    )

    alert_id: str = Field(
        sa_column=Column(String(200), primary_key=True, nullable=False)
    )
    contract_version: int
    parser_revision: str = Field(
        sa_column=Column(String(64), nullable=False)
    )
    indicator_version: str = Field(
        sa_column=Column(String(32), nullable=False)
    )
    content_sha256: str = Field(
        sa_column=Column(String(64), nullable=False)
    )
    raw_payload_sha256: str = Field(
        sa_column=Column(String(64), nullable=False)
    )

    symbol: str = Field(sa_column=Column(String(32), nullable=False))
    timeframe: str = Field(sa_column=Column(String(16), nullable=False))
    setup: str = Field(sa_column=Column(String(64), nullable=False))
    side: str = Field(sa_column=Column(String(5), nullable=False))
    price: Decimal = Field(sa_column=Column(TRADINGVIEW_PRICE, nullable=False))
    bar_time_ms: int = Field(sa_column=Column(BigInteger, nullable=False))
    # UTC-naive by repository convention; bar_time_ms remains authoritative.
    bar_time: datetime = Field(sa_column=Column(DateTime, nullable=False))

    received_at: datetime = Field(
        default_factory=utc_now_naive,
        sa_column=Column(DateTime, nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now_naive,
        sa_column=Column(DateTime, nullable=False),
    )

    # Exact decoded UTF-8 body is immutable audit evidence. Normalized fields
    # above drive reads and analysis; this is never fed to a future generic
    # parser.
    payload_json: str = Field(sa_column=Column(Text, nullable=False))
    levels_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    context_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))

    analysis_status: str = "pending"
    analysis_attempts: int = 0
    analysis_started_at: Optional[datetime] = None
    analysis_completed_at: Optional[datetime] = None
    # Deliberately separate from wire contract and Pine indicator versions.
    scorer_revision: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    verdict: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    confidence: Optional[str] = Field(
        default=None,
        sa_column=Column(String(16), nullable=True),
    )
    assessment_json: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    analysis_error_code: Optional[str] = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    analysis_error: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )


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
TRADINGVIEW_ALERT_LIGHT = (
    defer(TradingViewAlert.payload_json),
    defer(TradingViewAlert.levels_json),
    defer(TradingViewAlert.context_json),
    defer(TradingViewAlert.assessment_json),
    defer(TradingViewAlert.analysis_error),
)


class PracticeRun(SQLModel, table=True):
    """A3 session identity; revisions never replace the canonical cohort."""
    __tablename__ = "practice_run"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_key: str = Field(unique=True)
    day: date = Field(index=True)
    revision: int = 0
    parent_id: Optional[uuid.UUID] = Field(default=None, foreign_key="practice_run.id")
    job_id: uuid.UUID = Field(foreign_key="job_run.id")
    mode: str
    comparison: str
    status: str = "queued"
    result: Optional[str] = None
    late: bool = False
    deadline: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    policy_version: str
    policy_hash: str
    calendar_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    brief_json: str = Field(default="[]", sa_column=Column(Text, nullable=False))
    timings_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    error: Optional[str] = None


class PracticeOpportunity(SQLModel, table=True):
    __tablename__ = "practice_opportunity"
    __table_args__ = (UniqueConstraint("run_id", "symbol", name="uq_practice_opportunity_symbol"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(foreign_key="practice_run.id", index=True)
    symbol: str
    context_id: Optional[uuid.UUID] = Field(default=None, foreign_key="decision_context.id")
    revealed_at: Optional[datetime] = None
    benchmark_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    feedback_json: str = Field(default='{"rating":"unrated","phone_received":null}', sa_column=Column(Text, nullable=False))


class PracticeAgentCall(SQLModel, table=True):
    """One reserved paid attempt per ET day, including uncertain completions."""
    __tablename__ = "practice_agent_call"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    day: date = Field(unique=True)
    run_id: uuid.UUID = Field(foreign_key="practice_run.id", unique=True)
    status: str = "reserved"
    model: str
    prompt_version: str
    payload_json: str = Field(sa_column=Column(Text, nullable=False))
    output_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    config_json: str = Field(sa_column=Column(Text, nullable=False))
    usage_json: Optional[str] = None
    cost_usd: Optional[float] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
