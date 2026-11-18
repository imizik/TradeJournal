"""What's working (``app/engine/whats_working.py``, docs/copilot-lab.md § What's working).

``GET /copilot/desk/whats-working``: his closed real and paper trades in plain-word buckets, last 30 days and all time,
with each side's top 3 making and losing buckets. ``GET /copilot/desk/whats-working/record?option_type=``: the paper
record for the real ticket's order (that option type, entered at this New York time), or ``null``.

Owner-only like every ``/copilot`` route; refuses while the lab is off. This database only: no quote, no Robinhood, no
outside service. Nothing is written.
"""

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import whats_working

router = APIRouter()
_now = time.time  # tests pin the clock here


def _on():
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")


@router.get("/desk/whats-working")
def whats_working_report(db: Session = Depends(get_session)):
    _on()
    return whats_working.report(db, _now())


@router.get("/desk/whats-working/record")
def whats_working_record(option_type: Literal["call", "put"], db: Session = Depends(get_session)):
    _on()
    return {"record": whats_working.paper_record(db, option_type, _now())}
