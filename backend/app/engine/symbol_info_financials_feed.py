"""SEC EDGAR reads for the Financials tab (T3.2), cached on disk.

Two reads, both free and keyless but requiring a descriptive ``User-Agent``
(``SEC_USER_AGENT``; www.sec.gov answers 403 without a contact in it):

- ``www.sec.gov/files/company_tickers.json``: ticker to CIK, cached seven days.
- ``data.sec.gov/api/xbrl/companyfacts/CIK##########.json``: about 4 MB for a
  large filer. Only the normalized quarters are cached, never this payload,
  under ``backend/data/symbol_info/v1/sec/``.

A symbol stays fresh until the next 10-Q is due (latest quarter end + 105 days,
at least a day), then is checked daily. A failed read serves the cached copy
with its age and is not retried for five minutes.
"""

from collections.abc import Callable
from datetime import date, datetime, time as clock_time, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

import httpx

from app.engine import symbol_info_financials as financials

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_info" / "v1" / "sec"
SCHEMA = 1
SOURCE = "SEC EDGAR"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DEFAULT_USER_AGENT = "TradeJournal personal-research app"
TICKER_TTL = 7 * 24 * 3600
DAY = 24 * 3600
FILING_DUE_DAYS = 105  # next quarter end + two weeks, before the earliest 10-Q; then daily
RETRY_SECONDS = 300
MIN_INTERVAL = 0.2  # five requests a second at most, half of SEC's 10
TICKERS_KEY = "_tickers"
TICKERS_FILE = "_tickers.json"
NOT_AVAILABLE ="Not available for ETFs or funds."
UA_HINT = "SEC refused the request. Set SEC_USER_AGENT on the server to a name and contact email, for example \"TradeJournal you@example.com\"."


class ProviderError(Exception):
    pass


class NotFound(Exception):
    pass


def user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "").strip() or DEFAULT_USER_AGENT


class Pacer:
    def __init__(self, interval: float = MIN_INTERVAL):
        self._interval, self._next, self._lock = interval, 0.0, threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if delay:
            time.sleep(delay)


_pacer = Pacer()


def http_json(url: str):
    """GET ``url`` as JSON. Raises ``NotFound`` for 404 and ``ProviderError`` for everything else."""
    _pacer.wait()
    try:
        response = httpx.get(url, headers={"User-Agent": user_agent(), "Accept": "application/json"}, timeout=30, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise ProviderError("SEC EDGAR could not be reached.") from exc
    if response.status_code == 404:
        raise NotFound(url)
    if response.status_code == 403:
        raise ProviderError(UA_HINT)
    if response.status_code == 429:
        raise ProviderError("SEC EDGAR is rate limiting this server.")
    if response.status_code != 200:
        raise ProviderError(f"SEC EDGAR answered {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("SEC EDGAR returned an unreadable answer.") from exc


def sec_ticker(symbol: str) -> str:
    return symbol.upper().replace(".", "-").replace("/", "-")  # SEC writes share classes as BRK-B


def expires_at(entry: dict, fetched_at: float) -> float:
    """When a cached symbol is checked again: not before the next filing is due, then daily."""
    latest = entry.get("latest_end")
    due = None
    if latest:
        try:
            end = date.fromisoformat(latest)
            due = datetime.combine(end, clock_time.min, timezone.utc).timestamp() + FILING_DUE_DAYS * DAY
        except ValueError:
            pass
    daily = fetched_at + DAY
    return max(daily, due) if due and fetched_at < due else daily


class SymbolFinancials:
    def __init__(self, root: Path = CACHE_DIR, clock: Callable[[], float] = time.time, get: Callable[[str], object] = http_json):
        self.root = root
        self._clock = clock
        self._get = get
        self._lock = threading.Lock()
        self._fetching: dict[str, threading.Lock] = {}
        self._entries: dict[str, tuple[float, dict]] = {}
        self._retry: dict[str, tuple[float, str]] = {}
        self._tickers: tuple[float, dict[str, int]] | None = None

    # --- ticker to CIK ---------------------------------------------------
    def _cik(self, symbol: str) -> int | None:
        now = self._clock()
        with self._lock:
            tickers = self._tickers
        if tickers is None:
            tickers = self._load_tickers()
            with self._lock:
                self._tickers = tickers
        if tickers is None or now - tickers[0] >= TICKER_TTL:
            with self._lock:
                until, why = self._retry.get(TICKERS_KEY, (0.0, ""))
            if now < until:
                if tickers is None:
                    raise ProviderError(why)
            else:
                try:
                    tickers = (now, self._fetch_tickers())
                except ProviderError as exc:
                    with self._lock:
                        self._retry[TICKERS_KEY] = (now + RETRY_SECONDS, str(exc))
                    if tickers is None:
                        raise
                else:
                    with self._lock:
                        self._tickers = tickers
                        self._retry.pop(TICKERS_KEY, None)
                    self._write(self.root / TICKERS_FILE, {"schema": SCHEMA, "fetched_at": now, "data": tickers[1]})
        return tickers[1].get(sec_ticker(symbol))

    def _fetch_tickers(self) -> dict[str, int]:
        try:
            raw = self._get(TICKERS_URL)
        except NotFound as exc:
            raise ProviderError("SEC EDGAR's ticker list was not found.") from exc
        mapping: dict[str, int] = {}
        for row in (raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []):
            if isinstance(row, dict) and isinstance(row.get("cik_str"), int) and row.get("ticker"):
                mapping.setdefault(str(row["ticker"]).upper(), row["cik_str"])
        if not mapping:
            raise ProviderError("SEC EDGAR returned an empty ticker list.")
        return mapping

    def _load_tickers(self):
        try:
            record = json.loads((self.root / TICKERS_FILE).read_text())
            if record.get("schema") == SCHEMA:
                return float(record["fetched_at"]), {k: int(v) for k, v in record["data"].items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        return None

    # --- per-symbol view ---------------------------------------------------
    def view(self, symbol: str) -> dict:
        with self._lock:
            lock = self._fetching.setdefault(symbol, threading.Lock())
        with lock:
            entry = self._entry(symbol)
            now = self._clock()
            if entry and now < expires_at(entry[1], entry[0]):
                return self._out(symbol, entry, None)
            with self._lock:
                until, why = self._retry.get(symbol, (0.0, ""))
            if now < until:
                return self._out(symbol, entry, why)
            try:
                data = self._read(symbol)
            except ProviderError as exc:
                why = str(exc)
            except Exception:
                log.exception("SEC financials failed for %s", symbol)
                why = "SEC financials could not be read."
            else:
                entry = (now, data)
                self._store(symbol, entry)
                with self._lock:
                    self._retry.pop(symbol, None)
                return self._out(symbol, entry, None)
            with self._lock:
                self._retry[symbol] = (now + RETRY_SECONDS, why)
            return self._out(symbol, entry, why)

    def _read(self, symbol: str) -> dict:
        cik = self._cik(symbol)
        if cik is None:
            return {"state": "none", "message": NOT_AVAILABLE}
        try:
            document = self._get(FACTS_URL.format(cik=cik))
        except NotFound:
            return {"state": "none", "message": NOT_AVAILABLE}
        if not isinstance(document, dict):
            raise ProviderError("SEC EDGAR returned an unreadable answer.")
        if not financials.has_quarterly_facts(document):
            return {"state": "none", "message": financials.NO_QUARTERS, "entity": document.get("entityName")}
        return {"state": "ready", "message": None, "entity": document.get("entityName"), **financials.normalize(document)}

    def _out(self, symbol: str, entry: tuple[float, dict] | None, why: str | None) -> dict:
        base = {"symbol": symbol, "source": SOURCE, "quarters": [], "latest_end": None, "entity": None}
        if entry is None:
            return {**base, "state": "unavailable", "message": why or "SEC financials are loading.", "fetched_at": None, "stale": False}
        fetched_at, data = entry
        message = data.get("message")
        if why and data.get("state") == "ready":
            message = f"{why} Showing the cached copy from {self._age(fetched_at)} ago."
        return {**base, **data, "fetched_at": int(fetched_at), "stale": bool(why), "message": message}

    def _age(self, fetched_at: float) -> str:
        seconds = max(0, int(self._clock() - fetched_at))
        return f"{seconds // DAY} days" if seconds >= DAY else f"{max(1, seconds // 3600)} hours" if seconds >= 3600 else f"{max(1, seconds // 60)} minutes"

    # --- disk -------------------------------------------------------------
    def _path(self, symbol: str) -> Path:
        return self.root / f"{symbol.replace('/', '_')}.json"

    def _entry(self, symbol: str):
        with self._lock:
            if symbol in self._entries:
                return self._entries[symbol]
        try:
            record = json.loads(self._path(symbol).read_text())
            entry = (float(record["fetched_at"]), record["data"]) if record.get("schema") == SCHEMA else None
        except (OSError, ValueError, KeyError, TypeError):
            entry = None
        if entry:
            with self._lock:
                self._entries[symbol] = entry
        return entry

    def _store(self, symbol: str, entry) -> None:
        with self._lock:
            self._entries[symbol] = entry
        self._write(self._path(symbol), {"schema": SCHEMA, "fetched_at": entry[0], "data": entry[1]})

    def _write(self, path: Path, record: dict) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(record, separators=(",", ":")))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass  # memory still holds it


symbol_financials = SymbolFinancials()
