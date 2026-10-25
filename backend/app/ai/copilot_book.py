"""Copilot Lab's read-only views of the chart and the owner's book (docs/copilot-lab.md).

Each function reads an existing service and returns a compact, bounded view with
its as-of time, for the tools in ``copilot_tools``:

- ``chart_context``: the same ``chart_feed.workspace`` the Charts page reads
  (bars, automatic levels and their interactions, VWAP, RVol, the quote row).
- ``positions``: open trades through ``chart_journal.positions`` (its open lots),
  marked with the dashboard's quote engine.
- ``trades``: recent closed trades in one symbol, as the journal stored them.
- ``memories``: the owner's approved (active) Jo memories through ``jo_briefing.memories``.

Nothing here writes. No account number, account id, trade id, fill id or broker
id leaves this module: an account appears by its name, with digit runs removed.
Webull stays out, as the owner chose (dormant).
"""
from __future__ import annotations

import re
from contextlib import nullcontext
from datetime import UTC, datetime

INTERVALS = ("1m", "5m", "15m", "1h", "1D")
MAX_BARS = 40
MAX_LEVELS_EACH_SIDE = 3
MAX_POSITIONS = 15
MAX_TRADES = 10
MAX_MEMORIES = 10
MAX_TAGS, MAX_TAG_CHARS = 4, 24  # so ten trades at every cap still fit MAX_RESULT_CHARS


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value)


def _journal_time(value: datetime | None) -> str | None:
    """A journal time is a naive New York wall clock (chart_journal.stamp): attach New York and keep the offset."""
    from app.engine.chart_math import ET
    if value is None:
        return None
    return (value.replace(tzinfo=ET) if value.tzinfo is None else value.astimezone(ET)).isoformat(timespec="seconds")


def _round(value, places: int = 2):
    if not isinstance(value, (int, float)):
        return None
    return round(float(value), 4 if abs(value) < 1 else places)


def _label(name: str | None) -> str:
    """An account's name with any digit run removed, so no account number can leak through a label."""
    return " ".join(re.sub(r"\d{2,}", "", name or "").split())[:20] or "account"


def _et(stamp) -> str | None:
    """A bar time, compact: New York month-day hour:minute."""
    from app.engine.chart_math import ET
    return datetime.fromtimestamp(stamp, ET).strftime("%m-%d %H:%M") if isinstance(stamp, (int, float)) else None


def _now() -> str:
    return _iso(datetime.now(UTC))


# --------------------------------------------------------------------------- the chart

def compact_chart(symbol: str, timeframe: str, data: dict) -> dict:
    """The model's view of one workspace read: nothing recomputed, only selected and rounded."""
    panel = (data.get("panels") or {}).get(timeframe) or {}
    bars = panel.get("bars") or []
    last = bars[-1] if bars else None
    spot = last.get("close") if last else None
    quote = next((q for q in data.get("quotes") or [] if q.get("symbol") == symbol), {})
    levels = data.get("auto_levels") or {}
    events = panel.get("level_events") or {}

    def zone(z: dict) -> dict:
        state = (events.get(z.get("id")) or {}).get("state")
        return {"low": _round(z.get("low")), "high": _round(z.get("high")), "label": str(z.get("label") or "")[:60],
                "score": _round(z.get("score")), **({"state": state} if state else {})}

    zones = [z for z in levels.get("zones") or [] if isinstance(z.get("low"), (int, float)) and isinstance(z.get("high"), (int, float))]
    above = sorted((z for z in zones if spot is not None and z["low"] > spot), key=lambda z: z["low"])[:MAX_LEVELS_EACH_SIDE]
    below = sorted((z for z in zones if spot is not None and z["high"] < spot), key=lambda z: -z["high"])[:MAX_LEVELS_EACH_SIDE]
    at = [z for z in zones if spot is not None and z["low"] <= spot <= z["high"]][:1]
    vwap = last.get("vwap") if last else None
    sd = last.get("vwap_sd") if last else None
    rvol = data.get("rvol") or {}
    shown = bars[-MAX_BARS:]
    return {
        "symbol": symbol, "timeframe": timeframe, "state": "ok" if bars else "no_bars",
        "as_of": _iso(data.get("intraday_as_of")) or _iso(data.get("checked_at")),
        "session": data.get("session"),
        "market": {"date": data["market"].get("date"), "status": data["market"].get("status"),
                   "description": str(data["market"].get("description") or "")[:80] or None} if isinstance(data.get("market"), dict) else None,
        "delayed": bool(data.get("delayed")),
        "bars": {"count_total": len(bars), "shown": len(shown),
                 "fields": "t (New York, MM-DD HH:MM, the bar's start), o, h, l, c, v, rvol (relative volume, null when unknown), "
                           "x (extended hours)",
                 "rows": [[_et(b.get("time")), _round(b.get("open")), _round(b.get("high")), _round(b.get("low")),
                           _round(b.get("close")), int(b.get("volume") or 0), _round(b.get("rvol")), bool(b.get("extended"))]
                          for b in shown]},
        "last": _round(spot),
        "vwap": None if vwap is None else {"vwap": _round(vwap), "sd": _round(sd),
                                            **({"band_1sd": [_round(vwap - sd), _round(vwap + sd)]} if sd is not None else {})},
        "levels": {"atr": _round(levels.get("atr")), "at": [zone(z) for z in at], "above": [zone(z) for z in above],
                   "below": [zone(z) for z in below],
                   **({"missing": [str(m)[:120] for m in list((levels.get("missing") or {}).values())[:3]]} if levels.get("missing") else {})},
        "rvol": {"state": rvol.get("state"), "baseline_sessions": rvol.get("traded"), "message": str(rvol.get("message") or "")[:120] or None,
                 "last_bar": _round(last.get("rvol")) if last else None} if rvol else None,
        "quote": {"last": _round(quote.get("last")), "open": _round(quote.get("open")), "day_high": _round(quote.get("day_high")),
                  "day_low": _round(quote.get("day_low")), "previous_close": _round(quote.get("previous_close")),
                  "change_pct": _round(quote.get("change_percentage")), "volume": quote.get("volume"),
                  "trade_time": _iso(quote.get("trade_time"))} if quote else None,
        "issues": [str(i)[:120] for i in (data.get("issues") or [])][:3],
    }


def chart_context(symbol: str, timeframe: str) -> dict:
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import ChartFeedError, chart_feed
    from app.engine.chart_history import chart_history
    try:
        data = chart_feed.workspace(symbol, [timeframe], [], "extended", calendar=chart_calendar,
                                    stored_session=chart_history.stored, volume_profile=chart_history.volume_profile)
    except ChartFeedError as exc:
        return {"symbol": symbol, "timeframe": timeframe, "state": "unavailable", "reason": str(exc)[:200], "as_of": _now()}
    return compact_chart(symbol, timeframe, data)


# --------------------------------------------------------------------------- the book

def _not_webull():
    from sqlalchemy import or_
    from app.models import Account
    return or_(Account.broker.is_(None), Account.broker != "webull")  # Dormant by the owner's choice.


def _mark(trade, quotes: dict) -> tuple[float | None, str | None]:
    """The current mark in the same units as the journal's avg_cost: dollars a share, or a contract (premium x 100)."""
    if trade.instrument_type == "option":
        from app.engine.quotes import OptionQuoteRequest, option_mark
        result, quoted_at = option_mark(OptionQuoteRequest(ticker=trade.ticker, expiration=trade.expiration.isoformat(),
                                                           strike=float(trade.strike), option_type=trade.option_type or ""))
        premium = result.mid if result.mid is not None else result.last_price
        return (None if premium is None else round(premium * 100, 2)), _iso(quoted_at)
    price = quotes.get(trade.ticker)
    return (None if price is None else float(price)), None


def _warm_option_quotes(trades: list) -> None:
    """One batched option-quote read, so the per-contract marks after it come from the 60-second cache, not one
    provider call each (fifteen options must not reach the tool timeout)."""
    from app.engine.quotes import OptionQuoteRequest, get_option_quotes
    wanted = [OptionQuoteRequest(ticker=t.ticker, expiration=t.expiration.isoformat(), strike=float(t.strike),
                                 option_type=t.option_type or "")
              for t in trades if t.instrument_type == "option" and t.expiration and t.strike is not None]
    if wanted:
        get_option_quotes(wanted)


def position_rows(db, limit: int = MAX_POSITIONS, first: str | None = None) -> tuple[list[tuple], int]:
    """``([(trade, row), ...], total)``: the row is the model's view (below); the trade lets a caller in this package
    look up what else the journal keeps for it, and never leaves the server. ``total`` counts every open position.
    ``first`` puts that symbol's positions ahead of the alphabetical rest before the ``limit`` cut, so the symbol a
    turn is about is never the one dropped from a large book."""
    from sqlmodel import select
    from app.engine import chart_journal
    from app.engine.quotes import get_stock_quotes
    from app.models import Account, Trade
    trades = {str(t.id): t for t in db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                                            .where(Trade.status == "open").where(_not_webull())).all()}
    tickers = sorted({t.ticker for t in trades.values()})
    held = [p for ticker in tickers for p in chart_journal.positions(db, ticker) if p["trade_id"] in trades]
    if first:
        held.sort(key=lambda p: trades[p["trade_id"]].ticker != first)  # stable: the alphabetical order holds within each part
    quotes = get_stock_quotes(sorted({trades[p["trade_id"]].ticker for p in held if trades[p["trade_id"]].instrument_type == "stock"})) if held else {}
    _warm_option_quotes([trades[p["trade_id"]] for p in held[:limit]])
    from app.engine.chart_math import ET
    now = datetime.now(UTC)
    pairs = []
    for p in held[:limit]:
        trade = trades[p["trade_id"]]
        mark, quoted_at = _mark(trade, quotes)
        cost, quantity = p.get("avg_cost"), p.get("open") or 0
        sign = -1 if p.get("direction") == "short" else 1
        gain = None if mark is None or cost is None else round(sign * (mark - cost) * quantity, 2)
        opened = trade.opened_at.replace(tzinfo=ET) if trade.opened_at.tzinfo is None else trade.opened_at  # New York wall clock
        pairs.append((trade, {
            "symbol": trade.ticker, "account": _label(p.get("account")), "instrument": trade.instrument_type,
            **({"option": {"side": trade.option_type, "strike": _round(float(trade.strike)), "expiry": trade.expiration.isoformat()}}
               if trade.instrument_type == "option" else {}),
            "direction": p.get("direction"), "quantity": quantity, "avg_entry": _round(cost),
            "mark": _round(mark), **({"mark_as_of": quoted_at} if quoted_at else {}), "unrealized_usd": gain,
            "unrealized_pct": None if gain is None or not cost else round(100 * sign * (mark - cost) / cost, 1),
            "opened_at": _journal_time(trade.opened_at), "days_held": (now - opened).days,
        }))
    return pairs, len(held)


def positions(session=None) -> dict:
    from sqlmodel import Session
    from app.database import engine
    with (Session(engine) if session is None else nullcontext(session)) as db:
        pairs, count = position_rows(db)
    rows = [row for _, row in pairs]
    now = datetime.now(UTC)
    return {"state": "ok", "as_of": _iso(now), "count": count, "shown": len(rows), "positions": rows,
            "units": "Options: avg_entry and mark are dollars per contract (the premium x 100). Stocks: dollars per share. "
                     "opened_at is New York time.",
            "excluded": "Webull accounts (dormant)"}


def trades(symbol: str, limit: int = 5, session=None, exclude=None) -> dict:
    """Recent closed trades in ``symbol``, newest first; ``exclude`` leaves one trade out (the one under review)."""
    from sqlmodel import Session, col, select
    from app.database import engine
    from app.models import Account, Tag, Trade, TradeTag
    with (Session(engine) if session is None else nullcontext(session)) as db:
        query = (select(Trade, Account.name).join(Account, Account.id == Trade.account_id)
                 .where(Trade.ticker == symbol, Trade.status != "open").where(_not_webull()))
        if exclude is not None:
            query = query.where(Trade.id != exclude)
        found = db.exec(query.order_by(col(Trade.closed_at).desc()).limit(min(limit, MAX_TRADES))).all()
        ids = [t.id for t, _ in found]
        tags: dict = {}
        if ids:
            for trade_id, name in db.exec(select(TradeTag.trade_id, Tag.name).join(Tag, Tag.id == TradeTag.tag_id)
                                          .where(col(TradeTag.trade_id).in_(ids))).all():
                tags.setdefault(trade_id, []).append(str(name)[:MAX_TAG_CHARS])
    rows = [{
        "account": _label(name), "instrument": t.instrument_type,
        **({"option": {"side": t.option_type, "strike": _round(float(t.strike)), "expiry": t.expiration.isoformat()}}
           if t.instrument_type == "option" and t.strike is not None and t.expiration else {}),
        "quantity": float(t.contracts), "entry_time": _journal_time(t.opened_at), "exit_time": _journal_time(t.closed_at),
        "entry_price": _round(float(t.avg_entry_premium)),
        "exit_price": None if t.avg_exit_premium is None else _round(float(t.avg_exit_premium)),
        "pnl_usd": None if t.realized_pnl is None else round(float(t.realized_pnl), 2),
        "pnl_pct": None if t.pnl_pct is None else round(100 * float(t.pnl_pct), 1), "hold_minutes": t.hold_duration_mins,
        "status": t.status, "expired_worthless": bool(t.expired_worthless), "tags": sorted(tags.get(t.id, []))[:MAX_TAGS],
    } for t, name in found]
    return {"symbol": symbol, "state": "ok", "as_of": _now(), "trades": rows,
            "units": "Option prices are per contract as the journal stores them; stock prices per share. pnl_pct is percent of "
                     "the premium paid. Times are New York."}


def memories(limit: int = 5, symbol: str | None = None, session=None) -> dict:
    """Approved memories, newest first; with ``symbol``, that symbol's first and then the general ones (no symbol)."""
    from sqlmodel import Session
    from app.database import engine
    from app.engine import jo_briefing
    with (Session(engine) if session is None else nullcontext(session)) as db:
        if symbol:
            found = jo_briefing.memories(db, status="active", symbol=symbol, limit=MAX_MEMORIES)
            found += [m for m in jo_briefing.memories(db, status="active", limit=MAX_MEMORIES * 4) if not m.get("symbol")]
        else:
            found = jo_briefing.memories(db, status="active", limit=MAX_MEMORIES * 2)
        found = [m for m in found if not m.get("redacted_at")]
    rows = []
    for m in found[:min(limit, MAX_MEMORIES)]:
        body = m.get("body") or {}
        rows.append({"kind": body.get("kind"), "symbol": m.get("symbol"), "text": str(body.get("original_text") or "")[:280],
                     **({"interpretation": str(body["interpretation"])[:160]} if body.get("interpretation") else {}),
                     "saved_at": _iso(m.get("received_at"))})
    return {"state": "ok", "as_of": _now(), **({"symbol": symbol} if symbol else {}), "memories": rows,
            "note": "The owner's approved memories: statements, theses, preferences and lessons they confirmed. Read-only."}
