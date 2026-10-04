"""The level alert monitor (Charts C5.1): judges every active alert whether or
not a chart is open, records each firing once and delivers it to the phone.

It runs in the API process beside the one Tradier market stream
(``chart_stream.py``) and adds the alerted symbols to that stream's single
subscription while any session could trade (04:00-20:00 New York). Three
things happen in order on each pass of one loop, at least every
``SWEEP_SECONDS`` and at once when a trade fires an alert or an alert changes:

1. **Record.** A firing found on the stream waits in memory only until this
   pass writes it. The event row's unique (alert, generation) is the
   deduplication: a reconnect, a restart or the sweep finding the same firing
   again cannot record a second one.
2. **Deliver.** Pending events are claimed one at a time (an update that only
   one process can win), sent through ntfy and marked sent, or put back with a
   backoff. Delivery is at-least-once; a claim older than two minutes (a crash
   mid-send) is put back. An event not delivered within six hours expires.
3. **Sweep.** For each alerted symbol, today's 1-minute bars through the chart
   feed's shared, cached and budgeted read (the same request an open chart
   makes, so a charted symbol costs nothing extra). "Closes beyond" alerts are
   judged on its closed candles. Touch and cross alerts are judged on minutes
   the stream did not cover: a restart, a reconnect or an outage.
"""

import asyncio
from datetime import UTC, date, datetime
import logging
import time
from typing import Callable
import uuid

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import level_alerts, ntfy
from app.engine.chart_feed import ChartFeedError
from app.engine.chart_math import ET, chart_bars, normalize_bars, session_windows
from app.models import LevelAlert, LevelAlertEvent

log = logging.getLogger(__name__)

SWEEP_SECONDS = 20
CLAIM_SECONDS = 120
EXPIRE_SECONDS = 6 * 3600
BACKOFF = (30, 60, 120, 300, 900)
UNCONFIGURED_RETRY = 300
STREAM_HOURS = (4 * 60 - 5, 20 * 60 + 5)  # New York minutes when trades can print, with a margin


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _span(day: date, windows: list[tuple[str, int, int]], session: str) -> tuple[float, float]:
    """When an alert's session runs on ``day``: the regular hours, or premarket through postmarket."""
    parts = [w for w in windows if session == "extended" or w[0] == "regular"]
    start, end = min(w[1] for w in parts), max(w[2] for w in parts)
    return tuple(datetime(day.year, day.month, day.day, m // 60, m % 60, tzinfo=ET).timestamp() for m in (start, end))


class LevelAlertMonitor:
    def __init__(self, engine, stream=None, *, feed=None, calendar=None, splits=None,
                 clock: Callable[[], float] = time.time, sweep_seconds: float = SWEEP_SECONDS):
        self.engine = engine
        self.stream = stream
        self.feed = feed
        self.calendar = calendar
        self.splits = splits
        self.clock = clock
        self.sweep_seconds = sweep_seconds
        # Read on the event loop by the stream's tick hook; replaced whole by each reload.
        self._watched: dict[uuid.UUID, dict] = {}
        self._firing: set[tuple[uuid.UUID, int]] = set()
        self._found: list[dict] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def changed(self) -> None:
        """An alert was added, removed or re-armed: reload now. Safe from any thread."""
        if self._loop is not None and self._wake is not None:
            self._loop.call_soon_threadsafe(self._wake.set)

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Level alert pass failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.sweep_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def run_once(self) -> None:
        await self._record_found()
        await asyncio.to_thread(self.deliver)
        await asyncio.to_thread(self.reload)
        if self.stream is not None and self.symbols():
            self.stream.ensure_running()
        fired = await asyncio.to_thread(self.sweep)
        if fired:
            self._found.extend(fired)
            await self._record_found()
            await asyncio.to_thread(self.deliver)

    async def _record_found(self) -> None:
        """Write the firings waiting in memory. If the database fails, they wait for the next pass:
        their alerts are held out of judging until then, so dropping them would lose the firing."""
        found, self._found = self._found, []
        if not found:
            return
        try:
            await asyncio.to_thread(self.record, found)
        except Exception:
            self._found = found + self._found  # recording again is safe: a written firing is skipped
            raise

    # ------------------------------------------------------------ the stream

    def symbols(self) -> set[str]:
        """Symbols the stream should carry for touch and cross alerts, while trades can print."""
        moment = datetime.fromtimestamp(self.clock(), ET)
        minute = moment.hour * 60 + moment.minute
        if moment.weekday() >= 5 or not STREAM_HOURS[0] <= minute < STREAM_HOURS[1]:
            return set()
        return {alert["symbol"] for alert in self._watched.values() if alert["condition"] != "closes_beyond"}

    def on_tick(self, tick: dict) -> None:
        """One validated trade, before coalescing. Runs on the event loop: memory only."""
        for alert in self._watched.values():
            if alert["symbol"] != tick["symbol"] or alert["condition"] == "closes_beyond":
                continue
            if alert["session"] == "regular" and tick["session"] != "regular":
                continue
            if tick["at"] < alert["armed_at"] or (alert["id"], alert["generation"]) in self._firing:
                continue
            if level_alerts.trade_fires(alert["condition"], alert["direction"], alert["level"], tick["price"]):
                self._firing.add((alert["id"], alert["generation"]))
                self._found.append(self._event(alert, tick["price"], tick["at"], "stream", None))
                if self._wake is not None:
                    self._wake.set()

    def _event(self, alert: dict, price: float, at: float, source: str, bar_time: int | None) -> dict:
        return {"alert_id": alert["id"], "generation": alert["generation"], "level": alert["level"], "price": price,
                "event_at": at, "source": source, "bar_time": bar_time, "detected_at": self.clock()}

    # ------------------------------------------------------------ reload

    def reload(self) -> None:
        """Active alerts from the database, each on today's price basis."""
        today = datetime.fromtimestamp(self.clock(), ET).date()
        with Session(self.engine) as db:
            rows = db.exec(select(LevelAlert).where(LevelAlert.state == "active")).all()
        watched = {}
        for row in rows:
            if (row.id, row.generation) in self._firing:
                continue
            watched[row.id] = {
                "id": row.id, "generation": row.generation, "symbol": row.symbol, "condition": row.condition,
                "interval": row.interval, "session": row.session, "direction": row.direction,
                "level": self._level(row.symbol, row.price, row.created_on, today),
                "armed_at": _epoch(row.armed_at), "checked_through": row.checked_through,
            }
        self._watched = watched

    def _level(self, symbol: str, price: float, created_on: date, today: date) -> float:
        if self.splits is None or created_on >= today:
            return price
        info = self.splits.get(symbol, today)
        return level_alerts.on_today_basis(price, created_on, info["splits"])

    # ------------------------------------------------------------ sweep

    def sweep(self) -> list[dict]:
        """Judge closed candles and uncovered minutes; returns firings and saves each alert's progress.

        A symbol's minutes are read only when a candle of an alert's session
        may have become final since the alert was last judged: never on a
        closed day, before the session or once its last candle was judged, and
        touch or cross alerts the stream covered throughout need no read at all.
        """
        if self.feed is None or not self._watched:
            return []
        now = self.clock()
        today = datetime.fromtimestamp(now, ET).date()
        if now < datetime(today.year, today.month, today.day, 4, tzinfo=ET).timestamp():
            return []  # no minutes yet; Tradier refuses a start in the future
        hours = self.calendar.hours(today) if self.calendar is not None else None
        windows = session_windows(today, hours)
        if not windows:
            return []  # a weekend or a market holiday: nothing trades
        # The newest minute end that can be final: every candle ends on a minute.
        mark = int((now - level_alerts.LATENESS) // 60) * 60
        fired, progress = [], {}
        for symbol in sorted({alert["symbol"] for alert in self._watched.values()}):
            due = []
            for alert in self._watched.values():
                if alert["symbol"] != symbol or (alert["id"], alert["generation"]) in self._firing:
                    continue
                start, end = _span(today, windows, alert["session"])
                limit = min(mark, end)  # judged no further than the session's last candle
                after = max(alert["checked_through"] or 0, alert["armed_at"])
                if limit <= max(after, start):
                    continue
                if alert["condition"] != "closes_beyond" and self.stream is not None and self.stream.covered(symbol, after, limit):
                    progress[alert["id"]] = alert["checked_through"] = limit  # the stream judged every trade
                    continue
                due.append((alert, limit))
            if not due:
                continue
            try:
                data, _, _ = self.feed.read("/v1/markets/timesales", {
                    "symbol": symbol, "interval": "1min", "session_filter": "all",
                    "start": today.strftime("%Y-%m-%d 04:00"), "end": today.strftime("%Y-%m-%d 20:00"),
                }, 15)
            except ChartFeedError as exc:
                log.info("Level alert sweep skipped %s: %s", symbol, exc)
                continue
            series = (data or {}).get("series") or {}
            rows = series.get("data") if isinstance(series, dict) else None
            minutes = normalize_bars(rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else [])
            for alert, limit in due:
                found, checked = self._judge(alert, minutes, hours, today, now)
                if found:
                    self._firing.add((alert["id"], alert["generation"]))
                    fired.append(found)
                    continue
                # Judged through `limit` even where no candle traded, so a quiet minute is not read again.
                checked = max(checked or 0, limit)
                if checked != alert["checked_through"]:
                    progress[alert["id"]] = alert["checked_through"] = checked
        if progress:
            with Session(self.engine) as db:
                for alert_id, checked in progress.items():
                    db.exec(update(LevelAlert).where(LevelAlert.id == alert_id, LevelAlert.state == "active")
                            .values(checked_through=checked))
                db.commit()
        return fired

    def _judge(self, alert: dict, minutes: list[dict], hours, today: date, now: float) -> tuple[dict | None, int | None]:
        after = max(alert["checked_through"] or 0, alert["armed_at"])
        if alert["condition"] == "closes_beyond":
            bars = level_alerts.final(chart_bars(minutes, [], alert["interval"], alert["session"], {today: hours}), now, after)
            for bar in bars:
                if level_alerts.close_fires(alert["direction"], alert["level"], bar):
                    return self._event(alert, bar["close"], bar["end_time"], "closed_bar", bar["time"]), None
        else:
            # A minute that started before the alert was armed may hold trades from before it.
            bars = [bar for bar in level_alerts.final(chart_bars(minutes, [], "1m", alert["session"], {today: hours}), now, after)
                    if bar["time"] >= alert["armed_at"]]
            for bar in bars:
                if self.stream is not None and self.stream.covered(alert["symbol"], bar["time"], bar["end_time"]):
                    continue  # the stream judged every trade in this minute
                if level_alerts.minute_fires(alert["condition"], alert["direction"], alert["level"], bar):
                    extreme = bar["high"] if alert["direction"] == "up" else bar["low"]
                    return self._event(alert, extreme, bar["time"], "minute_bars", bar["time"]), None
        return None, (max(int(bar["end_time"]) for bar in bars) if bars else None)

    # ------------------------------------------------------------ record

    def record(self, found: list[dict]) -> None:
        """Write each firing once; an alert removed or re-armed meanwhile records nothing."""
        for event in found:
            with Session(self.engine) as db:
                alert = db.get(LevelAlert, event["alert_id"])
                if alert is None or alert.generation != event["generation"] or alert.state != "active":
                    continue
                db.add(LevelAlertEvent(alert_id=alert.id, generation=alert.generation, level=event["level"], price=event["price"],
                                       source=event["source"], event_at=_utc(event["event_at"]), bar_time=event["bar_time"],
                                       detected_at=_utc(event["detected_at"])))
                alert.state = "fired"
                alert.fired_at = _utc(event["event_at"])
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()  # another detector or process recorded this firing first
                    continue
                log.info("Level alert %s fired (%s)", alert.id, event["source"])

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            db.exec(update(LevelAlertEvent).where(LevelAlertEvent.delivery == "sending", LevelAlertEvent.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="pending"))
            db.commit()
            due = db.exec(select(LevelAlertEvent.id).where(LevelAlertEvent.delivery == "pending")
                          .where((LevelAlertEvent.next_attempt_at.is_(None)) | (LevelAlertEvent.next_attempt_at <= _utc(now)))
                          .order_by(LevelAlertEvent.detected_at).limit(20)).all()
        for event_id in due:
            self._send(event_id)

    def _send(self, event_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(LevelAlertEvent).where(LevelAlertEvent.id == event_id, LevelAlertEvent.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            event = db.get(LevelAlertEvent, event_id)
            alert = db.get(LevelAlert, event.alert_id)
            if alert is None:
                return
            if now - _epoch(event.detected_at) > EXPIRE_SECONDS:
                event.delivery, event.last_error = "expired", "Not delivered within six hours, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                event.delivery, event.next_attempt_at = "pending", _utc(now + UNCONFIGURED_RETRY)
                event.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            title, body = level_alerts.message(
                {"symbol": alert.symbol, "condition": alert.condition, "interval": alert.interval, "direction": alert.direction, "label": alert.label},
                {"level": event.level, "price": event.price, "event_at": _epoch(event.event_at), "source": event.source,
                 "bar_time": event.bar_time, "detected_at": _epoch(event.detected_at)})
            event.attempts += 1
            try:
                ntfy.publish(title, body, path="/charts")
            except ntfy.NtfyError as exc:
                event.delivery = "pending"
                event.next_attempt_at = _utc(now + BACKOFF[min(event.attempts, len(BACKOFF)) - 1])
                event.last_error = str(exc)
                db.commit()
                log.warning("Level alert delivery failed (attempt %d): %s", event.attempts, exc)
                return
            event.delivery, event.delivered_at, event.last_error = "sent", _utc(self.clock()), None
            db.commit()


def alert_rows(db: Session, limit: int = 50) -> list[dict]:
    """Active alerts first, then fired ones newest first, each with its latest firing."""
    alerts = db.exec(select(LevelAlert)).all()
    alerts = sorted(alerts, key=lambda a: (a.state != "active", -(_epoch(a.fired_at) if a.fired_at else _epoch(a.created_at))))[:limit]
    events = {}
    if alerts:
        for event in db.exec(select(LevelAlertEvent).where(LevelAlertEvent.alert_id.in_([a.id for a in alerts]))).all():
            held = events.get(event.alert_id)
            if held is None or event.generation > held.generation:
                events[event.alert_id] = event
    rows = []
    for alert in alerts:
        event = events.get(alert.id)
        if event is not None and event.generation != alert.generation:
            event = None  # an earlier arming's firing
        rows.append({
            "id": str(alert.id), "symbol": alert.symbol, "price": alert.price, "created_on": alert.created_on.isoformat(),
            "condition": alert.condition, "interval": alert.interval, "session": alert.session, "direction": alert.direction,
            "source_kind": alert.source_kind, "source_id": alert.source_id, "label": alert.label, "state": alert.state,
            "armed_at": int(_epoch(alert.armed_at)),
            "event": None if event is None else {
                "level": event.level, "price": event.price, "source": event.source, "event_at": int(_epoch(event.event_at)),
                "detected_at": int(_epoch(event.detected_at)), "delivery": event.delivery, "attempts": event.attempts,
                "delivered_at": int(_epoch(event.delivered_at)) if event.delivered_at else None, "error": event.last_error,
            },
        })
    return rows


def create_alert(db: Session, *, symbol: str, price: float, reference: float, condition: str, interval: str | None,
                 session: str, source_kind: str, source_id: str | None, label: str, now: float) -> LevelAlert:
    """Validate and save one alert. Raises ValueError with what the user should read."""
    way = level_alerts.direction(reference, price)
    if way is None:
        raise ValueError("Price is at this level now, so the alert has no side to wait on.")
    if condition not in level_alerts.CONDITIONS:
        raise ValueError("Choose touches, crosses or closes beyond.")
    if condition == "closes_beyond" and interval not in level_alerts.CLOSE_INTERVALS:
        raise ValueError("Choose a 1-minute to 4-hour candle for a close beyond the level.")
    if session not in level_alerts.SESSIONS:
        raise ValueError("Choose regular or extended hours.")
    active = db.exec(select(LevelAlert).where(LevelAlert.state == "active")).all()
    if len(active) >= level_alerts.MAX_ACTIVE:
        raise ValueError(f"{level_alerts.MAX_ACTIVE} alerts are already active. Remove one first.")
    if symbol not in {a.symbol for a in active} and len({a.symbol for a in active}) >= level_alerts.MAX_SYMBOLS:
        raise ValueError(f"Alerts can watch {level_alerts.MAX_SYMBOLS} symbols at once, to stay within the market-data allowance.")
    interval = interval if condition == "closes_beyond" else None
    today = datetime.fromtimestamp(now, ET).date()
    for other in active:
        if (other.symbol, other.condition, other.interval, other.created_on) == (symbol, condition, interval, today) and abs(other.price - price) < 1e-6:
            raise ValueError("This alert is already set.")
    alert = LevelAlert(symbol=symbol, price=price, created_on=today, condition=condition, interval=interval, session=session,
                       direction=way, source_kind=source_kind, source_id=source_id, label=label[:level_alerts.LABEL_MAX],
                       created_at=_utc(now), armed_at=_utc(now))
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def rearm_alert(db: Session, alert: LevelAlert, *, price: float, reference: float, now: float) -> LevelAlert:
    """Arm a fired alert again at ``price`` (on today's basis), which way ``reference`` says."""
    way = level_alerts.direction(reference, price)
    if way is None:
        raise ValueError("Price is at this level now, so the alert has no side to wait on.")
    alert.price, alert.created_on, alert.direction = price, datetime.fromtimestamp(now, ET).date(), way
    alert.state, alert.generation, alert.armed_at = "active", alert.generation + 1, _utc(now)
    alert.checked_through, alert.fired_at = None, None
    db.commit()
    db.refresh(alert)
    return alert

