"""Tradier option chains, normalized (Charts C4.1).

Tradier field names stop here. Callers receive `options_models.OptionChain`
and a sorted list of expiration dates; nothing outside this module reads a
Tradier option field.

One request per expiration, never per strike: `/v1/markets/options/chains`
returns every contract for one date with bid/ask/sizes, last, volume, open
interest and ORATS greeks/IV. For SPX one date can carry both the SPX and the
SPXW root (2026-10-16: 1,060 SPX and 938 SPXW contracts in one response); each
contract keeps its root. Expirations are listed with every root included, so
SPXW dates are not dropped.

Requests share one budget of 30 per minute, the options share of the token's
120 (`docs/charts-roadmap.md`), separate from the chart feed's 60. One request
takes one slot whether or not it succeeds, and nothing here retries. A 429 or
an access refusal pauses this budget for a minute. A caller that may wait (a
background job) passes ``wait=True`` and sleeps until a slot frees; anything
else is refused at once with code ``rate_limited``.

Placeholders become None, never zero: Tradier reports "never traded" as a trade
time of 0 and an implied volatility it could not compute as 0. Real zeros (no
open interest, no volume, a zero bid) stay zero. Rows that do not identify one
contract consistently (strike, side, expiration and root against the OCC
symbol and the request) make the whole chain malformed: a chain missing strikes
would misstate positioning without saying so.
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timezone
import math
import re
import threading
import time
from typing import Any, Callable

import httpx

from app.engine import tradier
from app.engine.occ import parse_occ
from app.engine.options_models import OptionChain, OptionContract

EXPIRATIONS_PATH = "/v1/markets/options/expirations"
CHAINS_PATH = "/v1/markets/options/chains"
REQUESTS_PER_MINUTE = 30
PAUSE_SECONDS = 60
TIMEOUT_SECONDS = 20  # one SPX date is about 1.6 MB
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")


class OptionsChainError(Exception):
    """A chain or expiration list that could not be read. ``code`` is one of
    not_configured, rate_limited, access_denied, provider_unavailable or malformed."""

    def __init__(self, message: str, code: str = "provider_unavailable"):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# parsing: pure, on a decoded response
# ---------------------------------------------------------------------------


def parse_expirations(payload: Any) -> list[date]:
    """Sorted expiration dates. ``{"expirations": null}`` (no listed options) is an empty list."""
    try:
        section = payload["expirations"]
        if section is None:
            return []
        dates = section["date"]
        dates = [dates] if isinstance(dates, str) else dates
        if not isinstance(dates, list):
            raise TypeError("dates")
        return sorted({date.fromisoformat(d) for d in dates})
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed expirations") from exc


def parse_chain(payload: Any, underlying: str, expiration: date, fetched_at: datetime) -> OptionChain:
    """One expiration's contracts. ``{"options": null}`` (nothing listed for that
    date) is a chain with no contracts; a row that cannot be trusted is an error."""
    try:
        section = payload["options"]
        rows = [] if section is None else section["option"]
        rows = [rows] if isinstance(rows, dict) else rows
        if not isinstance(rows, list):
            raise TypeError("rows")
        contracts = [_contract(row, underlying, expiration) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed option chain") from exc
    if len({c.symbol for c in contracts}) != len(contracts):
        raise ValueError("malformed option chain: a contract is listed twice")
    return OptionChain(underlying, expiration, "tradier", fetched_at, tuple(contracts))


def _contract(row: dict, underlying: str, expiration: date) -> OptionContract:
    symbol = str(row["symbol"]).upper()
    occ = parse_occ(symbol)
    option_type = row["option_type"]
    strike = _number(row["strike"])
    root = str(row["root_symbol"]).upper()
    reported = str(row["underlying"]).upper()
    if (
        occ is None
        or option_type not in ("call", "put")
        or strike is None or strike <= 0
        or date.fromisoformat(row["expiration_date"]) != expiration
        or _alnum(reported) != _alnum(underlying)
        or occ["root"] != root
        or occ["expiration"] != expiration
        or occ["option_type"] != option_type
        or round(occ["strike"] * 1000) != round(strike * 1000)
    ):
        raise ValueError(f"inconsistent contract {symbol}")
    greeks = row.get("greeks") if isinstance(row.get("greeks"), dict) else {}
    multiplier = _count(row.get("contract_size"))
    stamp = greeks.get("updated_at")
    return OptionContract(
        symbol=symbol,
        underlying=reported,
        root=root,
        expiration=expiration,
        option_type=option_type,
        strike=strike,
        multiplier=multiplier if multiplier else None,
        bid=_number(row.get("bid")),
        ask=_number(row.get("ask")),
        last=_number(row.get("last")),
        bid_size=_count(row.get("bidsize")),
        ask_size=_count(row.get("asksize")),
        volume=_count(row.get("volume")),
        open_interest=_count(row.get("open_interest")),
        bid_time=_event_time(row.get("bid_date")),
        ask_time=_event_time(row.get("ask_date")),
        trade_time=_event_time(row.get("trade_date")),
        iv=_positive(greeks.get("mid_iv")),
        iv_smoothed=_positive(greeks.get("smv_vol")),
        delta=_number(greeks.get("delta")),
        gamma=_number(greeks.get("gamma")),
        theta=_number(greeks.get("theta")),
        vega=_number(greeks.get("vega")),
        greeks_updated_at=stamp if isinstance(stamp, str) and stamp else None,
    )


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive(value: Any) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _count(value: Any) -> int | None:
    parsed = _number(value)
    return int(parsed) if parsed is not None and parsed >= 0 and parsed == int(parsed) else None


def _event_time(value: Any) -> datetime | None:
    millis = _number(value)
    if millis is None or millis <= 0:
        return None  # 0 is Tradier's "never"
    return datetime.fromtimestamp(millis / 1000, timezone.utc)


def _alnum(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum())


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------


class TradierOptions:
    def __init__(
        self,
        per_minute: int = REQUESTS_PER_MINUTE,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()
        self._paused_until = 0.0

    def expirations(self, symbol: str, wait: bool = False) -> list[date]:
        """Every listed expiration date for ``symbol``, all roots included, sorted."""
        symbol = _symbol(symbol)
        payload = self._get(EXPIRATIONS_PATH, {"symbol": symbol, "includeAllRoots": "true", "strikes": "false"}, wait)
        try:
            return parse_expirations(payload)
        except ValueError as exc:
            raise OptionsChainError(f"Tradier returned an unreadable expiration list for {symbol}.", "malformed") from exc

    def chain(self, symbol: str, expiration: date, wait: bool = False) -> OptionChain:
        """Every contract for one expiration date, with greeks, in one request."""
        symbol = _symbol(symbol)
        payload = self._get(CHAINS_PATH, {"symbol": symbol, "expiration": expiration.isoformat(), "greeks": "true"}, wait)
        fetched_at = datetime.fromtimestamp(self._clock(), timezone.utc)
        try:
            return parse_chain(payload, symbol, expiration, fetched_at)
        except ValueError as exc:
            raise OptionsChainError(f"Tradier returned an unreadable {symbol} {expiration} option chain.", "malformed") from exc

    def _get(self, path: str, params: dict[str, str], wait: bool) -> Any:
        if not tradier.tradier_configured():
            raise OptionsChainError("Set TRADIER_API_KEY on the private backend to read option chains.", "not_configured")
        self._take(wait)
        try:
            response = httpx.get(
                f"{tradier.TRADIER_BASE_URL}{path}", params=params,
                headers={"Authorization": f"Bearer {tradier.TRADIER_API_KEY}", "Accept": "application/json"},
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise OptionsChainError("The Tradier connection failed while reading options.") from exc
        if response.status_code == 429:
            self._pause()
            raise OptionsChainError("Tradier's data allowance is exhausted; option reads pause for a minute.", "rate_limited")
        if response.status_code in (401, 403):
            self._pause()
            raise OptionsChainError("Tradier refused option data. Check the token and the account's market-data access.", "access_denied")
        if response.status_code >= 400:
            raise OptionsChainError(f"Tradier could not read options ({response.status_code}).")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OptionsChainError("Tradier returned a non-JSON options response.") from exc
        if not isinstance(payload, dict) or payload.get("fault") or payload.get("errors"):
            raise OptionsChainError("Tradier returned an unexpected options response.")
        return payload

    def _take(self, wait: bool) -> None:
        """Claim one request slot in the rolling minute, sleeping for it only when ``wait``."""
        while True:
            with self._lock:
                now = self._clock()
                while self._calls and self._calls[0] <= now - 60:
                    self._calls.popleft()
                if now < self._paused_until:
                    ready = self._paused_until
                elif len(self._calls) < self.per_minute:
                    self._calls.append(now)
                    return
                else:
                    ready = self._calls[0] + 60
            if not wait:
                raise OptionsChainError("Option reads are pacing to stay within their data allowance.", "rate_limited")
            self._sleep(max(ready - now, 0.05))

    def _pause(self) -> None:
        with self._lock:
            self._paused_until = max(self._paused_until, self._clock() + PAUSE_SECONDS)


def _symbol(symbol: str) -> str:
    cleaned = str(symbol or "").strip().upper()
    if not SYMBOL.fullmatch(cleaned):
        raise ValueError(f"not an underlying symbol: {symbol!r}")  # a caller's mistake; costs no request
    return cleaned


options_chain = TradierOptions()
