"""Pre-market prep: on a trading morning, one copilot turn writes a short prep from a compact pack (positions, armed plans,
earnings this week, today's time stops, the plan streak), saved as a copilot investigation, and one phone ping opens it.
Once a day at most, never on a weekend or holiday, off by default and while the lab is off; raw facts when the turn
fails. No network."""

import asyncio
from datetime import date, datetime
import json
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import copilot, copilot_context
from app.engine import jo_briefing, ntfy, position_alerts, premarket_prep, quotes, reconstructor
from app.engine.chart_feed import chart_feed
from app.engine.chart_math import ET
from app.engine.level_alert_monitor import LevelAlertMonitor
from app.engine.premarket_prep import FALLBACK_LABEL, PremarketPreps, build_pack
from app.engine.quotes import OptionQuoteResult
from app.engine.symbol_info_tradier import symbol_events
from app.models import Account, CopilotInvestigation, Fill, LevelAlert, PlanTimeStop, PositionWatch, PremarketPrep, TradeFill
from app.routers.fills import _rebuild_trades
from tests.secret_scan import leaks

ROTH, WEBULL = UUID(int=1), UUID(int=2)
INV = "55555555-5555-4555-8555-555555555555"
MON, TUE, SAT = date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 24)
SECRETS = ("8267", "4242", str(ROTH), str(WEBULL), "RH-55501234")


def at(hhmm: str, day: date = MON) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    """Every weekday open 9:30-16:00, except Tuesday Oct 27, a holiday here."""

    def hours(self, day):
        if day.weekday() >= 5 or day == TUE:
            return {"status": "closed"}
        return {"status": "open", "open": 570, "close": 960}


class _Monday(date):
    @classmethod
    def today(cls):
        return MON


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Monday)
    monkeypatch.setenv("PREMARKET_PREP_ENABLED", "true")
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    monkeypatch.delenv("PREMARKET_PREP_AT", raising=False)
    copilot_context.clear_habits_cache()


@pytest.fixture
def market(monkeypatch):
    """Marks, the plans board's batched quote, and the earnings calendar: every read is recorded."""
    seen = {"quote_rows": [], "refresh": [], "forecast": []}
    monkeypatch.setattr(quotes, "get_stock_quotes", lambda symbols: {s: {"CRWV": 131.2}.get(s) for s in symbols})
    monkeypatch.setattr(quotes, "option_mark", lambda req: (OptionQuoteResult(mid=4.1, last_price=4.0), at("08:29")))
    monkeypatch.setattr(quotes, "get_option_quotes", lambda requests: [OptionQuoteResult(mid=4.1)] * len(requests))

    def quote_rows(symbols):
        seen["quote_rows"].append(list(symbols))
        return [{"symbol": s, "last": {"APLD": 30.0}.get(s, 50.0)} for s in symbols], at("08:29"), None
    monkeypatch.setattr(chart_feed, "quote_rows", quote_rows)

    def refresh(dataset, symbols):
        seen["refresh"].append((dataset, list(symbols)))
        return None
    upcoming = {"NBIS": "2026-10-28", "IREN": "2026-11-05"}

    def forecast(symbol, today):
        seen["forecast"].append(symbol)
        day = upcoming.get(symbol)
        return {"state": "ready", "next": {"date": day, "status": "confirmed", "label": "Q3"} if day else None, "reports": []}
    monkeypatch.setattr(symbol_events, "refresh", refresh)
    monkeypatch.setattr(symbol_events, "forecast_earnings", forecast)
    return seen


@pytest.fixture
def engine(market):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Robinhood Roth 8267", type="roth_ira", last4="8267", broker="robinhood",
                       broker_account_id="RH-55501234"))
        db.add(Account(id=WEBULL, name="Webull 4242", type="individual", last4="4242", broker="webull"))
        call = {"option_type": "call", "strike": 100, "expiration": MON}  # expires today
        db.add_all([
            Fill(id=UUID(int=11), account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=2,
                 price=310, executed_at=datetime(2026, 10, 23, 10, 5), raw_email_id="gmail:11", **call),
            Fill(id=UUID(int=12), account_id=ROTH, ticker="CRWV", instrument_type="stock", side="buy", contracts=10,
                 price=120, executed_at=datetime(2026, 10, 20, 11, 0), raw_email_id="gmail:12"),
            Fill(id=UUID(int=13), account_id=WEBULL, ticker="TSLA", instrument_type="stock", side="buy", contracts=3,
                 price=200, executed_at=datetime(2026, 10, 23, 11, 0), raw_email_id="gmail:13"),  # dormant: never shown
        ])
        db.commit()
        _rebuild_trades(db, "test")
        entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id).where(Fill.ticker == "NBIS", TradeFill.role == "entry")).all()
        db.add(PositionWatch(account_id=ROTH, source_key=position_alerts.anchor(entries), generation=1, contracts=2, avg_cost=310,
                             peak_mark=450, peak_at=datetime(2026, 10, 23, 18, 0), armed_at=datetime(2026, 10, 23, 18, 0)))
        created = datetime(2026, 10, 23, 19, 0)  # Friday 15:00 ET, naive UTC
        for role, price in (("entry", 31.5), ("invalidation", 28.8)):
            db.add(LevelAlert(symbol="APLD", price=price, created_on=date(2026, 10, 23), condition="crosses", session="regular",
                              direction="up" if role == "entry" else "down", source_kind="copilot", source_id=INV,
                              label=f"APLD {role}", plan_role=role, created_at=created, armed_at=created))
        db.add(PlanTimeStop(client_id="card-1", investigation_id=INV, symbol="APLD", text="out by 15:30",
                            due_at=datetime(2026, 10, 26, 19, 30), created_at=created))
        db.add(CopilotInvestigation(id=UUID(INV), source="copilot", title="APLD reclaim plan", symbol="APLD",
                                    transcript_json="[]", evidence_json="[]"))
        db.commit()
        jo_briefing.save_memory(db, jo_briefing.MemorySave(operation_id="m1", kind="thesis", symbol="IREN", source="owner_statement",
                                                           status="active", owner_confirmed=True,
                                                           original_text="IREN is my AI-power thesis."))
    yield engine
    engine.dispose()


@pytest.fixture
def phone(monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    return sent


class Turn:
    def __init__(self, text="\n".join(f"Line {i}" for i in range(1, 9)), error=None):
        self.text, self.error, self.calls = text, error, []

    def __call__(self, question, now):
        self.calls.append(question)
        return self.text, self.error


def preps(engine, clock, turn):
    return PremarketPreps(engine, Calendar(), clock=clock, spawn=lambda work: work(), turn=turn)


def rows(engine):
    with Session(engine) as db:
        return db.exec(select(PremarketPrep).order_by(PremarketPrep.day)).all()


# ------------------------------------------------------------------ the pack

def test_the_pack_holds_positions_plans_earnings_time_stops_and_the_streak(engine, market):
    with Session(engine) as db:
        pack = build_pack(db, at("08:30"))
    text = json.dumps(pack, default=str)
    assert not leaks(text, SECRETS) and "trade_id" not in text and "TSLA" not in text
    held = pack["positions"]
    assert held["count"] == 2 and [p["symbol"] for p in held["positions"]] == ["NBIS", "CRWV"]  # expiring first
    nbis = held["positions"][0]
    assert nbis["expires_today"] is True and nbis["days_to_expiry"] == 0 and nbis["option"]["strike"] == 100
    assert nbis["unrealized_usd"] == 200.0 and nbis["giveback"] == "armed"
    assert held["positions"][1]["unrealized_usd"] == 112.0
    plan = pack["plans"]["plans"][0]
    assert plan["symbol"] == "APLD" and plan["thesis"] == "APLD reclaim plan" and plan["position"] == "waiting"
    assert plan["entry"] == {"price": 31.5, "state": "armed", "distance_pct": 5.0}
    assert plan["invalidation"] == {"price": 28.8, "state": "armed", "distance_pct": -4.0}
    assert market["quote_rows"] == [["APLD"]]  # one batched quote for the board
    earnings = pack["earnings"]
    assert earnings["checked"] == ["NBIS", "CRWV", "IREN"]  # held, then thesis memories
    assert earnings["this_week"] == [{"symbol": "NBIS", "date": "2026-10-28", "status": "confirmed"}]  # IREN reports next week
    assert market["refresh"] == [("calendars", ["NBIS", "CRWV", "IREN"])]  # one batched calendar read
    assert pack["time_stops"]["today"] == [{"symbol": "APLD", "text": "out by 15:30", "due": "15:30 ET"}]
    assert pack["streak"]["state"] == "ok" and "this_week" in pack["streak"]


def test_earnings_are_capped_at_eight_symbols_and_skip_indices(market):
    symbols = ["VIX", *[f"S{i}" for i in range(12)]]
    out = premarket_prep._earnings(symbols, MON)
    assert out["checked"] == [f"S{i}" for i in range(8)] and market["refresh"] == [("calendars", out["checked"])]


def test_one_failing_section_leaves_the_rest(engine, monkeypatch):
    monkeypatch.setattr(premarket_prep, "_plans", lambda db: 1 / 0)
    with Session(engine) as db:
        pack = build_pack(db, at("08:30"))
    assert pack["plans"] == {"state": "unavailable"} and pack["positions"]["state"] == "ok"


# ------------------------------------------------------------------ the morning ping

def test_it_preps_once_saves_an_investigation_and_pings_the_first_two_lines(engine, phone):
    turn, clock = Turn(), Clock(at("08:30"))
    runner = preps(engine, clock, turn)
    runner.run()
    assert len(turn.calls) == 1 and turn.calls[0].startswith("Pre-market prep for Mon Oct 26.")
    assert '"symbol":"APLD"' in turn.calls[0] and "Invent nothing" in turn.calls[0]
    [(title, body, kw)] = phone
    assert title == "Pre-market prep" and body == "Line 1\nLine 2"
    path = urlsplit(kw["path"])
    assert path.path == "/copilot-lab" and kw["direct_click"] is True
    investigation_id = parse_qs(path.query)["investigation"][0]
    assert parse_qs(path.query)["origin"] == [f"premarket_prep:{investigation_id}"]  # a plan made from it records the prep
    with Session(engine) as db:
        saved = db.get(CopilotInvestigation, UUID(investigation_id))
        assert saved.title == "Pre-market prep 2026-10-26" and saved.source == "copilot" and saved.status == "open"
        transcript = json.loads(saved.transcript_json)
    assert [m["role"] for m in transcript] == ["user", "assistant"]
    assert transcript[1]["content"].splitlines() == [f"Line {i}" for i in range(1, 7)]  # at most six lines
    [row] = rows(engine)
    assert row.delivery == "sent" and row.fallback is False and row.investigation_id == investigation_id

    clock.now = at("08:45")
    runner.run()
    preps(engine, clock, turn).run()  # a restart, or a second process
    runner.deliver()
    assert len(turn.calls) == 1 and len(phone) == 1 and len(rows(engine)) == 1


@pytest.mark.parametrize("moment", [at("08:30", SAT), at("08:30", TUE), at("08:29"), at("09:30")],
                         ids=["weekend", "holiday", "before its time", "past its window"])
def test_no_prep_outside_a_trading_morning(engine, phone, moment):
    turn = Turn()
    preps(engine, Clock(moment), turn).run()
    assert turn.calls == [] and phone == [] and rows(engine) == []


def test_the_time_is_a_setting(engine, phone, monkeypatch):
    monkeypatch.setenv("PREMARKET_PREP_AT", "09:00")
    turn = Turn()
    preps(engine, Clock(at("08:30")), turn).run()
    assert turn.calls == []
    preps(engine, Clock(at("09:05")), turn).run()
    assert len(turn.calls) == 1 and len(phone) == 1


@pytest.mark.parametrize("flag", ["PREMARKET_PREP_ENABLED", "COPILOT_ENABLED"])
def test_off_by_default_and_nothing_runs_while_the_lab_is_off(engine, phone, monkeypatch, flag):
    monkeypatch.delenv(flag)
    turn = Turn()
    preps(engine, Clock(at("08:30")), turn).run()
    assert turn.calls == [] and phone == [] and rows(engine) == []


def test_a_failed_turn_pings_the_raw_facts_labelled_as_such(engine, phone):
    preps(engine, Clock(at("08:30")), Turn(text="half an ans", error="Stopped: this turn reached its $0.25 API spend cap.")).run()
    [(title, body, kw)] = phone
    assert title == "Pre-market prep"
    assert body == f"{FALLBACK_LABEL}\nExpiring: NBIS 100C 10/26 today"
    [row] = rows(engine)
    assert row.fallback is True and "spend cap" in row.last_error
    assert row.body.splitlines()[2:] == ["Nearest triggers: APLD invalidation 28.8 (-4.0%); APLD entry 31.5 (+5.0%)",
                                         "Time stops today: APLD 15:30 ET", "Earnings this week: NBIS 10-28"]
    with Session(engine) as db:
        saved = db.get(CopilotInvestigation, UUID(row.investigation_id))
        assert json.loads(saved.transcript_json)[1]["content"] == row.body


def test_a_turn_through_the_labs_backend_respects_its_limits(engine, phone, monkeypatch):
    """The real ``run_turn`` on the fake backend: a budget stop mid-turn is a failed turn, so the raw facts go out."""
    async def over_budget(history, symbol, cfg, adapter, evidence, now):
        assert symbol is None and history[-1]["content"].startswith("Pre-market prep")
        yield {"type": "text", "delta": "NBIS expires "}
        yield {"type": "error", "code": "budget", "message": f"Stopped: this turn reached its ${cfg.turn_budget_usd:.2f} API spend cap."}
        yield {"type": "done", "metrics": {}}
    monkeypatch.setattr(copilot, "run_turn", over_budget)
    preps(engine, Clock(at("08:30")), premarket_prep._turn).run()
    [row] = rows(engine)
    assert row.fallback is True and row.last_error == "Copilot turn failed: Stopped: this turn reached its $0.25 API spend cap."
    assert phone[0][1].startswith(FALLBACK_LABEL)


def test_the_fake_backend_writes_a_prep_end_to_end(engine, phone, monkeypatch):
    monkeypatch.setattr(copilot.FakeAdapter, "__init__", lambda self, delay_s=0: setattr(self, "delay_s", 0))
    answer, error = premarket_prep._turn(premarket_prep.prompt({"day": "2026-10-26", "positions": {}}), at("08:30"))
    assert error is None and premarket_prep.lines(answer)


def test_an_interrupted_send_is_never_resent(engine, monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    calls = []

    def timeout(title, body, **kw):
        calls.append(title)
        raise ntfy.NtfyError("timed out") from httpx.ReadTimeout("slow")
    monkeypatch.setattr(ntfy, "publish", timeout)
    clock = Clock(at("08:30"))
    runner = preps(engine, clock, Turn())
    runner.run()
    clock.now = at("08:40")
    runner.deliver()
    assert calls == ["Pre-market prep"] and rows(engine)[0].delivery == "unknown"


def test_a_prep_that_never_finished_or_a_ping_never_sent_is_not_sent_late(engine, phone, monkeypatch):
    clock = Clock(at("08:30"))
    held = []
    runner = PremarketPreps(engine, Calendar(), clock=clock, spawn=held.append, turn=Turn())  # the prep thread never ran
    runner.run()
    clock.now = at("08:41")
    runner.deliver()
    assert rows(engine)[0].delivery == "expired" and phone == []
    held[0]()  # finishing now changes nothing
    assert rows(engine)[0].delivery == "expired" and phone == []

    monkeypatch.delenv("NTFY_URL")
    with Session(engine) as db:
        db.delete(rows(engine)[0])
        db.commit()
    clock.now = at("08:30")
    runner = preps(engine, clock, Turn())
    runner.run()
    assert rows(engine)[0].delivery == "pending"  # phone alerts not set up: waits
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    clock.now = at("09:05")
    runner.deliver()
    assert rows(engine)[0].delivery == "expired" and phone == []


def test_the_monitor_runs_the_prep_on_its_loop(engine):
    class Fake:
        calls = []

        def run(self):
            self.calls.append("run")

        def deliver(self):
            self.calls.append("deliver")

    fake = Fake()
    asyncio.run(LevelAlertMonitor(engine, None, prep=fake).run_once())
    assert fake.calls == ["run", "deliver"]
