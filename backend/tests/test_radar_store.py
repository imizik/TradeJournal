"""Radar PR 1: the recorder's isolated SQLite file and the tracked symbol list."""
import json
from pathlib import Path
import sqlite3

import pytest

from app.engine.radar_store import APPLICATION_ID, RadarStore, load_universe

FIXTURE = Path(__file__).parent / "fixtures" / "radar" / "sample_event.json"


def _pass(session="2026-10-20", status="ok"):
    return {"session_date": session, "started_at": f"{session}T14:00:00.000Z", "finished_at": f"{session}T14:00:01.000Z",
            "universe_version": "radar-universe-v1", "status": status, "symbols_requested": 1, "symbols_returned": 1,
            "unmatched": [], "requests_used": 1, "error": None, "skip_reason": None}


def _quote(symbol="MU"):
    return {"symbol": symbol, "last": 200.0, "prev_close": 195.0, "open": 196.0, "high": 201.0, "low": 195.5,
            "volume": 1000, "bid": 199.9, "ask": 200.1, "trade_time_ms": 1792500000000,
            "retrieved_at": "2026-10-20T14:00:00.900Z"}


def test_store_refuses_relative_paths_symlinks_and_foreign_databases(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        RadarStore("radar.sqlite")
    real = tmp_path / "real.sqlite"
    RadarStore(real)
    link = tmp_path / "link.sqlite"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        RadarStore(link)
    foreign = tmp_path / "foreign.sqlite"
    sqlite3.connect(foreign).execute("CREATE TABLE fills(id)").connection.commit()
    with pytest.raises(ValueError, match="non-Radar"):
        RadarStore(foreign)
    other_app = tmp_path / "other.sqlite"
    db = sqlite3.connect(other_app)
    db.execute("PRAGMA application_id=1")
    db.execute("CREATE TABLE pass(id)")
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="non-Radar"):
        RadarStore(other_app)
    assert sqlite3.connect(real).execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
    RadarStore(real)  # its own file reopens


def test_rows_are_append_only(tmp_path):
    store = RadarStore(tmp_path / "radar.sqlite")
    pass_id = store.append_pass(_pass(), [_quote()])
    assert store.passes()[0]["id"] == pass_id and store.quotes(pass_id)[0]["prev_close"] == 195.0
    data = json.loads(FIXTURE.read_text())
    store.append_event(data["event"])
    store.append_revision(data["revisions"][0])
    db = sqlite3.connect(store.path, isolation_level=None)
    for sql in ("UPDATE pass SET status='failed'", "DELETE FROM pass", "UPDATE quote SET last=1",
                "UPDATE event SET kind='x'", "DELETE FROM event", "UPDATE event_revision SET revision=9",
                "DELETE FROM event_revision"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        store.append_event(data["event"])  # same event id twice
    with pytest.raises(sqlite3.IntegrityError):
        store.append_pass({**_pass()}, [_quote(), _quote()])  # one row per symbol per pass
    assert len(store.passes()) == 1  # the failed pass left nothing behind


def test_sample_event_fixture_matches_the_typed_shape(tmp_path):
    store = RadarStore(tmp_path / "radar.sqlite")
    data = json.loads(FIXTURE.read_text())
    store.append_event(data["event"])
    store.append_revision(data["revisions"][0])
    assert store.events("2026-10-20") == [data["event"]]
    assert store.revisions(data["event"]["event_id"]) == data["revisions"]
    with pytest.raises(ValueError, match="RadarEvent"):
        store.append_event({**data["event"], "extra": 1})


def test_prune_keeps_the_newest_sessions_and_every_event(tmp_path):
    store = RadarStore(tmp_path / "radar.sqlite")
    for day in range(1, 6):
        store.append_pass(_pass(f"2026-10-0{day}"), [_quote()])
    store.append_event(json.loads(FIXTURE.read_text())["event"])
    assert store.prune_quotes(keep_sessions=3) == 2
    assert sorted({q["session_date"] for q in store.quotes()}) == ["2026-10-03", "2026-10-04", "2026-10-05"]
    assert len(store.passes()) == 5 and len(store.events()) == 1
    assert store.prune_quotes(keep_sessions=3) == 0


def test_tracked_universe_is_valid_and_keeps_the_benchmarks():
    universe = load_universe()
    symbols = {row["symbol"]: row for row in universe["symbols"]}
    assert universe["version"] == "radar-universe-v2" and len(symbols) == 169
    benchmarks = {"SPY", "QQQ", "IWM", "RSP", "SMH", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE",
                  "XLU", "XLV", "XLY"}
    assert {s for s, row in symbols.items() if row["benchmark"]} == benchmarks
    assert all(symbols[s]["kind"] == "etf" for s in benchmarks)
    assert "GOOGL" in symbols and "GOOG" not in symbols
    assert {"EA", "SQ", "GOOG"} == {row["symbol"] for row in universe["excluded"]}
    assert all(row["sources"] for row in symbols.values())
