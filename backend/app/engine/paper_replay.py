"""Paper trading on a past day (docs/copilot-lab.md § Paper replay): the owner picks a past trading day and a ticker, the
desk plays that day's minute bars forward from 9:30 ET, and he paper trades it with the paper book's own rules, any
time, nights and weekends included.

- **Bars.** The Charts history store (``chart_history``: Alpaca SIP minutes, raw, kept on disk once read): the day's file
  when it is stored, else one read through its own budget and lock, stored for next time. Never Tradier, never Robinhood.
  A day whose bars cannot be read is refused with the reason, so the desk can grey it out.
- **The replay clock.** The client plays the day; every request names the replay moment ``at`` (epoch seconds, inside
  the day's regular session). Only bars that ended by ``at`` are used: nothing after the clock prices a fill. A run's
  clock never goes back: a request before the newest thing it recorded is refused.
- **Fills: shares only.** A market order fills at the newest completed regular-session 1-minute bar's close, plus an
  assumed half-spread to buy and less one to sell (``half_spread``: the spread assumed ``SPREAD_BPS`` of the price wide,
  each half rounded up to whole cents, at least 2¢), stamped one second before the clock. A bar older than ``STALE_SECONDS`` is no price: refused. Options
  are not replayed: the app keeps no past option chain to pick a contract from and no past option quotes, so they are
  refused with that reason, never a made-up option price.
- **Limit orders, stop and target** (``paper_book``'s rules, on the replayed bars, one bar at a time). A limit is a day
  order: a buy fills on the first bar whose low plus the half-spread reaches it, at the bar's open plus the half-spread
  when that is already at or under the limit, else at the limit; a sell the other way round. A position's stop and
  target are judged on completed bars after its fill's minute; a bar touching both is the stop. With "Close
  automatically" on, the touch triggers a sale of all that is left at the next bar's open less the half-spread; off, the
  touch is only recorded. At the close every working order lapses and every open position is sold at the last bar's
  close (``flat``); leaving early sells at the clock's price.
- **Its own runs.** Each replay is a ``PaperRun`` with ``kind`` ``replay`` and ``replay_day``, so it never mixes with the
  live paper run (``paper_book.current_run`` reads live runs only) or real trades. The events and their fold are the
  paper book's own (``PaperEvent``; ``fold``, ``orders``, ``switches``, ``account``, ``stats``, ``verdict``).

Writes only ``paper_run`` and ``paper_event`` rows of replay runs. Never fills, trades, accounts or notifications.
"""
from __future__ import annotations

import json
import logging
import math
import re
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.engine import paper_book as pb
from app.engine.chart_math import ET, session_windows
from app.models import PaperEvent, PaperRun

log = logging.getLogger(__name__)

KIND = "replay"
DAYS_SHOWN = 20  # past trading days offered
SPREAD_BPS = 5.0  # the spread assumed for a replayed share fill, in basis points of the price (0.05%)
MIN_HALF_SPREAD = 0.01  # at least a 2¢ spread
STALE_SECONDS = 120  # the newest bar ended at most this long before the clock (the live book's quote freshness)
SCORE_SHOWN = 50
KEPT_DAYS = 16  # symbol-days of bars kept in memory
_kept: dict[tuple[str, date], list[dict]] = {}
OPTIONS_REFUSED = ("Options are not replayed yet: the app keeps no past option chain to pick a contract from and no past "
                   "option quotes for that minute, so there is no honest option price. Shares only.")


class ReplayError(pb.PaperError):
    pass


# --- the day and its bars --------------------------------------------------------------------------------------------

def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _hours(day: date) -> dict | None:
    from app.engine.chart_calendar import chart_calendar
    try:
        return chart_calendar.hours(day)
    except Exception:  # noqa: BLE001 -- no calendar: weekdays at the clock hours
        return None


def regular(day: date) -> tuple[int, int] | None:
    """The day's regular session in epoch seconds (the calendar's early closes), or None when the market was closed."""
    found = next((w for w in session_windows(day, _hours(day)) if w[0] == "regular"), None)
    if found is None:
        return None
    midnight = datetime(day.year, day.month, day.day, tzinfo=ET)
    return int((midnight + timedelta(minutes=found[1])).timestamp()), int((midnight + timedelta(minutes=found[2])).timestamp())


def days(now: float, count: int = DAYS_SHOWN) -> list[dict]:
    """The newest ``count`` past trading days (before today in New York), newest first."""
    out, day = [], datetime.fromtimestamp(now, ET).date()
    for _ in range(count * 2 + 10):
        day -= timedelta(days=1)
        hours = regular(day)
        if hours is not None:
            out.append({"date": day.isoformat(), "open_at": hours[0], "close_at": hours[1],
                        "early_close": datetime.fromtimestamp(hours[1], ET).hour < 16})
        if len(out) >= count:
            break
    return out


def _past_day(value, now: float) -> date:
    try:
        day = date.fromisoformat(str(value))
    except ValueError:
        raise ReplayError("Name the day as YYYY-MM-DD.") from None
    if day >= datetime.fromtimestamp(now, ET).date():
        raise ReplayError("Replay a day that is over: today's session is live paper, not replay.")
    return day


def bars(symbol: str, day: date) -> list[dict]:
    """The day's minute bars (4:00 AM to 8:00 PM, raw): the stored session, else one read through the history store's
    own budget. Raises ReplayError with the reason (the desk greys the day out with it)."""
    from app.engine.chart_history import HistoryError, chart_history
    kept = _kept.get((symbol, day))
    if kept is not None:
        return kept
    found = chart_history.stored(symbol, day)
    if found is None:
        try:
            found = chart_history.session(symbol, day)
        except HistoryError as exc:
            if exc.code in ("rate_limited", "pending"):
                raise ReplayError(f"The minute history is busy: try {symbol} on this day again in a minute.", 503) from None
            raise ReplayError(f"No minute bars for {symbol} on {day:%b %-d}: {exc}", 409) from None
        except Exception as exc:  # noqa: BLE001 -- the provider failed in a way the store does not name
            log.warning("paper replay: history read failed for %s %s: %s", symbol, day, type(exc).__name__)
            raise ReplayError(f"No minute bars for {symbol} on {day:%b %-d}: the history read failed.", 503) from None
    found = list(found or [])
    if found:  # a completed session's file never changes: keep the newest few in memory
        _kept[(symbol, day)] = found
        while len(_kept) > KEPT_DAYS:
            _kept.pop(next(iter(_kept)))
    return found


def session_bars(symbol: str, day: date) -> tuple[list[dict], tuple[int, int]]:
    """``bars`` and the regular session; refused when the market was closed or the session has no bars."""
    hours = regular(day)
    if hours is None:
        raise ReplayError(f"The market was closed on {day:%b %-d}.", 409)
    found = bars(symbol, day)
    if not any(hours[0] <= b["time"] < hours[1] for b in found):
        raise ReplayError(f"No regular-session minute bars for {symbol} on {day:%b %-d}.", 409)
    return found, hours


def suggestions(db: Session, day: date) -> list[dict]:
    """Tickers to replay on ``day``: the ones he traded that day (fills, Webull left out), then the ones he watches,
    without the tickers he set to "Not following"."""
    from app.engine import day_journal, day_replay, desk_watch
    hidden = day_journal.quiet(db)
    out: list[dict] = []
    try:
        traded = list(day_replay.traded(db, day))
    except Exception:  # noqa: BLE001 -- the fills could not be read: watched names still help
        db.rollback()
        traded = []
    try:
        watched = desk_watch.state(db)["symbols"]
    except Exception:  # noqa: BLE001
        db.rollback()
        watched = []
    for symbol, why in [*((s, "traded") for s in traded), *((s, "watched") for s in watched)]:
        if symbol not in hidden and all(o["symbol"] != symbol for o in out):
            out.append({"symbol": symbol, "why": why})
    return out


# --- prices at the replay clock --------------------------------------------------------------------------------------

def half_spread(price: float) -> float:
    """Half the spread assumed around a replayed price: ``SPREAD_BPS`` of it, halved and rounded up to whole cents (a
    fill stays on the penny grid), at least a cent."""
    return max(MIN_HALF_SPREAD, math.ceil(round(price * SPREAD_BPS / 10_000 / 2 * 100, 6)) / 100)


def _regular_bars(found: list[dict], hours: tuple[int, int]) -> list[dict]:
    return [b for b in found if hours[0] <= b["time"] < hours[1]]


def last_bar(session: list[dict], at: float) -> dict | None:
    """The newest regular-session bar that ended by ``at``."""
    done = [b for b in session if b["time"] + 60 <= at]
    return done[-1] if done else None


def _when(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, ET).strftime("%I:%M %p").lstrip("0")


def quote_at(session: list[dict], at: float, symbol: str) -> dict:
    """The replayed price at ``at``: the newest completed bar's close and the assumed bid and ask around it. Refused
    before the first bar ends and on a bar older than ``STALE_SECONDS``."""
    bar = last_bar(session, at)
    if bar is None:
        raise ReplayError("The first minute is still forming: step one bar to get a price.", 409)
    if at - (bar["time"] + 60) > STALE_SECONDS:
        raise ReplayError(f"No trade in {symbol} since the {_when(bar['time'])} bar: no fill on a stale price.", 409)
    close = float(bar["close"])
    half = half_spread(close)
    return {"close": close, "half_spread": half, "bid": round(close - half, 4), "ask": round(close + half, 4),
            "bar": bar["time"], "at": bar["time"] + 59}


def _leg(symbol: str, action: str, q: dict) -> dict:
    return {symbol: {"action": action, "bid": q["bid"], "ask": q["ask"], "price": q["ask"] if action == "buy" else q["bid"],
                     "bid_at": q["at"], "ask_at": q["at"], "close": q["close"], "half_spread": q["half_spread"], "bar": q["bar"]}}


# --- runs -------------------------------------------------------------------------------------------------------------

def runs(db: Session) -> list[PaperRun]:
    return list(db.exec(select(PaperRun).where(PaperRun.kind == KIND)
                        .order_by(col(PaperRun.started_at), col(PaperRun.id))).all())


def _run(db: Session, run_id, lock: bool = False) -> PaperRun:
    try:
        key = uuid.UUID(str(run_id))
    except ValueError:
        raise ReplayError("Name the replay.") from None
    query = select(PaperRun).where(PaperRun.id == key, PaperRun.kind == KIND)
    found = db.exec(query.with_for_update() if lock else query).first()
    if found is None:
        raise ReplayError("No such replay.", 404)
    return found


def start(db: Session, body: dict, now: float) -> PaperRun:
    day = _past_day(body.get("day"), now)
    if regular(day) is None:
        raise ReplayError(f"The market was closed on {day:%b %-d}.", 409)
    cash = pb.DEFAULT_CASH if body.get("starting_cash") is None else body.get("starting_cash")
    if isinstance(cash, bool) or not isinstance(cash, (int, float)) or not pb.MIN_CASH <= cash <= pb.MAX_CASH:
        raise ReplayError(f"Start with {pb.usd(pb.MIN_CASH)} to {pb.usd(pb.MAX_CASH)}.")
    run = PaperRun(starting_cash=round(float(cash), 2), started_at=_utc(now), kind=KIND, replay_day=day)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


class _Book:
    """One replay run's events in memory while a request works on it: each new fact is stored at once (its unique
    ``order_key`` keeps a repeat from recording twice) and appended, so a pass over many bars re-reads nothing."""

    def __init__(self, db: Session, run: PaperRun):
        self.db, self.run = db, run
        self.events = pb._events(db, run)
        self.keys = {e.order_key for e in self.events}
        self.new: list[dict] = []

    def store(self, position_id: uuid.UUID, kind: str, key: str, at: float, data: dict) -> bool:
        if key in self.keys:
            return False
        event = PaperEvent(run_id=self.run.id, position_id=position_id, kind=kind, order_key=key, effective_at=_utc(at),
                           data_json=json.dumps(data, sort_keys=True))
        self.db.add(event)
        try:
            self.db.commit()
        except IntegrityError:  # a racing request recorded this fact first: it stands once
            self.db.rollback()
            self.keys.add(key)
            self.events = pb._events(self.db, self.run)
            return False
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(event)
        self.events.append(event)
        self.events.sort(key=lambda e: (e.effective_at, e.recorded_at, str(e.id)))
        self.keys.add(key)
        return True

    def positions(self) -> list[dict]:
        return pb.fold(self.events)

    def working(self) -> list[dict]:
        return [o for o in pb.orders(self.events) if o["status"] == "working"]

    def newest(self) -> float | None:
        return max((_epoch(e.effective_at) for e in self.events), default=None)


def _clock(run: PaperRun, book: _Book, at, hours: tuple[int, int]) -> float:
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        raise ReplayError("Name the replay moment.")
    at = float(at)
    if not hours[0] <= at <= hours[1]:
        raise ReplayError("That moment is outside the replayed day's regular session.")
    newest = book.newest()
    if newest is not None and at + 1 < newest:  # a fill is stamped a second before the clock that made it
        raise ReplayError("The replay clock only goes forward.", 409)
    return at


# --- the pass over the bars ------------------------------------------------------------------------------------------

def _limit_fill(order: dict, bar: dict, closing: bool) -> float | None:
    """The per-share price a working share limit fills at on ``bar``, or None: a buy once the assumed ask reaches the
    limit (the open's ask when the bar opened through it), a sell once the assumed bid does."""
    half = half_spread(float(bar["open"]))
    if not closing:  # buying shares
        if bar["low"] + half > order["limit"] + pb.EPS:
            return None
        return round(min(bar["open"] + half, order["limit"]), 4)
    if bar["high"] - half < order["limit"] - pb.EPS:
        return None
    return round(max(bar["open"] - half, order["limit"]), 4)


def _fill_limit(book: _Book, order: dict, bar: dict) -> dict | None:
    closing = order["side"] == "close"
    per = _limit_fill(order, bar, closing)
    if per is None:
        return None
    at = bar["time"] + 59  # during the bar: its stop and target are judged from the next bar
    q = {"bid": per if closing else round(per - 2 * half_spread(per), 4), "ask": per if not closing else round(per + 2 * half_spread(per), 4),
         "close": float(bar["close"]), "half_spread": half_spread(per), "bar": bar["time"], "at": at}
    legs = _leg(order["symbol"], "sell" if closing else "buy", q)
    stock = per
    if closing:
        position = next((p for p in book.positions() if p["id"] == order["position"]), None)
        if position is None or position["status"] != "open":
            return None
        qty = min(order["quantity"], position["remaining"])
        cash = round(per * position["multiplier"] * qty, 2)
        data = {"quantity": qty, "per_share": per, "cash": cash, "legs_filled": legs, "stock": stock,
                "order_id": order["id"], "limit": order["limit"]}
        kind, position_id = "close", uuid.UUID(position["id"])
    else:
        qty = order["quantity"]
        cash = round(-per * order["multiplier"] * qty, 2)
        data = {**{k: order[k] for k in pb.SPEC_KEYS}, "quantity": qty, "per_share": -per, "cash": cash, "legs_filled": legs,
                "stock": stock, "note": order.get("note"), "stop": order.get("stop"), "target": order.get("target"),
                "order_id": order["id"], "limit": order["limit"]}
        kind, position_id = "open", uuid.UUID(order["id"])
    if not book.store(position_id, kind, f"fill:{order['id']}", at, data):
        return None
    if not closing and order.get("auto"):
        book.store(position_id, "auto", f"auto:fill:{order['id']}", at, {"on": True})
    return {"kind": "limit", "symbol": order["symbol"], "label": order["label"], "side": order["side"], "quantity": qty,
            "price": per, "at": at, "limit": order["limit"]}


def _hit(position: dict, bar: dict, only: str | None = None) -> str | None:
    """The level ``bar`` touched (a bar touching both is the stop), the setup scanner's rule."""
    long = position["bias"] == "long"
    stop = position.get("stop") if only in (None, "stop") else None
    target = position.get("target") if only in (None, "target") else None
    if stop is not None and (bar["low"] <= stop if long else bar["high"] >= stop):
        return "stop"
    if target is not None and (bar["high"] >= target if long else bar["low"] <= target):
        return "target"
    return None


def _first_bar(stamp: float) -> int:
    """The first bar judged after a fill or a switch at ``stamp``: the one after its minute."""
    return (int(stamp) // 60 + 1) * 60


def _sell_all(book: _Book, position: dict, per: float, at: float, key: str, extra: dict, q: dict) -> dict | None:
    current = next((p for p in book.positions() if p["id"] == position["id"]), None)
    if current is None or current["status"] != "open":
        return None
    qty = current["remaining"]
    cash = round(per * current["multiplier"] * qty, 2)
    data = {"quantity": qty, "per_share": per, "cash": cash, "legs_filled": _leg(current["symbol"], "sell", q),
            "stock": per, **extra}
    if not book.store(uuid.UUID(current["id"]), "close", key, at, data):
        return None
    for order in book.working():  # a closing limit for a position now closed ends with it
        if order["side"] == "close" and order["position"] == current["id"]:
            book.store(uuid.UUID(order["id"]), "cancel", f"end:{order['id']}", at, {"reason": "The position closed before it filled."})
    return {"kind": extra.get("auto") or ("flat" if extra.get("flat") else "left"), "symbol": current["symbol"],
            "label": current["label"], "side": "close", "quantity": qty, "price": per, "at": at,
            "pnl": round(cash + current["basis_left"], 2)}


def _pass(book: _Book, session: list[dict], hours: tuple[int, int], at: float, symbol: str) -> list[dict]:
    """Every completed regular-session bar of ``symbol`` up to ``at``, oldest first: a triggered automatic exit sells at
    the bar's open; then each working limit is checked against the bar; then each open position's stop and target.
    Only ``symbol``'s orders and positions are judged against its bars."""
    out: list[dict] = []
    for bar in session:
        if bar["time"] + 60 > at:
            break
        positions = {p["id"]: p for p in book.positions() if p["symbol"] == symbol}
        working = [o for o in book.working() if o["symbol"] == symbol]
        open_ = [p for p in positions.values() if p["status"] == "open"]
        if not working and not open_:
            continue
        switches = pb.switches(book.events)
        # 1. Automatic exits triggered on an earlier bar sell at this bar's open.
        for event in [e for e in book.events if e.kind == "trigger"]:
            trigger = json.loads(event.data_json)
            position = positions.get(str(event.position_id))
            switch = switches.get(str(event.position_id))
            key = f"autoexit:{event.position_id}:{trigger['auto_id']}"
            if (position is None or position["status"] != "open" or not switch or not switch["on"]
                    or switch["id"] != trigger["auto_id"] or key in book.keys or trigger["condition_at"] > bar["time"]):
                continue
            q = {"close": float(bar["open"]), "half_spread": half_spread(float(bar["open"])), "bar": bar["time"], "at": bar["time"]}
            q.update(bid=round(q["close"] - q["half_spread"], 4), ask=round(q["close"] + q["half_spread"], 4))
            found = _sell_all(book, position, q["bid"], bar["time"], key,
                              {"auto": trigger["level"], "reference": trigger["reference"], "condition_at": trigger["condition_at"]}, q)
            if found:
                out.append(found)
        # 2. Working limits placed before this bar began.
        for order in book.working():
            if order["symbol"] == symbol and order["placed_at"] <= bar["time"] and order["instrument"] == "stock":
                found = _fill_limit(book, order, bar)
                if found:
                    out.append(found)
        # 3. Stop and target on completed bars after each position's fill (or its switch).
        for position in [p for p in book.positions() if p["status"] == "open" and p["symbol"] == symbol]:
            if position.get("stop") is None and position.get("target") is None:
                continue
            switch = pb.switches(book.events).get(position["id"])
            if switch and switch["on"]:
                key = f"trigger:{position['id']}:{switch['id']}"
                if key in book.keys or bar["time"] < _first_bar(max(position["opened_at"], switch["at"])):
                    continue
                level = _hit(position, bar)
                if level:
                    book.store(uuid.UUID(position["id"]), "trigger", key, bar["time"] + 60,
                               {"level": level, "reference": position[level], "condition_at": bar["time"] + 60,
                                "bar_start": bar["time"], "low": bar["low"], "high": bar["high"], "auto_id": switch["id"]})
                continue
            for level in ("stop", "target"):
                key = f"touch:{position['id']}:{level}"
                if position.get(level) is None or key in book.keys or bar["time"] < _first_bar(position["opened_at"]):
                    continue
                if _hit(position, bar, only=level):
                    book.store(uuid.UUID(position["id"]), "touch", key, bar["time"] + 60,
                               {"level": level, "reference": position[level], "condition_at": bar["time"] + 60,
                                "bar_start": bar["time"], "low": bar["low"], "high": bar["high"]})
                    out.append({"kind": "touch", "symbol": position["symbol"], "label": position["label"], "level": level,
                                "at": bar["time"] + 60, "price": position[level]})
    return out


def _load(db: Session, run: PaperRun, symbols: set[str]) -> tuple[dict[str, list[dict]], tuple[int, int]]:
    hours = regular(run.replay_day)
    if hours is None:
        raise ReplayError("The replayed day has no regular session.", 409)
    return {s: _regular_bars(session_bars(s, run.replay_day)[0], hours) for s in sorted(symbols)}, hours


def _symbols(book: _Book) -> set[str]:
    return {p["symbol"] for p in book.positions() if p["status"] == "open"} | {o["symbol"] for o in book.working()}


def _advance(db: Session, run: PaperRun, book: _Book, at: float, also: str | None = None) -> tuple[list[dict], dict[str, list[dict]], tuple[int, int] | None]:
    """Work each symbol with an open position or a working order (and ``also``) bar by bar up to ``at``, before anything
    new is recorded at ``at``, so nothing he does at the clock undoes what the bars before it already did."""
    symbols = _symbols(book) | ({also} if also else set())
    if not symbols:
        return [], {}, regular(run.replay_day)
    sessions, hours = _load(db, run, symbols)
    found = []
    for symbol in sorted(symbols):
        found += _pass(book, sessions[symbol], hours, at, symbol)
    return found, sessions, hours


def step(db: Session, body: dict, now: float) -> dict:
    """Bring the run to the replay clock ``at``: work the bars up to it; at the close (or with ``end``, when he leaves)
    end the orders and sell what is open."""
    run = _run(db, body.get("run_id"), lock=True)
    book = _Book(db, run)
    hours = regular(run.replay_day)
    if hours is None:
        raise ReplayError("The replayed day has no regular session.", 409)
    at = _clock(run, book, body.get("at"), hours)
    found, sessions, hours = _advance(db, run, book, at)
    if sessions and (at >= hours[1] or body.get("end")):
        reason = "flat" if at >= hours[1] else "left"
        for symbol in sorted(sessions):
            found += _flatten_symbol(book, sessions[symbol], at, reason, symbol)
    db.commit()
    return {"happened": found, **view(db, run, at)}


def _flatten_symbol(book: _Book, session: list[dict], at: float, reason: str, symbol: str) -> list[dict]:
    """End the replay of ``symbol`` at ``at``: its working orders lapse at the close (or end when he leaves) and each
    open position sells at the newest completed bar's close less the half-spread."""
    out = []
    for order in book.working():
        if order["symbol"] == symbol:
            book.store(uuid.UUID(order["id"]), "lapse" if reason == "flat" else "cancel", f"end:{order['id']}", at,
                       {"reason": "A day order ends at the close." if reason == "flat" else "You left the replay."})
    bar = last_bar(session, at)
    if bar is None:
        return out
    close = float(bar["close"])
    q = {"close": close, "half_spread": half_spread(close), "bar": bar["time"], "at": bar["time"] + 59}
    q.update(bid=round(close - q["half_spread"], 4), ask=round(close + q["half_spread"], 4))
    for position in [p for p in book.positions() if p["status"] == "open" and p["symbol"] == symbol]:
        found = _sell_all(book, position, q["bid"], min(at, bar["time"] + 59), f"{reason}:{position['id']}", {reason: True}, q)
        if found:
            out.append(found)
    return out


# --- orders at the replay clock --------------------------------------------------------------------------------------

def _spec(body: dict, day: date) -> dict:
    if body.get("instrument") not in (None, "stock"):
        raise ReplayError(OPTIONS_REFUSED, 409)
    return pb.contract({**body, "instrument": "stock"}, day)


def order(db: Session, body: dict, now: float) -> dict:
    """A replay order at the clock ``at``: ``action`` open (buy shares) or close (sell an open position), market or
    ``order_type`` limit; ``preview`` answers what it would fill at (or hold) and stores nothing."""
    preview = bool(body.get("preview"))
    run = _run(db, body.get("run_id"), lock=not preview)
    book = _Book(db, run)
    hours = regular(run.replay_day)
    if hours is None:
        raise ReplayError("The replayed day has no regular session.", 409)
    at = _clock(run, book, body.get("at"), hours)
    if at >= hours[1]:
        raise ReplayError("The replayed day is over: the session closed.", 409)
    closing = body.get("action") == "close"
    positions = book.positions()
    if closing:
        try:
            position_id = str(uuid.UUID(str(body.get("position_id"))))
        except ValueError:
            raise ReplayError("Name the paper position.") from None
        position = next((p for p in positions if p["id"] == position_id), None)
        if position is None or position["status"] != "open":
            raise ReplayError("That paper position is not open.", 409)
        spec = {k: position[k] for k in pb.SPEC_KEYS}
    else:
        spec = _spec(body, run.replay_day)
        position = None
    session = _regular_bars(session_bars(spec["symbol"], run.replay_day)[0], hours)
    happened = [] if preview else _advance(db, run, book, at, also=spec["symbol"])[0]
    if not preview:
        positions = book.positions()
        if closing:
            position = next((p for p in positions if p["id"] == position["id"]), None)
            if position is None or position["status"] != "open":
                db.commit()
                return {"filled": None, "happened": happened, "closed_meanwhile": True, **view(db, run, at)}
    q = quote_at(session, at, spec["symbol"])
    working = book.working()
    acct = pb.account(run, positions, working)
    limit = pb._money(body.get("limit_price")) if body.get("order_type") == "limit" else None
    if body.get("order_type") == "limit" and limit is None:
        raise ReplayError("Name the limit price.")
    if closing:
        held = pb._held(working, position["id"])
        free = position["remaining"] - held
        if free <= 0:
            raise ReplayError(f"All {position['remaining']:,} are held for a working limit order: cancel it to sell another way.", 409)
        qty = free if body.get("quantity") is None else pb._quantity(body.get("quantity"), free)
    else:
        qty = pb._quantity(body.get("quantity"))
    marketable = limit is None or (limit >= q["ask"] - pb.EPS if not closing else limit <= q["bid"] + pb.EPS)
    per = (q["bid"] if closing else -q["ask"]) if marketable else None
    shown = {"label": spec["label"], "quantity": qty, "close": q["close"], "half_spread": q["half_spread"], "bid": q["bid"],
             "ask": q["ask"], "bar": q["bar"], "spread_bps": SPREAD_BPS, "buying_power": acct["buying_power"]}
    if not closing:
        stop, target = pb._levels(body, spec["bias"], q["close"])
        reserve = round((limit if limit is not None else q["ask"]) * qty, 2)
        if reserve > acct["buying_power"] + 0.005:
            raise ReplayError(f"Not enough paper buying power: this needs {pb.usd(reserve)} and you have {pb.usd(acct['buying_power'])}.", 409)
        shown["buying_power_after"] = round(acct["buying_power"] - reserve, 2)
    if marketable:
        cash = round(per * qty, 2)
        shown.update(per_share=per, cash=cash, fills_now=True)
        if closing:
            basis = position["basis_left"] if qty == position["remaining"] else round(position["cash"] * qty / position["quantity"], 2)
            shown["pnl"] = round(cash + basis, 2)
    else:
        shown.update(limit=limit, fills_now=False, reserve=0.0 if closing else round(limit * qty, 2), expires_at=hours[1])
    if preview:
        return {"preview": shown}
    key = pb._key(body)
    if key in book.keys:
        db.commit()
        return {"filled": None, "working": None, "duplicate": True, "happened": happened, **view(db, run, at)}
    if not marketable:
        order_id = uuid.uuid4()
        extra = {"position": position["id"]} if closing else {"note": pb._note(body), "stop": stop, "target": target,
                                                              "auto": bool(body.get("auto"))}
        data = {**spec, **extra, "side": "close" if closing else "open", "pays": not closing, "limit": limit,
                "quantity": qty, "reserve": shown["reserve"], "expires_at": float(hours[1])}
        book.store(order_id, "order", key, at, data)
        db.commit()
        return {"filled": None, "working": {**shown, "id": str(order_id)}, "happened": happened, **view(db, run, at)}
    legs = _leg(spec["symbol"], "sell" if closing else "buy", q)
    if closing:
        data = {"quantity": qty, "per_share": per, "cash": shown["cash"], "legs_filled": legs, "stock": q["close"]}
        if limit is not None:
            data["limit"] = limit
        book.store(uuid.UUID(position["id"]), "close", key, q["at"], data)
    else:
        position_id = uuid.uuid4()
        data = {**spec, "quantity": qty, "per_share": per, "cash": shown["cash"], "legs_filled": legs, "stock": q["close"],
                "note": pb._note(body), "stop": stop, "target": target}
        if limit is not None:
            data["limit"] = limit
        book.store(position_id, "open", key, q["at"], data)
        if body.get("auto") and (stop is not None or target is not None):
            book.store(position_id, "auto", f"auto:{key}", q["at"], {"on": True})
    db.commit()
    return {"filled": {**shown, "at": q["at"]}, "working": None, "happened": happened, **view(db, run, at)}


def cancel(db: Session, body: dict, now: float) -> dict:
    run = _run(db, body.get("run_id"), lock=True)
    book = _Book(db, run)
    hours = regular(run.replay_day)
    at = _clock(run, book, body.get("at"), hours)
    happened = _advance(db, run, book, at)[0]  # a fill on an earlier bar stands
    order_id = str(body.get("order_id") or "")
    found = next((o for o in book.working() if o["id"] == order_id), None)
    if found is None:
        db.commit()
        raise ReplayError("That paper order is no longer working: it filled or ended before this moment.", 409)
    book.store(uuid.UUID(order_id), "cancel", f"end:{order_id}", at, {"reason": "You canceled it."})
    db.commit()
    return {"happened": happened, **view(db, run, at)}


def set_auto(db: Session, body: dict, now: float) -> dict:
    run = _run(db, body.get("run_id"), lock=True)
    book = _Book(db, run)
    hours = regular(run.replay_day)
    at = _clock(run, book, body.get("at"), hours)
    happened = _advance(db, run, book, at)[0]  # an exit an earlier bar triggered stands
    position_id = str(body.get("position_id") or "")
    position = next((p for p in book.positions() if p["id"] == position_id), None)
    if position is None or position["status"] != "open":
        db.commit()
        raise ReplayError("That paper position is not open: it closed before this moment.", 409)
    if position.get("stop") is None and position.get("target") is None:
        raise ReplayError("This position has no stop or target to close at.", 409)
    on = body.get("on") is True
    current = pb.switches(book.events).get(position_id)
    if bool(current and current["on"]) != on:
        book.store(uuid.UUID(position_id), "auto", f"auto:{pb._key(body)}", at, {"on": on})
    db.commit()
    return {"happened": happened, **view(db, run, at)}


# --- what the desk shows ---------------------------------------------------------------------------------------------

def view(db: Session, run: PaperRun, at: float) -> dict:
    """The replay run at the clock ``at``: its account, open positions marked at the newest completed bar's close,
    working orders, closed trades and the run's own score."""
    book = _Book(db, run)
    positions = book.positions()
    working = book.working()
    acct = pb.account(run, positions, working)
    open_ = [p for p in positions if p["status"] == "open"]
    marks: dict[str, dict] = {}
    hours = regular(run.replay_day)
    for symbol in sorted({p["symbol"] for p in open_}):
        try:
            bar = last_bar(_regular_bars(session_bars(symbol, run.replay_day)[0], hours), at) if hours else None
        except ReplayError:
            bar = None
        if bar is not None:
            marks[symbol] = {"last": float(bar["close"]), "at": bar["time"] + 60}
    switches = pb.switches(book.events)
    triggered = {str(e.position_id) for e in book.events if e.kind == "trigger"}
    touched = {}
    for e in book.events:
        if e.kind == "touch":
            touched.setdefault(str(e.position_id), {})[json.loads(e.data_json)["level"]] = _epoch(e.effective_at)
    shown = []
    for p in reversed(open_):
        extra = {"auto": bool(switches.get(p["id"], {}).get("on")), "touched": touched.get(p["id"], {}),
                 "exiting": p["id"] in triggered and bool(switches.get(p["id"], {}).get("on")), "held": pb._held(working, p["id"])}
        shown.append(pb._position_view(p, marks, extra))
    priced = [s["mark"] for s in shown if s["mark"] is not None]
    equity = round(acct["cash"] + sum(m["value"] for m in priced), 2) if len(priced) == len(shown) else None
    closed = [p for p in positions if p["status"] != "open"]
    score = pb.stats([p["realized"] for p in closed], [(run.replay_day, p["realized"]) for p in closed])
    return {"run": _run_view(run, positions), "at": at,
            "account": {**acct, "equity": equity, "pnl": None if equity is None else round(equity - run.starting_cash, 2)},
            "positions": shown, "orders": [pb._order_view(o) for o in reversed(working)],
            "closed": [_closed_view(p, run) for p in sorted(closed, key=lambda p: p["closed_at"], reverse=True)],
            "score": score, "ended": hours is not None and at >= hours[1]}


def _run_view(run: PaperRun, positions: list[dict]) -> dict:
    hours = regular(run.replay_day)
    return {"id": str(run.id), "day": run.replay_day.isoformat(), "starting_cash": run.starting_cash,
            "started_at": _epoch(run.started_at), "open_at": hours[0] if hours else None, "close_at": hours[1] if hours else None,
            "symbols": sorted({p["symbol"] for p in positions}),
            "realized": round(sum(p["realized"] for p in positions), 2),
            "trades": sum(1 for p in positions if p["status"] != "open"),
            "left_open": sum(1 for p in positions if p["status"] == "open")}


def _closed_view(p: dict, run: PaperRun) -> dict:
    out = pb._position_view(p, None)
    last = p["exits"][-1] if p["exits"] else {}
    if last.get("flat"):
        out["verdict"] = {"kind": "flat", "text": "Sold at the replayed day's close"}
    elif last.get("left"):
        out["verdict"] = {"kind": "left", "text": "Sold when you left the replay"}
    out["day"] = run.replay_day.isoformat()
    out["run_id"] = str(run.id)
    return out


def scorecard(db: Session) -> dict:
    """Every replay run's closed trades, apart from live paper and real trades: P&L, win rate, each trade with its note
    and the day replayed; and each run."""
    all_runs = runs(db)
    trades, listed = [], []
    for run in all_runs:
        positions = pb.fold(pb._events(db, run))
        listed.append(_run_view(run, positions))
        trades += [(run, p) for p in positions if p["status"] != "open"]
    stats = pb.stats([p["realized"] for _, p in trades], [(run.replay_day, p["realized"]) for run, p in trades])
    trades.sort(key=lambda rp: (rp[1]["closed_at"], rp[0].started_at), reverse=True)
    return {"score": stats, "runs": list(reversed(listed)),
            "trades": [_closed_view(p, run) for run, p in trades[:SCORE_SHOWN]]}


TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def ticker(value) -> str:
    symbol = str(value or "").strip().upper()
    if not TICKER.match(symbol):
        raise ReplayError("Name a ticker.")
    return symbol
