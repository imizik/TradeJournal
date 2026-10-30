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


# ------------------------------------------------------------------ the pass

def test_the_seeded_day_one_message_per_fill(engine, world, sent):
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
        ("NBIS 10/23/26 160P", "put_entry,opened_green,late_short_dated", "sent"),
        ("NBIS 10/23/26 160P", "add_to_loser", "sent"),  # the position's other lines were already said
    ]
    assert [(t, b) for t, b, _ in sent] == [
        ("Pattern: CRWV", "Day already green (+$200 today): 1 past trade opened green, too few to read\nYour record, not advice."),
        ("Pattern: NBIS 160P", "Put entry: puts −$350 over 6 trades; calls +$150 over 5\n"
                               "Day already green (+$200 today): 1 past trade opened green, too few to read\n"
                               "Late short-dated buy: 1 past buy after 2 PM with 0–2 days left, too few to read\n"
                               "Your record, not advice."),
        ("Pattern: NBIS 160P", "Adding to a loser: 1 past add, too few to read\nYour record, not advice."),
    ]
    add = found[3]
    kw = sent[2][2]
    assert kw["path"] == f"/trades/{add.trade_id}?interrupt={add.id}" and kw["more"] == (("Noted", f"/trades/{add.trade_id}?interrupt={add.id}&noted=1"),)
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


def test_scaling_in_repeats_only_adding_to_a_loser(engine, world, sent):
    clock, interrupts = world
    fill(engine, ny("14:05"), qty=1, price=310)
    tick(clock, interrupts, "14:06")
    fill(engine, ny("14:20"), qty=1, price=320)  # above cost: the put and late-buy lines were already said
    tick(clock, interrupts, "14:21")
    fill(engine, ny("14:40"), qty=1, price=250)  # below cost
    tick(clock, interrupts, "14:41")
    assert [(r.kinds, r.delivery) for r in rows(engine)] == [("put_entry,late_short_dated", "sent"), ("", "none"), ("add_to_loser", "sent")]
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
