"""The answer scorecard (``app/engine/copilot_scorecard.py``, ``GET /copilot/answer-scorecard``): counts from seeded turns and
saved conversations, the window, the New York day, and the route's gates. Offline."""
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.database import engine
from app.engine import copilot_scorecard
from app.main import app
from app.models import CopilotInvestigation, CopilotTurn
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

NOW = datetime(2026, 10, 30, 20, 0)  # 16:00 New York, Friday, naive UTC like the rows


@pytest.fixture(autouse=True)
def clean():
    with Session(engine) as db:
        db.exec(delete(CopilotTurn))
        db.exec(delete(CopilotInvestigation))
        db.commit()
    yield


def turn(db, *, kind="ask", source="desk", cost=0.02, first=4000, total=6000, error=None, started=None, backend="anthropic",
         tools=("get_group_comparison",), billing="api", model="claude-opus-5-5", cache_read=0, inputs=1000) -> uuid.UUID:
    row = CopilotTurn(backend=backend, billing=billing, model=model, kind=kind, source=source, cost_usd=cost, first_text_ms=first,
                      total_ms=total, max_silence_ms=first, error=error, started_at=started or NOW - timedelta(hours=2),
                      tool_names=json.dumps(list(tools)), input_tokens=inputs, cache_read_input_tokens=cache_read, rounds=2)
    db.add(row)
    db.commit()
    return row.id


def conversation(db, title, messages, *, created=None, updated=None, source="copilot", symbol="NBIS") -> str:
    row = CopilotInvestigation(title=title, symbol=symbol, source=source, status="open", transcript_json=json.dumps(messages),
                               evidence_json="[]", created_at=created or NOW - timedelta(hours=3), updated_at=updated or NOW - timedelta(hours=1))
    db.add(row)
    db.commit()
    return str(row.id)


def answer(text, turn_id=None, rating=None, **metrics):
    out = {"role": "assistant", "content": text}
    if turn_id or metrics:
        out["metrics"] = {**({"turn_id": str(turn_id)} if turn_id else {}), **metrics}
    if rating:
        out["rating"] = rating
    return out


def test_counts_ratings_pushback_follow_ups_latency_and_cost_from_turns_and_saved_answers():
    with Session(engine) as db:
        t1, t2, t3 = turn(db, cost=0.02), turn(db, cost=0.03, first=5000), turn(db, kind="plan", source="charts", cost=0.05, tools=("get_chart_context", "get_quotes", "propose_plan"))
        t4 = turn(db, kind="prep", source="prep", cost=0.01, tools=())
        turn(db, error="stopped", cost=0.004, first=None, total=900)
        turn(db, error="daily_budget", cost=0.0, first=None, total=0, backend="anthropic")
        turn(db, backend="fake", billing="none", cost=0.0)  # a fake turn never counts
        turn(db, started=NOW - timedelta(days=9), cost=9.0)  # outside the window
        rated = conversation(db, "NBIS vs the group", [
            {"role": "user", "content": "Is NBIS lagging?"}, answer("Verdict: Wait — Not yet.", t1, "helped"),
            {"role": "user", "content": 'Push back on "Not yet.": CRWV is up 3%'}, answer("Verdict: Wait — Still.", t2, "didnt"),
            {"role": "user", "content": "ok thanks"}])
        conversation(db, "NBIS plan", [{"role": "user", "content": "Plan a trade: NBIS calls"}, answer("Verdict: Draft — Card below.", t3, "helped")])
        conversation(db, "Morning brief 2026-10-30", [{"role": "user", "content": "Morning brief"}, answer("Verdict: Focus — Expiries.", t4)])
        # An older answer with no turn id but inside the window counts under its title's kind; one outside does not.
        conversation(db, "Week review · Oct 20", [{"role": "user", "content": "Review my week"}, answer("Verdict: Pattern — W.", None, "helped", model="claude-sonnet-5-5")])
        conversation(db, "Old", [{"role": "user", "content": "q"}, answer("a", None, "helped")], created=NOW - timedelta(days=20), updated=NOW - timedelta(hours=1))
        conversation(db, "Radar: CRWV", [{"role": "user", "content": "job"}, answer("x", None, "helped")], source="research_job")
        card = copilot_scorecard.answer_scorecard(db, NOW, 7)
    assert card["state"] == "ok" and card["window"]["days"] == 7
    assert card["turns"]["total"] == 6 and card["turns"]["by_kind"] == {"ask": 4, "plan": 1, "prep": 1}
    a = card["answers"]
    assert (a["total"], a["rated"], a["helped"], a["didnt"]) == (5, 4, 3, 1) and a["helped_rate"] == 0.75
    assert a["pushback"] == 1 and a["follow_ups"] == 2 and a["failed"] == 0
    assert card["by_kind"]["ask"]["answers"] == 2 and card["by_kind"]["ask"]["helped_rate"] is None  # under 3 rated: null, not a number
    assert card["by_kind"]["plan"]["cost_usd"] == 0.05 and card["by_kind"]["week_review"]["answers"] == 1 and card["by_kind"]["prep"]["rated"] == 0
    assert card["by_source"]["charts"]["answers"] == 1 and card["by_model"]["claude-sonnet-5-5"]["answers"] == 1
    assert card["by_tools"]["2-3"]["answers"] == 1 and card["by_tools"]["none"]["answers"] == 2  # prep had none; the week review carried no tools
    assert card["top_tool_mixes"][0]["tools"] in ("get_group_comparison", "none")
    assert card["latency"]["ask"]["first_text_ms"] == {"p50": 4000, "p90": 5000} and card["latency"]["ask"]["turns"] == 2
    assert card["failed"] == {"daily_budget": 1, "stopped": 1}
    assert card["cost"]["total_usd"] == 0.114 and card["cost"]["top_threads"][0]["investigation_id"] == rated and card["cost"]["top_threads"][0]["usd"] == 0.05
    assert sum(d["usd"] for d in card["spend_by_day"]) == pytest.approx(0.114) and all(d["billing"] in ("api", "none") for d in card["spend_by_day"])


def test_a_late_evening_turn_lands_on_its_new_york_day_and_the_window_moves():
    with Session(engine) as db:
        turn(db, started=datetime(2026, 10, 30, 3, 30), cost=0.01)  # 23:30 New York on Oct 29
        card = copilot_scorecard.answer_scorecard(db, NOW, 7)
        assert [d["day"] for d in card["spend_by_day"]] == ["2026-10-29"]
        assert copilot_scorecard.answer_scorecard(db, NOW + timedelta(days=8), 7)["turns"]["total"] == 0


def test_a_failing_part_is_marked_unavailable_and_the_rest_stands(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no")
    monkeypatch.setattr(copilot_scorecard, "_answers", boom)
    with Session(engine) as db:
        turn(db)
        card = copilot_scorecard.answer_scorecard(db, NOW, 7)
    assert card["answers"] == {"state": "unavailable"} and card["turns"]["total"] == 1 and card["failed"] == {}


def test_the_route_is_owner_only_gated_and_bounded(boundary):  # noqa: F811
    boundary.patch.delenv("COPILOT_ENABLED", raising=False)
    assert boundary.owner.get("/copilot/answer-scorecard").status_code == 503
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    assert boundary.owner.get("/copilot/answer-scorecard?days=7").status_code == 200
    assert boundary.owner.get("/copilot/answer-scorecard?days=0").status_code == 422
    assert boundary.owner.get("/copilot/answer-scorecard?days=91").status_code == 422
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/answer-scorecard").status_code == 403


def test_the_route_reads_real_rows(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    recent = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)  # the route reads the real clock
    with Session(engine) as db:
        t = turn(db, started=recent)
        conversation(db, "T", [{"role": "user", "content": "q"}, answer("Verdict: Hold — H.", t, "helped")], created=recent, updated=recent)
    with TestClient(app) as client:
        body = client.get("/copilot/answer-scorecard?days=30").json()
    assert body["answers"]["helped"] == 1 and body["turns"]["total"] == 1 and body["window"]["days"] == 30
    assert "Verdict" not in json.dumps(body) and "since" in body["window"] and "until" in body["window"]  # counts only, no answer text
