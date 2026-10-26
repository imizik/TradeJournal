"""Pictures on phone pings: each ping carries a small chart, so one glance at the lock screen says what the words say.

``PING_IMAGES_ENABLED`` (default **true**: the renderer, ``chart_render``, needs nothing beyond numpy, already a
dependency) turns pictures off without touching the pings. After the notification policy says send, a sender reads
its picture's facts from the database in its own session through ``prepare`` (a failing read costs only the
picture), which returns a builder; ``picture`` runs the builder (the bar reads) and the drawing on a worker thread
with a ``BUDGET_SECONDS`` budget. A builder that fails, finds no bars, or runs past the budget gives no picture and
the ping goes out as text: a picture never delays a ping by more than the budget and never drops one. A retry (the
first send failed and was surely unsent, e.g. ntfy answered the picture with a 5xx) goes as text alone. ``publish``
sends the PNG to ntfy as the attachment (``ntfy.publish_image``); when the server refuses the attachment it sends the
text alone. The ping's ``PhonePing`` row records ``image``: ``attached``, ``none`` (text only: no picture, or ntfy
refused it) or ``off`` (pictures switched off). The picture never changes the policy's decision.

What each picture shows (all New York times, labels upper case, no account numbers or ids, the contract label as
the title):

- a plan's entry trigger or invalidation: the last ``WINDOW_MINUTES`` with the plan's levels and any entry fill;
- a give-back or held-an-hour alert: the underlying since the entry with the entry, the peak and now;
- a time stop: the day with the stop time and the entry;
- a no-plan nudge or link ping: the last ``WINDOW_MINUTES`` with the fill;
- a Radar event: the stock (or the group's median) against its benchmark, in percent, over the session's passes;
- thesis watch: today with the reference price the move is measured from;
- pre-market prep: the open options by days to expiry, else the first armed plan's chart.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import UTC, date, datetime
import logging
import os
from statistics import median
from typing import Callable

from sqlmodel import Session, select

from app.engine import chart_render, ntfy
from app.engine.chart_math import ET
from app.engine.chart_render import Chart, Level, Mark, Row, Series, Time

log = logging.getLogger(__name__)

BUDGET_SECONDS = 2.0
WINDOW_MINUTES = 90
POSITION_BARS = 120
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ping-image")


def enabled() -> bool:
    return os.environ.get("PING_IMAGES_ENABLED", "true").strip().lower() != "false"


def prepare(db: Session, facts: Callable, *args) -> Callable[[], Chart | None] | None:
    """``facts(db, *args)``: the sender's database reads for its picture, returning the builder. None when pictures
    are off or the reads failed (rolled back, so the sender's session stays usable; it has nothing pending here)."""
    if not enabled():
        return None
    try:
        return facts(db, *args)
    except Exception:  # noqa: BLE001 - a picture never costs the ping
        log.warning("Ping picture facts could not be read; sending the text alone", exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def picture(build: Callable[[], Chart | None] | None, budget: float | None = None) -> bytes | None:
    """The PNG ``build`` describes, or None when pictures are off, there is no builder, it found nothing, failed, or
    ran past ``budget`` seconds, ``BUDGET_SECONDS`` by default (it is left to finish on its own; its result is ignored)."""
    if build is None or not enabled():
        return None
    budget = BUDGET_SECONDS if budget is None else budget

    def run() -> bytes | None:
        chart = build()
        return chart_render.render(chart) if chart is not None else None

    try:
        future = _pool.submit(run)
    except RuntimeError:  # the pool is shut down (interpreter exit)
        return None
    try:
        return future.result(timeout=budget)
    except FutureTimeout:
        future.cancel()
        log.warning("Ping picture took longer than %.1fs; sending the text alone", budget)
    except Exception:  # noqa: BLE001 - a picture never costs the ping
        log.warning("Ping picture failed; sending the text alone", exc_info=True)
    return None


def publish(title: str, message: str, image: bytes | None, **kwargs) -> tuple[str | None, str]:
    """Send the ping, with ``image`` attached when there is one: ``(ntfy's message id, image state)``. Raises
    ``ntfy.NtfyError`` exactly as ``ntfy.publish`` does for the text."""
    if image is not None:
        try:
            return ntfy.publish_image(title, message, image, **kwargs), "attached"
        except ntfy.ImageRefused as exc:
            log.warning("%s; sending the text alone", exc)
    return ntfy.publish(title, message, **kwargs), "none" if enabled() else "off"


def record(db: Session, ticket, state: str) -> None:
    """Write the image state on the ping's policy record (``PhonePing.image``); never fails the ping."""
    from app.models import PhonePing
    if getattr(ticket, "id", None) is None:
        return
    try:
        row = db.get(PhonePing, ticket.id)
        if row is not None:
            row.image = state
            db.add(row)
    except Exception:  # noqa: BLE001
        log.warning("Could not record a ping's image state", exc_info=True)


# ------------------------------------------------------------------ bars


def today_bars(symbol: str) -> list[dict]:
    """Today's minute bars (extended hours), from the chart feed: one cached Tradier read."""
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    data = chart_feed.workspace(symbol, ["1m"], [], "extended", calendar=chart_calendar, quotes=False)
    return list(((data.get("panels") or {}).get("1m") or {}).get("bars") or [])


def stored_bars(symbol: str, day: date) -> list[dict]:
    """A completed session's minute bars from the chart cache on disk, never a fetch."""
    from app.engine.chart_history import chart_history
    return list(chart_history.stored(symbol, day) or [])


def _window(bars: list[dict], end: float, minutes: int = WINDOW_MINUTES) -> list[dict]:
    """The last ``minutes`` bars that started by ``end``."""
    return [b for b in bars if b["time"] <= end][-minutes:]


def _price(value: float) -> str:
    return f"{value:,.2f}"


def _clock(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, ET).strftime("%H:%M")


def _epoch_utc(moment: datetime | None) -> float | None:
    """A naive UTC column (``datetime.utcnow()``) as epoch seconds."""
    return None if moment is None else moment.replace(tzinfo=UTC).timestamp()


def _epoch_ny(moment: datetime | None) -> float | None:
    """A journal time (a naive New York wall clock) as epoch seconds."""
    return None if moment is None else (moment.replace(tzinfo=ET) if moment.tzinfo is None else moment).timestamp()


# ------------------------------------------------------------------ facts read in the sender's session


@dataclass(frozen=True)
class Fills:
    """A position's entry fills as (epoch seconds, price): a stock's price is on the chart, an option's is not."""
    stamps: tuple[tuple[float, float], ...] = ()
    on_chart: bool = False

    def marks(self, label: str = "FILL") -> tuple[tuple[Mark, ...], tuple[Time, ...]]:
        if not self.stamps:
            return (), ()
        if self.on_chart:
            first, *rest = sorted(self.stamps)
            return (Mark(int(first[0]), first[1], label, "amber"), *(Mark(int(t), p, "", "amber") for t, p in rest)), ()
        return (), (Time(int(min(t for t, _ in self.stamps)), label, "amber"),)


def entry_fills(db: Session, trade_id) -> Fills:
    from app.models import Fill, Trade, TradeFill
    if trade_id is None:
        return Fills()
    trade = db.get(Trade, trade_id)
    if trade is None:
        return Fills()
    rows = db.exec(select(Fill.executed_at, Fill.price).join(TradeFill, TradeFill.fill_id == Fill.id)
                   .where(TradeFill.trade_id == trade_id, TradeFill.role == "entry")).all()
    return Fills(tuple(sorted((_epoch_ny(at), float(price)) for at, price in rows if at is not None)),
                 trade.instrument_type != "option")


def plan_levels(db: Session, source_id: str | None) -> tuple[tuple[str, float], ...]:
    """A confirmed plan's levels (role, price) from its level alerts."""
    from app.models import LevelAlert
    if not source_id:
        return ()
    rows = db.exec(select(LevelAlert.plan_role, LevelAlert.price).where(
        LevelAlert.source_kind == "copilot", LevelAlert.source_id == source_id, LevelAlert.plan_role.is_not(None))).all()
    return tuple(sorted({(role, float(price)) for role, price in rows}))


ROLE_LABEL = {"entry": ("TRIG", "up"), "invalidation": ("INV", "down")}


def _plan_level_marks(levels) -> tuple[Level, ...]:
    return tuple(Level(price, f"{ROLE_LABEL.get(role, (role.upper(), 'muted'))[0]} {_price(price)}",
                       ROLE_LABEL.get(role, ("", "muted"))[1]) for role, price in levels)


# ------------------------------------------------------------------ the pictures


def plan_level(title: str, symbol: str, levels, event_at: float, fills: Fills, now: float) -> Callable[[], Chart | None]:
    """A plan's entry trigger or invalidation: the last 90 minutes with the plan's levels and the fill."""
    def build() -> Chart | None:
        shown = _window(today_bars(symbol), now)
        if not shown:
            return None
        marks, times = fills.marks()
        first = shown[0]["time"]
        return Chart(title=title, note=f"NOW {_price(shown[-1]['close'])}", bars=tuple(shown), levels=_plan_level_marks(levels),
                     marks=tuple(m for m in marks if m.time >= first), times=tuple(t for t in times if t.time >= first)
                     + ((Time(int(event_at), _clock(event_at), "muted"),) if event_at >= first else ()))
    return build


def position(title: str, note: str, symbol: str, opened_at: float | None, peak_at: float | None, fills: Fills,
             now: float) -> Callable[[], Chart | None]:
    """An open-trade alert: the underlying today since 15 minutes before the entry (the last 120 minutes when the entry
    was on an earlier day), with the entry, the peak and now."""
    def build() -> Chart | None:
        found = _window(today_bars(symbol), now, minutes=24 * 60)
        since = [b for b in found if opened_at is not None and b["time"] >= opened_at - 15 * 60]
        shown = since if since and since[0]["time"] <= opened_at else found[-POSITION_BARS:]
        if not shown:
            return None
        first, last = shown[0]["time"], shown[-1]
        marks, times = fills.marks("ENTRY")
        times = tuple(t for t in times if t.time >= first)
        if peak_at is not None and peak_at >= first:
            times += (Time(int(peak_at), "PEAK", "violet"),)
        return Chart(title=title, note=note, bars=tuple(shown), marks=tuple(m for m in marks if m.time >= first)
                     + (Mark(last["time"], last["close"], "NOW", "text"),), times=times)
    return build


def day_with_stop(title: str, symbol: str, due_at: float, fills: Fills, now: float) -> Callable[[], Chart | None]:
    """A time stop: the regular session so far with the stop time and the entry."""
    def build() -> Chart | None:
        found = _window(today_bars(symbol), now, minutes=24 * 60)
        shown = [b for b in found if not b.get("extended")] or found
        if not shown:
            return None
        first = shown[0]["time"]
        marks, times = fills.marks("ENTRY")
        return Chart(title=title, note=f"OUT {_clock(due_at)}", bars=tuple(shown), marks=tuple(m for m in marks if m.time >= first),
                     times=tuple(t for t in times if t.time >= first) + (Time(int(due_at), f"OUT {_clock(due_at)}", "amber"),))
    return build


def fill_window(title: str, symbol: str, fills: Fills, now: float) -> Callable[[], Chart | None]:
    """A no-plan nudge or link ping: the last 90 minutes with the fill."""
    def build() -> Chart | None:
        shown = _window(today_bars(symbol), now)
        if not shown:
            return None
        first = shown[0]["time"]
        marks, times = fills.marks()
        return Chart(title=title, note=f"NOW {_price(shown[-1]['close'])}", bars=tuple(shown),
                     marks=tuple(m for m in marks if m.time >= first), times=tuple(t for t in times if t.time >= first))
    return build


def radar(title: str, store, event_id: str, session_date: str, now: float) -> Callable[[], Chart | None]:
    """A Radar event: the stock (or the group's median) against its benchmark over the session's recorded passes."""
    def build() -> Chart | None:
        event = store.event(event_id)
        if event is None:
            return None
        symbols = list(event.get("symbols") or [])
        group = event.get("kind") == "group_move"
        benchmark = "SPY" if group else event.get("benchmark") or "SPY"
        passes = [p for p in store.passes(session_date) if p.get("status") in ("ok", "partial")]
        quotes = store.pass_quotes([p["id"] for p in passes])
        mine: list[tuple[int, float]] = []
        bench: list[tuple[int, float]] = []
        for p in passes:
            stamp = datetime.fromisoformat(str(p["finished_at"]).replace("Z", "+00:00")).timestamp()
            if stamp > now:
                continue
            rows = quotes.get(p["id"]) or {}
            moves = [m for m in (_change(rows.get(s)) for s in symbols) if m is not None]
            base = _change(rows.get(benchmark))
            if moves:
                mine.append((int(stamp), median(moves) if group else moves[0]))
            if base is not None:
                bench.append((int(stamp), base))
        if len(mine) < 2:
            return None
        label = (event.get("group") or "GROUP") if group else symbols[0]
        return Chart(title=title, series=(Series(label, tuple(mine), "blue"), Series(benchmark, tuple(bench), "muted")))
    return build


def _change(row: dict | None) -> float | None:
    if not row:
        return None
    last, prev = row.get("last"), row.get("prev_close")
    if not isinstance(last, (int, float)) or not isinstance(prev, (int, float)) or prev <= 0:
        return None
    return (last / prev - 1) * 100


def thesis(title: str, symbol: str, reference: float | None, wording: str, now: float) -> Callable[[], Chart | None]:
    """Thesis watch: today's minutes with the price the move is measured from."""
    def build() -> Chart | None:
        shown = _window(today_bars(symbol), now, minutes=POSITION_BARS * 3)
        if not shown:
            return None
        last = shown[-1]["close"]
        levels = ()
        note = f"NOW {_price(last)}"
        if reference:
            levels = (Level(reference, f"REF {_price(reference)}", "amber"),)
            note = f"{(last / reference - 1) * 100:+.1f}% {wording}".strip()
        return Chart(title=title, note=note, bars=tuple(shown), levels=levels)
    return build


def positions_strip(title: str, rows: list[tuple[str, int]]) -> Callable[[], Chart | None]:
    """Pre-market prep: the open options by days to expiry, soonest first."""
    def build() -> Chart | None:
        if not rows:
            return None
        longest = max(max(days for _, days in rows), 1)
        return Chart(title=title, rows=tuple(
            Row(label, "TODAY" if days <= 0 else f"{days}D", max(days, 0) / longest or 0.02,
                "down" if days <= 0 else "amber" if days <= 2 else "blue")
            for label, days in sorted(rows, key=lambda r: (r[1], r[0]))))
    return build


def armed_plan(title: str, symbol: str, levels, day: date, calendar=None) -> Callable[[], Chart | None]:
    """Pre-market prep with no options open: the first armed plan's symbol (this morning's minutes, else the last
    session's) with its levels."""
    def build() -> Chart | None:
        from app.engine.chart_levels import previous_session
        shown = today_bars(symbol)
        if not shown and (previous := previous_session(day, calendar)) is not None:
            shown = stored_bars(symbol, previous)
        shown = shown[-POSITION_BARS * 3:]
        if not shown:
            return None
        return Chart(title=title, note=f"{symbol} {_price(shown[-1]['close'])}", bars=tuple(shown), levels=_plan_level_marks(levels))
    return build


def premarket_facts(db: Session, today: date) -> tuple[list[tuple[str, int]], tuple[str, tuple] | None]:
    """(open options as (contract label, days to expiry), the first armed plan as (symbol, levels) or None)."""
    from sqlalchemy import or_
    from app.engine.chart_journal import contract_label
    from app.models import Account, LevelAlert, Trade
    trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                     .where(Trade.status == "open", Trade.instrument_type == "option", Trade.expiration.is_not(None))
                     .where(or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    rows = sorted({(contract_label(t.ticker, t.instrument_type, t.option_type, t.strike, t.expiration), (t.expiration - today).days)
                   for t in trades}, key=lambda r: (r[1], r[0]))
    plan = None
    if not rows:
        armed = db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", LevelAlert.plan_role.is_not(None),
                                                 LevelAlert.state == "active").order_by(LevelAlert.created_at)).first()
        if armed is not None:
            plan = (armed.symbol, plan_levels(db, armed.source_id))
    return rows, plan
