"""Stored-results and private-route checks; no market data involved."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine.symbol_info import journal_summary
from app.models import Account, Fill, Trade
from app.routers import symbol_info


def record(index, status="closed", pnl=Decimal("10.25"), hold=0):
    return {"id": str(UUID(int=index)), "status": status, "realized_pnl": pnl,
            "hold_duration_mins": hold, "opened_at": "2026-09-01T09:30:00",
            "closed_at": "2026-09-01T10:30:00" if status != "open" else None}


def test_completed_results_include_expirations_and_breakeven_but_not_partial_open_pnl():
    rows = [record(1), record(2, "expired", Decimal("-5.15"), 60),
            record(3, pnl=Decimal("0"), hold=None), record(4, "open", Decimal("900"))]
    data = journal_summary("SPY", rows, "2026-09-01T10:30:00")
    assert data["closed_trades"] == 3 and data["total_trades"] == 4
    assert data["realized_pnl"] == 5.1 and data["win_rate"] == 1 / 3
    assert data["average_hold_mins"] == 30 and data["hold_samples"] == 2
    assert data["best_trade"]["id"] == rows[0]["id"]
    assert data["worst_trade"]["status"] == "expired"
    assert data["open_positions"][0]["realized_pnl"] == 900


def test_missing_results_and_empty_history_are_not_reported_as_zero():
    data = journal_summary("SPY", [record(1, pnl=None), record(2)], None)
    assert data["missing_pnl"] == 1 and data["realized_pnl"] is None and data["win_rate"] is None
    assert data["best_trade"]["id"] == record(2)["id"]
    empty = journal_summary("SPY", [], None)
    assert empty["total_trades"] == 0 and empty["average_hold_mins"] is None
    assert empty["realized_pnl"] is None and empty["best_trade"] is None


def test_recent_trades_have_a_deterministic_five_record_limit():
    data = journal_summary("SPY", [record(i) for i in range(1, 9)], None)
    assert [t["id"] for t in data["recent_trades"]] == [str(UUID(int=i)) for i in range(8, 3, -1)]


def test_route_filters_underlying_keeps_accounts_and_uses_two_queries():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(symbol_info.router, prefix="/charts")
    with Session(engine) as db:
        app.dependency_overrides[get_session] = lambda: db
        for index in (1, 2):
            db.add(Account(id=UUID(int=index), name=f"Account {index}", type="individual", last4=str(index)))
        db.commit()
        for index, ticker, status in [(1, "SPY", "closed"), (2, "SPY", "open"), (3, "QQQ", "closed")]:
            db.add(Trade(id=UUID(int=100 + index), account_id=UUID(int=2 if index == 2 else 1),
                         ticker=ticker, instrument_type="option", contracts=1, option_type="call",
                         strike=500, avg_entry_premium=100, total_premium_paid=100,
                         realized_pnl=Decimal("10.25"), status=status, opened_at=datetime(2026, 9, 1, 9, 30),
                         closed_at=datetime(2026, 9, 2, 16) if status == "closed" else None))
        db.add(Fill(id=UUID(int=500), account_id=UUID(int=1), ticker="SPY", instrument_type="option",
                    side="sell_to_close", contracts=1, price=100, raw_email_id="test:symbol",
                    executed_at=datetime(2026, 9, 1, 10, 15)))
        db.commit()
        queries = []
        event.listen(engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
        with TestClient(app) as client:
            response = client.get("/charts/symbol/spy/you")
            assert response.status_code == 200
            data = response.json()
            assert len(queries) == 2  # no account/fill queries per trade
            assert "ai_review" not in queries[0]
            assert data["symbol"] == "SPY" and data["total_trades"] == 2
            assert data["realized_pnl"] == 10.25 and data["closed_trades"] == 1
            assert data["open_positions"][0]["account_name"] == "Account 2"
            assert data["last_traded_at"] == "2026-09-01T10:15:00"  # not the synthetic close
            assert data["time_zone"] == "America/New_York" and data["as_of"].endswith("+00:00")
            assert client.get("/charts/symbol/IWM/you").json()["total_trades"] == 0
            assert client.get("/charts/symbol/BRK%2FB/you").json()["symbol"] == "BRK/B"
            assert client.get("/charts/symbol/bad%24/you").status_code == 422
    engine.dispose()
