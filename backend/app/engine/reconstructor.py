"""
FIFO trade reconstructor.

Takes a list of Fill objects ordered by executed_at ASC and produces Trade +
TradeFill objects. Pure logic — no DB access. Call reconstruct() then persist
the results.

Core invariants:
  - Fills are never modified.
  - Trades are always safe to delete and rebuild from fills.
  - Same fills in same order always produce the same trades (idempotent).
"""

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Expiration cutoff time: 4 PM ET
_CLOSE_HOUR = 16

ContractKey = tuple[str, str, float, date]  # (ticker, option_type, strike, expiration)


@dataclass
class FillInput:
    """Minimal fill data needed by the reconstructor. Mirrors the Fill model."""
    id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    side: str           # "buy_to_open" | "sell_to_open" | "sell_to_close" | "buy_to_close"
    contracts: int
    price: float        # per-contract premium
    executed_at: datetime
    option_type: str    # "call" | "put"
    strike: float
    expiration: date


@dataclass
class TradeOutput:
    """Reconstructed trade. Mirrors the Trade model fields."""
    id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    option_type: str
    strike: float
    expiration: date
    contracts: int              # max position size
    avg_entry_premium: float
    avg_exit_premium: float | None
    total_premium_paid: float
    realized_pnl: float | None
    pnl_pct: float | None
    hold_duration_mins: int | None
    entry_time_bucket: str | None
    expired_worthless: bool
    opened_at: datetime
    closed_at: datetime | None
    status: str                 # "open" | "closed" | "expired"


@dataclass
class TradeFillOutput:
    trade_id: uuid.UUID
    fill_id: uuid.UUID
    role: str   # "entry" | "exit"


@dataclass
class ReconstructResult:
    trades: list[TradeOutput]
    trade_fills: list[TradeFillOutput]


# --- internal lot tracking ---

@dataclass
class _Lot:
    contracts: int
    price: float
    fill_id: uuid.UUID
    opened_at: datetime


@dataclass
class _OpenTrade:
    trade_id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    option_type: str
    strike: float
    expiration: date
    lots: deque[_Lot] = field(default_factory=deque)
    trade_fills: list[TradeFillOutput] = field(default_factory=list)
    # running totals for weighted-average entry
    total_entry_contracts: int = 0
    total_entry_cost: float = 0.0
    # running exit totals
    total_exit_contracts: int = 0
    total_exit_proceeds: float = 0.0
    realized_pnl: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    max_contracts: int = 0


def reconstruct(fills: list[FillInput], today: date | None = None) -> ReconstructResult:
    """
    Reconstruct trades from a list of fills ordered by executed_at ASC.

    today: override for expired-worthless detection (defaults to date.today()).
    """
    if today is None:
        today = date.today()

    # position_queue[key] → open trade being built
    open_trades: dict[ContractKey, _OpenTrade] = {}

    completed: list[_OpenTrade] = []

    for fill in sorted(fills, key=lambda f: f.executed_at):
        key: ContractKey = (fill.ticker, fill.option_type, fill.strike, fill.expiration)

        if fill.side in ("buy_to_open", "sell_to_open"):
            _handle_open(fill, key, open_trades)
        elif fill.side in ("sell_to_close", "buy_to_close"):
            _handle_close(fill, key, open_trades, completed)

    # Mark expired open trades
    still_open = list(open_trades.values())
    for ot in still_open:
        if ot.expiration < today:
            ot.realized_pnl = -_total_entry_cost(ot)
            completed.append(ot)
            del open_trades[(ot.ticker, ot.option_type, ot.strike, ot.expiration)]

    trades_out: list[TradeOutput] = []
    fills_out: list[TradeFillOutput] = []

    for ot in completed:
        trades_out.append(_finalize(ot, status="closed" if _is_fully_closed(ot) else "expired"))
        fills_out.extend(ot.trade_fills)

    for ot in open_trades.values():
        trades_out.append(_finalize(ot, status="open"))
        fills_out.extend(ot.trade_fills)

    return ReconstructResult(trades=trades_out, trade_fills=fills_out)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _handle_open(fill: FillInput, key: ContractKey, open_trades: dict) -> None:
    if key not in open_trades:
        open_trades[key] = _OpenTrade(
            trade_id=uuid.uuid4(),
            account_id=fill.account_id,
            ticker=fill.ticker,
            option_type=fill.option_type,
            strike=fill.strike,
            expiration=fill.expiration,
            opened_at=fill.executed_at,
        )

    ot = open_trades[key]
    lot = _Lot(
        contracts=fill.contracts,
        price=fill.price,
        fill_id=fill.id,
        opened_at=fill.executed_at,
    )
    ot.lots.append(lot)
    ot.total_entry_contracts += fill.contracts
    ot.total_entry_cost += fill.price * fill.contracts
    ot.max_contracts = max(ot.max_contracts, _contracts_in_queue(ot))
    ot.trade_fills.append(TradeFillOutput(trade_id=ot.trade_id, fill_id=fill.id, role="entry"))


def _handle_close(
    fill: FillInput,
    key: ContractKey,
    open_trades: dict,
    completed: list,
) -> None:
    if key not in open_trades:
        # Orphaned close fill — no matching open. Skip gracefully.
        return

    ot = open_trades[key]
    remaining = fill.contracts

    while remaining > 0 and ot.lots:
        lot = ot.lots[0]
        consumed = min(lot.contracts, remaining)

        # pnl per contract depends on direction
        if fill.side == "sell_to_close":
            pnl_per = fill.price - lot.price   # long position: sold higher = profit
        else:
            pnl_per = lot.price - fill.price   # short position: bought back lower = profit

        ot.realized_pnl += pnl_per * consumed
        ot.total_exit_contracts += consumed
        ot.total_exit_proceeds += fill.price * consumed

        lot.contracts -= consumed
        remaining -= consumed

        if lot.contracts == 0:
            ot.lots.popleft()

    ot.trade_fills.append(TradeFillOutput(trade_id=ot.trade_id, fill_id=fill.id, role="exit"))

    if not ot.lots:
        # Position fully closed
        ot_copy = open_trades.pop(key)
        _set_closed_at(ot_copy, fill.executed_at)
        completed.append(ot_copy)


def _set_closed_at(ot: _OpenTrade, closed_at: datetime) -> None:
    ot._closed_at = closed_at  # type: ignore[attr-defined]


def _finalize(ot: _OpenTrade, status: str) -> TradeOutput:
    avg_entry = ot.total_entry_cost / ot.total_entry_contracts if ot.total_entry_contracts else 0.0
    total_paid = avg_entry * ot.total_entry_contracts

    avg_exit: float | None = None
    if ot.total_exit_contracts > 0:
        avg_exit = ot.total_exit_proceeds / ot.total_exit_contracts

    realized_pnl: float | None = ot.realized_pnl if status != "open" else None
    pnl_pct: float | None = None
    if realized_pnl is not None and total_paid != 0:
        pnl_pct = realized_pnl / total_paid

    closed_at: datetime | None = getattr(ot, "_closed_at", None)

    # For expired-worthless trades, set closed_at to 4pm ET on expiration day
    expired_worthless = False
    if status == "expired":
        expired_worthless = True
        closed_at = datetime(
            ot.expiration.year, ot.expiration.month, ot.expiration.day,
            _CLOSE_HOUR, 0, 0, tzinfo=ET,
        )
        realized_pnl = -total_paid
        pnl_pct = -1.0

    hold_mins: int | None = None
    if closed_at is not None:
        # Normalize both to naive (SQLite strips tzinfo on read-back)
        ca = closed_at.replace(tzinfo=None) if closed_at.tzinfo else closed_at
        oa = ot.opened_at.replace(tzinfo=None) if ot.opened_at.tzinfo else ot.opened_at
        delta = ca - oa
        hold_mins = int(delta.total_seconds() / 60)

    return TradeOutput(
        id=ot.trade_id,
        account_id=ot.account_id,
        ticker=ot.ticker,
        option_type=ot.option_type,
        strike=ot.strike,
        expiration=ot.expiration,
        contracts=ot.max_contracts or ot.total_entry_contracts,
        avg_entry_premium=round(avg_entry, 4),
        avg_exit_premium=round(avg_exit, 4) if avg_exit is not None else None,
        total_premium_paid=round(total_paid, 4),
        realized_pnl=round(realized_pnl, 4) if realized_pnl is not None else None,
        pnl_pct=round(pnl_pct, 6) if pnl_pct is not None else None,
        hold_duration_mins=hold_mins,
        entry_time_bucket=_time_bucket(ot.opened_at),
        expired_worthless=expired_worthless,
        opened_at=ot.opened_at,
        closed_at=closed_at,
        status=status,
    )


def _contracts_in_queue(ot: _OpenTrade) -> int:
    return sum(lot.contracts for lot in ot.lots)


def _total_entry_cost(ot: _OpenTrade) -> float:
    avg = ot.total_entry_cost / ot.total_entry_contracts if ot.total_entry_contracts else 0.0
    return avg * ot.total_entry_contracts


def _is_fully_closed(ot: _OpenTrade) -> bool:
    return not ot.lots


def _time_bucket(dt: datetime) -> str | None:
    """Classify entry time as open/mid/close based on ET time."""
    if dt.tzinfo is None:
        return None
    et = dt.astimezone(ET)
    t = et.hour * 60 + et.minute
    if 9 * 60 + 30 <= t < 10 * 60:
        return "open"
    if 10 * 60 <= t < 15 * 60:
        return "mid"
    if 15 * 60 <= t < 16 * 60:
        return "close"
    return None
