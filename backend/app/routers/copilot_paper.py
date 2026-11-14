"""The owner's own paper book on the desk (``engine/paper_book.py``, docs/copilot-lab.md § Paper).

``GET /copilot/paper``: the paper account, its open positions at the desk's newest prices, closed trades and the
scorecard beside his real closed trades over the same dates, and ``review``: the newest Friday paper review
(``engine/paper_review.py``), shown until the next one. One of the desk's minute reads; it settles an expired option at
its close and otherwise only reads.
``POST /copilot/paper/runs``: start the paper account (``starting_cash``, default $10,000), or with ``reset`` a new run;
every older run keeps its history.
``POST /copilot/paper/orders``: open (``action: open``) or close/trim (``action: close``) a paper position at the live
quote (an opening order names whose idea it was: ``source`` mine, copilot, radar or scanner, and ``idea_id``), or with ``order_type: limit`` and ``limit_price`` place a day limit order that works until a fresh quote crosses
it, the close or a cancel; ``preview`` answers what it would fill at (or hold) and stores nothing. A market order is
refused outside the regular session, on a stale quote, or without the buying power.
``POST /copilot/paper/orders/cancel``: cancel a working paper limit order.
``POST /copilot/paper/auto``: turn a position's "Close automatically at stop/target" switch on or off.

Paper only: nothing here places an order anywhere, calls Robinhood, or writes fills, trades or accounts. Owner-only like
every ``/copilot`` route; refuses while the lab is off, and fills only on live evidence.
"""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import paper_book, paper_review

router = APIRouter()


def _settings():
    found = copilot.settings()
    if not found.enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return found


class RunAsk(BaseModel):
    starting_cash: float | None = None
    reset: bool = False


class OrderAsk(BaseModel):
    action: Literal["open", "close"]
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = None
    preview: bool = False
    order_key: str | None = Field(None, max_length=64)
    # open
    symbol: str | None = Field(None, max_length=12)
    instrument: Literal["stock", "option", "spread"] | None = None
    option_type: Literal["call", "put"] | None = None
    expiry: str | None = Field(None, max_length=10)
    strike: float | None = None
    long_strike: float | None = None
    short_strike: float | None = None
    note: str | None = Field(None, max_length=2000)
    stop: float | None = None
    target: float | None = None
    # whose idea: his own ticket (default), or Paper it on a copilot, Radar or scanner idea, with that idea's id
    source: Literal["mine", "copilot", "radar", "scanner"] | None = None
    idea_id: str | None = Field(None, max_length=64)
    # both
    quantity: int | None = None
    # close
    position_id: str | None = Field(None, max_length=40)


@router.get("/paper")
def paper(db: Session = Depends(get_session)):
    _settings()
    return {**paper_book.view(db, time.time()), "review": paper_review.latest()}


@router.post("/paper/runs")
def start(body: RunAsk, db: Session = Depends(get_session)):
    _settings()
    try:
        paper_book.start_run(db, body.starting_cash, body.reset, time.time())
    except paper_book.PaperError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return paper_book.view(db, time.time())


@router.post("/paper/orders")
def order(body: OrderAsk, db: Session = Depends(get_session)):
    found = _settings()
    if getattr(found, "evidence", "live") != "live":
        raise HTTPException(409, "Paper fills need live quotes, and the desk is on simulated evidence.")
    ask = body.model_dump()
    try:
        if body.order_type == "limit":
            return paper_book.place_limit(db, ask, time.time(), preview=body.preview)
        if body.action == "open":
            return paper_book.open_order(db, ask, time.time(), preview=body.preview)
        return paper_book.close_order(db, ask, time.time(), preview=body.preview)
    except paper_book.PaperError as exc:
        raise HTTPException(exc.status, str(exc)) from None


class CancelAsk(BaseModel):
    order_id: str = Field(..., max_length=40)


@router.post("/paper/orders/cancel")
def cancel(body: CancelAsk, db: Session = Depends(get_session)):
    _settings()
    try:
        return paper_book.cancel_order(db, body.model_dump(), time.time())
    except paper_book.PaperError as exc:
        raise HTTPException(exc.status, str(exc)) from None


class AutoAsk(BaseModel):
    position_id: str = Field(..., max_length=40)
    on: bool
    order_key: str | None = Field(None, max_length=64)


@router.post("/paper/auto")
def auto(body: AutoAsk, db: Session = Depends(get_session)):
    _settings()
    try:
        return paper_book.set_auto(db, body.model_dump(), time.time())
    except paper_book.PaperError as exc:
        raise HTTPException(exc.status, str(exc)) from None
