"""How he uses the desk (``app/engine/desk_use.py``, docs/copilot-lab.md § How I use the desk).

``POST /copilot/desk/use``: one flush of the desk's quiet counts (piece ids, opens, taps, seconds on screen per New York
day), added to the day's totals. ``GET /copilot/desk/use?size=``: the last 14 days per piece, each piece's last use,
how many days had desk use, and that size's folds. ``PUT /copilot/desk/folds``: one device size's folded pieces and the
fold suggestion's snooze, as he set them.

Owner-only like every ``/copilot`` route; refuses while the lab is off. This database only: no quote, no Robinhood, no
outside service.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import desk_use

router = APIRouter()


def _on():
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")


class UseRow(BaseModel):
    day: date
    piece: str = Field(..., max_length=40)
    opens: int = Field(0, ge=0)
    taps: int = Field(0, ge=0)
    seen_s: int = Field(0, ge=0)


class UseAsk(BaseModel):
    size: Literal["desk", "phone"]
    rows: list[UseRow] = Field(..., max_length=desk_use.MAX_ROWS)


class FoldsAsk(BaseModel):
    size: Literal["desk", "phone"]
    folded: list[str] = Field(..., max_length=desk_use.MAX_FOLDED)
    snoozed_until: date | None = None


@router.post("/desk/use")
def save_use(body: UseAsk, db: Session = Depends(get_session)):
    _on()
    try:
        return desk_use.record(db, body.size, [r.model_dump() for r in body.rows])
    except desk_use.UseError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.get("/desk/use")
def use(size: Literal["desk", "phone"] = "desk", db: Session = Depends(get_session)):
    _on()
    return desk_use.summary(db, size)


@router.put("/desk/folds")
def save_folds(body: FoldsAsk, db: Session = Depends(get_session)):
    _on()
    try:
        return desk_use.save_folds(db, body.size, body.folded, body.snoozed_until)
    except desk_use.UseError as exc:
        raise HTTPException(exc.status, str(exc)) from None
