"""His paper book's Robinhood-like orders (``app/engine/paper_book.py``, ``app/engine/paper_runner.py``): day limit
orders that hold buying power, fill at the ask (bid) only on a fresh quote that crosses, and end at the close or on a
cancel; a per-position switch that closes at the stop or target on the first completed 1-minute bar that touches it;
a touch with the switch off is told, never acted on; one PAPER ping per event on its own budget; paper marks on the
desk chart. Invented numbers, no network."""

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import select

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import notification_policy, paper_book, paper_runner
from app.models import PaperEvent, PhonePing
from app.routers import copilot_paper
from tests.test_paper_book import CALL, CLOSE, NOW, P90, P95, db, key, market, q  # noqa: F401 -- fixtures

OPEN = datetime(2026, 11, 13, 14, 30, tzinfo=UTC).timestamp()  # 09:30 New York


@pytest.fixture(autouse=True)
def session(monkeypatch, market):  # noqa: F811
    """The regular session from 09:30 to 16:00 (``phase`` can be set), and no check kept from another test."""
    market.phase = "regular"
    monkeypatch.setattr(paper_book, "_window", lambda now: (market.phase, (int(OPEN), int(CLOSE))))
    paper_book._checks.clear()
    yield
    paper_book._checks.clear()


def limit(db, price, qty=2, now=NOW, **extra):  # noqa: F811
    body = {"action": "open", "symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
            "strike": 100, "quantity": qty, "limit_price": price, "order_key": key(), **extra}
    return paper_book.place_limit(db, body, now)


def bar(start, low, high):
    return {"time": int(start), "end_time": int(start) + 60, "open": (low + high) / 2, "high": high, "low": low,
            "close": (low + high) / 2, "volume": 1000}


def passes(db, now, bars=()):  # noqa: F811
    return paper_book.minute_pass(db, now, lambda symbol, at: list(bars))


def test_a_buy_limit_holds_buying_power_and_fills_at_the_ask_only_when_a_fresh_ask_reaches_it(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    placed = limit(db, 3.20, stop=95, target=105)
    assert placed["filled"] is None and placed["working"]["reserve"] == 640.0  # 3.20 × 100 × 2
    assert placed["working"]["expires_at"] == CLOSE
    book = paper_book.view(db, NOW + 1)
    assert book["account"]["buying_power"] == 9360.0 and book["account"]["reserved"] == 640.0 and book["account"]["cash"] == 10000.0
    [working] = book["orders"]
    assert working["limit"] == 3.20 and working["check"]["natural"] == 3.40 and working["check"]["quoted_at"] == NOW - 5
    # A crossing ask too old to be live never fills; the order keeps working and shows that quote's time.
    market.quotes = {CALL: q(CALL, 3.00, 3.10, age=600, now=NOW + 60), "NBIS": q("NBIS", 97, 97.1, last=97.05, now=NOW + 60)}
    assert passes(db, NOW + 60) == []
    [working] = paper_book.view(db, NOW + 61)["orders"]
    assert "not live" in working["check"]["issue"] and working["check"]["quoted_at"] == NOW + 60 - 600
    # A fresh ask at 3.15 fills at 3.15 (not the limit): 315 × 2 = 630; the hold is released.
    market.quotes = {CALL: q(CALL, 3.05, 3.15, now=NOW + 120), "NBIS": q("NBIS", 97, 97.1, last=97.05, now=NOW + 120)}
    [told] = passes(db, NOW + 120)
    assert told["filled"]["cash"] == -630.0 and told["filled"]["position_id"] == placed["working"]["id"]
    assert told["title"] == "PAPER · NBIS limit filled" and told["body"].startswith("Paper, not real money. Bought 2 × NBIS $100 Call 11/20/26 at 3.15 (the ask)")
    assert "your limit 3.20. Cost $630.00." in told["body"]
    book = paper_book.view(db, NOW + 121)
    assert book["orders"] == [] and book["account"]["cash"] == 9370.0 and book["account"]["buying_power"] == 9370.0
    [held] = book["positions"]
    assert (held["stop"], held["target"], held["auto"], held["remaining"]) == (95, 105, False, 2)
    assert passes(db, NOW + 180) == []  # filled once


def test_a_marketable_limit_fills_at_once_and_a_double_tap_places_one_order(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    tap = key()
    first = limit(db, 3.50, order_key=tap)
    assert first["working"] is None and first["filled"]["cash"] == -680.0
    assert limit(db, 3.50, order_key=tap)["duplicate"]
    assert len(db.exec(select(PaperEvent).where(PaperEvent.kind == "order")).all()) == 1


def test_a_day_order_ends_at_the_close_a_cancel_ends_it_and_neither_can_fill_after(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    market.open, market.phase = False, "pre"
    early = limit(db, 2.00, now=OPEN - 3600)  # 08:30: a day order placed before the open works through today
    assert early["working"]["expires_at"] == CLOSE and early["filled"] is None and market.reads == []
    market.open, market.phase = True, "regular"
    other = limit(db, 2.10)
    assert paper_book.view(db, NOW)["account"]["reserved"] == 820.0
    paper_book.cancel_order(db, {"order_id": other["working"]["id"]}, NOW + 30)
    with pytest.raises(paper_book.PaperError) as again:
        paper_book.cancel_order(db, {"order_id": other["working"]["id"]}, NOW + 31)
    assert again.value.status == 409
    book = paper_book.view(db, NOW + 40)
    assert [o["id"] for o in book["orders"]] == [early["working"]["id"]] and book["account"]["reserved"] == 400.0
    # The close: the order lapses at 16:00 and its hold is released; a crossing quote after that fills nothing.
    market.open, market.phase = False, "post"
    book = paper_book.view(db, CLOSE + 5)
    assert book["orders"] == [] and book["account"]["buying_power"] == 10000.0
    [lapse] = db.exec(select(PaperEvent).where(PaperEvent.kind == "lapse")).all()
    assert lapse.effective_at == datetime.fromtimestamp(CLOSE, UTC).replace(tzinfo=None)
    with pytest.raises(paper_book.PaperError, match="day order"):
        limit(db, 2.00, now=CLOSE + 60)
    market.open, market.phase = True, "regular"
    market.quotes = {CALL: q(CALL, 1.00, 1.10, now=CLOSE - 30), "NBIS": q("NBIS", 90, 90.1, now=CLOSE - 30)}
    assert passes(db, CLOSE - 30) == []
    assert db.exec(select(PaperEvent).where(PaperEvent.kind == "open")).all() == []


def test_a_limit_it_cannot_afford_or_a_spread_limit_past_its_width_is_refused(db, market):  # noqa: F811
    paper_book.start_run(db, 1000, False, NOW)
    with pytest.raises(paper_book.PaperError, match="holds \\$1,200.00 and you have \\$1,000.00"):
        limit(db, 3.00, qty=4)
    limit(db, 3.00, qty=3)  # $900 held
    with pytest.raises(paper_book.PaperError, match="you have \\$100.00"):
        limit(db, 1.00, qty=2)
    market.quotes = {CALL: q(CALL, 0.50, 0.60), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    with pytest.raises(paper_book.PaperError, match="Not enough paper buying power"):  # a market order counts the hold too
        paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                   "strike": 100, "quantity": 2, "order_key": key()}, NOW)
    with pytest.raises(paper_book.PaperError, match="5-wide spread"):
        paper_book.place_limit(db, {"action": "open", "symbol": "NBIS", "instrument": "spread", "option_type": "put", "expiry": "2026-11-20",
                                    "long_strike": 90, "short_strike": 95, "quantity": 1, "limit_price": 5, "order_key": key()}, NOW)


def test_a_credit_spread_limit_holds_width_less_credit_and_fills_when_the_natural_credit_reaches_it(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {P95: q(P95, 1.80, 1.90), P90: q(P90, 0.60, 0.70), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    body = {"action": "open", "symbol": "NBIS", "instrument": "spread", "option_type": "put", "expiry": "2026-11-20",
            "long_strike": 90, "short_strike": 95, "quantity": 2, "limit_price": 1.25}
    placed = paper_book.place_limit(db, {**body, "order_key": key()}, NOW)  # natural credit 1.80 − 0.70 = 1.10: works
    assert placed["filled"] is None and placed["working"]["reserve"] == 750.0  # (5 − 1.25) × 100 × 2
    market.quotes = {P95: q(P95, 2.00, 2.10, now=NOW + 60), P90: q(P90, 0.65, 0.70, now=NOW + 60), "NBIS": q("NBIS", 97, 97.1, last=97.0, now=NOW + 60)}
    [told] = passes(db, NOW + 60)  # 2.00 − 0.70 = 1.30 ≥ 1.25: filled at the natural credit
    assert told["filled"]["per_share"] == 1.3 and told["filled"]["cash"] == 260.0
    assert "Opened 2 × NBIS" in told["body"] and "1.30 net credit" in told["body"]
    book = paper_book.view(db, NOW + 61)
    assert book["account"] == {**book["account"], "cash": 10260.0, "collateral": 1000.0, "reserved": 0.0, "buying_power": 9260.0}


def test_a_sell_limit_holds_its_contracts_and_fills_at_the_bid_and_an_orphan_ends(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    opened = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                        "strike": 100, "quantity": 3, "order_key": key()}, NOW)["filled"]
    sell = paper_book.place_limit(db, {"action": "close", "position_id": opened["position_id"], "quantity": 2, "limit_price": 4.00,
                                       "order_key": key()}, NOW + 10)
    assert sell["working"]["reserve"] == 0.0 and sell["filled"] is None
    with pytest.raises(paper_book.PaperError, match="no more than|whole number from 1 to 1"):
        paper_book.close_order(db, {"position_id": opened["position_id"], "quantity": 2, "order_key": key()}, NOW + 20)
    assert paper_book.view(db, NOW + 21)["positions"][0]["held"] == 2
    market.quotes = {CALL: q(CALL, 4.05, 4.20, now=NOW + 60), "NBIS": q("NBIS", 101, 101.1, last=101.05, now=NOW + 60)}
    [told] = passes(db, NOW + 60)
    assert told["filled"]["cash"] == 810.0 and told["filled"]["pnl"] == 130.0  # (4.05 − 3.40) × 100 × 2
    assert "Sold 2 × NBIS $100 Call 11/20/26 at 4.05 (the bid)" in told["body"] and "made $130.00" in told["body"]
    # A sell limit for the last one, then he closes it by hand: the order ends with the position.
    last = paper_book.place_limit(db, {"action": "close", "position_id": opened["position_id"], "limit_price": 9.00, "order_key": key()}, NOW + 70)
    with pytest.raises(paper_book.PaperError, match="held for a working limit"):
        paper_book.close_order(db, {"position_id": opened["position_id"], "order_key": key()}, NOW + 80)
    paper_book.cancel_order(db, {"order_id": last["working"]["id"]}, NOW + 81)
    paper_book.close_order(db, {"position_id": opened["position_id"], "order_key": key()}, NOW + 90)
    assert paper_book.view(db, NOW + 91)["orders"] == []


def test_with_the_switch_off_a_touch_is_told_once_per_level_and_nothing_closes(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    filled = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                        "strike": 100, "quantity": 1, "stop": 95, "target": 105, "order_key": key()}, NOW)["filled"]
    bars = [bar(NOW - 60, 97, 98.5), bar(NOW, 96, 98), bar(NOW + 60, 94.8, 96)]  # the entry minute does not count
    assert passes(db, NOW + 60 + 29, bars) == []  # the touching bar is not complete past its lateness yet
    [told] = passes(db, NOW + 120 + 31, bars)
    assert told["title"] == "PAPER · NBIS touched your stop"
    assert told["body"] == ("Paper, not real money. NBIS touched your stop 95.00 (the 10:01 AM ET bar's low 94.80). "
                            "Nothing was closed: Close automatically is off for NBIS $100 Call 11/20/26.")
    assert passes(db, NOW + 180 + 31, bars) == []  # once per level
    book = paper_book.view(db, NOW + 240)
    [held] = book["positions"]
    assert held["remaining"] == 1 and held["touched"] == {"stop": NOW + 120} and held["id"] == filled["position_id"]
    # A target touch noticed long after its bar is recorded without a ping.
    late = bars + [bar(NOW + 120, 104, 105.5)]
    assert passes(db, NOW + 120 + 60 * 20, late) == []
    assert paper_book.view(db, NOW + 2000)["positions"][0]["touched"] == {"stop": NOW + 120, "target": NOW + 180}


def test_with_the_switch_on_the_first_touch_after_it_sells_at_the_next_fresh_bid_graded_auto(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    filled = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                        "strike": 100, "quantity": 2, "stop": 95, "target": 105, "order_key": key()}, NOW)["filled"]
    pid = filled["position_id"]
    assert paper_book.set_auto(db, {"position_id": pid, "on": True, "order_key": key()}, NOW + 200) == {"auto": True}
    # A touch before the switch does not count; the first bar after it touching both the target and the stop is the stop.
    bars = [bar(NOW + 60, 94, 96), bar(NOW + 240, 94.5, 105.5)]
    market.quotes = {CALL: q(CALL, 2.10, 2.20, age=90, now=NOW + 331), "NBIS": q("NBIS", 95, 95.1, last=95.0, now=NOW + 331)}
    assert passes(db, NOW + 331, bars) == []  # triggered, but the quote is from before the bar ended: wait
    [trigger] = db.exec(select(PaperEvent).where(PaperEvent.kind == "trigger")).all()
    assert '"level": "stop"' in trigger.data_json
    assert paper_book.view(db, NOW + 332)["positions"][0]["exiting"] is True
    market.quotes = {CALL: q(CALL, 2.00, 2.10, now=NOW + 391), "NBIS": q("NBIS", 94.9, 95.0, last=94.95, now=NOW + 391)}
    [told] = passes(db, NOW + 391, bars)
    assert told["title"] == "PAPER · NBIS auto exit at the stop"
    assert told["filled"]["cash"] == 400.0 and told["filled"]["pnl"] == -280.0  # (2.00 − 3.40) × 100 × 2
    assert "Sold 2 × NBIS $100 Call 11/20/26 at 2.00 (the bid)" in told["body"] and "lost $280.00" in told["body"]
    [closed] = paper_book.view(db, NOW + 400)["closed"]
    assert closed["verdict"] == {"kind": "stop", "auto": True, "text": "Auto exit at the stop: the stock touched 95; out with the stock at 94.95"}
    assert passes(db, NOW + 451, bars) == []


def test_switching_off_before_the_sell_cancels_the_automatic_exit(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    pid = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                     "strike": 100, "quantity": 1, "target": 105, "order_key": key()}, NOW)["filled"]["position_id"]
    paper_book.set_auto(db, {"position_id": pid, "on": True, "order_key": key()}, NOW + 10)
    bars = [bar(NOW + 60, 104, 105.2)]
    market.quotes = {}
    assert passes(db, NOW + 151, bars) == []  # triggered at the target; no quote
    paper_book.set_auto(db, {"position_id": pid, "on": False, "order_key": key()}, NOW + 160)
    market.quotes = {CALL: q(CALL, 6.0, 6.1, now=NOW + 211), "NBIS": q("NBIS", 105, 105.1, now=NOW + 211)}
    [told] = passes(db, NOW + 211, bars)  # off: no exit; the target it touched is told instead, once
    assert told["title"] == "PAPER · NBIS touched your target" and "Nothing was closed" in told["body"]
    [held] = paper_book.view(db, NOW + 212)["positions"]
    assert held["remaining"] == 1 and not held["auto"] and not held["exiting"]
    with pytest.raises(paper_book.PaperError, match="no stop or target"):
        other = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "stock", "quantity": 1, "order_key": key()}, NOW + 211)
        paper_book.set_auto(db, {"position_id": other["filled"]["position_id"], "on": True, "order_key": key()}, NOW + 212)


def test_a_paper_ping_goes_once_on_its_own_budget_and_a_hidden_ticker_stays_silent(db, monkeypatch):  # noqa: F811
    sent = []
    runner = paper_runner.PaperRunner(None, send=lambda title, body, path: sent.append((title, body, path)))
    monkeypatch.setenv("ALERT_POLICY_ENABLED", "true")
    monkeypatch.delenv("PING_BUDGET_PAPER", raising=False)
    for i in range(8):
        runner.ping(db, {"source": f"fill:{i}", "symbol": "NBIS", "title": "PAPER · NBIS limit filled", "body": "Paper, not real money."}, NOW + i)
    runner.ping(db, {"source": "fill:0", "symbol": "NBIS", "title": "PAPER · NBIS limit filled", "body": "again"}, NOW + 20)
    assert len(sent) == 6 + 1  # six a day; a retry of the first is the same decision, sent again only if its send failed
    rows = db.exec(select(PhonePing).where(PhonePing.sender == "paper")).all()
    assert len(rows) == 8 and sum(r.decision == "over_cap" for r in rows) == 2
    assert all(r.kind == "paper" for r in rows)
    assert notification_policy.budget("paper") == 6 and notification_policy.rank("paper") > notification_policy.rank("research")
    monkeypatch.setattr("app.engine.day_journal.quiet", lambda session: {"HIDE"})
    runner.ping(db, {"source": "touch:x", "symbol": "HIDE", "title": "PAPER · HIDE touched your stop", "body": "x"}, NOW + 30)
    assert db.exec(select(PhonePing).where(PhonePing.source_id == "touch:x")).one().decision == "not_followed"
    assert len(sent) == 7


def test_paper_entries_and_exits_are_chart_marks_at_the_stocks_price(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    pid = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                     "strike": 100, "quantity": 1, "order_key": key()}, NOW)["filled"]["position_id"]
    market.quotes = {CALL: q(CALL, 3.90, 4.00, now=NOW + 60), "NBIS": q("NBIS", 99, 99.1, last=99.0, now=NOW + 60)}
    paper_book.close_order(db, {"position_id": pid, "order_key": key()}, NOW + 60)
    marks = paper_book.chart_marks(db, "NBIS", NOW - 600)
    assert [(m["kind"], m["side"], m["price"], m["at"]) for m in marks] == [("paper", "buy", 98.05, int(NOW - 5)), ("paper", "sell", 99.0, int(NOW + 55))]
    assert marks[0]["text"] == "Paper: Bought 1 × NBIS $100 Call 11/20/26 at 3.40 · NBIS 98.05"
    assert paper_book.chart_marks(db, "AAPL", NOW - 600) == [] and paper_book.chart_marks(db, "NBIS", NOW + 600) == []


def test_the_new_routes_are_owner_only_and_work(db, market, monkeypatch):  # noqa: F811
    for route in ("POST /copilot/paper/orders/cancel", "POST /copilot/paper/auto"):
        assert route in DOMAIN_ROUTES
    monkeypatch.setattr(copilot_paper.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="live"))
    monkeypatch.setattr(copilot_paper.time, "time", lambda: NOW)
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as client:
        client.post("/copilot/paper/runs", json={})
        market.quotes = {CALL: q(CALL, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
        order = {"action": "open", "order_type": "limit", "limit_price": 3.0, "symbol": "NBIS", "instrument": "option",
                 "option_type": "call", "expiry": "2026-11-20", "strike": 100, "quantity": 1}
        preview = client.post("/copilot/paper/orders", json={**order, "preview": True}).json()["preview"]
        assert preview["reserve"] == 300.0 and preview["buying_power_after"] == 9700.0
        placed = client.post("/copilot/paper/orders", json={**order, "order_key": key()}).json()
        assert placed["working"]["limit"] == 3.0
        assert client.get("/copilot/paper").json()["orders"][0]["id"] == placed["working"]["id"]
        assert client.post("/copilot/paper/orders/cancel", json={"order_id": placed["working"]["id"]}).json() == {"canceled": placed["working"]["id"]}
        assert client.post("/copilot/paper/orders/cancel", json={"order_id": placed["working"]["id"]}).status_code == 409
        filled = client.post("/copilot/paper/orders", json={**order, "order_type": "market", "stop": 95, "order_key": key()}).json()["filled"]
        on = client.post("/copilot/paper/auto", json={"position_id": filled["position_id"], "on": True, "order_key": key()})
        assert on.status_code == 200 and on.json() == {"auto": True}
        assert client.get("/copilot/paper").json()["positions"][0]["auto"] is True



def test_a_quote_from_before_the_open_crossed_legs_or_an_expired_contract_never_act(db, market):  # noqa: F811
    paper_book.start_run(db, None, False, NOW)
    # A limit working at the open: a quote last updated at 09:29 is within two minutes but from before the bell.
    market.open, market.phase = False, "pre"
    limit(db, 3.50, now=OPEN - 600)
    market.open, market.phase = True, "regular"
    market.quotes = {CALL: q(CALL, 3.30, 3.40, now=OPEN - 60, age=0), "NBIS": q("NBIS", 98.0, 98.1, now=OPEN - 60, age=0)}
    assert passes(db, OPEN + 35) == []
    market.quotes = {CALL: q(CALL, 3.30, 3.40, now=OPEN + 60, age=0), "NBIS": q("NBIS", 98.0, 98.1, now=OPEN + 60, age=0)}
    assert len(passes(db, OPEN + 95)) == 1
    # Buying back a credit spread on crossed legs (the sold leg's ask below the bought leg's bid) is no real market.
    market.quotes = {P95: q(P95, 1.80, 1.90), P90: q(P90, 0.60, 0.70), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    spread = paper_book.open_order(db, {"symbol": "NBIS", "instrument": "spread", "option_type": "put", "expiry": "2026-11-20",
                                        "long_strike": 90, "short_strike": 95, "quantity": 1, "order_key": key()}, NOW)["filled"]
    market.quotes = {P95: q(P95, 0.40, 0.50, now=NOW + 60), P90: q(P90, 0.60, 0.70, now=NOW + 60), "NBIS": q("NBIS", 99, 99.1, now=NOW + 60)}
    with pytest.raises(paper_book.PaperError, match="quotes are off"):
        paper_book.close_order(db, {"position_id": spread["position_id"], "order_key": key()}, NOW + 60)
    paper_book.place_limit(db, {"action": "close", "position_id": spread["position_id"], "limit_price": 0.05, "order_key": key()}, NOW + 60)
    assert [o["side"] for o in paper_book.view(db, NOW + 61)["orders"]] == ["close"]  # still working, nothing booked
    # A contract past its expiry, not yet settled, is never watched or pinged.
    expired = "NBIS261113C00100000"
    market.quotes = {expired: q(expired, 3.30, 3.40), "NBIS": q("NBIS", 98.0, 98.1, last=98.05)}
    paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-13",
                               "strike": 100, "quantity": 1, "stop": 95, "order_key": key()}, NOW)
    monday = NOW + 3 * 86400
    market.quotes = {}
    assert passes(db, monday + 120 + 31, [bar(monday + 60, 94, 96)]) == []
