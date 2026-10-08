"""Fetching and caching for the Short & borrow block (T3.1).

* Polygon ``short-interest``, ``short-volume`` and ticker details (shares outstanding),
  each cached one day per symbol on disk under ``backend/data/symbol_info/v1/polygon/``.
  The free plan is 5 calls a minute shared with fill enrichment, so a read goes through
  the enricher's adaptive limiter exactly as the News tab's Polygon feed does: it never
  waits more than ``MAX_WAIT_SECONDS`` for a slot, is never retried, and on a 429, any
  failure or a busy limiter serves the cached copy with its age and stays quiet for
  ``BACKOFF_SECONDS``. A 429 or busy limiter quiets every Polygon dataset, since the
  budget is shared.
* Tradier ``/v1/markets/etb`` (the easy-to-borrow list), one call a day, cached on disk
  under ``.../tradier/``. It has its own back-off (``RETRY_SECONDS``) and never touches
  the chart feed's cooldowns.

Normalizing is in ``symbol_info_short``; this module only moves bytes.
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

from app.engine import enricher, tradier
from app.engine.api_wait import observed_sleep
from app.engine.symbol_info_short import (hard_to_borrow, interest_view, normalize_details, normalize_etb,
                                          normalize_short_interest, normalize_short_volume, volume_view)

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_info" / "v1"
SCHEMA = 1
FRESH_SECONDS = 24 * 3600
BACKOFF_SECONDS = 5 * 60  # after a Polygon failure, no new call for this long
RETRY_SECONDS = 60  # after a Tradier failure
MAX_WAIT_SECONDS = 2.0  # a limiter slot further out than this is "busy": serve the cache
TIMEOUT_SECONDS = 10
POLYGON = "Polygon"
TRADIER = "Tradier"
INTEREST_SOURCE = "Polygon (FINRA short interest)"
VOLUME_SOURCE = "Polygon (FINRA daily short volume)"
BORROW_SOURCE = "Tradier easy-to-borrow list"
POLYGON_URL = "https://api.polygon.io"
# dataset: (provider, path, params, normalizer)
POLYGON_DATASETS: dict[str, tuple[str, dict, Callable]] = {
    "short_interest": ("/stocks/v1/short-interest", {"limit": 2, "sort": "settlement_date.desc"}, normalize_short_interest),
    "short_volume": ("/stocks/v1/short-volume", {"limit": 10, "sort": "date.desc"}, normalize_short_volume),
    "details": ("/v3/reference/tickers/{symbol}", {}, normalize_details),
}


def polygon_ticker(symbol: str) -> str:
    """Polygon writes class shares with a dot (BRK.B); the chart accepts BRK/B."""
    return symbol.replace("/", ".")


class SourceError(Exception):
    def __init__(self, message: str, shared: bool = False):
        super().__init__(message)
        self.shared = shared  # true when every Polygon read should wait, not just this one


class ShortFeed:
    def __init__(self, root: Path = DATA_DIR, clock: Callable[[], float] = time.time):
        self.root = root
        self._clock = clock
        self._memory: dict[tuple[str, str], tuple[float, list]] = {}
        self._quiet: dict[str, tuple[float, str]] = {}
        self._fetching = threading.Lock()  # one read at a time; a waiter reuses the fresh copy

    # ------------------------------------------------------------------ public

    def view(self, symbol: str) -> dict:
        with self._fetching:
            now = self._clock()
            interest = self._polygon("short_interest", symbol, now)
            volume = self._polygon("short_volume", symbol, now)
            # Shares outstanding only matter when there is a short-interest row to divide.
            details = self._polygon("details", symbol, now) if interest["rows"] else None
            etb = self._etb(now)
        borrow = self._borrow_block(symbol, etb)
        interest_out = self._wrap(interest, INTEREST_SOURCE, f"No FINRA short interest is published for {symbol}.")
        if interest["rows"]:
            interest_out.update(interest_view(interest["rows"], details["rows"] if details else []))
            if interest_out["shares_outstanding"] is None:
                interest_out["pct_message"] = "Shares outstanding unavailable, so the percentage is omitted."
            elif details and details["stale"]:
                interest_out["pct_message"] = f"Shares outstanding is an older copy. {details['message']}"
        volume_out = self._wrap(volume, VOLUME_SOURCE, f"No FINRA short-volume rows are published for {symbol}.")
        if volume["rows"]:
            volume_out.update(volume_view(volume["rows"]))
        blocks = (interest_out, volume_out)
        state = "ready" if any(b["state"] == "ready" for b in blocks) else "none" if all(b["state"] == "none" for b in blocks) else "unavailable"
        return {"symbol": symbol, "as_of": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "time_zone": "America/New_York", "state": state, "interest": interest_out, "volume": volume_out, "borrow": borrow}

    # ------------------------------------------------------------------ blocks

    @staticmethod
    def _wrap(block: dict, source: str, none: str) -> dict:
        state = "ready" if block["rows"] else "unavailable" if block["state"] == "unavailable" else "none"
        return {"state": state, "source": source, "fetched_at": block["fetched_at"], "age_seconds": block["age_seconds"],
                "stale": block["stale"], "message": block["message"] if state == "unavailable" or block["stale"] else None,
                "none_message": none if state == "none" else None}

    def _borrow_block(self, symbol: str, etb: dict) -> dict:
        out = {"source": BORROW_SOURCE, "fetched_at": etb["fetched_at"], "age_seconds": etb["age_seconds"], "stale": etb["stale"],
               "message": etb["message"] if etb["state"] == "unavailable" or etb["stale"] else None}
        if not etb["rows"]:
            return {**out, "state": "unavailable", "hard_to_borrow": None,
                    "message": etb["message"] or "Tradier's easy-to-borrow list is unavailable."}
        flag = hard_to_borrow(symbol, etb["rows"])
        return {**out, "state": "ready", "hard_to_borrow": flag, "list_size": len(etb["rows"]),
                "note": ("Missing from Tradier's easy-to-borrow list, which brokers use to decide where shares can be borrowed to short. "
                         "Expect higher borrow fees or no shares to short." if flag else
                         "On Tradier's easy-to-borrow list.")}

    # ------------------------------------------------------------------ cache

    def _path(self, provider: str, dataset: str, symbol: str | None) -> Path:
        name = dataset if symbol is None else f"{dataset}-{re.sub(r'[^A-Z0-9]+', '_', symbol)}"
        return self.root / provider / f"{name}.json"

    def _load(self, provider: str, dataset: str, symbol: str | None) -> tuple[float, list] | None:
        key = (dataset, symbol or "")
        if key in self._memory:
            return self._memory[key]
        try:
            body = json.loads(self._path(provider, dataset, symbol).read_text())
            if body.get("schema") == SCHEMA and isinstance(body.get("rows"), list):
                self._memory[key] = (float(body["fetched_at"]), body["rows"])
                return self._memory[key]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _save(self, provider: str, dataset: str, symbol: str | None, fetched_at: float, rows: list) -> None:
        self._memory[(dataset, symbol or "")] = (fetched_at, rows)
        try:
            path = self._path(provider, dataset, symbol)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{uuid4().hex}")
            temp.write_text(json.dumps({"schema": SCHEMA, "fetched_at": fetched_at, "rows": rows}, separators=(",", ":")))
            temp.replace(path)
        except OSError as exc:
            log.warning("Could not cache %s %s for %s: %s", provider, dataset, symbol, exc)

    # --------------------------------------------------------------- one read

    def _block(self, provider: str, dataset: str, symbol: str | None, now: float, quiet_keys: list[str],
               configured: bool, missing: str, read: Callable[[], list]) -> dict:
        cached = self._load(provider, dataset, symbol)
        if cached and now - cached[0] < FRESH_SECONDS:
            return self._answer(cached, now, None, False)
        for key in quiet_keys:
            quiet = self._quiet.get(key)
            if quiet and now < quiet[0]:
                return self._answer(cached, now, quiet[1], True)
        if not configured:
            return self._answer(cached, now, missing, True)
        try:
            rows = read()
        except SourceError as exc:
            self._quiet[quiet_keys[0] if exc.shared else quiet_keys[-1]] = (now + (BACKOFF_SECONDS if provider == "polygon" else RETRY_SECONDS), str(exc))
            return self._answer(cached, now, str(exc), True)
        self._quiet.pop(quiet_keys[-1], None)
        self._save(provider, dataset, symbol, now, rows)
        return self._answer((now, rows), now, None, False)

    @staticmethod
    def _answer(cached, now: float, why: str | None, failed: bool) -> dict:
        if cached is None:
            return {"rows": [], "state": "unavailable", "fetched_at": None, "age_seconds": None, "stale": False, "message": why}
        age = max(0, int(now - cached[0]))
        stale = failed
        return {"rows": cached[1], "state": "ready", "fetched_at": cached[0], "age_seconds": age, "stale": stale,
                "message": f"{why} Showing the copy from the last read." if stale else None}

    def _polygon(self, dataset: str, symbol: str, now: float) -> dict:
        path, params, parse = POLYGON_DATASETS[dataset]
        block = self._block("polygon", dataset, symbol, now, ["polygon", f"{dataset}:{symbol}"], bool(enricher.POLYGON_API_KEY),
                            "Set POLYGON_API_KEY on the private backend to read short interest.",
                            lambda: parse(self._call(path.format(symbol=polygon_ticker(symbol)), {**params, **({"ticker": polygon_ticker(symbol)} if "{symbol}" not in path else {})})))
        if block["state"] == "ready" and not block["rows"]:
            block["state"] = "none"
        return block

    def _call(self, path: str, params: dict) -> dict:
        """One Polygon read, never retried. Raises ``SourceError`` with the reason."""
        limiter = enricher._limiter
        delay = limiter.reserve_within(MAX_WAIT_SECONDS)
        if delay is None:
            raise SourceError("Polygon is busy with fill enrichment; its budget is shared.", shared=True)
        if delay > 0:
            observed_sleep("Polygon", "rate_limit", delay)
        try:
            response = httpx.get(f"{POLYGON_URL}{path}", params={**params, "apiKey": enricher.POLYGON_API_KEY}, timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise SourceError(f"Polygon could not be read ({type(exc).__name__}).") from None
        if response.status_code == 429:
            limiter.note_refusal(enricher._retry_after_seconds(response.headers))
            raise SourceError("Polygon refused the read (429, the free plan allows 5 a minute).", shared=True)
        if response.status_code in (401, 403):
            raise SourceError("Polygon refused this data on the current plan.")
        if response.status_code != 200:
            raise SourceError(f"Polygon could not be read ({response.status_code}).")
        limiter.note_success()
        try:
            return response.json()
        except ValueError:
            raise SourceError("Polygon returned an unreadable response.") from None

    # ----------------------------------------------------------------- tradier

    def _etb(self, now: float) -> dict:
        return self._block("tradier", "etb", None, now, ["etb"], tradier.tradier_configured(),
                           "Set TRADIER_API_KEY on the private backend to read the borrow list.", self._read_etb)

    @staticmethod
    def _read_etb() -> list:
        try:
            response = httpx.get(f"{tradier.TRADIER_BASE_URL}/v1/markets/etb", timeout=TIMEOUT_SECONDS,
                                 headers={"Authorization": f"Bearer {tradier.TRADIER_API_KEY}", "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise SourceError(f"The Tradier connection failed while reading the borrow list ({type(exc).__name__}).") from None
        if response.status_code == 429:
            raise SourceError("Tradier's data allowance is exhausted. Retrying in a minute.")
        if response.status_code in (401, 403):
            raise SourceError("Tradier refused the borrow list. Check the token's access.")
        if response.status_code != 200:
            raise SourceError(f"Tradier could not read the borrow list ({response.status_code}).")
        try:
            return normalize_etb(response.json())
        except (ValueError, TypeError, AttributeError):
            raise SourceError("Tradier returned an unreadable borrow list.") from None


short_feed = ShortFeed()
