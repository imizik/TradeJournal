"""Plan it on a Radar setup ping: one tap saves the setup card as a plan and arms its invalidation alert."""

from datetime import datetime
import json
import uuid
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.engine import level_alerts, radar_proof, radar_setup_plan
from app.models import CopilotInvestigation, LevelAlert, RadarSetup, TradeCapture
from tests.test_exit_habits import ROTH, engine  # noqa: F401

NOW = datetime(2026, 11, 10, 10, 5, tzinfo=ZoneInfo("America/New_York")).timestamp()
EVENT = "rd0-2026-11-10-dip-nbis-up-1"
CONTRACT = {"symbol": "NBIS261120C00062000", "option_type": "call", "strike": 62.0, "expiration": "2026-11-20",
            "bid": 1.1, "ask": 1.2, "mid": 1.15}


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
    assert tap(engine, setup_id) == ("Planned NBIS: out below 59.85. Alert armed.", "Planned")
    row, (capture,), (alert,), (thread,) = stored(engine, setup_id)
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
    assert tap(engine, setup_id, last=61.0) == ("Planned NBIS: out above 63.00. Alert armed.", "Planned")
    row, (capture,), (alert,), (thread,) = stored(engine, setup_id)
    assert thread.title == "Radar setup: NBIS gap up turning down"
    assert (capture.side, capture.strike, capture.expiration) == ("buy_puts", None, None)
    assert "Contract" not in capture.note and (alert.direction, alert.plan_role) == ("up", "invalidation")


def test_a_double_tap_saves_one_plan(engine):  # noqa: F811
    setup_id = card(engine)
    assert tap(engine, setup_id)[1] == "Planned"
    assert tap(engine, setup_id) == ("Already planned.", "Planned")
    _, captures, alerts, threads = stored(engine, setup_id)
    assert (len(captures), len(alerts), len(threads)) == (1, 1, 1)


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
    assert reply == "Planned NBIS: out below 59.85. Alert not armed: 0 alerts are already active. Remove one first."
    assert chosen == "Planned"
    row, (capture,), alerts, (thread,) = stored(engine, setup_id)
    assert (row.plan_state, row.investigation_id, alerts) == ("planned", str(thread.id), [])
    assert capture.origin_ref == EVENT


def test_an_unknown_setup_writes_nothing(engine):  # noqa: F811
    assert tap(engine, str(uuid.uuid4())) == ("That setup is no longer available.", None)
    assert tap(engine, "not-an-id") == ("That setup is no longer available.", None)
    with Session(engine) as db:
        assert db.exec(select(TradeCapture)).all() == [] and db.exec(select(CopilotInvestigation)).all() == []
