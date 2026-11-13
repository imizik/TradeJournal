"""The desk's Ticket (``engine/desk_ticket.py``, docs/copilot-lab.md § Ticket): read-only, copy only.

``GET /copilot/tickets``: the saved plans a ticket can open (armed, not yet entered), newest first.
``GET /copilot/tickets/{investigation_id}``: that plan's ticket; ``expiration`` and ``strike`` name the candidate the
owner picked when the plan names no contract. 404 without a saved plan, 409 once its position is open.

There is no write here and nothing that places, sends or stages an order; the ticket's fields are copied into
Robinhood by hand. Owner-only like every ``/copilot`` route; refuses while the lab is off.

``GET /copilot/chain?symbol=&expiration=``: the desk's Chain tab (``engine/desk_chain.py``), one expiry of the ticker's
option chain around the price with his held and planned contracts marked. Market data only; never Robinhood.

``GET /copilot/unusual``: unusual options activity on his held and watched names (``engine/desk_unusual.py``), from the
same option chain reads. Market data only; never Robinhood, never a ping.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import desk_chain, desk_ticket, desk_unusual

router = APIRouter()


def _settings():
    found = copilot.settings()
    if not found.enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return found


@router.get("/tickets")
def tickets(db: Session = Depends(get_session)):
    _settings()
    return {"plans": desk_ticket.armed(db)}


@router.get("/tickets/{investigation_id}")
def ticket(investigation_id: str, expiration: date | None = None, strike: float | None = Query(None, gt=0, lt=100000),
           db: Session = Depends(get_session)):
    found = _settings()
    pick = (expiration, strike) if expiration is not None and strike is not None else None
    try:
        return desk_ticket.build(db, investigation_id, mode=getattr(found, "evidence", "live"), pick=pick)
    except desk_ticket.TicketError as exc:
        raise HTTPException(404 if exc.code == "no_plan" else 409, str(exc)) from None


@router.get("/chain")
def chain(symbol: str = Query(..., min_length=1, max_length=15), expiration: date | None = None,
          strike: float | None = Query(None, gt=0, lt=100000), db: Session = Depends(get_session)):
    found = _settings()
    try:
        return desk_chain.view(db, symbol, expiration, mode=getattr(found, "evidence", "live"), strike=strike)
    except desk_chain.ChainError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/unusual")
def unusual(db: Session = Depends(get_session)):
    found = _settings()
    return desk_unusual.view(db, mode=getattr(found, "evidence", "live"))
