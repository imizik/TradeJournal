from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.models import Account, Trade
from app.routers.daily_review import router

ACCOUNT = UUID(int=1)


def trade(number, pnl, opened, closed, status="closed"):
    return Trade(id=UUID(int=100 + number), account_id=ACCOUNT, ticker="SPY", instrument_type="option",
                 contracts=1, avg_entry_premium=100, total_premium_paid=100,
                 realized_pnl=Decimal(str(pnl)) if pnl is not None else None, pnl_pct=None,
                 opened_at=opened, closed_at=closed, status=status)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ACCOUNT, name="Individual", type="individual", last4="1113"))
        session.add_all([
            # Two closes on Sep 1 sum, cents kept: 100.10 - 40.05.
            trade(1, "100.10", datetime(2026, 9, 1, 9, 31), datetime(2026, 9, 1, 10, 0)),
            trade(2, "-40.05", datetime(2026, 9, 1, 9, 45), datetime(2026, 9, 1, 11, 0)),
            # Opened Sep 1, closed Sep 2: its P&L belongs to Sep 2 only.
            trade(3, "25", datetime(2026, 9, 1, 15, 0), datetime(2026, 9, 2, 9, 40)),
            # An expiry counts like a close.
            trade(4, "-300", datetime(2026, 9, 2, 10, 0), datetime(2026, 9, 2, 16, 0), status="expired"),
            # Opened Sep 3 and still open: a trade day with nothing closed.
            trade(5, None, datetime(2026, 9, 3, 10, 0), None, status="open"),
            # Closed Sep 4 without a recorded P&L: never counted as zero.
            trade(6, None, datetime(2026, 9, 4, 10, 0), datetime(2026, 9, 4, 11, 0)),
        ])
        session.commit()

    def override():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/daily-review")
    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def test_each_day_carries_the_realized_pnl_of_what_closed_that_day(client):
    days = {item["day"]: item for item in client.get("/daily-review").json()}
    assert days["2026-09-01"]["closed_pnl"] == 60.05
    assert days["2026-09-01"]["trade_count"] == 3
    assert days["2026-09-02"]["closed_pnl"] == -275.0
    assert days["2026-09-03"]["closed_pnl"] is None
    assert days["2026-09-04"]["closed_pnl"] is None
