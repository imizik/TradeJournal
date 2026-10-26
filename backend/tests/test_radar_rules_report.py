"""The rules report (scripts/radar_rules_report.py) on a small invented store: read-only, deterministic, per version."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

import pytest

from app.engine import radar_rules
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore
from scripts import radar_rules_report as report

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "radar" / "rules_report_sessions.json").read_text())
UNIVERSE = FIXTURE["universe"]


def _iso(value: datetime) -> str:
    return radar_rules._iso(value.timestamp())


def _price(steps, minute):
    value = 100.0
    for at, price in steps:
        if minute >= at:
            value = price
    return value


@pytest.fixture
def store(tmp_path) -> Path:
    """The fixture sessions recorded as the live recorder would, with v0's events and the ratings saved."""
    live = RadarStore(tmp_path / "radar.sqlite")
    for day in FIXTURE["sessions"]:
        start = datetime.fromisoformat(day["date"]).replace(hour=9, minute=30, tzinfo=ET)
        for i in range(1, day["minutes"] + 1):
            at = start + timedelta(minutes=i)
            quotes = [{"symbol": row["symbol"], "last": _price(day["paths"].get(row["symbol"], []), i), "prev_close": 100.0,
                       "open": 100.0, "high": None, "low": None, "volume": 1000, "bid": None, "ask": None,
                       "trade_time_ms": int(at.timestamp() * 1000), "retrieved_at": _iso(at + timedelta(seconds=1))}
                      for row in UNIVERSE["symbols"]]
            live.append_pass({"session_date": day["date"], "started_at": _iso(at), "finished_at": _iso(at + timedelta(seconds=2)),
                              "universe_version": UNIVERSE["version"], "status": "ok", "symbols_requested": len(quotes),
                              "symbols_returned": len(quotes), "unmatched": [], "requests_used": 1, "error": None,
                              "skip_reason": None}, quotes)
        passes = radar_rules.session_passes(live.passes(day["date"]), day["date"])
        for event, revisions in radar_rules.replay(UNIVERSE, passes, live.pass_quotes(p["id"] for p in passes)):
            live.append_event(event)
            for revision in revisions:
                live.append_revision(revision)
    for row in FIXTURE["ratings"]:
        live.append_feedback(row["event_id"], row["rating"], "2030-01-16T21:00:00.000Z")
    return live.path


def _build(path, versions=None):
    versions = versions or list(radar_rules.VERSIONS.values())
    return report.build_report(RadarStore(path, read_only=True), versions, universe=UNIVERSE)


def test_events_per_session_and_version(store):
    text = _build(store)
    assert "Store snapshot: 2 sessions (2030-01-15 (partial, to 10:40 ET), 2030-01-16 (partial, to 10:30 ET))" in text
    assert "ratings recorded: 2" in text
    assert "| v1 | spy_relative_pct 4.5 → 4.0, persist_passes 3 → 2 |" in text
    assert "| 2030-01-15 (partial, to 10:40 ET) | v0 | 1 | 1 / 0 | 0 / 0 | 0 / 0 |" in text
    assert "| 2030-01-15 (partial, to 10:40 ET) | v1 | 2 | 2 / 0 | 0 / 0 | 0 / 0 |" in text
    assert "| 2030-01-16 (partial, to 10:30 ET) | v1 | 2 | 1 / 1 | 0 / 0 | 0 / 0 |" in text
    assert "| **All** | v0 | 2 |" in text and "| **All** | v1 | 4 |" in text


def test_each_v1_change_alone_and_together(store):
    text = _build(store)
    section = text.split("## What v1 changes")[1].split("##")[0]
    assert "| spy_relative_pct 4.5 → 4.0 | 3 (+1) | 1 | 0 | 0 | 0 |" in section  # BBB at 4.2 points
    assert "| persist_passes 3 → 2 | 3 (+1) | 1 | 0 | 1 | 0 |" in section  # DDD held two passes, faded the next
    assert "| all together | 4 (+2) | 2 | 0 | 1 | 0 | 01-15 BBB up, 01-16 DDD up |" in section


def test_added_events_and_timing_against_v0(store):
    section = _build(store).split("## v1 against v0, event by event")[1].split("## Ratings")[0]
    assert "**2030-01-15 (partial, to 10:40 ET):** 1 added, 0 dropped; the 1 shared fire a median 1 min earlier" in section
    assert "| added | 10:06 | relative_to_spy | BBB up | BBB ahead of SPY by 4.2% over 30 min" in section
    assert "| added | 10:06 | relative_to_spy | DDD up |" in section  # held on 10:05 and 10:06 only


def test_readings_near_the_thresholds(store):
    text = _build(store)
    spy = text.split("| Stock vs SPY ≥ |")[1].split("\n\n")[0]
    # AAA (6 points) and BBB (4.2) read from minute 35 until the window starts past the jump (64): 30 passes each;
    # CCC to the session's end at 60, DDD on two passes only
    assert "| 4.0 | 60 / 2 / 2 / 2 | 28 / 2 / 2 / 1 |" in spy
    assert "| 4.5 | 30 / 1 / 1 / 1 | 28 / 2 / 2 / 1 |" in spy


def test_ratings_survive_by_version(store):
    strict = report.variant("spy_relative_pct=7.0")
    assert strict.version == "radar-rules-v0+spy_relative_pct=7.0"
    text = _build(store, [radar_rules.V0, radar_rules.V1, strict])
    assert "| Rating | Rated | Survive v0 | Survive v1 | Survive v0+spy_relative_pct=7.0 |" in text
    assert "| useful | 1 | 1 | 1 | 0 |" in text  # AAA's 6 points is under 7
    assert "| not useful (all) | 1 | 1 | 1 | 0 |" in text and "|   irrelevant | 1 | 1 | 1 | 0 |" in text
    assert "| 2030-01-15 | 10:07 | relative_to_spy AAA up | radar-rules-v0 | useful | fires | fires | — |" in text


def test_report_is_deterministic_read_only_and_written_by_the_cli(store, tmp_path, monkeypatch):
    digest = hashlib.sha256(store.read_bytes()).hexdigest()
    first = _build(store)
    assert first == _build(store)
    assert hashlib.sha256(store.read_bytes()).hexdigest() == digest
    monkeypatch.setattr(report, "load_universe", lambda: UNIVERSE)
    out = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["radar_rules_report.py", str(store), "--out", str(out)])
    report.main()
    assert out.read_text() == first
    assert hashlib.sha256(store.read_bytes()).hexdigest() == digest


def test_an_event_too_close_to_the_last_pass_is_unresolved_not_held():
    event = {"first_seen_at": "2030-01-15T15:20:00.000Z"}
    assert report.outcome(event, [], "2030-01-15T15:30:00.000Z") == "unresolved"
    assert report.outcome(event, [], "2030-01-15T15:40:00.000Z") == "no revision"
    faded = [{"status": "faded", "recorded_at": "2030-01-15T15:25:00.000Z"}]
    assert report.outcome(event, faded, "2030-01-15T15:30:00.000Z") == "quick faded 10:25"


def test_no_ratings_says_so(tmp_path):
    empty = RadarStore(tmp_path / "empty.sqlite")
    text = report.build_report(RadarStore(empty.path, read_only=True), [radar_rules.V0], universe=UNIVERSE)
    assert "No recorded event has a rating yet" in text


def test_unknown_try_field_is_refused():
    with pytest.raises(SystemExit):
        report.variant("version=x")
