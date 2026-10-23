"""Owner-only Radar feed (``docs/radar.md``): saved events, their revisions and recording coverage.

Reads only what the recorder and the detection rules saved; nothing is
recomputed or refreshed with current prices. A missing or unreadable store is
reported as ``state: off`` rather than an error. Visits and feedback are
append-only rows in the same Radar file.
"""
from datetime import UTC, date, datetime
import logging
import os
import sqlite3
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.engine.chart_calendar import chart_calendar
from app.engine.chart_math import ET, session_windows
from app.engine.radar_comparison import compare_group, empty_comparison
from app.engine.radar_movers import build_movers, earlier_pass
from app.engine.radar_runner import enabled
from app.engine.radar_store import RadarStore, load_universe

log = logging.getLogger(__name__)
router = APIRouter()

STALE_SECONDS = 180


class VisitBody(BaseModel):
    # The feed's own ``generated_at``, so an event saved between reading the feed and posting the visit still counts as new.
    visited_at: str | None = None


class FeedbackBody(BaseModel):
    rating: Literal["useful", "already_knew", "too_late", "irrelevant"]


def _now() -> float:
    return time.time()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _store(*, read_only: bool = False) -> tuple[RadarStore | None, str | None]:
    """(store, None) or (None, the plain reason Radar is off)."""
    path = os.environ.get("RADAR_STORE", "").strip()
    if not enabled():
        return None, "Radar recording is not switched on."
    if not path or not os.path.isabs(path):
        return None, "Radar has no storage file configured."
    try:
        return RadarStore(path, read_only=read_only), None
    except (ValueError, OSError, sqlite3.Error) as exc:
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


def _news_block(check: dict | None) -> dict | None:
    """A saved news check as served; None until the first check. Headlines carry ``timing`` before/after the move."""
    if check is None:
        return None
    return {"status": check["status"], "checked_at": check["checked_at"], "headlines": check["headlines"]}


def _off(reason: str, session: str | None) -> dict:
    return {"state": "off", "reason": reason, "session": session, "events": [], "since_last_visit": [],
            "last_visit_at": None, "coverage": None, "generated_at": None}


def _valid_time(value: str, name: str) -> None:
    try:
        _parse(value)
    except ValueError:
        raise HTTPException(422, f"{name} must be an ISO time")


@router.get("/feed")
def feed(session: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
         since: str | None = Query(None, description="Count events first seen after this time as new instead of the last visit.")):
    now = _now()
    if session:
        try:
            date.fromisoformat(session)
        except ValueError:
            raise HTTPException(422, "session must be a real date")
    if since:
        _valid_time(since, "since")
    store, reason = _store()
    if store is None:
        return _off(reason, session)
    try:
        return _read_feed(store, session, since, now)
    except (sqlite3.Error, ValueError, KeyError, OSError) as exc:  # a busy or damaged file must not become a 500
        log.warning("radar feed unreadable: %s", exc)
        return _off("The Radar file could not be read right now.", session)


def _read_feed(store: RadarStore, session: str | None, since: str | None, now: float) -> dict:
    sessions = store.sessions()
    today = datetime.fromtimestamp(now, ET).date().isoformat()
    session = session or (today if today in sessions else (sessions[0] if sessions else today))
    coverage = _coverage(store, session, now)
    passes_total = len(store.passes(session))
    ratings = store.latest_ratings()
    news = store.latest_news()
    last_visit = store.last_visit()
    baseline = since or last_visit
    events = []
    for event in store.events(session):
        revisions = store.revisions(event["event_id"])
        events.append({**event, "latest_status": _revision_status(revisions), "revision_count": len(revisions),
                       "rating": ratings.get(event["event_id"]), "news": _news_block(news.get(event["event_id"]))})
    new = [e["event_id"] for e in events if baseline is None or _parse(e["first_seen_at"]) > _parse(baseline)]
    return {"state": _state(coverage, passes_total, now), "reason": None, "session": session, "sessions": sessions[:30],
            "events": events, "since_last_visit": new, "last_visit_at": last_visit, "coverage": coverage,
            "generated_at": _iso(now)}


@router.get("/movers")
def movers(session: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """A plain ranking from the latest recorded pass; no thresholds, events or provider calls."""
    now = _now()
    if session:
        try:
            date.fromisoformat(session)
        except ValueError:
            raise HTTPException(422, "session must be a real date")
    empty = {"session": session, "generated_at": _iso(now), "pass_at": None, "earlier_pass_at": None, "header": None,
             "leaders": [], "laggards": [], "groups": [], "missing": []}
    store, reason = _store(read_only=True)
    if store is None:
        return {**empty, "state": "off", "reason": reason}
    try:
        return _read_movers(store, session, now, empty)
    except (sqlite3.Error, ValueError, KeyError, OSError, TypeError) as exc:
        log.warning("radar movers unreadable: %s", exc)
        return {**empty, "state": "off", "reason": "The Radar file could not be read right now."}


def _read_movers(store: RadarStore, session: str | None, now: float, empty: dict) -> dict:
    sessions = store.sessions()
    today = datetime.fromtimestamp(now, ET).date().isoformat()
    session = session or (today if today in sessions else (sessions[0] if sessions else today))
    empty = {**empty, "session": session}
    coverage = _coverage(store, session, now)
    passes = store.passes(session)
    recorded = [p for p in passes if p["status"] in ("ok", "partial")]
    if not recorded:
        return {**empty, "state": "no_data", "reason": "Nothing has been recorded for this session yet."}
    latest = recorded[-1]
    earlier = earlier_pass(recorded, latest)
    result = build_movers(load_universe(), store.quotes(pass_id=latest["id"]),
                          store.quotes(pass_id=earlier["id"]) if earlier else None)
    base = {**empty, **result, "pass_at": latest["started_at"], "earlier_pass_at": earlier["started_at"] if earlier else None}
    if result["header"] is None:
        return {**base, "state": "no_data", "reason": "The latest pass has no usable SPY quote, so nothing can be ranked."}
    stale = coverage["live"] and (coverage["last_ok_pass_at"] is None or now - _parse(coverage["last_ok_pass_at"]) > STALE_SECONDS)
    return {**base, "state": "stale" if stale else "ok",
            "reason": "Recording has fallen behind; these numbers are from the last pass shown." if stale else None}


@router.get("/events/{event_id}")
def event_detail(event_id: str):
    store = _require_store()
    event = store.event(event_id)
    if event is None:
        raise HTTPException(404, "Radar event not found")
    checks = [_news_block(c) for c in store.news_checks(event_id)]
    return {"event": event, "revisions": store.revisions(event_id), "rating": store.latest_ratings().get(event_id),
            "news": checks[-1] if checks else None, "news_checks": checks}


@router.post("/visits")
def record_visit(body: VisitBody | None = None):
    store = _require_store()
    previous = store.last_visit()
    now = _now()
    visited = _iso(now)
    if body and body.visited_at:
        _valid_time(body.visited_at, "visited_at")
        visited = _iso(min(_parse(body.visited_at), now))
    store.append_visit(visited)
    return {"visited_at": visited, "previous_visit_at": previous}


@router.post("/events/{event_id}/feedback")
def event_feedback(event_id: str, body: FeedbackBody):
    store = _require_store()
    if store.event(event_id) is None:
        raise HTTPException(404, "Radar event not found")
    store.append_feedback(event_id, body.rating, _iso(_now()))
    return {"event_id": event_id, "rating": body.rating}


@router.get("/groups/compare")
def group_comparison(symbol: str = Query(..., pattern=r"^[A-Za-z0-9.\-]{1,16}$"),
                     group: str | None = Query(None, max_length=120)):
    """Read-only sampled group movement, independent of event detection and feed visits."""
    now = _now()
    result = empty_comparison(symbol.upper(), group, load_universe(), now)
    if group and not any(g["name"] == group for g in result["groups"]):
        raise HTTPException(422, "Group does not contain this symbol")
    if result["group"] is None:
        return result
    store, reason = _store(read_only=True)
    if store is None:
        return {**result, "state": "off", "reason": reason}
    clock = datetime.fromtimestamp(now, ET)
    try:
        hours = chart_calendar.hours(clock.date())
    except Exception:
        hours = None
    if hours is None:
        return {**result, "reason": "Market calendar unavailable; cannot identify the current recording session."}
    window = next((w[1:] for w in session_windows(clock.date(), hours) if w[0] == "regular"), None)
    live = bool(window and window[0] <= clock.hour * 60 + clock.minute < window[1])
    try:
        return compare_group(store, result, today=clock.date().isoformat(), now=now, live=live)
    except (sqlite3.Error, ValueError, KeyError, OSError, TypeError) as exc:
        log.warning("radar comparison unreadable: %s", exc)
        return {**empty_comparison(symbol.upper(), group, load_universe(), now),
                "state": "off", "reason": "Recorded group observations could not be read right now."}
