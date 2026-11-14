"""QQQ intraday momentum paper book: the rule and settings that passed ``qqq-intraday-momentum-20261114-v1``
(research/notes/qqq-intraday-momentum-2026-11-14.md), recorded live at 1x before any money.

The noise area at each hourly check (10:00 to 15:00) is max/min(today's 09:30 open, the previous close) x (1 +/- 1.25 x
sigma), where sigma is the average absolute move from the open to that time over the previous 60 full sessions. At a
check the book goes long above max(upper band, VWAP) and short below min(lower band, VWAP); a held position closes at a
check when the price crosses back through that level (and only the opposite side can open at that check); anything open
closes at 15:59. Decisions use the close of the minute bar before the check (Tradier timesales, the chart feed's cached
read); fills are a fresh Tradier quote (bid and ask both updated within 60 seconds): the ask to buy, the bid to sell. A
check this process reaches more than ``LATE_MINUTES`` after its time is recorded as missed, never traded late.

History: ``intraday_momentum_seed.json`` holds the 60 full sessions before the book started (from the study's SIP bars);
after each full session the book records that day's moves and close from its own bars, so the window rolls forward. A day
the server never saw is left out of the window (the window is the 60 most recent recorded sessions). Early closes and
closed days are not traded or recorded.

Paper only: a timesales read and at most one quote request a check, nothing placed anywhere, no message sent. Storage is
a SQLite file of its own (``INTRADAY_MOMENTUM_BOOK_PATH``), no migration. Off unless
``INTRADAY_MOMENTUM_BOOK_ENABLED=true`` (the owner's switch); it runs on the level alert monitor's loop and never raises
into it.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date, datetime
import json
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
PROTOCOL_ID = "qqq-intraday-momentum-20261114-v1"
LOOKBACK, VM = 60, 1.25
CHECKS = (600, 660, 720, 780, 840, 900)  # 10:00 .. 15:00 New York
OPEN_MINUTE, CLOSE_MINUTE, FULL_CLOSE = 570, 959, 960
LATE_MINUTES = 5
QUOTE_AGE_SECONDS = 60
RUN_SECONDS = 5
STAKE = 10_000.0
BACKTEST = {"protocol_id": PROTOCOL_ID, "mean_bp": 4.4, "interval_bp": [2.1, 6.85], "years": "2022-2026",
            "settings": {"lookback": LOOKBACK, "vm": VM, "every": 60, "stop": "band_vwap"},
            "note": "research/notes/qqq-intraday-momentum-2026-11-14.md"}
SEED = Path(__file__).resolve().parent / "intraday_momentum_seed.json"
DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "intraday_momentum_book.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS session (day TEXT PRIMARY KEY, open REAL NOT NULL, close REAL NOT NULL, moves TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS check_row (
    day TEXT NOT NULL, minute INTEGER NOT NULL, status TEXT NOT NULL,  -- done | missed
    price REAL, upper REAL, lower REAL, vwap REAL, note TEXT, PRIMARY KEY (day, minute)
);
CREATE TABLE IF NOT EXISTS trade (
    id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, side INTEGER NOT NULL, day_open REAL NOT NULL,
    entry_at REAL NOT NULL, entry REAL NOT NULL, exit_at REAL, exit REAL, how TEXT, status TEXT NOT NULL  -- open | closed
);
"""


def enabled() -> bool:
    return os.environ.get("INTRADAY_MOMENTUM_BOOK_ENABLED", "").lower() == "true"


def store_path() -> Path:
    return Path(os.environ.get("INTRADAY_MOMENTUM_BOOK_PATH") or DEFAULT_PATH)


# ------------------------------------------------------------------ store


class Store:
    def __init__(self, path: Path, seed: Path | None = SEED):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(SCHEMA)
            if seed is not None and db.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0:
                for s in json.loads(Path(seed).read_text())["sessions"]:
                    db.execute("INSERT OR IGNORE INTO session VALUES (?, ?, ?, ?)",
                               (s["day"], s["open"], s["close"], json.dumps(s["moves"])))

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def history(self, before: str) -> list[dict]:
        """The most recent ``LOOKBACK`` recorded sessions before ``before``, oldest first."""
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM session WHERE day < ? ORDER BY day DESC LIMIT ?", (before, LOOKBACK)).fetchall()
        return [{**dict(r), "moves": json.loads(r["moves"])} for r in reversed(rows)]

    def has_session(self, day: str) -> bool:
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM session WHERE day = ?", (day,)).fetchone() is not None

    def add_session(self, day: str, open_: float, close: float, moves: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO session VALUES (?, ?, ?, ?)", (day, open_, close, json.dumps(moves)))

    def checked(self, day: str) -> set[int]:
        with closing(self._connect()) as db:
            return {r[0] for r in db.execute("SELECT minute FROM check_row WHERE day = ?", (day,))}

    def add_check(self, day: str, minute: int, status: str, **row) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO check_row VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (day, minute, status, row.get("price"), row.get("upper"), row.get("lower"), row.get("vwap"), row.get("note")))

    def open_trade(self) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM trade WHERE status = 'open' ORDER BY id DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)

    def enter(self, day: str, side: int, day_open: float, at: float, price: float) -> None:
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO trade (day, side, day_open, entry_at, entry, status) VALUES (?, ?, ?, ?, ?, 'open')",
                       (day, side, day_open, at, price))

    def exit(self, trade_id: int, at: float, price: float, how: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE trade SET exit_at = ?, exit = ?, how = ?, status = 'closed' WHERE id = ? AND status = 'open'",
                       (at, price, how, trade_id))

    def trades(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM trade ORDER BY id")]

    def checks(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute("SELECT * FROM check_row ORDER BY day, minute")]


# ------------------------------------------------------------------ rules (pure)


def sigma(history: list[dict], minute: int) -> float | None:
    """The average absolute move from the open to ``minute`` over the window, or None without a full window."""
    vals = [h["moves"].get(str(minute)) for h in history]
    if len(vals) < LOOKBACK or any(v is None for v in vals):
        return None
    return sum(vals) / len(vals)


def regular(bars: list[dict], day: date, before_minute: int) -> list[dict]:
    """Today's regular-session minute bars that started at or after 09:30 and before ``before_minute``."""
    lo = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET).timestamp()
    hi = datetime(day.year, day.month, day.day, before_minute // 60, before_minute % 60, tzinfo=ET).timestamp()
    return [b for b in bars if lo <= b["time"] < hi]


def vwap(bars: list[dict]) -> float | None:
    vol = sum(b["volume"] for b in bars)
    return sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in bars) / vol if vol > 0 else None


def levels(open_: float, prev_close: float, sig: float, vw: float | None) -> dict:
    upper = max(open_, prev_close) * (1 + VM * sig)
    lower = min(open_, prev_close) * (1 - VM * sig)
    return {"upper": upper, "lower": lower, "vwap": vw,
            "long": max(upper, vw) if vw is not None else upper, "short": min(lower, vw) if vw is not None else lower}


def decide(side: int, price: float, lv: dict) -> tuple[bool, int]:
    """(close the held side?, side to open: 1, -1 or 0) at a check, as the study's band_vwap rule."""
    stop = side != 0 and ((price < lv["long"]) if side > 0 else (price > lv["short"]))
    if side != 0 and not stop:
        return False, 0
    # Flat (or just stopped): a side opens only beyond its own level, so a stopped side can never reopen here.
    return stop, 1 if price > lv["long"] else -1 if price < lv["short"] else 0


def fresh(quote, now: float) -> tuple[float, float] | None:
    if quote is None or quote.bid is None or quote.ask is None or quote.bid <= 0 or quote.ask < quote.bid:
        return None
    for stamp in (quote.bid_date, quote.ask_date):
        if stamp is None or not now - QUOTE_AGE_SECONDS <= stamp / 1000 <= now + QUOTE_AGE_SECONDS:
            return None
    return float(quote.bid), float(quote.ask)


def bp(t: dict) -> float | None:
    if t.get("status") != "closed":
        return None
    return t["side"] * (t["exit"] - t["entry"]) / t["day_open"] * 10_000


def summary(trades: list[dict], checks: list[dict], now: float, on: bool) -> dict:
    """Only finished days count: a day is finished once its last check (15:00) is recorded or the day has passed, and
    it has no open position. A checked day with no trade is a 0 day, as in the study."""
    today = datetime.fromtimestamp(now, ET).date().isoformat()
    open_days = {t["day"] for t in trades if t["status"] == "open"}
    last_checked = {c["day"] for c in checks if c["minute"] == CHECKS[-1]}
    finished = lambda d: d not in open_days and (d in last_checked or d < today)  # noqa: E731
    by_day: dict[str, float] = {}
    for t in trades:
        b = bp(t)
        if b is not None and finished(t["day"]):
            by_day[t["day"]] = by_day.get(t["day"], 0.0) + b
    for d in sorted({c["day"] for c in checks if c["status"] == "done"}):
        if finished(d):
            by_day.setdefault(d, 0.0)
    days = [by_day[d] for d in sorted(by_day)]
    held = next((t for t in reversed(trades) if t["status"] == "open"), None)
    rows = [{"day": d, "bp": round(by_day[d], 2), "dollars": round(STAKE * by_day[d] / 10_000, 2),
             "trades": [{"side": t["side"], "entry_at": t["entry_at"], "entry": t["entry"], "exit_at": t["exit_at"],
                         "exit": t["exit"], "how": t["how"]} for t in trades if t["day"] == d and t["status"] == "closed"]}
            for d in sorted(by_day, reverse=True)]
    return {
        "enabled": on, "symbol": SYMBOL, "stake": STAKE, "now": now, "backtest": BACKTEST,
        "holding": None if held is None else {"side": held["side"], "entry_at": held["entry_at"], "entry": held["entry"]},
        "days": rows,
        "totals": {"days": len(days), "days_traded": sum(1 for d in sorted(by_day) if any(t["day"] == d for t in trades)),
                   "mean_bp": round(sum(days) / len(days), 2) if days else None,
                   "dollars": round(sum(STAKE * b / 10_000 for b in days), 2) if days else None,
                   "up": sum(1 for b in days if b > 0),
                   "missed_checks": sum(1 for c in checks if c["status"] == "missed")},
    }


# ------------------------------------------------------------------ the recorder


class IntradayMomentumBook:
    def __init__(self, calendar=None, feed=None, *, clock: Callable[[], float] = time.time,
                 quote: Callable = tradier.get_quotes_once, store: Store | None = None):
        self.calendar = calendar
        self.feed = feed
        self.clock = clock
        self.quote = quote
        self.store = store or Store(store_path())
        self._last_run = 0.0

    def deliver(self) -> None:
        """Nothing to send; present so the monitor can treat it like its other stages."""

    def full_session(self, day: date) -> bool:
        """A regular session that closes at 16:00 by the calendar. Without the calendar, no trading (unconfirmed)."""
        if day.weekday() >= 5 or self.calendar is None:
            return False
        found = self.calendar.hours(day)
        return bool(found) and found.get("status") in (None, "open") and found.get("close") == FULL_CLOSE

    def open_day(self, day: date) -> bool:
        if day.weekday() >= 5:
            return False
        found = self.calendar.hours(day) if self.calendar is not None else None
        return not found or found.get("status") in (None, "open")

    def _bars(self, now: float) -> list[dict]:
        return self.feed.today_minutes(SYMBOL, now) if self.feed is not None else []

    def _quote(self, now: float) -> tuple[float, float] | None:
        try:
            return fresh(self.quote([SYMBOL]).get(SYMBOL), now)
        except Exception as exc:
            log.warning("Intraday momentum book quote failed: %s", exc)
            return None

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            log.exception("Intraday momentum book pass failed")

    def _run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        today, minute = moment.date(), moment.hour * 60 + moment.minute
        held = self.store.open_trade()
        if held is not None and held["day"] != today.isoformat():
            # A position left open by an outage: close it at the first quote in the next regular session (never held
            # overnight on purpose, never sold outside the session); the row says how.
            if not self.open_day(today) or not OPEN_MINUTE <= minute < CLOSE_MINUTE:
                return
            got = self._quote(now)
            if got is not None:
                self.store.exit(held["id"], now, got[0] if held["side"] > 0 else got[1], "late close")
            return
        if not self.full_session(today) or minute < CHECKS[0]:
            return
        day = today.isoformat()
        if minute >= FULL_CLOSE:
            self._record_session(today, now)
            return
        if minute >= CLOSE_MINUTE:
            if held is not None:
                got = self._quote(now)
                if got is not None:
                    self.store.exit(held["id"], now, got[0] if held["side"] > 0 else got[1], "close")
            return
        done = self.store.checked(day)
        for m in CHECKS:
            if m > minute or m in done:
                continue
            if minute >= m + LATE_MINUTES:
                self.store.add_check(day, m, "missed", note="not reached within five minutes")
                continue
            self._check(today, m, now, held)
            return  # one check a pass

    def _check(self, today: date, m: int, now: float, held: dict | None) -> None:
        day = today.isoformat()
        history = self.store.history(day)
        sig = sigma(history, m)
        if sig is None or not history:
            self.store.add_check(day, m, "missed", note="no 60-session history")
            return
        try:
            bars = self._bars(now)
        except Exception as exc:  # the chart feed refused or is stale: the next pass inside the five minutes tries again
            log.info("Intraday momentum book could not read QQQ bars: %s", exc)
            return
        before = regular(bars, today, m)
        start = datetime(today.year, today.month, today.day, 9, 30, tzinfo=ET).timestamp()
        if not before or before[0]["time"] != start or before[-1]["time"] < start + (m - OPEN_MINUTE - 1) * 60:
            return  # the 09:30 bar or the bar just before the check is not in yet: the next pass tries again
        price, open_ = before[-1]["close"], before[0]["open"]
        lv = levels(open_, history[-1]["close"], sig, vwap(before))
        side = held["side"] if held is not None else 0
        stop, want = decide(side, price, lv)
        if stop or want:
            got = self._quote(now)
            if got is None:
                return  # no fresh quote yet: the next pass inside the check's five minutes tries again
            bid, ask = got
            if stop:
                self.store.exit(held["id"], now, bid if side > 0 else ask, "stop")
            if want:
                self.store.enter(day, want, open_, now, ask if want > 0 else bid)
        self.store.add_check(day, m, "done", price=price, upper=lv["upper"], lower=lv["lower"], vwap=lv["vwap"])

    def _record_session(self, today: date, now: float) -> None:
        day = today.isoformat()
        if self.store.has_session(day):
            return
        try:
            bars = regular(self._bars(now), today, FULL_CLOSE)
        except Exception as exc:
            log.info("Intraday momentum book could not read today's bars: %s", exc)
            return
        start = datetime(today.year, today.month, today.day, 9, 30, tzinfo=ET).timestamp()
        if not bars or bars[0]["time"] != start:
            return
        open_ = bars[0]["open"]
        moves = {}
        for m in CHECKS:
            p = [b for b in bars if b["time"] < start + (m - OPEN_MINUTE) * 60]
            if p:
                moves[str(m)] = round(abs(p[-1]["close"] / open_ - 1), 6)
        if len(moves) == len(CHECKS):
            self.store.add_session(day, open_, bars[-1]["close"], moves)


def read(now: float | None = None) -> dict:
    """The desk's view, from the store alone (no provider call); a missing file reads as an empty book."""
    now = time.time() if now is None else now
    path = store_path()
    if not path.exists():
        return summary([], [], now, enabled())
    store = Store(path, seed=None)
    return summary(store.trades(), store.checks(), now, enabled())
