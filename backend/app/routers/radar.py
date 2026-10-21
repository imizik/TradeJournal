"""Owner-only Radar feed (``docs/radar.md``): saved events, their revisions and recording coverage.

Reads only what the recorder and the detection rules saved; nothing is
recomputed or refreshed with current prices. A missing or unreadable store is
reported as ``state: off`` rather than an error. Visits and feedback are
append-only rows in the same Radar file.
"""
from datetime import UTC, date, datetime
import logging
import os
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.engine.chart_calendar import chart_calendar
from app.engine.chart_math import ET, session_windows
from app.engine.radar_runner import enabled
from app.engine.radar_store import RadarStore, load_universe

log = logging.getLogger(__name__)
router = APIRouter()

STALE_SECONDS = 180


class FeedbackBody(BaseModel):
    rating: Literal["useful", "already_knew", "too_late", "irrelevant"]


def _now() -> float:
    return time.time()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _store() -> tuple[RadarStore | None, str | None]:
    """(store, None) or (None, the plain reason Radar is off)."""
    path = os.environ.get("RADAR_STORE", "").strip()
    if not enabled():
        return None, "Radar recording is not switched on."
    if not path or not os.path.isabs(path):
        return None, "Radar has no storage file configured."
    try:
        return RadarStore(path), None
    except (ValueError, OSError) as exc:
        log.warning("radar store unreadable: %s", exc)
        return None, "The Radar file could not be opened."


def _require_store() -> RadarStore:
    store, reason = _store()
    if store is None:
        raise HTTPException(503, reason)
    return store


def _regular_window(day: date) -> tuple[int, int] | None:
    try:
        hours = chart_calendar.hours(day)
    except Exception:  # an unreachable calendar falls back to clock hours, as the recorder does
        hours = None
    window = next((w for w in session_windows(day, hours) if w[0] == "regular"), None)
    return (window[1], window[2]) if window else None


def _coverage(store: RadarStore, session: str, now: float) -> dict:
    day = date.fromisoformat(session)
    passes = store.passes(session)
    recorded = [p for p in passes if p["status"] in ("ok", "partial")]
    ok = [p for p in passes if p["status"] == "ok"]
    window = _regular_window(day)
    expected, live = 0, False
    if window:
        clock = datetime.fromtimestamp(now, ET)
        if clock.date() > day:
            expected = window[1] - window[0]
        elif clock.date() == day:
            minute = clock.hour * 60 + clock.minute
            expected = max(0, min(minute, window[1]) - window[0])
            live = window[0] <= minute < window[1]
    universe = load_universe()
    symbols = [row["symbol"] for row in universe["symbols"]]
    latest = recorded[-1] if recorded else None
    missing: list[str] = []
    if latest:
        quoted = {q["symbol"] for q in store.quotes(pass_id=latest["id"])}
        missing = [s for s in symbols if s not in quoted] if quoted else list(latest["unmatched"])
    return {"passes_recorded": len(recorded), "passes_expected": expected,
            "passes_failed": sum(1 for p in passes if p["status"] in ("failed", "skipped")),
            "last_ok_pass_at": ok[-1]["started_at"] if ok else None,
            "symbols_tracked": len(symbols), "symbols_missing": missing,
            "universe_version": (latest or {}).get("universe_version") or universe["version"], "live": live}


def _state(coverage: dict, passes_total: int, now: float) -> str:
    if not passes_total:
        return "no_data"
    if coverage["live"]:
        last = coverage["last_ok_pass_at"]
        if last is None or now - _parse(last) > STALE_SECONDS:
            return "stale"
    return "recording"


def _revision_status(revisions: list[dict]) -> str | None:
    return revisions[-1]["status"] if revisions else None


@router.get("/feed")
def feed(session: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
         since: str | None = Query(None, description="Count events first seen after this time as new instead of the last visit.")):
    now = _now()
    store, reason = _store()
    if store is None:
        return {"state": "off", "reason": reason, "session": session, "events": [], "since_last_visit": [],
                "last_visit_at": None, "coverage": None}
    if session:
        try:
            date.fromisoformat(session)
        except ValueError:
            raise HTTPException(422, "session must be a real date")
    sessions = store.sessions()
    today = datetime.fromtimestamp(now, ET).date().isoformat()
    session = session or (today if today in sessions else (sessions[0] if sessions else today))
    coverage = _coverage(store, session, now)
    passes_total = len(store.passes(session))
    ratings = store.latest_ratings()
    last_visit = store.last_visit()
    baseline = since or last_visit
    events = []
    for event in store.events(session):
        revisions = store.revisions(event["event_id"])
        events.append({**event, "latest_status": _revision_status(revisions), "revision_count": len(revisions),
                       "rating": ratings.get(event["event_id"])})
    new = [e["event_id"] for e in events if baseline is None or _parse(e["first_seen_at"]) > _parse(baseline)]
    return {"state": _state(coverage, passes_total, now), "reason": None, "session": session, "sessions": sessions[:30],
            "events": events, "since_last_visit": new, "last_visit_at": last_visit, "coverage": coverage}


@router.get("/events/{event_id}")
def event_detail(event_id: str):
    store = _require_store()
    event = store.event(event_id)
    if event is None:
        raise HTTPException(404, "Radar event not found")
    return {"event": event, "revisions": store.revisions(event_id), "rating": store.latest_ratings().get(event_id)}


@router.post("/visits")
def record_visit():
    store = _require_store()
    previous = store.last_visit()
    visited = _iso(_now())
    store.append_visit(visited)
    return {"visited_at": visited, "previous_visit_at": previous}


@router.post("/events/{event_id}/feedback")
def event_feedback(event_id: str, body: FeedbackBody):
    store = _require_store()
    if store.event(event_id) is None:
        raise HTTPException(404, "Radar event not found")
    store.append_feedback(event_id, body.rating, _iso(_now()))
    return {"event_id": event_id, "rating": body.rating}
