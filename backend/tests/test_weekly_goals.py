"""His weekly goals (``app/engine/weekly_goals.py``): one or two, carried over until changed, with progress computed from
his real trades (Monday to Friday New York; Webull left out) or his paper book, never typed. A stale fill feed or an
unreadable source is shown with why and its time, never as on track. Invented numbers, no network."""

from datetime import UTC, date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import copilot_plans, desk_sparks, gmail_health, paper_book, paper_review, trading_rules, weekly_goals
from app.models import Trade
from app.routers import copilot_paper
from tests.test_paper_book import CALL, CLOSE, NOW, ROTH, WEBULL, db, key, market, q  # noqa: F401 -- fixtures

OPEN = datetime(2026, 11, 13, 14, 30, tzinfo=UTC).timestamp()  # Friday 09:30 New York; NOW is 10:00
MONDAY = date(2026, 11, 9)
LIVE = {"status": "live", "last_import_at": "2026-11-13T14:58:00Z"}


@pytest.fixture(autouse=True)
def session(monkeypatch, market):  # noqa: F811
    monkeypatch.setattr(paper_book, "_window", lambda now: ("regular", (int(OPEN), int(CLOSE))))
    monkeypatch.setattr(desk_sparks, "_session", lambda now: (date(2026, 11, 13), "regular", None, (int(OPEN), int(CLOSE))))
    monkeypatch.setattr(gmail_health, "gmail_health", lambda session: LIVE)
    monkeypatch.setattr(copilot_plans, "_plans", lambda session: ([], {}))
    paper_book._checks.clear()
    yield
    paper_book._checks.clear()


def trade(db, opened, closed=None, pnl=None, account=ROTH):  # noqa: F811
    row = Trade(account_id=account, ticker="NBIS", instrument_type="option", contracts=1, avg_entry_premium=5,
                total_premium_paid=500, opened_at=opened, closed_at=closed, realized_pnl=pnl,
                status="closed" if closed else "open")
    db.add(row)
    db.commit()
    return row


def test_one_or_two_measurable_goals_carry_over_until_changed(db):  # noqa: F811
    assert weekly_goals.current(db) == [] and weekly_goals.desk(db, NOW)["progress"] == []
    last_week = datetime(2026, 11, 5, 15, tzinfo=UTC).timestamp()
    saved = weekly_goals.save(db, [{"kind": "max_loss", "n": 300}, {"kind": "max_trades_day", "n": 5, "book": "paper"}], last_week)
    assert saved == [{"kind": "max_loss", "n": 300, "book": "real"}, {"kind": "max_trades_day", "n": 5, "book": "paper"}]
    assert weekly_goals.desk(db, NOW)["goals"] == saved  # set last week, still this week's
    for bad, why in [([{"kind": "max_loss", "n": 1}] * 3, "Keep it to 2"), ([{"kind": "vibes", "n": 1}], "one of"),
                     ([{"kind": "max_loss", "n": 0}], "whole N"), ([{"kind": "max_trades_day", "n": 2.5}], "whole N"),
                     ([{"kind": "max_loss", "n": True}], "whole N"), ([{"kind": "max_loss", "n": 300, "book": "both"}], "real trades or"),
                     ([{"kind": "max_loss", "n": 300}, {"kind": "max_loss", "n": 200}], "twice"),
                     ([{"kind": "rules_pct", "n": 80}], "Write your rules first")]:
        with pytest.raises(weekly_goals.GoalsError, match=why):
            weekly_goals.save(db, bad, NOW)
    assert next(k for k in weekly_goals.kinds(db) if k["kind"] == "rules_pct")["why_not"].startswith("Write your rules")
    trading_rules.save(db, [{"text": "Stop first", "check": {"kind": "stop_set"}}], NOW - 60)
    assert next(k for k in weekly_goals.kinds(db) if k["kind"] == "rules_pct")["why_not"] is None
    weekly_goals.save(db, [{"kind": "rules_pct", "n": 80}], NOW)
    assert weekly_goals.current(db) == [{"kind": "rules_pct", "n": 80, "book": "real"}]
    # Last week's review reads the goals in force when last week ended, not today's.
    assert [g["kind"] for g in weekly_goals.for_review(db, "2026-11-02", NOW)] == ["max_loss", "max_trades_day"]
    weekly_goals.save(db, [], NOW + 1)  # cleared: only the small control shows
    assert weekly_goals.desk(db, NOW + 2)["goals"] == []


def test_real_progress_counts_this_weeks_trades_only(db):  # noqa: F811
    weekly_goals.save(db, [{"kind": "max_loss", "n": 300}, {"kind": "max_trades_day", "n": 2}], NOW - 3600)
    trade(db, datetime(2026, 11, 6, 10), datetime(2026, 11, 6, 11), -900)  # last week: left out
    trade(db, datetime(2026, 11, 10, 9, 40), datetime(2026, 11, 10, 10), -220.5)
    trade(db, datetime(2026, 11, 10, 10, 5), datetime(2026, 11, 12, 15), 140)
    trade(db, datetime(2026, 11, 10, 11), None, None)  # still open: a trade on Tuesday, no loss yet
    trade(db, datetime(2026, 11, 12, 9, 50), datetime(2026, 11, 12, 10), -1000, account=WEBULL)  # Webull: left out
    [loss, per_day] = weekly_goals.desk(db, NOW)["progress"]
    assert loss["text"] == "max loss $220.50 (goal $300)" and loss["ok"] is True and loss["stale"] is None
    assert per_day["text"] == "most trades in a day 3 (Tue; goal 2)" and per_day["ok"] is False
    trade(db, datetime(2026, 11, 13, 9, 45), datetime(2026, 11, 13, 9, 55), -300.004)
    assert weekly_goals.desk(db, NOW)["progress"][0]["ok"] is True  # exactly the goal, to the cent, is met
    trade(db, datetime(2026, 11, 13, 9, 46), datetime(2026, 11, 13, 9, 56), -301)
    assert weekly_goals.desk(db, NOW)["progress"][0] == {**loss, "text": "max loss $301 (goal $300)", "ok": False}


def test_rules_followed_counts_linked_checklists_and_names_trades_without_one(db, monkeypatch):  # noqa: F811
    saved = trading_rules.save(db, [{"text": "Stop first", "check": {"kind": "stop_set"}}, {"text": "A+ only"}], NOW - 7200)
    weekly_goals.save(db, [{"kind": "rules_pct", "n": 80}], NOW - 3600)
    assert weekly_goals.desk(db, NOW)["progress"][0]["text"] == "rules: no checked trades yet (goal 80%)"
    body = {"instrument": "option", "expiry": "2026-11-20", "symbol": "NBIS"}
    for plan, stop, ticked in (("inv-a", 95, True), ("inv-b", 95, True), ("inv-c", None, True), ("inv-d", 95, True)):
        trading_rules.record_ticket(db, {**body, "stop": stop, "investigation_id": plan, "order_key": key(),
                                         "answers": {saved[1]["id"]: ticked}}, NOW - 600)
    a = trade(db, datetime(2026, 11, 10, 10), datetime(2026, 11, 10, 11), 50)
    b = trade(db, datetime(2026, 11, 11, 10))  # open: its checklist still counts (rules are judged at entry)
    c = trade(db, datetime(2026, 11, 12, 10), datetime(2026, 11, 12, 11), -80)
    old = trade(db, datetime(2026, 11, 5, 10), datetime(2026, 11, 5, 11), 10)  # last week's: left out
    trade(db, datetime(2026, 11, 12, 13))  # no checklist
    monkeypatch.setattr(copilot_plans, "_plans", lambda db: ([
        {"investigation_id": "inv-a", "trade": a}, {"investigation_id": "inv-b", "trade": b},
        {"investigation_id": "inv-c", "trade": c}, {"investigation_id": "inv-d", "trade": old}], {}))
    [got] = weekly_goals.desk(db, NOW)["progress"]
    assert got["text"] == "rules followed 2/3 (67%, goal 80%) · 1 without a checklist" and got["ok"] is False
    assert got["goal"] == "Follow all my rules on 80% of trades"


def test_a_stale_fill_feed_or_an_unreadable_source_is_grey_never_on_track(db, monkeypatch):  # noqa: F811
    weekly_goals.save(db, [{"kind": "max_loss", "n": 300}, {"kind": "max_trades_day", "n": 5, "book": "paper"}], NOW - 3600)
    trade(db, datetime(2026, 11, 10, 9, 40), datetime(2026, 11, 10, 10), -100)
    monkeypatch.setattr(gmail_health, "gmail_health", lambda db: {"status": "down", "last_import_at": "2026-11-12T19:15:00Z"})
    [loss, paper] = weekly_goals.desk(db, NOW)["progress"]
    assert loss["stale"] == "Real trades as of Nov 12, 2:15 PM ET: new fills are not arriving." and loss["ok"] is None
    assert loss["text"] == "max loss $100 (goal $300)"  # the number as last read, never a zero
    assert paper["stale"] is None  # the paper book is the desk's own: never behind the fill feed

    def broken(*_):
        raise RuntimeError("no state file")
    monkeypatch.setattr(gmail_health, "gmail_health", broken)
    assert weekly_goals.desk(db, NOW)["progress"][0]["stale"].startswith("The fill feed's state could not be read")
    monkeypatch.setattr(weekly_goals, "_real_rows", broken)
    [loss, _] = weekly_goals.desk(db, NOW)["progress"]
    assert loss["ok"] is None and loss["stale"] == "Could not be read just now." and "could not be read" in loss["text"]


def test_paper_goals_read_every_live_runs_week(db, market):  # noqa: F811
    trading_rules.save(db, [{"text": "Stop first", "check": {"kind": "stop_set"}}], NOW - 7200)
    weekly_goals.save(db, [{"kind": "rules_pct", "n": 50, "book": "paper"}, {"kind": "max_loss", "n": 50, "book": "paper"}], NOW)
    paper_book.start_run(db, None, False, NOW - 60)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    order = {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20", "strike": 100, "quantity": 1}
    good = paper_book.open_order(db, {**order, "order_key": key(), "stop": 95}, NOW)["filled"]
    paper_book.start_run(db, None, True, NOW + 30)  # a reset mid-week: the first run's week still counts
    paper_book.open_order(db, {**order, "order_key": key()}, NOW + 40)  # no stop: broken
    market.quotes = {CALL: q(CALL, 2.70, 2.80, now=NOW + 60), "NBIS": q("NBIS", 96, 96.1, last=96.05, now=NOW + 60)}
    [rules, loss] = weekly_goals.desk(db, NOW + 61)["progress"]
    assert rules["text"] == "paper rules followed 1/2 (50%, goal 50%)" and rules["ok"] is True
    assert loss["text"] == "paper max loss: no closed trades yet (goal $50)" and loss["ok"] is None
    assert good["cash"] == -340.0


def test_routes_are_owner_only_and_the_paper_read_carries_the_line_and_the_review_row(db, monkeypatch, tmp_path):  # noqa: F811
    assert "PUT /copilot/goals" in DOMAIN_ROUTES
    monkeypatch.setattr(copilot_paper, "_settings", lambda: type("S", (), {"enabled": True, "evidence": "live"})())
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    monkeypatch.setattr(paper_review, "latest", lambda: {"day": "2026-11-06", "monday": "2026-11-02", "at": NOW - 86400 * 7, "text": "Week: ..."})
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    client = TestClient(app)
    assert client.get("/copilot/paper").json()["goals"]["goals"] == []
    weekly_goals.save(db, [{"kind": "max_trades_day", "n": 4}], datetime(2026, 11, 1, 15, tzinfo=UTC).timestamp())
    trade(db, datetime(2026, 11, 3, 10), datetime(2026, 11, 3, 11), -40)
    put = client.put("/copilot/goals", json={"goals": [{"kind": "max_loss", "n": 300}]})
    assert put.status_code == 200, put.text
    assert put.json()["label"] == "This week" and put.json()["progress"][0]["text"] == "max loss: no closed trades yet (goal $300)"
    assert client.put("/copilot/goals", json={"goals": [{"kind": "max_loss", "n": -5}]}).status_code == 400
    book = client.get("/copilot/paper").json()
    assert book["goals"]["goals"] == [{"kind": "max_loss", "n": 300, "book": "real"}]
    # The review's row: last week's goal (set before it ended), measured over last week.
    assert [(g["goal"], g["text"], g["ok"]) for g in book["review"]["goals"]] == [
        ("No more than 4 trades a day", "most trades in a day 1 (Tue; goal 4)", True)]
    saturday = datetime(2026, 11, 14, 15, tzinfo=UTC).timestamp()
    weekend = weekly_goals.desk(db, saturday)
    assert (weekend["label"], weekend["monday"], weekend["progress"]) == ("Next week", "2026-11-16", [])
    assert MONDAY.isoformat() == weekly_goals.desk(db, NOW)["monday"]
