"""The paper challenge (``app/engine/paper_challenge.py``): a $10,000 run whose daily loss limit (3% of the start-of-day
equity, open P&L included) locks paper opens until the next New York trading day, whose 8% drawdown from the peak fails
the run with a 7-day cooldown, and whose +10% target passes it. Every fact is an append-only paper event. No network."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlmodel import select

from app.engine import paper_book, paper_challenge
from app.models import PaperEvent
from tests.test_paper_book import CALL, NOW, db, market, q  # noqa: F401 -- fixtures

MONDAY = datetime(2026, 11, 16, 5, 0, tzinfo=UTC).timestamp()  # Mon Nov 16 00:00 New York


@pytest.fixture
def unlock(monkeypatch):
    monkeypatch.setattr(paper_challenge, "unlock_at", lambda day: MONDAY)


def key():
    return uuid4().hex


def buy_calls(db, qty=2, now=NOW):
    return paper_book.open_order(db, {"symbol": "NBIS", "instrument": "option", "option_type": "call", "expiry": "2026-11-20",
                                      "strike": 100, "quantity": qty, "order_key": key()}, now)["filled"]


def buy_shares(db, qty=100, now=NOW):
    return paper_book.open_order(db, {"symbol": "NBIS", "instrument": "stock", "quantity": qty, "order_key": key()}, now)["filled"]


def quotes(market, now=NOW):
    market.quotes = {CALL: q(CALL, 3.30, 3.40, now=now), "NBIS": q("NBIS", 98.0, 98.1, last=98.05, now=now)}


def kinds(db):
    return [e.kind for e in db.exec(select(PaperEvent).order_by(PaperEvent.recorded_at)).all()]


def test_a_challenge_starts_at_ten_thousand_with_its_rules(db, market):
    paper_book.start_run(db, 2500, False, NOW, challenge=True)  # the challenge is always $10,000
    shown = paper_book.view(db, NOW + 1)
    assert shown["run"]["starting_cash"] == 10000
    c = shown["challenge"]
    assert c["rules"] == {"target_pct": 10.0, "daily_pct": 3.0, "max_dd_pct": 8.0}
    assert c["equity"] == 10000 and c["start_of_day"] == 10000 and c["daily_limit"] == 300.0
    assert c["to_target"] == 1000.0 and c["floor"] == 9200.0 and c["to_floor"] == 800.0 and c["today_pnl"] == 0.0
    assert c["lock"] is None and c["result"] is None and c["fresh"]
    # A plain run has no challenge and records nothing extra.
    paper_book.start_run(db, None, True, NOW + 2)
    assert paper_book.view(db, NOW + 3)["challenge"] is None


def test_open_pnl_exactly_at_the_limit_locks_opens_but_one_cent_short_does_not(db, market, unlock):
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    held = buy_calls(db)  # 2 × 3.40 = $680 out; flat before it, so the day starts at $10,000
    # Mark 1.91: worth $382, equity 9,320 + 382 = 9,702: −$298, inside the $300 limit.
    market.marks = {CALL: {"last": 1.91, "at": NOW + 50}}
    c = paper_book.view(db, NOW + 60)["challenge"]
    assert c["today_pnl"] == -298.0 and c["lock"] is None
    # Mark 1.90: equity 9,700, exactly −$300 = −3% of $10,000: locked.
    market.marks = {CALL: {"last": 1.90, "at": NOW + 110}}
    c = paper_book.view(db, NOW + 120)["challenge"]
    assert c["today_pnl"] == -300.0 and c["lock"]["pnl"] == -300.0 and c["lock"]["limit"] == 300.0
    assert c["lock"]["until"] == MONDAY and c["result"] is None
    with pytest.raises(paper_book.PaperError) as refused:
        buy_calls(db, 1, now=NOW + 130)
    assert refused.value.status == 409 and "Daily loss limit hit" in str(refused.value) and "Mon Nov 16 12:00 AM ET" in str(refused.value)
    # The copilot card's preview and an opening limit are refused too; a close still works.
    with pytest.raises(paper_book.PaperError):
        paper_book.open_order(db, {"symbol": "NBIS", "instrument": "stock", "quantity": 1}, NOW + 130, preview=True)
    with pytest.raises(paper_book.PaperError):
        paper_book.place_limit(db, {"symbol": "NBIS", "instrument": "stock", "quantity": 1, "limit_price": 90,
                                    "order_key": key()}, NOW + 130)
    quotes(market, NOW + 140)
    out = paper_book.close_order(db, {"position_id": held["position_id"], "order_key": key()}, NOW + 140)["filled"]
    assert out["all"]
    assert kinds(db).count("lock") == 1  # one lock for the day, however often it is read


def test_realized_loss_and_open_loss_add_up_to_the_breach_and_cancel_working_opens(db, market, unlock, monkeypatch):
    monkeypatch.setattr(paper_book, "_window", lambda now: ("regular", (int(NOW - 1800), int(NOW + 21600))))
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    first = buy_calls(db)  # −680
    market.quotes = {CALL: q(CALL, 2.40, 2.50, now=NOW + 60), "NBIS": q("NBIS", 96, 96.1, last=96.0, now=NOW + 60)}
    paper_book.close_order(db, {"position_id": first["position_id"], "order_key": key()}, NOW + 60)  # +480: −$200 closed
    quotes(market, NOW + 70)
    buy_calls(db, 1, now=NOW + 70)  # −340, cash 9,460
    # A working opening limit far below the market holds buying power until the lock cancels it.
    market.quotes = {CALL: q(CALL, 3.30, 3.40, now=NOW + 80), "NBIS": q("NBIS", 98.0, 98.1, last=98.05, now=NOW + 80)}
    placed = paper_book.place_limit(db, {"symbol": "NBIS", "instrument": "stock", "quantity": 1, "limit_price": 50,
                                         "order_key": key()}, NOW + 80)
    assert placed["working"] is not None
    # Mark 2.40: worth $240, equity 9,700: −$200 closed and −$100 open = the −$300 limit.
    market.marks = {CALL: {"last": 2.40, "at": NOW + 170}}
    found = paper_challenge.minute(db, paper_book.current_run(db), NOW + 180)
    [ping] = found
    assert ping["source"].startswith("lock:") and ping["title"].startswith("PAPER ·") and "-$300.00" in ping["body"]
    shown = paper_book.view(db, NOW + 190)
    assert shown["challenge"]["lock"] is not None and shown["orders"] == []
    assert shown["account"]["reserved"] == 0.0
    # Pinged within the paper budget once per lock: the same key, which the notification policy sends once.
    assert [p["source"] for p in paper_challenge.minute(db, paper_book.current_run(db), NOW + 240)] == [ping["source"]]


def test_the_lock_lifts_at_midnight_new_york_of_the_next_trading_day(db, market, unlock):
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    held = buy_calls(db)
    market.marks = {CALL: {"last": 1.50, "at": NOW + 50}}
    assert paper_book.view(db, NOW + 60)["challenge"]["lock"] is not None
    quotes(market, NOW + 70)
    paper_book.close_order(db, {"position_id": held["position_id"], "order_key": key()}, NOW + 70)  # flat at the 3.30 bid: 9,980
    market.marks = {}
    saturday = MONDAY - 36 * 3600
    assert paper_book.view(db, saturday)["challenge"]["lock"] is not None  # still locked over the weekend
    with pytest.raises(paper_book.PaperError):
        buy_calls(db, 1, now=MONDAY - 1)
    c = paper_book.view(db, MONDAY)["challenge"]
    assert c["lock"] is None and c["start_of_day"] == 9980.0 and c["daily_limit"] == 299.4  # a new day, a new start
    tuesday_open = MONDAY + 86400 + 9.5 * 3600 + 60
    quotes(market, tuesday_open)
    assert buy_calls(db, 1, now=tuesday_open)["quantity"] == 1


def test_unlock_skips_the_weekend_by_the_market_calendar(monkeypatch):
    from app.engine import desk_sparks
    monkeypatch.setattr(desk_sparks, "_session", lambda now: (None, "closed", None,
                                                              None if datetime.fromtimestamp(now, UTC).weekday() >= 5 else (1, 2)))
    assert paper_challenge.unlock_at(date(2026, 11, 13)) == MONDAY  # Friday → Monday 00:00 New York
    assert paper_challenge.unlock_at(date(2026, 11, 16)) == MONDAY + 86400


def test_an_eight_percent_drawdown_fails_the_run_with_a_seven_day_cooldown(db, market, unlock):
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    buy_shares(db)  # 100 × 98.10: cash $190
    # Up first: 100 × 99.50 + 190 = 10,140, a recorded high.
    market.marks = {"NBIS": {"last": 99.50, "at": NOW + 50}}
    assert paper_book.view(db, NOW + 60)["challenge"]["peak"] == 10140.0
    # 8% under the 10,140 peak is 9,328.80: 100 × 91.38 + 190 = 9,328 fails.
    market.marks = {"NBIS": {"last": 91.38, "at": NOW + 110}}
    c = paper_book.view(db, NOW + 120)["challenge"]
    assert c["result"]["kind"] == "fail" and c["result"]["pct"] == -6.7 and c["lock"] is None
    assert c["result"]["next_run_at"] == NOW + 120 + 7 * 86400
    with pytest.raises(paper_book.PaperError) as refused:
        buy_shares(db, 1, now=NOW + 130)
    assert "failed" in str(refused.value)
    # No new run of any kind for 7 days: a reset is never a free way out.
    for challenge in (True, False):
        with pytest.raises(paper_book.PaperError) as blocked:
            paper_book.start_run(db, None, True, NOW + 7 * 86400 - 1, challenge=challenge)
        assert blocked.value.status == 409 and "Nov 20" in str(blocked.value)
    paper_book.start_run(db, None, True, NOW + 120 + 7 * 86400, challenge=True)
    market.marks = {}
    shown = paper_book.view(db, NOW + 121 + 7 * 86400)
    [old] = shown["earlier"]
    assert old["challenge"] == {"result": "failed", "at": NOW + 120, "pct": -6.7} and old["left_open"] == 1
    assert kinds(db).count("fail") == 1


def test_the_target_passes_the_run_and_a_new_one_starts_at_once(db, market, unlock):
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    buy_shares(db)
    market.marks = {"NBIS": {"last": 108.10, "at": NOW + 50}}  # 10,810 + 190 = 11,000: exactly +10%
    c = paper_book.view(db, NOW + 60)["challenge"]
    assert c["result"]["kind"] == "pass" and c["result"]["pct"] == 10.0 and c["to_target"] == 0.0
    with pytest.raises(paper_book.PaperError) as refused:
        buy_shares(db, 1, now=NOW + 70)
    assert "passed" in str(refused.value)
    paper_book.start_run(db, None, True, NOW + 80, challenge=True)
    assert paper_book.view(db, NOW + 90)["earlier"][0]["challenge"]["result"] == "passed"


def test_stale_prices_are_never_judged_or_read_as_zero(db, market, unlock):
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    buy_calls(db)
    market.marks = {CALL: {"last": 0.50, "at": NOW - 600}}  # a deep loss on a ten-minute-old price
    c = paper_book.view(db, NOW + 60)["challenge"]
    assert not c["fresh"] and c["prices_at"] == NOW - 600 and c["equity"] == 9420.0 and c["lock"] is None
    market.marks = {}
    c = paper_book.view(db, NOW + 60)["challenge"]
    assert c["equity"] is None and c["today_pnl"] is None and c["to_floor"] is None and c["lock"] is None


def test_the_minute_reads_one_quote_when_the_desks_prices_are_stale(db, market, unlock):
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    buy_calls(db)
    market.reads.clear()
    market.quotes = {CALL: q(CALL, 1.80, 2.00, now=NOW + 300)}  # mid 1.90: equity 9,700
    found = paper_challenge.minute(db, paper_book.current_run(db), NOW + 300)
    assert market.reads == [[CALL]] and found and found[0]["source"].startswith("lock:")


def test_a_reset_over_a_running_challenge_is_kept_as_abandoned(db, market):
    paper_book.start_run(db, None, False, NOW, challenge=True)
    quotes(market)
    held = buy_calls(db)
    market.quotes = {CALL: q(CALL, 3.00, 3.10, now=NOW + 60), "NBIS": q("NBIS", 98.0, 98.1, last=98.05, now=NOW + 60)}
    paper_book.close_order(db, {"position_id": held["position_id"], "order_key": key()}, NOW + 60)  # −$80
    paper_book.start_run(db, None, True, NOW + 120, challenge=True)
    [old] = paper_book.view(db, NOW + 130)["earlier"]
    assert old["challenge"] == {"result": "abandoned", "at": NOW + 120, "pct": -0.8}


def test_the_route_starts_a_challenge(db, market, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import get_session
    from app.routers import copilot_paper
    app = FastAPI()
    app.include_router(copilot_paper.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    monkeypatch.setattr(copilot_paper.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    shown = TestClient(app).post("/copilot/paper/runs", json={"challenge": True}).json()
    assert shown["challenge"]["rules"]["daily_pct"] == 3.0 and shown["run"]["starting_cash"] == 10000
