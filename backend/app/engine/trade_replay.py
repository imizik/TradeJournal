"""One closed trade replayed on the chart: the underlying's minute candles with RTH VWAP, the option's own minute
prices when the feed has them, every fill, the pings that fired, the leak rules' cut, the model's trade tag, and the
position's P&L at each bar. Read by the trade page's Replay card (``GET /trades/{id}/replay``). Read-only.

Bars are the journal's Alpaca minutes (``alpaca.fetch_minute_bars_for_date``, the cache the path metrics fill); a
trade that closed today reads the day live, uncached, until the session is final. Each New York day keeps its regular
session, widened to any fill outside it. More than ``ONE_MINUTE_DAYS`` sessions are drawn as ``WIDE_MINUTES``-minute
candles. VWAP is the charts' own: minute HLC3 from 9:30, reset each day, absent outside the regular session.

P&L at a bar is realized (first in, first out over the fills up to and including that bar's minute, as fills carry
minutes only) plus the open contracts at that bar's close: the option's last trade (x100, fills store dollars per
contract), carried forward over a minute with no trade, or the stock's close. With no option bars the open part is
unknown, so the bar's P&L is null while anything is open. It is the last trade, not a price that could surely have
been sold at.

The cut is ``leak_bill.bill_trade``'s: the minute the hold rules (deep red past the hour, or a same-day option past
1 PM) said sell, on a long option. The cut line is ``fill_interrupts.cut_line`` (30% under a short-dated long option's
first buy) and its cross ``leak_bill.follow``'s, so the replay, the ping and the Sunday bill read one line.
"""
from __future__ import annotations

import logging
from bisect import bisect_left
from collections import deque
from datetime import UTC, date, datetime, timedelta
from typing import Callable

from sqlmodel import Session, select

from app.engine import fill_interrupts, leak_bill, plan_nudges, position_alerts, trade_ai_tags
from app.engine.analytics import wall_time
from app.engine.chart_journal import OPEN_SIDES
from app.engine.chart_math import ET
from app.engine.occ import occ_symbol
from app.engine.trade_path import MAX_PATH_WINDOW_DAYS
from app.models import Fill, Trade, TradeFill

log = logging.getLogger(__name__)

ONE_MINUTE_DAYS = 2  # sessions drawn as one-minute candles; a longer hold is drawn wider so it stays scrubbable
WIDE_MINUTES = 5
OPEN_MINUTE, CLOSE_MINUTE = 9 * 60 + 30, 16 * 60
EPS = 1e-9


def _parse(bar: dict) -> tuple[datetime, dict] | None:
    """A feed bar as (naive New York minute, its numbers), or None when it cannot be read."""
    try:
        at = datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00"))
        out = {"open": float(bar["o"]), "high": float(bar["h"]), "low": float(bar["l"]), "close": float(bar["c"]),
               "volume": float(bar.get("v") or 0)}
    except (KeyError, TypeError, ValueError):
        return None
    at = (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(ET).replace(tzinfo=None, second=0, microsecond=0)
    return at, out


def _minute(at: datetime) -> int:
    return at.hour * 60 + at.minute


def _epoch(at: datetime) -> int:
    """Naive New York wall time as epoch seconds."""
    return int(at.replace(tzinfo=ET).timestamp())


def _days(trade: Trade, closed: datetime) -> list[date]:
    start = wall_time(trade.opened_at).date()
    return [start + timedelta(days=n) for n in range((closed.date() - start).days + 1) if (start + timedelta(days=n)).weekday() < 5]


def _stock_bars(ticker: str, day: date) -> list[dict]:
    """The day's minutes from the journal cache; today's, read live and uncached until the session is final."""
    from app.engine.alpaca import ALPACA_API_KEY, _minute_session_complete, fetch_minute_bars_for_date, fetch_minute_bars_live
    if not ALPACA_API_KEY:  # no feed configured: only what the cache already holds
        return fetch_minute_bars_for_date([ticker], day, cache_only=True).get(ticker, [])
    if not _minute_session_complete(day):
        return fetch_minute_bars_live([ticker], day).get(ticker, [])
    return fetch_minute_bars_for_date([ticker], day).get(ticker, [])


def _option_bars(symbol: str, start: datetime, end: datetime) -> list[dict]:
    from app.engine.alpaca import ALPACA_API_KEY, fetch_option_bars
    if not ALPACA_API_KEY:
        return []
    return fetch_option_bars([symbol], "1Min", start.replace(tzinfo=ET), end.replace(tzinfo=ET)).get(symbol, [])


def _label(fill: dict, option: bool) -> str:
    verb = {"buy_to_open": "Bought", "buy": "Bought", "sell_to_close": "Sold", "sell": "Sold",
            "sell_to_open": "Sold to open", "buy_to_close": "Bought to close"}.get(fill["side"], fill["side"])
    price = fill["price"] / 100 if option else fill["price"]
    return f"{verb} {fill['contracts']:g} @ ${price:,.2f}"


def _pings(db: Session, trade: Trade) -> list[dict]:
    """Position alerts, plan pings and fill-time interrupts for the position, oldest first. ``sent`` is whether it
    reached the phone or may have; a held, capped or expired one is kept and says so."""
    out = [{"time": a["detected_at"], "kind": a["kind"], "title": None, "sent": a["delivery"] in ("sent", "unknown")}
           for a in position_alerts.for_trade(db, trade)["alerts"] + plan_nudges.for_trade(db, trade)]
    out += [{"time": i["detected_at"], "kind": "cut_line" if "cut_line" in i["kinds"] else "interrupt", "title": i["title"],
             "sent": i["delivery"] in ("sent", "unknown")} for i in fill_interrupts.for_trade(db, trade)]
    return sorted(out, key=lambda p: p["time"])


def pnl_path(fills: list[dict], minutes: list[datetime], marks: dict[datetime, float], sign: int,
             expired: bool = False) -> list[dict]:
    """Each minute's position: contracts ``held``, ``avg_cost`` per contract, ``realized`` and ``pnl`` (realized plus
    the open contracts at ``marks``, carried forward; null while anything is open with no mark yet). First in, first
    out over the fills whose minute is at or before the minute; a fill in a minute with no bar counts at the next bar,
    and any after the last bar at the last. ``expired``: what is still open at the last bar settles at $0, as the
    reconstructor books a worthless expiration with no exit fill."""
    ordered = sorted(fills, key=lambda f: (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, str(f["id"])))
    lots: deque[list[float]] = deque()
    realized, pointer, mark = 0.0, 0, None
    out = []
    for index, at in enumerate(minutes):
        final = index == len(minutes) - 1
        while pointer < len(ordered) and (final or ordered[pointer]["executed_at"].replace(second=0, microsecond=0) <= at):
            fill = ordered[pointer]
            qty, price = float(fill["contracts"]), float(fill["price"])
            if fill["side"] in OPEN_SIDES:
                lots.append([qty, price])
            else:
                while qty > EPS and lots:
                    used = min(qty, lots[0][0])
                    realized += sign * (price - lots[0][1]) * used
                    lots[0][0] -= used
                    qty -= used
                    if lots[0][0] <= EPS:
                        lots.popleft()
            pointer += 1
        if final and expired and lots:
            realized += sign * (0 - sum(lot[0] * lot[1] for lot in lots))
            lots.clear()
        mark = marks.get(at, mark)
        held = sum(lot[0] for lot in lots)
        cost = sum(lot[0] * lot[1] for lot in lots)
        if held <= EPS:
            pnl = realized if pointer else None
        else:
            pnl = None if mark is None else realized + sign * (mark * held - cost)
        out.append({"held": round(held, 6), "avg_cost": round(cost / held, 4) if held > EPS else None,
                    "realized": round(realized, 2), "pnl": None if pnl is None else round(pnl, 2)})
    return out


def build(db: Session, trade: Trade, stock_bars: Callable = _stock_bars, option_bars: Callable = _option_bars) -> dict:
    """The replay's body; ``state`` is ``ok``, or ``open``, ``too_long`` or ``no_bars`` with a ``reason``."""
    base = {"trade_id": str(trade.id), "ticker": trade.ticker, "instrument_type": trade.instrument_type}
    if trade.status == "open" or trade.closed_at is None:
        return {**base, "state": "open", "reason": "Replay opens once the trade is closed."}
    opened, closed = wall_time(trade.opened_at), wall_time(trade.closed_at)
    if (closed.date() - opened.date()).days + 1 > MAX_PATH_WINDOW_DAYS:
        return {**base, "state": "too_long", "reason": f"Held over {MAX_PATH_WINDOW_DAYS} days: too long to replay minute by minute."}

    rows = db.exec(select(TradeFill.role, Fill.id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at, Fill.raw_email_id)
                   .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id == trade.id)).all()
    fills = sorted(({"id": r.id, "role": r.role, "side": r.side, "contracts": float(r.contracts), "price": float(r.price),
                     "executed_at": wall_time(r.executed_at), "key": r.raw_email_id or str(r.id)} for r in rows),
                   key=lambda f: (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, str(f["id"])))
    pings = _pings(db, trade)
    tag = trade_ai_tags.for_trades(db, [trade.id]).get(str(trade.id))
    option = trade.instrument_type == "option"
    entries = [f for f in fills if f["role"] == "entry"]
    sign = -1 if entries and entries[0]["side"] == "sell_to_open" else 1
    ticker, status, expiration, strike, option_type = trade.ticker, trade.status, trade.expiration, trade.strike, trade.option_type
    realized_pnl = float(trade.realized_pnl) if trade.realized_pnl is not None else None
    db.close()  # the bars are network reads; no journal transaction stays open across them

    days = _days(trade, closed)
    minutes: dict[datetime, dict] = {}
    for day in days:
        on_day = [f["executed_at"] for f in fills if f["executed_at"].date() == day]
        start = min([OPEN_MINUTE] + [_minute(t) for t in on_day])
        end = max([CLOSE_MINUTE] + [_minute(t) + 1 for t in on_day])
        try:
            found = stock_bars(ticker, day)
        except Exception:  # noqa: BLE001 - a day the feed cannot read is drawn without candles
            log.warning("Replay: no minute bars for %s on %s", ticker, day, exc_info=True)
            found = []
        for bar in found or ():
            parsed = _parse(bar)
            if parsed and start <= _minute(parsed[0]) < end:
                minutes[parsed[0]] = parsed[1]
    if not minutes:
        return {**base, "state": "no_bars", "reason": "No minute bars for this trade's days yet."}

    # RTH VWAP on minute HLC3, reset each day, as Charts draws it.
    stamps = sorted(minutes)
    day_of, pv, vol = None, 0.0, 0.0
    for at in stamps:
        bar = minutes[at]
        if at.date() != day_of:
            day_of, pv, vol = at.date(), 0.0, 0.0
        bar["vwap"] = None
        if OPEN_MINUTE <= _minute(at) < CLOSE_MINUTE:
            pv += (bar["high"] + bar["low"] + bar["close"]) / 3 * bar["volume"]
            vol += bar["volume"]
            bar["vwap"] = round(pv / vol, 4) if vol else None

    # Option minutes are kept whole for the rules (the stock feed's minutes need not match the option feed's); for the
    # chart and the P&L each is folded into the first candle at or after it, so a candle's option close is the latest
    # trade by then.
    contract, option_rows, option_all, option_note = None, {}, [], None
    if option:
        contract = occ_symbol(ticker, expiration, option_type, float(strike)) if expiration and strike is not None and option_type else None
        if contract:
            try:
                found = option_bars(contract, stamps[0], stamps[-1] + timedelta(minutes=1))
            except Exception:  # noqa: BLE001 - the option pane says it has no prices; the candles still replay
                log.warning("Replay: no option bars for %s", contract, exc_info=True)
                found = []
            option_all = sorted(p for p in (_parse(bar) for bar in found or ()) if p and stamps[0] <= p[0] <= stamps[-1])
            for at, row in option_all:
                target = stamps[bisect_left(stamps, at)]
                held = option_rows.get(target)
                if held is None:
                    option_rows[target] = dict(row)
                else:
                    held.update(high=max(held["high"], row["high"]), low=min(held["low"], row["low"]), close=row["close"])
        if not option_rows:
            option_note = "The feed has no minute trades for this contract, so P&L shows only once it is closed."
    marks = {at: row["close"] * 100 for at, row in option_rows.items()} if option \
        else {at: row["close"] for at, row in minutes.items()}
    path = pnl_path(fills, stamps, marks, sign, expired=status == "expired")

    # Rules: only for a long option (every entry a buy to open), as the leak bill judges.
    cut = cut_line = None
    long_option = option and expiration is not None and entries and all(f["side"] == "buy_to_open" for f in entries)
    if long_option and option_all:
        raw = [{"t": at.replace(tzinfo=ET).isoformat(), "c": row["close"]} for at, row in option_all]
        found_cut = leak_bill.bill_trade(expiration, status == "expired", fills, raw)["cut"]
        if found_cut:
            cut = {"rule": found_cut["rule"], "time": _epoch(found_cut["at"]), "price": round(found_cut["price"], 2)}
    if long_option:
        first = min(entries, key=lambda f: (f["executed_at"], f["key"]))  # the pinged buy, as leak_bill.follow picks it
        line = fill_interrupts.cut_line({**first, "instrument_type": "option", "expiration": expiration}, [])
        if line is not None:
            crossed = None
            if option_all:
                raw = [{"t": at.replace(tzinfo=ET).isoformat(), "c": row["close"]} for at, row in option_all]
                seen = leak_bill.follow(status == "expired", fills, raw)
                if seen.get("at") is not None:
                    crossed = {"time": _epoch(seen["at"]), "state": seen["state"], "held": seen["held"], "cost": seen["cost"]}
            cut_line = {"price": round(line, 2), "crossed": crossed}

    left = sum(f["contracts"] * (1 if f["side"] in OPEN_SIDES else -1) for f in fills)
    width = 1 if len({at.date() for at in stamps}) <= ONE_MINUTE_DAYS else WIDE_MINUTES
    bars, options_out = [], []
    for index, at in enumerate(stamps):
        anchor = at.replace(minute=at.minute - at.minute % width)
        stamp, row, opt, pos = _epoch(anchor), minutes[at], option_rows.get(at), path[index]
        if bars and bars[-1]["time"] == stamp:  # the wider candle takes this minute
            last = bars[-1]
            last.update(high=max(last["high"], row["high"]), low=min(last["low"], row["low"]), close=row["close"],
                        volume=last["volume"] + row["volume"], vwap=row["vwap"], **pos)
        else:
            bars.append({"time": stamp, **row, **pos})
        if opt:
            if options_out and options_out[-1]["time"] == stamp:
                last = options_out[-1]
                last.update(high=max(last["high"], opt["high"]), low=min(last["low"], opt["low"]), close=opt["close"])
            else:
                options_out.append({"time": stamp, "open": opt["open"], "high": opt["high"], "low": opt["low"], "close": opt["close"]})

    return {
        **base, "state": "ok", "reason": None, "interval_minutes": width, "contract": contract,
        "multiplier": 100 if option else 1, "direction": "short" if sign < 0 else "long",
        "realized_pnl": realized_pnl,
        "bars": bars, "option_bars": options_out, "option_note": option_note,
        "fills": [{"id": str(f["id"]), "time": _epoch(f["executed_at"]), "entry": f["side"] in OPEN_SIDES,
                   "side": f["side"], "contracts": f["contracts"], "price": f["price"], "label": _label(f, option)} for f in fills]
        + ([{"id": "expired", "time": _epoch(stamps[-1]), "entry": False, "side": "expired", "contracts": left, "price": 0.0,
             "label": f"Expired worthless: {left:g} left"}] if status == "expired" and left > EPS else []),
        "pings": pings, "cut": cut, "cut_line": cut_line, "tag": tag,
    }
