"""
Fetch current stock prices and option premiums via yfinance with short-lived
in-memory caching.

All helpers are best-effort. If a quote cannot be fetched, the corresponding
result is returned as None instead of raising.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date

import yfinance as yf

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
OPTION_PREMIUM_SCALE = 1.0


@dataclass
class CachedStockQuote:
    price: float
    fetched_at: float


@dataclass
class OptionQuoteRequest:
    ticker: str
    expiration: str
    strike: float
    option_type: str


@dataclass
class OptionQuoteResult:
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    iv: float | None = None


@dataclass
class CachedOptionChain:
    premiums: dict[tuple[float, str], OptionQuoteResult]
    fetched_at: float


_stock_cache: dict[str, CachedStockQuote] = {}
_option_chain_cache: dict[tuple[str, str], CachedOptionChain] = {}


def get_stock_quotes(tickers: list[str]) -> dict[str, float | None]:
    """Return {ticker: price_or_None} for each requested ticker."""
    normalized = [ticker.strip().upper() for ticker in tickers if ticker.strip()]
    now = time.monotonic()
    result: dict[str, float | None] = {}
    missing: list[str] = []

    for ticker in normalized:
        cached = _stock_cache.get(ticker)
        if cached and (now - cached.fetched_at) < CACHE_TTL_SECONDS:
            result[ticker] = cached.price
        elif ticker not in missing:
            missing.append(ticker)

    if missing:
        fetched = _fetch_stock_quotes(missing)
        for ticker, price in fetched.items():
            result[ticker] = price
            if price is not None:
                _stock_cache[ticker] = CachedStockQuote(price=price, fetched_at=now)

    for ticker in normalized:
        result.setdefault(ticker, None)

    return result


def get_option_quotes(requests: list[OptionQuoteRequest]) -> list[OptionQuoteResult]:
    """Return option premiums for each request, aligned to the input order."""
    now = time.monotonic()
    results: list[OptionQuoteResult] = [OptionQuoteResult() for _ in requests]
    missing_expirations_by_ticker: dict[str, set[str]] = {}

    for req in requests:
        ticker = req.ticker.strip().upper()
        cache_key = (ticker, req.expiration)
        contract_key = (_normalize_strike(req.strike), req.option_type.lower())
        cached = _option_chain_cache.get(cache_key)

        if not cached or (now - cached.fetched_at) >= CACHE_TTL_SECONDS or contract_key not in cached.premiums:
            missing_expirations_by_ticker.setdefault(ticker, set()).add(req.expiration)

    if missing_expirations_by_ticker:
        fetched_at = time.monotonic()
        for ticker, expirations in missing_expirations_by_ticker.items():
            fetched = _fetch_option_chains(ticker, expirations)
            for requested_expiration, premiums in fetched.items():
                _option_chain_cache[(ticker, requested_expiration)] = CachedOptionChain(
                    premiums=premiums,
                    fetched_at=fetched_at,
                )

    for index, req in enumerate(requests):
        ticker = req.ticker.strip().upper()
        cache_key = (ticker, req.expiration)
        contract_key = (_normalize_strike(req.strike), req.option_type.lower())
        cached = _option_chain_cache.get(cache_key)
        if cached:
            results[index] = cached.premiums.get(contract_key, OptionQuoteResult())

    return results


def _fetch_stock_quotes(tickers: list[str]) -> dict[str, float | None]:
    """Fetch live-ish stock prices with a recent-history fallback."""
    result: dict[str, float | None] = {ticker: None for ticker in tickers}

    for ticker in tickers:
        try:
            yticker = yf.Ticker(ticker)
        except Exception:
            log.warning("Failed to initialize stock quote fetch for %s", ticker, exc_info=True)
            continue

        price = _get_fast_info_price(yticker)
        if price is not None:
            result[ticker] = price
            continue

        try:
            intraday = yticker.history(period="1d", interval="1m", auto_adjust=False, prepost=True)
            if not intraday.empty:
                price = _safe_float(intraday["Close"].dropna().iloc[-1])
                if price is not None:
                    result[ticker] = price
                    continue
        except Exception:
            log.debug("Intraday history lookup failed for %s", ticker, exc_info=True)

        try:
            daily = yticker.history(period="5d", interval="1d", auto_adjust=False)
            if not daily.empty:
                price = _safe_float(daily["Close"].dropna().iloc[-1])
                if price is not None:
                    result[ticker] = price
        except Exception:
            log.warning("Failed to fetch stock quote for %s", ticker, exc_info=True)

    return result


def _fetch_option_chains(
    ticker: str,
    expirations: set[str],
) -> dict[str, dict[tuple[float, str], OptionQuoteResult]]:
    """
    Fetch option chain data for a ticker.

    Returns a dict keyed by the requested expiration date. If the requested
    expiration is unavailable, the closest available expiration within 7 days is
    used and still cached under the requested expiration key.
    """
    result: dict[str, dict[tuple[float, str], OptionQuoteResult]] = {}

    try:
        yticker = yf.Ticker(ticker)
        available_expirations = set(yticker.options)
        parsed_chains_by_expiration: dict[str, dict[tuple[float, str], OptionQuoteResult]] = {}

        for requested_expiration in expirations:
            fetch_expiration = requested_expiration
            if fetch_expiration not in available_expirations:
                fetch_expiration = _find_closest_expiration(requested_expiration, available_expirations)
            if fetch_expiration is None:
                result[requested_expiration] = {}
                continue

            if fetch_expiration not in parsed_chains_by_expiration:
                chain = yticker.option_chain(fetch_expiration)
                parsed_chains_by_expiration[fetch_expiration] = _parse_option_chain(chain)

            result[requested_expiration] = parsed_chains_by_expiration[fetch_expiration]
    except Exception:
        log.warning("Failed to fetch option chains for %s", ticker, exc_info=True)
        for requested_expiration in expirations:
            result.setdefault(requested_expiration, {})

    return result


def _parse_option_chain(chain) -> dict[tuple[float, str], OptionQuoteResult]:
    premiums: dict[tuple[float, str], OptionQuoteResult] = {}

    for _, row in chain.calls.iterrows():
        key = (_normalize_strike(row.get("strike")), "call")
        premiums[key] = OptionQuoteResult(
            last_price=_scale_option_premium(row.get("lastPrice")),
            bid=_scale_option_premium(row.get("bid")),
            ask=_scale_option_premium(row.get("ask")),
            mid=_calc_mid(
                _scale_option_premium(row.get("bid")),
                _scale_option_premium(row.get("ask")),
            ),
            iv=_safe_float(row.get("impliedVolatility")),
        )

    for _, row in chain.puts.iterrows():
        key = (_normalize_strike(row.get("strike")), "put")
        premiums[key] = OptionQuoteResult(
            last_price=_scale_option_premium(row.get("lastPrice")),
            bid=_scale_option_premium(row.get("bid")),
            ask=_scale_option_premium(row.get("ask")),
            mid=_calc_mid(
                _scale_option_premium(row.get("bid")),
                _scale_option_premium(row.get("ask")),
            ),
            iv=_safe_float(row.get("impliedVolatility")),
        )

    return premiums


def _find_closest_expiration(target: str, available: set[str]) -> str | None:
    if not available:
        return None

    try:
        target_date = date.fromisoformat(target)
        closest = min(available, key=lambda exp: abs((date.fromisoformat(exp) - target_date).days))
        if abs((date.fromisoformat(closest) - target_date).days) <= 7:
            return closest
    except Exception:
        log.debug("Could not parse option expiration %s", target, exc_info=True)

    return None


def _normalize_strike(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return round(float(value), 4)


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
        if parsed != parsed:
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _get_fast_info_price(yticker) -> float | None:
    try:
        fast_info = yticker.fast_info
    except Exception:
        log.debug("fast_info lookup failed for %s", yticker.ticker, exc_info=True)
        return None

    for key in ("lastPrice", "regularMarketPrice", "previousClose"):
        try:
            if hasattr(fast_info, "get"):
                price = _safe_float(fast_info.get(key))
            else:
                price = _safe_float(fast_info[key])
            if price is not None:
                return price
        except Exception:
            continue

    return None


def _scale_option_premium(value) -> float | None:
    premium = _safe_float(value)
    if premium is None:
        return None
    return round(premium * OPTION_PREMIUM_SCALE, 4)


def _calc_mid(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    if (bid + ask) <= 0:
        return None
    return round((bid + ask) / 2, 4)
