from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.engine.quotes import (
    get_stock_quotes,
    get_option_quotes,
    OptionQuoteRequest,
)

router = APIRouter()


class OptionPosition(BaseModel):
    ticker: str
    expiration: str
    strike: float
    option_type: str  # "call" | "put"


class PositionQuoteRequest(BaseModel):
    positions: list[OptionPosition]


class PositionQuote(BaseModel):
    ticker: str
    underlying_price: float | None = None
    option_last_price: float | None = None
    option_bid: float | None = None
    option_ask: float | None = None
    option_mid: float | None = None
    option_iv: float | None = None


@router.get("")
async def stock_quotes(tickers: str = Query(..., description="Comma-separated tickers")):
    """Return current stock prices. Example: GET /quotes?tickers=NVDA,SPY"""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return {}
    return get_stock_quotes(ticker_list)


@router.post("/positions")
async def position_quotes(body: PositionQuoteRequest) -> list[PositionQuote]:
    """Return underlying prices + option premiums for a list of open positions.

    This is the main endpoint used by the dashboard to price open positions.
    It batch-fetches underlying stock prices and option chain data.
    """
    if not body.positions:
        return []

    # Get unique underlying tickers for stock quotes
    tickers = list({p.ticker.upper() for p in body.positions})
    stock_prices = get_stock_quotes(tickers)

    # Get option premiums
    option_reqs = [
        OptionQuoteRequest(
            ticker=p.ticker,
            expiration=p.expiration,
            strike=p.strike,
            option_type=p.option_type,
        )
        for p in body.positions
    ]
    option_results = get_option_quotes(option_reqs)

    results = []
    for pos, opt in zip(body.positions, option_results):
        results.append(PositionQuote(
            ticker=pos.ticker.upper(),
            underlying_price=stock_prices.get(pos.ticker.upper()),
            option_last_price=opt.last_price,
            option_bid=opt.bid,
            option_ask=opt.ask,
            option_mid=opt.mid,
            option_iv=opt.iv,
        ))

    return results
