"""The Copilot Lab's Plans board (``engine/copilot_plans.py``): confirmed copilot plans still armed, nearest first,
the Dashboard's Plans card (``engine/plan_positions.py``): each open position beside the plan it was entered under,
the Charts dock's loop for one symbol (``GET /copilot/symbol/{symbol}``): both of those and what is new on it, and the
desk's Context pane for the open thread (``GET /copilot/desk/{investigation_id}/picture|timeline|history``,
``engine/desk_context.py``).

Owner-only like every ``/copilot`` route; refuses while the lab is off. Read-only.
"""

from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import copilot_plans, desk_context, plan_positions
from app.engine.chart_math import ET
from app.routers import today

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

router = APIRouter()


@router.get("/plans")
def plans(db: Session = Depends(get_session)):
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return copilot_plans.board(db)


@router.get("/plans/positions")
def plan_positions_view(db: Session = Depends(get_session)):
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return plan_positions.positions(db)


@router.get("/symbol/{symbol}")
def symbol_loop(symbol: str, db: Session = Depends(get_session)):
    """The Charts dock's Copilot tab for one symbol: its open positions with their plans, its armed plans not yet in a
    position, and what is new on it (Radar events since the last Radar visit, thesis triggers fired today). Composed
    in-process from the Plans board, the Plans card and the Today screen's readers, each section on its own so one
    failing source reads ``{"state": "unavailable"}``. Quotes are read for this symbol only. Read-only."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(400, "Not a symbol.")
    now = today._now()
    shared = today.SharedQuotes()

    def quotes(symbols: list[str]):
        return shared([s for s in symbols if s == symbol])

    def armed_plans():
        rows = copilot_plans.board(db, quotes=quotes)["plans"]
        return {"state": "ok", "rows": [p for p in rows if p["symbol"] == symbol and p["position"] != "in_position"]}

    def positions():
        rows = plan_positions.positions(db, quotes=quotes)["positions"]
        return {"state": "ok", "rows": [p for p in rows if p["symbol"] == symbol]}

    day = datetime.fromtimestamp(now, ET).date()
    # The board first, as on the Today screen: its read covers the symbol, so the positions need no second read.
    armed = today._section(db, "symbol plans", armed_plans)
    return {
        "symbol": symbol, "as_of": today._iso(now),
        "positions": today._section(db, "symbol positions", positions), "plans": armed,
        "new": {"radar": today._section(db, "symbol radar", lambda: today._radar(now, symbol)),
                "thesis": today._section(db, "symbol thesis", lambda: today._thesis(db, day, symbol))},
        "quotes_at": shared.at, "quote_issue": shared.issue,
    }


def _thread(investigation_id: str, db: Session):
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    found = desk_context.investigation(db, investigation_id)
    if found is None:
        raise HTTPException(404, "No such investigation.")
    return found


@router.get("/desk/{investigation_id}/picture")
def desk_picture(investigation_id: str, db: Session = Depends(get_session)):
    """The Context pane's chart: today's minute bars for the thread's symbol with its plan's levels and today's fills,
    as a PNG. Unavailable (no symbol, no bars yet, the read failed or ran long) is a 404 whose detail says why."""
    inv = _thread(investigation_id, db)
    try:
        png = desk_context.picture(db, inv, today._now())
    except desk_context.Unavailable as exc:
        raise HTTPException(404, str(exc)) from None
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/desk/{investigation_id}/timeline")
def desk_timeline(investigation_id: str, db: Session = Depends(get_session)):
    """What touched the thread, newest first: its plan's alerts, time stop and revisits, its linked fills, and the
    symbol's thesis triggers, pings and today's decisions."""
    return desk_context.timeline(db, _thread(investigation_id, db), today._now())


@router.get("/desk/{investigation_id}/history")
def desk_history(investigation_id: str, db: Session = Depends(get_session)):
    """The owner's own record at the thread's plan invalidation (the engine behind ``get_level_history``)."""
    return desk_context.history(db, _thread(investigation_id, db))
