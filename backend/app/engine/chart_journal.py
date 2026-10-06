"""The journal on the chart (C3.1, C3.2): a trade's card from a fill arrow, and
the open positions drawn as lines. Read-only, and never calls a provider; the
option mark is the router's own on-demand request.

Units are the rule here. A stock fill's price is a share price, on the same
axis as the chart. An option fill's price is the premium per contract in
dollars (100 shares; see docs/agent/domain-rules.md) and is never an
underlying price, so nothing here offers it as a chart price. An option position's chart line is
the observed underlying price at its entry, labeled as such, or nothing.
"""

from collections import deque
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session, select

from app.engine.chart_math import ET
from app.engine.metric_versions import CONTEXT_VERSION, PATH_VERSION
from app.engine.trade_path import market_inputs_fingerprint, trade_inputs_fingerprint
from app.models import FILL_LIGHT, Account, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

OPEN_SIDES = {"buy_to_open", "sell_to_open", "buy"}
# Enrichment that read one exchange's prints, not the consolidated tape the chart draws.
SINGLE_VENUE = {"alpaca_iex"}


def stamp(value: datetime | None) -> int | None:
    """A journal time (a naive New York wall clock) as UTC seconds."""
    if value is None:
        return None
    return int((value.replace(tzinfo=ET) if value.tzinfo is None else value).timestamp())


def utc_stamp(value: datetime | None) -> int | None:
    """A ``datetime.utcnow()`` column as UTC seconds."""
    return None if value is None else int(value.replace(tzinfo=UTC).timestamp())


def number(value) -> float | None:
    return None if value is None else float(value)


def contract_label(ticker: str, instrument: str, option_type: str | None, strike, expiration) -> str:
    if instrument != "option":
        return f"{ticker} stock"
    kind = {"call": "C", "put": "P"}.get(option_type or "", "?")
    when = f"{expiration.month}/{expiration.day}/{expiration.year % 100:02d}" if expiration else "?"
    return f"{ticker} {when} {number(strike):g}{kind}" if strike is not None else f"{ticker} {when} ?{kind}"


def open_lots(fills: list[dict]) -> dict:
    """What is still open after replaying one trade's fills first in, first out,
    in the reconstructor's order (time, opens before closes, then id).

    ``avg_cost`` is the share-weighted price of the lots still open: after a
    partial exit it is the cost of what remains, not of every entry. A trade
    opened with ``sell_to_open`` is short; its realized P&L runs the other way.
    """
    ordered = sorted(fills, key=lambda f: (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, str(f["id"])))
    short = any(f["side"] == "sell_to_open" for f in ordered)
    lots: deque[list[Decimal]] = deque()
    realized = Decimal(0)
    for fill in ordered:
        qty, price = Decimal(str(fill["contracts"])), Decimal(str(fill["price"]))
        if fill["side"] in OPEN_SIDES:
            lots.append([qty, price])
            continue
        while qty > 0 and lots:
            lot = lots[0]
            used = min(lot[0], qty)
            realized += (lot[1] - price if short else price - lot[1]) * used
            lot[0] -= used
            qty -= used
            if lot[0] <= Decimal("0.000000001"):
                lots.popleft()
    remaining = sum((lot[0] for lot in lots), Decimal(0))
    cost = sum((lot[0] * lot[1] for lot in lots), Decimal(0))
    return {"open": float(remaining), "avg_cost": float(cost / remaining) if remaining else None,
            "realized": float(realized), "direction": "short" if short else "long"}


def _units(instrument: str) -> dict:
    if instrument == "option":
        return {"unit": "contract",
                "price_note": "Option prices are the premium per contract (100 shares), in dollars. They are not underlying prices."}
    return {"unit": "share", "price_note": "Stock prices are per share, on the chart's price axis."}


def _underlying_at(fill: Fill, context: FillMarketContext | None) -> dict | None:
    """The underlying price observed at an option fill, with where it came from."""
    if context is not None and context.entry_underlying_price is not None:
        return {"price": float(context.entry_underlying_price), "source": context.data_source,
                "as_of": stamp(context.entry_context_as_of), "single_venue": context.data_source in SINGLE_VENUE}
    if fill.underlying_price_at_fill is not None:
        return {"price": float(fill.underlying_price_at_fill), "source": "fill_enrichment", "as_of": stamp(fill.executed_at), "single_venue": False}
    return None


def _path(trade: Trade, fills: list[Fill], contexts: dict, metrics: TradePathMetrics | None) -> dict:
    if metrics is None:
        note = ("Computed once a trade closes." if trade.status == "open"
                else "Not computed yet. Run trade path metrics from Sync.")
        return {"state": "missing", "note": note}
    stale = (metrics.calculation_version != PATH_VERSION
             or metrics.inputs_fingerprint != trade_inputs_fingerprint(trade, fills)
             or metrics.market_inputs_fingerprint != market_inputs_fingerprint(fills, contexts))
    fields = ("underlying_mfe_pct", "underlying_mae_pct", "underlying_exit_efficiency", "underlying_giveback_pct",
              "moved_in_favor_first", "option_mfe_pct", "option_mae_pct", "option_exit_efficiency", "option_path_quality")
    return {
        "state": "stale" if stale else "current",
        "note": ("Computed from an older version of this trade or its inputs; the next path run recomputes it." if stale
                 else "From the trade path run, not from these candles."),
        "source": metrics.data_source, "fetched_at": utc_stamp(metrics.fetched_at),
        **{key: (number(getattr(metrics, key)) if key != "option_path_quality" else getattr(metrics, key)) for key in fields},
    }


def _context(fill: Fill | None, context: FillMarketContext | None) -> dict:
    if fill is None or context is None:
        return {"state": "missing", "note": "This entry has no market context yet. Enrich fills from Sync."}
    stale = context.calculation_version != CONTEXT_VERSION
    venue = context.data_source in SINGLE_VENUE
    notes = ["Computed by enrichment when the fill was imported, not from these candles."]
    if stale:
        notes.append("An older calculation; the next enrichment run replaces it.")
    if venue:
        notes.append("Read from one exchange (IEX), so VWAP and volume can differ from the chart's consolidated candles.")
    fields = ("entry_underlying_price", "entry_vwap", "entry_vs_vwap_pct", "rvol_time_adjusted", "simple_relative_volume",
              "chase_score", "entry_distance_from_day_high_pct", "entry_distance_from_day_low_pct",
              "entry_distance_from_premarket_high_pct", "entry_distance_from_premarket_low_pct",
              "entry_distance_from_prev_high_pct", "entry_distance_from_prev_low_pct", "entry_gap_pct")
    flags = ("is_chase_entry", "is_vwap_reclaim", "is_above_vwap", "is_trend_aligned", "is_late_move",
             "is_opening_range_breakout", "is_premarket_breakout")
    return {
        "state": "stale" if stale else "current", "note": " ".join(notes), "fill_id": str(fill.id),
        "source": context.data_source, "as_of": stamp(context.entry_context_as_of), "single_venue": venue,
        **{key: number(getattr(context, key)) for key in fields},
        "flags": {key: None if getattr(context, key) is None else bool(getattr(context, key)) for key in flags},
    }


def trade_card(db: Session, trade: Trade) -> dict:
    """Everything the card shows for one trade, in four queries."""
    links = db.exec(select(TradeFill).where(TradeFill.trade_id == trade.id)).all()
    roles = {link.fill_id: link.role for link in links}
    fills = list(db.exec(select(Fill).options(*FILL_LIGHT).where(Fill.id.in_(list(roles)))).all()) if roles else []
    fills.sort(key=lambda f: (f.executed_at, 0 if f.side in OPEN_SIDES else 1, str(f.id)))
    contexts = {str(row.fill_id): row for row in db.exec(
        select(FillMarketContext).where(FillMarketContext.fill_id.in_(list(roles))))} if roles else {}
    account = db.get(Account, trade.account_id)
    entries = [f for f in fills if roles[f.id] == "entry"]
    first = entries[0] if entries else None
    lots = open_lots([{"id": f.id, "side": f.side, "contracts": f.contracts, "price": f.price, "executed_at": f.executed_at} for f in fills])
    return {
        "trade": {
            "id": str(trade.id), "ticker": trade.ticker, "instrument": trade.instrument_type,
            "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
            "option_type": trade.option_type, "strike": number(trade.strike),
            "expiration": trade.expiration.isoformat() if trade.expiration else None,
            "account": {"name": account.name, "last4": account.last4} if account else None,
            "status": trade.status, "direction": lots["direction"], "expired_worthless": trade.expired_worthless,
            "opened_at": stamp(trade.opened_at), "closed_at": stamp(trade.closed_at), "hold_minutes": trade.hold_duration_mins,
            "contracts": number(trade.contracts), "avg_entry": number(trade.avg_entry_premium), "avg_exit": number(trade.avg_exit_premium),
            "cost": number(trade.total_premium_paid), "realized_pnl": number(trade.realized_pnl),
            "pnl_pct": number(trade.pnl_pct) * 100 if trade.pnl_pct is not None else None,
            **_units(trade.instrument_type),
        },
        "fills": [{
            "id": str(f.id), "role": roles[f.id], "side": f.side, "qty": float(f.contracts), "price": float(f.price),
            "time": stamp(f.executed_at),
            "underlying": _underlying_at(f, contexts.get(str(f.id))) if trade.instrument_type == "option" else None,
        } for f in fills],
        "position": {k: lots[k] for k in ("open", "avg_cost", "realized")} if trade.status == "open" and lots["open"] else None,
        "path": _path(trade, fills, contexts, db.get(TradePathMetrics, trade.id)),
        "context": _context(first, contexts.get(str(first.id)) if first else None),
    }


def fill_card(db: Session, fill: Fill) -> dict:
    link = db.exec(select(TradeFill).where(TradeFill.fill_id == fill.id)).first()
    trade = db.get(Trade, link.trade_id) if link else None
    return {
        "fill": {"id": str(fill.id), "ticker": fill.ticker, "side": fill.side, "qty": float(fill.contracts), "price": float(fill.price),
                 "time": stamp(fill.executed_at), "instrument": fill.instrument_type,
                 "contract": contract_label(fill.ticker, fill.instrument_type, fill.option_type, fill.strike, fill.expiration)},
        **(trade_card(db, trade) if trade else {"trade": None, "note": "This fill is not part of a reconstructed trade. Rebuild trades, or check it for a missing opening fill."}),
    }


def positions(db: Session, symbol: str) -> list[dict]:
    """Open trades on this underlying, for position lines (C3.2). Three queries
    for any number of trades: the trades, their fills, and the entries' context."""
    trades = db.exec(select(Trade, Account.name, Account.last4).join(Account, Account.id == Trade.account_id)
                     .where(Trade.ticker == symbol, Trade.status == "open").order_by(Trade.opened_at)).all()
    if not trades:
        return []
    ids = [trade.id for trade, _, _ in trades]
    rows = db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at,
                          Fill.underlying_price_at_fill)
                   .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(ids))).all()
    by_trade: dict = {}
    for row in rows:
        by_trade.setdefault(row.trade_id, []).append(row)
    entry_ids = [row.id for row in rows if row.role == "entry"]
    contexts = {row.fill_id: row for row in db.exec(select(FillMarketContext).where(FillMarketContext.fill_id.in_(entry_ids)))} if entry_ids else {}
    out = []
    for trade, account_name, last4 in trades:
        fills = sorted(by_trade.get(trade.id, []), key=lambda f: (f.executed_at, 0 if f.side in OPEN_SIDES else 1, str(f.id)))
        lots = open_lots([{"id": f.id, "side": f.side, "contracts": f.contracts, "price": f.price, "executed_at": f.executed_at} for f in fills])
        if not lots["open"]:
            continue
        entries = [f for f in fills if f.role == "entry"]
        underlying = None
        if trade.instrument_type == "option" and entries:
            context = contexts.get(entries[0].id)
            if context is not None and context.entry_underlying_price is not None:
                underlying = {"price": float(context.entry_underlying_price), "source": context.data_source,
                              "single_venue": context.data_source in SINGLE_VENUE}
            elif entries[0].underlying_price_at_fill is not None:
                underlying = {"price": float(entries[0].underlying_price_at_fill), "source": "fill_enrichment", "single_venue": False}
        out.append({
            "trade_id": str(trade.id), "account": account_name, "last4": last4, "instrument": trade.instrument_type,
            "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
            "direction": lots["direction"], "open": lots["open"], "avg_cost": lots["avg_cost"], "realized": lots["realized"],
            "opened_at": stamp(trade.opened_at),
            "exits": [stamp(f.executed_at) for f in fills if f.role == "exit"],
            # Stock: the chart line is avg_cost. Option: never the premium; the underlying at the first entry, or no line.
            "line": lots["avg_cost"] if trade.instrument_type == "stock" else (underlying["price"] if underlying else None),
            "underlying_at_entry": underlying,
            **_units(trade.instrument_type),
        })
    return out
