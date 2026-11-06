"""Opt-in SPY/QQQ morning first-pullback alerts, using the shared chart minute feed."""
import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
import os
import time

from sqlmodel import Session

from app.engine import notification_policy, phone, tradier
from app.engine.chart_feed import ChartFeedError
from app.engine.chart_math import ET, normalize_bars
from app.engine.level_alerts import LATENESS

log = logging.getLogger(__name__)
SYMBOLS = ("SPY", "QQQ")


def enabled():
    return (os.getenv("FIRST_PULLBACK_ALERTS_ENABLED", "").lower() == "true"
            and os.getenv("TJ_DOT_TRIAL_ENABLED") != "true"
            and "sandbox" not in tradier.TRADIER_BASE_URL)


@dataclass(frozen=True)
class Trigger:
    side: int
    end: int
    close: Decimal
    stop: Decimal

    @property
    def target(self):
        return self.close + Decimal("1.5") * (self.close - self.stop)


def first_trigger(bars, opened, cutoff):
    """Evaluate only the first arm and first pullback. Return even an old trigger so it cannot rearm."""
    side = 0
    pullback = []
    five = []
    total = volume = Decimal(0)
    previous = None
    for index, bar in enumerate(b for b in bars if opened <= b["time"] < cutoff):
        if bar["time"] != opened + index * 60:
            return None
        high, low, close, size = (Decimal(str(bar[k])) for k in ("high", "low", "close", "volume"))
        total += (high + low + close) / 3 * size
        volume += size
        vwap = total / volume if volume else None
        if (index + 1) % 5 == 0:
            five.append((close, vwap))
            trend = 0
            if len(five) >= 3:
                a, b, c = five[-3:]
                for direction in (1, -1):
                    if (direction * (b[0] - a[0]) > 0 and direction * (c[0] - b[0]) > 0
                            and all(v is not None and direction * (p - v) > 0 for p, v in (a, b, c))):
                        trend = direction
            if not side:
                side = trend
                previous = high, low, close
                continue
            if trend != side:
                return None

        if side:
            extreme = low if side == 1 else high
            if vwap is None or side * (extreme - vwap) <= 0:
                return None
            prior_high, prior_low, prior_close = previous
            if pullback and side * (close - (prior_high if side == 1 else prior_low)) > 0:
                stop = min(pullback) if side == 1 else max(pullback)
                return Trigger(side, bar["end_time"], close, stop) if side * (extreme - stop) > 0 else None
            if side * (close - prior_close) < 0 and len(pullback) < 3:
                pullback.append(extreme)
            elif pullback:
                return None
        previous = high, low, close
    return None


class FirstPullbackAlerts:
    def __init__(self, engine, feed, calendar, clock=time.time):
        self.engine, self.feed, self.calendar, self.clock = engine, feed, calendar, clock
        self.checked = {}

    async def watch(self):
        # Independent of slower monitor sweeps. Recheck a too-early shared cache entry after its 15s TTL.
        while True:
            try:
                await asyncio.to_thread(self.run)
            except Exception:
                log.exception("First-pullback alert pass failed")
            await asyncio.sleep(15 - (self.clock() - 1) % 15)

    def run(self):
        now = self.clock()
        moment = datetime.fromtimestamp(now, ET)
        day = moment.date()
        opened = int(moment.replace(hour=9, minute=30, second=0, microsecond=0).timestamp())
        cutoff = int(now // 60) * 60
        if (day.weekday() >= 5 or not opened + 17 * 60 <= cutoff < opened + 90 * 60
                or now - cutoff < LATENESS or not phone.configured()):
            return
        hours = self.calendar.hours(day)
        if not hours or hours["status"] != "open" or hours["open"] != 570 or hours["close"] <= 675:
            return
        for symbol in SYMBOLS:
            if self.checked.get(symbol) == cutoff:
                continue
            try:
                data, fetched, issue = self.feed.read("/v1/markets/timesales", {
                    "symbol": symbol, "interval": "1min", "session_filter": "all",
                    "start": f"{day} 04:00", "end": f"{day} 20:00",
                }, 15)
            except ChartFeedError:
                continue
            if issue or not cutoff + LATENESS <= fetched <= self.clock() < cutoff + 60:
                continue
            series = (data or {}).get("series")
            rows = series.get("data") if isinstance(series, dict) else None
            if not isinstance(rows, list):
                continue
            bars = normalize_bars(rows)
            if not any(b["end_time"] == cutoff for b in bars):
                continue
            self.checked[symbol] = cutoff
            signal = first_trigger(bars, opened, cutoff)
            if signal is None or signal.end != cutoff:
                continue
            # A forming minute cannot confirm a signal, but can already invalidate its levels.
            forming = next((b for b in bars if b["time"] == cutoff), None)
            if forming and (forming["low"] <= min(signal.stop, signal.target)
                            or forming["high"] >= max(signal.stop, signal.target)):
                continue
            try:
                self.notify(symbol, day, signal)
            except phone.SendError:
                log.warning("First-pullback delivery unconfirmed for %s on %s", symbol, day)

    def notify(self, symbol, day, signal):
        side = "CALL" if signal.side == 1 else "PUT"
        title = f"{symbol} first pullback · {side}"
        clock = datetime.fromtimestamp(signal.end, ET)
        body = (f"{clock:%H:%M} ET confirmation. ETF reference ${signal.close:.2f} (candle close).\n"
                f"ETF stop ${signal.stop:.2f} · 1.5R target ${signal.target:.2f}.\n"
                "Time exit: 15 minutes from entry.")
        with Session(self.engine) as db:
            ticket = notification_policy.decide(db, sender="first_pullback", source_id=f"{day}:{symbol}",
                                                kind="first_pullback", symbol=symbol, title=title, body=body,
                                                now=self.clock(), new_only=True)
            if ticket.held or ticket.id is None or self.clock() >= signal.end + 60:
                return
            phone.send(title, body + ticket.append, kind="first_pullback", path=f"/charts?symbol={symbol}")
            notification_policy.delivered(db, ticket, self.clock())
            db.commit()
