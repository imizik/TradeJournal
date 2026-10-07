"""Fetching and caching for the News tab (T1.2).

Two sources, each degrading on its own:

* Alpaca (Benzinga) through ``news.fetch_news(fast=True)``, cached 60 s per symbol in
  memory. One request on a ~2.5 s budget, no retry and no limiter wait; a 429,
  timeout or failure serves the older copy with its age (or ``failed``) and stays
  quiet for ``BACKOFF_SECONDS``, so the request path never blocks.
* Polygon ``/v2/reference/news`` (headlines with per-ticker sentiment), cached 15
  minutes per symbol on disk under ``backend/data/symbol_info/v1/polygon/``. The
  free plan is 5 calls a minute shared with fill enrichment, so this is read only
  when the News tab asks, goes through the enricher's adaptive limiter, never
  waits for a slot and never retries: on a 429, any failure, or a busy limiter it
  serves the cached copy with its age and stays quiet for ``BACKOFF_SECONDS``.

Normalizing is in ``symbol_info_news``; this module only moves bytes.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

import httpx

from app.engine import enricher, news
from app.engine.api_wait import observed_sleep
from app.engine.alpaca import ALPACA_API_KEY, ALPACA_API_SECRET
from app.engine.symbol_info_news import ALPACA, POLYGON, SENTIMENT_NOTE, merge, normalize_alpaca, normalize_polygon

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_info" / "v1" / "polygon"
SCHEMA = 1
DAYS = 7
ALPACA_FRESH_SECONDS = 60
POLYGON_FRESH_SECONDS = 15 * 60
BACKOFF_SECONDS = 5 * 60  # after a Polygon failure, no new call for this long
MAX_WAIT_SECONDS = 2.0  # a limiter slot further out than this is "busy": serve the cache
TIMEOUT_SECONDS = 10
URL = "https://api.polygon.io/v2/reference/news"
LABELS = {ALPACA: "Alpaca (Benzinga)", POLYGON: "Polygon"}


class SourceError(Exception):
    pass


class SymbolNews:
    def __init__(self, root: Path = CACHE_DIR, clock: Callable[[], float] = time.time,
                 alpaca: Callable[[str, datetime], list[dict]] | None = None):
        self.root = root
        self._clock = clock
        self._alpaca = alpaca or self._read_alpaca
        self._lock = threading.Lock()
        self._alpaca_cache: dict[str, tuple[float, list[dict]]] = {}
        self._alpaca_quiet_until: dict[str, float] = {}
        self._polygon_memory: dict[str, tuple[float, list[dict]]] = {}
        self._polygon_quiet_until: dict[str, tuple[float, str]] = {}
        self._fetching = threading.Lock()  # one read at a time; a waiter reuses the fresh copy

    # ------------------------------------------------------------------ public

    def view(self, symbol: str) -> dict:
        with self._fetching:
            now = self._clock()
            alpaca, a_status = self._alpaca_rows(symbol, now)
            polygon, p_status = self._polygon_rows(symbol, now)
        return {"symbol": symbol, "as_of": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "time_zone": "America/New_York", "days": DAYS, "sentiment_note": SENTIMENT_NOTE,
                "sources": [a_status, p_status], "articles": merge(alpaca or [], polygon or [])}

    # ------------------------------------------------------------------ alpaca

    @staticmethod
    def _read_alpaca(symbol: str, start: datetime) -> list[dict]:
        return news.fetch_news(symbols=[symbol], start=start, limit=50, fast=True)

    def _alpaca_rows(self, symbol: str, now: float) -> tuple[list[dict] | None, dict]:
        cached = self._alpaca_cache.get(symbol)
        if cached and now - cached[0] < ALPACA_FRESH_SECONDS:
            return cached[1], status(ALPACA, "ok", cached[0], now)
        if self._alpaca is self._read_alpaca and not (ALPACA_API_KEY and ALPACA_API_SECRET):
            return None, status(ALPACA, "not_configured", None, now, "Set ALPACA_API_KEY and ALPACA_API_SECRET on the private backend to read Alpaca news.")
        if now < self._alpaca_quiet_until.get(symbol, 0.0):
            return self._alpaca_degraded(cached, now)
        try:
            rows = normalize_alpaca(self._alpaca(symbol, datetime.fromtimestamp(now, timezone.utc) - timedelta(days=DAYS)))
        except Exception as exc:  # the provider's own errors vary; none may take down the tab
            log.warning("Alpaca news for %s failed: %s", symbol, exc)
            self._alpaca_quiet_until[symbol] = now + BACKOFF_SECONDS
            return self._alpaca_degraded(cached, now)
        self._alpaca_quiet_until.pop(symbol, None)
        self._alpaca_cache[symbol] = (now, rows)
        return rows, status(ALPACA, "ok", now, now)

    @staticmethod
    def _alpaca_degraded(cached, now: float) -> tuple[list[dict] | None, dict]:
        if cached:
            return cached[1], status(ALPACA, "stale", cached[0], now, "Alpaca news could not be read; showing the older copy.")
        return None, status(ALPACA, "failed", None, now, "Alpaca news could not be read.")

    # ----------------------------------------------------------------- polygon

    def _path(self, symbol: str) -> Path:
        return self.root / f"news-{re.sub(r'[^A-Z0-9]+', '_', symbol)}.json"

    def _load(self, symbol: str) -> tuple[float, list[dict]] | None:
        if symbol in self._polygon_memory:
            return self._polygon_memory[symbol]
        try:
            body = json.loads(self._path(symbol).read_text())
            if body.get("schema") == SCHEMA and isinstance(body.get("rows"), list):
                self._polygon_memory[symbol] = (float(body["fetched_at"]), body["rows"])
                return self._polygon_memory[symbol]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _save(self, symbol: str, fetched_at: float, rows: list[dict]) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self._path(symbol)
            temp = path.with_name(f".{path.name}.{uuid4().hex}")
            temp.write_text(json.dumps({"schema": SCHEMA, "fetched_at": fetched_at, "rows": rows}))
            temp.replace(path)
        except OSError as exc:
            log.warning("Could not cache Polygon news for %s: %s", symbol, exc)

    def _polygon_rows(self, symbol: str, now: float) -> tuple[list[dict] | None, dict]:
        cached = self._load(symbol)
        if cached and now - cached[0] < POLYGON_FRESH_SECONDS:
            return cached[1], status(POLYGON, "ok", cached[0], now)
        quiet = self._polygon_quiet_until.get(symbol)
        if quiet and now < quiet[0]:
            return self._degraded(cached, now, quiet[1])
        if not enricher.POLYGON_API_KEY:
            return None, status(POLYGON, "not_configured", None, now, "Set POLYGON_API_KEY on the private backend to add Polygon news and sentiment.")
        try:
            rows = normalize_polygon(self._call(symbol, now))
        except SourceError as exc:
            self._polygon_quiet_until[symbol] = (now + BACKOFF_SECONDS, str(exc))
            return self._degraded(cached, now, str(exc))
        self._polygon_memory[symbol] = (now, rows)
        self._polygon_quiet_until.pop(symbol, None)
        self._save(symbol, now, rows)
        return rows, status(POLYGON, "ok", now, now)

    def _degraded(self, cached, now: float, why: str) -> tuple[list[dict] | None, dict]:
        if cached:
            return cached[1], status(POLYGON, "stale", cached[0], now, f"{why} Showing the copy from the last read.")
        return None, status(POLYGON, "failed", None, now, why)

    def _call(self, symbol: str, now: float) -> dict:
        """One Polygon read, never retried. Raises ``SourceError`` with the reason."""
        limiter = enricher._limiter
        delay = limiter.reserve_within(MAX_WAIT_SECONDS)
        if delay is None:
            raise SourceError("Polygon is busy with fill enrichment; its budget is shared.")
        if delay > 0:
            observed_sleep("Polygon", "rate_limit", delay)
        since = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
        params = {"ticker": symbol, "limit": 50, "order": "desc", "sort": "published_utc",
                  "published_utc.gte": since, "apiKey": enricher.POLYGON_API_KEY}
        try:
            response = httpx.get(URL, params=params, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise SourceError(f"Polygon news could not be read ({type(exc).__name__}).") from None
        if response.status_code == 429:
            limiter.note_refusal(enricher._retry_after_seconds(response.headers))
            raise SourceError("Polygon refused the read (429, the free plan allows 5 a minute).")
        if response.status_code != 200:
            raise SourceError(f"Polygon news could not be read ({response.status_code}).")
        limiter.note_success()
        try:
            return response.json()
        except ValueError:
            raise SourceError("Polygon news came back unreadable.") from None


def status(provider: str, state: str, fetched_at: float | None, now: float, message: str | None = None) -> dict:
    """``state``: ok, stale (an older copy is shown), failed, or not_configured."""
    return {"provider": provider, "label": LABELS[provider], "state": state, "fetched_at": fetched_at,
            "age_seconds": None if fetched_at is None else max(0, int(now - fetched_at)), "message": message}


symbol_news = SymbolNews()

