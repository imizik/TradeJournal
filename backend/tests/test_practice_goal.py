"""The practice goal (docs/copilot-lab.md § Review my week): Review my week proposes one thing to practice
(propose_plan kind=practice, validated, one per answer, writes nothing), the owner confirms it through the owner-only
POST /copilot/practice (one active goal; a new Confirm replaces it), and the week review scores it for that week and
the week before. Seeded on the week review's own test week. No network."""
import asyncio
import copy
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import copilot, copilot_review, copilot_tools, research_job
from app.ai.copilot_fixture import FixtureEvidence
from app.database import get_session
from app.engine import practice_goal
from app.models import FillMarketContext, PhonePing, PracticeGoal
from app.routers import copilot_practice as practice_routes
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_week_review import INVESTIGATION, THU, TUE, WEBULL, _secret_free, _seed_week, _utc, db  # noqa: F401

MONDAY = date(2026, 10, 19)
GOOD = {"kind": "practice", "text": "Exit within 15 minutes when my invalidation breaks.", "measure": "exit_at_invalidation",
        "target": 1, "why": "1 of 2 invalidation hits this week was held past 15 minutes."}
CFG = copilot.Settings(enabled=True, backend="fake", evidence="fixture", model="m", effort="medium", fallbacks=False,
                       key_configured=False)


# --------------------------------------------------------------------------- the proposal

def test_a_practice_proposal_is_validated_and_labelled():
    assert copilot_tools.validate("propose_plan", GOOD) == {
        "kind": "practice", "text": GOOD["text"], "measure": "exit_at_invalidation", "label": "exit at my invalidation",
        "target": 1.0, "why": GOOD["why"]}
    plain = copilot_tools.validate("propose_plan", {**GOOD, "measure": "plan_before_entry", "target": None})
    assert plain["target"] is None and plain["label"] == "plan before entry"
    capped = copilot_tools.validate("propose_plan", {**GOOD, "measure": "max_trades_per_day", "target": 3})
    assert (capped["target"], capped["label"]) == (3.0, "at most 3 trades a day")


@pytest.mark.parametrize("change", [
    {"measure": "win_more"},                                  # not a measure the app can score
    {"measure": None},
    {"target": 1.5}, {"target": 0}, {"target": True},         # a share is above 0 and at most 1
    {"measure": "max_trades_per_day", "target": None},        # the daily cap is required
    {"measure": "max_trades_per_day", "target": 2.5},         # and whole
    {"measure": "max_trades_per_day", "target": 40},
    {"text": "x" * 201}, {"text": "  "}, {"why": "y" * 301},
    {"symbol": "NBIS"},                                       # not a practice argument
])
def test_a_bad_practice_is_refused(change):
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("propose_plan", {**GOOD, **change})
    assert "practice" in copilot_tools.TOOLS[-1]["input_schema"]["properties"]["kind"]["enum"]


def test_proposing_writes_nothing(db):  # noqa: F811
    shown = copilot_tools.call(FixtureEvidence(), "propose_plan", copilot_tools.validate("propose_plan", GOOD))
    assert shown["state"] == "ok" and shown["proposal"]["kind"] == "practice" and "Nothing is saved" in shown["note"]
    assert copilot._summary("propose_plan", shown) == f"proposed practice (exit_at_invalidation): {GOOD['text']}"
    assert db.exec(select(PracticeGoal)).all() == []


def _turn(messages, adapter, evidence=None):
    async def collect():
        return [e async for e in copilot.run_turn(messages, None, CFG, adapter, evidence or FixtureEvidence(),
                                                  datetime(2026, 10, 24, 11, 12))]
    return asyncio.run(collect())


def test_one_practice_per_answer():
    class Twice(copilot.FakeAdapter):
        """Two practice cards in one round, then one more in the next: only the first reaches the owner."""
        async def stream_round(self, system, messages, tools, allow_tools=True):
            if isinstance(messages[-1]["content"], str):
                yield "final", copilot.Round([{"type": "tool_use", "id": "p1", "name": "propose_plan", "input": GOOD},
                                              {"type": "tool_use", "id": "p2", "name": "propose_plan",
                                               "input": {**GOOD, "measure": "plan_before_entry"}}], "tool_use", copilot._zero_usage())
                return
            if len(messages) < 5:
                yield "final", copilot.Round([{"type": "tool_use", "id": "p3", "name": "propose_plan",
                                               "input": {**GOOD, "measure": "respond_to_giveback_15m"}}], "tool_use", copilot._zero_usage())
                return
            yield "final", copilot.Round([{"type": "text", "text": "ok"}], "end_turn", copilot._zero_usage())

    events = _turn([{"role": "user", "content": "Review my week"}], Twice(0))
    assert [e["measure"] for e in events if e["type"] == "proposal"] == ["exit_at_invalidation"]
    assert [e["summary"] for e in events if e["type"] == "tool" and e.get("status") == "error"] == [
        "refused: one practice proposal per answer"] * 2


def test_a_practice_that_fails_after_validation_frees_the_slot(monkeypatch):
    real, calls = copilot_tools.propose, []

    def flaky(evidence, proposal):
        calls.append(proposal["measure"])
        if len(calls) == 1:
            raise RuntimeError("store hiccup")
        return real(evidence, proposal)
    monkeypatch.setattr(copilot_tools, "propose", flaky)

    class Retries(copilot.FakeAdapter):
        async def stream_round(self, system, messages, tools, allow_tools=True):
            if len(messages) < 5:
                yield "final", copilot.Round([{"type": "tool_use", "id": f"p{len(messages)}", "name": "propose_plan", "input": GOOD}],
                                             "tool_use", copilot._zero_usage())
                return
            yield "final", copilot.Round([{"type": "text", "text": "ok"}], "end_turn", copilot._zero_usage())

    events = _turn([{"role": "user", "content": "Review my week"}], Retries(0))
    assert len(calls) == 2 and [e["measure"] for e in events if e["type"] == "proposal"] == ["exit_at_invalidation"]


class BigWeek(FixtureEvidence):
    """The fixture's week with twelve trades and two of three invalidation hits held past 15 minutes."""
    def get_week_review(self, week_start=None):
        week = copy.deepcopy(super().get_week_review(week_start))
        week["sample"] = {"trades": 12, "small": False}
        week["totals"]["trades"] = 12
        week["follow_through"].update(invalidation_hit_while_held=3, held_past_15m=2)
        return week


def test_the_scripted_week_proposes_one_practice_and_a_small_week_none():
    events = _turn([{"role": "user", "content": "Context: Review my week"}], copilot.FakeAdapter(0), BigWeek())
    [card] = [e for e in events if e["type"] == "proposal"]
    assert (card["kind"], card["measure"], card["target"]) == ("practice", "exit_at_invalidation", 1.0)
    assert card["why"] == "2 of 3 invalidation hits this week were held past 15 minutes."
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "To practice next week" in text and "on the card below" in text

    small = _turn([{"role": "user", "content": "Context: Review my week"}], copilot.FakeAdapter(0))
    assert not [e for e in small if e["type"] == "proposal"]
    assert "Small sample" in "".join(e["delta"] for e in small if e["type"] == "text")


def test_the_prompt_asks_for_one_scored_practice_and_leads_with_the_score():
    prompt = " ".join(copilot.SYSTEM_PROMPT.split())
    for phrase in ("propose exactly one of them with propose_plan kind=practice when the counts support it",
                   "the measure from the fixed set", "the count it rests on", "Propose no practice when the week is too small",
                   "open with the practice score in one sentence", "never characterizing the owner",
                   "at most one or two things to practice next week", "Lead with planned vs unplanned"):
        assert phrase in prompt, phrase


def test_the_job_allowlist_is_unchanged():
    assert research_job.JOB_TOOLS == ("get_group_comparison", "get_peer_moves", "get_symbol_news", "get_symbol_events",
                                      "get_quotes", "get_saved_research", "get_chart_context")
    assert not [t for t in research_job.LAB_TOOLS if "propose_plan" in t or "week_review" in t]


# --------------------------------------------------------------------------- confirming

def test_a_new_goal_replaces_the_active_one(db):  # noqa: F811
    first = practice_goal.save(db, text="Plan first.", measure="plan_before_entry", target=None, investigation_id=None,
                               today=date(2026, 10, 24))  # a Saturday: practiced from the next Monday
    assert (first.status, first.week_start) == ("active", date(2026, 10, 26))
    second = practice_goal.save(db, text="Act on give-backs.", measure="respond_to_giveback_15m", target=0.5,
                                investigation_id=INVESTIGATION, today=date(2026, 10, 28))  # its first week is not over
    db.refresh(first)
    assert (first.status, second.status, second.week_start) == ("dropped", "active", date(2026, 10, 26))
    third = practice_goal.save(db, text="Three a day at most.", measure="max_trades_per_day", target=3, investigation_id=None,
                               today=date(2026, 10, 31))
    db.refresh(second)
    assert (second.status, third.status) == ("scored", "active") and second.ended_at is not None
    assert practice_goal.active(db).id == third.id
    assert len(db.exec(select(PracticeGoal).where(PracticeGoal.status == "active")).all()) == 1
    with pytest.raises(practice_goal.PracticeError):
        practice_goal.save(db, text="x", measure="max_trades_per_day", target=None, investigation_id=None, today=date(2026, 11, 2))


@pytest.fixture
def lab(db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(practice_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    app = FastAPI()
    app.include_router(practice_routes.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        yield client


def test_the_route_confirms_reads_and_replaces(lab, db):  # noqa: F811
    assert lab.get("/copilot/practice").json() == {"goal": None, "this_week": None}
    made = lab.post("/copilot/practice", json={"text": "  Plan   first. ", "measure": "plan_before_entry", "target": 0.8,
                                               "investigation_id": INVESTIGATION})
    assert made.status_code == 201
    goal = made.json()["goal"]
    assert (goal["text"], goal["measure"], goal["label"], goal["target"]) == ("Plan first.", "plan_before_entry", "plan before entry", 0.8)
    assert INVESTIGATION not in made.text  # the page never gets ids back
    assert lab.post("/copilot/practice", json={"text": "Exit at the line.", "measure": "exit_at_invalidation"}).status_code == 201
    assert lab.get("/copilot/practice").json()["goal"]["measure"] == "exit_at_invalidation"
    assert [g.status for g in db.exec(select(PracticeGoal).order_by(PracticeGoal.created_at)).all()] == ["dropped", "active"]
    assert db.exec(select(PracticeGoal).where(PracticeGoal.status == "dropped")).one().investigation_id == INVESTIGATION
    for bad in ({"text": "x", "measure": "nope"}, {"text": "x", "measure": "max_trades_per_day"}, {"text": "", "measure": "plan_before_entry"},
                {"text": "x", "measure": "plan_before_entry", "investigation_id": "not-an-id"}):
        assert lab.post("/copilot/practice", json=bad).status_code == 422


def test_refused_while_the_lab_is_off(lab, monkeypatch):
    monkeypatch.setattr(practice_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/practice").status_code == 503
    assert lab.post("/copilot/practice", json={"text": "x", "measure": "plan_before_entry"}).status_code == 503


def test_assistant_sessions_cannot_reach_the_practice_goal(boundary):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    assert boundary.owner.get("/copilot/practice").status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/practice").status_code == 403
    assert boundary.public.post("/copilot/practice", json={"text": "x", "measure": "plan_before_entry"}).status_code == 403


# --------------------------------------------------------------------------- scoring

def _score(db, measure, target=None, monday=MONDAY):  # noqa: F811
    out = practice_goal.score(db, measure, target, monday)
    return out["text"], out["met"], out.get("source")


def test_each_measure_scores_the_seeded_week(db):  # noqa: F811
    _seed_week(db)
    assert _score(db, "plan_before_entry", 0.5) == ("2 of 5", False, None)        # NBIS and CRWV planned before the entry
    assert _score(db, "plan_before_entry") == ("2 of 5", None, None)              # no target, no verdict
    # No invalidation ping judged yet: the plans' follow-through (NBIS out in 10 min, CRWV held 70).
    assert _score(db, "exit_at_invalidation", 1) == ("1 of 2", False, "plan follow-through")
    assert _score(db, "respond_to_giveback_15m") == ("0 of 1", None, None)        # IREN's give-back, closed later
    assert _score(db, "no_trade_after_hour_red") == ("1 of 4", None, None)        # NBIS, CRWV and IREN held an hour, red
    assert _score(db, "no_opening_while_green") == ("0 of 0", None, None)         # no day P&L recorded yet
    assert _score(db, "max_trades_per_day", 1) == ("1 of 3", False, None)         # Tue 1, Wed 2, Thu 2 (Webull left out)
    assert _score(db, "max_trades_per_day", 2) == ("3 of 3", True, None)


def test_invalidation_pings_and_day_pnl_are_used_when_present(db):  # noqa: F811
    _seed_week(db)
    for n, then in enumerate(("closed", "trimmed", "held", None, "unmatched")):
        db.add(PhonePing(sender="level_alerts", source_id=f"ping-{n}", kind="invalidation", rank=1, decision="sent", title="t",
                         body="b", decided_at=_utc(TUE) + timedelta(hours=n), then=then))
    db.add(PhonePing(sender="level_alerts", source_id="held-back", kind="invalidation", rank=1, decision="merged", title="t",
                     body="b", decided_at=_utc(TUE), then="closed"))
    for fill_id, day_pnl in ((1, 0.0), (3, 120.0), (5, -40.0), (7, 80.0)):  # the long options' first entries
        db.add(FillMarketContext(fill_id=UUID(int=fill_id), data_source="test", fetched_at=datetime(2026, 10, 25),
                                 realized_pnl_today_before=day_pnl))
    db.commit()
    db.add(PhonePing(sender="position_alerts", source_id="webull", kind="invalidation", rank=1, decision="sent", title="t",
                     body="b", decided_at=_utc(TUE), then="held", anchor=f"{WEBULL}:week:11"))  # dormant: left out
    db.commit()
    assert _score(db, "exit_at_invalidation", 0.5) == ("2 of 3", True, "invalidation pings")
    assert _score(db, "no_opening_while_green", 0.75) == ("2 of 4", False, None)  # CRWV and IREN opened on a green day


def test_the_week_review_leads_with_the_goal_this_week_and_last(db):  # noqa: F811
    _seed_week(db)
    practice_goal.save(db, text="Capture a plan before every entry.", measure="plan_before_entry", target=0.8,
                       investigation_id=INVESTIGATION, today=date(2026, 10, 20))
    week = copilot_review.week_review("2026-10-21", session=db)
    _secret_free(week)  # no ids, within the tool bound
    practice = week["practice"]
    assert practice["state"] == "ok" and practice["practicing"] is True
    assert practice["goal"] == {"text": "Capture a plan before every entry.", "measure": "plan_before_entry",
                                "label": "plan before entry", "target": 0.8, "week_start": "2026-10-19",
                                "since": practice["goal"]["since"]}
    assert (practice["this_week"]["text"], practice["this_week"]["met"]) == ("2 of 5", False)
    assert (practice["last_week"]["week_start"], practice["last_week"]["text"]) == ("2026-10-12", "0 of 1")  # the NBIS stock trade
    earlier = copilot_review.week_review("2026-10-16", session=db)["practice"]
    assert earlier["practicing"] is False  # that week came before the goal

    text = "".join(e["delta"] for e in _turn([{"role": "user", "content": "Review my week"}], copilot.FakeAdapter(0),
                                             _Live(db)) if e["type"] == "text")
    assert text.index("**Practice** (plan before entry): 2 of 5 this week, 0 of 1 the week before.") < text.index("**Week of")


class _Live(FixtureEvidence):
    """The fixture, except the week review reads the seeded journal."""
    label = "fixture"

    def __init__(self, db):  # noqa: F811
        super().__init__()
        self.db = db

    def get_week_review(self, week_start=None):
        return copilot_review.week_review(week_start, session=self.db)


def test_the_lab_line_reads_the_current_week(db):  # noqa: F811
    _seed_week(db)
    practice_goal.save(db, text="Act on give-backs.", measure="respond_to_giveback_15m", target=None, investigation_id=None,
                       today=date(2026, 10, 24))  # Saturday: starts Monday the 26th
    assert practice_goal.current(db, date(2026, 10, 24))["this_week"] is None  # not started yet
    later = practice_goal.current(db, date(2026, 10, 27))
    assert later["goal"]["week_start"] == "2026-10-26" and later["this_week"]["text"] == "0 of 0"
    assert json.dumps(later).count("-") < 20  # dates only; no ids
