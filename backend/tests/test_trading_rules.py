"""His own trading rules (``app/engine/trading_rules.py``): written once, checked at each entry (paper at its fill, real
when he copies it from the Ticket), never blocking an order, and scored by followed versus broken. An automatic check
that cannot be evaluated says why and is never a pass. Invented numbers, no network."""

from datetime import UTC, date, datetime
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import select

from app.access_manifest import DOMAIN_ROUTES
from app.ai import copilot_paper_book
from app.database import get_session
from app.engine import copilot_plans, desk_sparks, paper_book, trading_rules
from app.models import DeskAccountValue, PaperEvent, Trade, TradingRuleRecord
from app.routers import copilot_paper
from tests.test_paper_book import CALL, CLOSE, NOW, ROTH, db, key, market, q  # noqa: F401 -- fixtures

OPEN = datetime(2026, 11, 13, 14, 30, tzinfo=UTC).timestamp()  # 09:30 New York; NOW is 10:00


@pytest.fixture(autouse=True)
def session(monkeypatch, market):  # noqa: F811
    monkeypatch.setattr(paper_book, "_window", lambda now: ("regular", (int(OPEN), int(CLOSE))))
    monkeypatch.setattr(desk_sparks, "_session", lambda now: (date(2026, 11, 13), "regular", None, (int(OPEN), int(CLOSE))))
    paper_book._checks.clear()
    yield
    paper_book._checks.clear()


RULES = [
    {"text": "Never more than 5% on one trade", "check": {"kind": "max_size_pct", "n": 5}},
    {"text": "Stop before I enter", "check": {"kind": "stop_set"}},
    {"text": "Wait out the first 15 minutes", "check": {"kind": "no_open_minutes", "n": 15}},
    {"text": "", "check": {"kind": "max_open", "n": 2}},
    {"text": "No weeklies", "check": {"kind": "min_dte", "n": 5}},
    {"text": "Only A+ setups"},
]


def rules(db):  # noqa: F811
    return trading_rules.save(db, RULES, NOW - 3600)


def by_text(results):
    return {r["text"]: r for r in results}


def buy(db, now=NOW, **extra):  # noqa: F811
    return paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                      "strike": 100, "quantity": 1, "order_key": key(), **extra}, now)["filled"]


def sell(db, position_id, now):  # noqa: F811
    return paper_book.close_order(db, {"position_id": position_id, "order_key": key()}, now)["filled"]


def test_the_list_keeps_his_words_ids_and_one_check_each(db):  # noqa: F811
    saved = rules(db)
    assert len(saved) == 6 and all(r["id"].startswith("r_") for r in saved)
    assert saved[3]["text"] == "At most 2 open positions"  # an automatic rule left blank reads its check
    assert saved[5]["check"] is None
    edited = trading_rules.save(db, [{**saved[1], "text": "Stop first, always"}, {"text": "  "}], NOW)
    assert edited == [{**saved[1], "text": "Stop first, always"}]  # the id is kept; an empty line is dropped
    assert trading_rules.current(db) == edited
    for bad, why in [([{"text": "x"}] * 9, "Keep it to 8"), ([{"text": "x", "check": {"kind": "vibes"}}], "one of"),
                     ([{"text": "x", "check": {"kind": "max_open", "n": 0}}], "needs N"),
                     ([{"text": "x", "check": {"kind": "min_dte", "n": 2.5}}], "whole number"),
                     ([{"text": "x", "check": {"kind": "min_dte", "n": 0}}], "needs N"),  # a blank N, never "at least 0 days"
                     ([{"text": "x", "check": {"kind": "max_open", "n": None}}], "needs N")]:
        with pytest.raises(trading_rules.RulesError, match=why):
            trading_rules.save(db, bad, NOW)


def test_each_automatic_check_passes_fails_or_says_why_it_cannot(db):  # noqa: F811
    saved = rules(db)
    ctx = trading_rules.paper_context(10_000.0, 1)
    order = {"instrument": "option", "expiry": "2026-11-20", "size": 340.0, "stop": 95.0, "at": NOW}
    got = by_text(trading_rules.evaluate(saved, order, ctx, {saved[5]["id"]: True}))
    assert got["Never more than 5% on one trade"]["status"] == "pass"
    assert got["Never more than 5% on one trade"]["reason"] == "$340.00 is 3.4% of paper cash $10,000.00."
    assert got["Stop before I enter"]["status"] == "pass"
    assert got["Wait out the first 15 minutes"]["status"] == "pass"  # 10:00 is 30 minutes in
    assert got["At most 2 open positions"]["status"] == "pass" and "makes 2 open" in got["At most 2 open positions"]["reason"]
    assert got["No weeklies"]["status"] == "pass" and got["No weeklies"]["reason"] == "7 days to expiry."
    assert got["Only A+ setups"]["status"] == "pass"
    assert trading_rules.outcome(list(got.values())) == "followed"

    early = {**order, "size": 600.0, "stop": None, "at": OPEN + 10 * 60, "expiry": "2026-11-14"}
    got = by_text(trading_rules.evaluate(saved, early, trading_rules.paper_context(10_000.0, 2), {}))
    assert {t: r["status"] for t, r in got.items()} == {
        "Never more than 5% on one trade": "fail", "Stop before I enter": "fail", "Wait out the first 15 minutes": "fail",
        "At most 2 open positions": "fail", "No weeklies": "fail", "Only A+ setups": "fail"}
    assert got["Wait out the first 15 minutes"]["reason"].endswith("10 minutes after the open.")
    assert got["Only A+ setups"]["reason"] == "Not ticked."

    # Can't check is never a pass: no account value, no size, before the open; shares have no expiry.
    blind = {"instrument": "stock", "expiry": None, "size": None, "stop": 95.0, "at": OPEN - 600}
    got = by_text(trading_rules.evaluate(saved, blind, {"account_words": "Can't check: nothing read."}, None))
    assert got["Never more than 5% on one trade"]["status"] == "unknown"
    assert got["Wait out the first 15 minutes"]["status"] == "unknown" and "Before the open" in got["Wait out the first 15 minutes"]["reason"]
    assert got["At most 2 open positions"]["status"] == "unknown"
    assert got["No weeklies"]["status"] == "na"
    assert got["Only A+ setups"]["status"] == "ask"
    assert trading_rules.outcome(list(got.values())) == "unclear"
    got = by_text(trading_rules.evaluate(saved, {**order, "size": 340.0}, {"account_value": None, "account_words": "Can't check: x"}, {}))
    assert got["Never more than 5% on one trade"] == {**got["Never more than 5% on one trade"], "status": "unknown", "reason": "Can't check: x"}


def test_a_paper_fill_keeps_its_checklist_and_a_broken_rule_never_blocks_it(db, market):  # noqa: F811
    saved = rules(db)
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    filled = buy(db, quantity=2, rule_answers={saved[5]["id"]: False, "not-a-rule": True})  # no stop, A+ unticked
    assert filled["cash"] == -680.0
    [event] = db.exec(select(PaperEvent).where(PaperEvent.kind == "open")).all()
    kept = by_text(json.loads(event.data_json)["rules"])
    assert kept["Never more than 5% on one trade"]["reason"] == "$680.00 is 6.8% of paper cash $10,000.00."
    assert kept["Never more than 5% on one trade"]["status"] == "fail"
    assert kept["Stop before I enter"]["status"] == "fail" and kept["Only A+ setups"]["status"] == "fail"
    assert kept["At most 2 open positions"]["reason"] == "This makes 1 open (paper positions and working paper buys)."
    [held] = paper_book.view(db, NOW + 1)["positions"]
    assert held["rules_outcome"] == "broken" and len(held["rules"]) == 6
    # A rule edited later leaves the kept checklist as it was.
    trading_rules.save(db, [], NOW + 2)
    [held] = paper_book.view(db, NOW + 3)["positions"]
    assert held["rules_outcome"] == "broken"


def test_a_paper_limit_is_checked_at_its_fill_against_the_rules_as_placed(db, market):  # noqa: F811
    saved = rules(db)
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    placed = paper_book.place_limit(db, {"action": "open", "symbol": "NBIS", "instrument": "option", "option_type": "call",
                                         "expiry": "2026-11-20", "strike": 100, "quantity": 1, "limit_price": 3.20,
                                         "order_key": key(), "stop": 95, "rule_answers": {saved[5]["id"]: True}}, NOW)
    assert placed["working"]
    trading_rules.save(db, [{"text": "Changed my mind"}], NOW + 30)  # after placing: the order keeps the old list
    market.quotes = {CALL: q(CALL, 3.05, 3.15, now=NOW + 120), "NBIS": q("NBIS", 97, 97.1, last=97.05, now=NOW + 120)}
    paper_book.minute_pass(db, NOW + 120, lambda symbol, at: [])
    [held] = paper_book.view(db, NOW + 121)["positions"]
    got = by_text(held["rules"])
    assert len(got) == 6 and held["rules_outcome"] == "followed"
    assert got["Never more than 5% on one trade"]["reason"] == "$315.00 is 3.2% of paper cash $10,000.00."  # the fill's ask
    assert got["At most 2 open positions"]["reason"].startswith("This makes 1 open")  # the order is this entry, not another
    assert got["Wait out the first 15 minutes"]["reason"] == "10:01 AM ET, 31 minutes after the open."  # the fill's quote, 10:01:55


def test_the_scorecard_splits_closed_trades_followed_versus_broken_and_by_rule(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    before = buy(db)  # entered before he had rules: left out, counted
    saved = rules(db)
    good = buy(db, stop=95, rule_answers={saved[5]["id"]: True})
    bad = buy(db, quantity=2, rule_answers={})
    market.quotes = {CALL: q(CALL, 3.90, 4.00, now=NOW + 60), "NBIS": q("NBIS", 99, 99.1, last=99.05, now=NOW + 60)}
    sell(db, good["position_id"], NOW + 60)  # +50
    sell(db, before["position_id"], NOW + 60)  # +50
    market.quotes = {CALL: q(CALL, 2.90, 3.00, now=NOW + 120), "NBIS": q("NBIS", 96, 96.1, last=96.05, now=NOW + 120)}
    sell(db, bad["position_id"], NOW + 120)  # 2 × (2.90 − 3.40) × 100 = −100
    split = paper_book.view(db, NOW + 121)["score"]["paper"]["rules"]
    assert split["followed"] == {"trades": 1, "pnl": 50.0, "win_rate": 100.0}
    assert split["broken"] == {"trades": 1, "pnl": -100.0, "win_rate": 0.0}
    assert split["unclear"] == {"trades": 0, "pnl": 0, "win_rate": None} and split["unrecorded"] == 1
    stop = next(r for r in split["by_rule"] if r["text"] == "Stop before I enter")
    assert stop["followed"]["pnl"] == 50.0 and stop["broken"]["pnl"] == -100.0
    size = next(r for r in split["by_rule"] if r["text"] == "Never more than 5% on one trade")
    # Size counts against the paper cash at each entry: 340 of 9,660 passes; 680 of 9,320 (7.3%) breaks 5%.
    assert size["followed"] == {"trades": 1, "pnl": 50.0, "win_rate": 100.0} and size["broken"]["trades"] == 1


def test_the_real_side_reads_the_account_line_and_matches_only_through_the_plans_link(db, monkeypatch):  # noqa: F811
    saved = rules(db)
    no_line = trading_rules.check_entry(db, {"side": "real", "instrument": "option", "expiry": "2026-11-20", "size": 500,
                                             "stop": 95, "last4": "8267"}, NOW)
    size = by_text(no_line["results"])["Never more than 5% on one trade"]
    assert size["status"] == "unknown" and "account line has no value" in size["reason"]
    db.add(DeskAccountValue(day="2026-11-13", at=int(NOW - 60), masked="••8267", label="Roth", total_value=20_000.0))
    db.commit()
    got = by_text(trading_rules.check_entry(db, {"side": "real", "instrument": "option", "expiry": "2026-11-20", "size": 500,
                                                 "stop": 95, "last4": "8267"}, NOW)["results"])
    assert got["Never more than 5% on one trade"]["status"] == "pass"
    assert got["Never more than 5% on one trade"]["reason"].startswith("$500.00 is 2.5% of Roth ••8267 at $20,000.00")
    assert got["Only A+ setups"]["status"] == "ask"
    assert by_text(trading_rules.check_entry(db, {"side": "real", "instrument": "option", "size": 500, "last4": None}, NOW)["results"])[
        "Never more than 5% on one trade"]["status"] == "unknown"

    body = {"instrument": "option", "expiry": "2026-11-20", "size": 500, "stop": 95, "last4": "8267", "symbol": "NBIS"}
    for plan in ("inv-closed", "inv-open", "inv-none"):
        out = trading_rules.record_ticket(db, {**body, "investigation_id": plan, "order_key": key(),
                                               "answers": {saved[5]["id"]: plan != "inv-closed"}}, NOW)
        assert out["recorded"]
    closed = Trade(account_id=ROTH, ticker="NBIS", instrument_type="option", contracts=1, avg_entry_premium=5,
                   total_premium_paid=500, realized_pnl=-120, opened_at=datetime(2026, 11, 13, 10, 5), status="closed",
                   closed_at=datetime(2026, 11, 13, 14))
    still = Trade(account_id=ROTH, ticker="NBIS", instrument_type="option", contracts=1, avg_entry_premium=5,
                  total_premium_paid=500, opened_at=datetime(2026, 11, 13, 10, 6))
    db.add(closed)
    db.add(still)
    db.commit()
    monkeypatch.setattr(copilot_plans, "_plans", lambda session: (
        [{"investigation_id": "inv-closed", "trade": closed}, {"investigation_id": "inv-open", "trade": still},
         {"investigation_id": "inv-none", "capture": None}, {"investigation_id": "inv-other", "trade": closed}], {}))
    real = trading_rules.real_split(db, trading_rules.current(db))
    assert (real["checklists"], real["matched"], real["open"], real["unmatched"]) == (3, 1, 1, 1)
    assert real["broken"] == {"trades": 1, "pnl": -120.0, "win_rate": 0.0}  # A+ left unticked on the matched one
    assert real["followed"]["trades"] == 0


def test_routes_are_owner_only_and_the_copilot_read_carries_the_results(db, market, monkeypatch):  # noqa: F811
    for route in ("GET /copilot/rules", "PUT /copilot/rules", "POST /copilot/rules/check", "POST /copilot/rules/ticket"):
        assert route in DOMAIN_ROUTES
    monkeypatch.setattr(copilot_paper, "_settings", lambda: type("S", (), {"enabled": True, "evidence": "live"})())
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    client = TestClient(app)
    saved = client.put("/copilot/rules", json={"rules": [{"text": "Stop first", "check": {"kind": "stop_set"}}, {"text": "A+ only"}]})
    assert saved.status_code == 200, saved.text
    [stop_rule, tick] = saved.json()["rules"]
    assert client.put("/copilot/rules", json={"rules": [{"text": "x", "check": {"kind": "max_open", "n": 99}}]}).status_code == 400
    assert client.get("/copilot/rules").json()["rules"] == [stop_rule, tick]
    checked = client.post("/copilot/rules/check", json={"side": "paper", "instrument": "stock", "size": 100}).json()
    assert [r["status"] for r in checked["results"]] == ["fail", "ask"]
    ticket = client.post("/copilot/rules/ticket", json={"investigation_id": "inv-1", "order_key": key(), "instrument": "option",
                                                        "stop": 95, "answers": {tick["id"]: True}})
    assert ticket.json()["outcome"] == "followed"
    assert len(db.exec(select(TradingRuleRecord).where(TradingRuleRecord.kind == "ticket")).all()) == 1

    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    order = {"action": "open", "symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
             "strike": 100, "quantity": 1, "order_key": key(), "rule_answers": {tick["id"]: True}}
    assert client.post("/copilot/paper/orders", json=order).status_code == 200  # no stop: broken, still filled
    book = client.get("/copilot/paper").json()
    assert book["my_rules"] == [stop_rule, tick] and book["positions"][0]["rules_outcome"] == "broken"
    out = copilot_paper_book.compact(paper_book.view(db, NOW + 1, settle_expired=False), set(), NOW + 1)
    assert "paper_by_my_rules" not in out["score"]  # nothing checked has closed yet: no empty split for the copilot
    assert out["score"]["real_by_my_rules"]["checklists"] == 1 and out["score"]["real_by_my_rules"]["unmatched"] == 1
    assert out["open"][0]["my_rules"] == {"outcome": "broken", "broken": ["Stop first: No stop set."]}
    assert copilot_paper_book.compact(paper_book.view(db, NOW + 1, settle_expired=False), {"NBIS"}, NOW + 1)["open"] == []
