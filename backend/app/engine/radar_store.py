"""Radar PR 1: the recorder's own append-only SQLite file.

Radar (selected 2026-10-21, see ``docs/radar.md``) records one Tradier quote
pass a minute over the tracked symbol list in ``app/data/radar_universe.json``.
Every pass, quote, event and event revision lives in an owner-selected SQLite
file, separate from the journal Postgres (no Alembic migration) and from every
other store. Pass, event and revision rows are never updated or deleted; quote
rows are never updated and are pruned only past ``RETENTION_SESSIONS``.

This PR defines the event and revision shape that the detection PR will write;
nothing here detects anything.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Literal, TypedDict

APPLICATION_ID = 0x52414431  # RAD1: the isolated Radar recorder file; foreign files are never adopted.
RETENTION_SESSIONS = 60
UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "radar_universe.json"

TABLES = {"pass", "quote", "event", "event_revision", "visit", "feedback", "event_news"}
RATINGS = ("useful", "already_knew", "too_late", "irrelevant")
NEWS_STATUSES = ("found", "none_found", "unavailable")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pass(id INTEGER PRIMARY KEY AUTOINCREMENT, session_date TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL, universe_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok','partial','failed','skipped')),
  symbols_requested INTEGER NOT NULL, symbols_returned INTEGER NOT NULL, unmatched TEXT NOT NULL,
  requests_used INTEGER NOT NULL, error TEXT, skip_reason TEXT);
CREATE INDEX IF NOT EXISTS pass_session ON pass(session_date);
CREATE TABLE IF NOT EXISTS quote(pass_id INTEGER NOT NULL REFERENCES pass(id), session_date TEXT NOT NULL,
  symbol TEXT NOT NULL, last REAL, prev_close REAL, open REAL, high REAL, low REAL, volume INTEGER,
  bid REAL, ask REAL, trade_time_ms INTEGER, retrieved_at TEXT NOT NULL, PRIMARY KEY(pass_id, symbol));
CREATE INDEX IF NOT EXISTS quote_session ON quote(session_date, symbol);
CREATE TABLE IF NOT EXISTS event(event_id TEXT PRIMARY KEY, session_date TEXT NOT NULL, rule_version TEXT NOT NULL,
  universe_version TEXT NOT NULL, kind TEXT NOT NULL, first_seen_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_session ON event(session_date);
CREATE TABLE IF NOT EXISTS event_revision(event_id TEXT NOT NULL REFERENCES event(event_id), revision INTEGER NOT NULL,
  recorded_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(event_id, revision));
CREATE TABLE IF NOT EXISTS visit(id INTEGER PRIMARY KEY AUTOINCREMENT, visited_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES event(event_id),
  rating TEXT NOT NULL CHECK(rating IN ('useful','already_knew','too_late','irrelevant')), recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS feedback_event ON feedback(event_id);
CREATE TABLE IF NOT EXISTS event_news(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES event(event_id),
  checked_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('found','none_found','unavailable')), headlines TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_news_event ON event_news(event_id);
CREATE TRIGGER IF NOT EXISTS event_news_no_update BEFORE UPDATE ON event_news BEGIN SELECT RAISE(ABORT,'radar news checks are immutable'); END;
CREATE TRIGGER IF NOT EXISTS event_news_no_delete BEFORE DELETE ON event_news BEGIN SELECT RAISE(ABORT,'radar news checks are immutable'); END;
CREATE TRIGGER IF NOT EXISTS visit_no_update BEFORE UPDATE ON visit BEGIN SELECT RAISE(ABORT,'radar visits are immutable'); END;
CREATE TRIGGER IF NOT EXISTS visit_no_delete BEFORE DELETE ON visit BEGIN SELECT RAISE(ABORT,'radar visits are immutable'); END;
CREATE TRIGGER IF NOT EXISTS feedback_no_update BEFORE UPDATE ON feedback BEGIN SELECT RAISE(ABORT,'radar feedback is immutable'); END;
CREATE TRIGGER IF NOT EXISTS feedback_no_delete BEFORE DELETE ON feedback BEGIN SELECT RAISE(ABORT,'radar feedback is immutable'); END;
CREATE TRIGGER IF NOT EXISTS pass_no_update BEFORE UPDATE ON pass BEGIN SELECT RAISE(ABORT,'radar passes are immutable'); END;
CREATE TRIGGER IF NOT EXISTS pass_no_delete BEFORE DELETE ON pass BEGIN SELECT RAISE(ABORT,'radar passes are immutable'); END;
CREATE TRIGGER IF NOT EXISTS quote_no_update BEFORE UPDATE ON quote BEGIN SELECT RAISE(ABORT,'radar quotes are immutable'); END;
CREATE TRIGGER IF NOT EXISTS event_no_update BEFORE UPDATE ON event BEGIN SELECT RAISE(ABORT,'radar events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON event BEGIN SELECT RAISE(ABORT,'radar events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS revision_no_update BEFORE UPDATE ON event_revision BEGIN SELECT RAISE(ABORT,'radar revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS revision_no_delete BEFORE DELETE ON event_revision BEGIN SELECT RAISE(ABORT,'radar revisions are immutable'); END;
"""

PassStatus = Literal["ok", "partial", "failed", "skipped"]
EventKind = Literal["relative_to_spy", "relative_to_sector", "group_move"]
EventDirection = Literal["up", "down"]


class RadarPass(TypedDict):
    session_date: str
    started_at: str
    finished_at: str
    universe_version: str
    status: PassStatus
    symbols_requested: int
    symbols_returned: int
    unmatched: list[str]
    requests_used: int
    error: str | None
    skip_reason: str | None


class RadarQuote(TypedDict):
    symbol: str
    last: float | None
    prev_close: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: int | None
    bid: float | None
    ask: float | None
    trade_time_ms: int | None  # Tradier's own trade_date, unmodified
    retrieved_at: str


class RadarEvidence(TypedDict):
    symbol: str
    pass_id: int
    retrieved_at: str
    last: float
    change_pct: float  # versus prev_close


class RadarCoverage(TypedDict):
    passes_expected: int
    passes_recorded: int
    symbols_missing: list[str]


class RadarEvent(TypedDict):
    """One meaningful change, as the detection PR will write it (shape only here)."""
    event_id: str
    session_date: str
    rule_version: str
    universe_version: str
    kind: EventKind
    direction: EventDirection
    symbols: list[str]
    benchmark: str  # SPY, a sector ETF, or the group name for a group move
    group: str | None
    first_seen_at: str
    summary: str
    measures: dict[str, float]  # e.g. {"relative_pct": 3.1, "volume_ratio": 2.4}
    evidence: list[RadarEvidence]
    coverage: RadarCoverage
    chart: dict[str, str]  # {"symbol": ..., "from": ..., "to": ...} for the chart link


class RadarNewsHeadline(TypedDict):
    headline: str
    source: str | None
    published_at: str
    url: str
    symbols: list[str]
    timing: Literal["before", "after"]  # published before or after the event's first_seen_at


class RadarEventNews(TypedDict):
    """One news check of an event, saved beside it; the event itself is never rewritten."""
    event_id: str
    checked_at: str
    status: Literal["found", "none_found", "unavailable"]
    headlines: list[RadarNewsHeadline]


class RadarEventRevision(TypedDict):
    """A later reading of the same event; revisions never replace the original."""
    event_id: str
    revision: int  # 1, 2, ...
    recorded_at: str
    status: Literal["extended", "faded", "reversed", "corrected"]
    measures: dict[str, float]
    evidence: list[RadarEvidence]
    note: str


_EVENT_FIELDS = set(RadarEvent.__annotations__)
_REVISION_FIELDS = set(RadarEventRevision.__annotations__)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def load_universe(path: Path = UNIVERSE_PATH) -> dict:
    """The tracked symbol list; refuses duplicates and group members that are not listed."""
    data = json.loads(Path(path).read_text())
    version = data.get("version")
    symbols = [row["symbol"] for row in data["symbols"]]
    if not isinstance(version, str) or not version or not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("radar universe needs a version and unique symbols")
    if any(row["kind"] not in ("etf", "stock") for row in data["symbols"]):
        raise ValueError("radar universe kinds are etf or stock")
    if any(m not in set(symbols) for group in data["groups"] for m in group["members"]):
        raise ValueError("radar group member missing from the symbol list")
    return data


class RadarStore:
    """Explicit owner-selected SQLite file for Radar's quote passes and events."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("radar store path must be absolute")
        if self.path.is_symlink():
            raise ValueError("radar store may not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            marker = db.execute("PRAGMA application_id").fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if marker == 0 and not tables:
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            elif marker != APPLICATION_ID or not tables <= TABLES:
                raise ValueError("refusing to adopt a non-Radar database")
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def append_pass(self, record: RadarPass, quotes: list[RadarQuote] = ()) -> int:
        """One pass and its quote rows in one transaction; returns the pass id."""
        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO pass(session_date, started_at, finished_at, universe_version, status, symbols_requested,"
                " symbols_returned, unmatched, requests_used, error, skip_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (record["session_date"], record["started_at"], record["finished_at"], record["universe_version"],
                 record["status"], record["symbols_requested"], record["symbols_returned"], _json(record["unmatched"]),
                 record["requests_used"], record["error"], record["skip_reason"]))
            pass_id = cursor.lastrowid
            db.executemany(
                "INSERT INTO quote VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(pass_id, record["session_date"], q["symbol"], q["last"], q["prev_close"], q["open"], q["high"], q["low"],
                  q["volume"], q["bid"], q["ask"], q["trade_time_ms"], q["retrieved_at"]) for q in quotes])
        return pass_id

    def passes(self, session_date: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM pass", ()
        if session_date:
            sql, args = sql + " WHERE session_date=?", (session_date,)
        with self._db() as db:
            rows = [dict(row) for row in db.execute(sql + " ORDER BY id", args)]
        for row in rows:
            row["unmatched"] = json.loads(row["unmatched"])
        return rows

    def quotes(self, pass_id: int | None = None, session_date: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM quote WHERE 1=1", []
        if pass_id is not None:
            sql, args = sql + " AND pass_id=?", args + [pass_id]
        if session_date:
            sql, args = sql + " AND session_date=?", args + [session_date]
        with self._db() as db:
            return [dict(row) for row in db.execute(sql + " ORDER BY pass_id, symbol", args)]

    def append_event(self, event: RadarEvent) -> None:
        if set(event) != _EVENT_FIELDS:
            raise ValueError("radar event fields do not match RadarEvent")
        with self._db() as db:
            db.execute("INSERT INTO event VALUES(?,?,?,?,?,?,?)",
                       (event["event_id"], event["session_date"], event["rule_version"], event["universe_version"],
                        event["kind"], event["first_seen_at"], _json(event)))

    def append_revision(self, revision: RadarEventRevision) -> None:
        if set(revision) != _REVISION_FIELDS:
            raise ValueError("radar revision fields do not match RadarEventRevision")
        with self._db() as db:
            db.execute("INSERT INTO event_revision VALUES(?,?,?,?)",
                       (revision["event_id"], revision["revision"], revision["recorded_at"], _json(revision)))

    def events(self, session_date: str | None = None) -> list[dict]:
        sql, args = "SELECT payload FROM event", ()
        if session_date:
            sql, args = sql + " WHERE session_date=?", (session_date,)
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute(sql + " ORDER BY rowid", args)]

    def revisions(self, event_id: str) -> list[dict]:
        with self._db() as db:
            return [json.loads(row[0]) for row in
                    db.execute("SELECT payload FROM event_revision WHERE event_id=? ORDER BY revision", (event_id,))]

    def event(self, event_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT payload FROM event WHERE event_id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def sessions(self) -> list[str]:
        """Every session date with a pass or an event, newest first."""
        with self._db() as db:
            return [row[0] for row in db.execute(
                "SELECT session_date FROM pass UNION SELECT session_date FROM event ORDER BY 1 DESC")]

    def append_visit(self, visited_at: str) -> None:
        with self._db() as db:
            db.execute("INSERT INTO visit(visited_at) VALUES(?)", (visited_at,))

    def last_visit(self) -> str | None:
        with self._db() as db:
            row = db.execute("SELECT visited_at FROM visit ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def append_feedback(self, event_id: str, rating: str, recorded_at: str) -> None:
        if rating not in RATINGS:
            raise ValueError("unknown radar rating")
        with self._db() as db:
            db.execute("INSERT INTO feedback(event_id, rating, recorded_at) VALUES(?,?,?)", (event_id, rating, recorded_at))

    def latest_ratings(self) -> dict[str, str]:
        """The newest rating per event; earlier ratings stay in the table."""
        with self._db() as db:
            return {row[0]: row[1] for row in db.execute("SELECT event_id, rating FROM feedback ORDER BY id")}

    def append_news(self, check: RadarEventNews) -> None:
        if check["status"] not in NEWS_STATUSES:
            raise ValueError("unknown radar news status")
        with self._db() as db:
            db.execute("INSERT INTO event_news(event_id, checked_at, status, headlines) VALUES(?,?,?,?)",
                       (check["event_id"], check["checked_at"], check["status"], _json(check["headlines"])))

    def news_checks(self, event_id: str) -> list[RadarEventNews]:
        """Every news check of one event, oldest first."""
        with self._db() as db:
            rows = db.execute("SELECT event_id, checked_at, status, headlines FROM event_news WHERE event_id=? ORDER BY id",
                              (event_id,)).fetchall()
        return [{**dict(row), "headlines": json.loads(row["headlines"])} for row in rows]

    def latest_news(self) -> dict[str, RadarEventNews]:
        """The newest news check per event; earlier checks stay in the table."""
        with self._db() as db:
            rows = db.execute("SELECT event_id, checked_at, status, headlines FROM event_news ORDER BY id").fetchall()
        return {row["event_id"]: {**dict(row), "headlines": json.loads(row["headlines"])} for row in rows}

    def prune_quotes(self, keep_sessions: int = RETENTION_SESSIONS) -> int:
        """Delete quote rows older than the newest ``keep_sessions`` recorded sessions; passes and events stay."""
        with self._db() as db:
            cut = db.execute("SELECT DISTINCT session_date FROM quote ORDER BY session_date DESC LIMIT 1 OFFSET ?",
                             (keep_sessions,)).fetchone()
            if cut is None:
                return 0
            return db.execute("DELETE FROM quote WHERE session_date<=?", (cut[0],)).rowcount
