"""Daily and weekly chart history: one Tradier series per symbol per New York day.

Daily bars come only from Tradier's daily history, never from minutes (extended
hours would corrupt them). The whole series (start 1970, end yesterday) is read
once per symbol per New York date through the chart feed, so it shares Tradier's
budget and cooldown, and is kept in a small in-memory LRU: adjusted history is
rewritten by the provider after every split, so there is deliberately no disk
copy. Indicators are computed over the whole series (about 10-15 ms for 8,000
bars) and a history page is a slice of that result, so page seams cannot
disagree. The workspace joins a short live tail by date. Both go through the
same C0.6 split basis (`chart_adjust`), applied once.

This module imports the feed lazily: ``ChartFeed`` owns the instance.
"""

from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import threading

from app.engine.chart_adjust import BASIS, adjust_daily, describe, suspect_gaps
from app.engine.chart_math import ET, chart_bars, daily_page, normalize_bars
from app.engine.chart_splits import UNAVAILABLE

PAGE = 1200
CAP = 8  # symbols kept; about 3 MB of adjusted bars each
SERIES_START = "1970-01-01"
TAIL_DAYS = 10
INTERVALS = ("1D", "1W")


@dataclass
class DailyEntry:
    day: date
    basis: str
    info: dict
    bars: list[dict]  # adjusted, completed days only (through yesterday)
    states: dict[str, str] = field(default_factory=dict)


def basis_key(info: dict) -> str:
    """What the stored bars were adjusted with: a new split set means a new entry."""
    return f"{BASIS}|" + ",".join(f"{s['ex_date']}:{s['ratio']}" for s in info["splits"])


def history_rows(payload: dict) -> list[dict]:
    """Rows of a daily history response. A missing or oddly shaped container is malformed;
    Tradier's `{"history": null}` is a symbol with no bars."""
    from app.engine.chart_feed import ChartFeedError

    if not isinstance(payload, dict) or "history" not in payload:
        raise ChartFeedError("Tradier returned an unexpected daily history response.")
    section = payload["history"]
    if section is None:
        return []
    days = section.get("day") if isinstance(section, dict) else None
    if isinstance(days, dict):
        return [days]
    if not isinstance(days, list):
        raise ChartFeedError("Tradier returned an unexpected daily history response.")
    return [row for row in days if isinstance(row, dict)]


class ChartDaily:
    def __init__(self, feed):
        self.feed = feed
        self._lock = threading.RLock()  # coalesces a symbol's simultaneous first reads
        self._entries: OrderedDict[str, DailyEntry] = OrderedDict()

    def tail_params(self, symbol: str, today: date) -> dict:
        return {"symbol": symbol, "interval": "daily", "start": (today - timedelta(days=TAIL_DAYS)).isoformat(), "end": today.isoformat()}

    def entry(self, symbol: str, today: date, info: dict) -> DailyEntry:
        """The completed series for ``today``'s New York date, fetched at most once per date and basis."""
        from app.engine.chart_feed import ChartFeedError

        basis = basis_key(info)
        with self._lock:
            saved = self._entries.get(symbol)
            if saved and saved.day == today and saved.basis == basis:
                self._entries.move_to_end(symbol)
                return saved
            data, _, _ = self.feed.read("/v1/markets/history", {
                "symbol": symbol, "interval": "daily", "start": SERIES_START,
                "end": (today - timedelta(days=1)).isoformat(),
            }, 0, keep=False)
            rows = history_rows(data)
            bars = normalize_bars(rows, daily=True)
            if rows and not bars:
                raise ChartFeedError("Tradier returned unusable daily history.")
            bars, states = adjust_daily(bars, info["splits"])
            made = DailyEntry(today, basis, info, bars, states)
            if bars:  # a symbol with no bars is retried, not remembered
                self._entries[symbol] = made
                self._entries.move_to_end(symbol)
                while len(self._entries) > CAP:
                    self._entries.popitem(last=False)
            return made

    def assemble(self, entry: DailyEntry, tail: list[dict]) -> tuple[list[dict], dict[str, str]]:
        """The completed series joined to a fresh tail by date; the tail wins wherever it overlaps.

        The tail is adjusted by the same function as the series. Returns the
        merged adjusted daily bars and each split's check state.
        """
        tail, tail_states = adjust_daily(tail, entry.info["splits"])
        if not tail:
            return entry.bars, entry.states
        base = entry.bars[:bisect_left(entry.bars, tail[0]["time"], key=lambda bar: bar["time"])]
        return base + tail, {**entry.states, **tail_states}

    def page(self, symbol: str, interval: str, before: int, limit: int = PAGE, today: date | None = None) -> dict:
        """One page of older daily or weekly bars. Raises ``ChartFeedError`` when Tradier cannot answer."""
        today = today or datetime.now(ET).date()
        info = self.feed.splits.get(symbol) if self.feed.splits else UNAVAILABLE
        entry = self.entry(symbol, today, info)
        series = chart_bars([], entry.bars, interval, "regular")
        bars, older, exhausted = daily_page(series, before, limit)
        start = datetime.fromtimestamp(entry.bars[0]["time"], ET).date().isoformat() if entry.bars else None
        return {"symbol": symbol, "interval": interval, "before": before, "limit": limit, "bars": bars,
                "older_cursor": older, "exhausted": exhausted, "continuation": None, "warmup": "ready",
                "source": "tradier", "price_basis": BASIS, "issue": None, "history_start": start,
                "adjustment": describe(entry.info, daily=entry.states, suspects=suspect_gaps(bars))}
