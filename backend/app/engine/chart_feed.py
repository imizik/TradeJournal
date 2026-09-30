"""Bounded, shared Tradier reads for the private chart workspace.

This is polling, not a tick stream. Historical and forming bars stay in a
separate memory cache; nothing is written into the enrichment caches or fills.
"""

from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import threading
import time

import httpx

from app.engine import tradier
from app.engine.chart_math import ET, chart_bars, market_day, normalize_bars


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
    def __init__(self):
        self._lock = threading.RLock()
        self._cache: OrderedDict[tuple, CachedRead] = OrderedDict()
        self._calls: deque[float] = deque()
        self._retry_at = 0.0

    def read(self, path: str, params: dict, ttl: int) -> tuple[dict, float, str | None]:
        if not tradier.tradier_configured():
            raise ChartFeedError("Connect your Tradier account to load charts. Set TRADIER_API_KEY on the private backend.", "not_configured")
        key = (tradier.TRADIER_BASE_URL, path, tuple(sorted(params.items())))
        # The lock also coalesces concurrent requests from several tabs/panels.
        with self._lock:
            now = time.time()
            saved = self._cache.get(key)
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
                saved = CachedRead(payload, time.time(), now + ttl)
                self._cache[key] = saved
                self._cache.move_to_end(key)
                while len(self._cache) > 96:
                    self._cache.popitem(last=False)
                return saved.data, saved.fetched_at, None
            except (httpx.HTTPError, ValueError, ChartFeedError) as exc:
                error = exc if isinstance(exc, ChartFeedError) else ChartFeedError("The chart data connection is unavailable. Retrying shortly.")
                # Failure cache prevents repeated misses during an outage; old
                # data is explicitly marked, never silently represented as live.
                if error.code != "rate_limited":
                    self._retry_at = max(self._retry_at, now + 15)
                if saved:
                    return saved.data, saved.fetched_at, str(error)
                raise error from None

    def workspace(self, symbol: str, intervals: list[str], watchlist: list[str], session: str, calendar=None) -> dict:
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
        if needs_intraday:
            current = read("intraday", "/v1/markets/timesales", {
                "symbol": symbol, "interval": "1min", "session_filter": "all",
                "start": today.strftime("%Y-%m-%d 04:00"),
                # Stable request key; the provider returns only existing bars.
                "end": today.strftime("%Y-%m-%d 20:00"),
            }, 15)
            minutes = normalize_bars(_rows(current, "series", "data"))
        if needs_daily:
            history = read("daily", "/v1/markets/history", {
                "symbol": symbol, "interval": "daily",
                "start": (today - timedelta(days=1100)).isoformat(), "end": today.isoformat(),
            }, 60)
            daily = normalize_bars(_rows(history, "history", "day"), daily=True)

        quote_data = read("quotes", "/v1/markets/quotes", {"symbols": ",".join(sorted(set([symbol, *watchlist])))}, 15)
        quotes = []
        for q in _rows(quote_data, "quotes", "quote"):
            quotes.append({
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
        return {
            "symbol": symbol, "provider": "Tradier", "session": session,
            "delayed": "sandbox" in tradier.TRADIER_BASE_URL,
            "refresh_seconds": 15, "checked_at": int(time.time()), "fetched_at": fetched,
            "panels": panels, "quotes": quotes, "issues": list(dict.fromkeys(problems)),
            "intraday_as_of": minutes[-1]["time"] if minutes else None, "market": market_day(today, hours),
            "history_note": "Completed intraday sessions load on scroll from cached Alpaca SIP raw bars (from 2016); today uses Tradier. Intraday prices are unadjusted, so splits can create discontinuities. Daily bars remain Tradier and dividend adjustments are not guaranteed.",
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


chart_feed = ChartFeed()
