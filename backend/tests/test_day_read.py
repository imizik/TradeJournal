"""The day read (docs/copilot-lab.md § The day read, ``app/engine/day_read.py``): after the close, one small recorded turn
a day writes four to six lines on the owner's day from the day report's facts; it is kept for the day (memory and a
file), a second one runs only on his tap, a day with no fills and no plans gets one line and no call, a spent budget is
refused with a zero-cost row, every dollar figure in the read must be one the facts hold, and a ticker he does not follow
is left out of every part. Offline: the scripted model, or a stand-in adapter with a priced usage."""
import asyncio
import time
import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, delete, select

from app.ai import copilot, copilot_answer, copilot_prompt, copilot_spend
from app.database import engine as app_engine
from app.engine import alert_scorecard, day_read, plan_streak
from app.engine import robinhood_book as rb
from app.engine import robinhood_fills
from app.engine.chart_math import ET
from app.main import app
from app.models import Account, CopilotTurn, DayJournalEntry, Trade, TradeCapture
from app.routers import copilot_desk

# Friday 2026-11-13: 18:00 New York (after the close) and 11:00 (in the session).
EVENING = datetime(2026, 11, 13, 18, 0, tzinfo=ET).timestamp()
MIDDAY = datetime(2026, 11, 13, 11, 0, tzinfo=ET).timestamp()
ROTH, INDIVIDUAL = uuid.UUID(int=11), uuid.UUID(int=12)
NBIS, CRWV, OLDX, MU = (uuid.UUID(int=n) for n in (21, 22, 23, 24))


@pytest.fixture
def journal():
    """A journal of its own: two accounts and today's trades (NBIS lost with a plan, CRWV won without one, OLDX not
    followed, MU opened and still open)."""
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        db.add(Account(id=ROTH, name="Roth IRA", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=INDIVIDUAL, name="Individual", type="individual", last4="1234", broker="robinhood"))

        def trade(id_, account, ticker, strike, entry, exit_, pnl, opened, closed, contracts=3):
            db.add(Trade(id=id_, account_id=account, ticker=ticker, instrument_type="option", option_type="call", strike=strike,
                         expiration=date(2026, 11, 21), contracts=contracts, avg_entry_premium=entry, avg_exit_premium=exit_,
                         total_premium_paid=entry * contracts, realized_pnl=pnl, opened_at=datetime.fromisoformat(opened),
                         closed_at=datetime.fromisoformat(closed) if closed else None, status="closed" if closed else "open"))
        trade(NBIS, ROTH, "NBIS", 100, 235.0, 110.0, -375.0, "2026-11-13T10:02", "2026-11-13T11:47")
        trade(CRWV, INDIVIDUAL, "CRWV", 120, 150.0, 211.25, 122.5, "2026-11-13T10:15", "2026-11-13T14:30", contracts=2)
        trade(OLDX, ROTH, "OLDX", 5, 40.0, 10.0, -60.0, "2026-11-13T09:50", "2026-11-13T10:20", contracts=2)
        trade(MU, ROTH, "MU", 90, 300.0, None, None, "2026-11-13T15:10", None, contracts=1)
        db.add(DayJournalEntry(operation_id="f-oldx", day=date(2026, 11, 13), kind="follow", text="Not following", symbol="OLDX"))
        for client, symbol, hour in (("c1", "NBIS", 14), ("c2", "OLDX", 14)):  # 09:00 New York, saved today
            db.add(TradeCapture(client_id=client, received_at=datetime(2026, 11, 13, hour), account_id=ROTH, account_label="Roth IRA",
                                underlying=symbol, side="buy_calls", instrument="option", mode="discretionary", wording="Reclaim of 98",
                                context_state="unavailable", image_state="none", context_json="{}"))
        db.commit()
    yield db_engine
    db_engine.dispose()


@pytest.fixture(autouse=True)
def lab(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    monkeypatch.setattr(day_read, "ROOT", tmp_path / "day_read")
    monkeypatch.setattr(day_read, "close_epoch", lambda day: datetime(day.year, day.month, day.day, 16, 0, tzinfo=ET).timestamp())
    entries = [{"trade_id": str(NBIS), "state": "planned", "capture_id": None}, {"trade_id": str(CRWV), "state": "unplanned"},
               {"trade_id": str(OLDX), "state": "unplanned"}, {"trade_id": str(MU), "state": "late"}]
    monkeypatch.setattr(plan_streak, "streak", lambda db, now=None: {"this_week": {"entries": entries}})
    alert_at = datetime(2026, 11, 13, 11, 5, tzinfo=ET).timestamp()
    monkeypatch.setattr(alert_scorecard, "scorecard", lambda db, now, days=30: {"rows": [
        {"at": alert_at, "kind": "give_back", "kind_label": "Give-back", "contract": "NBIS 11/21/26 100C", "symbol": "NBIS",
         "pnl_pct_at_alert": 12.0, "outcome": {"state": "closed", "how": "sold", "sell_at_alert_usd": 705.0, "actual_usd": 330.0,
                                                "vs_alert_usd": -375.0}},
        {"at": alert_at, "kind": "give_back", "kind_label": "Give-back", "contract": "OLDX 11/21/26 5C", "symbol": "OLDX",
         "pnl_pct_at_alert": 9.0, "outcome": {"state": "open", "sell_at_alert_usd": 99.0}}]})
    monkeypatch.setattr(rb.feed, "snapshot", lambda kick=True: ({"state": "off"}, None))
    monkeypatch.setattr(robinhood_fills.poller, "desk", lambda now=None: None)
    with Session(app_engine) as db:
        db.exec(delete(CopilotTurn))
        db.commit()
    day_read.clear()
    yield
    day_read.clear()


@pytest.fixture
def facts_from(journal, monkeypatch):
    """The read's facts come from the test journal."""
    def read_facts(now):
        with Session(journal) as db:
            return day_read.facts(db, now)
    monkeypatch.setattr(day_read, "_facts", read_facts)
    return journal


@pytest.fixture
def turns(monkeypatch):
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
        with Session(app_engine) as db:
            rows = db.exec(select(CopilotTurn).order_by(CopilotTurn.started_at)).all()
        if count is None or len(rows) >= count or time.monotonic() > deadline:
            return rows
        time.sleep(0.02)


def _read(**kwargs):
    return asyncio.run(day_read.read(**{"now": EVENING, **kwargs}))


def _facts(journal):
    with Session(journal) as db:
        return day_read.facts(db, EVENING)


# --------------------------------------------------------------------------- the facts

def test_the_facts_hold_realised_pnl_by_account_and_its_total_as_the_top_bar_counts_it(journal):
    f = _facts(journal)
    assert f["realized"] == {"Roth IRA": -375.0, "Individual": 122.5} and f["realized_total"] == -252.5
    with Session(journal) as db:  # the desk's top bar, OLDX's -$60 aside (a ticker he does not follow)
        assert copilot_desk._realized_today(db, date(2026, 11, 13))["usd"] == -252.5 - 60.0
    text = day_read.pack(f)
    assert "Realised today (trades closed today): total -$252.50; Roth IRA -$375.00; Individual +$122.50" in text
    # Each trade with its times, its premium a share, its size and whether a plan came first.
    assert ("- NBIS 11/21/26 100C, Roth IRA: 3 contracts, in 10:02 at $2.35, out 11:47 at $1.10, realised -$375.00; "
            "plan saved before the entry") in text
    assert "- CRWV 11/21/26 120C, Individual: 2 contracts, in 10:15 at $1.50, out 14:30 at $2.11, realised +$122.50; no plan" in text
    assert "Opened today, still open:\n- MU 11/21/26 90C, Roth IRA: 1 contract in 15:10 at $3.00; plan saved after the entry" in text
    assert text.count("NBIS 11/21/26 100C, Roth IRA") == 1  # opened and closed today: once, under Closed today
    assert "Plans saved today: 1 (NBIS)" in text
    assert ("11:05 Give-back on NBIS 11/21/26 100C at +12%: you sold for $330.00 against $705.00 at the alert "
            "(-$375.00 against selling at the alert)") in text
    assert "the Robinhood account line is not available (off)" in text


def test_a_ticker_he_does_not_follow_is_in_no_part_of_the_facts(journal, monkeypatch):
    monkeypatch.setattr(robinhood_fills.poller, "desk", lambda now=None: [
        {"symbol": "OLDX", "instrument": "stock", "option_type": None, "strike": None, "expiry": None, "action": "buy", "filled": 5,
         "avg": 4.0, "filled_at": EVENING - 7200, "account": "Roth IRA", "pairing": "provisional"}])
    monkeypatch.setattr(rb.feed, "snapshot", lambda kick=True: ({"state": "ok"}, {"at": EVENING - 60, "accounts": [
        {"label": "Roth IRA", "last4": "8267", "open_pnl": 900.0, "day_change": -86.0},
        {"label": "Individual", "last4": "1234", "open_pnl": -40.0, "day_change": 12.0}], "positions": [
        {"last4": "8267", "symbol": "MU", "usd": 1000.0}, {"last4": "8267", "symbol": "OLDX", "usd": -100.0},
        {"last4": "1234", "symbol": "CRWV", "usd": -40.0}]}))
    text = day_read.pack(_facts(journal))
    assert "OLDX" not in text
    # The Roth holds OLDX: its open P&L is its followed positions' (+$1,000.00), with no change today; the other's as given.
    assert "Roth IRA open +$1,000.00 (followed positions only); Individual open -$40.00, today +$12.00" in text


def test_a_provisional_robinhood_fill_is_labelled_provisional(journal, monkeypatch):
    monkeypatch.setattr(robinhood_fills.poller, "desk", lambda now=None: [
        {"symbol": "SMCI", "instrument": "option", "option_type": "call", "strike": 45.0, "expiry": "2026-11-21", "action": "buy_to_open",
         "filled": 2, "avg": 1.2, "filled_at": datetime(2026, 11, 13, 15, 58, tzinfo=ET).timestamp(), "account": "Individual",
         "pairing": "provisional"},
        {"symbol": "AMD", "instrument": "stock", "option_type": None, "strike": None, "expiry": None, "action": "buy", "filled": 1,
         "avg": 150.0, "filled_at": EVENING - 3600, "account": "Individual", "pairing": "matched"}])  # in the journal already
    text = day_read.pack(_facts(journal))
    assert "(provisional: call them provisional if you mention them)" in text
    assert "SMCI" in text and "at $1.20, Individual (provisional)" in text and "AMD" not in text


# --------------------------------------------------------------------------- one read a day, kept

def test_one_read_a_day_is_written_once_and_kept_across_a_restart(facts_from, turns):
    first = _read()
    assert first["state"] == "ok" and first["cached"] is False and len(turns) == 1
    assert first["text"].startswith("Simulated day read") and "P&L:" in first["text"] and "Tomorrow:" in first["text"]
    assert "Realised today" in first["facts"]  # Ask more carries the facts it was written from
    again = _read(now=EVENING + 600)
    assert again["state"] == "ok" and again["cached"] is True and again["text"] == first["text"] and len(turns) == 1
    day_read.clear()  # a restart: the read comes back from its file, with no call
    assert _read(now=EVENING + 900)["text"] == first["text"] and len(turns) == 1
    [row] = _rows(1)
    assert row.kind == "day_read" and row.source == "desk" and row.error is None and row.symbol is None


def test_a_lost_read_is_not_written_again_automatically_only_on_his_tap(facts_from, turns):
    _read()
    day_read.clear()
    for path in day_read.ROOT.glob("*.json"):
        path.unlink()
    lost = _read(now=EVENING + 60)
    assert lost["state"] == "none" and "Refresh" in lost["message"] and len(turns) == 1
    fresh = _read(now=EVENING + 120, refresh=True)
    assert fresh["state"] == "ok" and fresh["cached"] is False and len(turns) == 2
    assert copilot_spend.kind_today("day_read")["count"] == 2


def test_before_the_close_there_is_no_read(facts_from, turns):
    assert _read(now=MIDDAY) == {"state": "early"}
    assert turns == [] and _rows() == []


def test_a_day_with_no_fills_and_no_plans_is_one_line_and_no_call(turns, monkeypatch):
    monkeypatch.setattr(day_read, "_facts", lambda now: {"closed": [], "opened": [], "plans": [], "provisional": [], "alerts": []})
    out = _read()
    assert out["state"] == "quiet" and out["text"] == "Nothing to read today: no fills and no plans."
    assert turns == [] and _rows() == []


def test_the_read_is_one_round_with_no_tools_on_the_configured_model(facts_from, turns):
    _read()
    [started] = turns
    cfg = started["cfg"]
    assert (cfg.max_rounds, cfg.max_tool_calls, cfg.turn_budget_usd, cfg.max_tokens) == (1, 0, 0.10, 1500)
    assert cfg.model == copilot.settings().model  # no cheaper model has held an answer shape in the eval
    assert started["kind"] == "day_read" and started["source"] == "desk"
    assert copilot_prompt.job_for("day_read", "desk") == "day_read" and copilot_prompt.TOOLS["day_read"] == []
    prompt = copilot_prompt.PROMPTS["day_read"]
    assert "copied exactly as" in prompt and "never take a dollar figure from the owner context block" in prompt
    assert "get_market_regime" not in prompt and "propose_plan" not in prompt
    assert copilot_prompt.shape("day_read") == copilot_answer.DAY_READ_SHAPE
    # A request with no tools sends neither tools nor a tool choice.
    request = copilot.AnthropicAdapter(day_read.small(copilot.settings()), client=object()).request("s", [{"role": "user", "content": "x"}], [], False)
    assert "tools" not in request and "tool_choice" not in request


# --------------------------------------------------------------------------- the figures

def test_every_figure_in_the_read_is_one_the_day_report_holds(facts_from, turns):
    out = _read()
    assert day_read.unmatched(out["text"], out["facts"]) == []
    assert "-$252.50" in out["text"] and "-$375.00" in out["text"]  # the total and the biggest trade, as the report has them


def test_the_figure_check_catches_a_rounded_an_invented_and_a_flipped_figure():
    facts = "total -$252.50; Roth IRA -$375.00; at $2.35"
    assert day_read.unmatched("You lost $375.00 on NBIS at $2.35; -$252.50 on the day.", facts) == []
    assert day_read.unmatched("You lost $375 on NBIS.", facts) == []  # the same value, written without cents
    assert day_read.unmatched("Down $250 on the day.", facts) == ["$250.00"]
    assert day_read.unmatched("Up +$375.00 on NBIS.", facts) == ["+$375.00"]
    assert day_read.unmatched("About $1.2k lost.", "$1.20 a contract") == ["$1.20k"]  # $1,200, never $1.20
    assert day_read.unmatched("Lost $-375.00 on NBIS.", facts) == [] and day_read.unmatched("Made $+375.00.", facts) == ["+$375.00"]
    assert day_read.unmatched("Filled between $1.20-$1.50.", "at $1.20; at $1.50") == []  # a range, not a negative
    assert day_read.unmatched("NBIS lost −$375.00.", facts) == []  # the Unicode minus


class Priced:
    """A real-model stand-in: one round that writes ``text``, with a priced usage."""
    model = "claude-sonnet-5-5"

    def __init__(self, text):
        self.text = text
        self.calls = []

    async def stream_round(self, system, messages, tools, allow_tools=True):
        self.calls.append({"system": system, "tools": tools, "allow": allow_tools, "message": messages[-1]["content"]})
        usage = {"input_tokens": 9000, "output_tokens": 250, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        yield "text", self.text
        yield "final", copilot.Round([{"type": "text", "text": self.text}], "end_turn", usage, self.model)


def _api(monkeypatch, text):
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    adapter = Priced(text)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: adapter)
    return adapter


GOOD = ("P&L: realised -$252.50 (Roth IRA -$375.00, Individual +$122.50).\nPlans: NBIS had a plan first; CRWV had none.\n"
        "Biggest: NBIS 100C lost -$375.00 after you held through the 11:05 give-back alert.\n"
        "Tomorrow: on a give-back alert like NBIS's, sell at the alert or say why you hold.")


def test_an_api_read_runs_the_jobs_prompt_with_the_facts_and_counts_its_cost(facts_from, monkeypatch):
    adapter = _api(monkeypatch, GOOD)
    out = _read()
    assert out["state"] == "ok" and out["text"] == GOOD
    [call] = adapter.calls
    assert call["system"] == copilot_prompt.PROMPTS["day_read"] and call["tools"] == [] and call["allow"] is False
    assert "Realised today (trades closed today): total -$252.50" in call["message"] and "OLDX" not in call["message"]
    [row] = _rows(1)
    expected = round(copilot.cost_usd("claude-sonnet-5-5", {"input_tokens": 9000, "output_tokens": 250, "cache_read_input_tokens": 0,
                                                             "cache_creation_input_tokens": 0}), 6)
    assert row.billing == "api" and row.kind == "day_read" and float(row.cost_usd) == pytest.approx(expected)
    assert out["today"]["count"] == 1 and out["today"]["cost_usd"] == pytest.approx(round(expected, 4))


def test_a_read_quoting_a_figure_the_report_does_not_hold_is_not_shown(facts_from, monkeypatch):
    _api(monkeypatch, GOOD.replace("-$252.50", "-$250"))
    out = _read()
    assert out["state"] == "error" and "text" not in out and "-$250.00" in out["message"]
    assert len(_rows(1)) == 1  # the call is counted
    again = _read(now=EVENING + 60)  # not asked again by itself
    assert again["state"] == "error" and again["cached"] is True and len(_rows()) == 1


def test_a_read_naming_a_ticker_he_does_not_follow_is_not_shown(facts_from, monkeypatch):
    _api(monkeypatch, GOOD + "\nOLDX was the other loser.")
    out = _read()
    assert out["state"] == "error" and "ticker you do not follow" in out["message"] and "OLDX" not in out["message"]


def test_ordinary_words_are_never_taken_for_a_ticker_he_does_not_follow():
    hidden = {"OLDX", "ET", "A", "P", "SPY"}
    assert day_read.hidden_named("Biggest: NBIS at 14:05 ET. A plan first; P&L: -$375.00. OLDX too.", hidden, "as of 17:30 ET") == ["OLDX"]
    assert day_read.hidden_named("SPY was flat.", hidden) == ["SPY"]


def test_a_failed_refresh_never_hides_the_days_good_read(facts_from, turns, monkeypatch):
    first = _read()
    assert first["state"] == "ok"
    _api(monkeypatch, GOOD.replace("-$252.50", "-$999.00"))
    failed = _read(now=EVENING + 60, refresh=True)
    assert failed["state"] == "error"
    again = _read(now=EVENING + 120)
    assert again["state"] == "ok" and again["text"] == first["text"]
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.99)  # a refused Refresh hides nothing either
    assert _read(now=EVENING + 180, refresh=True)["state"] == "budget"
    assert _read(now=EVENING + 240)["text"] == first["text"]


def test_a_quiet_day_is_not_kept_so_fills_that_arrive_later_get_their_read(facts_from, turns, monkeypatch):
    real = day_read._facts
    monkeypatch.setattr(day_read, "_facts", lambda now: {"closed": [], "opened": [], "plans": [], "provisional": [], "alerts": []})
    assert _read()["state"] == "quiet"
    monkeypatch.setattr(day_read, "_facts", real)
    assert _read(now=EVENING + 600)["state"] == "ok" and len(turns) == 1


def test_a_trade_the_plan_streak_does_not_track_says_so_and_never_claims_it_is_older(journal, monkeypatch):
    monkeypatch.setattr(plan_streak, "streak", lambda db, now=None: {"this_week": {"entries": []}})
    text = day_read.pack(_facts(journal))
    assert "plan not tracked for this trade" in text and "before this week" not in text


def test_a_spent_budget_refuses_the_read_with_a_zero_cost_row_and_no_call(facts_from, turns, monkeypatch):
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.85)  # two $0.10 caps no longer fit under $4.00
    out = _read()
    assert out["state"] == "budget" and out["message"] == "No read of your day: today's copilot budget ($4.00) is spent."
    assert turns == []
    [row] = _rows(1)
    assert row.kind == "day_read" and row.error == "daily_budget" and row.cost_usd == 0
    assert out["today"] == {"count": 0, "refused": 1, "cost_usd": 0.0}
    assert _read(now=EVENING + 60)["state"] == "budget" and len(_rows()) == 1  # kept: no second refusal row
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.80)  # room again: only his tap reads
    assert _read(now=EVENING + 120, refresh=True)["state"] == "ok" and len(turns) == 1


def test_two_asks_at_once_make_one_call(facts_from, turns):
    async def both():
        return await asyncio.gather(day_read.read(now=EVENING), day_read.read(now=EVENING))
    a, b = asyncio.run(both())
    assert a["text"] == b["text"] and len(turns) == 1


# --------------------------------------------------------------------------- the route

def test_the_route_reads_and_the_timings_view_counts_the_days_reads(facts_from, turns, monkeypatch):
    monkeypatch.setattr(day_read.time, "time", lambda: EVENING)
    with TestClient(app) as client:
        body = client.post("/copilot/desk/day-read", json={}).json()
        assert body["state"] == "ok" and body["today"]["count"] == 1
        assert client.post("/copilot/desk/day-read", json={}).json()["cached"] is True
        assert client.get("/copilot/desk/timings").json()["day_reads"]["count"] == 1
        monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
        assert client.post("/copilot/desk/day-read", json={}).status_code == 503
