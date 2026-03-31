import uuid
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel, Relationship


class Account(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    type: str   # "roth_ira"
    last4: str  # "8267"

    fills: list["Fill"] = Relationship(back_populates="account")
    trades: list["Trade"] = Relationship(back_populates="account")


class Fill(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="account.id")
    ticker: str                  # underlying only — "NVDA" not "NVDA250328C00900000"
    side: str                    # "buy_to_open" | "sell_to_close" | "buy_to_close" | "sell_to_open"
    contracts: int
    price: float                 # per-contract premium in dollars
    executed_at: datetime        # tz-aware America/New_York
    option_type: str             # "call" | "put"
    strike: float
    expiration: date
    raw_email_id: str            # IMAP UID for traceability

    # Enriched after parse — all nullable, never block a fill save
    iv_at_fill: Optional[float] = None
    delta_at_fill: Optional[float] = None
    iv_rank_at_fill: Optional[float] = None  # 0.0–1.0
    underlying_price_at_fill: Optional[float] = None

    account: Optional[Account] = Relationship(back_populates="fills")
    trade_fills: list["TradeFill"] = Relationship(back_populates="fill")


class Trade(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="account.id")
    ticker: str
    option_type: str             # "call" | "put"
    strike: float
    expiration: date
    contracts: int               # max position size during trade
    avg_entry_premium: float     # per contract
    avg_exit_premium: Optional[float] = None
    total_premium_paid: float    # avg_entry × contracts (cash at risk)
    realized_pnl: Optional[float] = None
    pnl_pct: Optional[float] = None  # % gain/loss on premium
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
