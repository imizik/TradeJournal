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
from app.main import app
from app.routers import quotes

state = "ready"


@app.post("/__test/dashboard-state", include_in_schema=False)
def dashboard_state(value: str):
    global state
    if value not in {"ready", "quotes_unavailable", "quotes_error", "journal_error", "slow"}:
        raise HTTPException(400, "Invalid fixture state")
    state = value
    return {"state": state}


@app.middleware("http")
async def journal_state(request, call_next):
    if request.url.path == "/trades":
        if state == "journal_error":
            return JSONResponse({"detail": "Fixture journal unavailable"}, status_code=503)
        if state == "slow":
            await asyncio.sleep(2)
    return await call_next(request)


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
