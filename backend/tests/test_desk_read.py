"""The desk read (docs/copilot-lab.md § The desk read, ``app/engine/desk_read.py``): one small recorded turn per ticker,
kept for 30 minutes in the session (longer outside it), refreshed on a tap or once it expires, refused when the day's
budget has no room for it, never for a ticker he does not follow, and counted in the desk's timings view. Offline: the
scripted model, or a recording adapter with a priced usage; nothing reaches Anthropic."""
import asyncio
import time
import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.ai import copilot, copilot_answer, copilot_prompt, copilot_spend
from app.database import engine
from app.engine import day_journal, desk_read
from app.engine.chart_math import ET
from app.main import app
from app.models import CopilotTurn, DayJournalEntry

# Friday 2026-11-13: 11:00 New York (in the session), 08:00 (before the open), 18:00 (after the close).
IN_SESSION = datetime(2026, 11, 13, 11, 0, tzinfo=ET).timestamp()
PRE_OPEN = datetime(2026, 11, 13, 8, 0, tzinfo=ET).timestamp()
EVENING = datetime(2026, 11, 13, 18, 0, tzinfo=ET).timestamp()


@pytest.fixture(autouse=True)
def lab(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    monkeypatch.setattr(desk_read, "expires_at", _clock_hours_expiry)
    with Session(engine) as db:
        db.exec(delete(CopilotTurn))
        db.exec(delete(DayJournalEntry))
        db.commit()
    desk_read.clear()
    yield
    desk_read.clear()


_real_expires_at = desk_read.expires_at


def _clock_hours_expiry(now: float) -> float:
    """``expires_at`` on the clock hours (no market calendar read in a test)."""
    from app.engine import chart_calendar as calendar_module

    class NoCalendar:
        @staticmethod
        def hours(day):
            raise RuntimeError("no calendar in tests")
    saved = calendar_module.chart_calendar
    calendar_module.chart_calendar = NoCalendar()
    try:
        return _real_expires_at(now)
    finally:
        calendar_module.chart_calendar = saved


@pytest.fixture
def turns(monkeypatch):
    """Every model turn the reads start: the settings each ran with."""
    started: list = []
    real = copilot_spend.recorded_turn

    def counted(history, symbol, cfg, *args, **kwargs):
        started.append({"symbol": symbol, "cfg": cfg, "question": history[-1]["content"], **kwargs})
        return real(history, symbol, cfg, *args, **kwargs)
    monkeypatch.setattr(copilot_spend, "recorded_turn", counted)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    return started


def _rows(count: int | None = None, timeout: float = 5.0) -> list[CopilotTurn]:
    deadline = time.monotonic() + timeout
    while True:
        with Session(engine) as db:
            rows = db.exec(select(CopilotTurn).order_by(CopilotTurn.started_at)).all()
        if count is None or len(rows) >= count or time.monotonic() > deadline:
            return rows
        time.sleep(0.02)


def _read(symbol="NBIS", **kwargs):
    return asyncio.run(desk_read.read(symbol, **kwargs))


def _hide(symbol: str):
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id=str(uuid.uuid4()), day=date(2026, 11, 13), kind="follow", text="Not following", symbol=symbol))
        db.commit()


# --------------------------------------------------------------------------- how long a read is kept

def test_a_read_is_kept_30_minutes_in_the_session_two_hours_outside_and_never_past_the_open():
    assert desk_read.expires_at(IN_SESSION) == IN_SESSION + 30 * 60
    assert desk_read.expires_at(EVENING) == EVENING + 2 * 60 * 60
    # 08:00: two hours would reach 10:00, so the read stops at the 09:30 open.
    assert desk_read.expires_at(PRE_OPEN) == datetime(2026, 11, 13, 9, 30, tzinfo=ET).timestamp()
    saturday = datetime(2026, 11, 14, 11, 0, tzinfo=ET).timestamp()
    assert desk_read.expires_at(saturday) == saturday + 2 * 60 * 60


# --------------------------------------------------------------------------- the cache

def test_one_read_runs_once_and_a_reselect_inside_the_window_shows_it_with_its_age_and_no_new_call(turns):
    first = _read(now=IN_SESSION)
    assert first["state"] == "ok" and first["cached"] is False and first["age_s"] == 0
    assert first["text"].startswith("Verdict: ") and "Changes if:" in first["text"]
    assert len(turns) == 1
    again = _read(now=IN_SESSION + 10 * 60)
    assert again["state"] == "ok" and again["cached"] is True and again["age_s"] == 600 and again["text"] == first["text"]
    assert len(turns) == 1  # no model call
    other = _read("CRWV", now=IN_SESSION + 10 * 60)
    assert other["cached"] is False and len(turns) == 2  # kept per ticker


def test_an_expired_read_and_a_refresh_each_read_again(turns):
    _read(now=IN_SESSION)
    expired = _read(now=IN_SESSION + 30 * 60 + 1)
    assert expired["cached"] is False and expired["age_s"] == 0 and len(turns) == 2
    refreshed = _read(now=IN_SESSION + 31 * 60, refresh=True)
    assert refreshed["cached"] is False and len(turns) == 3
    # The refreshed read is the one kept from then on.
    assert _read(now=IN_SESSION + 40 * 60)["age_s"] == 9 * 60 and len(turns) == 3


def test_two_reads_of_one_ticker_at_once_make_one_call(turns):
    async def both():
        return await asyncio.gather(desk_read.read("NBIS", now=IN_SESSION), desk_read.read("NBIS", now=IN_SESSION))
    first, second = asyncio.run(both())
    assert len(turns) == 1 and first["text"] == second["text"] and {first["cached"], second["cached"]} == {False, True}


def test_a_failed_read_is_not_kept(turns, monkeypatch):
    class Failing:
        model = "fake-scripted"

        async def stream_round(self, *args, **kwargs):
            raise copilot.CopilotError("api_rate_limit", "The API is busy.")
            yield  # pragma: no cover
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: Failing())
    failed = _read(now=IN_SESSION)
    assert failed["state"] == "error" and failed["message"] == "The API is busy." and "text" not in failed
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    assert _read(now=IN_SESSION + 60)["state"] == "ok" and len(turns) == 2


# --------------------------------------------------------------------------- the small turn and its record

def test_a_read_is_a_small_desk_read_turn_recorded_on_the_shared_budget(turns):
    _read(now=IN_SESSION)
    [started] = turns
    cfg = started["cfg"]
    assert (cfg.max_rounds, cfg.max_tool_calls, cfg.turn_budget_usd, cfg.max_tokens) == (2, 4, 0.10, 1500)
    assert cfg.turn_budget_usd < copilot.settings().turn_budget_usd
    assert cfg.model == copilot.settings().model  # the configured model: no cheaper one has held the shape
    assert started["kind"] == "desk_read" and started["source"] == "desk" and started["symbol"] == "NBIS"
    assert copilot_prompt.job_for("desk_read", "desk") == "desk_read"
    assert "plan" not in started["question"].lower()  # nothing in it asks for a plan card
    [row] = _rows(1)
    assert row.kind == "desk_read" and row.source == "desk" and row.symbol == "NBIS" and row.error is None
    assert copilot_spend.kind_today("desk_read") == {"count": 1, "refused": 0, "cost_usd": 0.0}


class Priced:
    """A real-model stand-in: one round of reads, then the four lines, each round with a priced usage."""
    model = "claude-sonnet-5-5"

    def __init__(self):
        self.calls = []

    async def stream_round(self, system, messages, tools, allow_tools=True):
        self.calls.append({"system": system, "tools": [t["name"] for t in tools], "allow": allow_tools})
        usage = {"input_tokens": 8000, "output_tokens": 300, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        if allow_tools:
            content = [{"type": "tool_use", "id": "t1", "name": "get_quotes", "input": {"symbols": ["NBIS"]}}]
            yield "final", copilot.Round(content, "tool_use", usage, self.model)
            return
        text = "Verdict: Hold — NBIS holds above your entry.\n- Last 94.35, 1.2% over your 93.20 entry.\n- Its group is up 0.8%.\nChanges if: a close under 91."
        yield "text", text
        yield "final", copilot.Round([{"type": "text", "text": text}], "end_turn", usage, self.model)


def test_an_api_read_counts_its_cost_toward_the_day_and_runs_the_jobs_prompt_and_tools(monkeypatch):
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    adapter = Priced()
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: adapter)
    out = _read(now=IN_SESSION)
    assert out["state"] == "ok" and out["text"].startswith("Verdict: Hold")
    first, second = adapter.calls
    assert first["system"] == copilot_prompt.PROMPTS["desk_read"] and first["tools"] == list(copilot_prompt.DESK_READ_TOOLS)
    assert first["allow"] and not second["allow"]  # one round of reads, then it must write
    [row] = _rows(1)
    expected = round(2 * copilot.cost_usd("claude-sonnet-5-5", {"input_tokens": 8000, "output_tokens": 300, "cache_read_input_tokens": 0,
                                                                 "cache_creation_input_tokens": 0}), 6)
    assert row.billing == "api" and row.kind == "desk_read" and float(row.cost_usd) == pytest.approx(expected)
    assert copilot_spend.spent_today() == pytest.approx(expected)
    assert out["cost_usd"] == pytest.approx(round(expected, 4)) and out["today"]["count"] == 1


def test_the_desk_read_job_offers_only_its_reads_and_ends_with_its_own_shape():
    prompt = copilot_prompt.PROMPTS["desk_read"]
    names = {t["name"] for t in copilot_prompt.TOOLS["desk_read"]}
    assert names == set(copilot_prompt.DESK_READ_TOOLS)
    assert not names & {"propose_plan", "get_trade_review", "get_option_candidates", "get_level_history", "get_week_review"}
    assert "Exactly three or four lines" in prompt and "Never Draft" in prompt and "Earlier evidence" not in prompt
    assert copilot_prompt.shape("desk_read") == copilot_answer.DESK_READ_SHAPE
    assert copilot_answer.without_shape("Desk read: NBIS.\n\n" + copilot_answer.DESK_READ_SHAPE) == "Desk read: NBIS."


# --------------------------------------------------------------------------- refusals

def test_a_spent_budget_refuses_the_read_with_a_zero_cost_row_and_no_call(turns, monkeypatch):
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # $3.85 of $4.00 spent: two caps' worth ($0.20) no longer fits, so no read starts.
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.85)
    out = _read(now=IN_SESSION)
    assert out["state"] == "budget" and "budget ($4.00) is spent" in out["message"] and "text" not in out
    assert turns == []
    [row] = _rows(1)
    assert row.kind == "desk_read" and row.error == "daily_budget" and row.cost_usd == 0 and row.symbol == "NBIS"
    assert out["today"] == {"count": 0, "refused": 1, "cost_usd": 0.0}
    # With $0.20 still free, a read starts.
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.80)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    assert _read(now=IN_SESSION + 60)["state"] == "ok" and len(turns) == 1


def test_the_headroom_scales_with_a_dearer_models_cap(monkeypatch):
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("COPILOT_MODEL", "claude-fable-5-2")  # a cap twice Opus's: $0.20 a read, so $0.40 of room
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.65)
    assert copilot.turn_cap(desk_read.small(copilot.settings()), False) == pytest.approx(0.20)
    assert _read(now=IN_SESSION)["state"] == "budget"


def test_reads_of_different_tickers_run_one_at_a_time_and_see_the_last_ones_cost(monkeypatch):
    """A turn's row is written after its stream ends, so the next read's check adds the cost the last one just spent."""
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    live = {"now": 0, "most": 0}

    class Slow(Priced):
        async def stream_round(self, *args, **kwargs):
            live["now"] += 1
            live["most"] = max(live["most"], live["now"])
            await asyncio.sleep(0.05)
            async for event in super().stream_round(*args, **kwargs):
                yield event
            live["now"] -= 1
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: Slow())
    # $3.78 recorded: room for the first read; the first read's $0.038 not yet in the record still counts for the second.
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.78)

    async def both():
        return await asyncio.gather(desk_read.read("NBIS", now=IN_SESSION), desk_read.read("CRWV", now=IN_SESSION))
    first, second = asyncio.run(both())
    assert live["most"] == 1
    assert [first["state"], second["state"]] == ["ok", "budget"]


def test_a_ticker_he_does_not_follow_never_gets_a_read_and_neither_does_an_unreadable_setting(turns, monkeypatch):
    _read(now=IN_SESSION)
    _hide("NBIS")
    assert _read(now=IN_SESSION + 60) == {"state": "hidden"}  # not even the kept one
    assert _read(now=IN_SESSION + 60, refresh=True) == {"state": "hidden"}
    assert len(turns) == 1
    monkeypatch.setattr(day_journal, "not_following", lambda db: (_ for _ in ()).throw(RuntimeError("db down")))
    assert _read("CRWV", now=IN_SESSION) == {"state": "hidden"}
    assert len(turns) == 1


def test_not_a_ticker_is_refused_without_a_call(turns):
    assert _read("nbis; drop", now=IN_SESSION)["state"] == "error" and turns == []


# --------------------------------------------------------------------------- the route and the timings view

def test_the_route_reads_and_the_timings_view_counts_the_days_reads_and_cost(turns, monkeypatch):
    with TestClient(app) as client:
        body = client.post("/copilot/desk/read", json={"symbol": "nbis"}).json()
        assert body["state"] == "ok" and body["cached"] is False
        assert client.post("/copilot/desk/read", json={"symbol": "NBIS"}).json()["cached"] is True
        _rows(1)
        timings = client.get("/copilot/desk/timings").json()
        assert timings["desk_reads"] == {"count": 1, "refused": 0, "cost_usd": 0.0} and "routes" in timings
        assert client.post("/copilot/desk/read", json={"symbol": ""}).status_code == 422
        monkeypatch.setenv("COPILOT_ENABLED", "false")
        assert client.post("/copilot/desk/read", json={"symbol": "NBIS"}).status_code == 503
    assert len(turns) == 1
