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


def test_session_context_distinguishes_short_bounce_from_session_decline(store):
    first = seed(store, NOW - 2700)
    seed(store, NOW - 900, {s: 90 for s in ("NVDA", "AMD", "MU", "QQQ", "SPY")})
    seed(store, NOW, {s: 95 for s in ("NVDA", "AMD", "MU", "QQQ", "SPY")})
    before = store.path.read_bytes()
    result = read(RadarStore(store.path, read_only=True))
    session = result["session_context"]
    assert result["coverage"]["peers_up"] == 2
    assert session["coverage"]["peers_down"] == 2
    assert session["window"]["start_pass_id"] == first
    assert session["window"]["end_pass_id"] == result["window"]["end_pass_id"]
    assert session["rows"][0]["change_pct"] == pytest.approx(-5)
    assert session["window_minutes"] == 45
    assert session["coverage"]["recorded_minutes"] == 3
    assert session["coverage"]["expected_minutes"] == 46
    assert session["state"] == "partial"
    assert store.path.read_bytes() == before


def test_session_late_start_and_one_sample_do_not_fabricate_open(store):
    first = seed(store, NOW - 120)
    assert read(store)["session_context"]["window"] is None
    seed(store, NOW)
    result = read(store)
    assert result["window"] is None  # short session does not shorten 15-minute window
    assert result["session_context"]["window"]["start_pass_id"] == first
    assert result["session_context"]["window_minutes"] == 2


def test_session_keeps_first_pass_even_when_member_missing_or_version_old(store):
    first = seed(store, NOW - 2700, {"NVDA": 100, "QQQ": 100, "SPY": 100}, status="partial")
    seed(store, NOW - 900)
    seed(store, NOW)
    session = read(store)["session_context"]
    assert session["window"]["start_pass_id"] == first
    assert session["coverage"]["missing"] == ["AMD", "MU"]
    assert session["rows"][1]["change_pct"] is None
    seed(store, NOW - 3000, version="old")
    result = read(store)
    assert result["window"] is not None
    assert result["session_context"]["window"] is None
    assert "version" in result["session_context"]["reason"]


def test_session_stale_future_closed_and_no_overnight_carry(store):
    seed(store, NOW - 2700)
    seed(store, NOW)
    seed(store, NOW + 600)
    assert read(store, NOW + 181)["session_context"]["state"] == "stale"
    assert read(store)["session_context"]["window"]["end"] == iso(NOW)
    closed = read(store, NOW + 86400, live=False, today="2026-10-21")["session_context"]
    assert closed["session"] == "2026-10-20" and not closed["live"]
    assert read(store, NOW + 86400, today="2026-10-21")["session_context"]["window"] is None


def test_session_first_pass_is_not_lost_after_600_records(store):
    first = seed(store, NOW - 18000)
    for offset in range(600):
        seed(store, NOW - (599 - offset) * 30)
    assert read(store)["session_context"]["window"]["start_pass_id"] == first


def test_session_does_not_replace_ineligible_endpoint_trade(store):
    seed(store, NOW - 2700, edits={"AMD": {"trade_time_ms": (NOW - 2821) * 1000}})
    seed(store, NOW - 900)
    seed(store, NOW)
    session = read(store)["session_context"]
    assert session["rows"][1]["change_pct"] is None
    assert session["rows"][1]["reason"] == "Stale or future trade time"


def test_recovery_uses_selected_low_pass_not_peers_own_lows(store):
    seed(store, NOW - 180, {"NVDA": 100, "AMD": 50, "MU": 110, "QQQ": 100, "SPY": 100})
    low = seed(store, NOW - 120, {"NVDA": 90, "AMD": 100, "MU": 100, "QQQ": 100, "SPY": 100})
    seed(store, NOW - 60, {"NVDA": 94, "AMD": 90, "MU": 80, "QQQ": 100, "SPY": 100})
    end = seed(store, NOW, {"NVDA": 99, "AMD": 95, "MU": 90, "QQQ": 101, "SPY": 100})
    before = store.path.read_bytes()
    result = read(RadarStore(store.path, read_only=True))["recovery_context"]
    assert result["state"] == "ready"
    assert result["window"]["start_pass_id"] == low
    assert result["window"]["end_pass_id"] == end
    assert result["low_anchor"]["price"] == 90
    assert [r["change_pct"] for r in result["rows"]] == pytest.approx([10, -5, -10, 1, 0])
    assert result["coverage"]["peers_down"] == 2
    assert result["low_search"]["eligible_minutes"] == 4
    assert result["coverage"]["recorded_minutes"] == 3
    assert not result["at_recorded_low"]
    assert store.path.read_bytes() == before
    # Changing the selected symbol deliberately selects a different common anchor.
    amd = compare_group(store, empty_comparison("AMD", "Chips", UNIVERSE, NOW),
                        today="2026-10-20", now=NOW, live=True)["recovery_context"]
    assert amd["low_anchor"]["price"] == 50
    assert amd["window"]["start"] == iso(NOW - 180)


def test_recovery_ties_choose_earliest_and_disclose_no_rebound(store):
    first = seed(store, NOW - 120)
    seed(store, NOW - 60)
    seed(store, NOW)
    result = read(store)["recovery_context"]
    assert result["low_anchor"]["pass_id"] == first
    assert result["at_recorded_low"] and result["rows"][0]["change_pct"] == 0


def test_recovery_new_low_or_only_sample_has_no_rebound_window(store):
    seed(store, NOW - 120)
    assert "two eligible" in read(store, NOW - 120)["recovery_context"]["reason"]
    low = seed(store, NOW, {"NVDA": 90})
    result = read(store)["recovery_context"]
    assert result["low_anchor"]["pass_id"] == low
    assert result["window"] is None and not result["rows"]
    assert "too recent" in result["reason"]


@pytest.mark.parametrize("edits", [
    {"last": None}, {"last": 0}, {"last": float("inf")},
    {"trade_time_ms": None}, {"trade_time_ms": (NOW - 241) * 1000},
    {"trade_time_ms": (NOW - 119) * 1000}, {"retrieved_at": iso(NOW - 119)},
])
def test_recovery_invalid_low_samples_are_omitted_and_disclosed(store, edits):
    first = seed(store, NOW - 180)
    seed(store, NOW - 120, {"NVDA": 1}, edits={"NVDA": edits})
    seed(store, NOW - 60)
    seed(store, NOW, {"NVDA": 105, "AMD": 100, "MU": 100, "QQQ": 100, "SPY": 100})
    result = read(store)["recovery_context"]
    assert result["low_anchor"]["pass_id"] == first
    assert result["low_search"]["omitted_samples"] == 1
    assert result["state"] == "partial"


def test_recovery_requires_eligible_latest_selected_sample(store):
    seed(store, NOW - 120)
    seed(store, NOW, {"AMD": 110})
    result = read(store)["recovery_context"]
    assert "no eligible latest" in result["reason"]
    assert not result["rows"] and result["window"] is None


def test_recovery_search_gaps_before_anchor_and_missing_peer_are_visible(store):
    seed(store, NOW - 600, status="failed")
    low = seed(store, NOW - 60, {"NVDA": 90, "QQQ": 100, "SPY": 100}, status="partial")
    seed(store, NOW)
    result = read(store)["recovery_context"]
    assert result["window"]["start_pass_id"] == low
    assert result["low_search"]["eligible_minutes"] == 2
    assert result["low_search"]["expected_minutes"] == 11
    assert result["low_search"]["omitted_samples"] == 1
    assert result["coverage"]["recorded_minutes"] == result["coverage"]["expected_minutes"] == 2
    assert result["coverage"]["missing"] == ["AMD", "MU"]
    assert result["state"] == "partial"


def test_recovery_long_pass_omitted_and_version_change_anywhere_refused(store):
    first = seed(store, NOW - 240)
    seed(store, NOW - 180, {"NVDA": 1}, duration=91)
    seed(store, NOW)
    result = read(store)["recovery_context"]
    assert result["low_anchor"]["pass_id"] == first
    assert result["low_search"]["omitted_samples"] == 1
    seed(store, NOW - 120, version="old")
    result = read(store)["recovery_context"]
    assert "version changed" in result["reason"] and not result["rows"]


def test_recovery_stale_future_closed_and_no_overnight_carry(store):
    seed(store, NOW - 60)
    seed(store, NOW)
    seed(store, NOW + 60, {"NVDA": 1})
    result = read(store)["recovery_context"]
    assert result["window"]["end"] == iso(NOW)
    assert result["low_anchor"]["price"] == 100
    assert read(store, NOW + 241)["recovery_context"]["state"] == "stale"
    closed = read(store, NOW + 86400, live=False, today="2026-10-21")["recovery_context"]
    assert closed["session"] == "2026-10-20" and not closed["live"]
    assert read(store, NOW + 86400, today="2026-10-21")["recovery_context"]["window"] is None


def test_recovery_no_eligible_samples_and_symbol_scoped_history(store):
    seed(store, NOW - 60, {"AMD": 100})
    seed(store, NOW, {"AMD": 101})
    result = read(store)["recovery_context"]
    assert "No eligible selected-stock" in result["reason"]
    assert result["low_search"]["omitted_samples"] == 2
    assert not store.quotes(session_date="2026-10-20", symbol="NVDA")
    assert len(store.quotes(session_date="2026-10-20", symbol="AMD")) == 2
