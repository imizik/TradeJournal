"""The desk's "what's moving" strip (app/engine/desk_moving.py, GET /copilot/desk/moving): which tiles, in what order,
where each change comes from, that a ticker he does not follow never shows, the cache, and the one grey line when there
is nothing. Every price and change is invented."""

from __future__ import annotations

from datetime import UTC, date, datetime
import copy
import json
from pathlib import Path

import pytest
from sqlmodel import Session

from app.engine import desk_moving
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore
from app.engine.symbol_info_tradier import symbol_events
from app.models import ChartSettingsRecord, DayJournalEntry, RadarSetup
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)

HOURS = {"status": "open", "open": 570, "close": 960}
SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())["event"]

# Day changes in % the recorder holds (prev close 100, so last = 100 + change).
RECORDED = {"SPY": 0.5, "QQQ": 0.9, "IWM": -0.4, "XLK": 1.2, "XLE": -1.5, "XLF": 0.1, "SMH": 2.0,
            "NVDA": 3.0, "AMD": -4.0, "MU": 6.5, "CRWV": -8.0, "NBIS": 1.0, "TSLA": -0.2, "PLTR": 5.0}


def at(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def record(path, when: datetime, changes: dict[str, float]) -> RadarStore:
    """One recorded pass at ``when`` (New York) holding each symbol's last against a previous close of 100."""
    store = RadarStore(path)
    stamp = at(when)
    store.append_pass({"session_date": when.date().isoformat(), "started_at": stamp, "finished_at": stamp,
                       "universe_version": "radar-universe-v2", "status": "ok", "symbols_requested": len(changes),
                       "symbols_returned": len(changes), "unmatched": [], "requests_used": 1, "error": None, "skip_reason": None},
                      [{"symbol": s, "last": 100.0 + c, "prev_close": 100.0, "open": 100.0, "high": 110.0, "low": 90.0,
                        "volume": 1000, "bid": None, "ask": None, "trade_time_ms": int(when.timestamp() * 1000),
                        "retrieved_at": stamp} for s, c in changes.items()])
    return store


def event(store: RadarStore, session: str, symbol: str, kind: str, n: int = 1) -> None:
    store.append_event({**copy.deepcopy(SAMPLE), "event_id": f"ev-{symbol}-{n}", "session_date": session, "kind": kind,
                        "symbols": [symbol]})


@pytest.fixture
def rig(desk, quotes, clock, engine, monkeypatch, tmp_path):  # noqa: F811
    desk_moving.clear()
    monkeypatch.setattr(chart_calendar, "hours", lambda day: HOURS)
    monkeypatch.setattr(desk_moving, "_held", lambda db: ["CRWV", "NBIS", "APLD"])
    monkeypatch.setattr(symbol_events, "_earnings", lambda symbol, today, reports, issue: {"next": None, "reports": []})
    monkeypatch.setattr(symbol_events, "chart_earnings", lambda *a: pytest.fail("the strip must not start an earnings refresh"))
    quotes["rows"] = [{"symbol": "APLD", "change_percentage": 7.25, "last": 30.0},
                      {"symbol": "ANET", "change_percentage": -2.0, "last": 1.0},
                      {"symbol": "CRDO", "change_percentage": -3.0, "last": 1.0},
                      {"symbol": "ALAB", "change_percentage": 1.0, "last": 1.0},
                      {"symbol": "IREN", "change_percentage": 2.0, "last": 1.0},
                      {"symbol": "CIFR", "change_percentage": -1.0, "last": 1.0}]
    with Session(engine) as db:
        db.add(ChartSettingsRecord(name="default", data_json=json.dumps({"watchlist": ["MU", "PLTR", "NVDA"]}), revision=1))
        db.commit()
    state = {"client": desk, "clock": clock, "quotes": quotes, "engine": engine, "patch": monkeypatch, "path": tmp_path / "radar.sqlite"}
    yield state
    desk_moving.clear()


def radar_on(rig, when: datetime | None = None, changes: dict | None = None) -> RadarStore:
    when = when or datetime.fromtimestamp(rig["clock"]["t"] - 30, ET)
    store = record(rig["path"], when, RECORDED if changes is None else changes)
    rig["patch"].setenv("RADAR_ENABLED", "true")
    rig["patch"].setenv("RADAR_STORE", str(rig["path"]))
    return store


def moving(rig) -> dict:
    response = rig["client"].get("/copilot/desk/moving")
    assert response.status_code == 200, response.text
    return response.json()


def hide(rig, symbol: str) -> None:
    with Session(rig["engine"]) as db:
        db.add(DayJournalEntry(operation_id=f"hide-{symbol}", day=date(2026, 10, 21), kind="follow", symbol=symbol, text="Not following"))
        db.commit()


# ---------------------------------------------------------------------------------------------------- groups


def test_groups_read_index_then_sectors_by_change_then_his_own(rig):
    radar_on(rig)
    body = moving(rig)
    assert body["state"] == "ok" and body["mode"] == "live" and body["session"] == "2026-10-21"
    keys = [g["key"] for g in body["groups"]]
    assert keys[:3] == ["SPY", "QQQ", "IWM"]  # the index proxies first, always in this order
    assert keys[3:7] == ["SMH", "XLK", "XLF", "XLE"]  # sectors the recorder has, biggest gain first; none invented
    assert body["groups"][3]["label"] == "Semis" and body["groups"][3]["symbol"] == "SMH"
    watching = next(g for g in body["groups"] if g["key"] == "watching")
    assert watching["change_pct"] == 5.0  # median of MU 6.5, PLTR 5.0, NVDA 3.0
    assert [m["symbol"] for m in watching["members"]] == ["MU", "PLTR", "NVDA"]  # biggest gain first
    own = [g for g in body["groups"] if g["kind"] == "research"]
    assert own and keys.index("watching") < keys.index(own[0]["key"])
    cloud = next(g for g in own if g["label"] == "Cloud capacity")  # NBIS, CRWV recorded; APLD, IREN, CIFR quoted: 5 of 8
    assert cloud["change_pct"] == 1.0  # median of 7.25, 2, 1, -1, -8
    assert all(g["change_pct"] is not None for g in body["groups"])
    assert [g["change_pct"] for g in own] == sorted((g["change_pct"] for g in own), reverse=True)


def test_a_group_needs_half_its_members_or_it_is_left_out(rig):
    radar_on(rig)
    labels = {g["label"] for g in moving(rig)["groups"]}
    # Connectivity: ANET, CRDO, ALAB (quoted) of ANET, CRDO, ALAB, COHR, LITE, AAOI, POET: 3 of 7 is under half.
    assert "Connectivity" not in labels
    desk_moving.clear()
    rig["quotes"]["rows"] += [{"symbol": "COHR", "change_percentage": 4.0}]
    group = next(g for g in moving(rig)["groups"] if g["label"] == "Connectivity")
    assert group["change_pct"] == -0.5  # median of -3, -2, 1, 4
    assert [m["symbol"] for m in group["members"]][:4] == ["COHR", "ALAB", "ANET", "CRDO"]
    assert group["members"][-1]["change_pct"] is None  # unknown members are listed last with no number, never 0


def test_the_recorder_serves_what_it_has_and_one_batched_read_the_rest(rig):
    radar_on(rig)
    moving(rig)
    asked = rig["quotes"]["asked"]
    assert len(asked) == 1  # one call for every name the recorder does not cover
    assert "APLD" in asked[0] and "ANET" in asked[0]
    assert not {"SPY", "QQQ", "XLK", "MU", "NVDA", "CRWV"} & set(asked[0])  # recorded: no provider call


def test_without_the_recorder_the_etfs_come_from_the_quote_read(rig):
    rig["quotes"]["rows"] += [{"symbol": "SPY", "change_percentage": 0.3}, {"symbol": "XLE", "change_percentage": -1.1}]
    body = moving(rig)
    assert [g["key"] for g in body["groups"]][:2] == ["SPY", "XLE"]  # QQQ, IWM unknown: no tile rather than a zero
    assert body["groups"][1]["members"] == []  # no recorder, no sector membership


# ---------------------------------------------------------------------------------------------------- movers


def test_his_movers_come_first_then_the_recorders_by_size(rig):
    radar_on(rig)
    movers = moving(rig)["movers"]
    mine = [m for m in movers if m["mine"]]
    assert [m["symbol"] for m in mine] == ["CRWV", "APLD", "MU", "PLTR", "NVDA", "NBIS"]  # by size, either way
    assert movers[: len(mine)] == mine
    broad = [m["symbol"] for m in movers if not m["mine"]]
    assert broad == ["AMD", "TSLA"]  # the recorder's stocks not already shown, by size; ETFs are never movers
    assert next(m for m in movers if m["symbol"] == "APLD")["change_pct"] == 7.25


def test_a_ticker_he_does_not_follow_is_never_shown(rig):
    radar_on(rig)
    hide(rig, "MU")
    hide(rig, "AMD")
    body = moving(rig)
    shown = {m["symbol"] for m in body["movers"]}
    assert not {"MU", "AMD"} & shown
    members = {m["symbol"] for g in body["groups"] for m in g["members"]}
    assert not {"MU", "AMD"} & members  # not in any popover either
    watching = next(g for g in body["groups"] if g["key"] == "watching")
    assert watching["change_pct"] == 4.0  # PLTR 5, NVDA 3: his hidden name does not move his group


def test_an_unreadable_follow_setting_shows_no_movers(rig):
    radar_on(rig)
    rig["patch"].setattr(desk_moving, "_hidden", lambda db: None)
    body = moving(rig)
    assert body["movers"] == [] and "watching" not in [g["key"] for g in body["groups"]]
    assert body["groups"][0]["key"] == "SPY"  # the market tiles still stand
    assert all(g["members"] == [] for g in body["groups"])  # no list that might hold a hidden name


def test_reasons_only_when_the_app_already_knows_one(rig):
    store = radar_on(rig)
    event(store, "2026-10-21", "AMD", "relative_to_spy")
    event(store, "2026-10-20", "TSLA", "gap_reversal")  # yesterday's: not today's reason
    with Session(rig["engine"]) as db:
        db.add(RadarSetup(event_id="ev-nbis", session_date="2026-10-21", rule_version="v", kind="dip_turn", symbol="NBIS",
                          direction="up", entry=1.0, invalidation=0.5))
        db.commit()
    cached = {"MU": {"next": None, "reports": [{"date": "2026-10-20", "label": "Q3"}]},  # after yesterday's close
              "PLTR": {"next": None, "reports": [{"date": "2026-10-01", "label": "Q3"}]}}  # weeks ago: no reason
    rig["patch"].setattr(symbol_events, "_earnings", lambda symbol, today, reports, issue: cached.get(symbol, {"next": None, "reports": []}))
    reasons = {m["symbol"]: m["reason"] for m in moving(rig)["movers"]}
    assert reasons["MU"] == "Earnings" and reasons["NBIS"] == "Dip turn" and reasons["AMD"] == "Radar"
    assert reasons["PLTR"] is None and reasons["TSLA"] is None and reasons["CRWV"] is None


# ---------------------------------------------------------------------------------------------------- hours, cache


def test_before_the_open_it_is_the_last_sessions_close_with_no_quote_read(rig):
    radar_on(rig, datetime(2026, 10, 20, 15, 59, 30, tzinfo=ET))
    rig["clock"]["t"] = datetime(2026, 10, 21, 8, 0, tzinfo=ET).timestamp()
    body = moving(rig)
    assert body["mode"] == "close" and body["session"] == "2026-10-20"
    assert "asked" not in rig["quotes"]  # the quote's previous close has rolled before the open: not asked at all
    assert [m["symbol"] for m in body["movers"] if m["mine"]] == ["CRWV", "MU", "PLTR", "NVDA", "NBIS"]  # APLD: unknown


def test_after_the_close_the_quote_read_uses_the_regular_close(rig):
    radar_on(rig, datetime(2026, 10, 21, 15, 59, 30, tzinfo=ET))
    rig["clock"]["t"] = datetime(2026, 10, 21, 17, 30, tzinfo=ET).timestamp()
    rig["quotes"]["rows"] = [{"symbol": "APLD", "change_percentage": 9.0, "regular_close": 33.0, "previous_close": 30.0}]
    body = moving(rig)
    assert body["mode"] == "close" and body["session"] == "2026-10-21"
    assert next(m for m in body["movers"] if m["symbol"] == "APLD")["change_pct"] == 10.0  # the close, not after hours


def test_a_stale_recorder_in_the_session_is_not_used_as_live(rig):
    radar_on(rig, datetime.fromtimestamp(rig["clock"]["t"] - 600, ET))
    body = moving(rig)
    assert body["mode"] == "live" and [m for m in body["movers"] if not m["mine"]] == []
    assert "SPY" in rig["quotes"]["asked"][0]


def test_changes_are_kept_for_the_cache_window(rig):
    radar_on(rig)
    first = moving(rig)
    assert moving(rig) == first and len(rig["quotes"]["asked"]) == 1  # the second read asks nothing
    rig["clock"]["t"] += desk_moving.CACHE_SECONDS + 1
    radar_on(rig)  # a newer pass, so the recorder stays current
    moving(rig)
    assert len(rig["quotes"]["asked"]) == 2


def test_nothing_to_show_is_one_unavailable_line_never_zeros(rig):
    rig["quotes"]["fail"] = True
    body = moving(rig)
    assert body["state"] == "unavailable" and body["groups"] == [] and body["movers"] == [] and body["mode"] is None
    assert body["reason"]


def test_refused_while_the_lab_is_off(rig):
    rig["patch"].setattr("app.routers.copilot_desk.copilot.settings", lambda: type("S", (), {"enabled": False})())
    assert rig["client"].get("/copilot/desk/moving").status_code == 503


def test_the_read_reports_where_its_time_goes():
    from app.engine import request_timing
    assert any("/copilot/desk/moving".startswith(p) for p in request_timing.PREFIXES)  # Server-Timing and /desk/timings


def test_his_positions_add_robinhoods_last_snapshot_without_asking_robinhood(engine, monkeypatch):  # noqa: F811
    from app.engine import robinhood_book
    asked = []

    def snapshot(kick=True):
        asked.append(kick)
        return {"state": "ok"}, {"positions": [{"symbol": "hood"}, {"symbol": None}]}
    monkeypatch.setattr(robinhood_book.feed, "snapshot", snapshot)
    with Session(engine) as db:
        held = desk_moving._held(db)
    assert "HOOD" in held and asked == [False]  # the feed's last snapshot only: no refresh is kicked
