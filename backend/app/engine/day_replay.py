"""Watch your day: at the close, a short replay clip of today for each symbol the owner traded, scrubbed by thumb.

**The clip.** For each symbol with a fill on the day (Webull left out while it is dormant), ``FRAMES`` frames
(``FPS`` a second, so about 30 seconds) of the regular session (widened to take in a fill outside it) drawn by
``chart_render.frame``: the day's bars up to the frame's minute as 3-minute candles on a fixed axis, the confirmed
plan's trigger and invalidation lines from when they were armed, each fill as a BUY or SELL dot as it happens (a
stock at its price, an option on the underlying at the fill's minute), a PING line when a phone ping for the symbol
went out, and the clock in the corner. Frame ``i`` shows everything before ``times[i]``.

The frames are encoded as an **animated PNG** (``chart_render.apng``), not a GIF: the app's dark theme is already
an 11-colour palette, so APNG keeps it exactly with no quantising, plays in any ``<img>``, and since every frame is a
whole PNG the replay page can cut one out and draw it to a canvas, which is what makes thumb scrubbing simple (a
browser cannot seek an animated image). A clip over ``MAX_BYTES`` keeps every other frame (half the rate, same
length), then halves the picture, until it fits.

Bars come from storage only: the completed session on disk, or for today the chart feed's minutes already read for
the chart and the ping pictures (``ping_images.today_bars``). No model call.

**Storage.** ``<CAPTURE_STORAGE_DIR>/day-replay/<date>/<SYMBOL>.png`` plus ``index.json`` (each clip's frame times,
rate and size; the day's fill and ping counts) and ``poster.png`` (the first clip's last frame, the ping's picture).
A day is kept ``KEEP_DAYS`` and then deleted; the private API serves it to the owner only (``routers/replay.py``).

**The job.** Off unless ``DAY_REPLAY_ENABLED=true``. On the level alert monitor's loop: at 16:20 New York on a trading
day the day is claimed once (``DayReplay.day`` is unique), the clips are built on a worker thread, and a day with no
fill is recorded ``skipped`` with nothing built or sent. Otherwise one ping, "Watch your day: NBIS, SPY · 3 fills,
2 pings", goes through ``notification_policy.decide`` (kind ``day_replay``, ranked with the prep) and opens
``/replay/<date>``. Delivery is at-most-once, as the week review's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Callable
import uuid

import numpy as np
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import captures, chart_render, notification_policy, ntfy, ping_images
from app.engine.chart_math import ET, session_windows
from app.engine.chart_render import Chart, Level, Mark, Time
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc
from app.engine.premarket_prep import _trading_day
from app.models import DayReplay

log = logging.getLogger(__name__)

FRAMES = 300
FPS = 10
SLOT = 180  # seconds per candle: 130 candles in a regular session
MAX_BYTES = 8_000_000
MIN_FRAMES = 30
KEEP_DAYS = 14
RUN_SECONDS = 30
AT = 16 * 60 + 20
PREPARE_SECONDS = 10 * 60
EXPIRE_SECONDS = 2 * 60 * 60
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
BUYS = frozenset({"buy", "buy_to_open", "buy_to_close"})
TITLE = "Watch your day"


def enabled() -> bool:
    return os.environ.get("DAY_REPLAY_ENABLED", "").strip().lower() == "true"


# ------------------------------------------------------------------ the day's facts


@dataclass(frozen=True)
class Fill:
    time: int  # epoch seconds
    buy: bool
    price: float | None  # on the chart's basis: a stock's price, an option's underlying at the fill (when known)


@dataclass(frozen=True)
class PlanLine:
    since: int  # epoch seconds: armed
    role: str  # entry | invalidation
    price: float


@dataclass(frozen=True)
class SymbolDay:
    symbol: str
    day: date
    bars: tuple[dict, ...]
    fills: tuple[Fill, ...]
    pings: tuple[int, ...] = ()
    plan: tuple[PlanLine, ...] = ()


def _ny(moment: datetime) -> int:
    return int((moment.replace(tzinfo=ET) if moment.tzinfo is None else moment).timestamp())


def _naive_utc(moment: datetime | None) -> int | None:
    return None if moment is None else int(moment.replace(tzinfo=UTC).timestamp())


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """The New York day as naive UTC (for the UTC columns)."""
    start = datetime(day.year, day.month, day.day, tzinfo=ET)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)


def traded(db: Session, day: date) -> dict[str, tuple[Fill, ...]]:
    """The day's fills by symbol (New York day; Webull left out), symbols in order of their first fill."""
    from app.models import Account, Fill as FillRow
    rows = db.exec(select(FillRow).join(Account, Account.id == FillRow.account_id)
                   .where(FillRow.executed_at >= datetime.combine(day, datetime.min.time()),
                          FillRow.executed_at < datetime.combine(day + timedelta(days=1), datetime.min.time()))
                   .where(or_(Account.broker.is_(None), Account.broker != "webull"))
                   .order_by(FillRow.executed_at)).all()
    out: dict[str, list[Fill]] = {}
    for row in rows:
        symbol = (row.ticker or "").upper()
        if not SYMBOL.fullmatch(symbol):
            continue
        price = float(row.price) if row.instrument_type != "option" else (
            float(row.underlying_price_at_fill) if row.underlying_price_at_fill else None)
        out.setdefault(symbol, []).append(Fill(_ny(row.executed_at), row.side in BUYS, price))
    return {symbol: tuple(fills) for symbol, fills in out.items()}


def pings(db: Session, day: date, symbol: str) -> tuple[int, ...]:
    """When a phone ping for the symbol went out that day (the policy's sent records)."""
    from app.models import PhonePing
    start, end = _day_bounds(day)
    rows = db.exec(select(PhonePing.decided_at).where(PhonePing.symbol == symbol, PhonePing.decision == "sent",
                                                      PhonePing.decided_at >= start, PhonePing.decided_at < end)).all()
    return tuple(sorted(_naive_utc(at) for at in rows))


def plan_lines(db: Session, day: date, symbol: str) -> tuple[PlanLine, ...]:
    """Confirmed plans' trigger and invalidation in the symbol that were armed on the day: made before its end and not
    fired before its start."""
    from app.models import LevelAlert
    start, end = _day_bounds(day)
    rows = db.exec(select(LevelAlert).where(LevelAlert.symbol == symbol, LevelAlert.source_kind == "copilot",
                                            LevelAlert.plan_role.in_(("entry", "invalidation")), LevelAlert.created_at < end)
                   .where(or_(LevelAlert.fired_at.is_(None), LevelAlert.fired_at >= start))).all()
    return tuple(sorted({PlanLine(_naive_utc(r.created_at), r.plan_role, float(r.price)) for r in rows}, key=lambda p: (p.since, p.role)))


def bars(symbol: str, day: date) -> list[dict]:
    """The day's minute bars from storage: the completed session on disk, else (today) the chart feed's minutes."""
    stored = ping_images.stored_bars(symbol, day)
    if stored:
        return stored
    if day == datetime.now(ET).date():
        return ping_images.today_bars(symbol)
    return []


# ------------------------------------------------------------------ frames


def window(day: SymbolDay, calendar=None) -> tuple[int, int]:
    """The clip's span in epoch seconds: the regular session, widened to take in every fill."""
    hours = calendar.hours(day.day) if calendar is not None else None
    regular = next((w for w in session_windows(day.day, hours) if w[0] == "regular"), ("regular", 570, 960))
    midnight = int(datetime(day.day.year, day.day.month, day.day.day, tzinfo=ET).timestamp())
    start, end = midnight + regular[1] * 60, midnight + regular[2] * 60
    for fill in day.fills:
        minute = fill.time - fill.time % 60
        start, end = min(start, minute - minute % SLOT), max(end, minute + 60)
    return start, end


def frame_times(start: int, end: int, count: int = FRAMES) -> list[int]:
    """Frame ``i`` shows what happened before ``times[i]``; the last frame is the whole span."""
    return [start + round((i + 1) * (end - start) / count) for i in range(count)]


def first_frame(times: list[int], stamp: int) -> int | None:
    """The first frame that shows something that happened at ``stamp``."""
    return next((i for i, t in enumerate(times) if t > stamp), None)


def _price_at(shown: list[dict], stamp: int) -> float | None:
    before = [b for b in shown if b["time"] <= stamp]
    return before[-1]["close"] if before else (shown[0]["open"] if shown else None)


def charts(day: SymbolDay, calendar=None, count: int = FRAMES) -> tuple[tuple[int, int, float, float], list[tuple[int, Chart]]]:
    """The clip's axes ``(start, end, low, high)`` and each frame's (time, chart)."""
    start, end = window(day, calendar)
    shown = sorted((b for b in day.bars if start <= b["time"] < end), key=lambda b: b["time"])
    fills = [(f, f.price if f.price is not None else _price_at(shown, f.time)) for f in day.fills]
    prices = [p for b in shown for p in (b["low"], b["high"])] + [p for _, p in fills if p is not None]
    prices += [line.price for line in day.plan]
    low, high = (min(prices), max(prices)) if prices else (0.0, 1.0)
    title = f"{day.symbol} {day.day:%b} {day.day.day}"
    out = []
    for t in frame_times(start, end, count):
        levels = {}
        for line in day.plan:  # the latest plan's line of each role armed by now
            if line.since < t:
                levels[line.role] = line
        out.append((t, Chart(
            title=title, note=datetime.fromtimestamp(t, ET).strftime("%H:%M"),
            bars=tuple(b for b in shown if b["time"] < t),
            levels=tuple(Level(line.price, f"{ping_images.ROLE_LABEL[line.role][0]} {line.price:,.2f}",
                               ping_images.ROLE_LABEL[line.role][1]) for _, line in sorted(levels.items())),
            marks=tuple(Mark(f.time, p, "BUY" if f.buy else "SELL", "up" if f.buy else "down")
                        for f, p in fills if p is not None and f.time < t),
            times=tuple(Time(stamp, "PING", "violet") for stamp in day.pings if start <= stamp < t))))
    return (start, end, low, high), out


@dataclass(frozen=True)
class Clip:
    png: bytes
    times: tuple[int, ...]
    fps: float
    width: int
    height: int
    poster: bytes  # the last frame as a still PNG


def clip(day: SymbolDay, calendar=None, max_bytes: int | None = None) -> Clip | None:
    """The symbol's day as an APNG within ``max_bytes`` (``MAX_BYTES``); None without bars."""
    cap = MAX_BYTES if max_bytes is None else max_bytes
    (start, end, low, high), frames = charts(day, calendar)
    if not any(b for b in day.bars if start <= b["time"] < end):
        return None
    pixels = [chart_render.frame(c, start=start, end=end, low=low, high=high, slot=SLOT) for _, c in frames]
    times = [t for t, _ in frames]
    poster = chart_render._png(pixels[-1])
    fps = float(FPS)
    data = chart_render.apng(pixels, fps)
    while len(data) > cap:
        if len(pixels) > MIN_FRAMES * 2:  # half the rate, the same length; the last frame stays
            keep = (len(pixels) - 1) % 2
            pixels, times, fps = pixels[keep::2], times[keep::2], fps / 2
        elif pixels[0].shape[1] > chart_render.WIDTH // 4:
            pixels = [np.ascontiguousarray(p[::2, ::2]) for p in pixels]
        else:
            log.warning("Day replay for %s is %d bytes, over the %d cap even at its smallest", day.symbol, len(data), cap)
            break
        data = chart_render.apng(pixels, fps)
    height, width = pixels[0].shape
    return Clip(data, tuple(times), fps, width, height, poster)


# ------------------------------------------------------------------ storage


def root() -> Path:
    return captures.storage_root() / "day-replay"


def _today() -> date:
    return datetime.now(ET).date()


def expired(day: date, today: date | None = None) -> bool:
    return day < (today or _today()) - timedelta(days=KEEP_DAYS)


def purge(today: date | None = None) -> int:
    """Delete the days past ``KEEP_DAYS``; returns how many."""
    gone = 0
    for path in root().iterdir() if root().is_dir() else []:
        try:
            day = date.fromisoformat(path.name)
        except ValueError:
            continue
        if expired(day, today):
            shutil.rmtree(path, ignore_errors=True)
            gone += 1
    return gone


def save(day: date, clips: dict[str, Clip], fills: int, ping_count: int) -> dict:
    """Write the day's clips, then its index (last, so a listed clip is always whole)."""
    folder = root() / day.isoformat()
    for symbol, made in clips.items():
        captures._write(folder / f"{symbol}.png", made.png)
    if clips:
        captures._write(folder / "poster.png", next(iter(clips.values())).poster)
    index = {"date": day.isoformat(), "fills": fills, "pings": ping_count,
             "clips": [{"symbol": symbol, "frames": len(c.times), "fps": c.fps, "width": c.width, "height": c.height,
                        "bytes": len(c.png), "times": list(c.times)} for symbol, c in clips.items()]}
    captures._write(folder / "index.json", json.dumps(index, separators=(",", ":")).encode())
    return index


def index(day: date, today: date | None = None) -> dict | None:
    """The day's clips as saved, or None when there are none or the day has expired."""
    if expired(day, today):
        return None
    try:
        return json.loads((root() / day.isoformat() / "index.json").read_text())
    except (OSError, ValueError):
        return None


def load(day: date, symbol: str, today: date | None = None) -> bytes | None:
    if not SYMBOL.fullmatch(symbol) or index(day, today) is None:
        return None
    try:
        return (root() / day.isoformat() / f"{symbol}.png").read_bytes()
    except OSError:
        return None


def days(today: date | None = None) -> list[dict]:
    """Every kept day with clips, newest first: ``{date, symbols}``."""
    out = []
    for path in sorted(root().iterdir(), reverse=True) if root().is_dir() else []:
        try:
            day = date.fromisoformat(path.name)
        except ValueError:
            continue
        found = index(day, today)
        if found and found.get("clips"):
            out.append({"date": found["date"], "symbols": [c["symbol"] for c in found["clips"]]})
    return out


# ------------------------------------------------------------------ build


def build(db: Session, day: date, calendar=None, read_bars: Callable[[str, date], list[dict]] | None = None) -> dict | None:
    """Read the day, render and save its clips; None (nothing written) when the owner had no fill."""
    read_bars = read_bars or bars
    found = traded(db, day)
    if not found:
        return None
    made: dict[str, Clip] = {}
    fill_count = ping_count = 0
    for symbol, fills in found.items():
        symbol_day = SymbolDay(symbol, day, tuple(read_bars(symbol, day) or ()), fills, pings(db, day, symbol), plan_lines(db, day, symbol))
        fill_count += len(fills)
        ping_count += len(symbol_day.pings)
        result = clip(symbol_day, calendar)
        if result is not None:
            made[symbol] = result
        else:
            log.info("Day replay: no stored bars for %s on %s", symbol, day)
    return save(day, made, fill_count, ping_count)


def ping_title(saved: dict) -> str:
    symbols = ", ".join(c["symbol"] for c in saved["clips"])
    fills, sent = saved["fills"], saved["pings"]
    return f"{TITLE}: {symbols} · {fills} fill{'' if fills == 1 else 's'}, {sent} ping{'' if sent == 1 else 's'}"


def ping_body(saved: dict) -> str:
    seconds = max((c["frames"] / c["fps"] for c in saved["clips"]), default=0)
    return f"A {round(seconds)}-second replay of each symbol you traded today. Tap to scrub through it."


class DayReplays:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None,
                 read_bars: Callable[[str, date], list[dict]] | None = None):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.read_bars = read_bars
        self._spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True, name="day-replay").start())
        self._last_run = 0.0

    def run(self) -> None:
        """Claim today's replay once it is due, then build it off the alert loop."""
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        if not enabled():
            return
        moment = datetime.fromtimestamp(now, ET)
        if moment.hour * 60 + moment.minute < AT or not _trading_day(self.calendar, moment.date()):
            return
        with Session(self.engine) as db:
            if db.exec(select(DayReplay.id).where(DayReplay.day == moment.date())).first():
                return
            row = DayReplay(day=moment.date(), detected_at=_utc(now))
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # another process claimed the day a moment earlier
                return
            row_id = row.id
        log.info("Day replay claimed for %s", moment.date())
        self._spawn(lambda: self._prepare_and_send(row_id))

    def _prepare_and_send(self, row_id: uuid.UUID) -> None:
        try:
            self.prepare(row_id)
        except Exception:
            log.exception("Day replay failed")
            with Session(self.engine) as db:
                db.exec(update(DayReplay).where(DayReplay.id == row_id, DayReplay.delivery == "preparing")
                        .values(delivery="expired", last_error="The clips could not be built, so nothing was sent."))
                db.commit()
            return
        self.deliver()

    def prepare(self, row_id: uuid.UUID) -> None:
        """Build and save the day's clips and queue the ping (or skip a day with no fill)."""
        with Session(self.engine) as db:
            row = db.get(DayReplay, row_id)
            if row is None or row.delivery != "preparing":
                return
            day = row.day
            purge(day)
            saved = build(db, day, self.calendar, self.read_bars)
            if saved is None or not saved["clips"]:
                row.delivery = "skipped"
                row.last_error = "No fills today, so no replay was built." if saved is None else "No stored bars for the symbols traded today."
                db.add(row)
                db.commit()
                return
            queued = db.exec(update(DayReplay).where(DayReplay.id == row_id, DayReplay.delivery == "preparing").values(
                delivery="pending", symbols=",".join(c["symbol"] for c in saved["clips"]), fills=saved["fills"],
                pings=saved["pings"], title=ping_title(saved), body=ping_body(saved)))
            db.commit()
            if queued.rowcount == 1:
                log.info("Day replay ready for %s: %s", day, ping_title(saved))

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            db.exec(update(DayReplay).where(DayReplay.delivery == "preparing", DayReplay.detected_at < _utc(now - PREPARE_SECONDS))
                    .values(delivery="expired", last_error="The clips did not finish in time, so nothing was sent."))
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(DayReplay).where(DayReplay.delivery == "sending", DayReplay.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(DayReplay.id).where(DayReplay.delivery == "pending")
                          .where((DayReplay.next_attempt_at.is_(None)) | (DayReplay.next_attempt_at <= _utc(now)))
                          .order_by(DayReplay.detected_at).limit(5)).all()
        for row_id in due:
            self._send(row_id)

    def _send(self, row_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(DayReplay).where(DayReplay.id == row_id, DayReplay.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            row = db.get(DayReplay, row_id)
            if now - _epoch(row.detected_at) > EXPIRE_SECONDS:
                row.delivery, row.last_error = "expired", "Not sent within 2 hours of its time, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                row.delivery, row.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                row.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            title, text, path = row.title or TITLE, row.body or "", f"/replay/{row.day.isoformat()}"
            ticket = notification_policy.decide(db, sender="day_replay", source_id=str(row.id), kind="day_replay",
                                                title=title, body=text, now=now)
            if ticket.held:
                row.delivery, row.last_error = "held", ticket.reason
                db.commit()
                return
            row.attempts += 1
            image = None
            if row.attempts == 1 and ping_images.enabled():  # a retry goes as text, as every picture ping's does
                try:
                    image = (root() / row.day.isoformat() / "poster.png").read_bytes()
                except OSError:
                    image = None
            try:
                _, state = ping_images.publish(title, text + ticket.append, image, priority=3, tags=("clapper",), path=path,
                                               direct_click=True)
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    row.delivery, row.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    row.delivery, row.last_error = "pending", str(exc)
                    row.next_attempt_at = _utc(now + BACKOFF[min(row.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Day replay delivery failed (attempt %d): %s", row.attempts, exc)
                return
            row.delivery, row.delivered_at = "sent", _utc(self.clock())
            notification_policy.delivered(db, ticket, now)
            ping_images.record(db, ticket, state)
            db.commit()
