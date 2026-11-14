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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import paper_book, paper_replay, paper_review

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


# --- paper replay: practice on a past day (``engine/paper_replay.py``) -------------------------------------------------
# ``GET /copilot/paper/replay``: the replay scorecard, and with ``with_days`` the past trading days offered (every replay run's closed trades,
# apart from live paper and real trades). ``GET /copilot/paper/replay/day?day=``: the tickers to suggest for a day.
# ``GET /copilot/paper/replay/bars?day=&symbol=``: that day's minute bars from the Charts history store (refused with the
# reason when they cannot be read). ``POST /copilot/paper/replay/runs``: start a replay run on a day. ``.../step``: bring
# a run to the replay clock (limits, stop and target worked bar by bar; at the close, or with ``end``, everything sold).
# ``.../orders``, ``.../orders/cancel``, ``.../auto``: the paper book's own orders at the replay clock, shares only.
# Never Tradier or Robinhood; writes only replay runs' paper rows.

def _replay(call):
    _settings()
    try:
        return call()
    except paper_book.PaperError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.get("/paper/replay")
def replay_home(with_days: bool = False, db: Session = Depends(get_session)):
    def call():
        found = {**paper_replay.scorecard(db), "spread_bps": paper_replay.SPREAD_BPS, "options": paper_replay.OPTIONS_REFUSED}
        if with_days:  # the market calendar: only when he opens replay, never on the desk's own read
            found["days"] = paper_replay.days(time.time())
        return found
    return _replay(call)


@router.get("/paper/replay/day")
def replay_day(day: str = Query(..., max_length=10), db: Session = Depends(get_session)):
    def call():
        found = paper_replay._past_day(day, time.time())
        return {"day": found.isoformat(), "symbols": paper_replay.suggestions(db, found)}
    return _replay(call)


@router.get("/paper/replay/bars")
def replay_bars(day: str = Query(..., max_length=10), symbol: str = Query(..., max_length=12)):
    def call():
        found = paper_replay._past_day(day, time.time())
        name = paper_replay.ticker(symbol)
        bars, hours = paper_replay.session_bars(name, found)
        keep = ("time", "open", "high", "low", "close", "volume")
        return {"symbol": name, "day": found.isoformat(), "open_at": hours[0], "close_at": hours[1],
                "bars": [{k: b[k] for k in keep} for b in bars]}
    return _replay(call)


class ReplayStart(BaseModel):
    day: str = Field(..., max_length=10)
    starting_cash: float | None = None


@router.post("/paper/replay/runs")
def replay_start(body: ReplayStart, db: Session = Depends(get_session)):
    def call():
        run = paper_replay.start(db, body.model_dump(), time.time())
        return paper_replay.view(db, run, paper_replay.regular(run.replay_day)[0])
    return _replay(call)


class ReplayStep(BaseModel):
    run_id: str = Field(..., max_length=40)
    at: float
    end: bool = False


@router.post("/paper/replay/step")
def replay_step(body: ReplayStep, db: Session = Depends(get_session)):
    return _replay(lambda: paper_replay.step(db, body.model_dump(), time.time()))


class ReplayOrder(OrderAsk):
    run_id: str = Field(..., max_length=40)
    at: float
    auto: bool = False


@router.post("/paper/replay/orders")
def replay_order(body: ReplayOrder, db: Session = Depends(get_session)):
    return _replay(lambda: paper_replay.order(db, body.model_dump(), time.time()))


class ReplayCancel(BaseModel):
    run_id: str = Field(..., max_length=40)
    at: float
    order_id: str = Field(..., max_length=40)


@router.post("/paper/replay/orders/cancel")
def replay_cancel(body: ReplayCancel, db: Session = Depends(get_session)):
    return _replay(lambda: paper_replay.cancel(db, body.model_dump(), time.time()))


class ReplayAuto(AutoAsk):
    run_id: str = Field(..., max_length=40)
    at: float


@router.post("/paper/replay/auto")
def replay_auto(body: ReplayAuto, db: Session = Depends(get_session)):
    return _replay(lambda: paper_replay.set_auto(db, body.model_dump(), time.time()))
