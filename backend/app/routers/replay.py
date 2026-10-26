"""Watch your day (``engine/day_replay.py``): the owner's replay clips, read-only.

- ``GET /replay``: the kept days with clips, newest first, ``{days: [{date, symbols}]}``, so the Today screen and
  the trade page know when to offer "Watch today".
- ``GET /replay/{date}``: that day's clips, each ``{symbol, frames, fps, width, height, bytes, times, path}``
  (``times`` are epoch seconds: frame ``i`` shows the day before ``times[i]``), with the day's fill and ping counts.
- ``GET /replay/{date}/{symbol}``: the clip, an animated PNG.

Owner only (not in any assistant grant). A day past ``day_replay.KEEP_DAYS`` is gone (404). No ids.
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Response

from app.engine import day_replay

router = APIRouter()


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, "The date must be YYYY-MM-DD.") from None


@router.get("")
def list_days():
    return {"days": day_replay.days()}


@router.get("/{day}")
def get_day(day: str):
    found = day_replay.index(_day(day))
    if not found or not found.get("clips"):
        raise HTTPException(404, "No replay for that day.")
    clips = [{**clip, "path": f"/replay/{found['date']}/{clip['symbol']}"} for clip in found["clips"]]
    return {"date": found["date"], "fills": found["fills"], "pings": found["pings"], "clips": clips}


@router.get("/{day}/{symbol}")
def get_clip(day: str, symbol: str):
    data = day_replay.load(_day(day), symbol.upper())
    if data is None:
        raise HTTPException(404, "No replay for that symbol and day.")
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, no-store"})
