"""The plan streak: entries planned before entry, newest first, in Robinhood accounts;
a suggested plan holds the streak open for 30 minutes, a late plan breaks it."""

import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import capture_links, plan_streak
from app.engine.captures import profile
from app.models import Account, Fill, Trade, TradeCapture, TradeFill
from app.routers import captures as captures_router
from app.routers.fills import _rebuild_trades

ROTH = UUID(int=1)
WEBULL = UUID(int=2)
INDIVIDUAL = UUID(int=3)
LATER = date(2099, 1, 15)
n = iter(range(100, 10_000))
# Friday September 18, 2026, 11:00 in New York (EDT, UTC-4).
NOW = datetime(2026, 9, 18, 15, 0)


def entry(db, at: str, strike: float, account=ROTH) -> Trade:
    """One opening NVDA call fill at a New York wall clock, rebuilt into its own trade."""
    i = next(n)
    db.add(Fill(id=UUID(int=i), account_id=account, ticker="NVDA", instrument_type="option", side="buy_to_open", contracts=1,
                price=1.0, executed_at=datetime.fromisoformat(at), raw_email_id=f"streak:{i}", option_type="call", strike=strike, expiration=LATER))
    db.commit()
    _rebuild_trades(db, "test")
    return db.get(Trade, db.exec(select(TradeFill).where(TradeFill.fill_id == UUID(int=i))).one().trade_id)


def plan(db, received_utc: str, strike: float, trade: Trade | None = None) -> TradeCapture:
    """A plan received at a UTC time, linked to ``trade`` when given."""
    row = TradeCapture(client_id=f"client-{next(n)}", received_at=datetime.fromisoformat(received_utc), account_id=ROTH, account_label="Roth",
                       underlying="NVDA", side="buy_calls", instrument="option", mode="template", strike=strike, expiration=LATER,
                       context_state="unavailable", image_state="unavailable")
    db.add(row)
    db.commit()
    db.refresh(row)
    if trade is not None:
        capture_links.link(db, row, trade.id)
    return row


def planned(db, at: str, strike: float, minutes_before: int = 5, account=ROTH) -> Trade:
    trade = entry(db, at, strike, account)
    received = datetime.fromisoformat(at) + timedelta(hours=4) - timedelta(minutes=minutes_before)
    plan(db, received.isoformat(), strike, trade)
    return trade


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267"))
        session.add(Account(id=WEBULL, name="Webull", type="individual", last4="2222", broker="webull"))
        session.add(Account(id=INDIVIDUAL, name="Individual", type="individual", last4="1111", broker="robinhood"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def week(db):
    """Two weeks of entries, oldest first, ending in a pending one."""
    planned(db, "2026-08-03T10:00", 890)  # older than 30 days: out of the default window
    planned(db, "2026-09-10T10:00", 898)
    planned(db, "2026-09-11T10:00", 899)
    planned(db, "2026-09-14T09:40", 900)  # Monday
    planned(db, "2026-09-14T10:00", 901)
    entry(db, "2026-09-15T10:00", 902)  # no plan: breaks
    planned(db, "2026-09-16T10:00", 903)
    late = entry(db, "2026-09-16T11:00", 904)
    plan(db, "2026-09-16T15:10:00", 904, late)  # saved ten minutes after entry: late, breaks
    planned(db, "2026-09-17T10:00", 905)
    planned(db, "2026-09-17T10:30", 906)
    planned(db, "2026-09-17T11:00", 907)
    entry(db, "2026-09-18T09:45", 950, account=WEBULL)  # Webull: never counted
    entry(db, "2026-09-18T10:45", 908)
    plan(db, "2026-09-18T14:40:00", 908)  # suggested, not linked: pending
    return db


def test_streak_counts_pre_entry_plans_and_breaks_on_late_or_missing(week):
    result = plan_streak.streak(week, NOW)
    assert result["show"] is True and result["tracking"] is False
    # Newest first: 908 is pending, then 907, 906, 905 planned, then 904's late plan breaks it.
    assert result["current"] == 3
    assert result["pending"] == 1
    # 9/10, 9/11, 9/14 ×2; the August entry is outside the 30-day window.
    assert result["best"] == 4
    assert result["last_break"] == {"contract": "NVDA 1/15/99 904C", "short": "NVDA 904C",
                                    "entry_time": int(datetime(2026, 9, 16, 15, 0, tzinfo=UTC).timestamp()), "reason": "late"}
    # Monday 9/14 to Friday 9/18 in New York; Webull is out.
    assert result["this_week"]["planned"] == 6
    assert result["this_week"]["total"] == 9
    assert result["this_week"]["pending"] == 1


def test_pending_expires_after_thirty_minutes_and_linking_extends(week):
    later = NOW + timedelta(minutes=20)  # 11:20, 35 minutes after the 10:45 entry
    result = plan_streak.streak(week, later)
    assert result["current"] == 0 and result["pending"] == 0
    assert result["last_break"]["short"] == "NVDA 908C" and result["last_break"]["reason"] == "no_plan"
    suggested = week.exec(select(TradeCapture).where(TradeCapture.strike == 908)).one()
    trade = week.exec(select(Trade).where(Trade.strike == 908)).one()
    capture_links.link(week, suggested, trade.id)
    result = plan_streak.streak(week, later)
    assert result["current"] == 4
    assert result["last_break"]["short"] == "NVDA 904C"


def test_week_is_monday_to_friday_in_new_york(week):
    # Sunday 23:00 in New York is Monday 03:00 UTC: still last week.
    assert plan_streak.streak(week, datetime(2026, 9, 21, 3, 0))["this_week"]["total"] == 9
    # Monday 00:30 in New York starts a new week.
    fresh = plan_streak.streak(week, datetime(2026, 9, 21, 4, 30))["this_week"]
    assert fresh["total"] == 0 and fresh["planned"] == 0
    # In winter New York is UTC-5: Monday 04:30 UTC is still Sunday there.
    assert plan_streak._week(datetime(2026, 11, 9, 4, 30))[0] == datetime(2026, 11, 2)
    assert plan_streak._week(datetime(2026, 11, 9, 5, 30))[0] == datetime(2026, 11, 9)


def test_tracking_sets_the_start_and_the_accounts(week):
    entry(week, "2026-09-18T10:50", 960, account=INDIVIDUAL)  # unplanned, another Robinhood account
    assert plan_streak.streak(week, NOW)["current"] == 0
    row = profile(week)
    row.tracking_since = datetime(2026, 9, 16, 12, 0)
    row.tracking_accounts = f'["{ROTH}"]'
    week.add(row)
    week.commit()
    result = plan_streak.streak(week, NOW)
    assert result["tracking"] is True
    assert result["current"] == 3
    # From 9/16 08:00 New York: 903, then 904 late, 905–907.
    assert result["best"] == 3
    assert result["this_week"]["total"] == 6


def test_hidden_until_tracking_or_a_plan_exists(db):
    entry(db, "2026-09-17T10:00", 905)
    result = plan_streak.streak(db, NOW)
    assert result["show"] is False and result["current"] == 0
    assert result["last_break"]["reason"] == "no_plan"
    plan(db, "2026-09-18T12:00:00", 999)
    assert plan_streak.streak(db, NOW)["show"] is True


def test_route_returns_no_ids(week, monkeypatch):
    class Clock(datetime):
        @staticmethod
        def utcnow():
            return NOW

    monkeypatch.setattr(plan_streak, "datetime", Clock)
    app = FastAPI()
    app.include_router(captures_router.router, prefix="/charts")
    app.dependency_overrides[get_session] = lambda: week
    with TestClient(app) as client:
        response = client.get("/charts/captures/streak")
    assert response.status_code == 200
    assert response.json()["current"] == 3
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", response.text)
    assert "id" not in {key.split("_")[-1] for key in response.json()}
