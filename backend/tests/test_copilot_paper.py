"""The copilot and his paper book (docs/copilot-lab.md § Paper): ``get_paper_book`` reads the book and never writes it
(no fill, no settlement), shows every price with its time and a missing one as unknown, and leaves tickers he does not
follow out of its lists; the Friday paper review (``engine/paper_review.py``) is written once after the close from the
week's facts, skipped in a week with no closed paper trade, refused when a figure or a hidden ticker is not the facts',
kept for the desk until the next one, and sent as one PAPER REVIEW ping on its own budget. Offline: the scripted model."""
import asyncio
import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, delete, select

from app.ai import copilot, copilot_paper_book, copilot_prompt, copilot_spend, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence
from app.ai.research_job import JOB_TOOLS
from app.database import engine as app_engine
from app.engine import day_read, notification_policy, ntfy, paper_book, paper_review
from app.engine.chart_math import ET
from app.models import Account, CopilotTurn, DayJournalEntry, PaperEvent, PhonePing, Trade

ROTH = uuid.UUID(int=1)
CALL = "NBIS261120C00100000"
OLD_CALL = "NBIS261106C00100000"  # expired Friday Nov 6


def at(day: int, hh: int, mm: int = 0) -> float:
    return datetime(2026, 11, day, hh, mm, tzinfo=ET).timestamp()


FRIDAY = at(13, 16, 50)  # Friday Nov 13, after the close


def q(symbol, bid, ask, now, last=None):
    stamp = int((now - 5) * 1000)
    return SimpleNamespace(symbol=symbol, bid=bid, ask=ask, bid_date=stamp, ask_date=stamp, last=last, mid=None)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    state = SimpleNamespace(quotes={}, marks={}, closes={})
    monkeypatch.setattr(paper_book, "_market_open", lambda now: True)
    monkeypatch.setattr(paper_book, "_live_quotes", lambda symbols: {s: state.quotes[s] for s in symbols if s in state.quotes})
    monkeypatch.setattr(paper_book, "_marks", lambda symbols: {s: state.marks[s] for s in symbols if s in state.marks})
    monkeypatch.setattr(paper_book, "_close_for", lambda symbol, day, now: state.closes.get((symbol, day)))
    monkeypatch.setattr(paper_book, "_close_moment", lambda day: datetime(day.year, day.month, day.day, 16, tzinfo=ET).timestamp())
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth IRA", type="roth_ira", last4="8267", broker="robinhood"))
        session.commit()
        session.state = state
        yield session
    engine.dispose()


def _order(db, now, quotes, **body):
    db.state.quotes = quotes
    return paper_book.open_order(db, {"order_key": uuid.uuid4().hex, **body}, now)["filled"]["position_id"]


def _close(db, now, quotes, position_id):
    db.state.quotes = quotes
    return paper_book.close_order(db, {"position_id": position_id, "order_key": uuid.uuid4().hex}, now)["filled"]


def seed(db):
    """A run from Thursday Nov 5: a stock trade closed last week, an option that expired last Friday and was never
    settled, this week's NBIS call (took its target, +$140.00) and CRWV shares (not followed, -$10.50), MU shares open
    with an old mark, AMD shares open with no price; real trades this week (NBIS -$120.00, OLDX not followed -$60.00)."""
    paper_book.start_run(db, None, False, at(5, 10))
    t = at(5, 10)
    stock = _order(db, t, {"NBIS": q("NBIS", 90.0, 90.1, t, last=90.05)}, symbol="NBIS", instrument="stock", quantity=10)
    t = at(6, 11)
    _close(db, t, {"NBIS": q("NBIS", 92.0, 92.1, t, last=92.0)}, stock)  # +19.00
    t = at(5, 10, 5)
    _order(db, t, {OLD_CALL: q(OLD_CALL, 1.0, 1.1, t), "NBIS": q("NBIS", 90, 90.1, t, last=90.05)}, symbol="NBIS",
           instrument="option", option_type="call", expiry="2026-11-06", strike=100, quantity=1)
    t = at(10, 10)
    call = _order(db, t, {CALL: q(CALL, 3.3, 3.4, t), "NBIS": q("NBIS", 98, 98.1, t, last=98.05)}, symbol="NBIS",
                  instrument="option", option_type="call", expiry="2026-11-20", strike=100, quantity=2, stop=95, target=105,
                  note="reclaim of 98")
    t = at(11, 14)
    _close(db, t, {CALL: q(CALL, 4.1, 4.2, t), "NBIS": q("NBIS", 106, 106.1, t, last=106.0)}, call)  # +140.00
    t = at(10, 10, 30)
    crwv = _order(db, t, {"CRWV": q("CRWV", 120.0, 120.1, t, last=120.05)}, symbol="CRWV", instrument="stock", quantity=5, stop=119)
    t = at(12, 11)
    _close(db, t, {"CRWV": q("CRWV", 118.0, 118.1, t, last=118.0)}, crwv)  # -10.50
    t = at(13, 10)
    _order(db, t, {"MU": q("MU", 90.0, 90.1, t, last=90.05)}, symbol="MU", instrument="stock", quantity=10)
    _order(db, t, {"AMD": q("AMD", 150.0, 150.1, t, last=150.05)}, symbol="AMD", instrument="stock", quantity=1)
    db.state.marks = {"MU": {"last": 91.0, "at": int(at(13, 10, 5))}}
    db.state.closes = {("NBIS", date(2026, 11, 6)): 104.0}
    for ticker, pnl, closed in (("NBIS", -120.0, "2026-11-12T13:00"), ("OLDX", -60.0, "2026-11-12T14:00"), ("NBIS", 500.0, "2026-11-06T13:00")):
        db.add(Trade(account_id=ROTH, ticker=ticker, instrument_type="option", option_type="call", strike=100, expiration=date(2026, 11, 20),
                     contracts=1, avg_entry_premium=300, avg_exit_premium=180, total_premium_paid=300, realized_pnl=pnl,
                     opened_at=datetime.fromisoformat(closed).replace(hour=10), closed_at=datetime.fromisoformat(closed), status="closed"))
    for symbol in ("CRWV", "OLDX"):
        db.add(DayJournalEntry(operation_id=f"f-{symbol}", day=date(2026, 11, 9), kind="follow", text="Not following", symbol=symbol))
    db.commit()


# --------------------------------------------------------------------------- the tool

def test_the_tool_is_offered_where_he_talks_and_never_to_a_background_job():
    assert "get_paper_book" in copilot_tools.TOOL_NAMES and "get_paper_book" in copilot_tools.BOOK_CONTEXT_TOOLS
    assert copilot_tools.PROVENANCE["get_paper_book"][1] == "saved"
    assert copilot_tools.validate("get_paper_book", {}) == {}
    assert copilot_tools.validate("get_paper_book", {"symbol": "nbis"}) == {"symbol": "NBIS"}
    for bad in ({"symbol": "not a ticker"}, {"close": True}, {"symbol": "NBIS", "quantity": 1}):
        with pytest.raises(copilot_tools.ToolInputError):
            copilot_tools.validate("get_paper_book", bad)
    offered = {job: {t["name"] for t in copilot_prompt.TOOLS[job]} for job in copilot_prompt.JOBS}
    assert {job for job, names in offered.items() if "get_paper_book" in names} == {"desk", "telegram"}
    assert "get_paper_book" not in JOB_TOOLS
    assert "read get_paper_book" in copilot_prompt.PROMPTS["desk"] and "never zero" in copilot_prompt.PROMPTS["telegram"]


def test_it_reads_the_book_with_each_prices_time_and_writes_nothing(db):
    seed(db)
    events = len(db.exec(select(PaperEvent)).all())
    view = paper_book.view(db, FRIDAY, settle_expired=False)
    out = copilot_paper_book.compact(view, {"CRWV", "OLDX"}, FRIDAY)
    assert len(db.exec(select(PaperEvent)).all()) == events  # no settlement, no fill
    assert out["state"] == "ok" and out["run"] == {"number": 1, "started": "Nov 5 10:00 AM ET", "starting_cash": 10000.0}
    by = {row["label"]: row for row in out["open"]}
    mu, amd, old = by["MU shares"], by["AMD shares"], by["NBIS $100 Call 11/6/26"]
    # MU: 10 × 91.00 − 901.00 at the 10:05 price, 405 minutes old at 16:50: shown with its time, never as live.
    assert (mu["value"], mu["pnl"], mu["price_at"], mu["price_age_minutes"]) == (910.0, 9.0, "Nov 13 10:05 AM ET", 405)
    assert amd["price"].startswith("none") and "pnl" not in amd  # no price: unknown, never zero
    assert old["past_expiry"].startswith("expired 2026-11-06") and old["price"].startswith("none")
    assert out["account"]["value"] == "unknown: 2 open position(s) have no price yet"
    assert out["account"]["cash"] == round(10000 + 19.0 - 110.0 + 140.0 - 10.5 - 901.0 - 150.1, 2)
    # Closed, newest first; CRWV is not followed: out of the list, in the totals.
    assert [c["label"] for c in out["closed"]] == ["NBIS $100 Call 11/20/26", "NBIS shares"]
    target = out["closed"][0]
    assert (target["realized"], target["ended_kind"], target["stop"], target["target"], target["note"]) == (140.0, "target", 95.0, 105.0, "reclaim of 98")
    assert "CRWV" not in str(out) and out["not_followed_left_out"].startswith("1 paper position")
    assert out["score"]["paper"]["trades"] == 3 and out["score"]["paper"]["pnl"] == 148.5  # 19.00 + 140.00 − 10.50
    assert out["score"]["real"]["trades"] == 3 and out["score"]["real"]["pnl"] == 320.0  # since Nov 5, Webull left out
    assert out["working_orders"].startswith("none")
    only = copilot_paper_book.compact(view, {"CRWV", "OLDX"}, FRIDAY, symbol="MU")
    assert [r["label"] for r in only["open"]] == ["MU shares"] and only["closed"] == [] and "whole run" in only["score"]["note"]
    # The desk's own read does settle it: the copilot's read left that to it.
    assert paper_book.view(db, FRIDAY)["positions"][-1]["label"] != "NBIS $100 Call 11/6/26"


def test_a_book_not_started_and_a_long_book_stay_whole(db):
    assert copilot_paper_book.compact(paper_book.view(db, FRIDAY, settle_expired=False), set(), FRIDAY)["state"] == "none"
    big = {"run": {"number": 1, "started_at": at(2, 10), "starting_cash": 1e4},
           "account": {"cash": 1e4, "collateral": 0, "buying_power": 1e4, "equity": 1e4, "pnl": 0, "prices_at": None, "unpriced": 0},
           "positions": [], "score": {"paper": {"trades": 0, "pnl": 0}, "real": {"trades": 0, "pnl": 0}},
           "closed": [{"label": f"NBIS ${i} Call 11/20/26", "symbol": "NBIS", "quantity": 1, "opened_at": at(3, 10), "closed_at": at(4, 10),
                       "realized": 1.0, "note": "x" * 280, "verdict": {"kind": "early", "text": "Out before the stop or target: stock 99"}}
                      for i in range(50)]}
    out = copilot_paper_book.compact(big, set(), FRIDAY)
    assert len(copilot_tools.bounded(out)) < copilot_tools.MAX_RESULT_CHARS and out["closed_more"] >= 42


def test_replay_and_fixture_answer_and_the_scripted_desk_turn_cites_the_book():
    from app.ai.copilot_replay import ReplayEvidence
    assert ReplayEvidence.get_paper_book(SimpleNamespace(), None)["state"] == "unavailable"
    book = FixtureEvidence().get_paper_book()
    assert book["note"].startswith("SIMULATED") and book["score"]["paper"]["pnl"] == -10.5

    async def turn():
        cfg = copilot.settings()
        return [e async for e in copilot.run_turn([{"role": "user", "content": "How am I doing on paper?"}], None, cfg,
                                                  copilot.FakeAdapter(0), FixtureEvidence(), datetime.fromtimestamp(FRIDAY, ET))]
    events = asyncio.run(turn())
    assert "get_paper_book" in [e["name"] for e in events if e["type"] == "tool"]
    text = "".join(e["delta"] for e in events if e["type"] == "text")
    assert "Took the target" in text and "+140.00" in text


# --------------------------------------------------------------------------- the weekly review

class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


@pytest.fixture
def lab(monkeypatch, tmp_path, db):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("COPILOT_EVIDENCE", "fixture")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(paper_review, "ROOT", tmp_path / "paper_review")
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))

    def read(now):
        return paper_review.facts(db, now)
    monkeypatch.setattr(paper_review, "_facts", read)
    with Session(app_engine) as session:
        session.exec(delete(CopilotTurn))
        session.exec(delete(PhonePing))
        session.commit()
    paper_review.clear()
    yield db
    paper_review.clear()


def test_the_weeks_facts_hold_only_this_weeks_closed_trades_and_keep_hidden_ones_in_the_totals(lab):
    seed(lab)
    f = paper_review.facts(lab, FRIDAY)
    assert f["monday"] == "2026-11-09" and f["paper"]["trades"] == 2 and f["paper"]["pnl"] == 129.5
    assert [c["label"] for c in f["closed"]] == ["NBIS $100 Call 11/20/26"]  # CRWV hidden, last week's NBIS shares out
    assert f["real"]["trades"] == 2 and f["real"]["pnl"] == -180.0 and [r["realized"] for r in f["real_closed"]] == [-120.0]
    text = paper_review.pack(f)
    assert "Paper this week: 2 closed, realised +$129.50; win rate 50%; average winner +$140.00; average loser -$10.50" in text
    assert "Real this week: 2 closed, realised -$180.00" in text
    assert ("- NBIS $100 Call 11/20/26, 2 contracts: in Nov 10 9:59 AM ET, out Nov 11 1:59 PM ET; realised +$140.00; stop 95, "
            "target 105 (stock prices); how it ended: Took the target: stock 106 vs target 105; his note: \"reclaim of 98\"") in text
    assert "- MU shares, 10 shares: in Nov 13 9:59 AM ET; no stop, no target (stock prices); open P&L +$9.00 at the Nov 13 10:05 AM ET price" in text
    assert "AMD shares, 1 share" in text and "no price yet, so its P&L is unknown" in text
    assert "CRWV" not in text and "OLDX" not in text


def test_friday_after_the_close_it_writes_keeps_and_pings_once(lab, monkeypatch):
    seed(lab)
    sent = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    clock = SimpleNamespace(now=at(13, 16, 30))
    reviews = paper_review.PaperReviews(app_engine, Calendar(), clock=lambda: clock.now, spawn=lambda work: work())
    reviews.run()
    assert sent == [] and paper_review.latest() is None  # before 16:45
    clock.now = FRIDAY
    reviews.run()
    shown = paper_review.latest()
    assert shown["day"] == "2026-11-13" and shown["monday"] == "2026-11-09"
    assert shown["text"].startswith("Simulated paper review, not Claude.\nWeek: paper +$129.50 over 2, real -$180.00 over 2.")
    [(title, body, kw)] = sent
    assert title == "PAPER REVIEW · week of Nov 9" and body == shown["text"] and kw["path"] == "/copilot-lab"
    with Session(app_engine) as session:
        [row] = session.exec(select(CopilotTurn)).all()
        [ping] = session.exec(select(PhonePing)).all()
    assert row.kind == "paper_review" and ping.kind == "paper_review" and ping.decision == "sent"
    kept = (paper_review.ROOT / "2026-11-13.json").read_text()
    assert '"state": "sent"' in kept
    # A restart (memory gone) neither writes it again nor sends it again.
    paper_review.clear()
    clock.now = FRIDAY + 600
    again = paper_review.PaperReviews(app_engine, Calendar(), clock=lambda: clock.now, spawn=lambda work: work())
    again.run()
    again.deliver()
    assert len(sent) == 1 and paper_review.latest()["text"] == shown["text"]
    # Shown until the next one: still there on Monday.
    assert paper_review.latest()["day"] == "2026-11-13"


def test_not_on_a_thursday_and_not_while_the_lab_is_off(lab, monkeypatch):
    seed(lab)
    calls = []

    async def write(now):
        calls.append(now)
        return {"state": "skipped"}
    monkeypatch.setattr(paper_review, "write", write)
    paper_review.PaperReviews(app_engine, Calendar(), clock=lambda: at(12, 17), spawn=lambda work: work()).run()
    monkeypatch.setenv("COPILOT_ENABLED", "false")
    paper_review.PaperReviews(app_engine, Calendar(), clock=lambda: FRIDAY, spawn=lambda work: work()).run()
    assert calls == []
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    reviews = paper_review.PaperReviews(app_engine, Calendar(), clock=lambda: FRIDAY, spawn=lambda work: work())
    reviews.run()
    reviews._last_run = 0
    reviews.run()  # once a day
    assert calls == [FRIDAY]


def test_a_week_with_no_closed_paper_trade_is_skipped_with_no_call(lab):
    paper_book.start_run(lab, None, False, at(9, 10))
    out = asyncio.run(paper_review.write(FRIDAY))
    assert out["state"] == "skipped" and paper_review.latest() is None
    with Session(app_engine) as session:
        assert session.exec(select(CopilotTurn)).all() == []


@pytest.mark.parametrize("text,why", [("Week: paper +$999.00 over 2.", "+$999.00"), ("Week: CRWV did the damage.", "do not follow")])
def test_a_figure_or_a_hidden_ticker_the_facts_do_not_hold_is_never_shown(lab, monkeypatch, text, why):
    seed(lab)

    async def run(*args, **kwargs):
        return {"state": "ok", "text": text, "cost_usd": 0.02}
    monkeypatch.setattr(day_read, "_run", run)
    out = asyncio.run(paper_review.write(FRIDAY))
    assert out["state"] == "error" and why in out["message"] and paper_review.latest() is None


def test_a_spent_budget_refuses_it_with_a_zero_cost_row_and_a_second_ask_that_day_runs_nothing(lab, monkeypatch):
    seed(lab)
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 3.85)
    out = asyncio.run(paper_review.write(FRIDAY))
    assert out["state"] == "budget"
    with Session(app_engine) as session:
        [row] = session.exec(select(CopilotTurn)).all()
    assert row.kind == "paper_review" and row.error == "daily_budget" and row.cost_usd == 0
    monkeypatch.setattr(copilot_spend, "spent_today", lambda session=None: 0.0)
    assert asyncio.run(paper_review.write(FRIDAY + 60))["state"] == "done"


def test_its_ping_has_its_own_budget_and_a_send_that_may_have_landed_is_never_resent(lab, monkeypatch):
    seed(lab)
    assert notification_policy.budget("paper_review") == 1 and notification_policy.budget("radar_event") == 4
    attempts = []

    def refused(title, body, **kw):
        attempts.append(title)
        raise ntfy.NtfyError("timed out") from TimeoutError()  # may have reached the phone
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", refused)
    reviews = paper_review.PaperReviews(app_engine, Calendar(), clock=lambda: FRIDAY, spawn=lambda work: work())
    reviews.run()
    reviews.deliver()
    assert len(attempts) == 1 and '"state": "unknown"' in (paper_review.ROOT / "2026-11-13.json").read_text()


def test_the_desks_paper_read_carries_the_newest_review(lab, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.database import get_session
    from app.routers import copilot_paper
    seed(lab)
    asyncio.run(paper_review.write(FRIDAY))
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: lab
    body = TestClient(app).get("/copilot/paper").json()
    assert body["review"]["day"] == "2026-11-13" and body["review"]["text"].startswith("Simulated paper review")
    assert "facts" not in body["review"]


def test_a_second_delivery_pass_during_the_send_never_sends_it_twice(lab, monkeypatch):
    seed(lab)
    sent = []
    reviews = paper_review.PaperReviews(app_engine, Calendar(), clock=lambda: FRIDAY, spawn=lambda work: None)

    def publish(title, body, **kw):
        sent.append(title)
        paper_review.clear()  # as after a restart: the next pass reloads the kept file
        reviews.deliver()  # the monitor's own pass, arriving while this send is in flight
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", publish)
    assert asyncio.run(paper_review.write(FRIDAY))["ping"]["state"] == "pending"
    reviews.deliver()
    assert sent == ["PAPER REVIEW · week of Nov 9"]
