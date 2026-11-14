"""The copilot's desk actions (docs/copilot-lab.md § Desk actions): desk_action checks a request against the desk and
returns a card; nothing is written by the tool, the turn or the save. Offline: fixture quotes, an in-memory database."""
import asyncio
from datetime import date

import pytest
from sqlmodel import Session, select

from app.ai import copilot, copilot_actions, copilot_prompt, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence, desk_requests
from app.engine import copilot_investigations, desk_watch
from app.models import DayJournalEntry, LevelAlert
from tests.test_copilot import NOW, _cfg
from tests.test_desk_ticket import NBIS, WED, engine, plan  # noqa: F401  (the shared fixture and plan helper)


class Desk:
    """Evidence with a fixed desk and fixed prices."""
    label = "fixture"

    def __init__(self, hidden=False, watching=(), plans=(), tickets=(), last=101.20):
        self.state = {"hidden": hidden, "watching": list(watching), "plans": list(plans), "tickets": list(tickets)}
        self.last = last

    def desk_state(self, symbol):
        return self.state

    def get_quotes(self, symbols):
        return {"fetched_at": 1_792_857_000, "prices": {s: self.last for s in symbols}}


PLAN = {"investigation_id": NBIS, "direction": "long", "thesis": "Reclaims VWAP",
        "invalidation": {"price": 92.30, "alert_id": "33333333-3333-4333-8333-333333333333", "state": "active"}}


def card(evidence, **args):
    return copilot_actions.act(evidence, copilot_actions.validate(args), now=1_792_857_000)["action"]


def refused(evidence, **args):
    with pytest.raises(copilot_tools.ToolInputError) as exc:
        card(evidence, **args)
    return str(exc.value)


# --------------------------------------------------------------------------- the request

@pytest.mark.parametrize("args,why", [
    ({"action": "order", "symbol": "NBIS"}, "action must be"),
    ({"action": "show", "symbol": "NBIS", "timeframe": "5m"}, "2m, 15m and 1D"),
    ({"action": "show", "symbol": "NBIS", "price": 98}, "unexpected arguments"),
    ({"action": "alert", "symbol": "NBIS", "price": 98}, "above or below"),
    ({"action": "alert", "symbol": "NBIS", "price": -1, "side": "below"}, "positive"),
    ({"action": "draw", "symbol": "NBIS", "price": 102.5, "label": "x" * 41}, "at most 40"),
    ({"action": "ticket", "symbol": "NBIS", "strike": 100, "option_type": "call", "expiry": "Dec 19"}, "YYYY-MM-DD"),
    ({"action": "watch", "symbol": "../etc"}, "US ticker"),
])
def test_a_request_takes_only_its_own_arguments(args, why):
    with pytest.raises(copilot_tools.ToolInputError, match=why):
        copilot_tools.validate("desk_action", args)


def test_a_view_change_is_a_card_too_and_needs_no_price():
    shown = card(Desk(last=None), action="show", symbol="NBIS", timeframe="15m")
    assert shown == {"action": "show", "symbol": "NBIS", "timeframe": "15m", "tab": "chart", "made_at": 1_792_857_000}
    assert copilot_actions.line(shown) == "Show NBIS · 15m"
    assert copilot_actions.line(card(Desk(), action="show", symbol="NBIS", tab="chain")) == "Show NBIS · Chain"


def test_an_alert_card_says_what_it_sets_and_keeps_the_price_it_was_made_at():
    made = card(Desk(), action="alert", symbol="NBIS", side="below", price=98)
    assert copilot_actions.line(made) == "Set alert: NBIS below 98.00"
    assert made["last"] == 101.20 and made["as_of"] == 1_792_857_000 and made["label"] is None


def test_an_alert_on_the_wrong_side_or_far_away_is_refused_and_asks():
    assert "already above 98.00" in refused(Desk(), action="alert", symbol="NBIS", side="above", price=98)  # 101.20 is above it
    assert "more than 50%" in refused(Desk(), action="alert", symbol="NBIS", side="below", price=40)
    assert "no side" in refused(Desk(last=98.0), action="alert", symbol="NBIS", side="below", price=98)
    assert "no current price" in refused(Desk(last=None), action="draw", symbol="NBIS", price=98)


def test_a_ticker_he_stopped_following_gets_no_card_of_any_kind():
    for args in ({"action": "show", "symbol": "NBIS"}, {"action": "watch", "symbol": "NBIS"},
                 {"action": "alert", "symbol": "NBIS", "side": "below", "price": 98}):
        assert "Not following" in refused(Desk(hidden=True), **args)


def test_watching_checks_the_list_as_it_is():
    assert copilot_actions.line(card(Desk(watching=["APLD"]), action="watch", symbol="IREN")) == "Watch IREN"
    assert "already on the Watching list" in refused(Desk(watching=["IREN"]), action="watch", symbol="IREN")
    assert "not on the Watching list" in refused(Desk(), action="unwatch", symbol="IREN")


def test_moving_a_plans_stop_names_the_plan_and_the_stop_it_replaces():
    moved = card(Desk(plans=[PLAN]), action="plan_stop", symbol="NBIS", price=96)
    assert moved["investigation_id"] == NBIS and moved["alert_id"] == PLAN["invalidation"]["alert_id"]
    assert moved["was"] == 92.30 and moved["direction"] == "long"
    assert copilot_actions.line(moved) == "Update plan: NBIS stop 92.30 → 96.00"
    assert "no saved plan" in refused(Desk(), action="plan_stop", symbol="NBIS", price=96)
    assert "ask the owner which one" in refused(Desk(plans=[PLAN, {**PLAN, "investigation_id": "x"}]), action="plan_stop", symbol="NBIS", price=96)
    assert "already past" in refused(Desk(plans=[PLAN]), action="plan_stop", symbol="NBIS", price=102)  # a long's stop above the price
    assert "already 92.30" in refused(Desk(plans=[PLAN]), action="plan_stop", symbol="NBIS", price=92.3)


def test_a_ticket_opens_only_from_one_saved_plan_of_that_kind():
    tickets = [{"investigation_id": NBIS, "option_type": "call", "thesis": "Reclaims VWAP"}]
    opened = card(Desk(tickets=tickets), action="ticket", symbol="NBIS", strike=100, option_type="call", expiry="2026-12-18")
    assert opened["investigation_id"] == NBIS and copilot_actions.line(opened) == "Open ticket: NBIS 100 call Dec 18"
    assert "for calls, not puts" in refused(Desk(tickets=tickets), action="ticket", symbol="NBIS", strike=100, option_type="put", expiry="2026-12-18")
    assert "no saved plan" in refused(Desk(), action="ticket", symbol="NBIS", strike=100, option_type="call", expiry="2026-12-18")
    assert "passed" in refused(Desk(tickets=tickets), action="ticket", symbol="NBIS", strike=100, option_type="call", expiry="2026-10-01")


def test_replay_evidence_has_no_desk():
    class Replay:
        label = "replay"
    assert "not available" in refused(Replay(), action="show", symbol="NBIS")


# --------------------------------------------------------------------------- the desk as it stands

def test_the_desk_state_reads_follow_watching_and_plans_without_a_quote(engine, monkeypatch):  # noqa: F811
    import app.database
    monkeypatch.setattr(app.database, "engine", engine)
    plan(engine)
    with Session(engine) as db:
        desk_watch.add(db, "IREN")
        db.add(DayJournalEntry(operation_id="f1", day=WED, kind="follow", symbol="RKLB", text="Not following"))
        db.commit()
        stop = db.exec(select(LevelAlert).where(LevelAlert.plan_role == "invalidation")).one()
    state = copilot_actions.read_state("NBIS")
    assert state["hidden"] is False and "IREN" in state["watching"]  # beside the Charts list it started from
    assert state["plans"] == [{"investigation_id": NBIS, "direction": "long", "thesis": "Reclaims VWAP with the group.",
                               "invalidation": {"price": 90.0, "alert_id": str(stop.id), "state": "active"}}]
    assert [t["investigation_id"] for t in state["tickets"]] == [NBIS] and state["tickets"][0]["option_type"] == "call"
    assert copilot_actions.read_state("RKLB")["hidden"] is True


# --------------------------------------------------------------------------- the turn

def run(question, job="desk", evidence=None):
    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": question}], "NBIS", _cfg(), copilot.FakeAdapter(delay_s=0),
                                                  evidence or Desk(), NOW, job=job)]
    return asyncio.run(collect())


@pytest.mark.parametrize("question,line", [
    ("Alert me if NBIS loses 98", "Set alert: NBIS below 98.00"),
    ("Show me NBIS on the 15 minute", "Show NBIS · 15m"),
    ("Open the chain for NBIS", "Show NBIS · Chain"),
    ("Watch IREN", "Watch IREN"),
    ("Mark 102.50 as resistance on NBIS", "Draw 102.50 on NBIS · resistance"),
    ("Build the 100 call for Dec 18 on NBIS", "Open ticket: NBIS 100 call Dec 18"),
    ("Move my stop on the NBIS plan to 96", "Update plan: NBIS stop 92.30 → 96.00"),
])
def test_the_scripted_model_makes_each_card(question, line):
    desk = Desk(plans=[PLAN], tickets=[{"investigation_id": NBIS, "option_type": "call", "thesis": None}])
    events = run(question, evidence=desk)
    [proposal] = [e for e in events if e["type"] == "proposal"]
    assert proposal["kind"] == "desk_action" and copilot_actions.line(proposal) == line
    assert "Verdict:" not in "".join(e["delta"] for e in events if e["type"] == "text")


def test_a_missing_part_is_a_question_and_a_refusal_is_said_not_acted_on():
    events = run("Show me NBIS on the 5-minute")
    assert not [e for e in events if e["type"] == "proposal"]
    assert "2m, 15m and 1D" in "".join(e["delta"] for e in events if e["type"] == "text")
    events = run("Alert me if NBIS loses 98", evidence=Desk(hidden=True))
    assert not [e for e in events if e["type"] == "proposal"]
    assert "Not following" in "".join(e["delta"] for e in events if e["type"] == "text")


def test_at_most_three_actions_in_one_answer():
    class Four:
        model = "claude-sonnet-5-5"
        rounds = 0

        async def stream_round(self, system, messages, tools, allow_tools=True):
            self.rounds += 1
            content = ([{"type": "tool_use", "id": f"a{i}", "name": "desk_action", "input": {"action": "show", "symbol": s}}
                        for i, s in enumerate(("NBIS", "CRWV", "APLD", "IREN"))] if self.rounds == 1 else [{"type": "text", "text": "ok"}])
            yield "final", copilot.Round(content, "tool_use" if self.rounds == 1 else "end_turn", copilot._zero_usage(), self.model)

    async def collect():
        return [e async for e in copilot.run_turn([{"role": "user", "content": "Show me all four"}], None, _cfg(), Four(), Desk(), NOW)]
    events = asyncio.run(collect())
    assert len([e for e in events if e["type"] == "proposal"]) == 3
    assert any("at most 3 desk actions" in (e.get("summary") or "") for e in events if e["type"] == "tool")


def test_only_the_desk_is_offered_the_action_and_its_rule():
    for job in copilot_prompt.JOBS:
        offered = "desk_action" in {t["name"] for t in copilot_prompt.TOOLS[job]}
        assert offered is (job == "desk") and ("desk_action" in copilot_prompt.PROMPTS[job]) is (job == "desk"), job
    assert "never offer one unprompted" in copilot_prompt.PROMPTS["desk"]
    events = run("Alert me if NBIS loses 98", job="telegram")
    assert not [e for e in events if e["type"] == "proposal"]


def test_a_desk_action_card_saves_with_its_outcome_and_a_tampered_one_does_not():
    desk = Desk(plans=[PLAN])
    proposal = next(e for e in run("Move my stop on the NBIS plan to 96", evidence=desk) if e["type"] == "proposal")
    stored = {k: v for k, v in proposal.items() if k != "type"} | {"client_id": "card-abc123", "outcome": {"state": "confirmed", "note": "Plan updated: stop 96.00"}}
    assert copilot_investigations._saved_proposal(stored) == stored
    for bad in ({"alert_id": "not-an-id"}, {"action": "order"}, {"made_at": None}, {"price": "96"}):
        with pytest.raises(ValueError):
            copilot_investigations._saved_proposal({**stored, **bad})


def test_the_fixture_reads_only_requests_that_open_the_message():
    today = date(2026, 11, 13)
    assert desk_requests("What should I watch on NBIS today?", "NBIS", today) is None
    assert desk_requests("Is my stop too tight? Move it to 96?", "NBIS", today) is None
    assert desk_requests("Build the 100/110 call spread", "NBIS", today) == "Which NBIS contract: the strike, call or put, and the expiry?"
