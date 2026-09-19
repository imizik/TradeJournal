"""Tradier market-data client: live quotes for equities and option contracts.

Scope is deliberately one endpoint. Tradier is a *live* quote source here and
nothing else -- its 1-minute history reaches back 20 days and it serves nothing
at all for expired option contracts, so Polygon and Alpaca keep the historical
work. See `docs/tradier-integration-plan.md` for the whole assessment.

`POST /v1/markets/quotes` takes a comma-separated symbol list, so every open
position and its underlying come back in ONE request. Equities and OCC option
symbols mix freely in that list.

Rate limit: Tradier documents 120 requests/minute for `/markets`, per access
token, and every response carries `X-Ratelimit-Available`. Peak usage in this
application is under ten calls a minute, so there is nothing to pace and no
budget to discover -- this module reads the header, logs when the remaining
allowance gets low, and backs off only on an actual 429. Do NOT grow the
Polygon-style learned limiter here; that design exists because Polygon's real
budget depends on an unknown plan, and Tradier's does not.

Greeks are ORATS data refreshed **hourly** and carry their own `updated_at`.
They are never contemporaneous with a fill. `greeks_updated_at` is passed
through unmodified so a caller can show the staleness; never store them in a
fill's `*_at_fill` columns.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

log = logging.getLogger(__name__)

TRADIER_API_KEY = os.environ.get("TRADIER_API_KEY", "")
TRADIER_BASE_URL = os.environ.get("TRADIER_BASE_URL", "https://api.tradier.com").rstrip("/")

REQUEST_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3
# Tradier counts in 1-minute windows. A 429 without Retry-After means waiting
# for the window to roll; anything longer is a stall, anything shorter is a
# second refusal.
DEFAULT_RETRY_AFTER_SECONDS = 20.0
LOW_ALLOWANCE_WARNING = 20  # remaining calls in the window worth logging about


class TradierError(RuntimeError):
    """A Tradier request that could not be completed."""


@dataclass
class TradierQuote:
    """One quote row, normalized. Option premiums are PER SHARE, as Tradier
    reports them -- the x100 per-contract conversion belongs to the caller."""

    symbol: str
    last: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    volume: Optional[int] = None
    # Tradier's own millisecond timestamps, passed through unmodified.
    bid_date: Optional[int] = None
    ask_date: Optional[int] = None
    trade_date: Optional[int] = None
    # Options only, and only when greeks were requested.
    iv_mid: Optional[float] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    smv_vol: Optional[float] = None
    greeks_updated_at: Optional[str] = None
    raw: Optional[dict] = None


def tradier_configured() -> bool:
    return bool(TRADIER_API_KEY)


def get_quotes(symbols: list[str], greeks: bool = False) -> dict[str, TradierQuote]:
    """Quote every symbol in one request. Returns {symbol: TradierQuote}.

    Symbols Tradier does not recognize are simply absent from the result, the
    same contract `fetch_option_snapshots` follows. Raises TradierError when the
    request itself fails, so a caller can fall back to another provider.
    """
    wanted = [s.strip().upper() for s in symbols if s and s.strip()]
    if not wanted:
        return {}
    if not tradier_configured():
        raise TradierError("TRADIER_API_KEY is not set")

    payload = {"symbols": ",".join(wanted)}
    if greeks:
        payload["greeks"] = "true"

    data = _post("/v1/markets/quotes", payload)
    rows = _quote_rows(data)

    result: dict[str, TradierQuote] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            result[symbol] = _parse_quote(symbol, row)

    missing = [s for s in wanted if s not in result]
    if missing:
        log.info("Tradier returned no quote for %d symbol(s): %s", len(missing), ", ".join(missing[:5]))
    return result


# ---------------------------------------------------------------------------
# response shape
#
# Tradier returns `quotes.quote` as an OBJECT for one symbol and an ARRAY for
# several, and reports unknown symbols separately under
# `quotes.unmatched_symbols`. Both shapes reach here on the same code path, so
# normalize once, at the edge.
# ---------------------------------------------------------------------------

def _quote_rows(data: dict) -> list[dict]:
    quotes = (data or {}).get("quotes")
    if not isinstance(quotes, dict):
        return []

    unmatched = quotes.get("unmatched_symbols")
    if unmatched:
        symbols = unmatched.get("symbol") if isinstance(unmatched, dict) else unmatched
        log.info("Tradier did not match: %s", symbols)

    quote = quotes.get("quote")
    if isinstance(quote, dict):
        return [quote]
    if isinstance(quote, list):
        return [row for row in quote if isinstance(row, dict)]
    return []


def _parse_quote(symbol: str, row: dict) -> TradierQuote:
    bid = _f(row.get("bid"))
    ask = _f(row.get("ask"))
    greeks = row.get("greeks") if isinstance(row.get("greeks"), dict) else {}

    return TradierQuote(
        symbol=symbol,
        last=_f(row.get("last")),
        bid=bid,
        ask=ask,
        mid=_mid(bid, ask),
        bid_size=_i(row.get("bidsize")),
        ask_size=_i(row.get("asksize")),
        volume=_i(row.get("volume")),
        bid_date=_i(row.get("bid_date")),
        ask_date=_i(row.get("ask_date")),
        trade_date=_i(row.get("trade_date")),
        iv_mid=_f(greeks.get("mid_iv")),
        delta=_f(greeks.get("delta")),
        gamma=_f(greeks.get("gamma")),
        theta=_f(greeks.get("theta")),
        vega=_f(greeks.get("vega")),
        smv_vol=_f(greeks.get("smv_vol")),
        greeks_updated_at=greeks.get("updated_at") or None,
        raw=row,
    )


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def _post(path: str, payload: dict[str, str]) -> dict:
    url = f"{TRADIER_BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {TRADIER_API_KEY}",
        "Accept": "application/json",
    }

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = httpx.post(url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            last_error = exc
            log.warning("Tradier transport error on %s (attempt %d): %s", path, attempt, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(attempt)
            continue

        _note_allowance(response.headers)

        if response.status_code == 429:
            wait = _retry_after_seconds(response.headers)
            last_error = TradierError(f"Tradier rate limited {path}")
            log.warning("Tradier rate limited %s; waiting %.0fs", path, wait)
            if attempt < MAX_ATTEMPTS:
                time.sleep(wait)
            continue

        if response.status_code in (401, 403):
            # Entitlement and a bad token look the same from here; say both.
            raise TradierError(
                f"Tradier refused the request ({response.status_code}). Check TRADIER_API_KEY "
                "and that the account is entitled to market data."
            )

        if response.status_code >= 400:
            raise TradierError(f"Tradier {path} returned {response.status_code}: {response.text[:200]}")

        try:
            return response.json()
        except ValueError as exc:
            raise TradierError(f"Tradier {path} returned non-JSON: {response.text[:200]}") from exc

    raise TradierError(f"Tradier {path} failed after {MAX_ATTEMPTS} attempts: {last_error}")


def _note_allowance(headers) -> None:
    available = _i(headers.get("X-Ratelimit-Available"))
    if available is not None and available <= LOW_ALLOWANCE_WARNING:
        log.warning(
            "Tradier rate-limit allowance low: %s of %s left this window",
            available,
            headers.get("X-Ratelimit-Allowed", "?"),
        )


def _retry_after_seconds(headers) -> float:
    raw = headers.get("Retry-After")
    if raw:
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            pass

    expiry = _i(headers.get("X-Ratelimit-Expiry"))
    if expiry is not None:
        # Tradier reports the window expiry in milliseconds.
        remaining = (expiry / 1000.0) - time.time()
        if 0 < remaining <= 120:
            return remaining
    return DEFAULT_RETRY_AFTER_SECONDS


# ---------------------------------------------------------------------------
# coercion
# ---------------------------------------------------------------------------

def _f(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
        if parsed != parsed:  # NaN
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _mid(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    if bid is None or ask is None:
        return None
    if (bid + ask) <= 0:
        return None
    return round((bid + ask) / 2, 4)
