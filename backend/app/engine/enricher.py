"""
Fill enricher: fetches underlying prices from Polygon and computes option greeks
via Black-Scholes. Also fetches technical indicators (SMA, EMA, RSI, MACD).

Rate limit: Polygon free tier = 5 calls/min. We stay at 4.5/min with a token
bucket to leave headroom.

Cache: raw Polygon responses are saved to backend/data/polygon_cache/ so the
backfill can be interrupted and resumed without re-fetching.
"""

import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import yfinance as yf

import httpx
from dotenv import load_dotenv
from scipy.optimize import brentq
from scipy.stats import norm
from sqlmodel import Session, select

from app.models import Fill

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

log = logging.getLogger(__name__)

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "polygon_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RISK_FREE_RATE = 0.05  # ~current fed funds rate


# ---------------------------------------------------------------------------
# Rate limiter: 4.5 calls/min = one call every 13.4s
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, calls_per_minute: float = 4.5):
        self._interval = 60.0 / calls_per_minute
        self._last = 0.0

    def wait(self):
        elapsed = time.monotonic() - self._last
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last = time.monotonic()


_limiter = _RateLimiter(calls_per_minute=3.0)


# ---------------------------------------------------------------------------
# Polygon HTTP helpers with local cache
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe}.json"


def _polygon_get(path: str, params: dict) -> dict:
    """GET from Polygon, caching by (path + sorted params). Retries on 429."""
    cache_key = path + "_" + "_".join(f"{k}={v}" for k, v in sorted(params.items()))
    cp = _cache_path(cache_key)
    if cp.exists():
        return json.loads(cp.read_text())

    url = f"https://api.polygon.io{path}"
    req_params = {**params, "apiKey": POLYGON_API_KEY}

    for attempt in range(5):
        _limiter.wait()
        try:
            resp = httpx.get(url, params=req_params, timeout=30)
        except (httpx.NetworkError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            # Connection reset (e.g. after computer sleep) — retry with backoff
            wait = 20 * (attempt + 1)
            log.warning("Network error, waiting %ds (attempt %d/5): %s", wait, attempt + 1, e)
            time.sleep(wait)
            continue
        if resp.status_code == 403:
            log.warning("403 from Polygon for %s — ticker not covered by free tier, skipping", path)
            return {}
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            log.warning("429 from Polygon — waiting %ds (attempt %d/5)", wait, attempt + 1)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        # Only cache non-empty responses so today's missing bars get retried next sync
        results = data.get("results")
        has_data = (
            (isinstance(results, list) and len(results) > 0)
            or (isinstance(results, dict) and len(results.get("values", [])) > 0)
        )
        if has_data:
            cp.write_text(json.dumps(data))
        return data

    raise RuntimeError(f"Polygon request failed after 5 retries: {path}")


def fetch_minute_bars(ticker: str, day: date) -> dict[str, dict]:
    """Return {HH:MM -> {close, vwap}} for a ticker on a given trading day."""
    date_str = day.strftime("%Y-%m-%d")
    data = _polygon_get(
        f"/v2/aggs/ticker/{ticker}/range/1/minute/{date_str}/{date_str}",
        {"adjusted": "true", "sort": "asc", "limit": 1000},
    )
    bars: dict[str, dict] = {}
    for bar in data.get("results", []):
        dt = datetime.utcfromtimestamp(bar["t"] / 1000)
        # EDT = UTC-4, EST = UTC-5; approximate with -4 (covers DST/non-DST close enough)
        et_hour = (dt.hour - 4) % 24
        key = f"{et_hour:02d}:{dt.minute:02d}"
        bars[key] = {"close": bar["c"], "vwap": bar.get("vw")}
    return bars


def fetch_hourly_indicator_series(ticker: str, indicator: str, **kwargs) -> dict[str, float]:
    """
    Return {datetime_str -> value} for an hourly indicator series.
    Key format: "YYYY-MM-DD HH" (ET hour, approximate UTC-4).
    """
    params = {
        "timespan": "hour",
        "adjusted": "true",
        "limit": 5000,
        **kwargs,
    }
    data = _polygon_get(f"/v1/indicators/{indicator}/{ticker}", params)

    result: dict[str, float] = {}
    for entry in data.get("results", {}).get("values", []):
        dt = datetime.utcfromtimestamp(entry["timestamp"] / 1000)
        et_hour = (dt.hour - 4) % 24
        key = f"{dt.strftime('%Y-%m-%d')} {et_hour:02d}"
        result[key] = entry["value"]
    return result


def fetch_indicator_series(ticker: str, indicator: str, **kwargs) -> dict[str, float]:
    """
    Return {date_str -> value} for a full indicator series.
    indicator: "sma" | "ema" | "rsi" | "macd"
    """
    params = {
        "timespan": "day",
        "adjusted": "true",
        "limit": 5000,
        **kwargs,
    }
    data = _polygon_get(f"/v1/indicators/{indicator}/{ticker}", params)

    result: dict[str, float] = {}
    for entry in data.get("results", {}).get("values", []):
        dt_str = datetime.utcfromtimestamp(entry["timestamp"] / 1000).strftime("%Y-%m-%d")
        result[dt_str] = entry["value"]
    return result


def fetch_macd_series(ticker: str) -> tuple[dict[str, float], dict[str, float]]:
    """Return ({date -> macd_value}, {date -> signal_value})."""
    params = {
        "timespan": "day",
        "adjusted": "true",
        "short_window": 12,
        "long_window": 26,
        "signal_window": 9,
        "limit": 5000,
    }
    data = _polygon_get(f"/v1/indicators/macd/{ticker}", params)

    macd: dict[str, float] = {}
    signal: dict[str, float] = {}
    for entry in data.get("results", {}).get("values", []):
        dt_str = datetime.utcfromtimestamp(entry["timestamp"] / 1000).strftime("%Y-%m-%d")
        macd[dt_str] = entry["value"]
        signal[dt_str] = entry["signal"]
    return macd, signal


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

    # Group fills by ticker to minimize indicator API calls
    tickers = {f.ticker for f in fills}

    # Fetch indicator series per ticker (1 call per indicator per ticker)
    log.info("Fetching indicator series for %d tickers", len(tickers))
    sma_20_cache: dict[str, dict[str, float]] = {}
    sma_50_cache: dict[str, dict[str, float]] = {}
    ema_9_cache: dict[str, dict[str, float]] = {}
    ema_20_cache: dict[str, dict[str, float]] = {}
    rsi_cache: dict[str, dict[str, float]] = {}
    macd_cache: dict[str, dict[str, float]] = {}
    macd_signal_cache: dict[str, dict[str, float]] = {}
    ema_9h_cache: dict[str, dict[str, float]] = {}

    for ticker in tickers:
        try:
            sma_20_cache[ticker] = fetch_indicator_series(ticker, "sma", window=20)
            sma_50_cache[ticker] = fetch_indicator_series(ticker, "sma", window=50)
            ema_9_cache[ticker] = fetch_indicator_series(ticker, "ema", window=9)
            ema_20_cache[ticker] = fetch_indicator_series(ticker, "ema", window=20)
            rsi_cache[ticker] = fetch_indicator_series(ticker, "rsi", window=14)
            macd_vals, signal_vals = fetch_macd_series(ticker)
            macd_cache[ticker] = macd_vals
            macd_signal_cache[ticker] = signal_vals
            ema_9h_cache[ticker] = fetch_hourly_indicator_series(ticker, "ema", window=9)
        except Exception as e:
            log.warning("Failed to fetch indicators for %s: %s", ticker, e)

    # Group fills by (ticker, date) to share underlying bar fetches
    from collections import defaultdict
    by_ticker_date: dict[tuple[str, str], list[Fill]] = defaultdict(list)
    for fill in fills:
        if fill.executed_at is None:
            continue
        day_str = fill.executed_at.strftime("%Y-%m-%d")
        by_ticker_date[(fill.ticker, day_str)].append(fill)

    enriched = 0
    total_groups = len(by_ticker_date)

    for i, ((ticker, day_str), day_fills) in enumerate(by_ticker_date.items()):
        log.info("Enriching %s %s (%d/%d)", ticker, day_str, i + 1, total_groups)
        if on_progress:
            on_progress(i + 1, ticker)
        day = date.fromisoformat(day_str)

        try:
            bars = fetch_minute_bars(ticker, day)
        except Exception as e:
            log.warning("Failed to fetch bars for %s %s: %s", ticker, day_str, e)
            bars = {}

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

            # Daily indicators
            fill.sma_20_at_fill = sma_20_cache.get(ticker, {}).get(day_str)
            fill.sma_50_at_fill = sma_50_cache.get(ticker, {}).get(day_str)
            fill.ema_9_at_fill = ema_9_cache.get(ticker, {}).get(day_str)
            fill.ema_20_at_fill = ema_20_cache.get(ticker, {}).get(day_str)
            fill.rsi_14_at_fill = rsi_cache.get(ticker, {}).get(day_str)
            fill.macd_at_fill = macd_cache.get(ticker, {}).get(day_str)
            fill.macd_signal_at_fill = macd_signal_cache.get(ticker, {}).get(day_str)

            # Hourly EMA-9: key is "YYYY-MM-DD HH" in ET
            hour_key = f"{day_str} {fill.executed_at.hour:02d}"
            fill.ema_9h_at_fill = ema_9h_cache.get(ticker, {}).get(hour_key)

            session.add(fill)
            enriched += 1

    session.commit()
    log.info("Enriched %d fills", enriched)
    return enriched
