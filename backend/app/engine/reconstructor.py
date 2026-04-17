"""
FIFO trade reconstructor.

Handles both options and stocks. Pure logic - no DB access.
"""

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
_CLOSE_HOUR = 16
_ZERO = Decimal("0")
_EPSILON = Decimal("0.000000001")

ContractKey = tuple[uuid.UUID, str, str, str | None, Decimal | None, date | None]

_OPEN_SIDES = {"buy_to_open", "sell_to_open", "buy"}
_CLOSE_SIDES = {"sell_to_close", "buy_to_close", "sell"}


def _q6(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _q4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _sort_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(ET).replace(tzinfo=None)


@dataclass
class FillInput:
    id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    instrument_type: str
    side: str
    contracts: Decimal
    price: Decimal
    executed_at: datetime
    option_type: str | None = None
    strike: Decimal | None = None
    expiration: date | None = None


@dataclass
class TradeOutput:
    id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    instrument_type: str
    contracts: Decimal
    avg_entry_premium: Decimal
    avg_exit_premium: Decimal | None
    total_premium_paid: Decimal
    realized_pnl: Decimal | None
    pnl_pct: Decimal | None
    hold_duration_mins: int | None
    entry_time_bucket: str | None
    expired_worthless: bool
    opened_at: datetime
    closed_at: datetime | None
    status: str
    option_type: str | None = None
    strike: Decimal | None = None
    expiration: date | None = None


@dataclass
class TradeFillOutput:
    trade_id: uuid.UUID
    fill_id: uuid.UUID
    role: str


@dataclass
class ReconstructResult:
    trades: list[TradeOutput]
    trade_fills: list[TradeFillOutput]
    anomalies: list[str]


@dataclass
class _Lot:
    contracts: Decimal
    price: Decimal
    fill_id: uuid.UUID
    opened_at: datetime


@dataclass
class _OpenTrade:
    trade_id: uuid.UUID
    account_id: uuid.UUID
    ticker: str
    instrument_type: str
    option_type: str | None
    strike: Decimal | None
    expiration: date | None
    lots: deque[_Lot] = field(default_factory=deque)
    trade_fills: list[TradeFillOutput] = field(default_factory=list)
    total_entry_contracts: Decimal = _ZERO
    total_entry_cost: Decimal = _ZERO
    total_exit_contracts: Decimal = _ZERO
    total_exit_proceeds: Decimal = _ZERO
    realized_pnl: Decimal = _ZERO
    opened_at: datetime = field(default_factory=datetime.utcnow)
    max_contracts: Decimal = _ZERO
    current_open_contracts: Decimal = _ZERO
    closed_at: datetime | None = None


def reconstruct(fills: list[FillInput], today: date | None = None) -> ReconstructResult:
    if today is None:
        today = date.today()

    open_trades: dict[ContractKey, _OpenTrade] = {}
    completed: list[_OpenTrade] = []
    anomalies: list[str] = []

    for fill in sorted(fills, key=lambda f: _sort_dt(f.executed_at)):
        key = _make_key(fill)
        if fill.side in _OPEN_SIDES:
            _handle_open(fill, key, open_trades)
        elif fill.side in _CLOSE_SIDES:
            _handle_close(fill, key, open_trades, completed, anomalies)
        else:
            anomalies.append(f"Unsupported fill side {fill.side!r} for fill {fill.id}")

    for key, ot in list(open_trades.items()):
        if ot.instrument_type == "option" and ot.expiration and ot.expiration < today:
            ot.realized_pnl = -_total_entry_cost(ot)
            completed.append(ot)
            del open_trades[key]

    trades_out, fills_out = [], []
    for ot in completed:
        trades_out.append(_finalize(ot, "closed" if not ot.lots else "expired"))
        fills_out.extend(ot.trade_fills)
    for ot in open_trades.values():
        trades_out.append(_finalize(ot, "open"))
        fills_out.extend(ot.trade_fills)

    return ReconstructResult(trades=trades_out, trade_fills=fills_out, anomalies=anomalies)


def _make_key(fill: FillInput) -> ContractKey:
    if fill.instrument_type == "option":
        return (fill.account_id, fill.ticker, "option", fill.option_type, fill.strike, fill.expiration)
    return (fill.account_id, fill.ticker, "stock", None, None, None)


def _handle_open(fill: FillInput, key: ContractKey, open_trades: dict[ContractKey, _OpenTrade]) -> None:
    if key not in open_trades:
        open_trades[key] = _OpenTrade(
            trade_id=fill.id,
            account_id=fill.account_id,
            ticker=fill.ticker,
            instrument_type=fill.instrument_type,
            option_type=fill.option_type,
            strike=fill.strike,
            expiration=fill.expiration,
            opened_at=fill.executed_at,
        )

    ot = open_trades[key]
    ot.lots.append(_Lot(contracts=fill.contracts, price=fill.price, fill_id=fill.id, opened_at=fill.executed_at))
    ot.total_entry_contracts += fill.contracts
    ot.total_entry_cost += fill.price * fill.contracts
    ot.current_open_contracts += fill.contracts
    ot.max_contracts = max(ot.max_contracts, ot.current_open_contracts)
    ot.trade_fills.append(TradeFillOutput(trade_id=ot.trade_id, fill_id=fill.id, role="entry"))


def _handle_close(
    fill: FillInput,
    key: ContractKey,
    open_trades: dict[ContractKey, _OpenTrade],
    completed: list[_OpenTrade],
    anomalies: list[str],
) -> None:
    if key not in open_trades:
        anomalies.append(f"Orphaned close fill {fill.id} for {fill.ticker} at {fill.executed_at.isoformat()}")
        return

    ot = open_trades[key]
    remaining = fill.contracts

    while remaining > _ZERO and ot.lots:
        lot = ot.lots[0]
        consumed = min(lot.contracts, remaining)
        pnl_per = fill.price - lot.price if fill.side in ("sell_to_close", "sell") else lot.price - fill.price
        ot.realized_pnl += pnl_per * consumed
        ot.total_exit_contracts += consumed
        ot.total_exit_proceeds += fill.price * consumed
        lot.contracts -= consumed
        remaining -= consumed
        ot.current_open_contracts -= consumed
        if abs(lot.contracts) < _EPSILON:
            ot.lots.popleft()

    if remaining > _ZERO:
        anomalies.append(
            f"Over-close on fill {fill.id}: tried to close {fill.contracts} but only matched {fill.contracts - remaining}"
        )

    ot.trade_fills.append(TradeFillOutput(trade_id=ot.trade_id, fill_id=fill.id, role="exit"))

    if not ot.lots:
        ot.closed_at = fill.executed_at
        completed.append(open_trades.pop(key))


def _total_entry_cost(ot: _OpenTrade) -> Decimal:
    if not ot.total_entry_contracts:
        return _ZERO
    avg = ot.total_entry_cost / ot.total_entry_contracts
    return avg * ot.total_entry_contracts


def _finalize(ot: _OpenTrade, status: str) -> TradeOutput:
    avg_entry = ot.total_entry_cost / ot.total_entry_contracts if ot.total_entry_contracts else _ZERO
    total_paid = avg_entry * ot.total_entry_contracts
    avg_exit = (ot.total_exit_proceeds / ot.total_exit_contracts if ot.total_exit_contracts else None)

    realized_pnl = ot.realized_pnl if ot.total_exit_contracts else None
    pnl_pct = (realized_pnl / total_paid) if realized_pnl is not None and total_paid else None

    closed_at = ot.closed_at
    expired_worthless = False

    if status == "expired":
        expired_worthless = True
        closed_at = datetime(ot.expiration.year, ot.expiration.month, ot.expiration.day, _CLOSE_HOUR, 0, 0, tzinfo=ET)
        realized_pnl = -total_paid
        pnl_pct = Decimal("-1")

    hold_mins: int | None = None
    if closed_at is not None:
        ca = closed_at.replace(tzinfo=None) if closed_at.tzinfo else closed_at
        oa = ot.opened_at.replace(tzinfo=None) if ot.opened_at.tzinfo else ot.opened_at
        hold_mins = int((ca - oa).total_seconds() / 60)

    return TradeOutput(
        id=ot.trade_id,
        account_id=ot.account_id,
        ticker=ot.ticker,
        instrument_type=ot.instrument_type,
        option_type=ot.option_type,
        strike=ot.strike,
        expiration=ot.expiration,
        contracts=_q6(ot.max_contracts or ot.total_entry_contracts),
        avg_entry_premium=_q6(avg_entry),
        avg_exit_premium=_q6(avg_exit) if avg_exit is not None else None,
        total_premium_paid=_q6(total_paid),
        realized_pnl=_q6(realized_pnl) if realized_pnl is not None else None,
        pnl_pct=_q4(pnl_pct) if pnl_pct is not None else None,
        hold_duration_mins=hold_mins,
        entry_time_bucket=_time_bucket(ot.opened_at),
        expired_worthless=expired_worthless,
        opened_at=ot.opened_at,
        closed_at=closed_at,
        status=status,
    )


def _time_bucket(dt: datetime) -> str | None:
    et = dt if dt.tzinfo is None else dt.astimezone(ET)
    t = et.hour * 60 + et.minute
    if 9 * 60 + 30 <= t < 10 * 60:
        return "open"
    if 10 * 60 <= t < 15 * 60:
        return "mid"
    if 15 * 60 <= t < 16 * 60:
        return "close"
    return None
