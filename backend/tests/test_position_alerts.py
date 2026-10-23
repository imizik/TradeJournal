"""Open-trade phone alerts: give-back after a gain, and last-day expiry. Phone only;
nothing here places or changes an order."""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import ntfy, position_alerts, reconstructor
from app.engine.chart_math import ET
from app.engine.position_alerts import PositionAlerts
from app.engine.tradier import TradierError, TradierQuote
from app.models import Account, Fill, PositionAlert, PositionWatch, Trade
from app.routers import position_alerts as position_alerts_router
from app.routers.fills import _rebuild_trades

ROTH = UUID(int=1)
WED = date(2026, 10, 21)
FRI = date(2026, 10, 23)
OCC = "SNDK261023C00230000"
n = iter(range(100, 10_000))


def at(day: date, hhmm: str) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    def __init__(self, close=960, status="open"):
        self.close, self.status = close, status

    def hours(self, day):
        return {"status": self.status, "open": 570, "close": self.close}


class Quotes:
    """Tradier's per-share bid and ask for the contract, quoted ``age`` seconds before the clock."""

    def __init__(self, clock):
        self.clock, self.bid, self.ask, self.age, self.ask_age, self.calls, self.fail = clock, None, None, 5, 5, 0, False

    def set(self, bid, ask=None):
        self.bid, self.ask = bid, ask if ask is not None else round(bid + 0.04, 2)

    def __call__(self, symbols):
        self.calls += 1
        if self.fail:
            raise TradierError("down")
        if self.bid is None:
            return {}
        bid_at, ask_at = int((self.clock() - self.age) * 1000), int((self.clock() - self.ask_age) * 1000)
        return {s: TradierQuote(symbol=s, bid=self.bid, ask=self.ask, bid_date=bid_at, ask_date=ask_at) for s in symbols}


def fill(db, side, qty, price, when, expiration=FRI, account_id=ROTH):
    i = next(n)
    db.add(Fill(id=UUID(int=i), account_id=account_id, ticker="SNDK", instrument_type="option", side=side, contracts=qty, price=price,
                executed_at=datetime.fromisoformat(when), raw_email_id=f"gmail:{i}", option_type="call", strike=230,
                expiration=expiration))
    db.commit()
    _rebuild_trades(db, "test")
    db.commit()


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture(autouse=True)
def on_wednesday(monkeypatch):
    """Trade rebuilds expire contracts past the machine's own date; these trades are held on WED, whatever today is."""
    monkeypatch.setattr(reconstructor, "date", _Wednesday)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def world(engine):
    clock = Clock(at(WED, "10:00"))
    quotes = Quotes(clock)
    watcher = PositionAlerts(engine, Calendar(), clock=clock, quotes=quotes)
    return clock, quotes, watcher


def step(clock, watcher, seconds=31):
    clock.now += seconds
    watcher.run()


def alerts(engine):
    with Session(engine) as db:
        return db.exec(select(PositionAlert).order_by(PositionAlert.detected_at)).all()


def test_a_gain_given_back_sends_one_alert(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")  # $800 in
    quotes.set(4.50)  # mid $4.52: +13%, +$104 -> armed
    step(clock, watcher)
    quotes.set(5.00)  # mid $5.02: peak +$204
    step(clock, watcher)
    assert alerts(engine) == []
    quotes.set(4.10)  # mid $4.12: +3% -> fires
    step(clock, watcher)
    quotes.set(3.90)
    step(clock, watcher)
    found = alerts(engine)
    assert [a.kind for a in found] == ["giveback"]
    a = found[0]
    assert (a.contracts, a.avg_cost, a.mark, a.bid, a.gain, a.peak_gain) == (2, 400, 412, 410, 24, 204)
    title, body, _ = position_alerts.message(a)
    assert title == "SNDK 10/23/26 230C: gave back its gain"
    assert body == "Was up +$204 (+26%), now +$24 (+3%) at a $4.12 mid, bid $4.10. 2 contracts open. Close it or decide."


def test_a_small_position_never_arms_on_percent_alone(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 100, "2026-10-21T09:45")  # $100 in
    quotes.set(1.30)  # +32%, but +$32
    step(clock, watcher)
    quotes.set(0.95)
    step(clock, watcher)
    assert alerts(engine) == []


def test_floorless_exception_and_position_alerts_are_off_by_default(monkeypatch):
    monkeypatch.delenv("POSITION_ALERTS_ENABLED", raising=False)
    monkeypatch.delenv("POSITION_ALERTS_FLOORLESS_ACCOUNT_ID", raising=False)
    assert position_alerts.enabled() is False
    assert position_alerts.floorless_giveback({"account_id": ROTH, "trade": None}) is False


def test_buying_more_re_arms_and_selling_part_keeps_it_armed(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")
    quotes.set(4.60)
    step(clock, watcher)
    quotes.set(4.00)
    step(clock, watcher)
    assert [(a.kind, a.generation) for a in alerts(engine)] == [("giveback", 0)]
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T10:03")  # a new cost and a new arming
    quotes.set(4.40)
    step(clock, watcher)
    with Session(engine) as db:
        fill(db, "sell_to_close", 3, 440, "2026-10-21T10:04")  # one left: still armed
    quotes.set(4.00)
    step(clock, watcher)
    assert [(a.kind, a.generation, a.contracts) for a in alerts(engine)] == [("giveback", 0, 2), ("giveback", 1, 1)]


def test_an_unfit_quote_is_not_judged(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")
    quotes.set(4.60)
    step(clock, watcher)
    quotes.set(2.00, 6.00)  # mid $4.00 but the spread is 100% of it
    step(clock, watcher)
    quotes.set(4.00)
    quotes.age = 300  # a five-minute-old bid
    step(clock, watcher)
    quotes.age, quotes.ask_age = 5, 300  # a fresh bid beside a stale ask
    step(clock, watcher)
    quotes.ask_age, quotes.fail = 5, True
    step(clock, watcher)
    assert alerts(engine) == []
    quotes.fail = False
    step(clock, watcher)
    assert [a.kind for a in alerts(engine)] == ["giveback"]


def test_nothing_is_read_outside_regular_hours_or_on_a_closed_day(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")
    quotes.set(4.60)
    clock.now = at(WED, "09:20")
    watcher.run()
    clock.now = at(WED, "16:05")
    watcher.run()
    watcher.calendar = Calendar(status="closed")
    clock.now = at(WED, "11:00")
    watcher.run()
    assert quotes.calls == 0


def test_the_peak_survives_a_restart(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")
    quotes.set(4.60)
    step(clock, watcher)
    restarted = PositionAlerts(engine, Calendar(), clock=clock, quotes=quotes)
    quotes.set(4.00)
    step(clock, restarted)
    assert [(a.kind, a.peak_gain) for a in alerts(engine)] == [("giveback", 124)]


def test_a_trade_rebuild_does_not_send_again(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")
    quotes.set(4.60)
    step(clock, watcher)
    quotes.set(4.00)
    step(clock, watcher)
    with Session(engine) as db:
        _rebuild_trades(db, "test")
        db.commit()
    step(clock, watcher)
    assert len(alerts(engine)) == 1


def test_last_day_alerts_at_ninety_and_thirty_minutes_before_the_close(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 3, 150, "2026-10-21T10:00", expiration=WED)
    quotes.set(0.40)
    for hhmm in ("14:29", "14:30", "14:45", "15:30", "15:50"):
        clock.now = at(WED, hhmm)
        watcher.run()
    found = alerts(engine)
    assert [a.kind for a in found] == ["expiry_first", "expiry_final"]
    assert [datetime.fromtimestamp(a.detected_at.replace(tzinfo=UTC).timestamp(), ET).strftime("%H:%M") for a in found] == ["14:30", "15:30"]
    title, body, priority = position_alerts.message(found[1], "4:00 PM", 30)
    assert title == "SNDK 10/21/26 230C: 30 minutes left, expires today"
    assert body == "Still open: 3 contracts, now -$324 (-72%) at a $0.42 mid, bid $0.40. The market closes at 4:00 PM."
    assert priority == 5


def test_a_missed_first_expiry_alert_is_not_sent_late_and_half_days_move_both(engine, world):
    clock, quotes, watcher = world
    watcher.calendar = Calendar(close=780)  # a 1:00 PM close
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 150, "2026-10-21T10:00", expiration=WED)
    clock.now = at(WED, "11:29")
    watcher.run()
    clock.now = at(WED, "11:30")
    watcher.run()
    assert [a.kind for a in alerts(engine)] == ["expiry_first"]
    watcher.calendar, watcher._last_run = Calendar(), 0
    with Session(engine) as db:
        db.exec(PositionAlert.__table__.delete())
        db.commit()
    clock.now = at(WED, "15:35")  # the server was down at 14:30
    watcher.run()
    found = alerts(engine)
    assert [a.kind for a in found] == ["expiry_final"] and found[0].mark is None  # no quote: still sent
    assert "no live quote right now" in position_alerts.message(found[0])[1]


def sent_to(monkeypatch, record):
    def publish(title, body, priority=4, tags=(), path=""):
        record.append((title, path))
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", publish)


def fired(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")
    quotes.set(4.60)
    step(clock, watcher)
    quotes.set(4.00)
    step(clock, watcher)
    return alerts(engine)[0]


def test_delivery_sends_once_with_a_link_to_the_trade(engine, world, monkeypatch):
    clock, _, watcher = world
    alert = fired(engine, world)
    sent = []
    sent_to(monkeypatch, sent)
    watcher.deliver()
    watcher.deliver()
    assert sent == [("SNDK 10/23/26 230C: gave back its gain", f"/trades/{alert.trade_id}")]
    assert alerts(engine)[0].delivery == "sent"


def test_a_stale_claim_is_unknown_and_never_resent(engine, world, monkeypatch):
    clock, _, watcher = world
    alert = fired(engine, world)
    with Session(engine) as db:
        row = db.get(PositionAlert, alert.id)
        row.delivery, row.claimed_at = "sending", datetime.fromtimestamp(clock.now - 200, UTC).replace(tzinfo=None)
        db.commit()
    sent = []
    sent_to(monkeypatch, sent)
    watcher.deliver()
    assert sent == [] and alerts(engine)[0].delivery == "unknown"


@pytest.mark.parametrize("cause,outcome", [
    (None, "pending"), (httpx.ConnectError("refused"), "pending"),
    (httpx.ReadTimeout("no answer"), "unknown"), (httpx.RemoteProtocolError("dropped"), "unknown"),
])
def test_only_a_send_that_surely_never_left_is_retried(engine, world, monkeypatch, cause, outcome):
    clock, _, watcher = world
    fired(engine, world)
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")

    def publish(*args, **kwargs):
        if cause is None:
            raise ntfy.NtfyError("ntfy refused the notification (500).")
        raise ntfy.NtfyError("ntfy could not be reached.") from cause
    monkeypatch.setattr(ntfy, "publish", publish)
    watcher.deliver()
    assert alerts(engine)[0].delivery == outcome


def test_an_alert_not_sent_within_fifteen_minutes_expires(engine, world, monkeypatch):
    clock, _, watcher = world
    fired(engine, world)
    monkeypatch.delenv("NTFY_URL", raising=False)
    watcher.deliver()
    assert alerts(engine)[0].delivery == "pending"
    clock.now += 16 * 60
    sent = []
    sent_to(monkeypatch, sent)
    watcher.deliver()
    assert sent == [] and alerts(engine)[0].delivery == "expired"


def test_the_trade_page_reads_this_positions_alerts(engine, world, monkeypatch):
    fired(engine, world)
    monkeypatch.setenv("POSITION_ALERTS_ENABLED", "true")
    app = FastAPI()
    app.include_router(position_alerts_router.router, prefix="/trades")
    with Session(engine) as db:
        trade_id = db.exec(select(Trade.id)).one()
        app.dependency_overrides[get_session] = lambda: db
        body = TestClient(app).get(f"/trades/{trade_id}/phone-alerts").json()
        assert db.exec(select(PositionWatch)).one().armed_at is not None
    assert body["enabled"] is True
    assert body["giveback_dollar_floor_applies"] is True
    assert [(a["kind"], a["gain"], a["peak_gain"], a["delivery"]) for a in body["alerts"]] == [("giveback", 4.0, 124.0, "pending")]
    assert body["watch"] == {"peak_gain": 124.0, "peak_gain_pct": 0.155, "armed": True, "fired": True, "peak_at": body["watch"]["peak_at"]}


def test_trade_page_reports_floorless_exception_for_configured_spy_account(engine, world, monkeypatch):
    fired(engine, world)
    monkeypatch.setenv("POSITION_ALERTS_ENABLED", "true")
    monkeypatch.setenv("POSITION_ALERTS_FLOORLESS_ACCOUNT_ID", str(ROTH))
    app = FastAPI()
    app.include_router(position_alerts_router.router, prefix="/trades")
    with Session(engine) as db:
        trade = db.exec(select(Trade)).one()
        trade.ticker = "SPY"
        db.add(trade)
        db.commit()
        app.dependency_overrides[get_session] = lambda: db
        body = TestClient(app).get(f"/trades/{trade.id}/phone-alerts").json()
    assert body["giveback_dollar_floor_applies"] is False


def test_a_trim_that_changes_the_cost_basis_re_arms_instead_of_alerting(engine, world):
    """Average up, then trim into strength: FIFO sells the cheap lot, so the gain that armed it is gone
    without any price move. That is a new basis, not a give-back."""
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 300, "2026-10-21T09:45")
        fill(db, "buy_to_open", 1, 500, "2026-10-21T09:50")
    quotes.set(4.58)  # mid $4.60 on a $4.00 basis: +15%, +$120 -> armed
    step(clock, watcher)
    with Session(engine) as db:
        fill(db, "sell_to_close", 1, 460, "2026-10-21T10:01")  # sells the $3.00 lot; $5.00 is left
    step(clock, watcher)
    step(clock, watcher)
    assert alerts(engine) == []
    with Session(engine) as db:
        watch = db.exec(select(PositionWatch)).one()
        assert (watch.generation, watch.avg_cost, watch.armed_at) == (1, 500, None)


def test_a_first_expiry_alert_more_than_fifteen_minutes_late_is_skipped(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 150, "2026-10-21T10:00", expiration=WED)
    for hhmm in ("14:45", "15:00", "15:29"):  # the server came up at 14:45
        clock.now = at(WED, hhmm)
        watcher.run()
    assert alerts(engine) == []
    clock.now = at(WED, "15:30")
    watcher.run()
    assert [a.kind for a in alerts(engine)] == ["expiry_final"]


def test_a_contract_too_thin_to_price_shows_its_bid_not_no_quote(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 3, 150, "2026-10-21T10:00", expiration=WED)
    quotes.set(0.05, 0.10)
    clock.now = at(WED, "14:30")
    watcher.run()
    alert = alerts(engine)[0]
    assert (alert.mark, alert.bid) == (None, 5)
    assert position_alerts.message(alert, "4:00 PM")[1] == "3 contracts open, bid $0.05, too thin to price at a midpoint. The market closes at 4:00 PM."


def test_an_expiry_alert_is_never_sent_after_the_close_and_states_the_minutes_left(engine, world, monkeypatch):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 150, "2026-10-21T10:00", expiration=WED)
    clock.now = at(WED, "15:50")
    watcher.run()
    sent = []
    sent_to(monkeypatch, sent)
    clock.now = at(WED, "15:52")
    watcher.deliver()
    assert sent[0][0] == "SNDK 10/21/26 230C: 8 minutes left, expires today"
    with Session(engine) as db:
        db.exec(PositionAlert.__table__.update().values(delivery="pending"))
        db.commit()
    clock.now = at(WED, "16:01")
    watcher.deliver()
    assert len(sent) == 1 and alerts(engine)[0].delivery == "expired"


def test_the_anchor_breaks_same_minute_ties_on_the_source_id_not_the_fill_uuid():
    from types import SimpleNamespace
    when = datetime(2026, 10, 21, 10, 0)
    a = SimpleNamespace(executed_at=when, raw_email_id="gmail:A", id=UUID(int=9))
    b = SimpleNamespace(executed_at=when, raw_email_id="gmail:B", id=UUID(int=1))
    assert position_alerts.anchor([a, b]) == position_alerts.anchor([b, a]) == "gmail:A"

@pytest.mark.parametrize('symbol,account,configured,expected', [
    ('SPY', ROTH, str(ROTH), True),
    ('QQQ', ROTH, str(ROTH), True),
    ('SPY', UUID(int=2), str(ROTH), False),
    ('SNDK', ROTH, str(ROTH), False),
    ('SPY', ROTH, '', False),
    ('SPY', ROTH, 'invalid', False),
])
def test_floorless_account_and_symbol_scope(monkeypatch, symbol, account, configured, expected):
    from types import SimpleNamespace
    monkeypatch.setenv('POSITION_ALERTS_FLOORLESS_ACCOUNT_ID', configured)
    position = {'account_id': account, 'trade': SimpleNamespace(ticker=symbol, instrument_type='option')}
    assert position_alerts.floorless_giveback(position) is expected
    position['trade'].instrument_type = 'stock'
    assert position_alerts.floorless_giveback(position) is False

@pytest.mark.parametrize('symbol,account,configured,should_fire', [
    ('SPY', ROTH, str(ROTH), True),
    ('QQQ', ROTH, str(ROTH), True),
    ('SPY', UUID(int=2), str(ROTH), False),
    ('SPY', ROTH, '', False),
    ('SNDK', ROTH, str(ROTH), False),
])
def test_small_position_floor_exception_lifecycle(engine, world, monkeypatch, symbol, account, configured, should_fire):
    monkeypatch.setenv('POSITION_ALERTS_FLOORLESS_ACCOUNT_ID', configured)
    clock, quotes, watcher = world
    with Session(engine) as db:
        if account != ROTH:
            db.add(Account(id=account, name="Other", type="taxable", last4="0000", broker="robinhood"))
            db.commit()
        fill(db, 'buy_to_open', 1, 100, '2026-10-21T09:45', account_id=account)
        trade = db.exec(select(Trade)).one()
        trade.ticker = symbol
        db.add(trade)
        db.commit()
    quotes.set(1.07)  # midpoint +9% does not arm
    step(clock, watcher)
    with Session(engine) as db:
        assert db.exec(select(PositionWatch)).one().armed_at is None
    quotes.set(1.08)  # midpoint +10%, only $10 gain
    step(clock, watcher)
    quotes.set(1.02)  # midpoint +4%, does not fire
    step(clock, watcher)
    assert alerts(engine) == []
    quotes.set(1.01)  # midpoint +3%
    step(clock, watcher)
    assert len(alerts(engine)) == int(should_fire)



# ---------------------------------------------------------------- held an hour


@pytest.fixture
def hold_on(monkeypatch):
    monkeypatch.setenv("POSITION_ALERTS_ENABLED", "true")
    monkeypatch.setenv("POSITION_HOLD_ALERTS", "true")


def run_at(clock, watcher, day, *times):
    for hhmm in times:
        clock.now = at(day, hhmm)
        watcher.run()


def kinds(engine):
    return [a.kind for a in alerts(engine)]


def test_a_position_held_sixty_minutes_gets_one_re_decide_alert(engine, world, hold_on):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T10:00")
    quotes.set(4.46)  # mid $4.48: +12%, +$48 -- under $50, so give-back never arms
    run_at(clock, watcher, WED, "10:30")
    quotes.set(3.74)  # mid $3.76: -6%
    run_at(clock, watcher, WED, "10:59")
    assert alerts(engine) == []
    run_at(clock, watcher, WED, "11:00", "11:01", "11:10")
    found = alerts(engine)
    assert kinds(engine) == ["hold_hour"]
    title, body, _ = position_alerts.message(found[0])
    assert title == "SNDK 10/23/26 230C: open an hour, re-decide"
    assert body == ("Open 60 min, now -$24 (-6%) at a $3.76 mid, bid $3.74, best seen by the alert watch +$48 (+12%). "
                    "1 contract open. Re-decide: close, trim, or set your exit.")


def test_an_entry_before_the_open_counts_from_nine_thirty(engine, world, hold_on):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T08:15")
    quotes.set(4.00)
    run_at(clock, watcher, WED, "09:45", "10:29")
    assert alerts(engine) == []
    run_at(clock, watcher, WED, "10:30")
    assert kinds(engine) == ["hold_hour"]


def test_a_half_day_close_before_the_hour_skips_it_and_moves_nothing_else(engine, world, hold_on):
    clock, quotes, watcher = world
    watcher.calendar = Calendar(close=780)  # a 1:00 PM close
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T11:30")
        fill(db, "buy_to_open", 1, 400, "2026-10-21T12:10", expiration=date(2026, 10, 30))
    quotes.set(4.00)
    run_at(clock, watcher, WED, "12:30", "12:59")
    assert [a.contract for a in alerts(engine)] == ["SNDK 10/23/26 230C"]  # the 11:30 entry's hour lands before the close


def test_once_per_position_whether_it_is_added_to_before_or_after_the_alert(engine, world, hold_on):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T10:00")
    quotes.set(4.00)
    run_at(clock, watcher, WED, "10:20")
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 300, "2026-10-21T10:25")  # a new basis within the hour: the clock is the first entry's
    run_at(clock, watcher, WED, "10:30", "11:00", "11:01")
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 500, "2026-10-21T11:02")  # a new basis inside the alert's window
    run_at(clock, watcher, WED, "11:03", "11:10", "12:03")
    assert [(a.kind, a.generation) for a in alerts(engine)] == [("hold_hour", 1)]


def test_a_hold_alert_more_than_fifteen_minutes_late_is_skipped(engine, world, hold_on):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T10:00")
    quotes.set(4.00)
    run_at(clock, watcher, WED, "11:15", "11:30")  # the server was down at 11:00
    assert alerts(engine) == []


def test_an_expiry_alert_due_within_fifteen_minutes_wins(engine, world, hold_on):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 150, "2026-10-21T13:25", expiration=WED)  # an hour lands at 14:25, the first expiry at 14:30
    quotes.set(1.50)
    run_at(clock, watcher, WED, "14:25", "14:30", "14:35")
    assert kinds(engine) == ["expiry_first"]
    regular = ("regular", 570, 960)

    def due(hhmm, expires):
        return position_alerts.hold_due(datetime.fromisoformat(f"2026-10-21T{hhmm}"), WED, regular, expires)
    assert (due("12:00", True), due("13:15", True), due("14:20", True), due("14:40", True)) == (780, 855, None, None)
    assert (due("13:25", False), due("15:00", False)) == (865, None)
    assert position_alerts.hold_due(datetime(2026, 10, 20, 15, 30), WED, regular, False) is None  # opened another day


@pytest.mark.parametrize("flags", [{"POSITION_ALERTS_ENABLED": "true"}, {"POSITION_HOLD_ALERTS": "true"}])
def test_the_hold_alert_is_off_without_both_switches(engine, world, monkeypatch, flags):
    clock, quotes, watcher = world
    monkeypatch.delenv("POSITION_ALERTS_ENABLED", raising=False)
    monkeypatch.delenv("POSITION_HOLD_ALERTS", raising=False)
    for name, value in flags.items():
        monkeypatch.setenv(name, value)
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T10:00")
    quotes.set(4.00)
    run_at(clock, watcher, WED, "11:00")
    assert alerts(engine) == []


def test_a_quote_that_cannot_be_judged_still_sends_saying_so(engine, world, hold_on):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T10:00")
    quotes.set(2.00, 6.00)  # a spread of 100% of the midpoint
    run_at(clock, watcher, WED, "11:00")
    found = alerts(engine)
    assert (found[0].kind, found[0].mark, found[0].bid) == ("hold_hour", None, 200)
    assert position_alerts.message(found[0])[1] == ("Open 60 min, no reliable quote, bid $2.00. 1 contract open. "
                                                    "Re-decide: close, trim, or set your exit.")
    found[0].bid = None
    assert position_alerts.message(found[0])[1].startswith("Open 60 min, no reliable quote. 1 contract open.")


def test_hold_alert_delivery_is_at_most_once(engine, world, hold_on, monkeypatch):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 400, "2026-10-21T10:00")
    quotes.set(4.00)
    run_at(clock, watcher, WED, "11:00")
    alert = alerts(engine)[0]
    sent = []
    sent_to(monkeypatch, sent)
    watcher.deliver()
    watcher.deliver()
    assert sent == [("SNDK 10/23/26 230C: open an hour, re-decide", f"/trades/{alert.trade_id}")]
    with Session(engine) as db:
        row = db.get(PositionAlert, alert.id)
        row.delivery, row.claimed_at = "sending", datetime.fromtimestamp(clock.now - 200, UTC).replace(tzinfo=None)
        db.commit()
    watcher.deliver()
    assert len(sent) == 1 and alerts(engine)[0].delivery == "unknown"
