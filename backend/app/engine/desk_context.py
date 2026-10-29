"""The Copilot desk's Context pane (docs/copilot-lab.md#the-desk): three reads for the open thread, keyed by its saved
investigation and its symbol.

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
- ``market_picture``: the Briefing's chart, today's ``MARKET`` (QQQ) minutes with the day's fills and phone pings sent
  as dots, under the picture route's reserved ``MARKET_ID``.

Read-only: nothing here arms, sends or writes. No account numbers or ids beyond the investigation's own.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import UTC, date, datetime, timedelta
import json
import logging
import threading
import uuid

from sqlmodel import Session, select

from app.engine import chart_render, copilot_plans, ping_images
from app.engine.chart_math import ET, chart_bars
from app.engine.chart_render import Chart, Mark, Time
from app.models import (Account, CaptureLink, CopilotInvestigation, DayJournalEntry, Fill, LevelAlert, LevelAlertEvent,
                        PhonePing, PlanTimeStop, ResearchJob, ThesisWatchTrigger, TradeCapture, TradeFill)

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


class Unavailable(Exception):
    """The picture cannot be shown; ``str(exc)`` says why, in words for the owner."""


def investigation(db: Session, investigation_id: str) -> CopilotInvestigation | None:
    try:
        key = uuid.UUID(investigation_id)
    except ValueError:
        return None
    return db.get(CopilotInvestigation, key)


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
    """Today's minutes up to ``now``: the regular session once it has bars, before that the pre-market."""
    today = datetime.fromtimestamp(now, ET).date()
    found_bars = [b for b in read(symbol) if b["time"] <= now][-DAY_BARS:]
    found_bars = [b for b in found_bars if datetime.fromtimestamp(b["time"], ET).date() == today]
    return [b for b in found_bars if not b.get("extended")] or found_bars


def fifteen_bars(symbol: str) -> list[dict]:
    """Regular-session 15-minute bars: today's from the chart feed, and up to ``SESSIONS_15M - 1`` completed sessions
    before it from the chart history (from disk, or fetched once and stored), split-adjusted like a chart page."""
    from app.engine.chart_adjust import adjust_minutes
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    from app.engine.chart_history import HistoryError, chart_history
    from app.engine.chart_splits import UNAVAILABLE
    data = chart_feed.workspace(symbol, ["15m"], [], "regular", calendar=chart_calendar, quotes=False)
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


def picture(db: Session, inv: CopilotInvestigation, now: float, bars=None, budget: float = BUDGET_SECONDS,
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
    found = plan(db, str(inv.id))
    levels = tuple(sorted((a.plan_role, float(a.price)) for a in (found["entry"], found["invalidation"]) if a)) if found else ()
    today = datetime.fromtimestamp(now, ET).date()
    start = datetime.combine(today, datetime.min.time())
    fills = list(db.exec(select(Fill).where(Fill.ticker == symbol, Fill.executed_at >= start,
                                            Fill.executed_at < start + timedelta(days=1), _not_webull())
                         .order_by(Fill.executed_at).limit(MAX_FILLS)).all())
    read = bars or {"2m": ping_images.today_bars, "15m": fifteen_bars, "1D": daily_bars}[timeframe]

    def draw() -> bytes | None:
        if timeframe == "2m":
            shown = _today_shown(read, symbol, now)
        elif timeframe == "15m":
            shown = [b for b in read(symbol) if b["time"] <= now]
        else:
            shown = [b for b in read(symbol) if now - DAILY_DAYS * 86400 <= b["time"] <= now]
        if not shown:
            return None
        note = f"NOW {_price(shown[-1]['close'])}"
        title = symbol if timeframe == "2m" else f"{symbol} {timeframe}"
        if timeframe == "1D":
            return chart_render.render(Chart(title=title, note=note, bars=tuple(shown)))
        marks, times = _fill_marks(fills, shown[0]["time"])
        return chart_render.render(Chart(title=title, note=note, bars=tuple(shown), levels=ping_images._plan_level_marks(levels),
                                         marks=marks + tuple(_event_marks(list(events), shown)), times=times))

    return _budgeted(symbol, draw, budget, WHAT[timeframe])


def market_picture(events: list[dict], now: float, bars=None, budget: float = BUDGET_SECONDS) -> bytes:
    """The Briefing's chart: today's ``MARKET`` minutes with the day's fills (any symbol, amber) and phone pings sent
    (violet) as dots on the bar of their minute, the first of each labelled FILL or PING. ``events`` are the session
    timeline's rows (``kind``, ``at``); one before the first bar shown is left off. Raises ``Unavailable``."""
    read = bars or ping_images.today_bars

    def draw() -> bytes | None:
        shown = _today_shown(read, MARKET, now)
        if not shown:
            return None
        marks = _event_marks([e for e in events if e["kind"] in ("fill", "ping")], shown)
        return chart_render.render(Chart(title=MARKET, note=f"NOW {_price(shown[-1]['close'])}", bars=tuple(shown), marks=tuple(marks)))

    return _budgeted(MARKET, draw, budget)


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


def _fill_rows(fills: list[Fill]) -> list[dict]:
    from app.engine.chart_journal import contract_label
    rows = []
    for f in fills:
        verb = "Bought" if f.side.startswith("buy") else "Sold"
        qty = f"{float(f.contracts):g}"
        what = contract_label(f.ticker, f.instrument_type, f.option_type, f.strike, f.expiration)
        price = f" at {_price(float(f.price))}" if f.instrument_type == "stock" else ""
        rows.append(_row("fill", _epoch_ny(f.executed_at), f"{verb} {qty} {what}{price}", "linked to the plan"))
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


def timeline(db: Session, inv: CopilotInvestigation, now: float) -> dict:
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
        found = plan(db, investigation_id)
    except Exception:  # noqa: BLE001
        log.warning("Desk timeline: the plan could not be read", exc_info=True)
        db.rollback()
        unavailable.append("plan")
    alerts: list[LevelAlert] = []

    def alert_rows():
        alerts.extend(_thread_alerts(db, investigation_id))
        return _alert_rows(db, alerts)
    read("alerts", alert_rows)
    read("time stop", lambda: _stop_rows(found))
    read("revisits", lambda: _revisit_rows(db, investigation_id))
    read("fills", lambda: _fill_rows(_linked_fills(db, found["capture"] if found else None)))
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


def history(db: Session, inv: CopilotInvestigation, level_history=None) -> dict:
    if not inv.symbol:
        return {"state": "missing", "reason": "This thread has no symbol, so there is no level to look up."}
    found = plan(db, str(inv.id))
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
