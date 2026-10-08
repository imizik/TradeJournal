"""Practice paper plans (A2): arming under P0, the watcher pass, restarts and phone delivery."""

import json
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import decisions, ntfy, paper
from app.engine import paper_execution as px
from app.models import DecisionEvent, DecisionRecord, Fill, Trade
from app.routers import decisions as routes
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DAY, NEXT = date(2026, 10, 7), date(2026, 10, 8)


def at(day, hour, minute, second=0):
    return int(datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ET).timestamp())


class Calendar:
    def __init__(self, closes=None):
        self.closes = closes or {}

    def hours(self, day):
        if day.weekday() >= 5:
            return {"date": day.isoformat(), "status": "closed", "open": None, "close": None}
        return {"date": day.isoformat(), "status": "open", "open": 570, "close": self.closes.get(day, 960)}


class Feed:
    def __init__(self):
        self.minutes = []

    def read(self, path, params, ttl):
        rows = [{"timestamp": s, "open": o, "high": h, "low": low, "close": c, "volume": 100} for s, o, h, low, c in self.minutes]
        return {"series": {"data": rows}}, 0, None

    def flat(self, first, last, price=100.5):
        self.minutes += [(t, price, price, price, price) for t in range(first, last, 60)]


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def plan(**over):
    result = {"instrument": "stock", "direction": "long", "trigger": decisions.POLICY_SPEC["trigger"],
              "trigger_level": 100.0, "stop": 98.0, "target": 104.0, "entry_guard": {"min": 100.0, "max": 101.0},
              "expiry": "2026-10-07T15:15:00-04:00", "max_holding_sessions": 2, "initial_risk_per_share": 2.0,
              "freshness_limit_seconds": 86400, "cost_model": dict(paper.COST)}
    result.update(over)
    return result


def record(engine, symbol="SPY", decision="take", received=at(DAY, 8, 55), **plan_over):
    item = DecisionRecord(operation_id=f"op-{uuid.uuid4()}", opportunity_id="opp", actor="human", decision=decision,
                          symbol=symbol, context_id=uuid.uuid4(), received_at=datetime.fromtimestamp(received, UTC).replace(tzinfo=None),
                          input_cutoff=datetime.fromtimestamp(received - 60, UTC).replace(tzinfo=None),
                          policy_version=decisions.POLICY_VERSION, policy_hash=decisions.POLICY_HASH,
                          evidence_json="{}", evidence_sha256="e", record_sha256="r",
                          decision_json=json.dumps({"plan": plan(**plan_over) if decision == "take" else {}, "rationale": "",
                                                    "wait_condition": None, "wait_expiry": None}))
    with Session(engine) as db:
        db.add(item)
        db.commit()
        db.refresh(item)
    return item.id


def arm(engine, record_id, when=at(DAY, 9, 0), op="arm-1", calendar=None):
    with Session(engine) as db:
        return paper.arm(db, record_id, op, now=datetime.fromtimestamp(when, UTC), calendar=calendar or Calendar())


def types(engine, record_id):
    with Session(engine) as db:
        return [e.event_type for e in paper.events_for(db, record_id)]


def watcher(engine, feed, clock):
    return paper.PaperWatcher(engine, feed, Calendar(), None, clock=clock)


# ---------------------------------------------------------------- arming


def test_arming_stores_the_complete_policy_hash_once(engine):
    rid = record(engine)
    rows, created = arm(engine, rid)
    data = json.loads(rows[0].data_json)
    assert created and data["policy_version"] == "shadow-isaac-p0-v1" and data["policy_hash"] == paper.POLICY_HASH
    assert data["on_time"] is True and rows[0].delivery == "none"
    again, created = arm(engine, rid)
    assert not created and [r.id for r in again] == [r.id for r in rows]
    with pytest.raises(paper.PaperError, match="operation_id"):
        arm(engine, rid, op="arm-2")


@pytest.mark.parametrize("kwargs,match", [
    ({"symbol": "TSLA"}, "universe"),
    ({"decision": "wait"}, "TAKE"),
    ({"cost_model": {"version": "p0-cost-v1", "slippage_bps": 0.5, "slippage_per_share": 0.01}}, "p0-cost-v1"),
    ({"expiry": "2026-10-07T15:30:00-04:00"}, "watch cutoff"),
    ({"received": at(date(2026, 10, 6), 9, 0)}, "decided today"),
])
def test_arming_refuses_what_p0_does_not_allow(engine, kwargs, match):
    with pytest.raises(paper.PaperError, match=match):
        arm(engine, record(engine, **kwargs))
    with Session(engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


def test_arming_refuses_a_closed_day_a_passed_expiry_and_an_early_close_cutoff(engine):
    with pytest.raises(paper.PaperError, match="calendar"):
        arm(engine, record(engine), calendar=type("C", (), {"hours": lambda self, d: None})())
    with pytest.raises(paper.PaperError, match="passed"):
        arm(engine, record(engine), when=at(DAY, 15, 16))
    early = Calendar({DAY: 13 * 60})  # an early close moves the cutoff to 12:15
    with pytest.raises(paper.PaperError, match="watch cutoff"):
        arm(engine, record(engine), calendar=early)
    assert arm(engine, record(engine, expiry="2026-10-07T12:15:00-04:00"), calendar=early)[1]


def test_one_active_plan_per_symbol_and_three_per_session(engine):
    arm(engine, record(engine, "SPY"))
    with pytest.raises(paper.PaperError, match="one per symbol"):
        arm(engine, record(engine, "SPY"))
    arm(engine, record(engine, "QQQ"))
    arm(engine, record(engine, "IWM"))
    with pytest.raises(paper.PaperError, match="at most 3"):
        arm(engine, record(engine, "AAPL"))


def test_a_late_decision_arms_but_is_labelled_late(engine):
    rows, _ = arm(engine, record(engine, received=at(DAY, 9, 5)), when=at(DAY, 9, 6))
    assert json.loads(rows[0].data_json)["on_time"] is False


# ---------------------------------------------------------------- the watcher


def lifecycle(engine):
    rid = record(engine)
    arm(engine, rid, when=at(DAY, 9, 0))
    feed, clock = Feed(), Clock(at(DAY, 10, 15, 35))
    feed.flat(at(DAY, 9, 30), at(DAY, 10, 14), 99.8)
    feed.minutes.append((at(DAY, 10, 14), 99.9, 100.3, 99.9, 100.2))  # the 10:00-10:15 bar closes at 100.20
    return rid, feed, clock, watcher(engine, feed, clock)


def test_a_plan_triggers_enters_and_exits_with_no_browser(engine):
    rid, feed, clock, w = lifecycle(engine)
    w.run()
    assert types(engine, rid) == ["armed", "trigger"]
    feed.minutes.append((at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5))
    clock.now = at(DAY, 10, 17, 31)
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "entry"]
    feed.minutes.append((at(DAY, 10, 17), 100.5, 104.1, 100.5, 104.0))
    clock.now = at(DAY, 10, 18, 31)
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "entry", "exit"]
    with Session(engine) as db:
        row = paper.paper_row(db, rid)
        assert db.exec(select(Fill)).all() == [] and db.exec(select(Trade)).all() == []
    assert row["status"] == "closed" and row["outcome"]["planned_r"] == pytest.approx(1.729775)
    assert row["outcome_x3"]["planned_r"] == pytest.approx(1.689325)
    assert all(e["source"] == paper.SOURCE for e in row["events"])


def test_passes_repeated_and_a_restart_record_nothing_twice(engine):
    rid, feed, clock, w = lifecycle(engine)
    w.run()  # the trigger, seen on time
    feed.minutes.append((at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5))
    clock.now = at(DAY, 10, 17, 31)
    for _ in range(3):
        w.run()
        watcher(engine, feed, clock).run()  # a fresh process: state comes from the database only
    assert types(engine, rid) == ["armed", "trigger", "entry"]


def test_a_restart_past_the_detection_delay_is_a_missed_trigger(engine):
    rid, feed, clock, w = lifecycle(engine)
    clock.now = at(DAY, 10, 25)
    w.run()
    assert types(engine, rid) == ["armed", "missed_trigger"]


def test_an_untriggered_plan_expires_quietly(engine):
    rid = record(engine)
    arm(engine, rid)
    feed = Feed()
    feed.flat(at(DAY, 9, 30), at(DAY, 15, 30), 99.0)
    w = watcher(engine, feed, Clock(at(DAY, 15, 21)))
    w.run()
    with Session(engine) as db:
        rows = paper.events_for(db, rid)
    assert [r.event_type for r in rows] == ["armed", "expired"] and rows[-1].delivery == "none"


def test_a_split_after_entry_leaves_the_outcome_unresolved(engine):
    rid, feed, clock, w = lifecycle(engine)
    feed.minutes.append((at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5))
    clock.now = at(DAY, 10, 17, 31)
    w.run()
    w.splits = type("S", (), {"get": lambda self, s, d: {"splits": [{"ex_date": NEXT.isoformat(), "ratio": 2}]}})()
    clock.now = at(NEXT, 9, 31)
    w.run()
    assert types(engine, rid)[-1] == "unresolved"


# ---------------------------------------------------------------- the phone


def test_each_paper_event_is_sent_once_and_retried_on_failure(engine, monkeypatch):
    rid, feed, clock, w = lifecycle(engine)
    w.run()
    sent, fail = [], [True]

    def publish(title, body, path=""):
        if fail[0]:
            raise ntfy.NtfyError("down")
        sent.append((title, body, path))

    monkeypatch.setattr(ntfy, "publish", publish)
    w.deliver()
    with Session(engine) as db:
        event = db.exec(select(DecisionEvent).where(DecisionEvent.event_type == "trigger")).one()
        assert event.delivery == "pending" and event.attempts == 1
    fail[0] = False
    clock.now += 60
    w.deliver()
    w.deliver()
    assert len(sent) == 1
    title, body, path = sent[0]
    assert title == "PRACTICE · SPY trigger" and "Not a real trade" in body and path == f"/?decision={rid}"


def test_a_late_message_says_it_is_late():
    item = DecisionRecord(symbol="SPY")
    _, body = paper.message(item, {"type": "entry", "at": 1000, "fill": 100.5}, 1000 + 600)
    assert "late by 10 min" in body


# ---------------------------------------------------------------- the routes


def test_arm_and_paper_routes(engine, monkeypatch):
    app = FastAPI()

    def session():
        with Session(engine) as db:
            yield db

    app.include_router(routes.router, prefix="/decisions")
    app.dependency_overrides[get_session] = session
    monkeypatch.setattr(routes, "chart_calendar", Calendar())
    rid = record(engine, received=at(date(2026, 10, 6), 9, 0))
    real = paper.arm
    monkeypatch.setattr(routes.paper, "arm", lambda db, r, op, now, calendar: real(
        db, r, op, now=datetime.fromtimestamp(at(DAY, 9, 0), UTC), calendar=calendar))
    with TestClient(app) as http:
        assert http.post(f"/decisions/{uuid.uuid4()}/arm", json={"operation_id": "a"}).status_code == 404
        refused = http.post(f"/decisions/{rid}/arm", json={"operation_id": "a"})
        assert refused.status_code == 422  # decided on another day than the arming day
        good = record(engine)
        first = http.post(f"/decisions/{good}/arm", json={"operation_id": "a"})
        assert first.status_code == 201 and first.json()["status"] == "armed"
        assert http.post(f"/decisions/{good}/arm", json={"operation_id": "a"}).status_code == 200
        assert http.post(f"/decisions/{good}/arm", json={"operation_id": "b"}).status_code == 409
        assert http.get(f"/decisions/{good}/paper").json()["events"][0]["type"] == "armed"


def test_the_policy_hash_covers_the_execution_rules():
    assert paper.POLICY_SPEC["execution"]["version"] == px.EXEC_VERSION
    assert paper.POLICY_SPEC["plan_schema"]["hash"] == decisions.POLICY_HASH
