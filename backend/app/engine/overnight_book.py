"""QQQ overnight paper book: the rule that passed ``qqq-overnight-20261114-v1`` (research/notes/qqq-overnight-2026-11-14.md),
recorded live with the same fills before any money.

Each full session (the market calendar's regular close at 16:00), the first pass at or after 15:59:00 buys QQQ at the
ask of a fresh quote; the first pass at or after 09:30:00 on the next open session sells it at the bid of a fresh quote (the regular
session only: a position whose exit cannot fill waits for the next session rather than selling after hours).
Early closes have no entry, as in the study. A quote is fresh when its bid and ask are above zero, the ask is at or
above the bid and both were updated within ``QUOTE_AGE_SECONDS`` of the pass. No fresh quote before 16:00:00 makes
the night ``missed`` (counted, never filled). An exit keeps trying until it fills and records its own time, so a late
exit shows as late instead of being dropped. A night the server never saw at all leaves no row.

Paper only: one quote request at the entry minute and at the exit minute, nothing placed anywhere, no message sent.
Storage is a SQLite file of its own (``OVERNIGHT_BOOK_PATH``), not the journal database: no migration. Everything is
derived from the rows, so a restart neither loses nor repeats a night. Off unless ``OVERNIGHT_BOOK_ENABLED=true`` (the
owner's switch); it runs on the level alert monitor's loop and never raises into it.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date, datetime
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable

from app.engine import tradier
from app.engine.chart_math import ET

log = logging.getLogger(__name__)

SYMBOL = "QQQ"
PROTOCOL_ID = "qqq-overnight-20261114-v1"
ENTRY_MINUTE = 15 * 60 + 59  # the buy goes at 15:59:00
FULL_CLOSE = 16 * 60  # entries only on sessions that close at 16:00
OPEN_MINUTE = 9 * 60 + 30  # the sell goes at 09:30:00
QUOTE_AGE_SECONDS = 60
RUN_SECONDS = 5  # the monitor passes every 20 s; this only stops a double pass
STAKE = 10_000.0  # dollars a night, for the desk's dollar line (results are in basis points)
BACKTEST = {"protocol_id": PROTOCOL_ID, "mean_bp": 4.2, "interval_bp": [1.1, 7.13], "nights": 2711,
            "years": "2016-2026", "note": "research/notes/qqq-overnight-2026-11-14.md"}
DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "overnight_book.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS night (
    day TEXT PRIMARY KEY,            -- the entry session, New York date
    status TEXT NOT NULL,            -- open | closed | missed
    entry_at REAL, entry_bid REAL, entry_ask REAL,
    exit_day TEXT, exit_at REAL, exit_bid REAL, exit_ask REAL,
    note TEXT
);
"""


def enabled() -> bool:
    return os.environ.get("OVERNIGHT_BOOK_ENABLED", "").lower() == "true"


def store_path() -> Path:
    return Path(os.environ.get("OVERNIGHT_BOOK_PATH") or DEFAULT_PATH)


# ------------------------------------------------------------------ store


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def nights(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM night ORDER BY day")]

    def night(self, day: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM night WHERE day = ?", (day,)).fetchone()
        return None if row is None else dict(row)

    def open_night(self) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM night WHERE status = 'open' ORDER BY day DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)

    def enter(self, day: str, at: float, bid: float, ask: float) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO night (day, status, entry_at, entry_bid, entry_ask) VALUES (?, 'open', ?, ?, ?)",
                       (day, at, bid, ask))

    def miss(self, day: str, note: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO night (day, status, note) VALUES (?, 'missed', ?)", (day, note))

    def exit(self, day: str, exit_day: str, at: float, bid: float, ask: float) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE night SET status = 'closed', exit_day = ?, exit_at = ?, exit_bid = ?, exit_ask = ? "
                       "WHERE day = ? AND status = 'open'", (exit_day, at, bid, ask, day))


# ------------------------------------------------------------------ rules (pure)


def fresh(quote, now: float) -> tuple[float, float] | None:
    """(bid, ask) when the quote is usable at ``now``, else None."""
    if quote is None or quote.bid is None or quote.ask is None or quote.bid <= 0 or quote.ask < quote.bid:
        return None
    for stamp in (quote.bid_date, quote.ask_date):
        if stamp is None or not now - QUOTE_AGE_SECONDS <= stamp / 1000 <= now + QUOTE_AGE_SECONDS:
            return None
    return float(quote.bid), float(quote.ask)


def result_bp(night: dict) -> float | None:
    if night.get("status") != "closed":
        return None
    return (night["exit_bid"] - night["entry_ask"]) / night["entry_ask"] * 10_000


def summary(nights: list[dict], now: float, on: bool, state: str) -> dict:
    """What the desk shows: the state now, the recorded nights newest first, and the running result."""
    closed = [n for n in nights if n["status"] == "closed"]
    bps = [result_bp(n) for n in closed]
    rows = []
    for n in reversed(nights):
        bp = result_bp(n)
        rows.append({"day": n["day"], "status": n["status"], "entry_at": n.get("entry_at"), "entry": n.get("entry_ask"),
                     "exit_day": n.get("exit_day"), "exit_at": n.get("exit_at"), "exit": n.get("exit_bid"),
                     "bp": None if bp is None else round(bp, 2), "dollars": None if bp is None else round(STAKE * bp / 10_000, 2),
                     "note": n.get("note")})
    return {
        "enabled": on, "state": state, "symbol": SYMBOL, "stake": STAKE, "now": now, "backtest": BACKTEST,
        "nights": rows,
        "totals": {"closed": len(closed), "missed": sum(1 for n in nights if n["status"] == "missed"),
                   "mean_bp": round(sum(bps) / len(bps), 2) if bps else None,
                   "dollars": round(sum(STAKE * b / 10_000 for b in bps), 2) if bps else None,
                   "up": sum(1 for b in bps if b > 0)},
    }


# ------------------------------------------------------------------ the recorder


class OvernightBook:
    def __init__(self, calendar=None, *, clock: Callable[[], float] = time.time,
                 quote: Callable = tradier.get_quotes_once, store: Store | None = None):
        self.calendar = calendar
        self.clock = clock
        self.quote = quote
        self.store = store or Store(store_path())
        self._last_run = 0.0

    def deliver(self) -> None:
        """Nothing to send; present so the monitor can treat it like its other stages."""

    def hours(self, day: date) -> tuple[int, int] | None:
        """(open, close) in New York minutes, or None when the market is shut that day."""
        if day.weekday() >= 5:
            return None
        found = self.calendar.hours(day) if self.calendar is not None else None
        if not found:
            return (OPEN_MINUTE, FULL_CLOSE)
        if found.get("status") not in (None, "open") or found.get("close") is None:
            return None
        return int(found.get("open") or OPEN_MINUTE), int(found["close"])

    def _quote(self, now: float) -> tuple[float, float] | None:
        try:
            return fresh(self.quote([SYMBOL]).get(SYMBOL), now)
        except Exception as exc:  # a provider failure: the next pass tries again
            log.warning("Overnight book quote failed: %s", exc)
            return None

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            log.exception("Overnight book pass failed")

    def _run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        today, minute = moment.date(), moment.hour * 60 + moment.minute
        hours = self.hours(today)
        if hours is None:
            return
        held = self.store.open_night()
        if held is not None:
            # Sold only in a regular session after the entry day; never bought again before it is sold.
            if held["day"] < today.isoformat() and hours[0] <= minute < hours[1]:
                got = self._quote(now)
                if got is not None:
                    self.store.exit(held["day"], today.isoformat(), now, *got)
            return
        if hours[1] != FULL_CLOSE or self.store.night(today.isoformat()) is not None:
            return
        if minute == ENTRY_MINUTE:
            got = self._quote(now)
            if got is not None:
                self.store.enter(today.isoformat(), now, *got)
        elif minute >= FULL_CLOSE:
            self.store.miss(today.isoformat(), "no fresh QQQ quote between 15:59 and 16:00")


def read(now: float | None = None) -> dict:
    """The desk's view, from the store alone (no provider call). Off: an empty book that says so."""
    now = time.time() if now is None else now
    on = enabled()
    path = store_path()
    if not path.exists():
        return summary([], now, on, "flat")
    store = Store(path)
    nights = store.nights()
    return summary(nights, now, on, "holding" if any(n["status"] == "open" for n in nights) else "flat")
