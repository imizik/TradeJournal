"""The automatic week review (docs/copilot-lab.md § Review my week): on the week's last trading day after its time, one
copilot turn on the owner's "Review my week" context, saved as a copilot investigation, and one phone ping that opens
it, with the practice it proposed shown as a card there until confirmed. Once a week, shifted to Thursday on a Friday
holiday, skipped for a week with no closed trade, off by default and while the lab is off, the week's facts when the
turn fails, gated by the notification policy. Seeded on the week review's own test week. No network."""

import asyncio
from datetime import date, datetime
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.ai import copilot
from app.database import get_session
from app.engine import notification_policy, ntfy, practice_goal, week_review_auto
from app.engine.chart_math import ET
from app.engine.level_alert_monitor import LevelAlertMonitor
from app.engine.week_review_auto import CONFIRM, FALLBACK_LABEL, WeekReviews
from app.models import CopilotInvestigation, PhonePing, WeekReviewAuto
from app.routers import copilot_practice as practice_routes
from tests.test_copilot_week_review import INVESTIGATION, _seed_week, db  # noqa: F401

MONDAY, THU, FRI, SAT = date(2026, 10, 19), date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 24)
NEXT_FRI = date(2026, 10, 30)
PROPOSAL = {"type": "proposal", "id": "plan_2", "kind": "practice", "text": "Exit within 15 minutes when my invalidation breaks.",
            "measure": "exit_at_invalidation", "label": "exit at my invalidation", "target": 1.0,
            "why": "1 of 2 invalidation hits this week was held past 15 minutes."}
ANSWER = ("**Practice** (plan before entry): 2 of 5 this week, 0 of 1 the week before.\n\n"
          "- Planned trades lost less than unplanned ones: 2 planned before the entry.\n"
          "Third line, not on the phone.")


def at(hhmm: str, day: date = FRI) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    """Every weekday open 9:30-16:00, except the days named closed."""

    def __init__(self, *closed: date):
        self.closed = set(closed)

    def hours(self, day):
        if day.weekday() >= 5 or day in self.closed:
            return {"status": "closed"}
        return {"status": "open", "open": 570, "close": 960}


class Turn:
    def __init__(self, text=ANSWER, error=None, events=()):
        self.text, self.error, self.events, self.calls = text, error, list(events), []

    def __call__(self, question, now):
        self.calls.append(question)
        return self.text, self.error, self.events


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("WEEK_REVIEW_AUTO_ENABLED", "true")
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    monkeypatch.delenv("WEEK_REVIEW_AUTO_AT", raising=False)
    monkeypatch.delenv("PING_DAILY_CAP", raising=False)


@pytest.fixture
def engine(db):  # noqa: F811
    _seed_week(db)
    return db.get_bind()


@pytest.fixture
def phone(monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    return sent


def reviews(engine, clock, turn, calendar=None):
    return WeekReviews(engine, calendar or Calendar(), clock=clock, spawn=lambda work: work(), turn=turn)


def rows(engine):
    with Session(engine) as db:  # noqa: F811
        return db.exec(select(WeekReviewAuto).order_by(WeekReviewAuto.week_start)).all()


def saved(engine, investigation_id):
    with Session(engine) as db:  # noqa: F811
        return db.get(CopilotInvestigation, UUID(investigation_id))


# ------------------------------------------------------------------ when it runs

def test_friday_after_its_time_it_reviews_saves_and_pings_once(engine, phone):
    turn, clock = Turn(), Clock(at("16:45"))
    runner = reviews(engine, clock, turn)
    runner.run()
    assert turn.calls == ["Context: Review my week of 2026-10-19"]  # the owner's own Review my week context
    [(title, body, kw)] = phone
    assert title == "Your week: -$150 · 2 of 5 planned"
    assert body == ("Practice (plan before entry): 2 of 5 this week, 0 of 1 the week before.\n"
                    "Planned trades lost less than unplanned ones: 2 planned before the entry.")
    path = urlsplit(kw["path"])
    assert path.path == "/copilot-lab" and kw["direct_click"] is True
    investigation_id = parse_qs(path.query)["investigation"][0]
    record = saved(engine, investigation_id)
    assert record.title == "Week review Oct 19–Oct 23" and record.source == "copilot" and record.status == "open"
    transcript = json.loads(record.transcript_json)
    assert transcript == [{"role": "user", "content": "Context: Review my week of 2026-10-19"},
                          {"role": "assistant", "content": ANSWER}]
    assert record.conclusion.startswith("Practice (plan before entry)")
    [row] = rows(engine)
    assert row.week_start == MONDAY and row.delivery == "sent" and row.fallback is False and row.proposal_json is None

    clock.now = at("17:30")
    runner.run()
    reviews(engine, clock, turn).run()  # a restart, or a second process
    runner.deliver()
    assert len(turn.calls) == 1 and len(phone) == 1 and len(rows(engine)) == 1


@pytest.mark.parametrize("moment", [at("16:44"), at("16:45", THU), at("10:00", SAT)],
                         ids=["before its time", "Thursday when Friday trades", "weekend"])
def test_not_before_its_time_or_day(engine, phone, moment):
    turn = Turn()
    reviews(engine, Clock(moment), turn).run()
    assert turn.calls == [] and phone == [] and rows(engine) == []


def test_a_friday_holiday_moves_it_to_thursday(engine, phone):
    turn, closed = Turn(), Calendar(FRI)
    reviews(engine, Clock(at("16:45", FRI)), turn, closed).run()
    assert turn.calls == []
    reviews(engine, Clock(at("16:50", THU)), turn, closed).run()
    assert turn.calls == ["Context: Review my week of 2026-10-19"] and len(phone) == 1


def test_the_time_is_a_setting(engine, phone, monkeypatch):
    monkeypatch.setenv("WEEK_REVIEW_AUTO_AT", "18:00")
    turn = Turn()
    reviews(engine, Clock(at("17:00")), turn).run()
    assert turn.calls == []
    reviews(engine, Clock(at("18:05")), turn).run()
    assert len(turn.calls) == 1


def test_a_week_with_no_closed_trade_is_skipped(engine, phone):
    turn = Turn()
    reviews(engine, Clock(at("16:45", NEXT_FRI)), turn).run()
    assert turn.calls == [] and phone == []
    [row] = rows(engine)
    assert row.week_start == date(2026, 10, 26) and row.delivery == "skipped" and row.investigation_id is None
    with Session(engine) as db:  # noqa: F811
        assert db.exec(select(CopilotInvestigation)).all() == []


@pytest.mark.parametrize("flag", ["WEEK_REVIEW_AUTO_ENABLED", "COPILOT_ENABLED"])
def test_off_by_default_and_nothing_runs_while_the_lab_is_off(engine, phone, monkeypatch, flag):
    monkeypatch.delenv(flag)
    turn = Turn()
    reviews(engine, Clock(at("16:45")), turn).run()
    assert turn.calls == [] and phone == [] and rows(engine) == []


# ------------------------------------------------------------------ the ping

def test_a_proposed_practice_is_kept_for_its_card_and_named_in_the_ping(engine, phone, db):  # noqa: F811
    practice_goal.save(db, text="Capture a plan before every entry.", measure="plan_before_entry", target=0.8,
                       investigation_id=INVESTIGATION, today=date(2026, 10, 20))
    tool = {"type": "tool", "id": "plan_1", "name": "get_week_review", "status": "ok",
            "provenance": {"source": "saved", "kind": "saved", "as_of": "2026-10-23T20:45:00Z", "state": "ok"}}
    reviews(engine, Clock(at("16:45")), Turn(text="Line one.\nLine two.\nLine three.", events=[tool, PROPOSAL])).run()
    [(title, body, kw)] = phone
    assert body.splitlines() == ["Line one.", "Line two.",
                                 "Practice (plan before entry): 2 of 5 this week, 0 of 1 last week", CONFIRM]
    [row] = rows(engine)
    card = week_review_auto.proposed(db, row.investigation_id)
    assert card == {k: v for k, v in PROPOSAL.items() if k != "type"}
    assert json.loads(saved(engine, row.investigation_id).evidence_json) == [
        {"tool": "get_week_review", "as_of": "2026-10-23T20:45:00Z", "kind": "saved", "message": 1}]
    # Confirmed from that investigation's card: it is not shown again.
    practice_goal.save(db, text=card["text"], measure=card["measure"], target=card["target"],
                       investigation_id=row.investigation_id, today=SAT)
    assert week_review_auto.proposed(db, row.investigation_id) is None


def test_the_practice_route_returns_the_card_for_that_investigation(engine, phone, db):  # noqa: F811
    reviews(engine, Clock(at("16:45")), Turn(events=[PROPOSAL])).run()
    [row] = rows(engine)
    app = FastAPI()
    app.include_router(practice_routes.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        assert "proposed" not in client.get("/copilot/practice").json()  # unchanged without the parameter
        assert client.get(f"/copilot/practice?investigation={row.investigation_id}").json()["proposed"]["kind"] == "practice"
        assert client.get(f"/copilot/practice?investigation={INVESTIGATION}").json()["proposed"] is None
        assert client.get("/copilot/practice?investigation=not-an-id").status_code == 422


def test_a_failed_turn_pings_the_weeks_facts_labelled_as_such(engine, phone):
    reviews(engine, Clock(at("16:45")), Turn(text="half", error="Stopped: this turn reached its $0.25 API spend cap.",
                                              events=[PROPOSAL])).run()
    [(title, body, kw)] = phone
    assert title == "Your week: -$150 · 2 of 5 planned"
    assert body.splitlines() == [FALLBACK_LABEL, "5 closed trades, -$150; plan before entry 2, late 1, none 2",
                                 "Invalidation hit while held 2: out within 15 min 1, held past 1"]
    [row] = rows(engine)
    assert row.fallback is True and "spend cap" in row.last_error and row.proposal_json is None  # no card without the answer
    assert json.loads(saved(engine, row.investigation_id).transcript_json)[1]["content"] == row.body


def test_a_turn_through_the_labs_backend_respects_its_budget(engine, phone, monkeypatch):
    """The real ``run_turn`` path: a budget stop mid-turn is a failed turn, so the facts go out."""
    async def over_budget(history, symbol, cfg, adapter, evidence, now):
        assert symbol is None and history == [{"role": "user", "content": "Context: Review my week of 2026-10-19"}]
        yield {"type": "text", "delta": "Your week "}
        yield {"type": "error", "code": "budget", "message": f"Stopped: this turn reached its ${cfg.turn_budget_usd:.2f} API spend cap."}
        yield {"type": "done", "metrics": {}}
    monkeypatch.setattr(copilot, "run_turn", over_budget)
    WeekReviews(engine, Calendar(), clock=Clock(at("16:45")), spawn=lambda work: work()).run()
    [row] = rows(engine)
    assert row.fallback is True and row.last_error == "Copilot turn failed: Stopped: this turn reached its $0.25 API spend cap."
    assert phone[0][1].startswith(FALLBACK_LABEL)


def test_the_fake_backend_reviews_the_week_end_to_end(monkeypatch):
    monkeypatch.setattr(copilot.FakeAdapter, "__init__", lambda self, delay_s=0: setattr(self, "delay_s", 0))
    answer, error, events = WeekReviews._lab_turn(week_review_auto.prompt(MONDAY), at("16:45"))
    assert error is None and week_review_auto.answer_lines(answer)
    assert [e["input"] for e in events if e["type"] == "tool" and e.get("name") == "get_week_review" and e.get("status") == "ok"] == [
        {"week_start": "2026-10-19"}]


def test_a_held_ping_is_recorded_not_sent(engine, phone, monkeypatch):
    monkeypatch.setenv("PING_DAILY_CAP", "0")
    reviews(engine, Clock(at("16:45")), Turn()).run()
    assert phone == []
    [row] = rows(engine)
    assert row.delivery == "held" and "cap 0" in row.last_error
    with Session(engine) as db:  # noqa: F811
        [ping] = db.exec(select(PhonePing)).all()
    assert (ping.sender, ping.kind, ping.decision) == ("week_review_auto", "week_review", "over_cap")
    assert ping.rank == notification_policy.rank("prep")  # ranked with the pre-market prep


def test_a_review_that_never_finished_is_not_sent_late(engine, phone):
    clock, held = Clock(at("16:45")), []
    runner = WeekReviews(engine, Calendar(), clock=clock, spawn=held.append, turn=Turn())
    runner.run()
    clock.now = at("17:01")
    runner.deliver()
    assert rows(engine)[0].delivery == "expired" and phone == []
    held[0]()  # finishing now changes nothing
    assert rows(engine)[0].delivery == "expired" and phone == []


def test_the_monitor_runs_the_review_on_its_loop(engine):
    calls = []
    fake = SimpleNamespace(run=lambda: calls.append("run"), deliver=lambda: calls.append("deliver"))
    asyncio.run(LevelAlertMonitor(engine, None, week_review=fake).run_once())
    assert calls == ["run", "deliver"]
