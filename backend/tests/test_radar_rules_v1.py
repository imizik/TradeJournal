"""The candidate ``radar-rules-v1`` (two passes, 4.0 points vs SPY) and its selection; v0 is covered by test_radar_rules."""
import logging
import sqlite3

import pytest

from app.engine import radar_rules, radar_runner, tradier
from tests.test_radar_rules import DAY, UNIVERSE, _pass, _runner, _store_with, kinds, session, steps


def run(paths, thresholds, minutes=70):
    passes, quotes = session(paths, minutes)
    return radar_rules.replay(UNIVERSE, passes, quotes, thresholds)


def test_v1_changes_only_the_spy_threshold_and_persistence():
    assert radar_rules.RULE_VERSION == "radar-rules-v0" and radar_rules.V0.version == "radar-rules-v0"
    assert radar_rules.V0.spy_relative_pct == 4.5 and radar_rules.V0.persist_passes == 3
    changed = {f: (getattr(radar_rules.V0, f), getattr(radar_rules.V1, f))
               for f in radar_rules.Thresholds.__dataclass_fields__ if getattr(radar_rules.V0, f) != getattr(radar_rules.V1, f)}
    assert changed == {"version": ("radar-rules-v0", "radar-rules-v1"), "spy_relative_pct": (4.5, 4.0),
                       "persist_passes": (3, 2)}
    assert list(radar_rules.VERSIONS) == ["radar-rules-v0", "radar-rules-v1"]


def test_v1_fires_a_pass_earlier_with_its_own_id_and_version():
    [(event, _)] = run({"AAA": steps((35, 106.0))}, radar_rules.V1)
    assert event["event_id"] == "rv1-2030-01-15-spy-aaa-up-1" and event["rule_version"] == "radar-rules-v1"
    assert event["first_seen_at"] == _pass(36)["finished_at"]  # 35 and 36; v0 waits for 37
    [(v0_event, _)] = run({"AAA": steps((35, 106.0))}, radar_rules.V0)
    assert v0_event["event_id"] == "rv0-2030-01-15-spy-aaa-up-1" and v0_event["first_seen_at"] == _pass(37)["finished_at"]


@pytest.mark.parametrize("paths", [
    {"AAA": steps((35, 104.2))},  # 4.2 points: under v0's 4.5, over v1's 4.0
    {"AAA": steps((35, 106.0), (37, 100.0))},  # held on two passes only
])
def test_v1_fires_where_v0_does_not(paths):
    assert kinds(run(paths, radar_rules.V0, minutes=60)) == []  # 60 minutes: before the drop back shows as a down move
    assert kinds(run(paths, radar_rules.V1, minutes=60)) == [("relative_to_spy", "AAA", "up")]


@pytest.mark.parametrize("paths", [
    {"AAA": steps((35, 103.8))},  # 3.8 points is under v1 too
    {"AAA": steps((35, 106.0), (36, 100.0))},  # one pass
    {"XLK": steps((35, 94.0)), "BBB": steps((35, 97.8))},  # 3.8 vs a falling sector: the sector rule is still 4.5
])
def test_v1_still_needs_its_thresholds(paths):
    assert kinds(run(paths, radar_rules.V1)) == []


def test_v1_skips_a_sector_event_once_spy_qualifies_at_four_points():
    # BBB +4.2% against a flat SPY and a falling XLK: v0 calls it a sector move, v1 already has the SPY event
    paths = {"BBB": steps((35, 104.2)), "XLK": steps((35, 99.5))}
    assert kinds(run(paths, radar_rules.V0)) == [("relative_to_sector", "BBB", "up")]
    assert kinds(run(paths, radar_rules.V1)) == [("relative_to_spy", "BBB", "up")]


@pytest.mark.parametrize("value,expected", [
    (None, "radar-rules-v0"), ("", "radar-rules-v0"), ("v0", "radar-rules-v0"), ("v1", "radar-rules-v1"),
    (" radar-rules-v1 ", "radar-rules-v1"),
])
def test_rules_version_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("RADAR_RULES_VERSION", raising=False)
    else:
        monkeypatch.setenv("RADAR_RULES_VERSION", value)
    assert radar_rules.from_env().version == expected


def test_unknown_rules_version_keeps_v0(monkeypatch, caplog):
    monkeypatch.setenv("RADAR_RULES_VERSION", "v9")
    with caplog.at_level(logging.ERROR):
        assert radar_rules.from_env() is radar_rules.V0
    assert "Unknown RADAR_RULES_VERSION 'v9'" in caplog.text


def test_runner_from_env_runs_the_selected_version(monkeypatch, tmp_path):
    for name in ("RADAR_ALERTS_ENABLED", "RADAR_PREMARKET_ENABLED", "RADAR_RULES_VERSION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    assert radar_runner.runner_from_env().rules is radar_rules.V0
    monkeypatch.setenv("RADAR_RULES_VERSION", "v1")
    assert radar_runner.runner_from_env().rules is radar_rules.V1


def test_the_store_records_the_version_each_event_was_found_under(tmp_path):
    store = _store_with(tmp_path, 35)
    v1 = _runner(store, 36)
    v1.rules = radar_rules.V1
    v1.run_once()
    [event] = store.events(DAY)
    assert event["event_id"] == "rv1-2030-01-15-spy-aaa-up-1" and event["rule_version"] == "radar-rules-v1"
    # v0 on the next pass reads only its own version's events, so it writes its own event beside v1's
    _runner(store, 37).run_once()
    assert [e["event_id"] for e in store.events(DAY)] == ["rv1-2030-01-15-spy-aaa-up-1", "rv0-2030-01-15-spy-aaa-up-1"]
    rows = sqlite3.connect(store.path).execute("SELECT event_id, rule_version FROM event ORDER BY rowid").fetchall()
    assert rows == [("rv1-2030-01-15-spy-aaa-up-1", "radar-rules-v1"), ("rv0-2030-01-15-spy-aaa-up-1", "radar-rules-v0")]
