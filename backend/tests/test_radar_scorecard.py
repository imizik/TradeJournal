"""The Radar scorecard (app/engine/radar_scorecard.py): each stock Radar hit, the decision logged on the desk after it,
and what the stock did against SPY in the hit's direction, with hand-worked numbers."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import radar_proof, radar_scorecard
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore
from app.models import DayJournalEntry

DONE, TODAY = "2026-10-27", "2026-10-28"
NOW = datetime(2026, 10, 28, 16, 0, tzinfo=UTC).timestamp()  # 12:00 New York, Oct 28
FLAT = {s: 100.0 for s in ("SPY", "AAA", "BBB", "FFF")}


def _at(hh_mm: str, session: str) -> float:
    return datetime.fromisoformat(f"{session}T{hh_mm}:00").replace(tzinfo=ET).timestamp()


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pass(store, hh_mm, prices, session=DONE):
    at = _at(hh_mm, session)
    record = {"session_date": session, "started_at": _stamp(at), "finished_at": _stamp(at + 5), "universe_version": "t",
              "status": "ok", "symbols_requested": 4, "symbols_returned": 4, "unmatched": [], "requests_used": 1, "error": None,
              "skip_reason": None}
    store.append_pass(record, [{"symbol": s, "last": p, "prev_close": 100, "open": 100, "high": None, "low": None, "volume": 1,
                                "bid": None, "ask": None, "trade_time_ms": (at - 1) * 1000, "retrieved_at": _stamp(at + 2)}
                               for s, p in prices.items()])
    return record


def _event(store, event_id, kind, direction, symbols, seen, session=DONE):
    store.append_event({"event_id": event_id, "session_date": session, "rule_version": "radar-rules-v1", "universe_version": "t",
                        "kind": kind, "direction": direction, "symbols": symbols, "benchmark": "SPY", "group": None,
                        "first_seen_at": seen["finished_at"], "summary": f"{symbols[0]} {direction}", "measures": {},
                        "evidence": [], "coverage": {}, "chart": {}})


def _decide(db, symbol, text, day, hh_mm):
    at = datetime.fromisoformat(f"{day}T{hh_mm}:00").replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None)
    db.add(DayJournalEntry(operation_id=f"{symbol}-{day}-{hh_mm}", day=date.fromisoformat(day), kind="decision", text=text,
                           symbol=symbol, created_at=at))
    db.commit()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def store(tmp_path):
    s = RadarStore(tmp_path / "radar.sqlite")
    start = _pass(s, "10:00", FLAT)
    hour = _pass(s, "11:00", {**FLAT, "SPY": 101.0, "AAA": 104.0, "FFF": 98.0})  # AAA +4% vs SPY +1%; FFF −2%
    _pass(s, "15:59", {**FLAT, "AAA": 99.0})                                     # close: AAA −1% vs a flat SPY
    _event(s, "aaa1", "relative_to_spy", "up", ["AAA"], start)
    _event(s, "fff", "relative_to_sector", "down", ["FFF"], start)
    _event(s, "pair", "group_move", "up", ["AAA", "BBB"], start)               # names no one stock: left out
    _event(s, "aaa2", "relative_to_spy", "up", ["AAA"], hour)
    live = _pass(s, "10:00", FLAT, session=TODAY)
    _pass(s, "11:01", {**FLAT, "BBB": 102.0}, session=TODAY)                     # within the scorer's two-minute tolerance
    _event(s, "bbb", "relative_to_spy", "up", ["BBB"], live, session=TODAY)
    old = _pass(s, "10:00", FLAT, session="2026-09-20")
    _event(s, "old", "relative_to_spy", "up", ["AAA"], old, session="2026-09-20")  # older than the window
    return s


def test_each_hit_shows_its_decision_and_the_move_after_it_in_the_hit_s_direction(store, db, monkeypatch):
    monkeypatch.setattr(radar_proof, "planned_events", lambda db, ids: {"aaa2": {"planned": True, "traded": False}})
    _decide(db, "AAA", "Watching. Radar: AAA up.", DONE, "10:05")
    _decide(db, "AAA", "Holding. Give-back fired.", DONE, "10:06")  # a position decision is not a Radar one
    _decide(db, "AAA", "Planning. Radar: AAA up.", DONE, "11:02")   # after the second hit: it answers that one
    _decide(db, "FFF", "Passing. Radar: FFF down.", TODAY, "09:40")  # the next day answers nothing
    card = radar_scorecard.scorecard(store, db, NOW)
    by = {r["event_id"]: r for r in card["rows"]}
    assert [r["event_id"] for r in card["rows"]] == ["bbb", "aaa2", "fff", "aaa1"]  # newest first; group and old left out
    assert (by["aaa1"]["decision"], by["aaa2"]["decision"], by["fff"]["decision"]) == ("watching", "planning", None)
    assert by["aaa1"]["after"] == {"hour_pct": 3.0, "close_pct": -1.0, "why": None}
    assert by["fff"]["after"] == {"hour_pct": 3.0, "close_pct": 0.0, "why": None}  # down 2% as SPY rose 1%: it kept going
    assert by["aaa2"]["after"] == {"hour_pct": None, "close_pct": -3.82, "why": "no pass recorded then"}
    assert by["bbb"]["after"] == {"hour_pct": 2.0, "close_pct": None, "why": "the session is still open"}
    assert (by["aaa2"]["planned"], by["aaa1"]["planned"], by["fff"]["kind_label"]) == (True, False, "vs sector")
    assert card["summary"] == {
        "watching": {"hits": 1, "measured": 1, "kept_going": 0, "avg_close_pct": -1.0},
        "passing": {"hits": 0, "measured": 0, "kept_going": 0, "avg_close_pct": None},
        "planning": {"hits": 1, "measured": 1, "kept_going": 0, "avg_close_pct": -3.82},
        "none": {"hits": 2, "measured": 1, "kept_going": 0, "avg_close_pct": 0.0},
    }
    assert (card["hits"], card["window_days"], card["truncated"]) == (4, 30, False)


def test_a_hit_whose_pass_is_missing_is_not_measured(tmp_path, db):
    s = RadarStore(tmp_path / "radar.sqlite")
    seen = {"finished_at": _stamp(_at("10:00", DONE) + 5)}
    _event(s, "ghost", "relative_to_spy", "up", ["AAA"], seen)
    [row] = radar_scorecard.scorecard(s, db, NOW)["rows"]
    assert row["after"] == {"hour_pct": None, "close_pct": None, "why": "the pass it was seen in was not recorded"}


def test_the_route_carries_the_radar_card_and_says_when_the_file_is_unreadable(store, db, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app.routers import copilot_desk, radar
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(copilot_desk.today, "_now", lambda: NOW)
    monkeypatch.setattr(radar, "_store", lambda read_only=False: (store, None))
    assert copilot_desk.desk_scorecard(db)["radar"]["hits"] == 4

    def broken(*_args, **_kwargs):
        raise ValueError("damaged")
    monkeypatch.setattr(radar_scorecard, "scorecard", broken)
    assert copilot_desk.desk_scorecard(db)["radar"] == {"state": "unavailable", "reason": "The Radar file could not be read right now."}
