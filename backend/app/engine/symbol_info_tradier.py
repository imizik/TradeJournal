"""Tradier fundamentals for the Events tab (T1.4) and the chart's earnings (C2.5).

Three beta endpoints, each batched with ``symbols=``: corporate calendars
(earnings), dividends and corporate actions (splits). Only normalized rows are
kept, in memory and on disk under ``backend/data/symbol_info/v1/tradier/``, for
12 hours (calendar) or 24 (dividends, splits), so a restart reuses them. A
failed read keeps serving the older copy with its age. These reads share the
Tradier token with the chart feed, so they have their own budget of 10 a minute
and never touch the chart feed's cooldowns.

The chart never waits for them: ``chart_earnings`` answers from the cache and
refreshes stale symbols, the watchlist's included, on a background thread in
one batched call. The Events tab's own request waits, for its one symbol.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import json
import logging
from pathlib import Path
import threading
import time
from uuid import uuid4

import httpx

from app.engine import tradier
from app.engine.symbol_info_events import (REPORTS_SHOWN, dividends_view, earnings_view, parse_dividends, parse_earnings,
                                           parse_splits, splits_view)
from app.engine import symbol_info_overview

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_info" / "v1" / "tradier"
SCHEMA = 1
PER_MINUTE = 10
BATCH = 10  # symbols per request; one company's calendar is up to about 50 KB
RETRY_SECONDS = 60
TIMEOUT_SECONDS = 10
NOT_CONFIGURED = "Set TRADIER_API_KEY on the private backend to read events."
TIME_NOTE = "Time of day not published. Tradier's calendar has dates only, so before the open or after the close is unknown."
# dataset: (path, normalizer, cache seconds, source label)
DATASETS: dict[str, tuple[str, Callable, int, str]] = {
    "calendars": ("/beta/markets/fundamentals/calendars", parse_earnings, 12 * 3600, "Tradier corporate calendar"),
    "dividends": ("/beta/markets/fundamentals/dividends", parse_dividends, 24 * 3600, "Tradier dividends"),
    "corporate_actions": ("/beta/markets/fundamentals/corporate_actions", parse_splits, 24 * 3600, "Tradier corporate actions"),
    "company": ("/beta/markets/fundamentals/company", symbol_info_overview.normalize_company, 24 * 3600, "Tradier company fundamentals"),
    "ratios": ("/beta/markets/fundamentals/ratios", symbol_info_overview.normalize_ratios, 24 * 3600, "Tradier company fundamentals"),
    "statistics": ("/beta/markets/fundamentals/statistics", symbol_info_overview.normalize_statistics, 24 * 3600, "Tradier company fundamentals"),
}
EVENT_DATASETS = ("calendars", "dividends", "corporate_actions")
OVERVIEW_DATASETS = ("company", "ratios", "statistics")


class SymbolEventsError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    fetched_at: float
    rows: list[dict]


class SymbolEvents:
    def __init__(self, root: Path = CACHE_DIR, clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None):
        self.root = root
        self._clock = clock
        self._spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True, name="symbol-events").start())
        self._lock = threading.Lock()  # guards the state below
        self._fetching = threading.Lock()  # one provider read at a time; a waiter reuses its result
        self._entries: dict[tuple[str, str], Entry] = {}
        self._absent: set[tuple[str, str]] = set()  # looked on disk, nothing there
        self._calls: deque[float] = deque()
        self._retry: dict[str, tuple[float, str]] = {}  # dataset: (until, why)
        self._refreshing = False

    # ------------------------------------------------------------------ public

    def chart_earnings(self, wanted: list[str], watchlist: list[str], today: date) -> dict[str, dict]:
        """Each wanted symbol's earnings for the chart, from the cache only, with
        every past report for markers. Stale symbols refresh in the background."""
        stale = [s for s in dict.fromkeys([*wanted, *watchlist]) if self._stale("calendars", s)]
        if stale and tradier.tradier_configured() and not self._cooling("calendars"):
            with self._lock:
                start, self._refreshing = not self._refreshing, True
            if start:
                try:
                    self._spawn(lambda: self._background(stale))
                except RuntimeError:
                    with self._lock:
                        self._refreshing = False
        return {symbol: self._earnings(symbol, today, None, None) for symbol in wanted}

    def forecast_earnings(self, symbol: str, today: date) -> dict:
        """The active symbol's earnings history for Forecast, with an independent calendar status."""
        issue = self.refresh("calendars", [symbol])
        entry, meta = self._block("calendars", symbol, issue)
        return {**meta, **earnings_view(entry.rows if entry else [], today, None)}

    def events(self, symbol: str, today: date) -> dict:
        """Everything the Events tab shows for one symbol. Each block degrades on its own."""
        issues = {dataset: self.refresh(dataset, [symbol]) for dataset in EVENT_DATASETS}
        dividends, dividend_meta = self._block("dividends", symbol, issues["dividends"])
        splits, split_meta = self._block("corporate_actions", symbol, issues["corporate_actions"])
        return {
            "symbol": symbol, "today": today.isoformat(), "time_zone": "America/New_York",
            "earnings": {**self._earnings(symbol, today, REPORTS_SHOWN, issues["calendars"]), "time_note": TIME_NOTE},
            "dividends": {**dividend_meta, **dividends_view(dividends.rows if dividends else [], today)},
            "splits": {**split_meta, "rows": splits_view(splits.rows if splits else [], today)},
        }

    def overview(self, symbol: str) -> dict:
        """Tradier company facts, with independent 24-hour caches per dataset."""
        datasets = {}
        for dataset in OVERVIEW_DATASETS:
            issue = self.refresh(dataset, [symbol])
            entry, meta = self._block(dataset, symbol, issue)
            values = entry.rows[0] if entry and entry.rows else {}
            datasets[dataset] = {**meta, **values}
        has_data = any(block["state"] == "ready" for block in datasets.values())
        return {"symbol": symbol, "state": "ready" if has_data else "none" if all(block["state"] == "none" for block in datasets.values()) else "unavailable",
                "datasets": datasets}

    def refresh(self, dataset: str, symbols: list[str]) -> str | None:
        """Read the stale ones among ``symbols``. Returns why it could not, or None."""
        with self._fetching:
            wanted = [s for s in symbols if self._stale(dataset, s)]  # another caller may have just read them
            if not wanted:
                return None
            if issue := self._cooling(dataset):
                return issue
            for start in range(0, len(wanted), BATCH):
                chunk = wanted[start:start + BATCH]
                try:
                    found = self._read(dataset, chunk)
                except SymbolEventsError as exc:
                    with self._lock:
                        self._retry[dataset] = (self._clock() + RETRY_SECONDS, str(exc))
                    return str(exc)
                fetched = self._clock()
                for symbol in chunk:
                    # A symbol Tradier answers without rows (an ETF's calendar) is cached as none.
                    self._store(dataset, symbol, Entry(fetched, found.get(symbol, [])))
            return None

    # ------------------------------------------------------------------ blocks

    def _earnings(self, symbol: str, today: date, reports: int | None, issue: str | None) -> dict:
        entry, meta = self._block("calendars", symbol, issue)
        return {**meta, **earnings_view(entry.rows if entry else [], today, reports)}

    def _block(self, dataset: str, symbol: str, issue: str | None) -> tuple[Entry | None, dict]:
        entry = self._entry(dataset, symbol)
        # A failure, even for another symbol, is news only where it leaves this one missing or old.
        if entry is None or self._stale(dataset, symbol):
            issue = issue or self._cooling(dataset) or (None if tradier.tradier_configured() else NOT_CONFIGURED)
        else:
            issue = None
        state = ("unavailable" if issue else "loading") if entry is None else "ready" if entry.rows else "unavailable" if issue else "none"
        return entry, {"state": state, "source": DATASETS[dataset][3], "fetched_at": int(entry.fetched_at) if entry else None,
                       "message": issue}

    def _background(self, symbols: list[str]) -> None:
        try:
            self.refresh("calendars", symbols)
        except Exception:  # a background thread has no caller to tell
            log.exception("Earnings calendar refresh failed")
        finally:
            with self._lock:
                self._refreshing = False

    # ------------------------------------------------------------------ cache

    def _stale(self, dataset: str, symbol: str) -> bool:
        entry = self._entry(dataset, symbol)
        return entry is None or self._clock() - entry.fetched_at >= DATASETS[dataset][2]

    def _cooling(self, dataset: str) -> str | None:
        with self._lock:
            until, why = self._retry.get(dataset, (0.0, ""))
        return why if self._clock() < until else None

    def _entry(self, dataset: str, symbol: str) -> Entry | None:
        key = (dataset, symbol)
        with self._lock:
            if key in self._entries or key in self._absent:
                return self._entries.get(key)
        entry = self._load(dataset, symbol)
        with self._lock:
            if entry is None:
                self._absent.add(key)
                return None
            return self._entries.setdefault(key, entry)

    def _path(self, dataset: str, symbol: str) -> Path:
        return self.root / dataset / f"{symbol.replace('/', '_')}.json"

    def _load(self, dataset: str, symbol: str) -> Entry | None:
        try:
            data = json.loads(self._path(dataset, symbol).read_text())
            if (data.get("schema"), data.get("provider"), data.get("dataset"), data.get("symbol")) != (SCHEMA, "tradier", dataset, symbol):
                return None
            fetched, rows = float(data["fetched_at"]), data["rows"]
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                return None
            return Entry(fetched, rows)
        except (OSError, KeyError, TypeError, ValueError, AttributeError):
            return None  # missing or damaged: read again from Tradier

    def _store(self, dataset: str, symbol: str, entry: Entry) -> None:
        with self._lock:
            self._entries[(dataset, symbol)] = entry
            self._absent.discard((dataset, symbol))
        path = self._path(dataset, symbol)
        record = {"schema": SCHEMA, "provider": "tradier", "dataset": dataset, "symbol": symbol,
                  "fetched_at": entry.fetched_at, "rows": entry.rows}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(record, separators=(",", ":")))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass  # memory still holds it; a restart reads Tradier again

    # --------------------------------------------------------------- provider

    def _read(self, dataset: str, symbols: list[str]) -> dict[str, list[dict]]:
        if not tradier.tradier_configured():
            raise SymbolEventsError(NOT_CONFIGURED)
        path, parse, _, label = DATASETS[dataset]
        with self._lock:
            now = self._clock()
            while self._calls and self._calls[0] <= now - 60:
                self._calls.popleft()
            if len(self._calls) >= PER_MINUTE:
                raise SymbolEventsError("Symbol info is pacing its Tradier reads to leave room for the charts. Retrying in a minute.")
            self._calls.append(now)
        try:
            response = httpx.get(f"{tradier.TRADIER_BASE_URL}{path}", params={"symbols": ",".join(symbols)},
                                 headers={"Authorization": f"Bearer {tradier.TRADIER_API_KEY}", "Accept": "application/json"},
                                 timeout=TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise SymbolEventsError(f"The Tradier connection failed while reading the {label.removeprefix('Tradier ')}.") from exc
        if response.status_code == 429:
            raise SymbolEventsError("Tradier's data allowance is exhausted. Retrying in a minute.")
        if response.status_code in (401, 403):
            raise SymbolEventsError("Tradier refused fundamentals data. Check the token and the account's market-data access.")
        if response.status_code >= 400:
            raise SymbolEventsError(f"Tradier could not read the {label.removeprefix('Tradier ')} ({response.status_code}).")
        try:
            return parse(response.json())
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SymbolEventsError(f"Tradier returned an unreadable {label.removeprefix('Tradier ')} response.") from exc


symbol_events = SymbolEvents()
