"""Plan it on a Radar setup ping: one tap saves the setup card as a plan and arms its invalidation alert."""

from datetime import datetime
import json
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session, select

from app.engine import captures as captures_engine, desk_radar_setups, level_alerts, radar_proof, radar_setup_plan, telegram_replies
from app.models import CopilotInvestigation, LevelAlert, PlanTimeStop, RadarSetup, TradeCapture
from tests.test_exit_habits import ROTH, engine  # noqa: F401

NOW = datetime(2026, 11, 10, 10, 5, tzinfo=ZoneInfo("America/New_York")).timestamp()
EVENT = "rd0-2026-11-10-dip-nbis-up-1"
CONTRACT = {"symbol": "NBIS261120C00062000", "option_type": "call", "strike": 62.0, "expiration": "2026-11-20",
            "bid": 1.1, "ask": 1.2, "mid": 1.15}


@pytest.fixture(autouse=True)
def clock_hours(monkeypatch):
    monkeypatch.setattr(telegram_replies, "_calendar", lambda: None)  # the time stop reads clock hours; no calendar fetch


def time_stops(db_engine) -> list[PlanTimeStop]:
    with Session(db_engine) as db:
        return db.exec(select(PlanTimeStop)).all()


def card(db_engine, direction="up", invalidation=59.85, contract=CONTRACT, kind="dip_turn", event=EVENT) -> str:
    with Session(db_engine) as db:
        row = RadarSetup(event_id=event, session_date="2026-11-10", rule_version="rd0", kind=kind, symbol="NBIS",
                         direction=direction, entry=61.2, invalidation=invalidation,
                         contract_json=json.dumps(contract) if contract else None)
        db.add(row)
        db.commit()
        return str(row.id)


def tap(db_engine, setup_id, last=61.4):
    return radar_setup_plan.plan(db_engine, setup_id, now=NOW, quote=lambda symbol: last)


def stored(db_engine, setup_id):
    with Session(db_engine) as db:
        return (db.get(RadarSetup, uuid.UUID(setup_id)), db.exec(select(TradeCapture)).all(), db.exec(select(LevelAlert)).all(),
                db.exec(select(CopilotInvestigation)).all())


def test_plan_it_saves_the_plan_with_the_radar_origin_and_arms_the_invalidation(engine):  # noqa: F811
    setup_id = card(engine)
    assert tap(engine, setup_id) == ("Planned NBIS: out below 59.85. Alert armed. 60-minute check armed.", "Planned")
    row, (capture,), (alert,), (thread,) = stored(engine, setup_id)
    [stop] = time_stops(engine)
    assert (stop.client_id, stop.investigation_id, stop.symbol, stop.text) == (uuid.UUID(setup_id).hex, str(thread.id), "NBIS", "60m")
    assert stop.due_at == datetime(2026, 11, 10, 16, 5)  # 11:05 ET in naive UTC: 60 minutes from the tap
    assert thread.title == "Radar setup: NBIS dip turning up" and thread.symbol == "NBIS" and thread.status == "open"
    assert (row.plan_state, row.investigation_id, row.plan_note) == ("planned", str(thread.id), None)
    assert row.planned_at is not None
    assert (capture.client_id, capture.account_id, capture.underlying, capture.side, capture.mode, capture.setup_label) == (
        uuid.UUID(setup_id).hex, ROTH, "NBIS", "buy_calls", "discretionary", "Copilot plan")
    assert (capture.origin_kind, capture.origin_ref) == ("radar_event", EVENT)
    assert (capture.strike, capture.expiration.isoformat()) == (62.0, "2026-11-20")
    assert json.loads(capture.context_json)["investigation_id"] == str(thread.id)
    assert capture.wording == "Entry: now, near 61.40. Invalidation: crosses 59.85."
    assert capture.note == f"Thesis: NBIS dip turning up on Radar ({EVENT}); the idea is wrong below 59.85. Contract: NBIS 11/20/26 62C."
    assert (alert.symbol, alert.price, alert.condition, alert.direction, alert.plan_role, alert.source_kind, alert.source_id,
            alert.state) == ("NBIS", 59.85, "crosses", "down", "invalidation", "copilot", str(thread.id), "active")
    with Session(engine) as db:
        assert radar_proof.planned_events(db, [EVENT]) == {EVENT: {"planned": True, "traded": False}}


def test_a_put_idea_without_a_contract_is_a_long_put_plan_out_above(engine):  # noqa: F811
    setup_id = card(engine, direction="down", invalidation=63.0, contract=None, kind="gap_reversal")
    assert tap(engine, setup_id, last=61.0) == ("Planned NBIS: out above 63.00. Alert armed. 60-minute check armed.", "Planned")
    row, (capture,), (alert,), (thread,) = stored(engine, setup_id)
    assert thread.title == "Radar setup: NBIS gap up turning down"
    assert (capture.side, capture.strike, capture.expiration) == ("buy_puts", None, None)
    assert "Contract" not in capture.note and (alert.direction, alert.plan_role) == ("up", "invalidation")


def test_a_double_tap_saves_one_plan(engine):  # noqa: F811
    setup_id = card(engine)
    assert tap(engine, setup_id)[1] == "Planned"
    assert tap(engine, setup_id) == ("Already planned.", "Planned")
    _, captures, alerts, threads = stored(engine, setup_id)
    assert (len(captures), len(alerts), len(threads), len(time_stops(engine))) == (1, 1, 1, 1)


def test_a_stock_through_the_level_is_refused_in_both_directions(engine):  # noqa: F811
    up = card(engine)
    assert tap(engine, up, last=59.85) == (
        "NBIS is already below 59.85, the level this setup was built on. No plan saved.", "Not planned")
    down = card(engine, direction="down", invalidation=63.0, event="rd0-2026-11-10-gap-nbis-down-1", kind="gap_reversal")
    assert tap(engine, down, last=63.5) == (
        "NBIS is already above 63.00, the level this setup was built on. No plan saved.", "Not planned")
    for setup_id in (up, down):
        row, captures, alerts, threads = stored(engine, setup_id)
        assert row.plan_state == "refused" and row.plan_note.endswith("No plan saved.") and row.planned_at is None
        assert (captures, alerts, threads) == ([], [], [])
    assert tap(engine, up)[0].startswith("Not planned: NBIS is already below")  # the refusal stands; nothing is written later


def test_a_missing_quote_leaves_the_card_for_a_later_tap(engine):  # noqa: F811
    setup_id = card(engine)
    assert tap(engine, setup_id, last=None) == (
        "The latest NBIS quote is stale or missing, so nothing was saved. Tap again in a moment.", None)
    row, captures, alerts, threads = stored(engine, setup_id)
    assert (row.plan_state, row.plan_note, captures, alerts, threads) == ("none", None, [], [], [])
    assert tap(engine, setup_id)[1] == "Planned"


def test_an_alert_the_caps_refuse_keeps_the_saved_plan(engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(level_alerts, "MAX_ACTIVE", 0)
    setup_id = card(engine)
    reply, chosen = tap(engine, setup_id)
    assert reply == ("Planned NBIS: out below 59.85. Alert not armed: 0 alerts are already active. Remove one first. "
                     "60-minute check armed.")
    assert chosen == "Planned"
    row, (capture,), alerts, (thread,) = stored(engine, setup_id)
    assert (row.plan_state, row.investigation_id, alerts) == ("planned", str(thread.id), [])
    assert capture.origin_ref == EVENT


def test_an_unknown_setup_writes_nothing(engine):  # noqa: F811
    assert tap(engine, str(uuid.uuid4())) == ("That setup is no longer available.", None)
    assert tap(engine, "not-an-id") == ("That setup is no longer available.", None)
    with Session(engine) as db:
        assert db.exec(select(TradeCapture)).all() == [] and db.exec(select(CopilotInvestigation)).all() == []


def test_a_time_stop_refused_after_the_close_keeps_the_plan_without_saying_armed(engine):  # noqa: F811
    setup_id = card(engine)
    late = datetime(2026, 11, 10, 16, 5, tzinfo=ZoneInfo("America/New_York")).timestamp()  # after the close: 60m has no session
    reply, chosen = radar_setup_plan.plan(engine, setup_id, now=late, quote=lambda symbol: 61.4)
    assert (reply, chosen) == ("Planned NBIS: out below 59.85. Alert armed.", "Planned")
    row, (capture,), (alert,), _ = stored(engine, setup_id)
    assert row.plan_state == "planned" and time_stops(engine) == []


def test_a_failing_time_stop_never_fails_the_plan(engine, monkeypatch):  # noqa: F811
    from app.engine import plan_time_stops
    monkeypatch.setattr(plan_time_stops, "create", lambda *a, **k: 1 / 0)
    setup_id = card(engine)
    assert tap(engine, setup_id) == ("Planned NBIS: out below 59.85. Alert armed.", "Planned")
    assert stored(engine, setup_id)[0].plan_state == "planned"


def test_a_failure_after_the_claim_releases_it_for_a_later_tap(engine, monkeypatch):  # noqa: F811
    setup_id = card(engine)
    real = captures_engine.save

    def broken(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(captures_engine, "save", broken)
    assert tap(engine, setup_id) == ("The plan could not be saved, so nothing is planned. Tap again in a moment.", None)
    row, captures, alerts, threads = stored(engine, setup_id)
    assert (row.plan_state, row.planned_at, captures, alerts, threads) == ("none", None, [], [], [])  # no stray thread
    monkeypatch.setattr(captures_engine, "save", real)
    assert tap(engine, setup_id)[1] == "Planned"
    row, (capture,), (alert,), (thread,) = stored(engine, setup_id)
    assert row.plan_state == "planned" and capture.origin_ref == EVENT
    assert row.investigation_id == alert.source_id == json.loads(capture.context_json)["investigation_id"] == str(thread.id)


def test_a_failure_after_the_capture_is_saved_is_retried_onto_the_same_thread(engine, monkeypatch):  # noqa: F811
    setup_id = card(engine)
    real = captures_engine.save

    def saved_then_lost(*a, **k):
        real(*a, **k)
        raise RuntimeError("connection lost after the commit")
    monkeypatch.setattr(captures_engine, "save", saved_then_lost)
    assert tap(engine, setup_id)[1] is None
    row, (capture,), alerts, (thread,) = stored(engine, setup_id)
    assert (row.plan_state, alerts) == ("none", []) and json.loads(capture.context_json)["investigation_id"] == str(thread.id)
    monkeypatch.setattr(captures_engine, "save", real)
    assert tap(engine, setup_id)[1] == "Planned"
    row, (capture,), (alert,), (thread,) = stored(engine, setup_id)
    assert row.investigation_id == alert.source_id == json.loads(capture.context_json)["investigation_id"] == str(thread.id)
    assert [s.investigation_id for s in time_stops(engine)] == [str(thread.id)]


def test_a_database_error_arming_the_alert_keeps_the_plan_and_says_so(engine, monkeypatch):  # noqa: F811
    from sqlalchemy.exc import OperationalError
    from app.engine import level_alert_monitor

    def broken(*a, **k):
        raise OperationalError("INSERT INTO level_alert", {}, Exception("database is locked"))
    monkeypatch.setattr(level_alert_monitor, "create_alert", broken)
    setup_id = card(engine)
    assert tap(engine, setup_id) == (
        "Planned NBIS: out below 59.85. Alert not armed: it could not be saved. 60-minute check armed.", "Planned")
    row, (capture,), alerts, (thread,) = stored(engine, setup_id)
    assert (row.plan_state, row.investigation_id, alerts) == ("planned", str(thread.id), [])
    assert len(time_stops(engine)) == 1


def test_a_setup_from_an_earlier_session_is_refused_and_writes_nothing(engine):  # noqa: F811
    with Session(engine) as db:
        row = RadarSetup(event_id=EVENT, session_date="2026-11-09", rule_version="rd0", kind="dip_turn", symbol="NBIS",
                         direction="up", entry=61.2, invalidation=59.85)
        db.add(row)
        db.commit()
        setup_id = str(row.id)
    assert tap(engine, setup_id) == ("This setup is from Nov 9; its level no longer applies. No plan saved.", "Not planned")
    row, captures, alerts, threads = stored(engine, setup_id)
    assert (row.plan_state, row.plan_note, row.planned_at, captures, alerts, threads) == ("none", None, None, [], [], [])
    assert time_stops(engine) == []


# ------------------------------------------------------------------ the desk: the setup on the Radar card, Plan it, the copilot


@pytest.fixture
def desk(engine, tmp_path, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient
    from app.database import get_session
    from app.engine.radar_store import RadarStore
    from app.main import app
    from app.routers import copilot_desk
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(copilot_desk, "_now", lambda: NOW)
    store = RadarStore(path)

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    try:
        with TestClient(app) as client:
            yield type("Desk", (), {"client": client, "store": store})
    finally:
        app.dependency_overrides.pop(get_session, None)


FULL = {**CONTRACT, "spread_pct": 8.7, "delta": 0.45}


def _event(store, event_id=EVENT, session="2026-11-10"):
    store.append_event({"event_id": event_id, "session_date": session, "rule_version": "rd0", "kind": "dip_turn",
                        "direction": "up", "symbols": ["NBIS"], "benchmark": "SPY", "first_seen_at": "2026-11-10T15:01:00Z",
                        "summary": "NBIS turned up from its session low.", "measures": {}, "evidence": [],
                        "universe_version": "v1", "group": None, "coverage": {}, "chart": {}})


def test_the_event_detail_carries_its_setup_card_worded_as_the_ping(desk, engine):  # noqa: F811
    _event(desk.store)
    _event(desk.store, event_id="rd0-2026-11-10-plain")
    setup_id = card(engine, contract=FULL)
    desk.store.append_pass({"session_date": "2026-11-10", "started_at": "2026-11-10T15:04:00.000Z", "finished_at": "2026-11-10T15:04:01.000Z",
                            "universe_version": "v1", "status": "ok", "symbols_requested": 1, "symbols_returned": 1, "unmatched": [],
                            "requests_used": 1, "error": None, "skip_reason": None},
                           [{"symbol": "NBIS", "last": 61.0, "prev_close": 63.0, "open": 62.0, "high": 62.5, "low": 59.85, "volume": 1,
                             "bid": None, "ask": None, "trade_time_ms": None, "retrieved_at": "2026-11-10T15:04:00.000Z"}])
    setup = desk.client.get(f"/copilot/desk/radar-setup?event={EVENT}").json()["setup"]
    assert setup["id"] == setup_id and setup["words"] == "dip turning up" and setup["side"] == "below"
    assert setup["levels_line"] == "In near 61.20 · out below 59.85 (−2.2%)"
    assert setup["contract_line"].startswith("Candidate: NBIS Nov 20 62C · 1.10 × 1.20")
    assert (setup["plan_state"], setup["investigation_id"], setup["paper"]) == ("none", None, {"state": "none"})
    assert setup["last"] == {"price": 61.0, "at": "2026-11-10T15:04:00.000Z"} and setup["distance_pct"] == 1.89
    assert not {"account_id", "trade_id", "capture_id"} & set(setup)
    assert desk.client.get("/copilot/desk/radar-setup?event=rd0-2026-11-10-plain").json() == {"setup": None}  # no card: today's behaviour


def test_plan_it_on_the_desk_runs_the_pings_plan_and_reads_back_planned(desk, engine, monkeypatch):  # noqa: F811
    _event(desk.store)
    setup_id = card(engine, contract=FULL)
    monkeypatch.setattr(radar_setup_plan.time, "time", lambda: NOW)
    monkeypatch.setattr(radar_setup_plan, "_live_price", lambda symbol: 61.4)
    first = desk.client.post(f"/copilot/desk/radar-setup/{setup_id}/plan").json()
    assert first["planned"] and not first["refused"] and first["reply"].startswith("Planned NBIS: out below 59.85. Alert armed.")
    thread = first["setup"]["investigation_id"]
    assert first["setup"]["plan_state"] == "planned" and thread
    again = desk.client.post(f"/copilot/desk/radar-setup/{setup_id}/plan").json()
    assert (again["reply"], again["planned"]) == ("Already planned.", True)
    _, captures, alerts, threads = stored(engine, setup_id)
    assert len(captures) == len(alerts) == len(threads) == 1
    assert desk.client.get(f"/copilot/desk/radar-setup?event={EVENT}").json()["setup"]["investigation_id"] == thread
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    listed = {r["id"]: r["origin"] for r in desk.client.get("/copilot/investigations").json()["investigations"]}
    assert listed == {thread: "radar"}
    with Session(engine) as db:
        assert desk_radar_setups.thread_ids(db, [thread, str(uuid.uuid4())]) == {thread}
    assert desk.client.post(f"/copilot/desk/radar-setup/{uuid.uuid4()}/plan").status_code == 404


def test_plan_it_on_the_desk_refuses_a_price_through_the_level_and_an_earlier_session(desk, engine, monkeypatch):  # noqa: F811
    setup_id = card(engine, contract=FULL)
    monkeypatch.setattr(radar_setup_plan.time, "time", lambda: NOW)
    monkeypatch.setattr(radar_setup_plan, "_live_price", lambda symbol: 59.5)
    through = desk.client.post(f"/copilot/desk/radar-setup/{setup_id}/plan").json()
    assert through["refused"] and not through["planned"] and through["setup"]["plan_state"] == "refused"
    assert "already below 59.85" in through["reply"]
    old = card(engine, event="rd0-2026-11-07-dip-nbis-up-1")
    with Session(engine) as db:
        db.get(RadarSetup, uuid.UUID(old)).session_date = "2026-11-07"
        db.commit()
    monkeypatch.setattr(radar_setup_plan, "_live_price", lambda symbol: 61.4)
    earlier = desk.client.post(f"/copilot/desk/radar-setup/{old}/plan").json()
    assert earlier["refused"] and earlier["reply"] == "This setup is from Nov 7; its level no longer applies. No plan saved."
    assert stored(engine, old)[1] == []


def test_copilot_rows_are_compact_and_replay_never_sees_a_later_plan_or_paper_result(engine):  # noqa: F811
    setup_id = card(engine, contract=FULL)
    with Session(engine) as db:
        row = db.get(RadarSetup, uuid.UUID(setup_id))
        row.created_at = datetime(2026, 11, 10, 15, 1)
        row.record_text = "Your first-hour calls: 9 of 17 green, +$1.2k"
        row.plan_state, row.planned_at = "planned", datetime(2026, 11, 10, 15, 10)
        row.paper_state, row.paper_pnl, row.paper_exit_reason, row.paper_exit_at = "closed", 45.0, "time_stop", datetime(2026, 11, 10, 16, 5)
        db.commit()
        [live] = desk_radar_setups.copilot_rows(db, "2026-11-10")
        assert live == {"symbol": "NBIS", "event_id": EVENT, "setup": "dip turning up", "entry": 61.2, "invalidation": 59.85,
                        "contract": "NBIS Nov 20 62C · 1.10 × 1.20 (8.7% wide) · Δ0.45", "record": "Your first-hour calls: 9 of 17 green, +$1.2k",
                        "plan": "planned", "first_seen": "2026-11-10T15:01:00Z", "paper": "+$45 per contract, out at 60-minute stop"}
        at = lambda hh, mm: datetime(2026, 11, 10, hh, mm, tzinfo=ZoneInfo("UTC")).timestamp()  # noqa: E731
        assert desk_radar_setups.copilot_rows(db, "2026-11-10", at(15, 0)) == []
        [early] = desk_radar_setups.copilot_rows(db, "2026-11-10", at(15, 5))
        assert early["plan"] == "not planned" and "paper" not in early
        [mid] = desk_radar_setups.copilot_rows(db, "2026-11-10", at(15, 30))
        assert mid["plan"] == "planned" and "paper" not in mid
        assert desk_radar_setups.copilot_rows(db, "2026-11-09") == []


def test_the_fixture_radar_today_carries_its_setup_card_and_bounded_drops_setups_last():
    from app.ai import copilot_fixture
    from app.engine import radar_today
    out = copilot_fixture.FixtureEvidence().get_radar_today()
    assert [s["symbol"] for s in out["setups"]] == ["NBIS"]
    assert copilot_fixture.FixtureEvidence().get_radar_today(group="CRWV")["setups"] == []
    big = {"events": [{"x": "y" * 100}] * 3, "setups": [{"x": "y" * 100}] * 3}
    radar_today.bounded(big, 300)
    assert big["events"] == [] and len(big["setups"]) == 2 and big["setups_shown"] == 2
