"""Radar PR 5: headlines near each saved event, or a plain "cause unknown".

Called from ``RadarRunner.run_once`` after the quote pass, inside regular hours
only. An event is checked once when it has no news check yet and once more
``RECHECK_SECONDS`` after that first check, and only while it is under
``MAX_AGE_SECONDS`` old. At most ``MAX_REQUESTS`` news requests go out per
pass; leftover events wait for the next pass. Each check is appended to the
``event_news`` table beside the event, never into it: the original event stays
the evidence as first saved. Only symbols in events are asked about; there is
no sweep across the universe. Nothing here claims a headline caused a move.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Callable

from app.engine import news
from app.engine.jo_morning_market import catalyst_first, eligible_headlines, stamp
from app.engine.radar_store import RadarEventNews, RadarNewsHeadline, RadarStore

log = logging.getLogger(__name__)

LOOKBACK = timedelta(hours=24)
RECHECK_SECONDS = 15 * 60
MAX_AGE_SECONDS = 2 * 60 * 60
MAX_REQUESTS = 3
MAX_HEADLINES = 5

NewsReader = Callable[[list[str], datetime, datetime], list[dict]]


def fetch(symbols: list[str], start: datetime, end: datetime) -> list[dict]:
    # One page on a short budget with no retry, so a slow provider cannot stall the minute's pass;
    # strict, so a refused key (403/404) is "unavailable", never "none found".
    return news.fetch_news(symbols=symbols, start=start, end=end, limit=50, fast=True, strict=True)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def due(event: dict, checks: list[RadarEventNews], now: datetime) -> bool:
    """First check while young, then one recheck 15 minutes later; never after two hours."""
    age = (now - stamp(event["first_seen_at"])).total_seconds()
    if not 0 <= age < MAX_AGE_SECONDS:
        return False
    if not checks:
        return True
    return len(checks) == 1 and (now - stamp(checks[0]["checked_at"])).total_seconds() >= RECHECK_SECONDS


def check(event: dict, now: datetime, reader: NewsReader = fetch) -> RadarEventNews:
    """One news check for one event; a provider failure becomes ``unavailable``, never an exception."""
    first_seen = stamp(event["first_seen_at"])
    start, symbols = first_seen - LOOKBACK, set(event["symbols"])
    record: RadarEventNews = {"event_id": event["event_id"], "checked_at": _iso(now), "status": "unavailable", "headlines": []}
    try:
        articles = eligible_headlines(reader(sorted(symbols), start, now), now)
    except Exception as exc:  # the provider being down is "unavailable", which is not the same as "none found"
        log.warning("radar news unavailable for %s: %s: %s", event["event_id"], type(exc).__name__, str(exc)[:200])
        return record
    nearby = [a for a in articles if stamp(a["created_at"]) >= start and symbols.intersection(a["symbols"])]
    headlines: list[RadarNewsHeadline] = []
    for article in catalyst_first(nearby)[:MAX_HEADLINES]:
        published = stamp(article["created_at"])
        headlines.append({"headline": article["headline"].strip()[:500], "source": article.get("source"),
                          "published_at": _iso(published), "url": article["url"][:1200],
                          "symbols": [s for s in article["symbols"] if isinstance(s, str)],
                          "timing": "before" if published <= first_seen else "after"})
    record["status"] = "found" if headlines else "none_found"
    record["headlines"] = headlines
    return record


def enrich(store: RadarStore, session_date: str, now: datetime, reader: NewsReader = fetch) -> int:
    """Check the session's due events, oldest first, up to ``MAX_REQUESTS``; returns how many were checked."""
    checked = 0
    for event in store.events(session_date):
        if checked >= MAX_REQUESTS:
            break
        if not due(event, store.news_checks(event["event_id"]), now):
            continue
        store.append_news(check(event, now, reader))
        checked += 1
    return checked
