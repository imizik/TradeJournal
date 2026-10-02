"""Bounded, shared Tradier reads for the private chart workspace.

This is polling, not a tick stream. Historical and forming bars stay in a
separate memory cache; nothing is written into the enrichment caches or fills.
"""

from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, time as wall_time
import math
import threading
import time

import httpx

from app.engine import tradier
from app.engine.chart_adjust import describe, suspect_gaps
from app.engine.chart_math import ET, chart_bars, market_day, normalize_bars
from app.engine.chart_splits import UNAVAILABLE, ChartSplits, chart_splits


class ChartFeedError(Exception):
    def __init__(self, message: str, code: str = "provider_unavailable"):
        super().__init__(message)
        self.code = code


@dataclass
class CachedRead:
    data: dict
    fetched_at: float
    expires_at: float


class ChartFeed:
    def __init__(self, splits: ChartSplits | None = None):
        from app.engine.chart_daily import ChartDaily  # imported here: chart_daily needs this module's errors

        self.splits = splits  # None: no split data, disclosed on every response
        self.daily = ChartDaily(self)
        self._lock = threading.RLock()
        self._cache: OrderedDict[tuple, CachedRead] = OrderedDict()
        self._calls: deque[float] = deque()
        self._retry_at = 0.0

    def read(self, path: str, params: dict, ttl: int, keep: bool = True) -> tuple[dict, float, str | None]:
        """One budgeted Tradier GET. ``keep=False`` skips the response cache (and its stale fallback):
        for a large answer the caller stores itself, so it is not held twice."""
        if not tradier.tradier_configured():
            raise ChartFeedError("Connect your Tradier account to load charts. Set TRADIER_API_KEY on the private backend.", "not_configured")
        key = (tradier.TRADIER_BASE_URL, path, tuple(sorted(params.items())))
        # The lock also coalesces concurrent requests from several tabs/panels.
        with self._lock:
            now = time.time()
            saved = self._cache.get(key) if keep else None
            if saved:
                self._cache.move_to_end(key)
                if now < saved.expires_at:
                    return saved.data, saved.fetched_at, None
            while self._calls and self._calls[0] <= now - 60:
                self._calls.popleft()
            try:
                if now < self._retry_at or len(self._calls) >= 60:
                    raise ChartFeedError("Chart requests are cooling down to stay within the data allowance.", "rate_limited")
                self._calls.append(now)
                response = httpx.get(
                    f"{tradier.TRADIER_BASE_URL}{path}", params=params,
                    headers={"Authorization": f"Bearer {tradier.TRADIER_API_KEY}", "Accept": "application/json"},
                    timeout=10,
                )
                if response.status_code == 429:
                    self._retry_at = now + 60
                    raise ChartFeedError("Tradier's data allowance is temporarily exhausted. Retrying in one minute.", "rate_limited")
                if response.status_code in (401, 403):
                    self._retry_at = now + 60
                    raise ChartFeedError("Tradier refused market data. Check the token and account data access.", "access_denied")
                if response.status_code >= 400:
                    raise ChartFeedError("Tradier could not load these charts. Please retry shortly.")
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("fault") or payload.get("errors"):
                    raise ChartFeedError("Tradier returned an unexpected market-data response.")
                fresh = CachedRead(payload, time.time(), now + ttl)
                if not keep:
                    return fresh.data, fresh.fetched_at, None
                self._cache[key] = fresh
                self._cache.move_to_end(key)
                while len(self._cache) > 96:
                    self._cache.popitem(last=False)
                return fresh.data, fresh.fetched_at, None
            except (httpx.HTTPError, ValueError, ChartFeedError) as exc:
                error = exc if isinstance(exc, ChartFeedError) else ChartFeedError("The chart data connection is unavailable. Retrying shortly.")
                # Failure cache prevents repeated misses during an outage; old
                # data is explicitly marked, never silently represented as live.
                if error.code != "rate_limited":
                    self._retry_at = max(self._retry_at, now + 15)
                if saved:
                    return saved.data, saved.fetched_at, str(error)
                raise error from None

    def workspace(self, symbol: str, intervals: list[str], watchlist: list[str], session: str, calendar=None, quotes: bool = True) -> dict:
        """One symbol's panels, plus batched quotes unless ``quotes`` is off (a
        panel holding its own symbol needs only candles)."""
        now = datetime.now(ET)
        today = now.date()
        problems = []
        fetched = {}
        # Unavailable calendar data falls back to clock hours, disclosed in `market`.
        hours = calendar.hours(today) if calendar is not None else None

        def read(name, path, params, ttl):
            try:
                data, stamp, issue = self.read(path, params, ttl)
                fetched[name] = stamp
                if issue:
                    problems.append(issue)
                return data
            except ChartFeedError as exc:
                if exc.code == "not_configured":
                    raise
                problems.append(str(exc))
                return {}

        needs_intraday = any(i not in ("1D", "1W") for i in intervals)
        needs_daily = any(i in ("1D", "1W") for i in intervals)
        minutes = []
        daily = []
        # Tradier refuses a start in the future (HTTP 400), and that failure would
        # cool every chart read down, quotes and daily bars included. Before 04:00
        # New York today has no bars yet: intraday panels come back empty and open
        # on the latest completed SIP sessions instead.
        if needs_intraday and now > datetime.combine(today, wall_time(4), ET):
            current = read("intraday", "/v1/markets/timesales", {
                "symbol": symbol, "interval": "1min", "session_filter": "all",
                "start": today.strftime("%Y-%m-%d 04:00"),
                # Stable request key; the provider returns only existing bars.
                "end": today.strftime("%Y-%m-%d 20:00"),
            }, 15)
            minutes = normalize_bars(_rows(current, "series", "data"))
        # Split data comes from its own provider read, outside the Tradier lock and budget.
        info = self.splits.get(symbol) if self.splits else UNAVAILABLE
        daily_states: dict[str, str] = {}
        if needs_daily:
            # Whole history once per New York date (C0.7), joined to a short tail read every minute.
            tail = normalize_bars(_rows(read("daily", "/v1/markets/history", self.daily.tail_params(symbol, today), 60), "history", "day"), daily=True)
            try:
                daily, daily_states = self.daily.assemble(self.daily.entry(symbol, today, info), tail)
            except ChartFeedError as exc:
                if exc.code == "not_configured":
                    raise
                # No older bars means no honest daily chart: the tail alone would pass for the whole history.
                problems.append(str(exc))

        quote_data = read("quotes", "/v1/markets/quotes", {"symbols": ",".join(sorted(set([symbol, *watchlist])))}, 15) if quotes else {}
        rows = []
        for q in _rows(quote_data, "quotes", "quote"):
            rows.append({
                "symbol": str(q.get("symbol", "")), "name": str(q.get("description") or q.get("symbol") or ""),
                "last": _number(q.get("last")), "change": _number(q.get("change")),
                "change_percentage": _number(q.get("change_percentage")),
                "volume": _number(q.get("volume")), "previous_close": _number(q.get("prevclose")),
                "trade_time": _number(q.get("trade_date"), divisor=1000),
            })

        panels = {}
        for interval in intervals:
            bars = chart_bars(minutes, daily, interval, session, {today: hours})
            panels[interval] = {"bars": bars[-1200:], "markers": []}
        if not any(p["bars"] for p in panels.values()) and problems:
            raise ChartFeedError(problems[0])
        # Today's Tradier minutes are on the post-split basis already: a split is
        # effective from its ex-date, and only splits up to today are applied.
        adjustment = describe(info, daily=daily_states, suspects=suspect_gaps(daily) if needs_daily else [])
        return {
            "symbol": symbol, "provider": "Tradier", "session": session,
            "delayed": "sandbox" in tradier.TRADIER_BASE_URL,
            "refresh_seconds": 15, "checked_at": int(time.time()), "fetched_at": fetched,
            "panels": panels, "quotes": rows, "issues": list(dict.fromkeys(problems)),
            "intraday_as_of": minutes[-1]["time"] if minutes else None, "market": market_day(today, hours),
            "adjustment": adjustment,
            "history_note": "Completed intraday sessions load on scroll from cached Alpaca SIP bars (from 2016); today uses Tradier. Daily and weekly charts scroll back through Tradier's whole daily history, read once per day and kept in memory. Prices are split-adjusted from recorded splits, as of each split's ex-date; the stored bars stay raw. Dividends are not adjusted.",
        }


def _rows(data, container, key) -> list[dict]:
    section = data.get(container)
    value = section.get(key) if isinstance(section, dict) else None
    if isinstance(value, dict):
        return [value]
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _number(value, divisor=1):
    try:
        result = float(value) / divisor
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


chart_feed = ChartFeed(splits=chart_splits)
