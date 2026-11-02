"""One Radar session as a compact feed for the copilot, cut at a moment (docs/radar.md § What the copilot reads).

The Radar screen composes events, revisions, news checks, ratings and "Movers now" from the store with no time cut,
which is right for a live screen. Replay freezes the clock, so everything here takes ``before`` (an epoch, or None for
now): an event first seen later, a revision recorded later, a news check made later and a pass started later never
appear. Ratings carry no time the store exposes, so they are shown only with no cut. Read-only; no provider calls.
"""
from datetime import datetime, UTC

from app.engine.radar_comparison import epoch
from app.engine.radar_movers import build_movers, earlier_pass
from app.engine.radar_store import RadarStore, load_universe

MAX_EVENTS = 12
MAX_LEADERS = 5
MAX_GROUPS = 6
MAX_HEADLINES = 3
RECORDED = ("ok", "partial")


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _before(stamp: str, before: float | None) -> bool:
    return before is None or epoch(stamp) <= before


def _event_row(event: dict, revisions: list[dict], check: dict | None, rating: str | None) -> dict:
    latest = revisions[-1] if revisions else None
    return {
        "event_id": event["event_id"], "kind": event["kind"], "direction": event["direction"], "symbols": event["symbols"],
        "benchmark": event["benchmark"], "group": event.get("group"), "first_seen_at": event["first_seen_at"],
        "summary": event["summary"], "measures": event.get("measures") or {},
        "latest": {"status": latest["status"], "recorded_at": latest["recorded_at"], "note": latest.get("note"),
                   "measures": latest.get("measures") or {}} if latest else None,
        "news": {"status": check["status"], "checked_at": check["checked_at"],
                 "headlines": [{"headline": h.get("headline", "")[:200], "source": h.get("source"),
                                "published_at": h.get("published_at"), "timing": h.get("timing")}
                               for h in (check.get("headlines") or [])[:MAX_HEADLINES]]} if check else None,
        "rating": rating,
    }


def _matches(event: dict, group: str | None) -> bool:
    if not group:
        return True
    wanted = group.strip().lower()
    return (event.get("group") or "").lower() == wanted or wanted.upper() in event["symbols"]


def _movers(store: RadarStore, universe: dict, passes: list[dict]) -> tuple[dict | None, dict | None]:
    recorded = [p for p in passes if p["status"] in RECORDED]
    if not recorded:
        return None, None
    latest = recorded[-1]
    earlier = earlier_pass(recorded, latest)
    quotes = store.pass_quotes([latest["id"]] + ([earlier["id"]] if earlier else []))
    result = build_movers(universe, list(quotes[latest["id"]].values()),
                          list(quotes[earlier["id"]].values()) if earlier else None, latest=latest, earlier=earlier)
    if result["header"] is None:
        return latest, None
    trim = ("symbol", "last", "day_pct", "from_open_pct", "vs_spy", "sector", "vs_sector", "last_15m_pct")
    return latest, {
        "pass_at": latest["started_at"], "earlier_pass_at": earlier["started_at"] if earlier else None,
        "spy_day_pct": result["header"]["spy_day_pct"], "qqq_day_pct": result["header"]["qqq_day_pct"],
        "symbols_with_data": result["header"]["symbols_with_data"], "symbols_tracked": result["header"]["symbols_tracked"],
        "leaders": [{k: r[k] for k in trim} for r in result["leaders"][:MAX_LEADERS]],
        "laggards": [{k: r[k] for k in trim} for r in result["laggards"][:MAX_LEADERS]],
        "groups": [{"name": g["name"], "members_with_data": g["members_with_data"], "ahead": g["ahead"], "behind": g["behind"],
                    "median_vs_spy": g["median_vs_spy"], "most": g["most"]} for g in result["groups"][:MAX_GROUPS]],
    }


def feed(store: RadarStore, session: str, before: float | None = None, *, group: str | None = None,
         limit: int = MAX_EVENTS, universe: dict | None = None) -> dict:
    """The session's events (newest first, at most ``limit``) and movers as they stood at ``before``."""
    universe = universe or load_universe()
    passes = [p for p in store.passes(session) if _before(p["started_at"], before) and _before(p["finished_at"], before)]
    ratings = store.latest_ratings() if before is None else {}
    rows = []
    for event in store.events(session):
        if not _before(event["first_seen_at"], before) or not _matches(event, group):
            continue
        revisions = [r for r in store.revisions(event["event_id"]) if _before(r["recorded_at"], before)]
        checks = [c for c in store.news_checks(event["event_id"]) if _before(c["checked_at"], before)]
        rows.append(_event_row(event, revisions, checks[-1] if checks else None, ratings.get(event["event_id"])))
    rows.sort(key=lambda r: r["first_seen_at"], reverse=True)
    latest, movers = _movers(store, universe, passes)
    out = {"state": "ok" if passes or rows else "no_data", "session": session,
           "as_of": _iso(before) if before is not None else (latest["started_at"] if latest else None),
           "events_total": len(rows), "events": rows[:limit], "movers": movers,
           "passes_recorded": sum(1 for p in passes if p["status"] in RECORDED)}
    if group:
        out["group"] = group
    if out["state"] == "no_data":
        out["reason"] = "Nothing has been recorded for this session yet."
    elif movers is None:
        out["movers_reason"] = "No recorded pass with a usable SPY quote, so nothing can be ranked."
    return out


def bounded(out: dict, most: int) -> dict:
    """Fewer events, never a cut string: the result must stay valid JSON within the tool limit."""
    import json
    while out["events"] and len(json.dumps(out, default=str, separators=(",", ":"))) > most:
        out["events"].pop()
        out["events_shown"] = len(out["events"])
    return out
