"""Fill-time pattern interrupts: one phone message when an entry fill repeats one of the owner's habits, with the
owner's own numbers. Phone only; nothing is ordered or advised."""

from datetime import date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import fill_interrupts, ntfy, reconstructor
from app.engine.chart_math import ET
from app.engine.fill_interrupts import FillInterrupts
from app.engine.level_alert_monitor import LevelAlertMonitor
from app.models import Account, Fill, FillInterrupt, PhonePing, Trade
from app.routers import position_alerts as position_alerts_router
from app.routers.fills import _rebuild_trades

ROTH, INDIVIDUAL, WEBULL = UUID(int=1), UUID(int=2), UUID(int=3)
WED = date(2026, 10, 21)
FRI = date(2026, 10, 23)
n = iter(range(100, 10_000))


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def ny(hhmm: str, day: date = WED) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture(autouse=True)
def on_wednesday(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    for name in ("FILL_INTERRUPTS_ENABLED", "PING_BUDGET_INTERRUPT", "PING_QUIET_MINUTES", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                 "ALERT_APP_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PING_IMAGES_ENABLED", "false")


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=INDIVIDUAL, name="Individual", type="individual", last4="1111", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="4242", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: out.append((title, body, kw)))
    return out


def fill(engine, when: datetime, ticker="NBIS", side="buy_to_open", qty=1, price=310, account=ROTH, option_type="put", strike=160,
         expiration=FRI, rebuild=True):
    i = next(n)
    option = {} if side in ("buy", "sell") else {"option_type": option_type, "strike": strike, "expiration": expiration}
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=account, ticker=ticker, instrument_type="stock" if side in ("buy", "sell") else "option",
                    side=side, contracts=qty, price=price, executed_at=when, raw_email_id=f"gmail:{i}", **option))
        db.commit()
        if rebuild:
            _rebuild_trades(db, "test")
            db.commit()


def rebuild(engine):
    with Session(engine) as db:
        _rebuild_trades(db, "test")
        db.commit()


def seed_history(engine):
    """Closed trades before Wednesday, Roth and Individual (and one in Webull, which never counts)."""
    d13, d14, d15, d16 = (date(2026, 10, d) for d in (13, 14, 15, 16))
    exp = date(2026, 10, 30)
    # Added to a loser: bought 500, added at 300, sold both at 350 (-$100).
    fill(engine, ny("10:00", d13), "AMD", option_type="call", strike=200, price=500, expiration=exp, rebuild=False)
    fill(engine, ny("10:30", d13), "AMD", option_type="call", strike=200, price=300, expiration=exp, rebuild=False)
    fill(engine, ny("11:00", d13), "AMD", side="sell_to_close", option_type="call", strike=200, qty=2, price=350, expiration=exp, rebuild=False)
    # Six puts, each -$50 or -$100.
    fill(engine, ny("10:00", d14), "AMD", option_type="put", strike=180, price=200, expiration=exp, rebuild=False)
    fill(engine, ny("10:20", d14), "AMD", side="sell_to_close", option_type="put", strike=180, price=100, expiration=exp, rebuild=False)
    for i in range(5):
        fill(engine, ny(f"10:0{i}", d16), "MU", option_type="put", strike=90 + i, price=200, expiration=exp, rebuild=False)
        fill(engine, ny(f"10:1{i}", d16), "MU", side="sell_to_close", option_type="put", strike=90 + i, price=150, expiration=exp, rebuild=False)
    # Late short-dated: bought 14:30 with one trading day left, expired worthless (-$100).
    fill(engine, ny("14:30", d14), "NVDA", option_type="call", strike=150, price=100, expiration=d15, rebuild=False)
    # Individual: a +$200 win, then a trade opened with the day green that lost $50.
    fill(engine, ny("09:45", d15), "MU", option_type="call", strike=100, price=100, expiration=exp, account=INDIVIDUAL, rebuild=False)
    fill(engine, ny("10:00", d15), "MU", side="sell_to_close", option_type="call", strike=100, price=300, expiration=exp, account=INDIVIDUAL,
         rebuild=False)
    fill(engine, ny("10:30", d15), "MU", option_type="call", strike=105, price=100, expiration=exp, account=INDIVIDUAL, rebuild=False)
    fill(engine, ny("11:00", d15), "MU", side="sell_to_close", option_type="call", strike=105, price=50, expiration=exp, account=INDIVIDUAL,
         rebuild=False)
    # Webull: a losing put, left out of every record.
    fill(engine, ny("10:00", d15), "TSLA", option_type="put", strike=400, price=900, expiration=exp, account=WEBULL, rebuild=False)
    fill(engine, ny("10:10", d15), "TSLA", side="sell_to_close", option_type="put", strike=400, price=100, expiration=exp, account=WEBULL)


def rows(engine):
    with Session(engine) as db:
        return db.exec(select(FillInterrupt).order_by(FillInterrupt.executed_at, FillInterrupt.detected_at)).all()


@pytest.fixture
def world(engine):
    seed_history(engine)
    clock = Clock(at("09:50"))
    return clock, FillInterrupts(engine, Calendar(), clock=clock)


def tick(clock, interrupts, hhmm):
    clock.now = at(hhmm)
    interrupts.run()
    interrupts.deliver()


# ------------------------------------------------------------------ the pure rules

def lot(side, price, hhmm="10:00", qty=1, i=None):
    return {"id": i or next(n), "side": side, "contracts": qty, "price": price, "executed_at": ny(hhmm)}


def option_fill(side="buy_to_open", price=250, hhmm="14:20", option_type="put", expiration=FRI):
    return {**lot(side, price, hhmm), "instrument_type": "option", "option_type": option_type, "expiration": expiration}


def test_off_by_default(monkeypatch):
    assert fill_interrupts.enabled() is False
    monkeypatch.setenv("FILL_INTERRUPTS_ENABLED", "true")
    assert fill_interrupts.enabled() is True


def test_add_to_loser_is_a_later_long_buy_below_the_open_lots_cost():
    prior = [lot("buy_to_open", 310, "14:05", qty=2)]
    assert fill_interrupts.adds_to_loser(option_fill(price=250), prior)
    assert not fill_interrupts.adds_to_loser(option_fill(price=310), prior)  # at cost is not below it
    assert not fill_interrupts.adds_to_loser(option_fill(price=250), [])  # a first entry
    # After a partial exit the cost is what is still open, first in first out: 400 sold, 200 left open.
    trimmed = [lot("buy_to_open", 400, "10:00"), lot("buy_to_open", 200, "10:05"), lot("sell_to_close", 300, "10:10")]
    assert not fill_interrupts.adds_to_loser(option_fill(price=250), trimmed)
    assert not fill_interrupts.adds_to_loser(option_fill(price=250), prior + [lot("sell_to_close", 200, "14:10", qty=2)])  # flat
    assert not fill_interrupts.adds_to_loser(option_fill(side="sell_to_open", price=250), [lot("sell_to_open", 310, "14:05")])
    stock = {**lot("buy", 90), "instrument_type": "stock"}
    assert not fill_interrupts.adds_to_loser(stock, [lot("buy", 120, "09:40")])  # nothing fires for stocks but a green day


def test_put_entry_opened_green_and_late_short_dated():
    assert fill_interrupts.is_put_entry(option_fill())
    assert not fill_interrupts.is_put_entry(option_fill(option_type="call"))
    assert not fill_interrupts.is_put_entry(option_fill(side="sell_to_open"))
    assert fill_interrupts.opened_green(0.01) and not fill_interrupts.opened_green(0) and not fill_interrupts.opened_green(None)
    closes = [(ny("10:05"), 200.0), (ny("14:30"), -500.0), (ny("15:00", date(2026, 10, 20)), 900.0)]
    assert fill_interrupts.day_pnl_before(closes, ny("14:20")) == 200.0  # that day's closes before the fill only
    assert fill_interrupts.trading_days(WED, FRI) == 2 and fill_interrupts.trading_days(FRI, date(2026, 10, 26)) == 1
    assert fill_interrupts.trading_days(WED, WED) == 0 and fill_interrupts.trading_days(WED, date(2026, 10, 26)) == 3
    assert fill_interrupts.late_short_dated(option_fill(hhmm="14:00"))
    assert not fill_interrupts.late_short_dated(option_fill(hhmm="13:59"))
    assert not fill_interrupts.late_short_dated(option_fill(expiration=date(2026, 10, 26)))  # three trading days
    assert fill_interrupts.late_short_dated(option_fill(expiration=WED, option_type="call"))  # 0DTE call
    assert not fill_interrupts.late_short_dated(option_fill(side="sell_to_open"))
    every = fill_interrupts.fired(option_fill(price=250), [lot("buy_to_open", 310, "14:05", qty=2)], 200.0)
    assert every == ["add_to_loser", "put_entry", "opened_green", "late_short_dated"]  # the message's order


def test_records_lines_and_the_too_few_rule():
    rows = [{"key": f"k{i}", "pnl": pnl, "long_option": True, "option_type": "put", "expired_worthless": i < 3, "added_to_loser": True,
             "opened_green": False, "late_short_dated": True} for i, pnl in enumerate((-500, -400, -300, 200, 100, -200))]
    rows.append({"key": "call", "pnl": 900.0, "long_option": True, "option_type": "call", "expired_worthless": False,
                 "added_to_loser": False, "opened_green": True, "late_short_dated": False})
    loser = fill_interrupts.record(rows, "add_to_loser")
    assert loser == {"n": 6, "pnl": -1100, "green": 2, "expired": 3}
    assert fill_interrupts.line("add_to_loser", loser) == "Adding to a loser: 6 past adds, 2 ended green, −$1,100"
    assert fill_interrupts.record(rows, "add_to_loser", exclude="k3")["n"] == 5  # the judged position is never counted
    puts = fill_interrupts.record(rows, "put_entry")
    assert fill_interrupts.line("put_entry", puts) == "Put entry: puts −$1,100 over 6 trades; calls 1, too few to read"
    late = fill_interrupts.record(rows, "late_short_dated")
    assert fill_interrupts.line("late_short_dated", late) == (
        "Late short-dated buy: 6 past buys after 2 PM with 0–2 days left, 50% expired worthless, −$1,100")
    green = fill_interrupts.record(rows, "opened_green")
    assert fill_interrupts.line("opened_green", green, 250.0) == "Day already green (+$250 today): 1 past trade opened green, too few to read"
    assert fill_interrupts.line("late_short_dated", fill_interrupts.record(rows[:4], "late_short_dated")).endswith("4 past buys after 2 PM "
                                                                                                                    "with 0–2 days left, too few to read")
    title, body = fill_interrupts.message("NBIS 160P", ["a", "b"])
    assert title == "Pattern: NBIS 160P" and body == "a\nb\nYour record, not advice."
    assert fill_interrupts.short_label("NBIS", "option", "call", 160.0) == "NBIS 160C" and fill_interrupts.short_label("CRWV", "stock", None, None) == "CRWV"


def past(key, ticker="SNDK", pnl=-100.0, premium=1000.0, entered=date(2026, 9, 1), long_option=True):
    return {"key": key, "pnl": pnl, "ticker": ticker, "entered": entered, "premium": premium, "long_option": long_option,
            "option_type": "call" if long_option else None, "expired_worthless": False, "added_to_loser": False,
            "opened_green": False, "late_short_dated": False, "built": 0.0, "quick_reentry": False}


def test_ticker_record_fires_only_on_a_losing_record_of_five_or_more():
    losing = [past(f"s{i}", pnl=pnl) for i, pnl in enumerate((-500, -400, 100, 200, -1))]  # -$601 over 5
    rec = fill_interrupts.record(losing + [past("mu", "MU", 9000)], "ticker_record", ticker="SNDK")
    assert rec == {"ticker": "SNDK", "n": 5, "pnl": -601, "green": 2}
    assert fill_interrupts.ticker_record(rec)
    assert fill_interrupts.line("ticker_record", rec) == "Your record in SNDK: 5 trades, 40% won, −$601"
    assert not fill_interrupts.ticker_record(fill_interrupts.record(losing[:4], "ticker_record", ticker="SNDK"))  # four is too few
    # The judged position is never in its own record: leaving it out drops the count under five.
    assert not fill_interrupts.ticker_record(fill_interrupts.record(losing, "ticker_record", "s0", ticker="SNDK"))
    flat = losing[:4] + [past("s4", pnl=600)]
    assert fill_interrupts.record(flat, "ticker_record", ticker="SNDK")["pnl"] == 0
    assert not fill_interrupts.ticker_record(fill_interrupts.record(flat, "ticker_record", ticker="SNDK"))  # zero is not below zero
    assert not fill_interrupts.ticker_record(fill_interrupts.record([past(f"m{i}", "MU", 500) for i in range(9)], "ticker_record", ticker="MU"))
    assert not fill_interrupts.ticker_record(None)
    assert fill_interrupts.line("ticker_record", fill_interrupts.record(losing[:2], "ticker_record", ticker="SNDK")) == (
        "Your record in SNDK: 2 trades, too few to read")


def test_large_size_is_twice_the_median_of_twenty_entries_in_twelve_months():
    day = date(2026, 10, 21)
    usual = [past(f"u{i}", premium=1000.0, pnl=50.0) for i in range(15)]
    big = [past(f"b{i}", premium=2500.0, pnl=-400.0 if i else 300.0) for i in range(5)]
    old = [past(f"o{i}", premium=50.0, entered=date(2025, 10, 20)) for i in range(30)]  # a year and a day: outside the window
    stock = [past(f"s{i}", premium=99_000.0, long_option=False) for i in range(5)]
    rec = fill_interrupts.record(usual + big + old + stock, "large_size", day=day)
    assert rec == {"n": 5, "pnl": -1300, "green": 1, "median": 1000.0, "entries": 20}
    buy = {"side": "buy_to_open", "instrument_type": "option", "contracts": 4, "price": 500.0}  # $2,000 paid, exactly twice the median
    assert fill_interrupts.premium(buy) == 2000 and fill_interrupts.large_size(buy, rec["median"])
    assert not fill_interrupts.large_size({**buy, "price": 499.0}, rec["median"])
    assert not fill_interrupts.large_size({"side": "buy", "instrument_type": "stock", "contracts": 100, "price": 20.0}, rec["median"])  # a stock is not a premium
    assert not fill_interrupts.large_size({**buy, "instrument_type": "stock"}, rec["median"])
    assert not fill_interrupts.large_size({**buy, "side": "sell_to_open"}, rec["median"])  # premium received, not paid
    assert fill_interrupts.line("large_size", rec, paid=2300.0) == (
        "Size: $2,300 is 2.3× your median ($1,000); your 5 past entries above 2×: 20% won, −$1,300")
    # Nineteen entries in the window is too few: no median, never fires, whatever the size.
    short = fill_interrupts.record(usual + big[:4] + old, "large_size", day=day)
    assert short["median"] is None and short["entries"] == 19 and not fill_interrupts.large_size({**buy, "contracts": 1000}, short["median"])
    # The judged position is left out of its own baseline.
    assert fill_interrupts.record(usual + big, "large_size", "u0", day=day)["median"] is None
    few = fill_interrupts.record(usual[:9] + big[:1] + [past(f"x{i}", premium=900.0) for i in range(10)], "large_size", day=day)
    assert fill_interrupts.line("large_size", few, paid=2000.0) == (
        "Size: $2,000 is 2.1× your median ($950); your 1 past entry above 2×, too few to read")


def test_eight_rules_fire_in_order_in_one_message():
    rows = [past(f"s{i}", premium=1000.0) for i in range(20)]
    ticker_rec = fill_interrupts.record(rows, "ticker_record", ticker="SNDK")
    size_rec = fill_interrupts.record(rows, "large_size", day=WED)
    built_rec = fill_interrupts.record(rows, "size_by_adding", day=WED)
    entry = {**option_fill(price=2500), "contracts": 1}
    prior = [lot("buy_to_open", 3100, "14:05", qty=2)]
    last = (ny("14:17"), -120.0)
    # An add cannot be a re-entry, so the eighth rule is judged on the position's first fill.
    kinds = fill_interrupts.fired(entry, prior, 200.0, ticker_rec, size_rec, built_rec, last) + fill_interrupts.fired(entry, [], None, last=last)[-1:]
    assert kinds == list(fill_interrupts.KINDS) == ["add_to_loser", "put_entry", "opened_green", "late_short_dated", "ticker_record",
                                                    "large_size", "size_by_adding", "quick_reentry"]
    assert fill_interrupts.fired(entry, [], None) == ["put_entry", "late_short_dated"]  # without the records and the close, no more
    assert set(fill_interrupts.ONCE_PER_POSITION) == set(kinds) - {"add_to_loser"}
    assert fill_interrupts.NOT_SENT == {"large_size", "late_short_dated"}  # judged for the desk, never a phone message
    recs = {"ticker_record": ticker_rec, "large_size": size_rec, "size_by_adding": built_rec}
    paid = {"size_by_adding": fill_interrupts.position_premium(entry, prior)}
    lines = [fill_interrupts.line(k, recs.get(k) or fill_interrupts.record(rows, k), 200.0, paid.get(k, fill_interrupts.premium(entry)),
                                  last, entry["executed_at"]) for k in kinds]
    _, body = fill_interrupts.message("SNDK 160P", lines)
    assert body.split("\n")[-5:] == [
        "Your record in SNDK: 20 trades, 0% won, −$2,000",
        "Size: $2,500 is 2.5× your median ($1,000); your 0 past entries above 2×, too few to read",
        "Size by adding: $8,700 in this position is 8.7× your median ($1,000) after an add below cost; "
        "your 0 past short-dated positions built this way, too few to read",
        "Back in 3 min after a −$120 close: 0 past entries within 5 min of a losing close, too few to read",
        "Your record, not advice."]
    assert len(body.split("\n")) == 9


def test_size_by_adding_is_an_add_below_cost_that_takes_a_short_dated_position_to_twice_the_median():
    prior = [lot("buy_to_open", 800, "10:00")]
    add = {**option_fill(price=700, hhmm="10:30"), "contracts": 2}  # below cost; $800 + $1,400 = $2,200 in, two days to expiry
    assert fill_interrupts.position_premium(add, prior) == 2200
    assert fill_interrupts.size_by_adding(add, prior, 1000.0)
    assert not fill_interrupts.size_by_adding(add, prior, 1101.0)  # under twice the median
    assert not fill_interrupts.size_by_adding(add, prior, None)  # too little history for a median
    assert not fill_interrupts.size_by_adding({**add, "price": 800}, prior, 1000.0)  # at cost is not an add below it
    assert not fill_interrupts.size_by_adding({**add, "contracts": 3}, [], 1000.0)  # a large first entry is not this rule
    assert fill_interrupts.size_by_adding({**add, "expiration": date(2026, 10, 24)}, prior, 1000.0)  # three calendar days
    assert not fill_interrupts.size_by_adding({**add, "expiration": date(2026, 10, 25)}, prior, 1000.0)  # four
    assert fill_interrupts.size_by_adding({**add, "expiration": WED}, prior, 1000.0)  # same day
    # A sale in between does not shrink what was paid in; the add must still be below the open lots' cost.
    assert fill_interrupts.size_by_adding(add, [lot("buy_to_open", 800, "10:00", qty=2), lot("sell_to_close", 750, "10:10")], 1500.0)
    day = date(2026, 10, 21)
    usual = [past(f"u{i}", premium=1000.0, pnl=50.0) for i in range(20)]
    built = [{**past(f"b{i}", premium=900.0, pnl=-600.0 if i else 200.0), "built": 2400.0, "added_to_loser": True} for i in range(5)]
    other = [{**past("long", premium=900.0), "added_to_loser": True},  # its add below cost was not short-dated: nothing built
             past("clean", premium=2400.0),  # large in one entry
             {**past("small", premium=900.0), "built": 1900.0, "added_to_loser": True}]  # under twice the median at the add
    rec = fill_interrupts.record(usual + built + other, "size_by_adding", day=day)
    assert rec == {"n": 5, "pnl": -2200, "green": 1, "median": 1000.0}
    assert fill_interrupts.record(usual + built + other, "size_by_adding", "b0", day=day)["n"] == 4  # never the judged position
    assert fill_interrupts.line("size_by_adding", rec, paid=2200.0) == (
        "Size by adding: $2,200 in this position is 2.2× your median ($1,000) after an add below cost; "
        "your 5 past short-dated positions built this way: 20% won, −$2,200")


def test_quick_reentry_is_an_option_bought_within_five_minutes_of_a_losing_close():
    buy = option_fill(hhmm="10:14")
    closes = [(ny("09:50"), 300.0), (ny("10:10"), -80.0), (ny("10:20"), -500.0), (ny("15:00", date(2026, 10, 20)), -900.0)]
    assert fill_interrupts.last_close(closes, ny("10:14")) == (ny("10:10"), -80.0)  # the latest that day, not after the fill
    assert fill_interrupts.last_close(closes, ny("09:40")) is None
    assert fill_interrupts.last_close(closes, ny("10:10")) == (ny("10:10"), -80.0)  # the same minute counts as close, then entry
    # Two closes in one minute are read together, whichever comes first: a -$80 and a +$100 are a +$20 minute, not a loss.
    tied = [(ny("10:10"), -80.0), (ny("10:10"), 100.0)]
    assert fill_interrupts.last_close(tied, ny("10:12")) == fill_interrupts.last_close(tied[::-1], ny("10:12")) == (ny("10:10"), 20.0)
    assert not fill_interrupts.quick_reentry(buy, fill_interrupts.last_close(tied, ny("10:12")))
    # A manual fill can carry seconds: closes are still read a whole minute at a time.
    seconds = [(ny("10:10").replace(second=5), 100.0), (ny("10:10").replace(second=45), -80.0)]
    assert fill_interrupts.last_close(seconds, ny("10:11")) == fill_interrupts.last_close(seconds[::-1], ny("10:11")) == (ny("10:10"), 20.0)
    assert fill_interrupts.last_close(seconds, ny("10:10").replace(second=20)) == (ny("10:10"), 20.0)  # the fill's own minute, whole
    flat = [(ny("10:10"), -1000.10), (ny("10:10"), -1000.20), (ny("10:10"), 2000.30)]  # sums to a hair under zero as floats
    assert fill_interrupts.last_close(flat, ny("10:12")) == (ny("10:10"), 0.0) and not fill_interrupts.quick_reentry(buy, (ny("10:10"), 0.0))
    # An add to a position already open is not a re-entry: the record counts first entries, and so does the rule.
    assert fill_interrupts.fired(buy, [], None, last=(ny("10:10"), -80.0)) == ["put_entry", "quick_reentry"]
    assert fill_interrupts.fired(buy, [lot("buy_to_open", 200, "09:40")], None, last=(ny("10:10"), -80.0)) == ["put_entry"]
    assert fill_interrupts.quick_reentry(buy, (ny("10:10"), -80.0))
    assert not fill_interrupts.quick_reentry(buy, (ny("10:09"), -80.0))  # five minutes is not within five
    assert not fill_interrupts.quick_reentry(buy, (ny("10:12"), 80.0)) and not fill_interrupts.quick_reentry(buy, (ny("10:12"), 0.0))
    assert not fill_interrupts.quick_reentry(buy, None)
    assert not fill_interrupts.quick_reentry({**buy, "side": "sell_to_open"}, (ny("10:12"), -80.0))
    assert not fill_interrupts.quick_reentry({**lot("buy", 120, "10:14"), "instrument_type": "stock"}, (ny("10:12"), -80.0))
    rows = [{**past(f"q{i}", pnl=pnl), "quick_reentry": True} for i, pnl in enumerate((-300, -200, 100, -50, 40))] + [past("calm", pnl=900)]
    rec = fill_interrupts.record(rows, "quick_reentry")
    assert rec == {"n": 5, "pnl": -410, "green": 2, "expired": 0}
    assert fill_interrupts.line("quick_reentry", rec, last=(ny("10:10"), -80.0), at=ny("10:14")) == (
        "Back in 4 min after a −$80 close: 5 past entries within 5 min of a losing close, 40% won, −$410")
    assert fill_interrupts.line("quick_reentry", fill_interrupts.record(rows[:1], "quick_reentry")) == (
        "Back in: 1 past entry within 5 min of a losing close, too few to read")


# ------------------------------------------------------------------ the pass

@pytest.mark.parametrize("copilot", [False, True])
def test_the_seeded_day_one_message_per_fill(engine, world, sent, monkeypatch, copilot):
    if copilot:
        monkeypatch.setenv("COPILOT_ENABLED", "true")
    else:
        monkeypatch.delenv("COPILOT_ENABLED", raising=False)
    clock, interrupts = world
    fill(engine, ny("10:00"), "SNDK", option_type="call", strike=500, price=100, expiration=date(2026, 10, 30))
    tick(clock, interrupts, "10:01")
    fill(engine, ny("10:05"), "SNDK", side="sell_to_close", option_type="call", strike=500, price=300, expiration=date(2026, 10, 30))
    fill(engine, ny("10:10"), "CRWV", side="buy", qty=10, price=120)
    tick(clock, interrupts, "10:11")
    fill(engine, ny("14:05"), qty=2, price=310)
    tick(clock, interrupts, "14:06")
    fill(engine, ny("14:20"), qty=1, price=250)
    tick(clock, interrupts, "14:21")
    found = rows(engine)
    assert [(r.contract, r.kinds, r.delivery) for r in found] == [
        ("SNDK 10/30/26 500C", "", "none"),  # a call, first of the day: nothing fires
        ("CRWV stock", "opened_green", "sent"),  # a stock fires only the green day
        ("NBIS 10/23/26 160P", "put_entry,opened_green", "sent"),  # a late short-dated buy is no longer a message
        ("NBIS 10/23/26 160P", "add_to_loser", "sent"),  # the position's other lines were already said
    ]
    assert [(t, b) for t, b, _ in sent] == [
        ("Pattern: CRWV", "Day already green (+$200 today): 1 past trade opened green, too few to read\nYour record, not advice."),
        ("Pattern: NBIS 160P", "Put entry: puts −$350 over 6 trades; calls +$150 over 5\n"
                               "Day already green (+$200 today): 1 past trade opened green, too few to read\n"
                               "Your record, not advice."),
        ("Pattern: NBIS 160P", "Adding to a loser: 1 past add, too few to read\nYour record, not advice."),
    ]
    add = found[3]
    kw = sent[2][2]
    # The tap opens the desk on the ticker while the copilot is on (the trade page otherwise); Noted stays the trade page's.
    assert kw["path"] == (f"/copilot-lab?symbol=NBIS&card=interrupt%3A{add.id}" if copilot else f"/trades/{add.trade_id}?interrupt={add.id}")
    assert kw["more"] == (("Noted", f"/trades/{add.trade_id}?interrupt={add.id}&noted=1"),)
    with Session(engine) as db:
        pings = db.exec(select(PhonePing).order_by(PhonePing.decided_at)).all()
        assert [(p.sender, p.kind, p.decision) for p in pings] == [("fill_interrupts", "interrupt", "sent")] * 3
        # Both NBIS messages are anchored to the position (its first entry fill), not to each fill.
        assert pings[1].anchor == pings[2].anchor == f"{ROTH}:{found[2].fill_key}" and found[3].position_key == found[2].fill_key


def test_each_fill_is_judged_once_across_a_rebuild_and_a_second_process(engine, world, sent):
    clock, interrupts = world
    fill(engine, ny("14:05"), qty=2, price=310)
    tick(clock, interrupts, "14:06")
    rebuild(engine)  # the trades rebuilt; the fill's source identity is the same
    tick(clock, interrupts, "14:07")
    other = FillInterrupts(engine, Calendar(), clock=Clock(at("09:30")))
    other.clock.now = at("14:08")
    other.run()
    other.deliver()
    assert len(rows(engine)) == 1 and len(sent) == 1


def test_an_earlier_fill_whose_email_comes_late_stays_on_the_same_position(engine, world, sent):
    clock, interrupts = world
    fill(engine, ny("14:02"), qty=1, price=310)  # its email came first
    tick(clock, interrupts, "14:03")
    fill(engine, ny("14:00"), qty=1, price=310)  # the earlier fill, a minute late: now the position's first entry
    tick(clock, interrupts, "14:04")
    later, earlier = sorted(rows(engine), key=lambda r: r.detected_at)
    assert later.position_key == earlier.position_key == later.fill_key
    assert (later.delivery, earlier.delivery) == ("sent", "none") and len(sent) == 1  # nothing new to say about the position
    with Session(engine) as db:
        trade = db.get(Trade, earlier.trade_id)
        assert [r["id"] for r in fill_interrupts.for_trade(db, trade)] == [str(later.id)]  # still listed on the rebuilt trade
        from app.routers import copilot_desk
        held = copilot_desk._interrupt_trade(db, db.get(type(later), later.id))  # the ping card still finds the position
        assert held is not None and held.status == "open"
        assert fill_interrupts.note(db, held, later.id, 0) is not None  # its Noted lands on the trade the card names


def test_scaling_in_repeats_only_adding_to_a_loser(engine, world, sent):
    clock, interrupts = world
    fill(engine, ny("14:05"), qty=1, price=310)
    tick(clock, interrupts, "14:06")
    fill(engine, ny("14:20"), qty=1, price=320)  # above cost: the put and late-buy lines were already said
    tick(clock, interrupts, "14:21")
    fill(engine, ny("14:40"), qty=1, price=250)  # below cost
    tick(clock, interrupts, "14:41")
    assert [(r.kinds, r.delivery) for r in rows(engine)] == [("put_entry", "sent"), ("", "none"), ("add_to_loser", "sent")]
    assert sent[1][1] == "Adding to a loser: 1 past add, too few to read\nYour record, not advice."


def test_only_fills_since_start_in_the_regular_session_and_never_webull(engine, world, sent):
    clock, interrupts = world
    fill(engine, ny("09:40"), "AMD", option_type="put", strike=170, price=100, expiration=date(2026, 10, 30))  # before the start
    fill(engine, ny("14:05"), "TSLA", option_type="put", strike=400, price=900, account=WEBULL)
    tick(clock, interrupts, "14:06")
    assert rows(engine) == []
    fill(engine, ny("15:58"), qty=1, price=310)
    tick(clock, interrupts, "16:01")  # after the close: nothing is judged
    assert rows(engine) == []
    late = FillInterrupts(engine, Calendar(), clock=Clock(at("09:00")))
    late.clock.now = at("16:20", date(2026, 10, 22))  # next day, and a fill first seen long after it happened
    late.run()
    assert rows(engine) == [] and sent == []


def test_delivery_is_at_most_once_and_expires(engine, world, monkeypatch):
    clock, interrupts = world
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    calls = []

    def lost(*a, **kw):
        calls.append(a)
        raise ntfy.NtfyError("ntfy timed out") from httpx.ReadTimeout("slow")

    monkeypatch.setattr(ntfy, "publish", lost)
    fill(engine, ny("14:05"), qty=2, price=310)
    tick(clock, interrupts, "14:06")
    tick(clock, interrupts, "14:08")
    [row] = rows(engine)
    assert row.delivery == "unknown" and len(calls) == 1  # may have reached the phone: never resent

    def refused(*a, **kw):
        calls.append(a)
        raise ntfy.NtfyError("ntfy refused the notification (500).")

    monkeypatch.setattr(ntfy, "publish", refused)
    fill(engine, ny("14:10"), "AMD", option_type="put", strike=170, price=100)
    tick(clock, interrupts, "14:11")
    assert rows(engine)[1].delivery == "pending"
    clock.now = at("14:15")  # past the three minutes: dropped, not sent late
    interrupts.deliver()
    assert rows(engine)[1].delivery == "expired" and len(calls) == 2


def test_the_budget_and_the_quiet_window_hold_it(engine, world, sent, monkeypatch):
    monkeypatch.setenv("PING_BUDGET_INTERRUPT", "1")
    clock, interrupts = world
    fill(engine, ny("14:05"), qty=2, price=310)
    tick(clock, interrupts, "14:06")
    fill(engine, ny("14:08"), qty=1, price=250)  # the same position inside the quiet window
    fill(engine, ny("14:08"), "AMD", option_type="put", strike=170, price=100)  # another position, over the budget
    tick(clock, interrupts, "14:09")
    first, add, other = rows(engine)
    assert (first.delivery, add.delivery, other.delivery) == ("sent", "held", "held")
    assert "quiet window" in add.last_error and other.last_error == "Not sent: Pattern interrupts' 1 message for today is spent."
    assert len(sent) == 1


def test_the_history_is_cached_and_rebuilt_when_the_closed_trades_change(engine, world, monkeypatch):
    clock, interrupts = world
    loads = []
    real = fill_interrupts.load_history
    monkeypatch.setattr(fill_interrupts, "load_history", lambda db: loads.append(1) or real(db))
    with Session(engine) as db:
        interrupts.history(db, WED)
        interrupts.history(db, WED)
        assert len(loads) == 1
    fill(engine, ny("10:00"), "SNDK", option_type="call", strike=500, price=100, expiration=date(2026, 10, 30))
    fill(engine, ny("10:05"), "SNDK", side="sell_to_close", option_type="call", strike=500, price=300, expiration=date(2026, 10, 30))
    with Session(engine) as db:
        rows_now = interrupts.history(db, WED)
        assert len(loads) == 2 and len(rows_now) == 11  # ten closed before Wednesday outside Webull, and this one


def test_noted_is_recorded_once_through_an_owner_only_route(engine, world, sent):
    from app.access_manifest import DOMAIN_ROUTES
    from app.engine import access

    clock, interrupts = world
    fill(engine, ny("14:05"), qty=2, price=310)
    tick(clock, interrupts, "14:06")
    [row] = rows(engine)
    app = FastAPI()
    app.include_router(position_alerts_router.router, prefix="/trades")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    client = TestClient(app)
    listed = client.get(f"/trades/{row.trade_id}/fill-interrupts").json()["interrupts"]
    assert [(i["id"], i["title"], i["noted_at"]) for i in listed] == [(str(row.id), "Pattern: NBIS 160P", None)]
    first = client.post(f"/trades/{row.trade_id}/fill-interrupts/{row.id}/noted").json()
    again = client.post(f"/trades/{row.trade_id}/fill-interrupts/{row.id}/noted").json()
    assert first["noted_at"] is not None and again["noted_at"] == first["noted_at"]
    assert client.post(f"/trades/{row.trade_id}/fill-interrupts/{UUID(int=999)}/noted").status_code == 404
    for operation in ("GET /trades/{trade_id}/fill-interrupts", "POST /trades/{trade_id}/fill-interrupts/{interrupt_id}/noted"):
        assert operation in DOMAIN_ROUTES
        for granted in (access.JOURNAL_PATHS, access.MARKET_PATHS, access.PRACTICE_PATHS, access.SAMPLE_WRITER_PATHS,
                        *access.SERVICE_PATHS.values()):
            assert operation not in granted


def test_the_monitor_runs_it_only_when_switched_on(engine, monkeypatch):
    assert LevelAlertMonitor(engine, calendar=Calendar()).interrupts is None
    monkeypatch.setenv("FILL_INTERRUPTS_ENABLED", "true")
    assert isinstance(LevelAlertMonitor(engine, calendar=Calendar()).interrupts, FillInterrupts)


def test_nothing_places_or_suggests_an_order():
    import inspect
    source = inspect.getsource(fill_interrupts)
    for word in ("place_order", "submit_order", "orders", "tradier.post"):
        assert word not in source


def test_a_large_add_in_a_losing_ticker_sends_every_line_once(engine, world, sent):
    clock, interrupts = world
    exp = date(2026, 10, 30)
    for i in range(20):  # twenty closed NBIS calls in September, $100 each: five won $40, fifteen lost $20
        fill(engine, ny("10:00", date(2026, 9, 1 + i)), option_type="call", strike=150 + i, price=100, expiration=exp, rebuild=False)
        fill(engine, ny("10:30", date(2026, 9, 1 + i)), side="sell_to_close", option_type="call", strike=150 + i,
             price=140 if i < 5 else 80, expiration=exp, rebuild=False)
    fill(engine, ny("09:40"), qty=2, price=310, rebuild=False)  # the position's first entry, before the process started
    fill(engine, ny("10:00"), "SNDK", option_type="call", strike=500, price=100, expiration=exp, rebuild=False)
    fill(engine, ny("10:05"), "SNDK", side="sell_to_close", option_type="call", strike=500, price=300, expiration=exp)  # +$200 today
    fill(engine, ny("14:20"), qty=1, price=250)  # below cost, a put, green day, a losing ticker, $870 in against a $100 median
    tick(clock, interrupts, "14:21")
    fill(engine, ny("14:40"), qty=1, price=240)  # a second large add, past the quiet window: only adding to a loser repeats
    tick(clock, interrupts, "14:41")
    first, second = rows(engine)
    # Late (14:20, two days left) and 2.5× the median in one fill, but neither of those is a message any more.
    assert first.kinds == "add_to_loser,put_entry,opened_green,ticker_record,size_by_adding" and second.kinds == "add_to_loser"
    body = sent[0][1].split("\n")
    assert len(body) == 6 and body[0].startswith("Adding to a loser") and body[1].startswith("Put entry")
    assert body[2].startswith("Day already green (+$200 today)")
    assert body[3:] == ["Your record in NBIS: 20 trades, 25% won, −$100",
                        "Size by adding: $870 in this position is 8.7× your median ($100) after an add below cost; "
                        "your 0 past short-dated positions built this way, too few to read",
                        "Your record, not advice."]
    assert sent[0][2]["priority"] == 4  # size by adding is position risk: it makes a sound
    assert len(sent) == 2 and sent[1][1].startswith("Adding to a loser")


@pytest.mark.parametrize("goal", ["no_opening_while_green", "plan_before_entry", "raises"])
def test_the_green_day_interrupt_carries_the_practice_goal_above_the_footer(engine, world, sent, monkeypatch, goal):
    def ping_line(db, measure, today):
        assert today == date(2026, 10, 21)
        if goal == "raises":
            raise RuntimeError("boom")
        return "Practice this week: no new trade while the day is green · kept 2 of 3 so far" if measure == goal else None
    monkeypatch.setattr(fill_interrupts.practice_goal, "ping_line", ping_line)
    clock, interrupts = world
    exp = date(2026, 10, 30)
    fill(engine, ny("10:00"), "SNDK", option_type="call", strike=500, price=100, expiration=exp)
    tick(clock, interrupts, "10:01")
    fill(engine, ny("10:05"), "SNDK", side="sell_to_close", option_type="call", strike=500, price=300, expiration=exp)
    fill(engine, ny("10:10"), "CRWV", side="buy", qty=10, price=120)
    tick(clock, interrupts, "10:11")
    practice = ["Practice this week: no new trade while the day is green · kept 2 of 3 so far"] if goal == "no_opening_while_green" else []
    assert sent[0][1].split("\n") == ["Day already green (+$200 today): 1 past trade opened green, too few to read", *practice,
                                      "Your record, not advice."]


def test_the_desk_s_usual_size_is_the_median_long_option_premium_once_twenty_are_in_the_window(engine, world, monkeypatch):
    rows = [{"long_option": True, "entered": WED, "premium": p} for p in [100.0] * 10 + [300.0] * 11]
    monkeypatch.setattr(fill_interrupts, "load_history", lambda db: rows)
    monkeypatch.setattr(fill_interrupts, "_USUAL", None)
    with Session(engine) as db:
        assert fill_interrupts.usual_size(db, WED) == 300.0
        rows[:] = rows[:19]  # nineteen: too few to say what is usual (the cache is per signature, so clear it)
        monkeypatch.setattr(fill_interrupts, "_USUAL", None)
        assert fill_interrupts.usual_size(db, WED) is None


def test_a_desk_row_says_its_size_only_at_twice_the_usual_or_more():
    from app.routers.copilot_desk import _size_x
    row = lambda cost, qty, direction="long": {"book": {"option": {"cost": cost, "quantity": qty, "direction": direction}}}  # noqa: E731
    big, small, short = row(250, 4), row(150, 2), row(250, 4, "short")
    for r in (big, small, short):
        _size_x(r, 400.0)
    assert big["book"]["size_x"] == 2.5 and "size_x" not in small["book"] and "size_x" not in short["book"]


def test_buying_within_five_minutes_of_a_losing_close_is_one_message_with_the_record(engine, world, sent):
    clock, interrupts = world
    exp = date(2026, 10, 30)
    for i in range(5):  # five past days: a losing close at 10:10, back in at 10:12, each re-entry lost $30
        day = date(2026, 9, 14 + i)
        fill(engine, ny("10:00", day), "AMD", option_type="call", strike=200 + i, price=200, expiration=exp, rebuild=False)
        fill(engine, ny("10:10", day), "AMD", side="sell_to_close", option_type="call", strike=200 + i, price=150, expiration=exp, rebuild=False)
        fill(engine, ny("10:12", day), "MU", option_type="call", strike=100 + i, price=100, expiration=exp, rebuild=False)
        fill(engine, ny("10:40", day), "MU", side="sell_to_close", option_type="call", strike=100 + i, price=70, expiration=exp, rebuild=False)
    fill(engine, ny("10:00"), "SNDK", option_type="call", strike=500, price=300, expiration=exp, rebuild=False)
    fill(engine, ny("10:20"), "SNDK", side="sell_to_close", option_type="call", strike=500, price=180, expiration=exp)  # -$120 today
    fill(engine, ny("10:23"), "CRWV", option_type="call", strike=120, price=150, expiration=exp)
    tick(clock, interrupts, "10:24")
    fill(engine, ny("10:40"), "CRWV", option_type="call", strike=120, price=160, expiration=exp)  # scaling in: said once
    tick(clock, interrupts, "10:41")
    fill(engine, ny("11:30"), "ORCL", option_type="call", strike=300, price=150, expiration=exp)  # an hour after the loss: quiet
    tick(clock, interrupts, "11:31")
    assert [(r.ticker, r.kinds) for r in rows(engine)] == [("CRWV", "quick_reentry"), ("CRWV", ""), ("ORCL", "")]
    assert [(t, b) for t, b, _ in sent] == [("Pattern: CRWV 120C", "Back in 3 min after a −$120 close: 5 past entries within 5 min of a "
                                             "losing close, 0% won, −$150\nYour record, not advice.")]
    assert sent[0][2]["priority"] <= 2  # silent


def test_the_size_record_counts_a_past_position_only_when_an_add_below_cost_took_it_to_the_multiple():
    """The record's test is the live rule's, at each past add: a later add above cost does not make an earlier one count."""
    exp, day = date(2026, 9, 3), date(2026, 9, 1)

    def entry(key, price, hhmm, role="entry", side="buy_to_open"):
        return {"id": key, "key": key, "role": role, "side": side, "contracts": 1, "price": price, "executed_at": ny(hhmm, day)}
    trade = {"id": "t", "account_id": ROTH, "ticker": "AMD", "status": "closed", "instrument_type": "option", "option_type": "call",
             "expiration": exp, "realized_pnl": -500.0, "expired_worthless": False, "closed_at": ny("15:00", day)}
    sold = entry("x", 600, "15:00", role="exit", side="sell_to_close")
    # $900, an $800 add below cost ($1,700 in), then a $1,000 add above cost ($2,700 in): no add below cost reached $2,000.
    [row] = fill_interrupts.history_rows([trade], {"t": [entry("a", 900, "10:00"), entry("b", 800, "10:30"), entry("c", 1000, "11:00"), sold]})
    assert row["added_to_loser"] and row["built"] == 1700
    # $900, $1,000 above cost, then an $800 add below cost: that add took it to $2,700.
    [row] = fill_interrupts.history_rows([trade], {"t": [entry("a", 900, "10:00"), entry("b", 1000, "10:30"), entry("c", 800, "11:00"), sold]})
    assert row["built"] == 2700
    # The same adds on a contract with four days left: the rule would not have fired, so nothing was built.
    [row] = fill_interrupts.history_rows([{**trade, "expiration": date(2026, 9, 5)}],
                                         {"t": [entry("a", 900, "10:00"), entry("b", 1000, "10:30"), entry("c", 800, "11:00"), sold]})
    assert row["built"] == 0


def test_two_fills_judged_in_one_pass_say_a_once_per_position_line_once(engine, world, sent):
    clock, interrupts = world
    fill(engine, ny("10:05"), qty=1, price=310, rebuild=False)
    fill(engine, ny("10:06"), qty=1, price=320)  # both emails arrive before the next pass
    tick(clock, interrupts, "10:07")
    assert [r.kinds for r in rows(engine)] == ["put_entry", ""]
    assert len(sent) == 1
