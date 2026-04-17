import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, Numeric
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

    # Enriched after parse - all nullable, never block a fill save
    iv_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    delta_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    iv_rank_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))
    underlying_price_at_fill: Optional[float] = Field(default=None, sa_column=Column(DECIMAL_18_6, nullable=True))

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
