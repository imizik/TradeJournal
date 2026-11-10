"""Shadow book v1 (docs/radar.md § Shadow book): the paper rules, the worker against a fixture Radar event and a fake
turn, restarts, the record route, and the turn's tool allowlist against a scripted Messages API client. No network."""
import asyncio
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, delete, select

from app.ai import copilot_spend, copilot_tools, research_job, shadow_turn
from app.ai.copilot_fixture import FixtureEvidence
from app.database import engine as test_engine, get_session
from app.engine import shadow_book as book
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore
from app.models import CopilotTurn, ShadowBookDecision, ShadowBookEvent
from app.routers import radar as radar_routes
from tests.fake_anthropic import FakeAsyncAnthropic, Sleep, answer, api_error, message, text, tool_use
from tests.test_copilot_adversarial import NEVER_IN_JOBS
from tests.test_research_job import lab

DAY = date(2026, 10, 22)  # a Thursday
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())["event"]


def at(hour, minute, second=0, day=DAY) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=ET).timestamp())


def stamp(moment: int) -> str:
    return datetime.fromtimestamp(moment, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


CLOSE = at(16, 0)


def plan_answer(**overrides):
    plan = {"symbol": "NBIS", "direction": "long", "instrument": "calls", "contract_expiration": "2026-10-24",
            "contract_strike": 120, "entry_trigger": {"condition": "crosses", "price": 118.0},
            "invalidation": {"condition": "touches", "price": 116.5}, "target": 121.0, "time_stop": "11:30",
            "thesis": "My rule: buy relative strength vs SPY on volume; wrong below 116.50."}
    return {"decision": "plan", "reason": "Leading its group on volume.", "plan": {**plan, **overrides}}


# ------------------------------------------------------------------ the paper rules (pure)


def test_check_plan_builds_the_contract_and_caps_the_time_stop():
    plan = book.check_plan(plan_answer()["plan"], ["NBIS"], at(10, 40), CLOSE)
    assert plan["quote_symbol"] == "NBIS261024C00120000" and plan["contract"] == "2026-10-24 120 call"
    assert plan["unit"] == "1 contract" and plan["target"] == 121.0 and plan["time_stop_at"] == at(11, 30)
    assert plan["kind"] == "trade_plan" and plan["invalidation"]["price"] == 116.5  # the propose_plan shape
    late = book.check_plan(plan_answer(time_stop="17:00")["plan"], ["NBIS"], at(10, 40), CLOSE)
    assert late["time_stop_at"] == CLOSE - 60  # never past the session's last regular minute
    stock = book.check_plan(plan_answer(instrument="stock")["plan"], ["NBIS"], at(10, 40), CLOSE)
    assert stock["quote_symbol"] == "NBIS" and stock["unit"] == "$1,000 of shares"


@pytest.mark.parametrize("overrides, message", [
    ({"target": 117.0}, "target must be above"),
    ({"symbol": "AAPL"}, "not one of this event's symbols"),
    ({"time_stop": "10:00"}, "later than now"),
    ({"time_stop": "soon"}, "New York time"),
    ({"instrument": "puts"}, "calls express a long view"),
    ({"invalidation": {"condition": "touches", "price": 119.0}}, "below its entry"),
    ({"contract_expiration": None}, "contract_expiration"),
])
def test_check_plan_refuses_an_incomplete_or_inconsistent_plan(overrides, message):
    with pytest.raises(book.PlanError, match=message):
        book.check_plan(plan_answer(**overrides)["plan"], ["NBIS"], at(10, 40), CLOSE)


def quote(bid, ask, updated):
    return SimpleNamespace(bid=bid, ask=ask, bid_date=updated * 1000, ask_date=updated * 1000)


def test_entry_is_the_first_fresh_quote_ask_to_buy_bid_to_short():
    calls = book.check_plan(plan_answer()["plan"], ["NBIS"], at(10, 40), CLOSE)
    assert book.entry_fill(calls, quote(2.3, 2.4, at(10, 39)), at(10, 40)) is None  # quoted before the decision
    assert book.entry_fill(calls, quote(2.3, 2.4, at(10, 40, 5)), at(10, 40))["price"] == 2.4
    short = book.check_plan(plan_answer(direction="short", instrument="stock", invalidation={"condition": "touches", "price": 119.5},
                                        target=115.0)["plan"], ["NBIS"], at(10, 40), CLOSE)
    fill = book.entry_fill(short, quote(117.9, 118.1, at(10, 40, 5)), at(10, 40))
    assert fill["price"] == 117.9 and fill["shares"] == 8  # $1,000 // 117.90


def test_results_options_per_contract_and_stock_on_its_shares():
    calls = book.check_plan(plan_answer()["plan"], ["NBIS"], at(10, 40), CLOSE)
    out = book.exit_fill(calls, {"ask": 2.4, "bid": 2.3, "price": 2.4}, quote(3.0, 3.1, at(11, 0)), at(11, 0), "target")
    assert out["price"] == 3.0 and out["pnl"] == pytest.approx((3.0 - 2.4) * 100 - 1.3) and out["reason"] == "target"
    short = {"instrument": "stock", "direction": "short"}
    assert book.result(short, {"price": 118.0, "shares": 8}, {"price": 116.0}) == {"pnl": 16.0, "return_pct": 1.69}


def test_exits_on_the_underlying_then_the_clock():
    calls = book.check_plan(plan_answer()["plan"], ["NBIS"], at(10, 40), CLOSE)
    def minute(m, lo, hi):
        return {"time": at(10, m), "end_time": at(10, m) + 60, "open": lo, "high": hi, "low": lo, "close": hi}
    bars = [minute(41, 117.8, 118.4), minute(42, 116.4, 121.2)]  # the second bar touches both: the invalidation
    found = book.exit_condition(calls, bars, at(10, 40, 10), CLOSE, at(10, 44))
    assert (found["reason"], found["reference"]) == ("invalidation", 116.5)
    assert book.exit_condition(calls, bars[:1], at(10, 40, 10), CLOSE, at(11, 30))["reason"] == "time_stop"
    calls["time_stop_at"] = CLOSE  # past the session's last minute
    assert book.exit_condition(calls, [], at(10, 40, 10), CLOSE, CLOSE - 30)["reason"] == "last_minute"


# ------------------------------------------------------------------ the worker


class Calendar:
    def hours(self, day):
        return {"date": day.isoformat(), "status": "open", "open": 570, "close": 960}


class Feed:
    def __init__(self):
        self.minutes = []

    def read(self, path, params, ttl):
        rows = [{"timestamp": t, "open": lo, "high": hi, "low": lo, "close": hi, "volume": 100} for t, lo, hi in self.minutes]
        return {"series": {"data": rows}}, 0, None


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Quotes:
    def __init__(self, clock):
        self.clock, self.next, self.asked = clock, (2.3, 2.4), []

    def __call__(self, symbol):
        self.asked.append(symbol)
        return None if self.next is None else quote(*self.next, int(self.clock()) + 1)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


STRONG = {**FIXTURE["measures"], "spy_relative_pct": 7.5}  # over the strong-event bar (7% vs SPY)
WEAK = {**FIXTURE["measures"], "spy_relative_pct": 2.1}


def radar_store(tmp_path, *events):
    """Events as (symbol, first seen) or (symbol, first seen, overrides); strong unless the overrides say otherwise."""
    store = RadarStore(tmp_path / "radar.sqlite")
    for i, (symbol, seen, *extra) in enumerate(events):
        store.append_event({**FIXTURE, "event_id": f"e{i}", "session_date": DAY.isoformat(), "symbols": [symbol],
                            "first_seen_at": stamp(seen), "summary": f"{symbol} up 3.1% vs SPY", "measures": STRONG,
                            **(extra[0] if extra else {})})
    return str(tmp_path / "radar.sqlite")


def shadow(engine, store, now, answers, turns=12):
    clock = Clock(now)
    seen = []

    async def decide(event, state, moment):
        seen.append((event, state))
        return answers.pop(0)
    worker = book.ShadowBook(engine, store, Feed(), Calendar(), clock=clock, decide=decide, turns=turns)
    worker.quote = Quotes(clock)
    return worker, clock, seen


def decisions(engine):
    with Session(engine) as db:
        rows = db.exec(select(ShadowBookDecision).order_by(ShadowBookDecision.claimed_at)).all()
        return [(r, book.fold(book.ShadowBook._events(db, r.id))) for r in rows]


def test_a_radar_event_becomes_one_decision_entered_and_exited_on_paper(engine, tmp_path):
    store = radar_store(tmp_path, ("NBIS", at(10, 38)))
    worker, clock, seen = shadow(engine, store, at(10, 40), [{"answer": plan_answer(), "model": "claude-sonnet-5-5"}])
    row = worker.claim_next()
    assert row.status == "deciding" and row.radar_event_id == "e0"
    asyncio.run(worker.decide_one(row))
    event, state = seen[0]
    assert event["summary"] == "NBIS up 3.1% vs SPY" and state["open_positions"] == [] and state["turn_cap"] == 12
    [(row, state)] = decisions(engine)
    assert row.status == "plan" and row.model == "claude-sonnet-5-5" and book.position_status(row, state) == "open"
    assert state["entry"]["price"] == 2.4 and worker.quote.asked == ["NBIS261024C00120000"]
    assert worker.claim_next() is None  # one decision per event

    # The target trades two minutes later; the exit is the next fresh bid.
    worker.feed.minutes = [(at(10, 41), 117.9, 118.5), (at(10, 42), 118.4, 121.3)]
    clock.now = at(10, 43, 40)
    worker.quote.next = (3.0, 3.1)
    worker.manage()
    [(row, state)] = decisions(engine)
    assert book.position_status(row, state) == "exit" and state["exit"]["reason"] == "target"
    assert state["exit"]["pnl"] == pytest.approx(58.7)
    worker.manage()  # nothing more to do; no fact is stored twice
    with Session(engine) as db:
        assert len(db.exec(select(ShadowBookEvent)).all()) == 3


def test_skip_stale_cap_and_late_events_are_recorded_without_extra_turns(engine, tmp_path):
    store = radar_store(tmp_path, ("AAA", at(10, 10)), ("BBB", at(10, 39)), ("CCC", at(10, 39, 30)))
    worker, clock, _ = shadow(engine, store, at(10, 40), [{"answer": {"decision": "skip", "reason": "Already extended."}}], turns=1)
    row = worker.claim_next()  # AAA is 30 minutes old: recorded, not decided; BBB is claimed
    asyncio.run(worker.decide_one(row))
    assert worker.claim_next() is None  # CCC is over the one-turn cap
    got = {r.radar_event_id: (r.status, r.reason) for r, _ in decisions(engine)}
    assert got["e0"][0] == "not_decided" and "30 minutes" in got["e0"][1]
    assert got["e1"] == ("skip", "Already extended.")
    assert got["e2"] == ("not_decided", "This session's 1 turns were used.")
    worker.clock.now = at(17, 0)
    assert worker.claim_next() is None  # quiet outside the session


def test_eligible_is_the_radar_strong_bar_or_a_dip():
    assert book.eligible({**FIXTURE, "measures": STRONG}) == (True, "")
    assert book.eligible({**FIXTURE, "symbols": ["NBIS"], "measures": WEAK}) == (False, "Below the strong-event bar: NBIS +2.1% vs SPY")
    assert book.eligible({"kind": "dip_turn", "symbols": ["AMD"], "measures": {"day_change_pct": -1.2}}) == (True, "")
    assert book.eligible({"kind": "gap_reversal", "symbols": ["AMD"], "measures": {"relative_pct": 1.9}}) == (True, "")
    group = {"kind": "group_move", "group": "Semis", "measures": {"median_relative_pct": 3.4, "members_with_data": 6,
                                                                  "members_same_direction": 5}}
    assert book.eligible(group) == (False, "Below the strong-event bar: Semis +3.4% vs SPY (5 of 6 the same way)")
    assert book.eligible({**group, "measures": {**group["measures"], "members_same_direction": 6}}) == (True, "")


def test_a_weak_event_is_filtered_without_a_turn_and_the_cap_counts_eligible_events_only(engine, tmp_path):
    dip = {"kind": "dip_turn", "rule_version": "radar-dip-v0", "measures": {"day_change_pct": -1.2, "low_change_pct": -2.4}}
    store = radar_store(tmp_path, ("NBIS", at(10, 38), {"measures": WEAK}), ("CRWV", at(10, 38, 30)),
                        ("APLD", at(10, 39), {"measures": WEAK}), ("AMD", at(10, 39, 10), dip), ("LAD", at(10, 39, 20)))
    worker, _, seen = shadow(engine, store, at(10, 40), [{"answer": {"decision": "skip", "reason": "Extended."}}] * 2, turns=2)
    strong = worker.claim_next()  # NBIS is below the bar: recorded on the way, no turn
    assert (strong.radar_event_id, strong.status) == ("e1", "deciding")
    asyncio.run(worker.decide_one(strong))
    dip_row = worker.claim_next()  # APLD filtered on the way; the dip claims the second turn
    assert (dip_row.radar_event_id, dip_row.status) == ("e3", "deciding")
    asyncio.run(worker.decide_one(dip_row))
    assert worker.claim_next() is None and len(seen) == 2
    got = {r.radar_event_id: (r.status, r.reason) for r, _ in decisions(engine)}
    assert got["e0"] == ("filtered", "Below the strong-event bar: NBIS +2.1% vs SPY")
    assert got["e2"] == ("filtered", "Below the strong-event bar: APLD +2.1% vs SPY")
    assert got["e1"][0] == got["e3"][0] == "skip"
    assert got["e4"] == ("not_decided", "This session's 2 turns were used.")  # two filtered events never used the cap
    assert worker.book(DAY)["turns_today"] == 2


def test_no_new_position_in_the_last_half_hour(engine, tmp_path):
    store = radar_store(tmp_path, ("NBIS", at(15, 44)))
    worker, _, _ = shadow(engine, store, at(15, 45), [])
    assert worker.claim_next() is None
    [(row, _)] = decisions(engine)
    assert (row.status, row.reason) == ("not_decided", "In the session's last half hour: no new positions.")


def test_a_refused_plan_or_failed_turn_is_an_error_never_a_position(engine, tmp_path):
    store = radar_store(tmp_path, ("NBIS", at(10, 39)), ("CRWV", at(10, 39, 20)))
    worker, clock, _ = shadow(engine, store, at(10, 40), [{"answer": plan_answer(target=110.0)},
                                                          {"error": {"code": "plan_limit", "message": "Plan limit reached."}}])
    asyncio.run(worker.decide_one(worker.claim_next()))
    asyncio.run(worker.decide_one(worker.claim_next()))
    got = [(r.status, r.reason) for r, s in decisions(engine)]
    assert got[0][0] == "error" and "target must be above" in got[0][1] and got[1] == ("error", "Plan limit reached.")
    with Session(engine) as db:
        assert db.exec(select(ShadowBookEvent)).all() == []


def test_a_restart_rebuilds_the_book_and_never_decides_twice(engine, tmp_path):
    store = radar_store(tmp_path, ("NBIS", at(10, 38)), ("CRWV", at(10, 39)))
    worker, clock, _ = shadow(engine, store, at(10, 40), [{"answer": plan_answer()}])
    asyncio.run(worker.decide_one(worker.claim_next()))
    cut_off = worker.claim_next()  # CRWV's turn is running when the process stops
    assert cut_off.status == "deciding"

    again, clock2, _ = shadow(engine, store, at(10, 42), [])
    assert again.recover() == 1 and again.claim_next() is None
    [(nbis, state), (crwv, _)] = decisions(engine)
    assert (crwv.status, crwv.reason) == ("error", "Interrupted by a restart; never retried.")
    assert book.position_status(nbis, state) == "open"  # rebuilt from the stored entry
    # The next session: the position still open is unresolved, never carried.
    clock2.now = at(9, 31, day=date(2026, 10, 23))
    again.manage()
    [(nbis, state), _] = decisions(engine)
    assert state["unresolved"]["reason"] == "session ended before the position finished"


def test_no_entry_quote_within_two_minutes_is_unresolved(engine, tmp_path):
    store = radar_store(tmp_path, ("NBIS", at(10, 39)))
    worker, clock, _ = shadow(engine, store, at(10, 40), [{"answer": plan_answer()}])
    worker.quote.next = None
    asyncio.run(worker.decide_one(worker.claim_next()))
    clock.now = at(10, 42, 30)
    worker.manage()
    [(row, state)] = decisions(engine)
    assert book.position_status(row, state) == "unresolved" and state["unresolved"]["reason"] == "no entry quote within two minutes"


# ------------------------------------------------------------------ the record


def test_the_week_route_lists_each_decision_and_a_side_by_side_summary(engine, tmp_path, monkeypatch):
    store = radar_store(tmp_path, ("NBIS", at(10, 38)), ("APLD", at(10, 38, 30), {"measures": WEAK}), ("CRWV", at(10, 39)))
    worker, clock, _ = shadow(engine, store, at(10, 40), [{"answer": plan_answer()}, {"answer": {"decision": "skip", "reason": "Wide spread."}}])
    asyncio.run(worker.decide_one(worker.claim_next()))
    worker.feed.minutes = [(at(10, 41), 118.4, 121.3)]
    clock.now, worker.quote.next = at(10, 42, 40), (3.0, 3.1)
    worker.manage()
    asyncio.run(worker.decide_one(worker.claim_next()))
    from app.ai import copilot_review
    monkeypatch.setattr(copilot_review, "week_review", lambda week_start, session=None: {"state": "ok", "totals": {"trades": 4, "pnl_usd": -80.0}})

    app = FastAPI()
    app.include_router(radar_routes.router, prefix="/radar")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    out = TestClient(app).get("/radar/shadow-book", params={"week": DAY.isoformat()}).json()
    assert out["week"] == {"start": "2026-10-19", "end": "2026-10-23"} and out["enabled"] is False
    assert out["summary"]["shadow"] == {"decisions": 3, "turns": 2, "filtered": 1, "plans": 1, "closed": 1, "pnl_usd": 58.7}
    assert out["summary"]["owner"] == {"state": "ok", "trades": 4, "pnl_usd": -80.0} and "not compared" in out["summary"]["note"]
    skip, plan = [d for d in out["decisions"] if d["decision"] != "filtered"]  # newest first
    [filtered] = [d for d in out["decisions"] if d["decision"] == "filtered"]  # claimed in NBIS's pass
    assert (filtered["reason"], filtered["plan"]) == ("Below the strong-event bar: APLD +2.1% vs SPY", None)
    assert (skip["decision"], skip["reason"], skip["plan"]) == ("skip", "Wide spread.", None)
    assert plan["event"]["summary"] == "NBIS up 3.1% vs SPY" and plan["plan"]["contract"] == "2026-10-24 120 call"
    assert plan["entry"]["price"] == 2.4 and plan["exit"] == {"price": 3.0, "at": plan["exit"]["at"], "reason": "target"}
    assert plan["result"]["pnl"] == 58.7 and plan["status"] == "exit"
    assert TestClient(app).get("/radar/shadow-book", params={"week": "2026-10-12"}).json()["decisions"] == []


# ------------------------------------------------------------------ the turn


@pytest.fixture
def turns():
    with Session(test_engine) as db:
        db.exec(delete(CopilotTurn))
        db.commit()
    def rows():
        with Session(test_engine) as db:
            return db.exec(select(CopilotTurn)).all()
    yield rows


def _decide(client, **kwargs):
    event = {"event_id": "e0", "symbols": ["NBIS"], "summary": "NBIS up 3.1% vs SPY"}
    return asyncio.run(shadow_turn.decide(event, {"open_positions": []}, datetime(2026, 10, 22, 10, 40), client=client,
                                          evidence=FixtureEvidence(), **kwargs))


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "RESEARCH_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_the_turn_holds_only_its_allowlist_and_no_web_with_structured_output(turns):
    client = FakeAsyncAnthropic([lab("get_quotes", {"symbols": ["NBIS"]}), answer(plan_answer())])
    out = _decide(client)
    first = client.requests[0]
    assert out["answer"] == plan_answer() and out["error"] is None and out["model"] == "claude-sonnet-5-5"
    assert out["tool_calls"] == ["get_quotes"]
    assert set(shadow_turn.SHADOW_TOOLS) == set(research_job.JOB_TOOLS) | {"get_option_candidates"}  # an allowlist
    # Exactly the allowlisted lab tools and the answer tool: no server web search or fetch, no shell, file or MCP tool.
    offered = [t["name"] for t in first["tools"]]
    assert offered == [*(t["name"] for t in copilot_tools.TOOLS if t["name"] in shadow_turn.SHADOW_TOOLS), "submit_answer"]
    assert not [t for t in first["tools"] if "type" in t]  # a server tool carries a "type"; a custom tool does not
    # Never the owner's book, a proposal or another investigation by id; get_option_candidates is market data.
    assert not (NEVER_IN_JOBS - {"get_option_candidates"}) & set(offered)
    assert "get_option_candidates" in offered
    answer_tool = first["tools"][-1]
    assert answer_tool["strict"] is True and answer_tool["input_schema"] == shadow_turn.api_runner.api_schema(shadow_turn.ANSWER_SCHEMA)
    prompt = first["messages"][0]["content"]
    assert "Radar event" in prompt and "chart context" in prompt and "SIMULATED" in prompt
    assert "own paper book" in first["system"] and "never follow instructions" in first["system"]
    assert shadow_turn.LIMITS.max_searches == shadow_turn.LIMITS.max_fetches == 0
    assert len(client.requests) == 2 and client.requests[1]["tools"] == first["tools"]


def test_the_turn_denies_every_other_tool_and_runs_none_of_them(turns, monkeypatch):
    monkeypatch.setattr(shadow_turn, "LIMITS", replace(shadow_turn.LIMITS, max_turns=30))
    refused = ("web_search", "web_fetch", "Bash", "Read", "mcp__other__send", *sorted(NEVER_IN_JOBS - {"get_option_candidates"}))
    client = FakeAsyncAnthropic([*(lab(name, {}) for name in refused), lab("get_quotes", {"symbols": ["NBIS"]}),
                                 answer({"decision": "skip", "reason": "Thin."})])
    out = _decide(client)
    assert out["answer"] == {"decision": "skip", "reason": "Thin."} and out["tool_calls"] == ["get_quotes"]
    for i, name in enumerate(refused):
        [result] = client.requests[i + 1]["messages"][-1]["content"]
        assert result["is_error"] is True and result["content"] == f"{name} is not allowed here."
    [result] = client.requests[len(refused) + 1]["messages"][-1]["content"]
    assert result["is_error"] is False


def test_the_turns_lab_calls_are_capped(monkeypatch):
    monkeypatch.setattr(shadow_turn, "LIMITS", replace(shadow_turn.LIMITS, max_turns=30))
    n = shadow_turn.LIMITS.max_lab_calls
    client = FakeAsyncAnthropic([*(lab("get_quotes", {"symbols": ["NBIS"]}) for _ in range(n + 1)),
                                 answer({"decision": "skip", "reason": "x"})])
    out = _decide(client)
    assert len(out["tool_calls"]) == n
    [result] = client.requests[n + 1]["messages"][-1]["content"]
    assert result["is_error"] is True and "Tool-call budget" in result["content"]


def test_the_turn_is_billed_in_the_background_and_does_not_count_toward_the_desk_budget(turns):
    before = copilot_spend.spent_today()
    out = _decide(FakeAsyncAnthropic([message(text("looking"), tool_use("get_quotes", {"symbols": ["NBIS"]}), stop_reason="tool_use"),
                                      answer(plan_answer(), input_tokens=50_000, output_tokens=0)]))
    assert out["metrics"]["backend"] == "shadow" and out["metrics"]["rounds"] == 2 and out["metrics"]["cost_usd"] == 0.103
    [row] = turns()
    assert (row.backend, row.billing, row.symbol, row.rounds) == ("shadow", "api_background", "NBIS", 2)
    assert row.model == "claude-sonnet-5-5" and float(row.cost_usd) == 0.103 and row.input_tokens == 51_000
    assert copilot_spend.spent_today() == before  # the desk's daily budget only counts billing == "api"


@pytest.mark.parametrize("rounds,code", [
    ([api_error(anthropic.RateLimitError, 429)], "api_rate_limit"),
    ([message(text("no"), stop_reason="refusal")], "refusal"),
    ([message(text("a")), message(text("b"))], "no_answer"),
    ([RuntimeError("boom")], "api"),
    ([Sleep(5), answer(plan_answer())], "timeout"),
])
def test_a_failed_turn_is_recorded_on_the_decision_and_logged_never_raised(turns, monkeypatch, rounds, code):
    monkeypatch.setattr(shadow_turn, "LIMITS", replace(shadow_turn.LIMITS, timeout_s=0.1))
    out = _decide(FakeAsyncAnthropic(rounds))
    assert out["answer"] is None and out["error"]["code"] == code and "boom" not in out["error"]["message"]
    [row] = turns()  # a failed turn is still logged, apart from the desk budget
    assert (row.backend, row.billing) == ("shadow", "api_background")


def test_the_turn_cap_and_the_budget_stop_a_shadow_turn(turns, monkeypatch):
    monkeypatch.setattr(shadow_turn, "LIMITS", replace(shadow_turn.LIMITS, max_turns=2))
    out = _decide(FakeAsyncAnthropic([lab("get_quotes", {"symbols": ["NBIS"]}), lab("get_quotes", {"symbols": ["NBIS"]}),
                                      answer(plan_answer())]))
    assert out["answer"] is None and out["error"]["code"] == "error_max_turns"
    monkeypatch.setattr(shadow_turn, "LIMITS", replace(shadow_turn.LIMITS, max_turns=10, budget_usd=0.05))
    out = _decide(FakeAsyncAnthropic([lab("get_quotes", {"symbols": ["NBIS"]}, input_tokens=100_000), answer(plan_answer())]))
    assert out["error"]["code"] == "error_max_budget_usd" and out["answer"] is None


def test_without_a_key_or_a_client_the_turn_is_refused_and_logs_nothing(turns, monkeypatch):
    def boom(**kwargs):
        raise AssertionError("no client without a key")
    monkeypatch.setattr(shadow_turn.api_runner.anthropic, "AsyncAnthropic", boom)
    event = {"event_id": "e0", "symbols": ["NBIS"], "summary": "x"}
    out = asyncio.run(shadow_turn.decide(event, {}, datetime(2026, 10, 22, 10, 40), evidence=FixtureEvidence()))
    assert out["answer"] is None and out["error"]["code"] == "api_not_configured" and out["model"] is None and turns() == []


def test_a_failed_save_is_an_error_not_a_stuck_decision(engine, tmp_path, monkeypatch):
    store = radar_store(tmp_path, ("NBIS", at(10, 39)))
    worker, _, _ = shadow(engine, store, at(10, 40), [{"answer": plan_answer()}])

    def broken(decision_id, answer):
        raise RuntimeError("database went away")
    monkeypatch.setattr(worker, "record_answer", broken)
    asyncio.run(worker.decide_one(worker.claim_next()))
    [(row, _)] = decisions(engine)
    assert (row.status, row.reason) == ("error", "The answer could not be saved.")


def test_an_unavailable_calendar_waits_instead_of_closing_a_position(engine, tmp_path):
    store = radar_store(tmp_path, ("NBIS", at(10, 39)))
    worker, clock, _ = shadow(engine, store, at(10, 40), [{"answer": plan_answer()}])
    asyncio.run(worker.decide_one(worker.claim_next()))
    worker.calendar = SimpleNamespace(hours=lambda day: None)
    clock.now = at(10, 50)
    worker.manage()
    [(row, state)] = decisions(engine)
    assert book.position_status(row, state) == "open"
