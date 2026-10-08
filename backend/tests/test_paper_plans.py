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
from app.models import DecisionContext, DecisionEvent, DecisionRecord, Fill, Trade
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
        self.issue = None
        self.fail = set()  # symbols whose read raises unexpectedly
        self.on_read = None

    def read(self, path, params, ttl):
        if params["symbol"] in self.fail:
            raise RuntimeError("boom")
        if self.on_read:
            self.on_read()
        rows = [{"timestamp": s, "open": o, "high": h, "low": low, "close": c, "volume": 100} for s, o, h, low, c in self.minutes]
        return {"series": {"data": rows}}, 0, self.issue

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
        db.add(DecisionContext(id=item.context_id, operation_id=f"ctx-{uuid.uuid4()}", symbol=symbol,
                               captured_at=item.input_cutoff, provider="fixture", data_json="{}", context_sha256="e"))
        db.commit()
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
    assert types(engine, rid) == ["armed", "trigger", "order_intent"]
    feed.minutes.append((at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5))
    clock.now = at(DAY, 10, 17, 31)
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent", "entry"]
    feed.minutes.append((at(DAY, 10, 17), 100.5, 104.1, 100.5, 104.0))
    clock.now = at(DAY, 10, 18, 31)
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent", "entry", "exit"]
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
    assert types(engine, rid) == ["armed", "trigger", "order_intent", "entry"]


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
    w.splits = type("S", (), {"get": lambda self, s, d: {"status": "ok", "splits": [{"ex_date": NEXT.isoformat(), "ratio": 2}]}})()
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


def test_a_late_message_says_it_is_late_and_an_on_time_one_does_not():
    item = DecisionRecord(symbol="SPY")
    _, body = paper.message(item, {"type": "entry", "at": 1020, "bar_start": 1020, "fill": 100.5}, 1020 + 60 + 30 + 600)
    assert "late by 10 min" in body
    # An entry minute is dated by its start but only knowable a minute and a half later: not late.
    _, body = paper.message(item, {"type": "entry", "at": 1020, "bar_start": 1020, "fill": 100.5}, 1020 + 60 + 30 + 20)
    assert "late" not in body
    _, body = paper.message(item, {"type": "trigger", "at": 1000, "close": 100.2, "level": 100}, 1000 + 40)
    assert "late" not in body


# ---------------------------------------------------------------- review fixes


def test_a_stale_feed_answer_is_never_judged(engine):
    rid, feed, clock, w = lifecycle(engine)
    feed.issue = "stale: provider unreachable"
    w.run()
    assert types(engine, rid) == ["armed"]
    feed.issue = None
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent"]


def test_a_restart_past_expiry_still_records_the_missed_trigger(engine):
    rid, feed, clock, w = lifecycle(engine)
    clock.now = at(DAY, 15, 30)  # restarted after the plan's expiry; the 10:15 trigger was never seen
    w.run()
    assert types(engine, rid) == ["armed", "missed_trigger"]


def test_a_stale_read_past_expiry_does_not_expire_the_plan_blind(engine):
    rid, feed, clock, w = lifecycle(engine)
    feed.issue = "stale"
    clock.now = at(DAY, 15, 30)
    w.run()
    assert types(engine, rid) == ["armed"]


def test_an_unavailable_split_source_pauses_judging_instead_of_assuming_no_split(engine):
    rid, feed, clock, w = lifecycle(engine)
    w.run()

    class Down:
        def get(self, symbol, day):
            raise RuntimeError("splits unreachable")

    w.splits = Down()
    feed.minutes.append((at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5))
    clock.now = at(DAY, 10, 17, 31)
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent"]
    w.splits = None
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent", "entry"]


def test_the_entry_minute_starts_after_the_trigger_was_stored(engine):
    rid, feed, clock, w = lifecycle(engine)
    clock.now = at(DAY, 10, 15, 58)

    def slow_read():  # the read takes past the next minute boundary before the trigger is stored
        clock.now = at(DAY, 10, 16, 3)

    feed.on_read = slow_read
    w.run()
    feed.on_read = None
    with Session(engine) as db:
        trigger = [r for r in paper.events_for(db, rid) if r.event_type == "trigger"][0]
    assert json.loads(trigger.data_json)["detected_at"] == at(DAY, 10, 16, 3)
    feed.minutes += [(at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5), (at(DAY, 10, 17), 100.7, 100.8, 100.6, 100.7)]
    clock.now = at(DAY, 10, 18, 31)
    w.run()
    with Session(engine) as db:
        entry = [json.loads(r.data_json) for r in paper.events_for(db, rid) if r.event_type == "entry"][0]
    assert entry["bar_start"] == at(DAY, 10, 17)


def test_the_reducer_waits_for_the_minute_after_the_trigger_was_durable():
    terms = px.terms_from_plan(plan())
    state = px.fold([px.arm_event(at(DAY, 9, 0)), {"type": "trigger", "key": "trigger", "at": at(DAY, 10, 15),
                                                   "detected_at": at(DAY, 10, 15, 35)}])
    sessions = [px.Session(DAY.isoformat(), at(DAY, 9, 30), at(DAY, 16, 0))]
    bars = [{"start": at(DAY, 10, m), "o": 100.5, "h": 100.5, "l": 100.5, "c": 100.5} for m in (16, 17)]
    events = px.advance(state, terms, bars, sessions, durable_at=at(DAY, 10, 16, 1))
    assert events[0]["bar_start"] == at(DAY, 10, 17)


def test_one_plans_failure_does_not_stop_the_others(engine):
    spy = record(engine, "SPY")
    qqq = record(engine, "QQQ")
    arm(engine, spy, op="a")
    arm(engine, qqq, op="b")
    feed, clock = Feed(), Clock(at(DAY, 10, 15, 35))
    feed.flat(at(DAY, 9, 30), at(DAY, 10, 14), 99.8)
    feed.minutes.append((at(DAY, 10, 14), 99.9, 100.3, 99.9, 100.2))
    feed.fail = {"SPY"}
    watcher(engine, feed, clock).run()
    assert types(engine, spy) == ["armed"] and types(engine, qqq) == ["armed", "trigger", "order_intent"]


def test_paper_plans_are_judged_even_when_the_level_alert_stage_fails(engine):
    import asyncio

    from app.engine.level_alert_monitor import LevelAlertMonitor

    calls = []

    class Paper:
        def run(self):
            calls.append("run")

        def deliver(self):
            calls.append("deliver")

    monitor = LevelAlertMonitor(engine, None, feed=None, paper=Paper())

    async def broken():
        raise RuntimeError("level alerts failed")

    monitor._run_alerts = broken
    with pytest.raises(RuntimeError):
        asyncio.run(monitor.run_once())
    assert calls == ["run", "deliver"]


# ---------------------------------------------------------------- the routes


def test_arm_and_paper_routes(engine, monkeypatch):
    app = FastAPI()

    def session():
        with Session(engine) as db:
            yield db

    app.include_router(routes.router, prefix="/decisions")
    app.dependency_overrides[get_session] = session
    monkeypatch.setattr(routes, "chart_calendar", Calendar())
    with TestClient(app) as http:
        response = http.post(f"/decisions/{uuid.uuid4()}/arm", json={"operation_id": "a"})
        assert response.status_code == 503 and "watcher" in response.json()["detail"]
    app.state.level_alerts = type("M", (), {"paper": object(), "changed": lambda self: None})()
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


@pytest.mark.parametrize("status", ["unknown", "stale"])
def test_split_metadata_failure_status_does_not_allow_entry(engine, status):
    rid, feed, clock, w = lifecycle(engine)
    w.run()
    feed.minutes.append((at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5))
    clock.now = at(DAY, 10, 17, 31)
    w.splits = type("S", (), {"get": lambda self, s, d: {"status": status, "splits": []}})()
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent"]
    w.splits = type("S", (), {"get": lambda self, s, d: {"status": "ok", "splits": []}})()
    w.run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent", "entry"]


def test_missing_closing_minute_cannot_supply_a_false_fifteen_minute_close(engine):
    rid, feed, clock, w = lifecycle(engine)
    feed.minutes[-1] = (at(DAY, 10, 13), 100.2, 100.3, 100.1, 100.2)
    w.run()
    assert types(engine, rid) == ["armed"]
    feed.minutes.append((at(DAY, 10, 14), 99.8, 99.9, 99.7, 99.8))
    w.run()
    assert types(engine, rid) == ["armed"]


def test_replay_pauses_when_saved_policy_hash_does_not_match(engine):
    rid, feed, clock, w = lifecycle(engine)
    with Session(engine) as db:
        row = paper.events_for(db, rid)[0]
        data = json.loads(row.data_json)
        data["policy_hash"] = "a-different-policy"
        row.data_json = json.dumps(data)
        db.add(row)
        db.commit()
    w.run()
    assert types(engine, rid) == ["armed"]


def test_after_close_restart_recovers_second_session_time_exit(engine):
    rid, feed, clock, w = lifecycle(engine)
    w.run()
    feed.flat(at(DAY, 10, 16), at(DAY, 16, 0))
    feed.flat(at(NEXT, 9, 30), at(NEXT, 16, 0))
    clock.now = at(NEXT, 17, 0)
    watcher(engine, feed, clock).run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent", "entry", "exit"]
    with Session(engine) as db:
        row = paper.paper_row(db, rid)
    assert row["outcome"]["exit_kind"] == "time"
    assert row["events"][-1]["reconstructed"] is True
    watcher(engine, feed, clock).run()
    assert types(engine, rid) == ["armed", "trigger", "order_intent", "entry", "exit"]


def test_concurrent_arms_cannot_bypass_the_symbol_cap(tmp_path, monkeypatch):
    db_engine = create_engine(f"sqlite:///{tmp_path / 'arms.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(db_engine)
    try:
        check_concurrent_symbol_cap(db_engine, monkeypatch)
    finally:
        db_engine.dispose()


def check_concurrent_symbol_cap(db_engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, BrokenBarrierError

    ids = [record(db_engine), record(db_engine)]
    start, eligibility = Barrier(2), Barrier(2)
    original = paper._armed_rows

    def competing_read(db):
        rows = original(db)
        # Without transaction serialization, both callers see an empty list
        # here. With it, the first times out while the second waits for the lock.
        try:
            eligibility.wait(timeout=0.3)
        except BrokenBarrierError:
            pass
        return rows

    monkeypatch.setattr(paper, "_armed_rows", competing_read)

    def attempt(rid):
        start.wait(timeout=5)
        try:
            arm(db_engine, rid, op=str(rid))
            return "armed"
        except paper.PaperError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ids))
    assert sorted(results) == ["armed", "refused"]
    with Session(db_engine) as db:
        assert len([row for row in original(db) if row.record_id in ids]) == 1


@pytest.mark.parametrize("missing", ["whole_interval", "empty_response"])
def test_missing_trigger_coverage_never_expires_a_plan_as_if_nothing_happened(engine, missing):
    rid = record(engine)
    arm(engine, rid)
    feed = Feed()
    if missing == "whole_interval":
        feed.flat(at(DAY, 9, 30), at(DAY, 15, 15), 99.0)
        feed.minutes = [m for m in feed.minutes if not at(DAY, 10, 0) <= m[0] < at(DAY, 10, 15)]
    w = watcher(engine, feed, Clock(at(DAY, 15, 30)))
    w.run()
    assert types(engine, rid) == ["armed"]


def test_entry_intent_is_sampled_after_trigger_commit_across_minute_boundary(engine, monkeypatch):
    rid, feed, clock, w = lifecycle(engine)
    clock.now = at(DAY, 10, 15, 58)
    store = w._store

    def slow_trigger_commit(record, events, **kwargs):
        store(record, events, **kwargs)
        if any(e["type"] == "trigger" for e in events):
            clock.now = at(DAY, 10, 16, 3)

    monkeypatch.setattr(w, "_store", slow_trigger_commit)
    w.run()
    feed.minutes += [(at(DAY, 10, 16), 100.5, 100.6, 100.4, 100.5), (at(DAY, 10, 17), 100.7, 100.8, 100.6, 100.7)]
    clock.now = at(DAY, 10, 18, 31)
    watcher(engine, feed, clock).run()
    with Session(engine) as db:
        events = [json.loads(r.data_json) for r in paper.events_for(db, rid)]
    intent = next(e for e in events if e["type"] == "order_intent")
    entry = next(e for e in events if e["type"] == "entry")
    assert intent["at"] == at(DAY, 10, 16, 3)
    assert intent["eligible_at"] == entry["bar_start"] == at(DAY, 10, 17)
    assert len([e for e in events if e["type"] == "order_intent"]) == 1


def test_crash_between_trigger_and_intent_cannot_backdate_or_delay_entry_indefinitely(engine):
    rid, feed, clock, w = lifecycle(engine)
    with Session(engine) as db:
        state = paper.state_of(db, rid)
    events = px.watch(state, px.terms_from_plan(plan()), [{"start": at(DAY, 10, 0), "end": at(DAY, 10, 15), "close": 100.2}], clock.now)
    with Session(engine) as db:
        paper.append(db, rid, events, now=clock.now)
    clock.now = at(DAY, 10, 25)
    watcher(engine, feed, clock).run()
    assert types(engine, rid) == ["armed", "trigger", "unresolved"]
