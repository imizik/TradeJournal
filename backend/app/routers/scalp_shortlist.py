"""Owner's morning paper shortlist. Reads never contact a market-data provider."""
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.engine.scalp_shortlist_store import publish_once, read_record, study_dir
from app.engine.scalp_shortlist import SESSIONS

router = APIRouter()
ET = ZoneInfo("America/New_York")


class PaperChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")
    choice: Literal["take", "pass"]


def _now() -> datetime:
    return datetime.now(ET)


@router.get("")
def session_view(response: Response, day: date | None = None):
    response.headers["Cache-Control"] = "no-store"
    now = _now()
    today = now.date()
    selected = day or today
    key = selected.isoformat()
    state = {"day": key, "today": today.isoformat(), "now": now.isoformat(), "sessions": SESSIONS,
             "live": None, "recap": None, "decisions": []}
    if key not in SESSIONS or selected > today:
        return state
    root = study_dir() / key
    if selected == today and now.time() < time(9, 40):
        return state
    live = read_record(root / "live.json")
    if live and datetime.fromisoformat(live["captured_at"]) > now:
        return state
    state["live"] = live
    if selected < today or now.time() >= time(10, 15):
        state["recap"] = read_record(root / "recap.json")
    if live:
        for pick in live["picks"]:
            decision = read_record(root / "decisions" / (pick["symbol"] + ".json"))
            if decision:
                state["decisions"].append(decision)
    return state


@router.post("/{day}/decisions")
def decide(day: date, body: PaperChoice, response: Response):
    response.headers["Cache-Control"] = "no-store"
    now = _now()
    key = day.isoformat()
    if key not in SESSIONS:
        raise HTTPException(404, "Outside the study")
    root = study_dir() / key
    live = read_record(root / "live.json")
    pick = next((p for p in live["picks"] if p["symbol"] == body.symbol), None) if live else None
    if pick is None:
        raise HTTPException(404, "That stock was not shown in this session")
    path = root / "decisions" / (body.symbol + ".json")
    saved = read_record(path)
    if saved is None:
        if day != now.date() or not time(9, 40) <= now.time() < time(9, 51) or datetime.fromisoformat(live["captured_at"]) > now:
            raise HTTPException(409, "The decision window is closed")
        saved = publish_once(path, {"symbol": body.symbol, "direction": pick["direction"], "choice": body.choice,
                                    "decided_at": now.isoformat(), "timely": now.time() < time(9, 41)})
    if saved["choice"] != body.choice:
        raise HTTPException(409, "A different decision was already recorded")
    return saved
