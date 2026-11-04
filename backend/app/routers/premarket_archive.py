from datetime import date as session_date
import json

from fastapi import APIRouter, HTTPException

from app.engine.premarket_archive import ROOT

router = APIRouter()


@router.get("/premarket/archive/{date}")
def archived_day(date: session_date):
    try:
        return json.loads((ROOT / f"{date.isoformat()}.json").read_text())
    except FileNotFoundError:
        raise HTTPException(404, "No saved pre-market ranking for this date") from None
