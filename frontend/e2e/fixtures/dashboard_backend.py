"""Offline quotes for the existing seeded browser harness, never the real app."""
from pathlib import Path
import asyncio
import os

# A mistaken app target must fail closed rather than put fixture prices on a
# real journal. The Playwright config recreates this database every invocation.
expected = Path(__file__).resolve().parents[3] / "backend/data/e2e_seed.db"
if os.environ.get("DATABASE_URL") != f"sqlite:///{expected}":
    raise RuntimeError("Browser quote fixture requires the disposable e2e database")

from fastapi import HTTPException
from starlette.responses import JSONResponse
from app.engine.quotes import OptionQuoteResult
from app.main import app as core_app
from app.routers import quotes

state = "ready"


@core_app.post("/__test/scanner-amzn", include_in_schema=False)
def scanner_amzn():
    """Monday's AMZN rules paper trade: 10:10 bar close, 10:11:10 entry, 10:55:54 target exit."""
    import json
    from datetime import date, datetime
    from sqlmodel import Session, select
    from app.database import engine
    from app.models import ScannerCandidate, ScannerEvent

    with Session(engine) as db:
        if db.exec(select(ScannerCandidate).where(ScannerCandidate.symbol == "AMZN", ScannerCandidate.session_date == date(2026, 10, 19))).first():
            return {"seeded": False}
        contract = {"symbol": "AMZN261023C00220000", "expiration": "2026-10-23", "option_type": "call", "strike": 220.0,
                    "delta": 0.35, "bid": 1.75, "ask": 1.80, "multiplier": 100}
        c = ScannerCandidate(scanner_version="s1-v1", params_hash="0" * 64, session_date=date(2026, 10, 19), symbol="AMZN", setup="orb",
                             direction="long", bar_start=datetime(2026, 10, 19, 14, 5), bar_end=datetime(2026, 10, 19, 14, 10),
                             detected_at=datetime(2026, 10, 19, 14, 10, 31), expires_at=datetime(2026, 10, 19, 14, 20), stop=219.10,
                             target=222.40, facts_json="{}", contract_json=json.dumps(contract), source="e2e")
        db.add(c)
        db.flush()
        for kind, at, data in (("entry", datetime(2026, 10, 19, 14, 11, 10), {"ask": 1.80, "bid": 1.75}),
                               ("exit_intent", datetime(2026, 10, 19, 14, 55, 30), {"reason": "target"}),
                               ("exit", datetime(2026, 10, 19, 14, 55, 54), {"bid": 4.70, "ask": 4.80, "reason": "target", "pnl": 288.70,
                                                                             "pnl_2x_spread": 268.70, "return_on_premium": 1.6})):
            db.add(ScannerEvent(candidate_id=c.id, key=kind, event_type=kind, effective_at=at, recorded_at=at, data_json=json.dumps(data)))
        db.commit()
    return {"seeded": True}


@core_app.post("/__test/dashboard-state", include_in_schema=False)
def dashboard_state(value: str):
    global state
    if value not in {"ready", "quotes_unavailable", "quotes_error", "journal_error", "slow"}:
        raise HTTPException(400, "Invalid fixture state")
    state = value
    return {"state": state}


async def app(scope, receive, send):
    # Forward untouched ASGI messages for every other route, including chart
    # streams and lifespan. Fault injection must not alter their transport.
    if scope["type"] == "http" and scope["path"] == "/trades" and scope["method"] == "GET":
        if state == "journal_error":
            await JSONResponse({"detail": "Fixture journal unavailable"}, status_code=503)(scope, receive, send)
            return
        if state == "slow":
            await asyncio.sleep(2)
    await core_app(scope, receive, send)


def stock_quotes(tickers):
    if state == "quotes_error":
        raise HTTPException(503, "Fixture quotes unavailable")
    prices = {"RNXT": 1.20, "AAPL": 240.00}
    return {ticker: prices.get(ticker) if state != "quotes_unavailable" else None for ticker in tickers}


def option_quotes(requests):
    if state == "quotes_error":
        raise HTTPException(503, "Fixture quotes unavailable")
    if state == "quotes_unavailable":
        return [OptionQuoteResult() for _ in requests]
    return [OptionQuoteResult(last_price=3.0, bid=2.9, ask=3.1, mid=3.0) for _ in requests]


quotes.get_stock_quotes = stock_quotes
quotes.get_option_quotes = option_quotes

# Loaded only behind the disposable database guard above, never by app.main.
from e2e.fixtures.day_journal_review import install as install_day_journal_fixture
install_day_journal_fixture(core_app)
