"""Insider buying and selling for the Overview tab's Ownership section (T3.3).

Source: Yahoo via ``yfinance`` ``Ticker.insider_transactions`` (unofficial). A day's
read is cached per symbol in memory and on disk under
``backend/data/symbol_info/v1/insiders/``; a failed read keeps serving the older
copy with its age and is not retried for five minutes.

Yahoo's ``Transaction`` column is empty; the kind of transaction is in ``Text``
(recorded 2026-10-08 for NVDA, NBIS, TSLA and eight more symbols): "Sale at price
...", "Purchase at price ...", "Stock Award(Grant)", "Stock Gift", "Conversion of
Exercise of derivative security", or blank. Only "Sale" and "Purchase" rows count
as selling and buying. Awards, gifts, exercises and blank rows are shown as
excluded in a count, never as a buy or a sell.

The window is by transaction date (``Start Date``), 90 calendar days ending today.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
import json
import logging
import math
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "symbol_info" / "v1" / "insiders"
SCHEMA = 1
TTL_SECONDS = 24 * 3600
RETRY_SECONDS = 300
WINDOW_DAYS = 90
KEEP_DAYS = 120  # the cache holds a little more than the window so a day-old copy still covers it
LATEST_SHOWN = 5
SOURCE = "Yahoo, unofficial"
NOTE = "Counts open-market purchases and sales only. Awards, gifts and option exercises are excluded."


class ProviderError(Exception):
    pass


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _day(value) -> str | None:
    try:
        return value.date().isoformat()
    except AttributeError:
        text = str(value or "")[:10]
        return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None


def _records(frame) -> list[dict]:
    if frame is None:
        return []
    try:
        return frame.reset_index().to_dict("records")
    except AttributeError:
        return [row for row in frame if isinstance(row, dict)] if isinstance(frame, list) else []


def classify(text) -> str:
    """"buy" and "sell" only for Yahoo's open-market Purchase and Sale rows; everything else is "other"."""
    head = str(text or "").strip().lower()
    if re.match(r"purchase\b", head):
        return "buy"
    if re.match(r"sale\b", head):
        return "sell"
    return "other"


def normalize(frame, today: date) -> list[dict]:
    """Yahoo's frame (or its records) into dated, classified rows from the last ``KEEP_DAYS``, newest first."""
    floor = (today - timedelta(days=KEEP_DAYS)).isoformat()
    rows = []
    for row in _records(frame):
        when = _day(row.get("Start Date"))
        shares = _number(row.get("Shares"))
        if not when or when < floor or shares is None or shares < 0:
            continue
        value = _number(row.get("Value"))
        rows.append({"date": when, "insider": str(row.get("Insider") or "").strip() or None, "position": str(row.get("Position") or "").strip() or None,
                     "kind": classify(row.get("Text")), "shares": shares, "value": value if value and value > 0 else None})
    return sorted(rows, key=lambda r: r["date"], reverse=True)


def summarize(rows: list[dict], today: date) -> dict:
    """The 90-day totals and the latest few counted transactions from ``normalize``'s rows."""
    since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    inside = [r for r in rows if since <= r["date"] <= today.isoformat()]
    counted = [r for r in inside if r["kind"] != "other"]
    totals = {}
    for kind in ("buy", "sell"):
        part = [r for r in counted if r["kind"] == kind]
        totals[kind] = {"count": len(part), "shares": sum(r["shares"] for r in part),
                        "value": sum(r["value"] or 0 for r in part), "unvalued": sum(1 for r in part if r["value"] is None)}
    unvalued = totals["buy"]["unvalued"] + totals["sell"]["unvalued"]
    return {"since": since, "until": today.isoformat(), "window_days": WINDOW_DAYS,
            "buys": {"count": totals["buy"]["count"], "shares": totals["buy"]["shares"]},
            "sells": {"count": totals["sell"]["count"], "shares": totals["sell"]["shares"]},
            "net_shares": totals["buy"]["shares"] - totals["sell"]["shares"],
            # A net dollar figure from some rows only would mislead, so it is blank when any counted row has no value.
            "net_value": totals["buy"]["value"] - totals["sell"]["value"] if counted and not unvalued else None,
            "excluded": len(inside) - len(counted), "note": NOTE,
            "latest": counted[:LATEST_SHOWN]}


def fetch_yahoo(symbol: str, today: date) -> list[dict]:
    import yfinance as yf  # imported late: it is slow to load
    try:
        frame = yf.Ticker(symbol.replace(".", "-").replace("/", "-")).insider_transactions  # Yahoo writes share classes as BRK-B
    except Exception as exc:  # yfinance raises many types
        raise ProviderError("Yahoo could not be read.") from exc
    return normalize(frame, today)


class SymbolInsiders:
    def __init__(self, root: Path = CACHE_DIR, clock: Callable[[], float] = time.time,
                 fetcher: Callable[[str, date], list[dict]] = fetch_yahoo, today: Callable[[], date] = lambda: datetime.now(ET).date()):
        self.root = root
        self._clock = clock
        self._fetcher = fetcher
        self._today = today
        self._lock = threading.Lock()
        self._fetching: dict[str, threading.Lock] = {}
        self._entries: dict[str, tuple[float, list[dict]]] = {}
        self._retry: dict[str, tuple[float, str]] = {}

    def view(self, symbol: str) -> dict:
        rows, fetched, message = self._read(symbol)
        base = {"symbol": symbol, "source": SOURCE, "fetched_at": int(fetched) if fetched else None, "message": message}
        if rows is None:
            return {**base, "state": "unavailable", "message": message}
        if not rows:
            return {**base, "state": "none", "message": message or "Yahoo lists no insider transactions for this symbol."}
        return {**base, "state": "ready", **summarize(rows, self._today())}

    def _read(self, symbol: str) -> tuple[list[dict] | None, float | None, str | None]:
        with self._lock:
            lock = self._fetching.setdefault(symbol, threading.Lock())
        with lock:  # one read per symbol; concurrent callers reuse its result
            entry = self._entry(symbol)
            now = self._clock()
            with self._lock:
                until, why = self._retry.get(symbol, (0.0, ""))
            if entry and now - entry[0] < TTL_SECONDS:
                return entry[1], entry[0], None
            if now < until:
                return (entry[1], entry[0], why) if entry else (None, None, why)
            try:
                rows = self._fetcher(symbol, self._today())
            except ProviderError as exc:
                why = str(exc)
            except Exception:
                log.exception("Insider read failed: %s", symbol)
                why = "Yahoo could not be read."
            else:
                self._store(symbol, (now, rows))
                with self._lock:
                    self._retry.pop(symbol, None)
                return rows, now, None
            with self._lock:
                self._retry[symbol] = (now + RETRY_SECONDS, why)
            return (entry[1], entry[0], why) if entry else (None, None, why)

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
        path = self._path(symbol)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps({"schema": SCHEMA, "fetched_at": entry[0], "data": entry[1]}, separators=(",", ":")))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass  # memory still holds it


symbol_insiders = SymbolInsiders()
