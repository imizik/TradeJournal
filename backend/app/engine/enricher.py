"""
Fill enricher: fetches underlying prices from Polygon and computes option greeks
via Black-Scholes. Technical indicators (daily SMA 20/50, EMA 9/20, RSI 14,
MACD, hourly EMA 9) are computed locally from Polygon daily and hourly
aggregates and reproduce Polygon's own indicator endpoints exactly (see
app/engine/indicators.py and tests/test_enricher.py).

Calls per ticker: one daily-aggregates call (refreshed when a fill needs a
later session), one hourly-aggregates page per ~50 sessions of hourly history
needed, and one minute-aggregates call per 60-day window of fill dates. The
previous design made seven indicator calls per ticker plus one minute call per
fill day, and never refreshed a fetched indicator series.

Rate limit: discovered, not configured. Calls run unpaced until Polygon
answers 429, and the number that succeeded in the preceding minute is the
budget -- so a free key finds its 5/min after one refusal and a paid key
(no per-minute limit) never paces at all. POLYGON_CALLS_PER_MINUTE is a
ceiling for pinning the rate lower on purpose.

Cache: raw Polygon responses are saved to backend/data/polygon_cache/ so a
backfill can be interrupted and resumed without re-fetching. Daily/hourly bar
caches record the window they cover and are refreshed once a fill needs a
later session, so indicators no longer go stale.
"""

import json
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from scipy.optimize import brentq
from scipy.stats import norm
from sqlmodel import Session

from app.engine.api_wait import observed_sleep
from app.engine.indicators import polygon_bar_et_date, polygon_daily_indicators, polygon_hourly_ema
from app.models import Fill

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

log = logging.getLogger(__name__)

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "polygon_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RISK_FREE_RATE = float(os.environ.get("RISK_FREE_RATE", "0.0372"))  # override via .env
ET = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

# Polygon's Basic plan serves two years of history; it is also the window
# Polygon's own indicator endpoints were computing over, so using it keeps
# locally computed values on the same footing as the fetched ones.
_DAILY_HISTORY_DAYS = 730
# Calendar days of hourly bars before the earliest fill: ~500 hourly bars, so
# the EMA-9 seed (weight 0.8**n) is long gone by the first fill.
_HOURLY_WARMUP_DAYS = 45
# Calendar days of fill dates per minute-bars call: ~42 sessions x 960 bars
# stays under Polygon's 50,000-base-aggregate page.
_MINUTE_WINDOW_DAYS = 60
_AGGS_PAGE_LIMIT = 50000

_DAILY_INDICATOR_COLUMNS = ("sma_20", "sma_50", "ema_9", "ema_20", "rsi_14", "macd", "macd_signal")


# ---------------------------------------------------------------------------
# Rate limiter: observed, not configured
#
# Polygon Basic (free) allows 5 calls/min; paid Stocks plans have no per-minute
# limit at all. A fixed rate means guessing which one you are on, and the wrong
# guess costs in both directions: guess high on a free key and the budget goes
# to 429s, guess low on a paid key and a one-minute backfill takes half an hour.
# The old default did the second -- 4.5/min, which is ~25 minutes for a week of
# fills across 38 tickers no matter what the key is entitled to.
#
# So the rate is discovered. Calls run unpaced until Polygon refuses one, and a
# refusal carries the answer with it: the number of calls that *succeeded* in
# the preceding minute is the budget. One 429 finds a free key's limit exactly
# -- no halving ladder -- and a paid key never sees one, so it never paces.
# After a quiet period the rate steps back up, so a transient refusal does not
# pin the process slow for the rest of its life.
#
# POLYGON_CALLS_PER_MINUTE still works, but it is now a *ceiling* rather than a
# target: set it only to pin the rate below whatever the plan would allow.
# ---------------------------------------------------------------------------

_LEARN_WINDOW = 60.0            # Polygon's limit is per minute
_MIN_LEARNED_RATE = 1.0         # never pace slower than one call a minute
_BLIND_REFUSAL_RATE = 9.0       # refused with nothing to learn from: halve to 4.5
# Pace just under what was measured. Polygon counts a rolling window, so
# spacing calls at exactly the budget keeps clipping its edge: simulating this
# job at a measured-exactly 5/min took 22 further refusals, each a wasted round
# trip. A few percent of headroom removes all of them.
_PACING_HEADROOM = 1.05
_RECOVERY_QUIET_PERIOD = 300.0  # no refusal for this long: try twice the rate
# Each probe that gets refused doubles the wait before the next one. Without
# this, a plan with a real cap is probed every five minutes forever: the rate
# doubles, overshoots, and buys a 429 -- three of them inside a 12-minute
# simulated run. Backing off converges on "stop asking" while still letting a
# one-off refusal recover quickly.
_RECOVERY_MAX_QUIET = 7200.0


def _configured_ceiling(raw: str | None = None) -> float | None:
    """POLYGON_CALLS_PER_MINUTE as a ceiling, or None to let the rate be
    discovered. Non-positive and unparseable values are ignored."""
    if raw is None:
        raw = os.environ.get("POLYGON_CALLS_PER_MINUTE", "")
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        log.warning("Ignoring POLYGON_CALLS_PER_MINUTE=%r; discovering the rate instead", raw)
        return None
    return value


class _AdaptiveRateLimiter:
    """Paces at the fastest rate Polygon has actually allowed.

    `rate is None` means unpaced. A 429 sets it from what got through; quiet
    time raises it again, never above `ceiling`.
    """

    def __init__(self, ceiling: float | None = None, clock=time.monotonic):
        self.ceiling = ceiling
        self.rate = ceiling
        self._clock = clock
        self._successes: deque[float] = deque()
        self._next_slot = 0.0
        self._last_refusal: float | None = None
        self._recovery_after = _RECOVERY_QUIET_PERIOD
        self._probing = False
        self._lock = threading.Lock()

    # -- state -------------------------------------------------------------

    def _trim(self, now: float) -> None:
        while self._successes and now - self._successes[0] > _LEARN_WINDOW:
            self._successes.popleft()

    def _recover(self, now: float) -> None:
        """Step back up after a quiet period, so one refusal is not permanent."""
        if self.rate is None or self._last_refusal is None:
            return
        if now - self._last_refusal < self._recovery_after:
            return
        self._last_refusal = now
        self._probing = True
        raised = self.rate * 2.0
        if self.ceiling is None:
            self.rate = raised
        elif raised >= self.ceiling:
            self.rate = self.ceiling
            self._last_refusal = None  # back at the ceiling; nothing left to recover
        else:
            self.rate = raised
        log.info("Polygon quiet since last refusal; raising pace to %s calls/min", self.rate)

    # -- the three things callers do ---------------------------------------

    def reserve(self) -> float:
        """Claim the next slot and return how long to wait before using it."""
        with self._lock:
            now = self._clock()
            self._recover(now)
            if self.rate is None:
                self._next_slot = now
                return 0.0
            delay = max(0.0, self._next_slot - now)
            self._next_slot = max(now, self._next_slot) + 60.0 / self.rate
            return delay

    def wait(self) -> None:
        delay = self.reserve()
        if delay > 0:
            observed_sleep("Polygon", "rate_limit", delay)

    def note_success(self) -> None:
        with self._lock:
            now = self._clock()
            self._successes.append(now)
            self._trim(now)

    def note_refusal(self, retry_after: float | None = None) -> float:
        """Learn the budget from a 429; return how long to wait before retrying."""
        with self._lock:
            now = self._clock()
            self._trim(now)
            if self._probing:
                # We raised the rate ourselves and the plan refused it: that is
                # a cap, not a hiccup. Wait longer before asking again.
                self._recovery_after = min(self._recovery_after * 2.0, _RECOVERY_MAX_QUIET)
                self._probing = False
            landed = len(self._successes)
            if landed:
                # `landed` calls got through in the last minute and the next one
                # did not: that is the budget, measured rather than assumed.
                learned = max(float(landed) / _PACING_HEADROOM, _MIN_LEARNED_RATE)
                self.rate = learned if self.rate is None else min(self.rate, learned)
            else:
                # Refused without a single success to measure -- halve blindly.
                current = self.rate if self.rate is not None else _BLIND_REFUSAL_RATE
                self.rate = max(current / 2.0, _MIN_LEARNED_RATE)
            self._last_refusal = now
            if retry_after is not None:
                wait = max(0.0, retry_after)
            elif self._successes:
                # Wait for the oldest call to age out of the window.
                wait = max(0.0, _LEARN_WINDOW - (now - self._successes[0]))
            else:
                wait = _LEARN_WINDOW
            # The caller sleeps `wait` before retrying, so that sleep *is* this
            # call's pacing. Scheduling the next slot any later would stack our
            # delay on top of the provider's own Retry-After and wait twice.
            self._next_slot = now + wait
            return wait


_limiter = _AdaptiveRateLimiter(ceiling=_configured_ceiling())


def polygon_calls_per_minute() -> float | None:
    """The rate currently being paced at, or None while unpaced. Safe to expose
    in status responses; read it per request, it changes as the rate is learned."""
    return _limiter.rate


def _retry_after_seconds(headers) -> float | None:
    """`Retry-After` in seconds, whether sent as a delay or an HTTP date."""
    raw = (headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC_TZ)
    return max(0.0, (when - datetime.now(UTC_TZ)).total_seconds())


# ---------------------------------------------------------------------------
# Polygon HTTP helpers with local cache
# ---------------------------------------------------------------------------

def _cache_key(path: str, params: dict) -> str:
    return path + "_" + "_".join(f"{k}={v}" for k, v in sorted(params.items()))


def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


class PolygonNotEntitled(RuntimeError):
    """Polygon answered 403: the key is invalid, or the plan does not cover the
    requested endpoint or data window. Never a cacheable "no data" result —
    fixing the key or plan must make the next sync fetch again."""


def _polygon_request(url: str, params: dict | None = None) -> dict:
    """One rate-limited GET with retries. Raises PolygonNotEntitled on 403.

    `url` is either an API path's full URL or a Polygon `next_url`, which
    already carries its own query string. httpx replaces rather than merges a
    query string when `params` is passed, so the key is appended by hand.
    """
    query = {**(params or {}), "apiKey": POLYGON_API_KEY}
    full_url = url + ("&" if "?" in url else "?") + urlencode(query)

    for attempt in range(5):
        _limiter.wait()
        try:
            resp = httpx.get(full_url, timeout=30)
        except (httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            # Connection reset (e.g. after computer sleep) — retry with backoff
            wait = 20 * (attempt + 1)
            log.warning("Network error, waiting %ds (attempt %d/5): %s", wait, attempt + 1, e)
            observed_sleep("Polygon", "network_retry", wait)
            continue
        if resp.status_code == 403:
            log.warning("403 from Polygon for %s - API key is not entitled to this endpoint/data window, skipping", url)
            raise PolygonNotEntitled(url)
        if resp.status_code == 429:
            wait = _limiter.note_refusal(_retry_after_seconds(resp.headers))
            log.warning(
                "429 from Polygon — pacing at %s calls/min, waiting %.0fs (attempt %d/5)",
                _limiter.rate, wait, attempt + 1,
            )
            observed_sleep("Polygon", "provider_429", wait)
            continue
        resp.raise_for_status()
        _limiter.note_success()
        return resp.json()

    raise RuntimeError(f"Polygon request failed after 5 retries: {url}")


def _has_results(data: dict) -> bool:
    results = data.get("results")
    return (isinstance(results, list) and len(results) > 0) or (
        isinstance(results, dict) and len(results.get("values", [])) > 0
    )


def _read_cached(cp: Path, empty_ttl: float | None) -> dict | None:
    """Cached response, {} for a still-valid empty marker, None when absent
    or when the empty marker is stale (or the caller disallows empties)."""
    if not cp.exists():
        return None
    data = json.loads(cp.read_text())
    empty_at = data.get("_empty_cached_at")
    if empty_at is None:
        return data
    if empty_ttl is not None and time.time() - float(empty_at) < empty_ttl:
        return {}
    return None


def _polygon_get(path: str, params: dict, empty_ttl: float | None = None) -> dict:
    """GET from Polygon, caching by (path + sorted params). Retries on 429.

    empty_ttl: if set, empty responses are cached as a timestamp marker for
    that many seconds, so permanently data-less requests (delisted tickers,
    days Polygon has no bars for) stop burning the rate-limit budget on every
    sync. If None, empty responses are never cached (recent data may still be
    published later). A 403 raises PolygonNotEntitled and caches nothing.
    """
    cp = _cache_path(_cache_key(path, params))
    cached = _read_cached(cp, empty_ttl)
    if cached is not None:
        return cached

    data = _polygon_request(f"https://api.polygon.io{path}", params)
    if _has_results(data):
        cp.write_text(json.dumps(data))
    elif empty_ttl is not None:
        cp.write_text(json.dumps({"_empty_cached_at": time.time()}))
    return data


# Empty-response cache lifetimes. Finalized history that came back empty will
# never appear (delisted ticker, no coverage there) — cache that for a year.
# Bar-range caches (no bars at all for a ticker) retry weekly.
_EMPTY_TTL_FINAL = 365 * 86400.0
_EMPTY_TTL_SERIES = 7 * 86400.0


def _fetch_aggregates(ticker: str, timespan: str, frm: date, to: date) -> dict:
    """Every page of /v2/aggs for [frm, to]; results merged into one response.

    Polygon's `limit` counts base (minute) aggregates, so an hourly request
    pages at roughly 50 sessions and a minute request at ~52 full sessions.
    """
    path = f"/v2/aggs/ticker/{ticker}/range/1/{timespan}/{frm.isoformat()}/{to.isoformat()}"
    data = _polygon_request(f"https://api.polygon.io{path}", {"adjusted": "true", "sort": "asc", "limit": _AGGS_PAGE_LIMIT})
    results = list(data.get("results") or [])
    next_url = data.get("next_url")
    while next_url:
        more = _polygon_request(next_url)
        results.extend(more.get("results") or [])
        next_url = more.get("next_url")
    data["results"] = results
    data.pop("next_url", None)
    return data


# ---------------------------------------------------------------------------
# Daily / hourly bar caches, one window per (ticker, timespan)
# ---------------------------------------------------------------------------

def _bars_cache_path(ticker: str, timespan: str) -> Path:
    return _cache_path(f"_v2_aggs_bars_{timespan}_{ticker}")


def _load_bars_cache(ticker: str, timespan: str) -> dict | None:
    cp = _bars_cache_path(ticker, timespan)
    if not cp.exists():
        return None
    try:
        entry = json.loads(cp.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(entry, dict) or not {"from", "to", "fetched_at", "results"} <= set(entry):
        return None
    return entry


def _bars_cache_covers(entry: dict, frm: date, to: date, now_et: datetime) -> bool:
    """Does a cached window serve [frm, to]?

    It must start no later than `frm`, and either already hold a bar dated
    on/after `to` or have been requested through `to` on a later ET calendar
    day — by then Polygon has published that session, or it was a holiday
    with nothing to publish. A same-day fetch is never trusted for `to`:
    Basic-plan data is end-of-day, so the fetch may simply have been early.
    """
    if date.fromisoformat(entry["from"]) > frm:
        return False
    fetched_at = datetime.fromtimestamp(float(entry["fetched_at"]), tz=ET)
    results = entry.get("results") or []
    if not results:
        # No bars at all (delisted, index-only symbol, not yet listed): retry
        # weekly, as the old empty-series marker did. A 403 never gets here —
        # it raises before anything is cached.
        return date.fromisoformat(entry["to"]) >= to and (now_et - fetched_at).total_seconds() < _EMPTY_TTL_SERIES
    if date.fromisoformat(polygon_bar_et_date(results[-1])) >= to:
        return True
    return date.fromisoformat(entry["to"]) >= to and fetched_at.date() > to


def fetch_aggregate_bars(ticker: str, timespan: str, frm: date, to: date, fetch_to: date | None = None) -> list[dict]:
    """Daily ('day') or hourly ('hour') bars covering [frm, to], cached per
    (ticker, timespan). A miss fetches [frm, fetch_to or to] and replaces the
    cached window. Raises (and caches nothing) on 403 or network failure."""
    now_et = datetime.now(ET)
    entry = _load_bars_cache(ticker, timespan)
    if entry is not None and _bars_cache_covers(entry, frm, to, now_et):
        return entry["results"]

    request_to = max(to, fetch_to) if fetch_to is not None else to
    log.info("Fetching %s bars for %s %s..%s", timespan, ticker, frm, request_to)
    data = _fetch_aggregates(ticker, timespan, frm, request_to)
    results = data.get("results") or []
    entry = {
        "ticker": ticker,
        "timespan": timespan,
        "from": frm.isoformat(),
        "to": request_to.isoformat(),
        "fetched_at": now_et.timestamp(),
        "results": results,
    }
    _bars_cache_path(ticker, timespan).write_text(json.dumps(entry))
    return results


# ---------------------------------------------------------------------------
# Minute bars, cached per (ticker, day) exactly as before; fetched in windows
# ---------------------------------------------------------------------------

_MINUTE_PARAMS = {"adjusted": "true", "sort": "asc", "limit": 1000}


def _minute_day_path(ticker: str, day: date) -> Path:
    return _cache_path(_cache_key(f"/v2/aggs/ticker/{ticker}/range/1/minute/{day.isoformat()}/{day.isoformat()}", _MINUTE_PARAMS))


def _minute_empty_ttl(day: date, today: date) -> float | None:
    # Sessions more than a few days old are finalized: an empty response there
    # is permanent, so cache the emptiness instead of retrying every sync.
    return _EMPTY_TTL_FINAL if day < today - timedelta(days=3) else None


def _bars_by_minute(results: list[dict]) -> dict[str, dict]:
    bars: dict[str, dict] = {}
    for bar in results:
        dt = datetime.fromtimestamp(bar["t"] / 1000, tz=UTC_TZ).astimezone(ET)
        bars[f"{dt.hour:02d}:{dt.minute:02d}"] = {"close": bar["c"], "vwap": bar.get("vw")}
    return bars


def _date_windows(days: list[date], span_days: int) -> list[list[date]]:
    """Group sorted dates so each window spans fewer than `span_days` days."""
    windows: list[list[date]] = []
    for day in days:
        if windows and (day - windows[-1][0]).days < span_days:
            windows[-1].append(day)
        else:
            windows.append([day])
    return windows


def fetch_minute_bars_for_days(ticker: str, days: Iterable[date]) -> dict[date, dict[str, dict]]:
    """{day -> {HH:MM -> {close, vwap}}} for a ticker on several trading days.

    Cached days are read from the per-day files fetch_minute_bars() always
    used. Missing days are fetched in ~60-day range calls and written back to
    the same per-day files, so a later single-day lookup hits the cache.
    """
    # Polygon's free Stock aggregates are end-of-day recency. Same-day minute
    # bars can 403 until Polygon has finalized/published the session.
    today = datetime.now(ET).date()
    out: dict[date, dict[str, dict]] = {}
    missing: list[date] = []
    for day in sorted(set(days)):
        if day >= today:
            log.info("Skipping Polygon minute bars for %s %s until end-of-day data is available", ticker, day)
            out[day] = {}
            continue
        cached = _read_cached(_minute_day_path(ticker, day), _minute_empty_ttl(day, today))
        if cached is not None:
            out[day] = _bars_by_minute(cached.get("results", []))
        else:
            missing.append(day)

    for window in _date_windows(missing, _MINUTE_WINDOW_DAYS):
        try:
            if len(window) == 1:
                # The same single-day request (and cache file) as before.
                day = window[0]
                data = _polygon_get(
                    f"/v2/aggs/ticker/{ticker}/range/1/minute/{day.isoformat()}/{day.isoformat()}",
                    _MINUTE_PARAMS,
                    empty_ttl=_minute_empty_ttl(day, today),
                )
                out[day] = _bars_by_minute(data.get("results", []))
                continue
            data = _fetch_aggregates(ticker, "minute", window[0], window[-1])
        except Exception as e:
            # Includes PolygonNotEntitled: nothing is cached for these days, so
            # a fixed key or plan fetches them on the next sync.
            log.warning("Failed to fetch bars for %s %s..%s: %s", ticker, window[0], window[-1], e)
            for day in window:
                out.setdefault(day, {})
            continue
        by_day: dict[str, list[dict]] = defaultdict(list)
        for bar in data.get("results") or []:
            by_day[polygon_bar_et_date(bar)].append(bar)
        for day in window:
            day_bars = by_day.get(day.isoformat(), [])
            cp = _minute_day_path(ticker, day)
            if day_bars:
                cp.write_text(json.dumps({
                    "ticker": ticker,
                    "adjusted": True,
                    "resultsCount": len(day_bars),
                    "results": day_bars,
                    "status": "OK",
                    "fetched_range": f"{window[0].isoformat()}_{window[-1].isoformat()}",
                }))
            elif _minute_empty_ttl(day, today) is not None:
                cp.write_text(json.dumps({"_empty_cached_at": time.time()}))
            out[day] = _bars_by_minute(day_bars)
    return out


def fetch_minute_bars(ticker: str, day: date) -> dict[str, dict]:
    """Return {HH:MM -> {close, vwap}} for a ticker on a given trading day."""
    return fetch_minute_bars_for_days(ticker, [day]).get(day, {})


# ---------------------------------------------------------------------------
# Indicator series per ticker, computed from cached bars
# ---------------------------------------------------------------------------

def _daily_indicator_series(ticker: str, days: list[date], daily_from: date, published_through: date) -> dict[str, dict[str, float]]:
    """{indicator -> {date -> value}} covering the last completed session
    before each fill date. Empty on failure; warmup dates are absent."""
    needed_to = min(max(days) - timedelta(days=1), published_through)
    if needed_to < daily_from:
        return {}
    bars = fetch_aggregate_bars(ticker, "day", daily_from, needed_to, fetch_to=published_through)
    series: dict[str, dict[str, float]] = {name: {} for name in _DAILY_INDICATOR_COLUMNS}
    for day_str, row in polygon_daily_indicators(bars).items():
        for name in _DAILY_INDICATOR_COLUMNS:
            value = row.get(name)
            if value is not None:
                series[name][day_str] = value
    return series


def _hourly_ema_series(ticker: str, days: list[date], daily_from: date, published_through: date) -> dict[str, float]:
    """{'YYYY-MM-DD HH' -> EMA-9} over the fills' days plus warmup."""
    frm = max(min(days) - timedelta(days=_HOURLY_WARMUP_DAYS), daily_from)
    to = min(max(days), published_through)
    if to < frm:
        return {}
    return polygon_hourly_ema(fetch_aggregate_bars(ticker, "hour", frm, to), 9)


# ---------------------------------------------------------------------------
# Black-Scholes
# ---------------------------------------------------------------------------

def _bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    if T <= 0:
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_volatility(option_price: float, S: float, K: float, T: float, r: float, option_type: str) -> Optional[float]:
    if T <= 0 or S <= 0 or K <= 0:
        return None
    try:
        iv = brentq(
            lambda sigma: _bs_price(S, K, T, r, sigma, option_type) - option_price,
            1e-6, 20.0, xtol=1e-6, maxiter=200,
        )
        return float(iv)
    except (ValueError, RuntimeError):
        return None


def compute_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> dict:
    if T <= 0 or sigma <= 0 or S <= 0:
        return {}
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1.0
    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * norm.pdf(d1) * math.sqrt(T) / 100.0  # per 1% change in IV
    theta_base = -S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))
    if option_type == "call":
        theta = (theta_base - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365.0
    else:
        theta = (theta_base + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365.0

    return {
        "delta": round(float(delta), 6),
        "gamma": round(float(gamma), 6),
        "theta": round(float(theta), 6),
        "vega": round(float(vega), 6),
    }


def _time_to_expiry(executed_at: datetime, expiration: date) -> float:
    """Years to expiry from fill time."""
    exp_dt = datetime.combine(expiration, datetime.min.time().replace(hour=16))  # 4pm ET
    delta = exp_dt - executed_at.replace(tzinfo=None)
    return max(0.0, delta.total_seconds() / (365.25 * 24 * 3600))


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def _prior_value(series: dict[str, float], day_str: str) -> Optional[float]:
    """Latest series value strictly before ``day_str``.

    Daily indicator values are computed on that day's close, which does not
    exist yet at fill time — using the fill day's own value would leak the
    future into "at fill" fields. The last completed day is the honest value.
    """
    prior = [k for k in series if k < day_str]
    return series[max(prior)] if prior else None


def _find_bar(bars: dict[str, dict], executed_at: datetime) -> Optional[dict]:
    """Find the closest minute bar dict at or before the fill time."""
    for delta_min in range(6):
        t = executed_at - timedelta(minutes=delta_min)
        key = f"{t.hour:02d}:{t.minute:02d}"
        if key in bars:
            return bars[key]
    return None


def enrich_fills(fills: list[Fill], session: Session, on_progress=None) -> int:
    """
    Enrich a list of fills with underlying price, greeks, and technical indicators.
    Writes results directly to DB. Returns count of fills enriched.
    """
    if not POLYGON_API_KEY:
        log.warning("POLYGON_API_KEY not set — skipping enrichment")
        return 0

    # Group fills by ticker: one daily and one hourly bars window per ticker
    # covers every indicator for every fill of that ticker.
    days_by_ticker: dict[str, set[date]] = defaultdict(set)
    for fill in fills:
        if fill.executed_at is not None:
            days_by_ticker[fill.ticker].add(fill.executed_at.date())
    tickers = sorted(days_by_ticker)

    today = datetime.now(ET).date()
    published_through = today - timedelta(days=1)  # Basic-plan data is end-of-day
    daily_from = today - timedelta(days=_DAILY_HISTORY_DAYS)

    log.info("Computing indicator series for %d tickers", len(tickers))
    daily_series: dict[str, dict[str, dict[str, float]]] = {}
    ema_9h_cache: dict[str, dict[str, float]] = {}
    for i, ticker in enumerate(tickers):
        if on_progress:
            on_progress(0, f"Indicators: {ticker} ({i + 1}/{len(tickers)})")
        days = sorted(days_by_ticker[ticker])
        try:
            daily_series[ticker] = _daily_indicator_series(ticker, days, daily_from, published_through)
        except Exception as e:
            log.warning("Failed to fetch daily bars for %s: %s", ticker, e)
            daily_series[ticker] = {}
        try:
            ema_9h_cache[ticker] = _hourly_ema_series(ticker, days, daily_from, published_through)
        except Exception as e:
            log.warning("Failed to fetch hourly bars for %s: %s", ticker, e)
            ema_9h_cache[ticker] = {}

    # Group fills by (ticker, date) to share underlying bar lookups
    by_ticker_date: dict[tuple[str, str], list[Fill]] = defaultdict(list)
    for fill in fills:
        if fill.executed_at is None:
            continue
        day_str = fill.executed_at.strftime("%Y-%m-%d")
        by_ticker_date[(fill.ticker, day_str)].append(fill)

    enriched = 0
    fills_done = 0
    total_groups = len(by_ticker_date)
    minute_bars_by_ticker: dict[str, dict[date, dict[str, dict]]] = {}

    for i, ((ticker, day_str), day_fills) in enumerate(by_ticker_date.items()):
        log.info("Enriching %s %s (%d/%d)", ticker, day_str, i + 1, total_groups)
        if on_progress:
            on_progress(fills_done, ticker)
        day = date.fromisoformat(day_str)

        if ticker not in minute_bars_by_ticker:
            # All of this ticker's fill days at once: one range call per ~60 days.
            try:
                minute_bars_by_ticker[ticker] = fetch_minute_bars_for_days(ticker, days_by_ticker[ticker])
            except Exception as e:
                log.warning("Failed to fetch bars for %s: %s", ticker, e)
                minute_bars_by_ticker[ticker] = {}
        bars = minute_bars_by_ticker[ticker].get(day, {})
        indicators = daily_series.get(ticker, {})

        for fill in day_fills:
            bar = _find_bar(bars, fill.executed_at) if bars else None
            underlying_price = bar["close"] if bar else None
            fill.underlying_price_at_fill = underlying_price
            fill.vwap_at_fill = bar["vwap"] if bar else None

            # Greeks only for options with all required data
            if (
                fill.instrument_type == "option"
                and underlying_price is not None
                and fill.strike is not None
                and fill.expiration is not None
                and fill.option_type is not None
            ):
                T = _time_to_expiry(fill.executed_at, fill.expiration)
                # fill.price is total premium per contract; BS uses per-share price
                option_price_per_share = float(fill.price) / 100.0
                iv = implied_volatility(
                    option_price_per_share, underlying_price,
                    float(fill.strike), T, RISK_FREE_RATE, fill.option_type,
                )
                if iv is not None:
                    fill.iv_at_fill = iv
                    greeks = compute_greeks(
                        underlying_price, float(fill.strike), T, RISK_FREE_RATE, iv, fill.option_type
                    )
                    fill.delta_at_fill = greeks.get("delta")
                    fill.gamma_at_fill = greeks.get("gamma")
                    fill.theta_at_fill = greeks.get("theta")
                    fill.vega_at_fill = greeks.get("vega")

            # Daily indicators: last completed day before the fill (the fill
            # day's own value is computed on its close — look-ahead at fill time)
            fill.sma_20_at_fill = _prior_value(indicators.get("sma_20", {}), day_str)
            fill.sma_50_at_fill = _prior_value(indicators.get("sma_50", {}), day_str)
            fill.ema_9_at_fill = _prior_value(indicators.get("ema_9", {}), day_str)
            fill.ema_20_at_fill = _prior_value(indicators.get("ema_20", {}), day_str)
            fill.rsi_14_at_fill = _prior_value(indicators.get("rsi_14", {}), day_str)
            fill.macd_at_fill = _prior_value(indicators.get("macd", {}), day_str)
            fill.macd_signal_at_fill = _prior_value(indicators.get("macd_signal", {}), day_str)

            # Hourly EMA-9: last completed hour bar (the fill's own hour bar
            # closes after the fill), key "YYYY-MM-DD HH" in ET
            prior_hour = fill.executed_at - timedelta(hours=1)
            hour_key = f"{prior_hour.strftime('%Y-%m-%d')} {prior_hour.hour:02d}"
            fill.ema_9h_at_fill = ema_9h_cache.get(ticker, {}).get(hour_key)

            session.add(fill)
            enriched += 1

        # Batch commits: one per (ticker, day) group is a network round trip
        # per group on hosted Postgres. SQLite only takes its write lock at
        # commit time, so batching is safe there too.
        if (i + 1) % 10 == 0:
            session.commit()
        fills_done += len(day_fills)

    session.commit()
    log.info("Enriched %d fills", enriched)
    return enriched
