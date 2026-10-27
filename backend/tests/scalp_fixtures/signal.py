"""Executable examples of the sealed v1 signal contract, NOT a runtime strategy.

Only tests import this module. Inputs are hand-authored fixtures; there is no
loader, persistence, clock, provider, Factory registration or activation path.
Prices use Decimal so the spec's strict equalities have unambiguous examples.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
D = Decimal
MINUTE = timedelta(minutes=1)


def positive(value):
    return isinstance(value, D) and value.is_finite() and value > 0


def aware(value):
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class Session:
    opened: datetime
    closed: datetime
    calendar_verified: bool = True
    clock_error_ms: int | None = 0
    healthy: bool = True
    halted: bool = False
    stock_feed: str = "fixture_consolidated_raw"
    option_feed: str = "fixture_consolidated_nbbo"

    def at(self, hour, minute):
        return self.opened.astimezone(ET).replace(hour=hour, minute=minute, second=0, microsecond=0)

    def eligible(self):
        return (aware(self.opened) and aware(self.closed)
                and self.calendar_verified and self.healthy and not self.halted
                and self.clock_error_ms is not None and abs(self.clock_error_ms) <= 100
                and self.opened == self.at(9, 30)
                and self.closed.date() == self.opened.date()
                and self.closed > self.at(11, 15)
                and self.stock_feed == "fixture_consolidated_raw"
                and self.option_feed == "fixture_consolidated_nbbo")


@dataclass(frozen=True)
class Bar:
    start: datetime
    received: datetime
    open: D
    high: D
    low: D
    close: D
    volume: D

    @property
    def end(self):
        return self.start + MINUTE

    def valid(self):
        return (all(positive(x) for x in (self.open, self.high, self.low, self.close))
                and self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
                and isinstance(self.volume, D) and self.volume.is_finite() and self.volume >= 0)


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: int
    at: datetime
    stop: D


def trend_side(ends):
    """Each pair is its own five-minute close and endpoint VWAP."""
    if len(ends) < 3 or any(v is None for _, v in ends[-3:]):
        return 0
    a, b, c = ends[-3:]
    for side in (1, -1):
        if (side * (b[0] - a[0]) > 0 and side * (c[0] - b[0]) > 0
                and all(side * (close - vwap) > 0 for close, vwap in (a, b, c))):
            return side
    return 0


@dataclass
class SignalExample:
    session: Session
    symbol: str
    bars: list = field(default_factory=list)
    five_ends: list = field(default_factory=list)
    pullback: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    side: int = 0
    retired: bool = False
    total_volume: D = D(0)
    total_value: D = D(0)

    def retire(self, reason):
        self.retired = True
        self.trace.append(reason)

    def minute(self, bar, decision):
        if self.retired:
            return None
        if self.symbol not in ("SPY", "QQQ") or not self.session.eligible():
            self.retire("ineligible_session")
            return None
        expected_start = self.session.opened + len(self.bars) * MINUTE
        if (bar is None or not aware(decision) or not aware(bar.start) or not aware(bar.received)
                or bar.start != expected_start or decision != expected_start + MINUTE + timedelta(seconds=5)
                or not bar.end <= bar.received <= decision or not bar.valid()):
            # Keep already-decided observations immutable, including on a revision.
            self.retire("invalid_or_missing_minute")
            return None
        previous = self.bars[-1] if self.bars else None
        self.bars.append(bar)
        self.total_volume += bar.volume
        self.total_value += (bar.high + bar.low + bar.close) / 3 * bar.volume
        vwap = self.total_value / self.total_volume if self.total_volume else None
        boundary = len(self.bars) % 5 == 0
        if boundary:
            self.five_ends.append((bar.close, vwap))
        if bar.end >= self.session.at(11, 0):
            self.retire("window_closed")
            return None
        if not self.side:
            if boundary and bar.end >= self.session.at(9, 45):
                self.side = trend_side(self.five_ends)
                if self.side:
                    self.trace.append("armed")
            return None  # An arm's minute can never be its pullback.
        if boundary and trend_side(self.five_ends) != self.side:
            self.retire("trend_failed")
            return None
        extreme = bar.low if self.side == 1 else bar.high
        if vwap is None or self.side * (extreme - vwap) <= 0:
            self.retire("vwap_failed")
            return None
        adverse = self.side * (bar.close - previous.close) < 0
        if not self.pullback:
            if adverse:
                self.pullback.append(bar)
                self.trace.append("pullback")
            return None
        prior_extreme = previous.high if self.side == 1 else previous.low
        if self.side * (bar.close - prior_extreme) > 0:
            stop = (min(b.low for b in self.pullback) if self.side == 1
                    else max(b.high for b in self.pullback))
            self.retire("trigger_invalidated" if self.side * (extreme - stop) <= 0 else "trigger")
            return Signal(self.symbol, self.side, decision, stop) if self.trace[-1] == "trigger" else None
        if adverse and len(self.pullback) < 3:
            self.pullback.append(bar)
        else:
            self.retire("pullback_failed")
        return None
