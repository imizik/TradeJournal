"""What's working (``app/engine/whats_working.py``): closed real and paper trades in plain-word buckets with exact sums
that match ``/stats``, bucket edges in New York time, too-few buckets never a verdict, missing facts never zero, the
ticket's paper record line and the Friday review's one leak line. Invented trades, no network."""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import paper_book, paper_review, whats_working as ww
from app.engine.chart_math import ET
from app.models import Account, PaperEvent, PaperRun, Trade
from app.routers import whats_working as route
from app.routers.stats import get_stats

ROTH = uuid.UUID(int=1)
WEBULL = uuid.UUID(int=2)
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=ET).timestamp()  # Wednesday Nov 18 2026, noon New York


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth IRA", type="roth_ira", last4="8267", broker="robinhood"))
        session.add(Account(id=WEBULL, name="Webull", type="webull_cash", last4="0001", broker="webull"))
        session.commit()
        yield session
    engine.dispose()


def real(db, *, opened, closed, pnl, kind="call", expiry=None, account=ROTH, status="closed"):
    """A closed journal trade; ``opened``/``closed`` are New York wall clocks, as the journal keeps them."""
    option = kind in ("call", "put")
    db.add(Trade(account_id=account, ticker="NBIS", instrument_type="option" if option else "stock", contracts=1,
                 option_type=kind if option else None, expiration=expiry, avg_entry_premium=1, total_premium_paid=100,
                 realized_pnl=pnl, opened_at=opened, closed_at=closed, status=status))


def seed_real(db):
    """Six puts entered 09:50 Nov 9-16, 3 DTE, out the next morning: -100 -50 -75 +25 -40 -60 = -300.00.
    Five calls entered 10:15, 10 DTE, out the same day: +100.10 +150 -20 +80 +89.90 = +400.00.
    One 0DTE call at 09:45, out 10:30: +200.00. One call entered exactly 10:30, scratch 0.00 (a loss, as /stats counts it).
    Shares in Friday Nov 13 at 14:00, out Tuesday Nov 17: +12.34. One call with no P&L (missing). One Webull put (left
    out). One old call closed Oct 1 (all time only): +1,000.00."""
    days = [date(2026, 11, d) for d in (9, 10, 11, 12, 13, 16)]
    for day, pnl in zip(days, (-100, -50, -75, 25, -40, -60)):
        opened = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=50)
        nxt = day + timedelta(days=3 if day.weekday() == 4 else 1)
        real(db, opened=opened, closed=datetime.combine(nxt, datetime.min.time()).replace(hour=9, minute=40), pnl=pnl,
             kind="put", expiry=day + timedelta(days=3))
    for day, pnl in zip(days, (100.10, 150, -20, 80, 89.90)):
        opened = datetime.combine(day, datetime.min.time()).replace(hour=10, minute=15)
        real(db, opened=opened, closed=opened + timedelta(hours=2), pnl=pnl, expiry=day + timedelta(days=10))
    real(db, opened=datetime(2026, 11, 17, 9, 45), closed=datetime(2026, 11, 17, 10, 30), pnl=200,
         expiry=date(2026, 11, 17))
    real(db, opened=datetime(2026, 11, 17, 10, 30), closed=datetime(2026, 11, 17, 11, 0), pnl=0,
         expiry=date(2026, 11, 20))
    real(db, opened=datetime(2026, 11, 13, 14, 0), closed=datetime(2026, 11, 17, 15, 0), pnl=12.34, kind="stock")
    real(db, opened=datetime(2026, 11, 17, 11, 0), closed=datetime(2026, 11, 17, 12, 0), pnl=None,
         expiry=date(2026, 11, 20))
    real(db, opened=datetime(2026, 11, 17, 9, 0), closed=datetime(2026, 11, 17, 9, 30), pnl=-999, kind="put",
         expiry=date(2026, 11, 17), account=WEBULL)
    real(db, opened=datetime(2026, 9, 30, 11, 0), closed=datetime(2026, 10, 1, 11, 0), pnl=1000,
         expiry=date(2026, 10, 30), status="expired")
    db.commit()


def by(side, dimension):
    return {b["label"]: b for b in side["dimensions"][dimension]}


# --------------------------------------------------------------------------- edges, New York time

def test_entry_time_edges_are_new_york_wall_clocks():
    at = lambda h, m: datetime(2026, 11, 18, h, m)  # noqa: E731
    assert [ww.entry_time(at(h, m)) for h, m in ((9, 59), (10, 0), (10, 29), (10, 30), (11, 59), (12, 0), (13, 59), (14, 0))] == [
        "Before 10:00", "10:00–10:30", "10:00–10:30", "10:30–12:00", "10:30–12:00", "12:00–14:00", "12:00–14:00", "After 14:00"]
    # A paper fill at 14:59 UTC in November is 09:59 New York (EST), so before 10:00.
    utc = datetime(2026, 11, 18, 14, 59, tzinfo=UTC).timestamp()
    assert ww.entry_time(datetime.fromtimestamp(utc, ET)) == "Before 10:00"
    assert ww.hold(datetime(2026, 11, 13, 15), datetime(2026, 11, 16, 9, 31)) == "Overnight"  # Friday to Monday
    assert ww.hold(datetime(2026, 11, 13, 15), datetime(2026, 11, 17, 9, 31)) == "Multi-day"
    assert ww.hold(datetime(2026, 11, 13, 9), datetime(2026, 11, 13, 15)) == "Same day"
    assert ww.hold(datetime(2026, 11, 13, 9), None) is None
    assert [ww.dte(datetime(2026, 11, 2, 10), date(2026, 11, d)) for d in (2, 3, 4, 9, 10, 30)] == [
        "0–1 days", "0–1 days", "2–7 days", "2–7 days", "8–30 days", "8–30 days"]
    assert ww.dte(datetime(2026, 11, 2, 10), date(2026, 12, 3)) == "Over 30 days"
    assert ww.dte(datetime(2026, 11, 2, 10), None) is None


# --------------------------------------------------------------------------- real: exact sums, as /stats

def test_real_buckets_sum_exactly_and_match_stats(db):
    seed_real(db)
    out = ww.report(db, NOW)
    every = out["windows"]["all"]["real"]
    stats = asyncio.run(get_stats(account="roth_ira", type=None, session=db))  # Webull left out, as here
    assert every["pnl"] == stats["total_pnl"] == 1312.34
    assert every["trades"] == stats["closed_trades"] - 1  # the one with no P&L is missing, not a zero
    assert every["win_rate"] == round(stats["win_rate"] * 100, 1)
    assert every["missing"]["pnl"] == 1
    for dimension in ("kind", "entry_time", "kind_time"):  # every priced trade lands in exactly one bucket
        assert round(sum(b["pnl"] for b in every["dimensions"][dimension]), 2) == every["pnl"]
        assert sum(b["trades"] for b in every["dimensions"][dimension]) == every["trades"]

    recent = out["windows"]["recent"]["real"]
    assert recent["pnl"] == 312.34 and recent["trades"] == 14  # the Oct 1 close is outside the last 30 days
    kinds = by(recent, "kind")
    assert kinds["Puts"] == {"label": "Puts", "trades": 6, "wins": 1, "losses": 5, "pnl": -300.0, "avg_pnl": -50.0,
                             "win_rate": 16.7, "judged": True}
    assert kinds["Calls"]["pnl"] == 600.0 and kinds["Calls"]["trades"] == 7 and kinds["Calls"]["losses"] == 2  # scratch 0.00 is a loss
    assert kinds["Shares"] == {"label": "Shares", "trades": 1, "wins": 1, "losses": 0, "pnl": 12.34, "avg_pnl": 12.34,
                               "win_rate": 100.0, "judged": False}
    times = by(recent, "entry_time")
    assert times["Before 10:00"]["pnl"] == -100.0 and times["Before 10:00"]["trades"] == 7
    assert times["10:00–10:30"]["pnl"] == 400.0 and times["10:30–12:00"]["trades"] == 1
    assert times["After 14:00"]["pnl"] == 12.34
    holds = by(recent, "hold")
    assert holds["Overnight"]["pnl"] == -300.0 and holds["Multi-day"]["pnl"] == 12.34 and holds["Same day"]["trades"] == 7
    dtes = by(recent, "dte")
    assert dtes["2–7 days"]["pnl"] == -300.0 and dtes["8–30 days"]["pnl"] == 400.0 and dtes["0–1 days"]["pnl"] == 200.0
    assert "n/a" not in dtes and sum(b["trades"] for b in dtes.values()) == 13  # shares have no expiry bucket
    assert by(recent, "kind_time")["Puts before 10:00"]["pnl"] == -300.0
    assert "source" not in recent["dimensions"] and "rules" not in recent["dimensions"]  # paper only
    # Half-cent P&L rounds as /stats rounds it, to the cent.
    real(db, opened=datetime(2026, 11, 17, 11, 0), closed=datetime(2026, 11, 17, 12, 0), pnl=0.005, expiry=date(2026, 11, 20))
    real(db, opened=datetime(2026, 11, 17, 11, 0), closed=datetime(2026, 11, 17, 12, 0), pnl=2.67, expiry=date(2026, 11, 20))
    db.commit()
    assert ww.report(db, NOW)["windows"]["all"]["real"]["pnl"] == asyncio.run(get_stats(account="roth_ira", type=None, session=db))["total_pnl"]


def test_top_three_are_only_judged_buckets_and_ties_go_to_the_narrower(db):
    seed_real(db)
    recent = ww.report(db, NOW)["windows"]["recent"]["real"]
    assert all(b["judged"] and b["trades"] >= ww.MIN_TRADES for b in recent["making"] + recent["losing"])
    # The six puts are also all of "Puts", "Overnight" and "2–7 days" but for the 10:30 scratch call: listed once.
    assert [b["label"] for b in recent["losing"]] == ["Puts before 10:00", "2–7 days", "Before 10:00"]
    assert recent["making"][0]["pnl"] == 600.0 and recent["making"][0]["label"] == "Calls"
    assert "Shares" not in [b["label"] for b in recent["making"]]  # +12.34 on one trade: too few to judge


def test_nothing_is_a_zero_when_there_are_no_trades(db):
    out = ww.report(db, NOW)["windows"]["recent"]
    assert out["real"]["trades"] == 0 and out["real"]["avg_pnl"] is None and out["real"]["win_rate"] is None
    assert out["real"]["making"] == [] and out["real"]["losing"] == []
    assert out["paper"]["dimensions"]["source"] == []


# --------------------------------------------------------------------------- paper

def _paper(db, run, *, opened, closed, cash_in, cash_out, instrument="option", option_type="put", expiry="2026-11-20",
           source=None, rules=None, quantity=1):
    pid = uuid.uuid4()
    data = {"symbol": "NBIS", "instrument": instrument, "option_type": option_type if instrument != "stock" else None,
            "expiry": expiry if instrument != "stock" else None, "multiplier": 100 if instrument != "stock" else 1,
            "quantity": quantity, "cash": cash_in, "legs": [], "credit": False, "width": None}
    if source:
        data["source"] = source
    if rules is not None:
        data["rules"] = rules
    db.add(PaperEvent(run_id=run, position_id=pid, kind="open", order_key=uuid.uuid4().hex,
                      effective_at=datetime.fromtimestamp(opened, UTC).replace(tzinfo=None), data_json=json.dumps(data)))
    if closed is not None:
        db.add(PaperEvent(run_id=run, position_id=pid, kind="close", order_key=uuid.uuid4().hex,
                          effective_at=datetime.fromtimestamp(closed, UTC).replace(tzinfo=None),
                          data_json=json.dumps({"quantity": quantity, "cash": cash_out})))


def ny(day, h, m=0):
    return datetime(2026, 11, day, h, m, tzinfo=ET).timestamp()


def seed_paper(db):
    """Two runs. Puts before 10:00: -$140.00, -$95.50, +$60.00 (3 trades). A copilot call 10:10 -> +$210.25 with rules
    followed; a radar put spread at 11:00 -> -$30.00 with rules broken; shares at 14:30 -> +$4.50, no rules recorded;
    one put still open (not counted)."""
    first, second = PaperRun(starting_cash=10_000, started_at=datetime(2026, 11, 1)), PaperRun(starting_cash=10_000, started_at=datetime(2026, 11, 10))
    db.add(first)
    db.add(second)
    db.commit()
    passed, failed = [{"status": "pass"}], [{"status": "fail"}]
    _paper(db, first.id, opened=ny(5, 9, 45), closed=ny(5, 11), cash_in=-340.0, cash_out=200.0, rules=passed)
    _paper(db, first.id, opened=ny(6, 9, 59), closed=ny(6, 10, 30), cash_in=-195.5, cash_out=100.0, rules=passed)
    _paper(db, second.id, opened=ny(16, 9, 31), closed=ny(16, 15), cash_in=-100.0, cash_out=160.0, rules=passed)
    _paper(db, second.id, opened=ny(16, 10, 10), closed=ny(17, 10), cash_in=-289.75, cash_out=500.0, option_type="call",
           source="copilot", rules=passed)
    _paper(db, second.id, opened=ny(16, 11), closed=ny(16, 12), cash_in=-80.0, cash_out=50.0, instrument="spread",
           source="radar", rules=failed)
    _paper(db, second.id, opened=ny(16, 14, 30), closed=ny(16, 15), cash_in=-1000.0, cash_out=1004.5, instrument="stock")
    _paper(db, second.id, opened=ny(17, 9, 40), closed=None, cash_in=-50.0, cash_out=0)
    db.commit()


def test_paper_buckets_whose_idea_and_rules(db):
    seed_paper(db)
    side = ww.report(db, NOW)["windows"]["all"]["paper"]
    assert side["trades"] == 6 and side["pnl"] == 9.25  # -140 -95.5 +60 +210.25 -30 +4.5
    kinds = by(side, "kind")
    assert kinds["Puts"]["pnl"] == -175.5 and kinds["Puts"]["trades"] == 3 and kinds["Puts"]["judged"] is False
    assert kinds["Put spreads"]["pnl"] == -30.0 and kinds["Calls"]["pnl"] == 210.25 and kinds["Shares"]["pnl"] == 4.5
    assert by(side, "kind_time")["Puts before 10:00"]["wins"] == 1 and by(side, "kind_time")["Puts before 10:00"]["losses"] == 2
    sources = by(side, "source")
    assert sources["My ideas"]["trades"] == 4 and sources["Copilot's ideas"]["pnl"] == 210.25 and sources["Radar's ideas"]["pnl"] == -30.0
    rules = by(side, "rules")
    assert rules["Rules followed"]["trades"] == 4 and rules["Rules broken"]["pnl"] == -30.0
    assert side["missing"]["rules"] == 1  # the shares had no rules check: missing, not "followed"
    assert "Rules unclear" not in rules  # none came back unknown here; one that does gets its own bucket
    assert by(side, "hold")["Overnight"]["pnl"] == 210.25
    # The same closed positions and P&L as the paper book's own scorecard split.
    folded = [p for run in db.exec(select(PaperRun)).all()
              for p in paper_book.fold(list(db.exec(select(PaperEvent).where(PaperEvent.run_id == run.id)
                                                    .order_by(PaperEvent.effective_at)).all())) if p["status"] != "open"]
    split = {s["source"]: s for s in paper_book.by_source(folded)}
    assert split["copilot"]["pnl"] == sources["Copilot's ideas"]["pnl"] and split["mine"]["trades"] == sources["My ideas"]["trades"]


def test_the_tickets_paper_record_is_the_option_type_at_this_new_york_time(db):
    seed_paper(db)
    record = ww.paper_record(db, "put", ny(18, 9, 50))
    assert record == {"label": "puts before 10:00", "wins": 1, "losses": 2, "pnl": -175.5, "trades": 3}
    assert ww.paper_record(db, "call", ny(18, 9, 50)) is None  # no paper call entered before 10:00
    assert ww.paper_record(db, "call", ny(18, 10, 5))["label"] == "calls 10:00–10:30"


# --------------------------------------------------------------------------- the Friday review's line

def test_leak_line_names_the_biggest_judged_leak_as_one_paper_change(db):
    assert ww.leak_line(db, NOW).startswith("Biggest leak: none with 5+ real trades in the last 30 days")
    seed_real(db)
    line = ww.leak_line(db, NOW)
    assert line == ("Try: no puts before 10:00 next week, on paper. (Biggest real leak, last 30 days: Puts before 10:00, "
                    "6 trades, 1W 5L, -$300.00.)")


def test_the_review_carries_the_leak_line_last_and_stands_without_it():
    found = {"day": "2026-11-20", "monday": "2026-11-16"}
    entry = paper_review._entry(found, 0.0, "Review.", 0.0, "", ["QQQ overnight: x"], "Try: no puts next week, on paper.")
    assert entry["text"].splitlines()[-1] == "Try: no puts next week, on paper."
    assert paper_review._entry(found, 0.0, "Review.", 0.0, "", [], None)["text"] == "Review."


# --------------------------------------------------------------------------- the routes

def test_routes_are_owner_only_refuse_while_off_and_read(db, monkeypatch):
    for r in ("GET /copilot/desk/whats-working", "GET /copilot/desk/whats-working/record"):
        assert r in DOMAIN_ROUTES
    seed_real(db)
    seed_paper(db)
    enabled = {"on": False}
    monkeypatch.setattr(route.copilot, "settings", lambda: type("S", (), {"enabled": enabled["on"]})())
    monkeypatch.setattr(route, "_now", lambda: ny(18, 9, 50))
    app = FastAPI()
    app.include_router(route.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    client = TestClient(app)
    assert client.get("/copilot/desk/whats-working").status_code == 503
    enabled["on"] = True
    body = client.get("/copilot/desk/whats-working").json()
    assert body["windows"]["all"]["real"]["pnl"] == 1312.34 and body["min_trades"] == 5
    assert client.get("/copilot/desk/whats-working/record", params={"option_type": "put"}).json()["record"]["trades"] == 3
    assert client.get("/copilot/desk/whats-working/record", params={"option_type": "spread"}).status_code == 422


def test_whats_working_stays_in_this_database():
    root = Path(__file__).resolve().parents[1]
    for path in ("app/engine/whats_working.py", "app/routers/whats_working.py"):
        text = (root / path).read_text()
        assert "robinhood" not in text.lower().replace("no robinhood", "") and "tradier" not in text.lower()


def test_the_review_stands_when_the_leak_line_cannot_be_read(monkeypatch):
    def broken(db, now):
        raise RuntimeError("journal unreadable")
    monkeypatch.setattr(ww, "leak_line", broken)
    assert paper_review._leak_line(NOW) is None
