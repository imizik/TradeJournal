"""Fetching and caching for the Peers strip (T3.4).

* Polygon ``/v1/related-companies/{ticker}``: the related tickers, cached seven days per symbol
  on disk under ``backend/data/symbol_info/v1/polygon/`` (an answer with no peers, an ETF, is
  cached too). The free plan is 5 calls a minute shared with fill enrichment, so the read goes
  through the enricher's adaptive limiter exactly like the News feed: it never waits more than
  ``MAX_WAIT_SECONDS`` for a slot (a slot further out counts as busy and claims nothing), never
  retries, and on a 429 or any failure serves the cached copy with its age and stays quiet for
  ``BACKOFF_SECONDS``.
* Tradier: one batched quote call for every peer, through the chart feed's budgeted read
  (``/v1/markets/quotes``, cached 15 s), so the peers share the chart's Tradier allowance.

Normalizing is in ``symbol_info_peers``; this module only moves bytes.
"""

from collections.abc import Callable
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

import httpx

from app.engine import enricher
from app.engine.api_wait import observed_sleep
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.engine.symbol_info_peers import chips, normalize_related

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_info" / "v1" / "polygon"
SCHEMA = 1
FRESH_SECONDS = 7 * 24 * 3600
BACKOFF_SECONDS = 5 * 60
MAX_WAIT_SECONDS = 2.0
TIMEOUT_SECONDS = 10
URL = "https://api.polygon.io/v1/related-companies/{symbol}"
POLYGON = {"provider": "polygon", "label": "Polygon related companies"}
TRADIER = {"provider": "tradier", "label": "Tradier quotes"}


class SourceError(Exception):
    pass


class SymbolPeers:
    def __init__(self, root: Path = CACHE_DIR, clock: Callable[[], float] = time.time,
                 quotes: Callable[[list[str]], tuple[dict, float, str | None]] | None = None):
        self.root = root
        self._clock = clock
        self._quotes = quotes or self._read_quotes
        self._memory: dict[str, tuple[float, list[str]]] = {}
        self._quiet_until: dict[str, tuple[float, str]] = {}
        self._fetching = threading.Lock()

    # ------------------------------------------------------------------ public

    def view(self, symbol: str) -> dict:
        now = self._clock()
        with self._fetching:
            tickers, source = self._related(symbol, now)
        quotes = {**TRADIER, "state": "ok", "fetched_at": None, "message": None}
        data: dict = {}
        if tickers:
            try:
                data, fetched_at, stale = self._quotes(tickers)
                quotes.update(fetched_at=fetched_at, state="stale" if stale else "ok", message=stale)
            except ChartFeedError as exc:
                quotes.update(state="failed", message=str(exc))
        state = "unavailable" if tickers is None else "ready" if tickers else "none"
        return {"symbol": symbol, "as_of": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "state": state, "source": source, "quotes": quotes, "peers": chips(tickers or [], data)}

    @staticmethod
    def _read_quotes(tickers: list[str]) -> tuple[dict, float, str | None]:
        return chart_feed.read("/v1/markets/quotes", {"symbols": ",".join(sorted(tickers))}, 15)

    # ----------------------------------------------------------------- polygon

    def _path(self, symbol: str) -> Path:
        return self.root / f"peers-{re.sub(r'[^A-Z0-9]+', '_', symbol)}.json"

    def _load(self, symbol: str) -> tuple[float, list[str]] | None:
        if symbol in self._memory:
            return self._memory[symbol]
        try:
            body = json.loads(self._path(symbol).read_text())
            if body.get("schema") == SCHEMA and isinstance(body.get("tickers"), list):
                self._memory[symbol] = (float(body["fetched_at"]), [str(t) for t in body["tickers"]])
                return self._memory[symbol]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _save(self, symbol: str, fetched_at: float, tickers: list[str]) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._path(symbol)
            temp = path.with_name(f".{path.name}.{uuid4().hex}")
            temp.write_text(json.dumps({"schema": SCHEMA, "fetched_at": fetched_at, "tickers": tickers}))
            temp.replace(path)
        except OSError as exc:
            log.warning("Could not cache Polygon peers for %s: %s", symbol, exc)

    def _related(self, symbol: str, now: float) -> tuple[list[str] | None, dict]:
        cached = self._load(symbol)
        if cached and now - cached[0] < FRESH_SECONDS:
            return cached[1], status("ok", cached[0], now)
        quiet = self._quiet_until.get(symbol)
        if quiet and now < quiet[0]:
            return self._degraded(cached, now, quiet[1])
        if not enricher.POLYGON_API_KEY:
            return None, status("not_configured", None, now, "Set POLYGON_API_KEY on the private backend to show peers.")
        try:
            tickers = normalize_related(self._call(symbol), symbol)
        except SourceError as exc:
            self._quiet_until[symbol] = (now + BACKOFF_SECONDS, str(exc))
            return self._degraded(cached, now, str(exc))
        self._memory[symbol] = (now, tickers)
        self._quiet_until.pop(symbol, None)
        self._save(symbol, now, tickers)
        return tickers, status("ok", now, now)

    @staticmethod
    def _degraded(cached, now: float, why: str) -> tuple[list[str] | None, dict]:
        if cached:
            return cached[1], status("stale", cached[0], now, f"{why} Showing the copy from the last read.")
        return None, status("failed", None, now, why)

    def _call(self, symbol: str) -> dict:
        """One Polygon read, never retried. Raises ``SourceError`` with the reason."""
        limiter = enricher._limiter
        delay = limiter.reserve_within(MAX_WAIT_SECONDS)
        if delay is None:
            raise SourceError("Polygon is busy with fill enrichment; its budget is shared.")
        if delay > 0:
            observed_sleep("Polygon", "rate_limit", delay)
        try:
            response = httpx.get(URL.format(symbol=polygon_ticker(symbol)), params={"apiKey": enricher.POLYGON_API_KEY}, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise SourceError(f"Polygon peers could not be read ({type(exc).__name__}).") from None
        if response.status_code == 429:
            limiter.note_refusal(enricher._retry_after_seconds(response.headers))
            raise SourceError("Polygon refused the read (429, the free plan allows 5 a minute).")
        if response.status_code != 200:
            raise SourceError(f"Polygon peers could not be read ({response.status_code}).")
        limiter.note_success()
        try:
            body = response.json()
        except ValueError:
            raise SourceError("Polygon peers came back unreadable.") from None
        if not isinstance(body, dict):
            raise SourceError("Polygon peers came back unreadable.")
        return body


def polygon_ticker(symbol: str) -> str:
    """Polygon writes class shares with a dot (BRK.B); the chart accepts BRK/B."""
    return symbol.replace("/", ".")


def status(state: str, fetched_at: float | None, now: float, message: str | None = None) -> dict:
    """``state``: ok, stale (an older copy is shown), failed, or not_configured."""
    return {**POLYGON, "state": state, "fetched_at": fetched_at,
            "age_seconds": None if fetched_at is None else max(0, int(now - fetched_at)), "message": message}


symbol_peers = SymbolPeers()
