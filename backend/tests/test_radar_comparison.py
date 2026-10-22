"""Common-pass observation semantics and the read-only owner API."""
from datetime import UTC, datetime
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.engine.radar_comparison import compare_group, empty_comparison, iso
from app.engine.radar_store import RadarStore
from app.main import app
from app.routers import radar

NOW = datetime(2026, 10, 20, 14, 15, tzinfo=UTC).timestamp()
UNIVERSE = {"version": "test-v1", "groups": [
    {"name": "Chips", "members": ["NVDA", "AMD", "MU"]},
    {"name": "AI", "members": ["NVDA", "AMD"]},
]}


@pytest.fixture
def store(tmp_path):
    return RadarStore(tmp_path / "radar.sqlite")


def seed(store, at, prices=None, *, status="ok", version="test-v1", day="2026-10-20", edits=None, duration=0):
    prices = prices or {"NVDA": 100, "AMD": 100, "MU": 100, "QQQ": 100, "SPY": 100}
    rows = []
    for symbol, last in prices.items():
        row = {"symbol": symbol, "last": last, "prev_close": 99, "open": 100, "high": 101, "low": 98,
               "volume": 1000, "bid": 99, "ask": 101, "trade_time_ms": int(at * 1000), "retrieved_at": iso(at)}
        row.update((edits or {}).get(symbol, {}))
        rows.append(row)
    return store.append_pass({"session_date": day, "started_at": iso(at), "finished_at": iso(at + duration),
                              "universe_version": version, "status": status, "symbols_requested": 5,
                              "symbols_returned": len(rows), "unmatched": [], "requests_used": 1,
                              "error": None, "skip_reason": None}, rows)


def read(store, now=NOW, live=True, today="2026-10-20"):
    return compare_group(store, empty_comparison("NVDA", "Chips", UNIVERSE, now), today=today, now=now, live=live)


def test_shared_window_returns_counts_and_no_writes(store):
    start = seed(store, NOW - 900)
    end = seed(store, NOW, {"NVDA": 105, "AMD": 102, "MU": 99, "QQQ": 101, "SPY": 100})
    before = store.path.read_bytes()
    result = read(RadarStore(store.path, read_only=True))
    assert result["window"]["start_pass_id"] == start and result["window"]["end_pass_id"] == end
    assert [r["change_pct"] for r in result["rows"]] == pytest.approx([5, 2, -1, 1, 0])
    assert result["coverage"]["peers_total"] == 2 and result["coverage"]["peers_up"] == 1
    assert result["coverage"]["peers_down"] == 1  # selected NVDA excluded
    assert store.path.read_bytes() == before
    assert not store.events() and not store.last_visit()


@pytest.mark.parametrize("field,value", [("last", 0), ("last", float("inf")), ("last", None),
    ("trade_time_ms", None), ("trade_time_ms", (NOW - 121) * 1000), ("trade_time_ms", (NOW + 1) * 1000),
    ("retrieved_at", iso(NOW + 1))])
def test_ineligible_rows_stay_missing_not_zero(store, field, value):
    seed(store, NOW - 900)
    seed(store, NOW, edits={"AMD": {field: value}})
    result = read(store)
    assert result["state"] == "partial"
    assert result["coverage"]["missing"] == ["AMD"]
    amd = next(r for r in result["rows"] if r["symbol"] == "AMD")
    assert amd["change_pct"] is None and amd["reason"]


def test_partial_pass_never_fills_missing_member_from_another_pass(store):
    seed(store, NOW - 900)
    seed(store, NOW - 60)
    seed(store, NOW, {"NVDA": 101, "QQQ": 100, "SPY": 100}, status="partial")
    result = read(store)
    assert result["coverage"]["missing"] == ["AMD", "MU"]
    assert result["coverage"]["peers_available"] == 0


def test_ok_pass_does_not_guarantee_coverage(store):
    seed(store, NOW - 900)
    seed(store, NOW, {"NVDA": 101})
    assert read(store)["coverage"]["missing"] == ["AMD", "MU", "QQQ", "SPY"]


def test_no_future_pass_no_shortened_window_and_tolerance(store):
    seed(store, NOW - 899)
    seed(store, NOW)
    seed(store, NOW + 60)
    assert read(store)["state"] == "insufficient"
    seed(store, NOW - 990)
    assert read(store)["window"]["end"] == iso(NOW)
    assert read(store)["window"]["start"] == iso(NOW - 990)


def test_long_gap_is_not_silently_widened(store):
    seed(store, NOW - 991)
    seed(store, NOW)
    assert read(store)["window"] is None


def test_version_change_and_long_pass_are_refused(store):
    seed(store, NOW - 900, version="old")
    seed(store, NOW)
    assert "version" in read(store)["reason"]
    # New session isolates the long-pass case.
    seed(store, NOW + 86400 - 900, day="2026-10-21", duration=91)
    seed(store, NOW + 86400, day="2026-10-21")
    assert "too long" in read(store, NOW + 86400, today="2026-10-21")["reason"]


def test_stale_closed_session_and_no_overnight_carry(store):
    seed(store, NOW - 900)
    seed(store, NOW)
    assert read(store, NOW + 181)["state"] == "stale"
    closed = read(store, NOW + 86400, live=False, today="2026-10-21")
    assert closed["session"] == "2026-10-20" and closed["live"] is False
    assert read(store, NOW + 86400, today="2026-10-21")["window"] is None


def test_api_off_missing_store_invalid_group_and_ungrouped(tmp_path, monkeypatch):
    path = tmp_path / "absent" / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(radar, "load_universe", lambda: UNIVERSE)
    with TestClient(app) as client:
        result = client.get("/radar/groups/compare", params={"symbol": "NVDA"}).json()
        assert result["state"] == "off" and not path.parent.exists()
        assert client.get("/radar/groups/compare?symbol=NVDA&group=wrong").status_code == 422
        assert client.get("/radar/groups/compare?symbol=SPY").json()["state"] == "ungrouped"
        assert client.get("/radar/groups/compare?symbol=../../").status_code == 422


def test_api_selected_group_and_readonly_foreign_file(store, monkeypatch):
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(store.path))
    monkeypatch.setattr(radar, "load_universe", lambda: UNIVERSE)
    monkeypatch.setattr(radar, "_now", lambda: NOW)
    monkeypatch.setattr(radar.chart_calendar, "hours", lambda day: {"status": "open", "open": 570, "close": 960})
    seed(store, NOW - 900)
    seed(store, NOW)
    with TestClient(app) as client:
        result = client.get("/radar/groups/compare?symbol=nvda&group=AI").json()
        assert result["group"]["name"] == "AI"
        assert result["coverage"]["peers_total"] == 1
        assert len(result["groups"]) == 2
        with sqlite3.connect(store.path) as db:
            db.execute("PRAGMA application_id=0")
        before = store.path.read_bytes()
        assert client.get("/radar/groups/compare?symbol=NVDA").json()["state"] == "off"
        assert store.path.read_bytes() == before


def test_full_window_ready_and_failed_minutes_disclosed(store):
    for offset in range(0, 901, 60):
        seed(store, NOW - 900 + offset)
    result = read(store)
    assert result["state"] == "ready"
    assert result["coverage"]["recorded_minutes"] == result["coverage"]["expected_minutes"] == 16


def test_calendar_unavailable_cannot_claim_current_session(store, monkeypatch):
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(store.path))
    monkeypatch.setattr(radar.chart_calendar, "hours", lambda day: None)
    with TestClient(app) as client:
        result = client.get("/radar/groups/compare?symbol=NVDA").json()
        assert result["state"] == "insufficient" and "calendar" in result["reason"]
        assert not result["rows"]
