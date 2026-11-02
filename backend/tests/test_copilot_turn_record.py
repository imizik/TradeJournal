"""One ``copilot_turn`` row per model turn, with what it was for and how it went (docs/copilot-lab.md § What every turn
records), and the saved conversation linking itself to its turns. Offline: the scripted model and a stubbed client."""
import asyncio
import json
import time
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.ai import copilot, copilot_spend
from app.ai.copilot_fixture import FixtureEvidence
from app.database import engine
from app.main import app
from app.models import CopilotInvestigation, CopilotTurn
from tests.test_copilot import NOW, _cfg, _frames


@pytest.fixture(autouse=True)
def clean():
    with Session(engine) as db:
        db.exec(delete(CopilotTurn))
        db.exec(delete(CopilotInvestigation))
        db.commit()
    yield


def _rows() -> list[CopilotTurn]:
    with Session(engine) as db:
        return db.exec(select(CopilotTurn).order_by(CopilotTurn.started_at)).all()


def _rows_once_written(count: int, timeout: float = 5.0) -> list[CopilotTurn]:
    """A turn served by the live app writes its row on the default executor after the stream ends; wait for it."""
    deadline = time.monotonic() + timeout
    while len(rows := _rows()) < count and time.monotonic() < deadline:
        time.sleep(0.02)
    return rows


def _collect(gen):
    async def go():
        return [e async for e in gen]
    return asyncio.run(go())


def test_a_desk_turn_writes_one_row_with_its_kind_tools_and_timings_and_the_done_event_names_it():
    turn = copilot_spend.recorded_turn([{"role": "user", "content": "Is NBIS lagging its group?"}], "NBIS", _cfg(), copilot.FakeAdapter(0),
                                       FixtureEvidence(), NOW, kind=None, source="desk")
    events = _collect(turn)
    done = next(e for e in events if e["type"] == "done")
    [row] = _rows()
    assert str(row.id) == done["turn_id"] and row.kind == "ask" and row.source == "desk" and row.symbol == "NBIS"
    names = json.loads(row.tool_names)
    assert names and "owner_context" not in names and "get_group_comparison" in names
    assert row.first_text_ms is not None and row.max_silence_ms is not None and row.cache_creation_input_tokens == 0
    assert row.effort == "medium" and row.evidence == "fixture" and row.error is None and row.billing == "none"


@pytest.mark.parametrize("question,expected", [
    ("Review my week", "week_review"),
    ("Review this position: 00000000-0000-4000-8000-0000000000a1", "review"),
    ("Explain this candle: NBIS 5m at 10:40 ET", "moment"),
    ("Plan a trade: NBIS calls into the close", "plan"),
    ('Push back on "the group is confirming": CRWV is doing all of it', "pushback"),
    ("Which is better, the 10/30 calls or the 11/6 calls?", "compare"),
    ("What matters right now across my open positions, armed watches and open investigations? Say so.", "briefing"),
])
def test_the_kind_follows_the_question_the_tools_and_the_cards(question, expected):
    _collect(copilot_spend.recorded_turn([{"role": "user", "content": question}], "NBIS", _cfg(), copilot.FakeAdapter(0),
                                         FixtureEvidence(), NOW, kind=None, source="desk"))
    assert [r.kind for r in _rows()] == [expected]


def test_kind_of_is_a_fixed_order():
    assert copilot_spend.kind_of("Push back on x", ["get_week_review"], [], "") == "pushback"
    assert copilot_spend.kind_of("x", ["get_trade_review", "get_moment"], ["trade_plan"], "") == "review"
    assert copilot_spend.kind_of("x", ["get_investigation_changes"], [], "") == "changes"
    assert copilot_spend.kind_of("x", [], ["trade_plan"], "Compare: a | b") == "plan"
    assert copilot_spend.kind_of("x", [], ["watch"], "Verdict: Unclear — H.\n\nCompare: a | b\nNeeds: x | y") == "compare"
    assert copilot_spend.kind_of("anything else", ["get_quotes"], [], "") == "ask"


def test_a_stopped_turn_is_recorded_with_its_cost_so_far():
    cfg = _cfg(backend="anthropic", key_configured=True)

    class Priced:
        model = "claude-sonnet-5-5"

        async def stream_round(self, system, messages, tools, allow_tools=True):
            yield "text", "Verdict: Hold — "
            yield "final", copilot.Round([{"type": "text", "text": "Verdict: Hold — H."}], "end_turn",
                                         {"input_tokens": 10_000, "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, self.model)

    async def stop_early():
        turn = copilot_spend.recorded_turn([{"role": "user", "content": "x"}], "NBIS", cfg, Priced(), FixtureEvidence(), NOW, kind=None, source="charts")
        async for event in turn:
            if event["type"] == "text":
                break
        await turn.aclose()
        await asyncio.sleep(0.05)  # the row goes to the default executor

    asyncio.run(stop_early())
    [row] = _rows()
    assert row.error == "stopped" and row.source == "charts" and row.billing == "api"
    assert row.rounds == 0 and row.cost_usd == 0  # stopped before the first round's usage landed; later rounds would be kept


def test_a_turn_that_ends_in_an_error_records_its_code():
    class Failing:
        model = "claude-sonnet-5-5"

        async def stream_round(self, system, messages, tools, allow_tools=True):
            raise copilot.CopilotError("api_rate_limit", "slow")
            yield  # pragma: no cover

    events = _collect(copilot_spend.recorded_turn([{"role": "user", "content": "x"}], None, _cfg(backend="anthropic", key_configured=True),
                                                  Failing(), FixtureEvidence(), NOW, kind=None, source="telegram"))
    assert [e["type"] for e in events][-2:] == ["error", "done"]
    [row] = _rows()
    assert row.error == "api_rate_limit" and row.source == "telegram" and row.symbol is None


def test_the_chat_route_records_source_and_investigation_and_refuses_past_the_cap_with_a_row(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.delenv("COPILOT_BACKEND", raising=False)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    investigation = str(uuid.uuid4())
    with TestClient(app) as client:
        body = {"messages": [{"role": "user", "content": "Is NBIS lagging?"}], "symbol": "NBIS", "source": "radar", "investigation_id": investigation}
        frames = _frames(client.post("/copilot/chat", json=body).text)
        done = next(f for f in frames if f["type"] == "done")
        [row] = _rows_once_written(1)
        assert str(row.id) == done["turn_id"] and row.source == "radar" and str(row.investigation_id) == investigation
        assert client.post("/copilot/chat", json={**body, "source": "phone"}).status_code == 422
        assert client.post("/copilot/chat", json={**body, "investigation_id": "not-a-uuid"}).status_code == 422
        # Past the daily API budget: refused, and the refusal is a zero-cost row that never counts toward the budget.
        monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 99.0)
        assert client.post("/copilot/chat", json=body).status_code == 429
    refused = _rows()[-1]
    assert refused.error == "daily_budget" and refused.cost_usd == 0 and refused.kind == "ask" and refused.source == "radar" and refused.rounds == 0


def test_saving_a_conversation_links_its_turns_once(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    first = copilot_spend.record({"backend": "fake", "usage": {}, "cost_usd": 0, "rounds": 1}, "NBIS", kind="ask", source="desk")
    second = copilot_spend.record({"backend": "fake", "usage": {}, "cost_usd": 0, "rounds": 1}, "NBIS", kind="ask", source="desk")
    transcript = [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A", "metrics": {"model": "fake", "turn_id": str(first)}},
                  {"role": "user", "content": "Q2"}, {"role": "assistant", "content": "A2", "metrics": {"turn_id": str(second)}}]
    with TestClient(app) as client:
        made = client.post("/copilot/investigations", json={"title": "Linked", "transcript": transcript})
        assert made.status_code == 201 and made.json()["transcript"][1]["metrics"]["turn_id"] == str(first)
        saved = made.json()
        other = client.post("/copilot/investigations", json={"title": "Thief", "transcript": transcript})
        assert other.status_code == 201
        # An unknown turn id is fine (the row may be a stopped turn still being written); a malformed one is refused.
        ok = client.put(f"/copilot/investigations/{saved['id']}", json={"title": "Linked", "revision": 1, "transcript": [
            *transcript, {"role": "user", "content": "Q3"}, {"role": "assistant", "content": "A3", "metrics": {"turn_id": str(uuid.uuid4())}}]})
        assert ok.status_code == 200
        bad = client.post("/copilot/investigations", json={"title": "Bad", "transcript": [{"role": "assistant", "content": "A", "metrics": {"turn_id": "nope"}}]})
        assert bad.status_code == 422
    with Session(engine) as db:
        linked = {str(r.id): str(r.investigation_id) for r in db.exec(select(CopilotTurn)).all()}
    assert linked == {str(first): saved["id"], str(second): saved["id"]}  # the second investigation took nothing over


def test_record_keeps_its_old_shape_and_the_refusal_helper_writes_zero_cost():
    assert copilot_spend.record({"backend": "fake", "usage": {}, "cost_usd": 0.0}, "SPY") is not None
    copilot_spend.record_refused(kind="prep", source="prep", backend="anthropic", code="daily_budget")
    rows = _rows()
    assert [r.kind for r in rows] == [None, "prep"] and rows[1].error == "daily_budget" and rows[1].cost_usd == 0 and rows[1].billing == "api"
    assert copilot_spend.spent_today() == 0


def test_the_scheduled_senders_name_their_kind(monkeypatch):
    """The morning brief and the week review record ``prep`` and ``week_review``; the brief alone is refused past the cap."""
    from app.engine import premarket_prep
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.delenv("COPILOT_BACKEND", raising=False)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    now = datetime(2026, 10, 26, 8, 30).timestamp()
    answer, error = premarket_prep._turn("Morning brief for 2026-10-26: NBIS 11/21 100C held.", now)
    assert error is None and answer
    events: list[dict] = []
    premarket_prep._turn("Review my week", now, events, kind="week_review")
    assert next(e for e in events if e["type"] == "done")["turn_id"]
    assert [r.kind for r in _rows()] == ["prep", "week_review"] and [r.source for r in _rows()] == ["prep", "week_review"]
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 99.0)
    answer, error = premarket_prep._turn("Morning brief", now)
    assert answer == "" and "budget" in error and _rows()[-1].error == "daily_budget" and _rows()[-1].kind == "prep"
