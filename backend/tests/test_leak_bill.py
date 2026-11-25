"""The Sunday leak bill (app/engine/leak_bill.py): what breaking the leak rules cost over the week's long option trades."""
from datetime import date, datetime
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import leak_bill, notification_policy
from app.engine.chart_math import ET
from app.models import Account, Fill, Trade, TradeFill

ROTH = uuid.UUID("00000000-0000-4000-8000-000000000001")
SUNDAY = datetime(2026, 11, 22, 18, 5, tzinfo=ET).timestamp()
TUE, WED = date(2026, 11, 17), date(2026, 11, 18)


def ny(hour: int, minute: int = 0, day: int = 17) -> datetime:
    return datetime(2026, 11, day, hour, minute)


def bar(hour: int, minute: int, close: float, day: int = 17) -> dict:
    """A minute bar at a New York (EST) time; ``close`` is per share, as the provider sends it."""
    return {"t": f"2026-11-{day}T{hour + 5:02d}:{minute:02d}:00Z", "c": close}


def buy(qty, price, at) -> dict:
    return {"id": uuid.uuid4(), "role": "entry", "side": "buy_to_open", "contracts": qty, "price": price, "executed_at": at}


def sell(qty, price, at) -> dict:
    return {"id": uuid.uuid4(), "role": "exit", "side": "sell_to_close", "contracts": qty, "price": price, "executed_at": at}


def test_a_short_dated_option_down_30_percent_after_an_hour_is_cut_there():
    fills = [buy(2, 200, ny(10)), sell(2, 60, ny(14))]
    bars = [bar(10, 30, 1.20), bar(11, 5, 1.41), bar(11, 6, 1.30), bar(11, 7, 0.90)]  # deep red before the hour, -29.5%, then -35%
    found = leak_bill.bill_trade(WED, False, fills, bars)
    assert found["cut"] == {"rule": "deep_red", "at": ny(11, 6), "price": 130.0}
    assert dict(found["saved"]) == {"deep_red": 140.0}  # 2 sold at 130 instead of 60
    assert not leak_bill.bill_trade(date(2026, 11, 21), False, fills, bars)["saved"]  # 4 days to expiry: not short-dated
    assert leak_bill.bill_trade(date(2026, 11, 20), False, fills, bars)["cut"]["rule"] == "deep_red"  # 3 days is


def test_an_add_below_cost_is_billed_what_it_lost_and_never_twice():
    quick = [buy(1, 200, ny(10)), buy(1, 100, ny(10, 20)), sell(2, 50, ny(10, 40))]
    assert dict(leak_bill.bill_trade(WED, False, quick, None)["saved"]) == {"add": 50.0}  # no bars needed
    above = [buy(1, 200, ny(10)), buy(1, 210, ny(10, 20)), sell(2, 50, ny(10, 40))]
    assert not leak_bill.bill_trade(WED, False, above, None)["saved"]
    # Expired: the add lost its $100; the first contract is cut at $80, an hour in and 47% down on both.
    found = leak_bill.bill_trade(WED, True, quick[:2], [bar(11, 10, 0.80)])
    assert dict(found["saved"]) == {"add": 100.0, "deep_red": 80.0}  # ended -300; by the rules, -120
    # A buy below cost after the cut is no add: by the rules nothing is held then.
    late = [buy(1, 200, ny(10)), buy(1, 100, ny(11, 30)), sell(2, 50, ny(14))]
    assert dict(leak_bill.bill_trade(WED, False, late, [bar(11, 6, 1.30)])["saved"]) == {"deep_red": 80.0}
    # Buys in one minute are taken in the journal's order (fill id), whatever order they are read in.
    one, two = {**buy(1, 200, ny(10)), "id": uuid.UUID(int=1)}, {**buy(1, 100, ny(10)), "id": uuid.UUID(int=2)}
    assert dict(leak_bill.bill_trade(WED, False, [two, one, sell(2, 50, ny(10, 40))], None)["saved"]) == {"add": 50.0}
    # First in, first out: the first sale is the first contract's, the add's is the second.
    split = [buy(1, 200, ny(10)), buy(1, 100, ny(10, 20)), sell(1, 150, ny(10, 30)), sell(1, 120, ny(10, 40))]
    assert dict(leak_bill.bill_trade(WED, False, split, None)["saved"]) == {"add": -20.0}  # the add paid


def test_a_same_day_option_bought_before_noon_is_cut_at_1_pm():
    held = [buy(1, 100, ny(10)), sell(1, 150, ny(15))]
    bars = [bar(12, 59, 0.90), bar(13, 0, 0.95), bar(13, 1, 0.60)]
    found = leak_bill.bill_trade(TUE, False, held, bars)
    assert found["cut"]["rule"] == "past_1pm" and dict(found["saved"]) == {"past_1pm": -55.0}  # holding paid
    assert leak_bill.bill_trade(TUE, False, [buy(1, 100, ny(10)), sell(1, 150, ny(13))], bars)["cut"] is None  # out by one
    assert leak_bill.bill_trade(TUE, False, [buy(1, 100, ny(12, 5)), sell(1, 150, ny(15))], bars)["cut"] is None  # bought after noon
    assert leak_bill.bill_trade(WED, False, held, bars[:2])["cut"] is None  # expires tomorrow
    # A minute holding one of the trade's own fills is not judged; pre-market bars are not either.
    busy = [buy(1, 100, ny(10)), buy(1, 100, ny(13)), sell(2, 150, ny(15))]
    assert leak_bill.bill_trade(TUE, False, busy, [bar(9, 0, 0.1), bar(13, 0, 0.95), bar(13, 1, 0.60)])["cut"]["at"] == ny(13, 1)


@pytest.fixture
def engine():
    found = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(found)
    with Session(found) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267"))  # Robinhood accounts carry no broker
        db.commit()
    yield found
    found.dispose()


def trade(db, ticker, fills, expiration=WED, status="closed", pnl=0.0, closed_at=None, account=ROTH):
    row = Trade(account_id=account, ticker=ticker, instrument_type="option", contracts=1, option_type="call", strike=100,
                expiration=expiration, opened_at=fills[0]["executed_at"], closed_at=closed_at or fills[-1]["executed_at"],
                status=status, realized_pnl=pnl, avg_entry_premium=fills[0]["price"], total_premium_paid=fills[0]["price"], expired_worthless=status == "expired")
    db.add(row)
    db.flush()
    for i, f in enumerate(fills):
        fill = Fill(account_id=account, ticker=ticker, instrument_type="option", side=f["side"], contracts=f["contracts"],
                    price=f["price"], executed_at=f["executed_at"], raw_email_id=f"{ticker}-{i}", option_type="call", strike=100,
                    expiration=expiration)
        db.add(fill)
        db.flush()
        db.add(TradeFill(trade_id=row.id, fill_id=fill.id, role=f["role"]))
    db.commit()
    return row


def week(db):
    trade(db, "MU", [buy(2, 200, ny(10)), sell(2, 60, ny(14))], pnl=-280)  # deep red: cut at 130
    trade(db, "NBIS", [buy(1, 200, ny(10)), buy(1, 100, ny(10, 20))], status="expired", pnl=-300, closed_at=ny(16, day=18))
    trade(db, "AMD", [buy(1, 100, ny(10)), sell(1, 140, ny(10, 30))], pnl=40)  # clean, under the hour: no bars asked
    trade(db, "SNDK", [buy(1, 100, ny(10)), sell(1, 20, ny(15))], pnl=-80)  # short-dated, past the hour, no bars
    trade(db, "OLD", [buy(1, 100, ny(10, day=10)), sell(1, 20, ny(15, day=10))], expiration=date(2026, 11, 11), pnl=-80)  # last week
    webull = uuid.uuid4()
    db.add(Account(id=webull, name="Webull", type="individual", last4="0001", broker="webull"))
    trade(db, "WB", [buy(1, 200, ny(10)), buy(1, 100, ny(10, 20)), sell(2, 50, ny(10, 40))], pnl=-200, account=webull)
    return {"MU": [bar(11, 6, 1.30)], "NBIS": [bar(11, 10, 0.80)]}


def test_the_week_adds_up_once_and_names_what_it_could_not_price(engine):
    with Session(engine) as db:
        bars = week(db)
        asked = []
        bill = leak_bill.week_bill(db, date(2026, 11, 16), date(2026, 11, 22), lambda t: asked.append(t.ticker) or bars.get(t.ticker))
        assert sorted(asked) == ["MU", "NBIS", "SNDK"]
        assert (bill["trades"], bill["broke"], bill["broke_pnl"], bill["saved"], bill["unpriced"]) == (4, 2, -580.0, 320.0, 1)
        assert bill["by_rule"] == {"deep_red": {"trades": 2, "saved": 220.0}, "add": {"trades": 1, "saved": 100.0},
                                   "past_1pm": {"trades": 0, "saved": 0.0}}
        title, body = leak_bill.render(bill, "Nov 16")
    assert title == "LEAK BILL · $320"
    assert body.splitlines() == [
        "Week of Nov 16: breaking your leak rules cost $320.",
        "2 of 4 option trades broke one and ended -$580; by the rules, -$260.",
        "Held short-dated down 30%+ past an hour: 2 trades, cost $220.",
        "Added below cost: 1 trade, cost $100.",
        "Priced at that minute's last trade, not a quote.",
        "1 trade held short-dated past an hour had no minute prices: not in the number.",
    ]


def test_a_clean_week_and_a_week_the_breaks_paid_say_so():
    rules = {"deep_red": {"trades": 0, "saved": 0.0}, "add": {"trades": 0, "saved": 0.0}, "past_1pm": {"trades": 0, "saved": 0.0}}
    clean = {"trades": 3, "broke": 0, "broke_pnl": 0.0, "saved": 0.0, "unpriced": 0, "by_rule": rules}
    assert leak_bill.render(clean, "Nov 16") == ("LEAK BILL · $0", "Week of Nov 16: none of your 3 option trades broke a leak rule.")
    paid = {**clean, "broke": 1, "broke_pnl": 50.0, "saved": -55.0, "by_rule": {**rules, "past_1pm": {"trades": 1, "saved": -55.0}}}
    title, body = leak_bill.render(paid, "Nov 16")
    assert title == "LEAK BILL · $0" and body.splitlines()[:3] == [
        "Week of Nov 16: the trades that broke a leak rule came out $55 ahead of following it.",
        "1 of 3 option trades broke one and ended +$50; by the rules, -$5.",
        "Same-day option held past 1 PM: 1 trade, paid $55."]


def test_it_is_sent_once_on_sunday_evening_and_is_off_by_default(engine, monkeypatch):
    monkeypatch.delenv("LEAK_BILL_ENABLED", raising=False)
    assert not leak_bill.enabled()
    sent = []
    send = lambda title, body, path: sent.append((title, path))  # noqa: E731
    empty = leak_bill.LeakBill(engine, clock=lambda: SUNDAY, send=send, bars_for=lambda t: None)
    assert empty.due(SUNDAY) and not empty.due(datetime(2026, 11, 22, 17, 59, tzinfo=ET).timestamp())
    assert not empty.due(datetime(2026, 11, 23, 18, 30, tzinfo=ET).timestamp())
    assert empty.run().startswith("nothing") and not sent and not empty.due(SUNDAY)
    with Session(engine) as db:
        bars = week(db)
    monkeypatch.setattr(notification_policy, "enabled", lambda: False)
    assert leak_bill.LeakBill(engine, clock=lambda: SUNDAY, send=send, bars_for=lambda t: bars.get(t.ticker)).run() == "sent"
    assert sent == [("LEAK BILL · $320", "/proof")]
    assert leak_bill.LeakBill(engine, clock=lambda: SUNDAY, send=send, bars_for=lambda t: bars.get(t.ticker)).run().startswith("held")
    assert len(sent) == 1  # once a week, across restarts
