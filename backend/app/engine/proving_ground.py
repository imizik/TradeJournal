"""The paper proving ground: every candidate idea source paper traded on one fixed bracket, with a leaderboard by source.

Isaac's ask (November 24, 2026): before any source earns real phone pings, it trades on paper. Each idea becomes one
long option contract (a call for up, a put for down) with the same bracket for every source:

- take profit when the contract's bid is at least ``TAKE_PROFIT`` (+20%) over the price paid;
- stop when its bid is ``STOP`` (15%) or more under it;
- a time stop ``HOLD_MINUTES`` (60) after the entry;
- flat ``FLAT_MINUTES`` before the regular close, so nothing is held overnight or into expiry.

Fills are the shadow book's and the setup scanner's: the ask of the first quote whose bid and ask both updated after
the idea (``shadow_book.entry_fill``), the bid of the first fresh quote at or after the exit condition, $0.65 a side
(``scanner_rules.result``, which also keeps a pessimistic twice-the-spread result). The bracket is checked on each
minute's quote, so a move inside a minute is missed and the exit fills at that minute's bid, never at the bracket price.

Sources (``SOURCES``):

- ``radar_setup``: each Radar setup card with a candidate contract (``RadarSetup``; needs ``RADAR_SETUP_CARDS``),
  entered on that card's contract.
- ``jo_morning``: each ``conditional`` opportunity in the day's newest Jo morning brief, entered from 9:45 New York
  on ``radar_setup.pick_contract``'s contract. The brief states no direction field, so a pick whose trigger or reason
  says put, short, fade, bearish or breakdown is down and anything else is up (``jo_direction``).
- ``open_window``: the 9:45-10:00 window of the October 21 behavior audit, as a rule: at 9:45 MU and NBIS each go in
  the direction of their move from the day's open, on ``pick_contract``'s contract.

A source **graduates** before its pings may go out unlabeled; until then ``label`` prefixes them ``PAPER``. Only
Radar setup pings exist today; Jo's brief and the 9:45 rule send no trade pings, so for them graduation shows on the
board only. The rule (``judge``) asks whether the record could be luck, not only whether it is green:

- each trade counts as its return on the premium paid, so a dear contract weighs no more than a cheap one;
- one session's trades are added into one number, because trades taken the same morning rise and fall together and
  are not separate evidence;
- the score is the average session over its standard error (a t statistic), and it must reach ``GRADUATE_SCORE``
  (3.0) on at least ``GRADUATE_DAYS`` (20) sessions and ``GRADUATE_TRADES`` (40) closed trades, with the
  twice-the-spread dollars above zero as well;
- the record is judged only at every ``REVIEW_DAYS``th (10th) session, on the sessions up to that one, so looking at
  the board every minute gives luck no extra chances and the label does not flicker in between. A graduated source
  whose score falls back under the bar at a later review is labeled ``PAPER`` again.

The bar is set for all of ``SOURCES`` at once: with every source at break-even after costs, the chance that any one
graduates within a year of sessions is about 5% (``tests/test_proving_ground.py`` simulates it, and fails if a
source is added without raising the bar). The rule it replaced, 40 closed trades net above zero, passed a break-even
source about half the time at trade 40 and nine times in ten within a year. The cost is time: at two trades a
session, a source with about 65% of its trades green typically needs about 40 sessions, one at 60% about 80, and
one at 55% is as likely as not still unproven after a year (break-even is about 49%). A changed rule is a new source: give it a new key rather than carrying the record on.

Paper only: quotes and option chains are read, nothing is placed, sized or sent. Storage is a SQLite file of its own
(``PROVING_GROUND_PATH``), no migration. Off unless ``PROVING_GROUND_ENABLED=true`` (the owner's switch); it runs on
its own minute loop in the API process and never raises into it. A restart neither loses nor repeats a trade: every
idea has one row by (source, ref), and anything still pending or open after its session is closed out as unresolved.
"""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, date, datetime
import json
import logging
import os
import math
from pathlib import Path
import re
import sqlite3
import statistics
import time
from typing import Callable

from app.engine import scanner_rules, tradier
from app.engine.chart_math import ET
from app.engine.shadow_book import entry_fill

log = logging.getLogger(__name__)

SOURCES = {"radar_setup": "Radar setups", "jo_morning": "Jo's morning picks", "open_window": "9:45 MU/NBIS rule"}
TAKE_PROFIT = 0.20
STOP = 0.15
HOLD_MINUTES = 60
FLAT_MINUTES = 5
ENTRY_WINDOW_SECONDS = 120  # no fresh quote this long after the idea -> unresolved
WINDOW = (585, 600)  # 9:45 to 10:00 New York, in minutes
OPEN_WINDOW_SYMBOLS = ("MU", "NBIS")
MAX_PICKS = 2  # contracts picked a minute: two option reads each, out of the shared budget
GRADUATE_TRADES = 40
GRADUATE_DAYS = 20  # sessions with a closed trade
REVIEW_DAYS = 10  # the record is judged at every tenth session, on the sessions up to it
GRADUATE_SCORE = 3.0  # the average session over its standard error
RUN_SECONDS = 60
RECENT = 10
_PLAN = {"instrument": "calls", "direction": "long"}  # buy to open, sell to close: ask in, bid out
_BEARISH = re.compile(r"\b(puts?|short|fade|fading|bearish|breakdown|breaks? down|breaks? below)\b", re.IGNORECASE)
DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "proving_ground.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, ref TEXT NOT NULL, day TEXT NOT NULL,
    symbol TEXT NOT NULL, direction TEXT NOT NULL, contract TEXT, created_at REAL NOT NULL,
    state TEXT NOT NULL,  -- pending | open | closed | unresolved
    entry REAL, entry_bid REAL, entry_at REAL, mark REAL, mark_ask REAL, exit REAL, exit_at REAL, reason TEXT, pnl REAL, pnl_2x REAL, note TEXT,
    UNIQUE (source, ref)
);
"""


def enabled() -> bool:
    return os.environ.get("PROVING_GROUND_ENABLED", "").lower() == "true"


def store_path() -> Path:
    return Path(os.environ.get("PROVING_GROUND_PATH") or DEFAULT_PATH)


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

    def add(self, source: str, ref: str, day: str, symbol: str, direction: str, contract: dict | None,
            created_at: float, note: str | None = None) -> bool:
        """One idea, once: False when (source, ref) is already there. No contract means unresolved at once."""
        state = "pending" if contract else "unresolved"
        with closing(self._connect()) as db, db:
            cur = db.execute("INSERT OR IGNORE INTO trade (source, ref, day, symbol, direction, contract, created_at, state, note) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (source, ref, day, symbol, direction, json.dumps(contract, sort_keys=True) if contract else None,
                              created_at, state, note if contract is None else None))
            return cur.rowcount == 1

    def has(self, source: str, ref: str) -> bool:
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM trade WHERE source = ? AND ref = ?", (source, ref)).fetchone() is not None

    def has_day(self, source: str, day: str) -> bool:
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM trade WHERE source = ? AND day = ?", (source, day)).fetchone() is not None

    def live(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [_row(r) for r in db.execute("SELECT * FROM trade WHERE state IN ('pending', 'open') ORDER BY id")]

    def update(self, trade_id: int, expected: str, **values) -> None:
        """Write only if the row is still in the state it was read in."""
        keys = sorted(values)
        with closing(self._connect()) as db, db:
            db.execute(f"UPDATE trade SET {', '.join(f'{k} = ?' for k in keys)} WHERE id = ? AND state = ?",
                       [values[k] for k in keys] + [trade_id, expected])

    def trades(self) -> list[dict]:
        with closing(self._connect()) as db:
            return [_row(r) for r in db.execute("SELECT * FROM trade ORDER BY id")]


def _read_only(path: Path) -> list[dict]:
    """Every trade, through a read-only connection: the ping path never writes or creates the file."""
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        return [_row(r) for r in db.execute("SELECT * FROM trade ORDER BY id")]


def _row(r: sqlite3.Row) -> dict:
    out = dict(r)
    out["contract"] = json.loads(out["contract"]) if out["contract"] else None
    return out


# ------------------------------------------------------------------ rules


def jo_direction(item: dict) -> str:
    """Up unless the pick's trigger or reason reads bearish (the brief has no direction field)."""
    text = " ".join(str(item.get(k) or "") for k in ("entry_trigger", "what_matters"))
    return "down" if _BEARISH.search(text) else "up"


def fresh(quote, since: float) -> bool:
    """A two-sided quote whose bid and ask both updated at or after ``since`` (Tradier's millisecond times)."""
    return quote is not None and quote.bid is not None and bool(quote.ask) and all(
        isinstance(t, (int, float)) and t >= since * 1000 for t in (quote.bid_date, quote.ask_date))


def bracket(row: dict, quote, now: float, close_at: float | None) -> str | None:
    """The exit reason this minute for an open row, or None. Price exits read a quote fresh after the entry."""
    if not fresh(quote, row["entry_at"]):
        quote = None
    if quote is not None and quote.bid >= row["entry"] * (1 + TAKE_PROFIT):
        return "take_profit"
    if quote is not None and quote.bid <= row["entry"] * (1 - STOP):
        return "stop"
    if now >= row["entry_at"] + HOLD_MINUTES * 60:
        return "time_stop"
    if close_at is not None and now >= close_at - FLAT_MINUTES * 60:
        return "session_close"
    return None


def _return(trade: dict) -> float | None:
    """A closed trade's net dollars over the premium paid with its commission; None when it has no entry price."""
    if not trade["entry"] or trade["pnl"] is None:
        return None
    return trade["pnl"] / (trade["entry"] * int((trade["contract"] or {}).get("multiplier") or 100) + scanner_rules.COMMISSION_PER_SIDE)


def judge(closed: list[dict]) -> dict:
    """Whether one source's closed trades could be luck (the module docstring has the rule and why).

    ``days`` and ``reviewed_days`` count sessions with a closed trade, all of them and those up to the last review;
    ``score`` is the average reviewed session's summed return over its standard error, None before two sessions."""
    by_day: dict[str, list[dict]] = {}
    for t in closed:
        if _return(t) is not None:
            by_day.setdefault(t["day"], []).append(t)
    days = sorted(by_day)
    reviewed = days[:len(days) // REVIEW_DAYS * REVIEW_DAYS]
    seen = [t for d in reviewed for t in by_day[d]]
    sums = [sum(_return(t) for t in by_day[d]) for d in reviewed]
    score = None
    if len(sums) >= 2:
        spread = statistics.stdev(sums)
        score = round(statistics.fmean(sums) / (spread / math.sqrt(len(sums))), 2) if spread > 0 else 0.0
    proven = score is not None and score >= GRADUATE_SCORE
    wide = sum(t["pnl_2x"] or 0 for t in seen) > 0
    enough = len(reviewed) >= GRADUATE_DAYS and len(seen) >= GRADUATE_TRADES
    if enough and proven and wide:
        status = "Graduated"
    elif len(days) < GRADUATE_DAYS or len(closed) < GRADUATE_TRADES:
        status = f"PAPER · {len(days)} of {GRADUATE_DAYS} days, {len(closed)} of {GRADUATE_TRADES} trades"
    elif enough and proven:
        status = "PAPER · in the red at twice the spread"
    else:
        status = f"PAPER · score {score or 0:.1f} of {GRADUATE_SCORE:.1f}, next look at day {len(reviewed) + REVIEW_DAYS}"
    return {"days": len(days), "reviewed_days": len(reviewed), "score": score, "graduated": enough and proven and wide,
            "status": status}


def board(trades: list[dict]) -> list[dict]:
    """One row per source, best net first: closed trades, green, net dollars (base and at twice the spread), exits,
    and ``judge``'s verdict on whether it has graduated."""
    out = []
    for source, name in SOURCES.items():
        mine = [t for t in trades if t["source"] == source]
        closed = [t for t in mine if t["state"] == "closed"]
        pnl = round(sum(t["pnl"] or 0 for t in closed), 2)
        out.append({
            "source": source, "name": name, "closed": len(closed), "green": sum((t["pnl"] or 0) > 0 for t in closed),
            "pnl": pnl, "pnl_2x": round(sum(t["pnl_2x"] or 0 for t in closed), 2),
            "avg": round(pnl / len(closed), 2) if closed else None,
            "open": sum(t["state"] in ("pending", "open") for t in mine),
            "unresolved": sum(t["state"] == "unresolved" for t in mine),
            "exits": {r: sum(t["reason"] == r for t in closed) for r in ("take_profit", "stop", "time_stop", "session_close", "no_exit")},
            **judge(closed),
        })
    return sorted(out, key=lambda r: (r["closed"] == 0, -r["pnl"]))


def graduated(source: str, path: Path | None = None) -> bool:
    """Whether ``source`` has graduated; False when the book has never run. Never raises."""
    try:
        path = path or store_path()
        if not path.exists():
            return False
        return next(r["graduated"] for r in board(_read_only(path)) if r["source"] == source)
    except Exception:
        log.exception("Proving ground: graduation read failed; the ping stays labeled PAPER")
        return False


def label(source: str, title: str, path: Path | None = None) -> str:
    """A ping title as sent: ``PAPER · `` in front until its source graduates."""
    return title if graduated(source, path) else f"PAPER · {title}"


def read(path: Path | None = None) -> dict:
    """The desk's view: the switch, the bracket, the board and the latest trades. No provider call."""
    path = path or store_path()
    trades = Store(path).trades() if path.exists() else []
    return {"enabled": enabled(), "graduate_trades": GRADUATE_TRADES, "graduate_days": GRADUATE_DAYS,
            "graduate_score": GRADUATE_SCORE, "review_days": REVIEW_DAYS,
            "bracket": {"take_profit": TAKE_PROFIT, "stop": STOP, "hold_minutes": HOLD_MINUTES, "flat_minutes": FLAT_MINUTES},
            "board": board(trades),
            "recent": [{k: t[k] for k in ("source", "day", "symbol", "direction", "state", "entry", "exit", "reason", "pnl", "note")}
                       | {"contract": (t["contract"] or {}).get("symbol")} for t in reversed(trades[-RECENT:])]}


# ------------------------------------------------------------------ the loop


def _epoch(value: datetime) -> float:
    return value.replace(tzinfo=UTC).timestamp() if value.tzinfo is None else value.timestamp()


class ProvingGround:
    def __init__(self, engine, calendar, *, store: Store | None = None, quotes=tradier.get_quotes_once,
                 pick: Callable | None = None, clock: Callable[[], float] = time.time):
        self.engine, self.calendar, self.quotes, self.clock = engine, calendar, quotes, clock
        self.store = store or Store(store_path())
        if pick is None:
            from app.engine.radar_setup import pick_contract as pick
        self.pick = pick
        self._last_run = 0.0
        self.last_error: str | None = None

    def run(self) -> None:
        try:
            self._run()
            self.last_error = None
        except Exception:  # paper only; the next minute tries again
            self.last_error = "Proving ground pass failed"
            log.exception("Proving ground pass failed")

    def _run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS - 1:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        today, minute = moment.date(), moment.hour * 60 + moment.minute
        hours = self.calendar.hours(today)
        inside = bool(hours and hours.get("status") == "open" and hours["open"] <= minute < hours["close"])
        close_at = (datetime(today.year, today.month, today.day, hours["close"] // 60, hours["close"] % 60, tzinfo=ET).timestamp()
                    if inside else None)
        if inside:
            picks = [MAX_PICKS]
            for intake in (self._radar, self._open_window, self._jo):
                if intake is not self._radar and not WINDOW[0] <= minute < WINDOW[1]:
                    continue
                try:  # one source failing never stops the others or the exits
                    intake(today, now, picks)
                except Exception:
                    log.exception("Proving ground: %s intake failed; the next minute tries again", intake.__name__)
        self._step(today, now, inside, close_at)

    # ------------------------------------------------------------ intake

    def _radar(self, today: date, now: float, picks: list[int]) -> None:
        from sqlmodel import Session, select
        from app.models import RadarSetup
        with Session(self.engine) as db:
            cards = db.exec(select(RadarSetup).where(RadarSetup.session_date == today.isoformat(),
                                                     RadarSetup.contract_json.is_not(None))).all()
        for card in cards:
            self.store.add("radar_setup", card.event_id, card.session_date, card.symbol, card.direction,
                           json.loads(card.contract_json), _epoch(card.created_at))

    def _open_window(self, today: date, now: float, picks: list[int]) -> None:
        day = today.isoformat()
        wanted = [s for s in OPEN_WINDOW_SYMBOLS if not self.store.has("open_window", f"{day}:{s}")]
        if not wanted or picks[0] <= 0:
            return
        quotes = self.quotes(wanted)
        for symbol in wanted:
            if picks[0] <= 0:
                return
            q = quotes.get(symbol)
            last, open_ = (q.last, tradier._f((q.raw or {}).get("open"))) if q else (None, None)
            if not last or not open_:
                continue  # no quote yet: the next minute tries again inside the window
            direction = "up" if last >= open_ else "down"
            picks[0] -= 1
            contract = self.pick(symbol, direction, today)
            self.store.add("open_window", f"{day}:{symbol}", day, symbol, direction, contract, now,
                           note=f"{symbol} {'up' if direction == 'up' else 'down'} from the open at 9:45; no liquid contract")

    def _jo(self, today: date, now: float, picks: list[int]) -> None:
        for symbol, item, ref in self._jo_picks(today):
            if picks[0] <= 0:
                return
            if self.store.has("jo_morning", ref):
                continue
            direction = jo_direction(item)
            picks[0] -= 1
            contract = self.pick(symbol, direction, today)
            self.store.add("jo_morning", ref, today.isoformat(), symbol, direction, contract, now,  # one per symbol a day
                           note="no liquid contract")

    def _jo_picks(self, today: date) -> list[tuple[str, dict, str]]:
        """The conditional opportunities of the day's newest brief (redacted ones skipped)."""
        from sqlmodel import Session, select
        from app.models import MorningBriefingPacket, MorningBriefingRecord
        with Session(self.engine) as db:
            row = db.exec(select(MorningBriefingRecord).join(MorningBriefingPacket)
                          .where(MorningBriefingPacket.day == today, MorningBriefingRecord.redacted_at.is_(None),
                                 MorningBriefingPacket.redacted_at.is_(None))
                          .order_by(MorningBriefingRecord.created_at.desc(), MorningBriefingRecord.id.desc())).first()
        if row is None:
            return []
        body = json.loads(row.body_json)
        return [(item["symbol"], item, f"{today.isoformat()}:{item['symbol']}") for item in body.get("opportunities") or []
                if item.get("status") == "conditional" and item.get("symbol")]

    # ------------------------------------------------------------ entries and exits

    def _step(self, today: date, now: float, inside: bool, close_at: float | None) -> None:
        live = self.store.live()
        wanted: list[dict] = []
        for row in live:
            if row["day"] != today.isoformat() and row["state"] == "open":
                # Entered but never given a fresh exit quote: closed at the last bid seen (zero if none), so a trade
                # that could not get out still counts against its source.
                mark = row["mark"] or 0.0
                scored = scanner_rules.result({"bid": row["entry_bid"], "ask": row["entry"]},
                                              {"bid": mark, "ask": row["mark_ask"] or mark}, int(row["contract"].get("multiplier") or 100))
                self.store.update(row["id"], "open", state="closed", exit=mark, reason="no_exit", pnl=scored["pnl"],
                                  pnl_2x=scored["pnl_2x_spread"],
                                  note=f"no fresh exit quote in session {row['day']}; closed at the last bid seen")
            elif row["day"] != today.isoformat():
                self.store.update(row["id"], row["state"], state="unresolved",
                                  note=f"session {row['day']} ended with the trade still {row['state']}; nothing is carried overnight")
            elif not inside:
                continue
            elif row["state"] == "pending" and now - row["created_at"] > ENTRY_WINDOW_SECONDS:
                self.store.update(row["id"], "pending", state="unresolved", note="no fresh option quote within 2 minutes")
            else:
                wanted.append(row)
        if not wanted:
            return
        quotes = self.quotes(sorted({r["contract"]["symbol"] for r in wanted}))
        for row in wanted:
            quote = quotes.get(row["contract"]["symbol"])
            if row["state"] == "pending":
                fill = entry_fill(_PLAN, quote, row["created_at"])
                if fill is not None:
                    self.store.update(row["id"], "pending", state="open", entry=fill["price"], entry_bid=fill["bid"], entry_at=now)
                continue
            if quote is not None and quote.bid is not None:
                self.store.update(row["id"], "open", mark=quote.bid, mark_ask=quote.ask)
            reason = bracket(row, quote, now, close_at)
            if reason is None or not fresh(quote, row["entry_at"]):
                continue  # the clock exits wait for a fresh quote, as the setup cards' paper book does
            scored = scanner_rules.result({"bid": row["entry_bid"], "ask": row["entry"]}, {"bid": quote.bid, "ask": quote.ask},
                                          int(row["contract"].get("multiplier") or 100))
            self.store.update(row["id"], "open", state="closed", exit=quote.bid, exit_at=now, reason=reason,
                              pnl=scored["pnl"], pnl_2x=scored["pnl_2x_spread"])


def ground_from_env(engine) -> ProvingGround | None:
    if not enabled():
        return None
    if not tradier.tradier_configured():
        log.error("PROVING_GROUND_ENABLED needs TRADIER_API_KEY; the proving ground stays off")
        return None
    from app.engine.chart_calendar import chart_calendar
    return ProvingGround(engine, chart_calendar)
