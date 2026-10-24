"""Radar premarket pilot: record-only lists of stocks already moving before the open.

Off unless ``RADAR_PREMARKET_ENABLED`` is true; it only runs inside an enabled Radar recorder. On an open
session day it scans once at each ``CHECKPOINTS`` time (08:50 and 09:20 New York): one batched Tradier quote
read for previous closes, then one 1-minute timesales read per tracked symbol through the shared chart feed (uncached),
paced to ``READS_PER_MINUTE`` and stopped at ``DEADLINE_MINUTES`` so the 09:20 scan ends before the regular
session. Only bars completed by the checkpoint count, so a slow scan reads the same minutes as a fast one.

Each scan and its per-symbol readings are written once to a separate SQLite file beside the Radar store
(``<store stem>-premarket.sqlite``) and never changed; the Radar store, its rules and its screen are untouched.
``PREMARKET_V0`` flags a stock whose premarket move differs from SPY's by at least 3 points, with at least
$250k traded premarket and a last trade at most 10 minutes before the checkpoint. The numbers are frozen for
the pilot (see ``docs/radar.md``). Nothing here alerts, trades, or reaches the screen.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable

from app.engine import tradier
from app.engine.chart_math import ET, normalize_bars, session_windows

RULE_VERSION = "radar-premarket-v0"
CHECKPOINTS = ((8, 50), (9, 20))
DEADLINE_MINUTES = 8
READS_PER_MINUTE = 40
BATCH_SIZE = 50
APPLICATION_ID = 0x52414450  # RADP: the premarket pilot file; foreign files are never adopted.
TABLES = {"premarket_scan", "premarket_reading"}


@dataclass(frozen=True)
class Rule:
    excess_pct: float  # |own premarket change - SPY premarket change|, points
    min_dollar_volume: float  # premarket shares x price, summed over completed minutes
    max_trade_age_minutes: int  # last completed bar before the checkpoint


PREMARKET_V0 = Rule(excess_pct=3.0, min_dollar_volume=250_000, max_trade_age_minutes=10)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS premarket_scan(id INTEGER PRIMARY KEY AUTOINCREMENT, session_date TEXT NOT NULL,
  checkpoint TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, rule_version TEXT NOT NULL,
  universe_version TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ok','partial','failed','skipped')),
  symbols_requested INTEGER NOT NULL, symbols_read INTEGER NOT NULL, symbols_with_bars INTEGER NOT NULL,
  requests_used INTEGER NOT NULL, flagged INTEGER NOT NULL, error TEXT, skip_reason TEXT,
  UNIQUE(session_date, checkpoint));
CREATE TABLE IF NOT EXISTS premarket_reading(scan_id INTEGER NOT NULL REFERENCES premarket_scan(id), symbol TEXT NOT NULL,
  prev_close REAL, quote_last REAL, quote_trade_ms INTEGER, last REAL, last_bar_at TEXT, bars INTEGER NOT NULL,
  volume INTEGER NOT NULL, dollar_volume REAL NOT NULL, change_pct REAL, excess_pct REAL, flagged INTEGER NOT NULL,
  read_error TEXT, PRIMARY KEY(scan_id, symbol));
CREATE TRIGGER IF NOT EXISTS premarket_scan_no_update BEFORE UPDATE ON premarket_scan BEGIN SELECT RAISE(ABORT,'premarket scans are immutable'); END;
CREATE TRIGGER IF NOT EXISTS premarket_scan_no_delete BEFORE DELETE ON premarket_scan BEGIN SELECT RAISE(ABORT,'premarket scans are immutable'); END;
CREATE TRIGGER IF NOT EXISTS premarket_reading_no_update BEFORE UPDATE ON premarket_reading BEGIN SELECT RAISE(ABORT,'premarket readings are immutable'); END;
CREATE TRIGGER IF NOT EXISTS premarket_reading_no_delete BEFORE DELETE ON premarket_reading BEGIN SELECT RAISE(ABORT,'premarket readings are immutable'); END;
"""

Read = Callable[..., tuple]  # chart_feed.read(path, params, ttl, keep=...)
Quotes = Callable[[list[str]], dict]


def enabled() -> bool:
    return os.environ.get("RADAR_PREMARKET_ENABLED", "false").lower() in ("1", "true", "yes")


def store_path(radar_store: str | Path) -> Path:
    path = Path(radar_store)
    return path.with_name(path.stem + "-premarket.sqlite")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class PremarketStore:
    """The pilot's own append-only SQLite file."""

    def __init__(self, path: str | Path, *, read_only: bool = False):
        self.path = Path(path)
        self.read_only = read_only
        if not self.path.is_absolute():
            raise ValueError("premarket store path must be absolute")
        if self.path.is_symlink():
            raise ValueError("premarket store may not be a symlink")
        if not read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            marker = db.execute("PRAGMA application_id").fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if marker == 0 and not tables and not read_only:
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            elif marker != APPLICATION_ID or not tables <= TABLES:
                raise ValueError("refusing to adopt a non-premarket database")
            if not read_only:
                db.executescript(_SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro" if self.read_only else self.path,
                             uri=self.read_only, timeout=10, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def has_scan(self, session_date: str, checkpoint: str) -> bool:
        with self._db() as db:
            return db.execute("SELECT 1 FROM premarket_scan WHERE session_date=? AND checkpoint=?",
                              (session_date, checkpoint)).fetchone() is not None

    def append_scan(self, scan: dict, readings: list[dict]) -> int:
        """One scan and its readings in one transaction; returns the scan id."""
        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO premarket_scan(session_date, checkpoint, started_at, finished_at, rule_version, universe_version,"
                " status, symbols_requested, symbols_read, symbols_with_bars, requests_used, flagged, error, skip_reason)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                tuple(scan[k] for k in ("session_date", "checkpoint", "started_at", "finished_at", "rule_version",
                                        "universe_version", "status", "symbols_requested", "symbols_read",
                                        "symbols_with_bars", "requests_used", "flagged", "error", "skip_reason")))
            scan_id = cursor.lastrowid
            db.executemany(
                "INSERT INTO premarket_reading VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(scan_id, r["symbol"], r["prev_close"], r["quote_last"], r["quote_trade_ms"], r["last"], r["last_bar_at"],
                  r["bars"], r["volume"], r["dollar_volume"], r["change_pct"], r["excess_pct"], int(r["flagged"]),
                  r["read_error"]) for r in readings])
        return scan_id

    def scans(self) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM premarket_scan ORDER BY session_date, checkpoint")]

    def readings(self, scan_id: int) -> list[dict]:
        with self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM premarket_reading WHERE scan_id=? ORDER BY symbol", (scan_id,))]


def due_checkpoint(calendar, now: datetime) -> tuple[str | None, str | None]:
    """(checkpoint "HH:MM" whose window is open now, skip reason) for an open session day; (None, None) otherwise."""
    today, minute = now.date(), now.hour * 60 + now.minute
    for hour, mins in CHECKPOINTS:
        start = hour * 60 + mins
        if start <= minute < start + DEADLINE_MINUTES:
            hours = calendar.hours(today)
            if hours is None:
                return (f"{hour:02d}:{mins:02d}", "calendar_unavailable") if today.weekday() < 5 else (None, None)
            windows = {w[0]: w for w in session_windows(today, hours)}
            if "regular" not in windows or start >= windows["regular"][1]:
                return None, None
            return f"{hour:02d}:{mins:02d}", None
    return None, None


def summarize(bars: list[dict], cutoff: float, day: date) -> dict:
    """Premarket minutes of ``day`` completed by ``cutoff`` (epoch seconds): last close, time, count, volume, dollars."""
    pre = []
    for bar in bars:
        at = datetime.fromtimestamp(bar["time"], ET)
        if at.date() == day and 240 <= at.hour * 60 + at.minute < 570 and bar["time"] + 60 <= cutoff:
            pre.append(bar)
    if not pre:
        return {"last": None, "last_bar_at": None, "bars": 0, "volume": 0, "dollar_volume": 0.0}
    return {"last": pre[-1]["close"], "last_bar_at": _iso(datetime.fromtimestamp(pre[-1]["time"], ET)), "bars": len(pre),
            "volume": int(sum(b["volume"] for b in pre)), "dollar_volume": float(sum(b["volume"] * b["close"] for b in pre))}


def apply_rule(readings: list[dict], stocks: set[str], cutoff: float, rule: Rule = PREMARKET_V0) -> int:
    """Fill change/excess/flagged in place against SPY's own premarket change; returns how many were flagged."""
    def change(r):
        return (r["last"] / r["prev_close"] - 1) * 100 if r["last"] and r["prev_close"] else None
    spy = next((change(r) for r in readings if r["symbol"] == "SPY"), None)
    flagged = 0
    for r in readings:
        r["change_pct"] = round(change(r), 3) if change(r) is not None else None
        r["excess_pct"] = round(r["change_pct"] - spy, 3) if r["change_pct"] is not None and spy is not None else None
        fresh = r["last_bar_at"] is not None and (cutoff - datetime.fromisoformat(r["last_bar_at"].replace("Z", "+00:00")).timestamp()
                                                 <= rule.max_trade_age_minutes * 60 + 60)
        r["flagged"] = bool(r["symbol"] in stocks and r["excess_pct"] is not None and abs(r["excess_pct"]) >= rule.excess_pct
                            and r["dollar_volume"] >= rule.min_dollar_volume and fresh)
        flagged += r["flagged"]
    return flagged


class PremarketScanner:
    def __init__(self, store: PremarketStore, calendar, universe: dict, *, quotes: Quotes = tradier.get_quotes_once,
                 read: Read | None = None, clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.store, self.calendar, self.universe = store, calendar, universe
        self.symbols = [row["symbol"] for row in universe["symbols"]]
        self.stocks = {row["symbol"] for row in universe["symbols"] if row["kind"] == "stock" and not row.get("benchmark")}
        self.quotes, self.clock, self.sleep = quotes, clock, sleep
        if read is None:
            from app.engine.chart_feed import chart_feed
            read = chart_feed.read
        self.read = read

    def run_once(self) -> int | None:
        """Record the due checkpoint's scan once; returns its id, or None when nothing is due or it already exists."""
        now = datetime.fromtimestamp(self.clock(), ET)
        checkpoint, skip = due_checkpoint(self.calendar, now)
        if checkpoint is None or self.store.has_scan(now.date().isoformat(), checkpoint):
            return None
        hour, mins = (int(x) for x in checkpoint.split(":"))
        cut = datetime(now.year, now.month, now.day, hour, mins, tzinfo=ET)
        deadline = cut.timestamp() + DEADLINE_MINUTES * 60 - 30
        scan = {"session_date": now.date().isoformat(), "checkpoint": checkpoint, "started_at": _iso(now), "finished_at": "",
                "rule_version": RULE_VERSION, "universe_version": self.universe["version"], "status": "skipped",
                "symbols_requested": 0, "symbols_read": 0, "symbols_with_bars": 0, "requests_used": 0, "flagged": 0,
                "error": None, "skip_reason": skip}
        readings: list[dict] = []
        if skip is None:
            readings = self._collect(scan, cut, deadline)
        scan["finished_at"] = _iso(datetime.fromtimestamp(self.clock(), ET))
        return self.store.append_scan(scan, readings)

    def _collect(self, scan: dict, cut: datetime, deadline: float) -> list[dict]:
        errors: list[str] = []
        found: dict = {}
        for i in range(0, len(self.symbols), BATCH_SIZE):
            scan["requests_used"] += 1
            try:
                found.update(self.quotes(self.symbols[i:i + BATCH_SIZE]))
            except Exception as exc:  # without previous closes there is nothing to measure; record and stop
                scan["status"], scan["error"] = "failed", f"quotes: {type(exc).__name__}: {str(exc)[:200]}"
                return []
        day = cut.date()
        readings, read_errors, stopped = [], 0, False
        gap = 60 / READS_PER_MINUTE
        for symbol in self.symbols:
            quote = found.get(symbol)
            row = {"symbol": symbol, "prev_close": tradier._f((quote.raw or {}).get("prevclose")) if quote else None,
                   "quote_last": quote.last if quote else None, "quote_trade_ms": quote.trade_date if quote else None,
                   "read_error": None, **summarize([], 0, day)}
            if stopped or self.clock() >= deadline:
                stopped, row["read_error"] = True, "deadline"
                readings.append(row)
                continue
            scan["symbols_requested"] += 1
            scan["requests_used"] += 1
            started = self.clock()
            try:
                # Uncached (keep=False): 169 reads would push every chart out of the feed's cache, and a stale
                # cached answer must not pass as a fresh read.
                data = self.read("/v1/markets/timesales", {"symbol": symbol, "interval": "1min", "session_filter": "all",
                                                           "start": day.strftime("%Y-%m-%d 04:00"),
                                                           "end": day.strftime("%Y-%m-%d 20:00")}, 15, keep=False)[0]
                series = (data or {}).get("series") or {}
                raw = series.get("data") if isinstance(series, dict) else None
                bars = normalize_bars(raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else [])
                row.update(summarize(bars, cut.timestamp(), day))
                scan["symbols_read"] += 1
                scan["symbols_with_bars"] += row["bars"] > 0
            except Exception as exc:  # one symbol's failure is recorded on its row; the scan goes on
                read_errors += 1
                row["read_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            readings.append(row)
            wait = gap - (self.clock() - started)
            if wait > 0:
                self.sleep(wait)
        scan["flagged"] = apply_rule(readings, self.stocks, cut.timestamp())
        if read_errors:
            errors.append(f"{read_errors} timesales reads failed")
        if stopped:
            errors.append(f"deadline: {sum(r['read_error'] == 'deadline' for r in readings)} symbols not read")
        scan["error"] = "; ".join(errors) or None
        scan["status"] = "ok" if not errors else "partial" if scan["symbols_read"] else "failed"
        return readings


def scanner_from_env(radar_store: str, calendar, universe: dict) -> PremarketScanner | None:
    if not enabled():
        return None
    return PremarketScanner(PremarketStore(store_path(radar_store)), calendar, universe)
