"""The Copilot desk's Context pane (docs/copilot-lab.md#the-desk): three reads for the open thread, keyed by its saved
investigation and its symbol, or by the symbol alone (``SYMBOL_PREFIX``): a position or plan opened with no saved
conversation reads its symbol's plan (in a position first, else armed) and, without a linked trade, its open trade.

- ``picture``: the thread's symbol as a PNG, drawn by the ping-picture renderer (``chart_render``), on one of
  ``TIMEFRAMES``: ``2m`` today's minutes (the same cached chart-feed read as a ping picture, ``ping_images.today_bars``),
  ``15m`` today and the ``SESSIONS_15M - 1`` completed sessions before it, ``1D`` the last ``DAILY_DAYS`` of daily bars.
  The intraday views also mark the plan's entry and invalidation lines, the owner's fills today, and today's phone
  pings sent (violet) and Radar hits (blue) on the symbol, so an alert can be judged against what price did next. The
  read and the drawing run on a worker with a ``BUDGET_SECONDS`` budget, and the renderer caches by content, so a
  repeat costs nothing. No bars, a failed read or a run past the budget is ``Unavailable`` with a reason, never a blank
  picture.
- ``timeline``: one list, newest first, of what touched the thread: its plan's level alerts (armed, hit), time stop and
  revisit jobs (the investigation-linked readers ``LinkedActivity`` shows), the fills of the trade linked to its plan,
  and for its symbol over the last ``RECENT_DAYS``: thesis-watch triggers, phone pings (a ping for one of the thread's
  own alerts or its time stop rides on that row), and today's ``decision`` journal entries. Each source is read on its
  own, so one failing names itself in ``unavailable`` and the rest still show.
- ``history``: the owner's own record at the plan's invalidation, from ``copilot_review.level_history`` (the engine
  behind the copilot's ``get_level_history``), as won / not-won counts for the trades that crossed it while held and one
  sentence built from those counts. No plan, or a plan without an invalidation, says what is missing.
- ``symbol_thread``: the thread for ``SYMBOL_PREFIX`` + a symbol, so the routes take it where they take an investigation.
- ``chart``: the cockpit centre's interactive chart as data (the same reads as ``picture``, bounded to ``MAX_BARS``
  candles and ``MAX_MARKS`` marks): candles (2m today with the pre-market and after-hours flagged), the plan's levels,
  the owner's fills, today's pings and Radar hits, and the time stop still ahead. The picture stays for the phone pings.
- ``market_picture``: the Briefing's chart, today's ``MARKET`` (QQQ) minutes with the day's fills and phone pings sent
  as dots, under the picture route's reserved ``MARKET_ID``.

Read-only: nothing here arms, sends or writes. No account numbers or ids beyond the investigation's own.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
import logging
import threading
import uuid

from sqlmodel import Session, select

from app.engine import chart_math, chart_render, copilot_plans, ping_images
from app.engine.chart_math import ET, REGULAR_OPEN, chart_bars
from app.engine.chart_render import Chart, Mark, Time
from app.models import (Account, CaptureLink, CopilotInvestigation, DayJournalEntry, Fill, LevelAlert, LevelAlertEvent,
                        PhonePing, PlanTimeStop, ResearchJob, ThesisWatchTrigger, Trade, TradeCapture, TradeFill)

log = logging.getLogger(__name__)

BUDGET_SECONDS = 6.0
MAX_FILLS = 40  # fills marked on the picture
MAX_ROWS = 40  # timeline rows
RECENT_DAYS = 7  # the symbol's thesis triggers and pings this far back
DAY_BARS = 24 * 60
TIMEFRAMES = ("2m", "15m", "1D")
SESSIONS_15M = 3  # today and the completed sessions before it on the 15m picture
DAILY_DAYS = 120  # calendar days of daily bars on the 1D picture
WHAT = {"2m": "minute bars for today", "15m": "15-minute bars", "1D": "daily bars"}
# Today's events on the thread's symbol, as dots on the intraday pictures: (label of the first, colour).
EVENT_TONE = {"fill": ("FILL", "amber"), "ping": ("PING", "violet"), "radar": ("RADAR", "blue")}
WORKERS = 2
_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="desk-picture")
# A read still running past its budget keeps its worker; a request finding none free says so at once rather than queueing.
_free = threading.BoundedSemaphore(WORKERS)

OPENING = {"buy", "buy_to_open", "sell_to_open"}
CONDITION = {"touches": "touches", "crosses": "crosses", "closes_beyond": "closes beyond"}
ROLE = {"entry": "Entry", "invalidation": "Invalidation"}
# The Briefing's chart: the market, read through the picture route under this reserved id (investigation ids are UUIDs).
MARKET_ID = "market"
MARKET = "QQQ"
# A thread named by its symbol alone, read through the same routes as ``symbol:NBIS``.
SYMBOL_PREFIX = "symbol:"


class Unavailable(Exception):
    """The picture cannot be shown; ``str(exc)`` says why, in words for the owner."""


def investigation(db: Session, investigation_id: str) -> CopilotInvestigation | None:
    try:
        key = uuid.UUID(investigation_id)
    except ValueError:
        return None
    return db.get(CopilotInvestigation, key)


@dataclass(frozen=True)
class SymbolThread:
    """A thread named by its symbol: ``id`` is the investigation of the symbol's plan, or empty when it has none."""
    id: str
    symbol: str


def symbol_thread(db: Session, symbol: str) -> SymbolThread:
    """The symbol's plan as the Plans board shows it (no quote read): one in a position first, else the nearest armed."""
    rows = [p for p in copilot_plans.board(db, quotes=lambda _symbols: ({}, None, None))["plans"] if p["symbol"] == symbol]
    found = min(rows, key=lambda p: p["position"] != "in_position", default=None)
    return SymbolThread(found["investigation_id"] if found else "", symbol)


def _epoch_utc(moment: datetime | None) -> int | None:
    return None if moment is None else int(moment.replace(tzinfo=UTC).timestamp())


def _epoch_ny(moment: datetime | None) -> int | None:
    return None if moment is None else int(moment.replace(tzinfo=ET).timestamp())


def _price(value: float) -> str:
    return f"{value:,.2f}"


# ------------------------------------------------------------------ the thread's plan


def plan(db: Session, investigation_id: str) -> dict | None:
    """The investigation's latest plan as the Plans board groups it (its parts made within ``PLAN_WINDOW`` of the
    newest), armed or not: ``entry`` and ``invalidation`` alerts, the time ``stop``, the plan ``capture`` and the
    ``direction`` (the capture's side, else entry above invalidation is long). None when it has no plan."""
    alerts = db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", LevelAlert.source_id == investigation_id,
                                              LevelAlert.plan_role.is_not(None))).all()
    stops = db.exec(select(PlanTimeStop).where(PlanTimeStop.investigation_id == investigation_id)).all()
    if not alerts and not stops:
        return None
    newest = max([a.created_at for a in alerts] + [s.created_at for s in stops])
    since = newest - copilot_plans.PLAN_WINDOW
    recent = sorted((a for a in alerts if a.created_at >= since), key=lambda a: a.created_at)
    entry = next((a for a in reversed(recent) if a.plan_role == "entry"), None)
    invalidation = next((a for a in reversed(recent) if a.plan_role == "invalidation"), None)
    stop = max((s for s in stops if s.created_at >= since), key=lambda s: s.created_at, default=None)
    symbol = (entry or invalidation or stop).symbol
    capture = None
    if stop is not None:
        capture = db.exec(select(TradeCapture).where(TradeCapture.client_id == stop.client_id)).first()
    if capture is None:
        capture = db.exec(select(TradeCapture).where(
            TradeCapture.setup_label == copilot_plans.PLAN_LABEL, TradeCapture.mode == "discretionary",
            TradeCapture.underlying == symbol, TradeCapture.received_at >= since, TradeCapture.received_at <= newest)
            .order_by(TradeCapture.received_at.desc())).first()
    if capture is not None:
        direction = "long" if capture.side in copilot_plans.LONG_SIDES else "short"
    elif entry is not None and invalidation is not None:
        direction = "long" if entry.price > invalidation.price else "short"
    else:
        direction = None
    return {"symbol": symbol, "entry": entry, "invalidation": invalidation, "stop": stop, "capture": capture,
            "direction": direction, "stops": stops}


def _linked_fills(db: Session, capture: TradeCapture | None) -> list[Fill]:
    """The fills of the trade the plan's capture is linked to (the link's anchored fill, resolved to its trade now)."""
    if capture is None:
        return []
    link = db.exec(select(CaptureLink).where(CaptureLink.capture_id == capture.id, CaptureLink.unlinked_at.is_(None))).first()
    if link is None:
        return []
    anchor = db.exec(select(TradeFill.trade_id).join(Fill, Fill.id == TradeFill.fill_id).where(
        Fill.raw_email_id == link.source_key, Fill.account_id == link.account_id)).first()
    if anchor is None:
        return []
    return list(db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id).where(TradeFill.trade_id == anchor)
                        .order_by(Fill.executed_at)).all())


def _open_fills(db: Session, symbol: str) -> list[Fill]:
    """The fills of the symbol's open trades (Webull left out), for a thread named by its symbol with no linked trade."""
    webull = select(Account.id).where(Account.broker == "webull")
    trades = select(Trade.id).where(Trade.ticker == symbol, Trade.status == "open", Trade.account_id.not_in(webull))
    return list(db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id).where(TradeFill.trade_id.in_(trades))
                        .order_by(Fill.executed_at).limit(MAX_ROWS)).all())


def _not_webull():
    webull = select(Account.id).where(Account.broker == "webull")
    return Fill.account_id.not_in(webull)


# ------------------------------------------------------------------ picture


def _fill_marks(fills: list[Fill], first: int) -> tuple[tuple[Mark, ...], tuple[Time, ...]]:
    """A stock fill at its price; an option fill at the underlying's price when the fill recorded it, else a line at
    its time, amber (pings are violet, Radar blue). The first opening and the first closing fill are labelled IN and
    OUT; the rest are unlabelled dots. A fill before the first bar shown (a pre-market fill once the regular session
    has bars) is left off."""
    marks: list[Mark] = []
    times: list[Time] = []
    said: set[str] = set()
    for fill in fills:
        at = _epoch_ny(fill.executed_at)
        if at is None or at < first:
            continue
        label = "IN" if fill.side in OPENING else "OUT"
        tone = "amber"
        text = "" if label in said else label
        said.add(label)
        price = float(fill.price) if fill.instrument_type == "stock" else (
            float(fill.underlying_price_at_fill) if fill.underlying_price_at_fill else None)
        if price is not None:
            marks.append(Mark(at, price, text, tone))
        else:
            times.append(Time(at, text, tone))
    return tuple(marks), tuple(times)


def _budgeted(symbol: str, draw, budget: float, what: str = WHAT["2m"]) -> bytes:
    """Runs ``draw`` on a worker within ``budget`` seconds; no bars (``None``), a failure or a run past the budget is
    ``Unavailable`` with the reason, naming ``what`` was read."""
    free = _free

    def run() -> bytes | None:
        try:
            return draw()
        finally:
            free.release()

    if not free.acquire(blocking=False):
        raise Unavailable("Earlier chart reads are still running; try again in a moment.")
    try:
        future = _pool.submit(run)
    except RuntimeError:  # the pool is shut down (interpreter exit)
        free.release()
        raise Unavailable("The chart picture is unavailable right now.") from None
    try:
        png = future.result(timeout=budget)
    except FutureTimeout:
        future.cancel()
        raise Unavailable("The bars took too long to read; try again in a moment.") from None
    except Exception:  # noqa: BLE001 - a failed read is an unavailable picture, never an error page
        log.warning("Desk picture for %s failed", symbol, exc_info=True)
        raise Unavailable(f"The {symbol} {what} could not be read.") from None
    if png is None:
        raise Unavailable(f"No {symbol} {what} yet.")
    return png


def _today_shown(read, symbol: str, now: float) -> list[dict]:
    """Today's minutes up to ``now``: the regular session once it has bars, before that the pre-market; after the
    close, the after-hours minutes past the session's last bar follow it."""
    today = datetime.fromtimestamp(now, ET).date()
    found_bars = [b for b in read(symbol) if b["time"] <= now][-DAY_BARS:]
    found_bars = [b for b in found_bars if datetime.fromtimestamp(b["time"], ET).date() == today]
    regular = [b for b in found_bars if not b.get("extended")]
    if not regular:
        return found_bars
    return regular + [b for b in found_bars if b.get("extended") and b["time"] > regular[-1]["time"]]


def _candles(bars: list[dict], limit: int = chart_render.CANDLE_LIMIT) -> list[dict]:
    """Today's minutes as candles of two minutes or more, as many as fit ``limit`` (the renderer draws a line past it):
    each candle opens at its first minute, closes at its last, with their high, low and volume; extended only when all
    of its minutes are."""
    if not bars:
        return []
    step = max(2, -(-len(bars) // limit)) * 60
    first = bars[0]["time"]
    out: list[dict] = []
    for bar in bars:
        slot = first + (bar["time"] - first) // step * step
        last = out[-1] if out else None
        if last is None or last["_slot"] != slot:
            out.append({**bar, "_slot": slot})
            continue
        last.update(high=max(last["high"], bar["high"]), low=min(last["low"], bar["low"]), close=bar["close"],
                    volume=(last.get("volume") or 0) + (bar.get("volume") or 0))
        if "extended" in last or "extended" in bar:
            last["extended"] = bool(last.get("extended")) and bool(bar.get("extended"))
    return [{k: v for k, v in b.items() if k != "_slot"} for b in out][-limit:]


def _day_title(symbol: str, shown: list[dict]) -> str:
    """The symbol, saying so when the regular session's bars are followed by after-hours ones."""
    return f"{symbol} + AFTER HOURS" if shown and not shown[0].get("extended") and shown[-1].get("extended") else symbol


def fifteen_bars(symbol: str) -> list[dict]:
    """Regular-session 15-minute bars: today's from the chart feed (each with its RVol, C2.4, when the stored baseline is
    ready), and up to ``SESSIONS_15M - 1`` completed sessions before it from the chart history (from disk, or fetched
    once and stored), split-adjusted like a chart page."""
    from app.engine.chart_adjust import adjust_minutes
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    from app.engine.chart_history import HistoryError, chart_history
    from app.engine.chart_splits import UNAVAILABLE
    data = chart_feed.workspace(symbol, ["15m"], [], "regular", calendar=chart_calendar, quotes=False,
                                volume_profile=chart_history.volume_profile)
    today = list(((data.get("panels") or {}).get("15m") or {}).get("bars") or [])
    info = chart_history.splits.get(symbol) if chart_history.splits else UNAVAILABLE
    earlier: list[list[dict]] = []
    day = datetime.now(ET).date()
    for _ in range(10):  # calendar days back, past a weekend and a holiday
        if len(earlier) >= SESSIONS_15M - 1:
            break
        day -= timedelta(days=1)
        hours = chart_calendar.hours(day) if day.weekday() < 5 else None
        if day.weekday() >= 5 or (hours is not None and hours["status"] == "closed"):
            continue  # weekends and holidays cost no history read
        try:
            minutes = adjust_minutes(chart_history.session(symbol, day), day, info["splits"])
        except HistoryError:
            break  # the older sessions are a bonus; today's bars still show
        if minutes:
            earlier.insert(0, chart_bars(minutes, [], "15m", "regular", {day: hours}))
    return [b for session in earlier for b in session] + today


def daily_bars(symbol: str) -> list[dict]:
    """Daily bars from the chart feed (whole history once per New York date, kept in memory)."""
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    data = chart_feed.workspace(symbol, ["1D"], [], "regular", calendar=chart_calendar, quotes=False)
    return list(((data.get("panels") or {}).get("1D") or {}).get("bars") or [])


def _event_marks(events: list[dict], shown: list[dict]) -> list[Mark]:
    """``events`` (``kind``, ``at``) as dots at the close of the bar of their time, the first of each kind labelled; one
    before the first bar shown is left off."""
    marks: list[Mark] = []
    said: set[str] = set()
    for event in sorted((e for e in events if e["kind"] in EVENT_TONE), key=lambda e: e["at"])[:MAX_FILLS]:
        bar = next((b for b in reversed(shown) if b["time"] <= event["at"]), None)
        if bar is None:
            continue
        label, colour = EVENT_TONE[event["kind"]]
        marks.append(Mark(int(event["at"]), float(bar["close"]), "" if label in said else label, colour))
        said.add(label)
    return marks


def picture(db: Session, inv: CopilotInvestigation | SymbolThread, now: float, bars=None, budget: float = BUDGET_SECONDS,
            timeframe: str = "2m", events: list[dict] = ()) -> bytes:
    """The thread's symbol on ``timeframe``: ``2m`` today's minutes (the regular session once it has bars, before that
    the pre-market), ``15m`` recent sessions, ``1D`` the last ``DAILY_DAYS``. The intraday ones carry its plan's levels,
    the owner's fills today and ``events`` (today's pings sent and Radar hits on the symbol, ``kind``/``at``). ``bars``
    replaces the timeframe's read. Raises ``Unavailable`` with the reason."""
    symbol = inv.symbol
    if not symbol:
        raise Unavailable("This thread has no symbol, so there is no chart.")
    if timeframe not in TIMEFRAMES:
        raise Unavailable(f"No {timeframe} chart; the choices are {', '.join(TIMEFRAMES)}.")
    found = plan(db, str(inv.id)) if inv.id else None
    levels = tuple(sorted((a.plan_role, float(a.price)) for a in (found["entry"], found["invalidation"]) if a)) if found else ()
    today = datetime.fromtimestamp(now, ET).date()
    start = datetime.combine(today, datetime.min.time())
    fills = list(db.exec(select(Fill).where(Fill.ticker == symbol, Fill.executed_at >= start,
                                            Fill.executed_at < start + timedelta(days=1), _not_webull())
                         .order_by(Fill.executed_at).limit(MAX_FILLS)).all())
    read = bars or {"2m": ping_images.today_bars, "15m": fifteen_bars, "1D": daily_bars}[timeframe]

    def draw() -> bytes | None:
        if timeframe == "2m":
            minutes = _today_shown(read, symbol, now)
            shown = _candles(minutes)  # the marks still sit on their own minute's price
        elif timeframe == "15m":
            shown = minutes = [b for b in read(symbol) if b["time"] <= now]
        else:
            shown = minutes = [b for b in read(symbol) if now - DAILY_DAYS * 86400 <= b["time"] <= now]
        if not shown:
            return None
        note = f"NOW {_price(shown[-1]['close'])}"
        title = _day_title(symbol, shown) if timeframe == "2m" else f"{symbol} {timeframe}"
        if timeframe == "1D":
            return chart_render.render(Chart(title=title, note=note, bars=tuple(shown)))
        marks, times = _fill_marks(fills, shown[0]["time"])
        return chart_render.render(Chart(title=title, note=note, bars=tuple(shown), levels=ping_images._plan_level_marks(levels),
                                         marks=marks + tuple(_event_marks(list(events), minutes)), times=times))

    return _budgeted(symbol, draw, budget, WHAT[timeframe])


def market_picture(events: list[dict], now: float, bars=None, budget: float = BUDGET_SECONDS) -> bytes:
    """The Briefing's chart: today's ``MARKET`` minutes with the day's fills (any symbol, amber) and phone pings sent
    (violet) as dots on the bar of their minute, the first of each labelled FILL or PING. ``events`` are the session
    timeline's rows (``kind``, ``at``); one before the first bar shown is left off. Raises ``Unavailable``."""
    read = bars or ping_images.today_bars

    def draw() -> bytes | None:
        minutes = _today_shown(read, MARKET, now)
        shown = _candles(minutes)
        if not shown:
            return None
        marks = _event_marks([e for e in events if e["kind"] in ("fill", "ping")], minutes)
        return chart_render.render(Chart(title=_day_title(MARKET, shown), note=f"NOW {_price(shown[-1]['close'])}", bars=tuple(shown), marks=tuple(marks)))

    return _budgeted(MARKET, draw, budget)


# ------------------------------------------------------------------ chart (the desk's interactive chart, as data)


STEP = {"2m": 120, "15m": 900, "1D": 86400}
MAX_BARS = 600  # one chart read's bars: a whole 04:00-20:00 day of 2m candles is 480
MAX_MARKS = 60
LEVEL_WORD = {"entry": "Entry", "invalidation": "Invalidation"}
WARM_SESSIONS = 3  # stored sessions before the 15m chart's first that warm its averages (from disk, never fetched)
USUAL_DAYS = 30  # a daily candle's volume against the average of this many before it
# The averages each timeframe draws, on the workspace's own math (``chart_math.ema``/``sma``); VWAP and RVol ride too.
AVERAGES = {"2m": (("ema9", chart_math.ema, 9), ("ema21", chart_math.ema, 21)),
            "15m": (("ema9", chart_math.ema, 9), ("ema21", chart_math.ema, 21)),
            "1D": (("ema21", chart_math.ema, 21), ("sma50", chart_math.sma, 50), ("sma200", chart_math.sma, 200))}


def _two_minute(minutes: list[dict]) -> list[dict]:
    """Minute bars as 2-minute candles on the even minute (the session edges, 09:30 and 16:00, are even), extended only
    when all of its minutes are."""
    out: list[dict] = []
    for bar in minutes:
        slot = int(bar["time"]) - int(bar["time"]) % 120
        extended = bool(bar.get("extended"))
        last = out[-1] if out else None
        if last is None or last["time"] != slot:
            out.append({"time": slot, "open": bar["open"], "high": bar["high"], "low": bar["low"], "close": bar["close"],
                        "volume": bar.get("volume") or 0, "extended": extended})
            continue
        last.update(high=max(last["high"], bar["high"]), low=min(last["low"], bar["low"]), close=bar["close"],
                    volume=last["volume"] + (bar.get("volume") or 0), extended=last["extended"] and extended)
    return out


def _plain(bar: dict) -> dict:
    return {"time": int(bar["time"]), "open": float(bar["open"]), "high": float(bar["high"]), "low": float(bar["low"]),
            "close": float(bar["close"]), "volume": float(bar.get("volume") or 0), "extended": bool(bar.get("extended"))}


def _fill_mark(fill: Fill) -> dict:
    """A fill at its price: a share fill's own, an option fill's underlying price when the fill recorded it, else none
    (the chart puts it on its candle)."""
    from app.engine.chart_journal import contract_label
    verb = "Bought" if fill.side.startswith("buy") else "Sold"
    what = contract_label(fill.ticker, fill.instrument_type, fill.option_type, fill.strike, fill.expiration)
    if fill.instrument_type == "stock":
        price = float(fill.price)
        text = f"{verb} {float(fill.contracts):g} {fill.ticker} shares at {_price(price)}"
    else:
        price = float(fill.underlying_price_at_fill) if fill.underlying_price_at_fill else None
        text = f"{verb} {float(fill.contracts):g} {what}" + (f" · {fill.ticker} at {_price(price)}" if price else "")
    return {"kind": "fill", "at": _epoch_ny(fill.executed_at), "price": price, "side": "buy" if verb == "Bought" else "sell",
            "text": text}


def _live(now: float) -> bool:
    """Bars can still change: a weekday between 04:00 and 20:00 New York (a holiday reads cached bars once a minute)."""
    moment = datetime.fromtimestamp(now, ET)
    return moment.weekday() < 5 and 4 <= moment.hour < 20


def today_minutes(symbol: str) -> list[dict]:
    """Today's minute bars (extended hours) with each regular-session minute's RTH VWAP and RVol (C2.4): the chart feed's
    cached read, the same provider request as ``ping_images.today_bars``; the RVol baseline is read from disk only."""
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    from app.engine.chart_history import chart_history
    data = chart_feed.workspace(symbol, ["1m"], [], "extended", calendar=chart_calendar, quotes=False,
                                volume_profile=chart_history.volume_profile)
    return list(((data.get("panels") or {}).get("1m") or {}).get("bars") or [])


def stored_sessions(symbol: str, before: date, count: int) -> list[tuple[date, dict | None, list[dict]]]:
    """Up to ``count`` completed sessions before ``before`` that are already on disk (never a provider request), oldest
    first: each date, its calendar hours and its minutes, split-adjusted like a chart page. Stops at the first missing
    one, so the sessions are always consecutive."""
    from app.engine.chart_adjust import adjust_minutes
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_history import chart_history
    from app.engine.chart_splits import UNAVAILABLE
    info = chart_history.splits.get(symbol) if chart_history.splits else UNAVAILABLE
    out: list[tuple[date, dict | None, list[dict]]] = []
    day = before
    for _ in range(10 + 2 * count):  # calendar days back, past weekends and holidays
        if len(out) >= count:
            break
        day -= timedelta(days=1)
        hours = chart_calendar.hours(day) if day.weekday() < 5 else None
        if day.weekday() >= 5 or (hours is not None and hours["status"] == "closed"):
            continue
        raw = chart_history.stored(symbol, day)
        if raw is None:
            break
        if raw:
            out.insert(0, (day, hours, adjust_minutes(raw, day, info["splits"])))
    return out


def _at_candles(candles: list[dict], step: int, minutes: list[dict], key: str) -> list[float | None]:
    """Each candle's ``key`` as of its last minute (the RTH VWAP and RVol are running values), None without one."""
    out: list[float | None] = []
    j = 0
    for candle in candles:
        value = None
        while j < len(minutes) and minutes[j]["time"] < candle["time"]:
            j += 1
        while j < len(minutes) and minutes[j]["time"] < candle["time"] + step:
            value = minutes[j].get(key)
            j += 1
        out.append(value)
    return out


def _regular_close(minutes: list[dict]) -> float | None:
    """A session's last regular-session close."""
    regular = [m for m in minutes if not m.get("extended")]
    return float(regular[-1]["close"]) if regular else None


def _minute_of_day(stamp: int) -> int:
    moment = datetime.fromtimestamp(stamp, ET)
    return moment.hour * 60 + moment.minute


def _usual_volume(bars: list[dict]) -> list[float | None]:
    """Each daily candle's volume over the average of the ``USUAL_DAYS`` before it."""
    out: list[float | None] = []
    for i, bar in enumerate(bars):
        before = [b.get("volume") or 0 for b in bars[max(0, i - USUAL_DAYS):i]]
        usual = sum(before) / len(before) if len(before) == USUAL_DAYS else 0
        out.append((bar.get("volume") or 0) / usual if usual > 0 else None)
    return out


def _desk_read(symbol: str, timeframe: str, now: float) -> dict | None:
    """One timeframe's candles with their studies, warmed on the candles before the first shown, and what the reading
    line and the reference lines need. None when there are no candles."""
    today = datetime.fromtimestamp(now, ET).date()
    on_today = lambda bars: [b for b in bars if b["time"] <= now and datetime.fromtimestamp(b["time"], ET).date() == today]  # noqa: E731
    warm: list[dict] = []
    prev_close = None
    if timeframe == "2m":
        minutes = on_today(today_minutes(symbol))
        shown = _two_minute(minutes)
        for candle, vwap, rvol in zip(shown, _at_candles(shown, 120, minutes, "vwap"), _at_candles(shown, 120, minutes, "rvol")):
            candle.update(vwap=vwap, rvol=rvol)
        earlier = stored_sessions(symbol, today, 1) if shown else []
        for day, hours, raw in earlier:
            session = chart_bars(raw, [], "1m", "extended", {day: hours})
            warm = _two_minute(session)
            prev_close = _regular_close(session)
    else:
        try:
            minutes = on_today(today_minutes(symbol))
        except Exception:  # noqa: BLE001 - the reading line is a bonus on these timeframes; the candles still show
            log.warning("Desk chart minutes for %s failed", symbol, exc_info=True)
            minutes = []
        if timeframe == "15m":
            shown = [b for b in fifteen_bars(symbol) if b["time"] <= now]
            if shown:
                first = datetime.fromtimestamp(shown[0]["time"], ET).date()
                for day, hours, raw in stored_sessions(symbol, first, WARM_SESSIONS):
                    warm += chart_bars(raw, [], "15m", "regular", {day: hours})
        else:
            history = [dict(b) for b in daily_bars(symbol) if b["time"] <= now]
            for bar, usual in zip(history, _usual_volume(history)):
                bar["rvol"] = usual
            cut = next((i for i, b in enumerate(history) if b["time"] >= now - DAILY_DAYS * 86400), len(history))
            warm, shown = history[:cut], history[cut:]
    if not shown:
        return None
    every = warm + shown
    closes = [float(b["close"]) for b in every]
    studies: dict[str, list[float | None]] = {}
    for name, average, length in AVERAGES[timeframe]:
        studies[name] = average(closes, length)[len(warm):]
    for name in ("vwap", "rvol"):
        studies[name] = [b.get(name) for b in shown]
    if len(shown) > MAX_BARS:
        shown = shown[-MAX_BARS:]
        studies = {name: values[-MAX_BARS:] for name, values in studies.items()}
    studies = {name: [None if v is None else round(float(v), 4) for v in values] for name, values in studies.items()}
    regular = [m for m in minutes if not m.get("extended")]
    last = minutes[-1] if minutes else shown[-1]
    day_of = lambda stamp: datetime.fromtimestamp(stamp, ET).date()  # noqa: E731
    if timeframe != "2m":  # the close of the session before the newest price's, from the candles shown
        prev_close = next((float(b["close"]) for b in reversed(shown) if day_of(b["time"]) < day_of(last["time"])), None)
    at = last["time"] if minutes else min(last.get("end_time") or last["time"], now)  # a candle's price is its end's
    reading = {"last": float(last["close"]), "at": int(at), "daily": not minutes and timeframe == "1D",
               "prev_close": prev_close,
               "vwap": regular[-1].get("vwap") if regular else None, "vwap_at": int(regular[-1]["time"]) if regular else None,
               "rvol": regular[-1].get("rvol") if regular else None}
    reading = {k: round(v, 4) if isinstance(v, float) else v for k, v in reading.items()}
    reference = []
    if timeframe != "1D":
        if prev_close is not None:
            reference.append({"key": "prev_close", "price": round(prev_close, 4), "label": f"Prev close {_price(prev_close)}"})
        pre = [m for m in minutes if m.get("extended") and _minute_of_day(m["time"]) < REGULAR_OPEN]
        if pre:
            high, low = max(m["high"] for m in pre), min(m["low"] for m in pre)
            reference += [{"key": "pm_high", "price": round(float(high), 4), "label": f"PM high {_price(high)}"},
                          {"key": "pm_low", "price": round(float(low), 4), "label": f"PM low {_price(low)}"}]
    return {"bars": [_plain(b) for b in shown], "studies": studies, "reading": reading, "reference": reference}


def _alerts(db: Session, symbol: str, plan_ids: set[str]) -> list[dict]:
    """The symbol's armed level alerts other than the plan's own lines: each as a thin line on the chart. One from a plan
    (any thread's) cannot be removed from the chart."""
    alerts = db.exec(select(LevelAlert).where(LevelAlert.symbol == symbol, LevelAlert.state == "active")
                     .order_by(LevelAlert.price)).all()
    out = []
    for alert in alerts:
        if str(alert.id) in plan_ids:
            continue
        side = "above" if alert.direction == "up" else "below"
        what = (f"Touches {_price(alert.price)}" if alert.condition == "touches" else f"Crosses {side} {_price(alert.price)}"
                if alert.condition == "crosses" else f"{alert.interval} close {side} {_price(alert.price)}")
        out.append({"id": str(alert.id), "price": float(alert.price), "text": what, "label": alert.label or None,
                    "removable": alert.plan_role is None})
    return out


def chart(db: Session, inv: CopilotInvestigation | SymbolThread | None, now: float, timeframe: str = "2m",
          events: list[dict] = (), budget: float = BUDGET_SECONDS) -> dict:
    """The desk's interactive chart as data: the symbol's candles on ``timeframe`` (``2m`` today from the pre-market to
    now, extended candles flagged; ``15m`` recent sessions; ``1D`` the last ``DAILY_DAYS``), read from the same cached
    chart feed as the picture, with ``studies`` (``AVERAGES`` plus the RTH VWAP and RVol), one value or None per candle,
    the averages warmed on the candles before the first shown (stored sessions on disk, the rest of the daily history)
    so they are right from the first candle; ``reference`` lines (intraday: the previous close and today's pre-market
    high and low); ``reading``: the newest price, the previous close, VWAP and RVol, each with its time; its plan's
    entry and invalidation as ``levels``; the symbol's other armed level ``alerts``; ``marks``: the owner's fills on the
    symbol since the first candle and ``events`` (today's pings sent and Radar hits, ``kind``/``at``/``text``); the
    plan's time stop while still ahead. ``inv`` None is the market chart: ``MARKET`` with ``events`` alone (the day's
    fills on any symbol and pings sent). ``live`` says bars can still change, so the desk reads again each minute.
    No bars, a failed read or a run past the budget is ``state`` "unavailable" with the reason."""
    symbol = MARKET if inv is None else inv.symbol
    base = {"symbol": symbol, "timeframe": timeframe, "step": STEP.get(timeframe), "as_of": int(now), "live": _live(now),
            "bars": [], "studies": {}, "reference": [], "reading": None, "levels": [], "alerts": [], "marks": [], "time_stop": None}
    if not symbol:
        return {**base, "state": "unavailable", "reason": "This thread has no symbol, so there is no chart."}
    if timeframe not in TIMEFRAMES:
        return {**base, "state": "unavailable", "reason": f"No {timeframe} chart; the choices are {', '.join(TIMEFRAMES)}."}
    try:
        read = _budgeted(symbol, lambda: _desk_read(symbol, timeframe, now), budget, WHAT[timeframe])
    except Unavailable as exc:
        return {**base, "state": "unavailable", "reason": str(exc)}
    shown = read["bars"]
    marks = [{"kind": e["kind"], "at": int(e["at"]), "price": None, "side": None, "text": e.get("text") or e["kind"].title()}
             for e in events if e.get("at") is not None and e["kind"] in ("fill", "ping", "radar")]
    levels: list[dict] = []
    time_stop = None
    if inv is not None:
        found = plan(db, str(inv.id)) if inv.id else None
        for alert in (found["entry"], found["invalidation"]) if found else ():
            if alert is not None:
                levels.append({"role": alert.plan_role, "price": float(alert.price), "id": str(alert.id),
                               "label": f"{LEVEL_WORD[alert.plan_role]} {_price(float(alert.price))}"})
        stop = found["stop"] if found else None
        due = _epoch_utc(stop.due_at) if stop is not None else None
        if due is not None and stop.delivery == "scheduled" and due > now:
            time_stop = {"at": due, "text": stop.text}
        since = datetime.fromtimestamp(shown[0]["time"], ET).replace(tzinfo=None)
        fills = db.exec(select(Fill).where(Fill.ticker == symbol, Fill.executed_at >= since, _not_webull())
                        .order_by(Fill.executed_at.desc()).limit(MAX_FILLS)).all()
        marks = [_fill_mark(f) for f in reversed(fills)] + marks
    marks = sorted((m for m in marks if m["at"] is not None and m["at"] >= shown[0]["time"]), key=lambda m: m["at"])[-MAX_MARKS:]
    alerts = _alerts(db, symbol, {level["id"] for level in levels})
    return {**base, **read, "state": "ok", "reason": None, "levels": levels, "alerts": alerts, "marks": marks,
            "time_stop": time_stop}


# ------------------------------------------------------------------ timeline


def _row(kind: str, at: int | None, text: str, detail: str | None = None) -> dict | None:
    return None if at is None else {"kind": kind, "at": at, "text": text, "detail": detail}


def _thread_alerts(db: Session, investigation_id: str) -> list[LevelAlert]:
    """Every level alert confirmed from the investigation: its plan's levels and its plain watches."""
    return list(db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", LevelAlert.source_id == investigation_id)).all())


def _alert_rows(db: Session, alerts: list[LevelAlert]) -> list[dict]:
    events = {e.alert_id: e for e in db.exec(select(LevelAlertEvent).where(
        LevelAlertEvent.alert_id.in_([a.id for a in alerts]))).all()} if alerts else {}
    rows = []
    for a in alerts:
        name = ROLE.get(a.plan_role or "", "Alert")
        rule = f"{CONDITION.get(a.condition, a.condition)} {_price(a.price)}" + (f" ({a.interval})" if a.interval else "")
        rows.append(_row("alert", _epoch_utc(a.created_at), f"{name} armed", f"{rule} · {a.label}" if a.label else rule))
        if a.state == "fired":
            event = events.get(a.id)
            hit = f"at {_price(event.price)}" if event else rule
            sent = " · pinged" if event and event.delivery == "sent" else ""
            rows.append(_row("alert", _epoch_utc(event.event_at if event else a.fired_at), f"{name} hit", hit + sent))
    return rows


def _stop_rows(found: dict | None) -> list[dict]:
    from app.engine import plan_time_stops
    rows = []
    for s in found["stops"] if found else []:
        due = datetime.fromtimestamp(_epoch_utc(s.due_at), ET).strftime("%H:%M")
        off = s.delivery == "scheduled" and not plan_time_stops.enabled()
        rows.append(_row("time_stop", _epoch_utc(s.created_at), f"Time stop set for {due}",
                         f"{s.text} · time-stop pings are off on this server" if off else s.text))
        if s.delivery == "sent":
            rows.append(_row("time_stop", _epoch_utc(s.delivered_at or s.detected_at or s.due_at), "Time stop pinged", s.text))
        elif s.delivery in ("skipped", "expired", "held"):
            word = {"skipped": "skipped", "expired": "not sent", "held": "held back"}[s.delivery]
            rows.append(_row("time_stop", _epoch_utc(s.detected_at or s.due_at), f"Time stop {word}", s.last_error or s.text))
    return rows


def _revisit_rows(db: Session, investigation_id: str) -> list[dict]:
    rows = []
    for job in db.exec(select(ResearchJob).where(ResearchJob.kind == "reassess",
                                                 ResearchJob.input_json.contains(investigation_id))).all():
        try:
            data = json.loads(job.input_json)
        except ValueError:
            continue
        if data.get("investigation_id") != investigation_id:
            continue
        question = (data.get("question") or "")[:200] or None
        rows.append(_row("revisit", _epoch_utc(job.created_at), "Revisit queued", question))
        if job.finished_at is not None and job.status in ("done", "failed", "cancelled"):
            rows.append(_row("revisit", _epoch_utc(job.finished_at), f"Revisit {job.status}", question))
    return rows


def _fill_rows(fills: list[Fill], detail: str = "linked to the plan") -> list[dict]:
    from app.engine.chart_journal import contract_label
    rows = []
    for f in fills:
        verb = "Bought" if f.side.startswith("buy") else "Sold"
        qty = f"{float(f.contracts):g}"
        what = contract_label(f.ticker, f.instrument_type, f.option_type, f.strike, f.expiration)
        price = f" at {_price(float(f.price))}" if f.instrument_type == "stock" else ""
        rows.append(_row("fill", _epoch_ny(f.executed_at), f"{verb} {qty} {what}{price}", detail))
    return rows


def _thesis_rows(db: Session, symbol: str, since: datetime) -> list[dict]:
    found = db.exec(select(ThesisWatchTrigger).where(ThesisWatchTrigger.symbol == symbol, ThesisWatchTrigger.fired_at >= since)
                    .order_by(ThesisWatchTrigger.fired_at.desc()).limit(MAX_ROWS)).all()
    label = {"news": "News", "move": "Move", "earnings": "Earnings"}
    return [_row("thesis", _epoch_utc(t.fired_at), f"{label.get(t.kind, t.kind.title())} · thesis watch", t.text[:200])
            for t in found]


def _ping_rows(db: Session, symbol: str, since: datetime, alerts: list[LevelAlert], found: dict | None) -> list[dict]:
    from app.engine import notification_policy as policy
    own_events = {str(e) for e in db.exec(select(LevelAlertEvent.id).where(
        LevelAlertEvent.alert_id.in_([a.id for a in alerts]))).all()} if alerts else set()
    own_stops = {str(s.id) for s in found["stops"]} if found else set()
    pings = db.exec(select(PhonePing).where(PhonePing.symbol == symbol, PhonePing.decided_at >= since)
                    .order_by(PhonePing.decided_at.desc()).limit(MAX_ROWS)).all()
    rows = []
    for p in pings:
        own = (p.sender == "level_alerts" and p.source_id in own_events) or (p.sender == "plan_time_stops" and p.source_id in own_stops)
        if own and p.decision == "sent":
            continue  # already on the alert's or the time stop's own row; a held one shows, with why
        state = "sent" if p.decision == "sent" else "held back"
        detail = f"{p.title} · {p.reason}" if p.decision != "sent" and p.reason else p.title
        rows.append(_row("ping", _epoch_utc(p.decided_at), f"Ping {state} · {policy._label(p.kind)}", detail[:300]))
    return rows


def _decision_rows(db: Session, symbol: str, today: date) -> list[dict]:
    found = db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "decision", DayJournalEntry.symbol == symbol,
                                                  DayJournalEntry.day == today)).all()
    return [_row("decision", _epoch_utc(e.created_at), "Decision", e.text[:300]) for e in found]


def _thread_fills(db: Session, inv: CopilotInvestigation | SymbolThread, found: dict | None) -> list[dict]:
    """The plan's linked trade; a thread named by its symbol with none shows the symbol's open trade instead."""
    linked = _linked_fills(db, found["capture"] if found else None)
    if linked or not isinstance(inv, SymbolThread):
        return _fill_rows(linked)
    return _fill_rows(_open_fills(db, inv.symbol), "the open position")


def timeline(db: Session, inv: CopilotInvestigation | SymbolThread, now: float) -> dict:
    investigation_id, symbol = str(inv.id), inv.symbol
    today = datetime.fromtimestamp(now, ET).date()
    since = datetime.fromtimestamp(now, UTC).replace(tzinfo=None) - timedelta(days=RECENT_DAYS)
    rows: list[dict] = []
    unavailable: list[str] = []

    def read(name: str, build) -> None:
        try:
            rows.extend(r for r in build() if r is not None)
        except Exception:  # noqa: BLE001 - one source failing never hides the rest
            log.warning("Desk timeline: %s could not be read", name, exc_info=True)
            db.rollback()
            unavailable.append(name)

    found: dict | None = None
    try:
        found = plan(db, investigation_id) if investigation_id else None
    except Exception:  # noqa: BLE001
        log.warning("Desk timeline: the plan could not be read", exc_info=True)
        db.rollback()
        unavailable.append("plan")
    alerts: list[LevelAlert] = []

    def alert_rows():
        alerts.extend(_thread_alerts(db, investigation_id))
        return _alert_rows(db, alerts)
    if investigation_id:  # a symbol with no plan has no alerts, time stop or revisits of its own
        read("alerts", alert_rows)
        read("time stop", lambda: _stop_rows(found))
        read("revisits", lambda: _revisit_rows(db, investigation_id))
    read("fills", lambda: _thread_fills(db, inv, found))
    if symbol:
        read("thesis watch", lambda: _thesis_rows(db, symbol, since))
        read("pings", lambda: _ping_rows(db, symbol, since, alerts, found))
        read("decisions", lambda: _decision_rows(db, symbol, today))
    rows.sort(key=lambda r: (r["at"], r["kind"]), reverse=True)
    return {"state": "ok", "symbol": symbol, "rows": rows[:MAX_ROWS], "count": len(rows), "unavailable": unavailable,
            "recent_days": RECENT_DAYS}


# ------------------------------------------------------------------ your history


def _won(data: dict) -> tuple[int, int]:
    """Won and not won among the trades that crossed, from the engine's split: realized P&L above zero is a win, so
    "not won" counts a breakeven with the losses."""
    split = (data.get("pnl") or {}).get("crossed") or {}
    n = int(split.get("trades") or 0)
    won = round((split.get("win_rate_pct") or 0) * n / 100)
    return won, n - won


def history_sentence(data: dict, won: int, not_won: int) -> str:
    """One sentence from the counts: how many past trades crossed a level this far from their entry, how those ended,
    and what the option did from the cross. Never more than the numbers say."""
    symbol, asked, part = data["symbol"], data["asked"], data.get("crossed") or {}
    kind = "calls" if asked["side"] == "below" else "puts"
    of, crossed = int(part.get("of") or 0), int(part.get("trades") or 0)
    where = f"{abs(asked['distance_pct']):.1f}% {asked['side']} entry"
    if of == 0:
        n = int((data.get("sample") or {}).get("trades") or 0)
        if n:
            return f"{n} closed {symbol} {kind if n != 1 else kind[:-1]} in the last {data['window']['days']} days, but none has recorded minute bars to replay."
        return f"No closed {symbol} {kind} in the last {data['window']['days']} days to compare at {where}."
    if crossed == 0:
        text = f"None of {of} past {symbol} {kind} crossed a level {where} while held."
    else:
        text = f"{crossed} of {of} past {symbol} {kind} crossed a level {where} while held: {won} won, {not_won} did not."
        if part.get("recovery_known"):
            text += f" {int(part.get('recovered_to_breakeven') or 0)} recovered to breakeven"
            median = part.get("median_pnl_from_cross_pct")
            text += f"; median {median:+.0f}% from the cross." if median is not None else "."
    if (data.get("sample") or {}).get("small"):
        text += " Too few trades to weigh."
    return text


def history(db: Session, inv: CopilotInvestigation | SymbolThread, level_history=None) -> dict:
    if not inv.symbol:
        return {"state": "missing", "reason": "This thread has no symbol, so there is no level to look up."}
    found = plan(db, str(inv.id)) if inv.id else None
    if found is None or found["invalidation"] is None:
        return {"state": "missing", "symbol": inv.symbol,
                "reason": "No plan invalidation yet. Once you confirm a plan card, your record at its invalidation shows here."}
    if found["entry"] is None or found["direction"] is None:
        # Without the planned entry the engine would measure from a live quote; the pane reads only what the plan says.
        return {"state": "missing", "symbol": found["symbol"],
                "reason": "The plan has an invalidation but no entry level, so there is no distance to compare past trades at."}
    if level_history is None:
        from app.ai.copilot_review import level_history
    side = "below" if found["direction"] == "long" else "above"
    level = float(found["invalidation"].price)
    entry = float(found["entry"].price)
    data = level_history(found["symbol"], level=level, side=side, entry=entry, session=db)
    if data.get("state") != "ok":
        return {"state": "unavailable", "symbol": found["symbol"], "level": level,
                "reason": data.get("reason") or "Your history at this level could not be read."}
    won, not_won = _won(data)
    part, asked = data.get("crossed") or {}, data["asked"]
    return {"state": "ok", "symbol": data["symbol"], "level": level, "side": side, "entry": asked["entry"],
            "entry_from": asked["entry_from"], "distance_pct": asked["distance_pct"], "trades": part.get("of"),
            "crossed": part.get("trades"), "won": won, "not_won": not_won, "recovered": part.get("recovered_to_breakeven"),
            "median_from_cross_pct": part.get("median_pnl_from_cross_pct"),
            "not_crossed": (data.get("pnl") or {}).get("not_crossed"), "small": bool((data.get("sample") or {}).get("small")),
            "window_days": data["window"]["days"], "sentence": history_sentence(data, won, not_won), "note": data.get("note"),
            "simulated": bool(data.get("simulated"))}
