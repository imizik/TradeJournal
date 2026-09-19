"""
Fetch current stock prices and option premiums with short-lived in-memory
caching.

Two providers, chosen by ``QUOTES_PROVIDER``:

- ``yfinance`` (default) -- unofficial and unlicensed, and it downloads a whole
  option chain per (ticker, expiration) to read one contract.
- ``tradier`` -- licensed, consolidated NBBO, and every position plus its
  underlying comes back in ONE request. Falls back to yfinance on any error, so
  a bad token degrades instead of emptying the dashboard.

Which one is better is an empirical question, not a settled one:
``backend/scripts/compare_quote_providers.py`` prices the open book through
both (and through Alpaca) in the same second so the choice can be made on
measurement. Until that has been run against a real account, the default stays
where it was.

Option premiums are PER SHARE from both providers. The x100 per-contract
conversion lives in the frontend (`frontend/lib/dashboard.ts`); do not move it
here without changing both.

All helpers are best-effort. If a quote cannot be fetched, the corresponding
result is returned as None instead of raising.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date

import yfinance as yf

from app.engine.occ import occ_symbol
from app.engine.tradier import TradierError, get_quotes as tradier_get_quotes, tradier_configured

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
OPTION_PREMIUM_SCALE = 1.0

PROVIDER_YFINANCE = "yfinance"
PROVIDER_TRADIER = "tradier"


def quotes_provider() -> str:
    """The configured provider, falling back to yfinance when Tradier is
    selected without a key -- a misconfiguration should not blank the book."""
    configured = os.environ.get("QUOTES_PROVIDER", PROVIDER_YFINANCE).strip().lower()
    if configured == PROVIDER_TRADIER and not tradier_configured():
        log.warning("QUOTES_PROVIDER=tradier but TRADIER_API_KEY is unset — using yfinance")
        return PROVIDER_YFINANCE
    if configured not in (PROVIDER_YFINANCE, PROVIDER_TRADIER):
        log.warning("Unknown QUOTES_PROVIDER=%r — using yfinance", configured)
        return PROVIDER_YFINANCE
    return configured


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
    # Provenance, for callers that need to say where a number came from and how
    # old it is. Tradier's IV is ORATS data refreshed hourly and carries its own
    # timestamp; yfinance's is whatever the chain reported. Neither is live, and
    # neither may be written to a fill's *_at_fill columns.
    provider: str | None = None
    iv_updated_at: str | None = None


@dataclass
class CachedOptionChain:
    premiums: dict[tuple[float, str], OptionQuoteResult]
    fetched_at: float


_stock_cache: dict[str, CachedStockQuote] = {}
_option_chain_cache: dict[tuple[str, str], CachedOptionChain] = {}
# Tradier quotes one contract at a time rather than a chain, so it gets its own
# cache keyed by OCC symbol. The two providers never share cached state.
_option_contract_cache: dict[str, tuple[OptionQuoteResult, float]] = {}


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
    if quotes_provider() == PROVIDER_TRADIER:
        results = _tradier_option_quotes(requests)
        if results is not None:
            return results
        log.warning("Tradier option quotes unavailable — falling back to yfinance")

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


def _tradier_option_quotes(requests: list[OptionQuoteRequest]) -> list[OptionQuoteResult] | None:
    """Tradier option premiums, aligned to the input order.

    Returns None when the provider could not answer at all, which tells the
    caller to fall back. An individual contract Tradier does not know is an
    empty result, not a failure -- the same contract yfinance follows.
    """
    now = time.monotonic()
    symbols_by_index: dict[int, str] = {}
    for index, req in enumerate(requests):
        symbol = _occ_for_request(req)
        if symbol:
            symbols_by_index[index] = symbol

    needed = {
        symbol
        for symbol in symbols_by_index.values()
        if not _fresh_contract(symbol, now)
    }

    if needed:
        try:
            quotes = tradier_get_quotes(sorted(needed), greeks=True)
        except TradierError as exc:
            log.warning("Tradier option quote request failed: %s", exc)
            return None

        for symbol in needed:
            quote = quotes.get(symbol)
            result = (
                OptionQuoteResult(
                    last_price=_scale_option_premium(quote.last),
                    bid=_scale_option_premium(quote.bid),
                    ask=_scale_option_premium(quote.ask),
                    mid=_calc_mid(
                        _scale_option_premium(quote.bid),
                        _scale_option_premium(quote.ask),
                    ),
                    iv=quote.iv_mid,
                    provider=PROVIDER_TRADIER,
                    iv_updated_at=quote.greeks_updated_at,
                )
                if quote
                else OptionQuoteResult(provider=PROVIDER_TRADIER)
            )
            _option_contract_cache[symbol] = (result, now)

    results: list[OptionQuoteResult] = []
    for index in range(len(requests)):
        symbol = symbols_by_index.get(index)
        cached = _option_contract_cache.get(symbol) if symbol else None
        results.append(cached[0] if cached else OptionQuoteResult(provider=PROVIDER_TRADIER))
    return results


def _occ_for_request(req: OptionQuoteRequest) -> str | None:
    try:
        expiration = date.fromisoformat(req.expiration)
    except (TypeError, ValueError):
        log.warning("Unparseable option expiration %r for %s", req.expiration, req.ticker)
        return None
    return occ_symbol(req.ticker, expiration, req.option_type, req.strike)


def _fresh_contract(symbol: str, now: float) -> bool:
    cached = _option_contract_cache.get(symbol)
    return bool(cached and (now - cached[1]) < CACHE_TTL_SECONDS)


def _fetch_stock_quotes(tickers: list[str]) -> dict[str, float | None]:
    """Fetch live-ish stock prices with a recent-history fallback."""
    if quotes_provider() == PROVIDER_TRADIER:
        fetched = _tradier_stock_quotes(tickers)
        if fetched is not None:
            return fetched
        log.warning("Tradier stock quotes unavailable — falling back to yfinance")

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


def _tradier_stock_quotes(tickers: list[str]) -> dict[str, float | None] | None:
    """One batched Tradier call for every ticker. None means "could not ask"."""
    try:
        quotes = tradier_get_quotes(tickers)
    except TradierError as exc:
        log.warning("Tradier stock quote request failed: %s", exc)
        return None

    result: dict[str, float | None] = {}
    for ticker in tickers:
        quote = quotes.get(ticker.upper())
        # Prefer the last trade; fall back to the mid when a symbol has quotes
        # but no print yet (thin names before the open).
        result[ticker] = (quote.last if quote and quote.last is not None else quote.mid) if quote else None
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
            provider=PROVIDER_YFINANCE,
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
            provider=PROVIDER_YFINANCE,
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
