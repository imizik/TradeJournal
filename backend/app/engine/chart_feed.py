"""Bounded, shared Tradier reads for the private chart workspace.

This is polling, not a tick stream. Historical and forming bars stay in a
separate memory cache; nothing is written into the enrichment caches or fills.
"""

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as wall_time, timedelta
import math
import threading
import time

import httpx

from app.engine import chart_levels, chart_rvol, tradier
from app.engine.chart_adjust import adjust_minutes, describe, factor_before, suspect_gaps
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

    def workspace(self, symbol: str, intervals: list[str], watchlist: list[str], session: str, calendar=None, quotes: bool = True,
                  stored_session: Callable[[str, date], list[dict] | None] | None = None,
                  volume_profile: Callable[[str, date], chart_rvol.Profile | None] | None = None,
                  extra_levels: Callable[[str, float | None], tuple[list[chart_levels.Level], dict]] | None = None,
                  range_levels: Callable[[str, float | None], tuple[list[chart_levels.Level], dict]] | None = None,
                  auto: bool = True) -> dict:
        """One symbol's panels, plus batched quotes unless ``quotes`` is off (a
        panel holding its own symbol needs only candles).

        With ``stored_session`` (a completed session's raw minutes from disk, or
        None) the response also carries the automatic levels (C2.1–C2.3). They
        cost no provider request beyond the daily bars a daily panel reads anyway.
        With ``volume_profile`` (a stored session's RVol profile, or None) each
        intraday candle of today carries its relative volume (C2.4), from disk only.
        With ``extra_levels`` (more levels for the symbol at its latest price, and what
        to say about them: the options layer, C4.4) those join the automatic levels
        before they merge into zones; ``range_levels`` (the expected-move bands, C2.7) join
        the same way. ``auto=False`` leaves the automatic ones out.
        """
        now = datetime.now(ET)
        today = now.date()
        problems = []
        fetched = {}
        # Unavailable calendar data falls back to clock hours, disclosed in `market`.
        hours = calendar.hours(today) if calendar is not None else None

        def read(name, path, params, ttl, quiet=False):
            try:
                data, stamp, issue = self.read(path, params, ttl)
                fetched[name] = stamp
                if issue and not quiet:
                    problems.append(issue)
                return data
            except ChartFeedError as exc:
                if exc.code == "not_configured":
                    raise
                if not quiet:
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
        if needs_daily or stored_session:
            # Read for the levels alone, a failure is theirs to report, not the charts'.
            quiet = not needs_daily
            # Whole history once per New York date (C0.7), joined to a short tail read every minute.
            tail = normalize_bars(_rows(read("daily", "/v1/markets/history", self.daily.tail_params(symbol, today), 60, quiet), "history", "day"), daily=True)
            try:
                daily, daily_states = self.daily.assemble(self.daily.entry(symbol, today, info), tail)
            except ChartFeedError as exc:
                if exc.code == "not_configured":
                    raise
                # No older bars means no honest daily chart: the tail alone would pass for the whole history.
                if not quiet:
                    problems.append(str(exc))

        quote_data = read("quotes", "/v1/markets/quotes", {"symbols": ",".join(sorted(set([symbol, *watchlist])))}, 15) if quotes else {}
        rows = []
        for q in _rows(quote_data, "quotes", "quote"):
            rows.append({
                "symbol": str(q.get("symbol", "")), "name": str(q.get("description") or q.get("symbol") or ""),
                "last": _number(q.get("last")), "change": _number(q.get("change")),
                "change_percentage": _number(q.get("change_percentage")),
                "volume": _number(q.get("volume")), "previous_close": _number(q.get("prevclose")),
                # Tradier's `close` is the current regular-session close. It is
                # often null before/while RTH is open; never infer it from last.
                "regular_close": _number(q.get("close")),
                "trade_time": _number(q.get("trade_date"), divisor=1000),
            })

        rvol, average = self._rvol(symbol, today, hours, info, calendar, volume_profile) if volume_profile else (None, None)
        # The newest minute's start ends a candle still forming.
        newest = datetime.fromtimestamp(minutes[-1]["time"], ET) if minutes else None
        last_minute = newest.hour * 60 + newest.minute if newest else None
        panels = {}
        for interval in intervals:
            bars = chart_bars(minutes, daily, interval, session, {today: hours})
            if rvol is not None and interval not in ("1D", "1W"):
                # Before the 1,200-candle cut, so the count starts at the session's first candle.
                values = chart_rvol.candle_rvol(bars, average, today, last_minute) if average else [None] * len(bars)
                bars = [{**bar, "rvol": value} for bar, value in zip(bars, values)]
            panels[interval] = {"bars": bars[-1200:], "markers": []}
        if not any(p["bars"] for p in panels.values()) and problems:
            raise ChartFeedError(problems[0])
        # Today's Tradier minutes are on the post-split basis already: a split is
        # effective from its ex-date, and only splits up to today are applied.
        adjustment = describe(info, daily=daily_states if needs_daily else {}, suspects=suspect_gaps(daily) if needs_daily else [])
        data = {
            "symbol": symbol, "provider": "Tradier", "session": session,
            "delayed": "sandbox" in tradier.TRADIER_BASE_URL,
            "refresh_seconds": 15, "checked_at": int(time.time()), "fetched_at": fetched,
            "panels": panels, "quotes": rows, "issues": list(dict.fromkeys(problems)),
            "intraday_as_of": minutes[-1]["time"] if minutes else None, "market": market_day(today, hours),
            "adjustment": adjustment,
            "history_note": "Completed intraday sessions load on scroll from cached Alpaca SIP bars (from 2016); today uses Tradier. Daily and weekly charts scroll back through Tradier's whole daily history, read once per day and kept in memory. Prices are split-adjusted from recorded splits, as of each split's ex-date; the stored bars stay raw. Dividends are not adjusted.",
        }
        if stored_session:
            data["auto_levels"] = self._levels(symbol, today, minutes, daily, info, calendar, stored_session, panels, extra_levels, auto,
                                             range_levels, session=session)
        if volume_profile:
            data["rvol"] = rvol
        return data

    @staticmethod
    def _rvol(symbol, today, hours, info, calendar, volume_profile) -> tuple[dict | None, chart_rvol.Profile | None]:
        """Today's time-of-day volume baseline (C2.4) from the stored sessions before it, on
        today's price basis. None on a day with no session; otherwise what the chart says about
        it, with the baseline only when it is ready."""
        def state(name: str, message: str | None, days=(), traded=(), missing=()) -> dict:
            return {"state": name, "day": today.isoformat(), "sessions": [d.isoformat() for d in days],
                    "traded": len(traded), "missing": [d.isoformat() for d in missing], "message": message}

        if hours is not None and hours["status"] != "open":
            return None, None
        days = chart_rvol.window(today, calendar.hours) if hours is not None else None
        if days is None:
            return state("unavailable", "The market calendar is unavailable, so the 20 sessions before today cannot be chosen."), None
        if hours["open"] != chart_rvol.OPEN:
            return state("unavailable", "Today's regular session does not open at 9:30, so its minutes cannot be compared.", days), None
        profiles, missing = [], []
        for day in days:
            profile = volume_profile(symbol, day)
            if profile is None:
                missing.append(day)
                continue
            # Raw stored volume, multiplied by every split from that session up to today.
            factor = factor_before(info["splits"], day)
            profiles.append((day, profile if factor == 1.0 else tuple(None if v is None else v * factor for v in profile)))
        if missing:
            return state("building", f"RVol needs the 20 sessions before today; {len(missing)} not stored yet. Watchlist names are stored each "
                         "morning before the open, and any symbol's sessions as its older candles load.", days, missing=missing), None
        found = chart_rvol.baseline(profiles)
        if len(found.traded) < chart_rvol.MIN_SESSIONS:
            return state("insufficient", f"Only {len(found.traded)} of the 20 sessions before today traded in regular hours; RVol needs "
                         f"{chart_rvol.MIN_SESSIONS}.", days, found.traded), None
        return state("ready", None, days, found.traded), found.average

    def _levels(self, symbol, today, minutes, daily, info, calendar, stored_session, panels, extra_levels=None, auto=True,
                range_levels=None, session="extended") -> dict:
        """Automatic levels for the session in progress (or the next one), with any extra
        ones, merged into zones, and each intraday panel's interactions with them on its
        closed bars today."""
        now = int(time.time())
        # Validate the full daily lookback, including holidays inside pivot/ATR windows.
        oldest = datetime.fromtimestamp(daily[-(chart_levels.DAILY_TAIL + 1)]["time"], ET).date() if len(daily) > chart_levels.DAILY_TAIL else \
            datetime.fromtimestamp(daily[0]["time"], ET).date() if daily else today
        # Sparse/delisted history must not turn one chart read into years of
        # calendar requests. 150 days covers the ordinary 72-session tail.
        first = max(min(oldest, today - timedelta(days=21)), today - timedelta(days=150))
        known = {d: calendar.hours(d) if calendar is not None else None
                 for d in (first + timedelta(days=i) for i in range((today - first).days + 11))}
        day = chart_levels.session_day(today, known)
        previous = chart_levels.previous_session(day, known)
        stored = stored_session(symbol, previous) if previous else None
        # The previous session from the history cache, on the same basis as today's Tradier minutes.
        before = adjust_minutes(stored, previous, info["splits"]) if stored else []
        found = chart_levels.compute_levels(day, before + (minutes if day == today else []), daily, now, known)
        band = chart_levels.BAND_ATR * found.atr if found.atr is not None else None
        # The latest price: today's newest minute, else the last daily close.
        spot = minutes[-1]["close"] if minutes else daily[-1]["close"] if daily else None
        extra, about = extra_levels(symbol, spot) if extra_levels else ([], None)
        # The expected move (C2.7) is priced around a live price only: today's newest minute, never a daily close.
        live = minutes[-1]["close"] if minutes and datetime.fromtimestamp(minutes[-1]["time"], ET).date() == today \
            and 0 <= now - minutes[-1]["time"] <= 120 else None
        bands, ranges = range_levels(symbol, live) if range_levels else ([], None)
        zones = chart_levels.confluence([*(found.levels if auto else ()), *extra, *bands], band)
        missing = dict(found.missing) if auto else {}
        if band is None:
            missing["confluence"] = "No daily ATR yet, so nearby levels are not merged and interactions are not read."
        for interval, panel in panels.items():
            if interval in ("1D", "1W") or band is None:
                continue
            bars = [b for b in panel["bars"] if b["end_time"] <= now and datetime.fromtimestamp(b["time"], ET).date() == day]
            events = {}
            for zone in zones:
                start = chart_levels.zone_start(zone)
                events[zone.id] = {"state": "developing", "events": [], "at_level": False} if start is None \
                    else chart_levels.interactions(zone.low, zone.high, band, bars, start)
            panel["level_events"] = events
        return {"day": day.isoformat(), "as_of": now, "atr": found.atr, "band": band, "session": session, "missing": missing, "auto": auto,
                **({"options": about} if extra_levels else {}), **({"ranges": ranges} if range_levels else {}),
                "zones": [{"id": z.id, "low": z.low, "high": z.high, "label": z.label, "score": z.score,
                           "members": [asdict(m) for m in z.members]} for z in zones]}


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
