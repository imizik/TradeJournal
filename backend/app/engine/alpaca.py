"""
Alpaca market data client with file-based cache.

Endpoint: https://data.alpaca.markets
Feed: IEX (free) by default, override with ALPACA_DATA_FEED=sip

Cache layout:
  backend/data/alpaca_cache/stocks/1Day/{feed}/{ticker}.json
  backend/data/alpaca_cache/stocks/1Min/{feed}/{ticker}/{date}.json
  backend/data/alpaca_cache/stocks/1Hour/{feed}/{ticker}.json
  backend/data/alpaca_cache/options/{timeframe}/{symbol}/{start}_{end}.json

Daily bar cache is considered stale after 30 days (split/dividend adjustments
can change retroactively). Minute and hourly bar caches never expire.
"""

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

log = logging.getLogger(__name__)

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_API_SECRET = os.environ.get("ALPACA_API_SECRET", "")
ALPACA_DATA_FEED = os.environ.get("ALPACA_DATA_FEED", "iex")

DATA_URL = "https://data.alpaca.markets"
DAILY_CACHE_TTL_DAYS = 30

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "alpaca_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Rate limiter — Alpaca has no documented hard limit; 60/min is conservative
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, calls_per_minute: float = 60.0):
        self._interval = 60.0 / calls_per_minute
        self._last = 0.0

    def wait(self):
        elapsed = time.monotonic() - self._last
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last = time.monotonic()


_limiter = _RateLimiter(60.0)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
    }


def _alpaca_get(path: str, params: dict) -> dict:
    url = f"{DATA_URL}{path}"
    for attempt in range(5):
        _limiter.wait()
        try:
            resp = httpx.get(url, params=params, headers=_headers(), timeout=30)
        except (httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            wait = 15 * (attempt + 1)
            log.warning("Alpaca network error, retrying in %ds: %s", wait, e)
            time.sleep(wait)
            continue
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            log.warning("Alpaca 429 — waiting %ds (attempt %d/5)", wait, attempt + 1)
            time.sleep(wait)
            continue
        if resp.status_code == 403:
            log.warning("Alpaca 403 for %s — check key or feed entitlement", path)
            return {}
        if resp.status_code == 404:
            log.warning("Alpaca 404 for %s", path)
            return {}
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Alpaca request failed after 5 retries: {path}")


def _fetch_all_pages(path: str, params: dict) -> dict[str, list]:
    """Paginate a multi-symbol bars request. Returns {ticker: [bars]}."""
    result: dict[str, list] = {}
    page_params = dict(params)
    while True:
        data = _alpaca_get(path, page_params)
        for ticker, bars in data.get("bars", {}).items():
            result.setdefault(ticker, []).extend(bars)
        token = data.get("next_page_token")
        if not token:
            break
        page_params["page_token"] = token
    return result


# ---------------------------------------------------------------------------
# Cache path helpers
# ---------------------------------------------------------------------------

def _daily_cache_path(ticker: str) -> Path:
    p = CACHE_DIR / "stocks" / "1Day" / ALPACA_DATA_FEED / f"{ticker}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _minute_cache_path(ticker: str, day: date) -> Path:
    p = CACHE_DIR / "stocks" / "1Min" / ALPACA_DATA_FEED / ticker / f"{day.isoformat()}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _hourly_cache_path(ticker: str) -> Path:
    p = CACHE_DIR / "stocks" / "1Hour" / ALPACA_DATA_FEED / f"{ticker}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _option_bars_cache_path(symbol: str, timeframe: str, start: date | datetime, end: date | datetime) -> Path:
    safe_symbol = "".join(ch for ch in symbol.upper() if ch.isalnum())
    safe_timeframe = "".join(ch for ch in timeframe if ch.isalnum())
    start_key = start.isoformat().replace(":", "").replace("+", "")
    end_key = end.isoformat().replace(":", "").replace("+", "")
    p = CACHE_DIR / "options" / safe_timeframe / safe_symbol / f"{start_key}_{end_key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _daily_cache_valid(path: Path) -> bool:
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=ET)
    now_et = datetime.now(ET)
    # If the cache was written before today's 4:30pm close and we're now past it,
    # the file doesn't contain today's final bar — force a re-fetch.
    today_close_et = now_et.replace(hour=16, minute=30, second=0, microsecond=0)
    if mtime.date() == now_et.date() and mtime < today_close_et and now_et >= today_close_et:
        return False
    age_days = (now_et - mtime).days
    return age_days < DAILY_CACHE_TTL_DAYS


def _bar_et_date(bar: dict) -> Optional[date]:
    ts = bar.get("t")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(ET).date()
    except ValueError:
        return None


def _previous_weekday(day: date) -> date:
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _latest_completed_daily_bar_date(now_et: datetime | None = None) -> date:
    """Return the latest date for which a final daily bar should exist."""
    now_et = now_et or datetime.now(ET)
    today = now_et.date()
    today_close_et = now_et.replace(hour=16, minute=30, second=0, microsecond=0)

    if today.weekday() >= 5:
        return _previous_weekday(today)
    if now_et < today_close_et:
        return _previous_weekday(today)
    return today


def _latest_required_daily_bar_date(end: date) -> date:
    requested = min(end, _latest_completed_daily_bar_date())
    while requested.weekday() >= 5:
        requested -= timedelta(days=1)
    return requested


def _daily_cache_covers(path: Path, end: date) -> bool:
    if not _daily_cache_valid(path):
        return False
    try:
        bars = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not bars:
        return False

    last_date = max((d for d in (_bar_et_date(bar) for bar in bars) if d is not None), default=None)
    if last_date is None:
        return False

    requested_latest_complete = _latest_required_daily_bar_date(end)
    return last_date >= requested_latest_complete


# ---------------------------------------------------------------------------
# Public fetch functions
# ---------------------------------------------------------------------------

def fetch_daily_bars(tickers: list[str], start: date, end: date) -> dict[str, list]:
    """
    Fetch daily bars for a list of tickers from start to end.
    Returns {ticker: [bar_dict]}. Results are cached per ticker.
    Fetches uncached tickers in batches of 100.
    """
    result: dict[str, list] = {}
    missing: list[str] = []

    for ticker in tickers:
        cp = _daily_cache_path(ticker)
        if _daily_cache_covers(cp, end):
            result[ticker] = json.loads(cp.read_text())
        else:
            missing.append(ticker)

    if not missing:
        return result

    log.info("Fetching daily bars for %d tickers from Alpaca (%s feed)", len(missing), ALPACA_DATA_FEED)

    for i in range(0, len(missing), 100):
        batch = missing[i : i + 100]
        bars = _fetch_all_pages(
            "/v2/stocks/bars",
            {
                "symbols": ",".join(batch),
                "timeframe": "1Day",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjustment": "all",
                "feed": ALPACA_DATA_FEED,
                "limit": 10000,
            },
        )
        for ticker, ticker_bars in bars.items():
            cp = _daily_cache_path(ticker)
            cp.write_text(json.dumps(ticker_bars))
            result[ticker] = ticker_bars
        # Tickers with no bars at all won't appear in response — store empty list
        for ticker in batch:
            if ticker not in result:
                result[ticker] = []

    return result


def fetch_minute_bars_for_date(tickers: list[str], day: date, cache_only: bool = False) -> dict[str, list]:
    """
    Fetch 1-minute bars for multiple tickers on a single trading date (04:00–20:00 ET).
    Returns {ticker: [bar_dict]}. Results are cached per ticker/date.
    Skips today — intraday bars are not final.
    """
    result: dict[str, list] = {}
    missing: list[str] = []

    for ticker in tickers:
        cp = _minute_cache_path(ticker, day)
        if cp.exists():
            result[ticker] = json.loads(cp.read_text())
        else:
            missing.append(ticker)

    if not missing:
        return result

    if cache_only:
        return result  # caller only wants what's already on disk

    if day > datetime.now(ET).date():
        log.info("Skipping minute bar fetch for %s — future date", day)
        return result

    log.info("Fetching minute bars for %d tickers on %s", len(missing), day)

    start_dt = datetime(day.year, day.month, day.day, 4, 0, 0, tzinfo=ET)
    end_dt = datetime(day.year, day.month, day.day, 20, 0, 0, tzinfo=ET)

    for i in range(0, len(missing), 50):
        batch = missing[i : i + 50]
        bars = _fetch_all_pages(
            "/v2/stocks/bars",
            {
                "symbols": ",".join(batch),
                "timeframe": "1Min",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "adjustment": "raw",
                "feed": ALPACA_DATA_FEED,
                "limit": 10000,
            },
        )
        for ticker, ticker_bars in bars.items():
            cp = _minute_cache_path(ticker, day)
            cp.write_text(json.dumps(ticker_bars))
            result[ticker] = ticker_bars
        for ticker in batch:
            if ticker not in result:
                result[ticker] = []

    return result


def fetch_option_bars(
    symbols: list[str],
    timeframe: str,
    start: date | datetime,
    end: date | datetime,
) -> dict[str, list]:
    """
    Fetch historical option OHLC bars for option contract symbols.

    Results are cached by exact symbol/timeframe/start/end window. The API accepts
    up to 100 symbols per request, but the response limit is across all symbols,
    so pagination is always followed.
    """
    normalized = []
    seen = set()
    for symbol in symbols:
        value = symbol.strip().upper()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)

    result: dict[str, list] = {}
    missing: list[str] = []
    for symbol in normalized:
        cp = _option_bars_cache_path(symbol, timeframe, start, end)
        if cp.exists():
            result[symbol] = json.loads(cp.read_text())
        else:
            missing.append(symbol)

    if missing:
        log.info("Fetching option %s bars for %d contract(s)", timeframe, len(missing))

    for i in range(0, len(missing), 100):
        batch = missing[i : i + 100]
        bars = _fetch_all_pages(
            "/v1beta1/options/bars",
            {
                "symbols": ",".join(batch),
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": 10000,
                "sort": "asc",
            },
        )
        for symbol in batch:
            symbol_bars = bars.get(symbol, [])
            # Do not cache empty option responses. A 403 entitlement miss also
            # returns no bars via _alpaca_get(), and caching that would hide
            # data after the key/feed is fixed.
            if symbol_bars:
                cp = _option_bars_cache_path(symbol, timeframe, start, end)
                cp.write_text(json.dumps(symbol_bars))
            result[symbol] = symbol_bars

    for symbol in normalized:
        result.setdefault(symbol, [])

    return result


def fetch_snapshots(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch current snapshots (latest trade, today's daily bar, prev daily bar,
    latest minute bar) for many tickers in one call. Never cached — this is
    the live "right now" path used by market report generation.
    Returns {ticker: snapshot_dict}; tickers Alpaca has no data for are absent.
    """
    result: dict[str, dict] = {}
    for i in range(0, len(tickers), 100):
        batch = tickers[i : i + 100]
        data = _alpaca_get(
            "/v2/stocks/snapshots",
            {"symbols": ",".join(batch), "feed": ALPACA_DATA_FEED},
        )
        for ticker, snap in data.items():
            if isinstance(snap, dict):
                result[ticker] = snap
    return result


def fetch_minute_bars_live(tickers: list[str], day: date) -> dict[str, list]:
    """
    Fetch 1-minute bars for the given date (04:00–20:00 ET) WITHOUT touching
    the persistent minute cache. The persistent cache never expires, so caching
    a partial intraday day would poison enrichment runs — this path is for
    live report generation only.
    """
    result: dict[str, list] = {}
    start_dt = datetime(day.year, day.month, day.day, 4, 0, 0, tzinfo=ET)
    end_dt = datetime(day.year, day.month, day.day, 20, 0, 0, tzinfo=ET)

    for i in range(0, len(tickers), 50):
        batch = tickers[i : i + 50]
        bars = _fetch_all_pages(
            "/v2/stocks/bars",
            {
                "symbols": ",".join(batch),
                "timeframe": "1Min",
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "adjustment": "raw",
                "feed": ALPACA_DATA_FEED,
                "limit": 10000,
            },
        )
        for ticker in batch:
            result[ticker] = bars.get(ticker, [])
    return result


def alpaca_configured() -> bool:
    return bool(ALPACA_API_KEY and ALPACA_API_SECRET)
