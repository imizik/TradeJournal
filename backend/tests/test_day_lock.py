"""Real-money day lock: one ping at down 3% on the day, one green walk-away ping when he goes flat green. Phone only."""

from datetime import date, datetime
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import day_lock, ntfy
from app.engine.chart_math import ET
from app.engine.day_lock import DayLock
from app.models import Account, PhonePing, Trade

ROTH, WEBULL = UUID(int=1), UUID(int=3)
WED = date(2026, 10, 21)


def at(hhmm: str) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(WED.year, WED.month, WED.day, h, m, tzinfo=ET).timestamp()


def ny(hhmm: str) -> datetime:
    return datetime.combine(WED, datetime.strptime(hhmm, "%H:%M").time())


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


@pytest.fixture(autouse=True)
def quiet_env(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERT_APP_URL", "DAY_LOCK_ALERTS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
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


def trade(engine, opened: str, closed: str | None, pnl: float | None, account=ROTH):
    with Session(engine) as db:
        db.add(Trade(account_id=account, ticker="NBIS", instrument_type="option", contracts=1, option_type="call", strike=100,
                     expiration=WED, avg_entry_premium=100, total_premium_paid=100, realized_pnl=pnl, opened_at=ny(opened),
                     closed_at=ny(closed) if closed else None, status="closed" if closed else "open"))
        db.commit()


def lock(engine, now: str, accounts=None) -> DayLock:
    return DayLock(engine, Calendar(), clock=lambda: at(now), accounts=lambda: accounts)


def test_switch_is_off_by_default(monkeypatch):
    assert not day_lock.enabled()
    monkeypatch.setenv("DAY_LOCK_ALERTS", "true")
    assert day_lock.enabled()


def test_day_figures_and_the_three_percent_line():
    # $10,000 this morning: realized -$200 and -$100 still open leaves $9,700 now, -3.0%.
    figures = day_lock.day_figures(-200, [{"total_value": 6000, "day_change": -60}, {"total_value": 3700, "day_change": -40}])
    assert figures == {"pnl": -300, "pct": -3.0, "start": 10000, "complete": True}
    assert day_lock.loss_due(figures)
    assert not day_lock.loss_due(day_lock.day_figures(-200, [{"total_value": 9790, "day_change": -90}]))  # -2.9%
    # Any unknown figure: no percent, never a guess.
    unknown = day_lock.day_figures(-900, [{"total_value": 6000, "day_change": None}])
    assert unknown["pct"] is None and not day_lock.loss_due(unknown)
    assert not day_lock.loss_due(day_lock.day_figures(-900, None))


def test_loss_lock_pings_once_a_day(engine, sent):
    trade(engine, "09:40", "10:10", -250)
    trade(engine, "09:40", "10:20", -5000, account=WEBULL)  # Webull is left out
    accounts = [{"total_value": 9700, "day_change": -50}]
    lock(engine, "10:30", accounts).run()
    assert len(sent) == 1 and sent[0][0].startswith("Down −$300 today (-3.0%): your 3% day lock")
    assert sent[0][2]["priority"] == 5
    again = lock(engine, "10:45", accounts)  # a restart the same day: the claim holds
    again.run()
    assert len(sent) == 1
    with Session(engine) as db:
        assert db.exec(select(PhonePing.source_id).where(PhonePing.sender == "day_lock")).all() == [f"day_loss:{WED.isoformat()}"]


def test_no_loss_ping_without_the_feed_or_outside_the_session(engine, sent):
    trade(engine, "09:40", "10:10", -5000)
    lock(engine, "10:30", None).run()
    lock(engine, "16:05", [{"total_value": 5000, "day_change": 0}]).run()
    assert sent == []


def test_green_walk_away_when_flat_after_a_green_close(engine, sent):
    trade(engine, "09:40", "10:10", 400)
    trade(engine, "10:15", None, None)  # still open: not flat yet
    lock(engine, "10:20", [{"total_value": 10400, "day_change": 0}]).run()
    assert sent == []
    with Session(engine) as db:
        db.exec(select(Trade).where(Trade.status == "open")).one().status = "closed"
        open_one = db.exec(select(Trade).where(Trade.realized_pnl.is_(None))).one()
        open_one.realized_pnl, open_one.closed_at = 50, ny("10:25")
        db.commit()
    lock(engine, "10:30", [{"total_value": 10450, "day_change": 0}]).run()
    assert len(sent) == 1 and sent[0][0] == "Green on the day +$450: walk away"
    lock(engine, "10:31", None).run()
    assert len(sent) == 1


def test_green_needs_a_fresh_close_and_a_green_day(engine, sent):
    trade(engine, "09:40", "10:10", 400)
    lock(engine, "11:00", None).run()  # 50 minutes after the close: not the moment he went flat
    assert sent == []
    figures = day_lock.day_figures(400, [{"total_value": 9000, "day_change": -500}])  # swing positions take the day red
    assert not day_lock.green_due(400, figures, 0, ny("10:10"), ny("10:15"))
    assert day_lock.green_due(400, day_lock.day_figures(400, None), 0, ny("10:10"), ny("10:15"))
