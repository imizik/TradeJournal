"""Is Radar finding what Isaac would otherwise miss, early enough? For the /proof page.

Read-only over the Radar file and saved morning briefings; no provider or model call.
Scope: every event of the newest rule version (versions are never pooled).

- **Ratings:** the latest rating per event (``useful``, ``already_knew``, ``too_late``, ``irrelevant``).
- **Movers:** for each stock event, the plain Movers ranking (``radar_movers.build_movers``, top 10
  leaders for an up event, laggards for a down one) rebuilt at every recorded pass of its session.
  ``radar_first``: the stock was not on that side of the list at any pass up to the event's first
  sighting but was later; ``not_in_movers``: never that session; ``movers_first``: it already was, at or
  before the sighting; ``unavailable``: the session's quotes are gone (pruned after 20 sessions).
  Group events are rated but not timed: Movers lists stocks.
- **Morning brief:** the stock as an opportunity or item in a saved, unredacted briefing within
  ``BRIEF_DAYS`` days: ``brief_first`` (on or before the event's day), ``radar_first`` (only after),
  ``not_in_brief``. Shown, not part of the verdict: a brief names at most a handful of stocks.
"""
from collections import Counter, defaultdict
from datetime import date
import json
from statistics import median

from sqlmodel import Session, select

from app.engine.radar_comparison import epoch
from app.engine.radar_movers import build_movers
from app.engine.radar_store import RATINGS, RadarStore
from app.models import MorningBriefingPacket, MorningBriefingRecord

STOCK_KINDS = ("relative_to_spy", "relative_to_sector")
USABLE = ("ok", "partial")
BRIEF_DAYS = 5
MIN_RATED = 20
MIN_TIMED = 10
USEFUL_SHARE = 0.4
AHEAD_SHARE = 0.5


def movers_timeline(universe: dict, passes: list[dict], quotes: dict[int, dict[str, dict]]) -> list[tuple[float, set, set]]:
    """(pass start, leader symbols, laggard symbols) for every recorded pass that could be ranked."""
    out = []
    for p in sorted((p for p in passes if p["status"] in USABLE), key=lambda p: (p["started_at"], p["id"])):
        ranked = build_movers(universe, list(quotes.get(p["id"], {}).values()), None, latest=p)
        if ranked["header"] is not None:
            out.append((epoch(p["started_at"]), {r["symbol"] for r in ranked["leaders"]}, {r["symbol"] for r in ranked["laggards"]}))
    return out


def movers_timing(event: dict, timeline: list[tuple[float, set, set]]) -> dict:
    if not timeline:
        return {"result": "unavailable", "lead_minutes": None}
    symbol, seen = event["symbols"][0], epoch(event["first_seen_at"])
    listed = [at for at, up, down in timeline if symbol in (up if event["direction"] == "up" else down)]
    if not listed:
        return {"result": "not_in_movers", "lead_minutes": None}
    lead = round((listed[0] - seen) / 60, 1)
    return {"result": "radar_first" if lead > 0 else "movers_first", "lead_minutes": lead}


def brief_timing(symbol: str, day: date, briefs: dict[date, set[str]]) -> str:
    days = [d for d, symbols in briefs.items() if symbol in symbols and abs((d - day).days) <= BRIEF_DAYS]
    if any(d <= day for d in days):
        return "brief_first"
    return "radar_first" if days else "not_in_brief"


def verdict(ratings: Counter, timing: Counter) -> dict:
    rated = sum(ratings[r] for r in RATINGS)
    timed = timing["radar_first"] + timing["not_in_movers"] + timing["movers_first"]
    ahead = timing["radar_first"] + timing["not_in_movers"]
    rule = (f"Helping: at least {MIN_RATED} rated events with {USEFUL_SHARE:.0%}+ rated useful, and in {AHEAD_SHARE:.0%}+ of "
            f"at least {MIN_TIMED} timed stock events Movers did not already list the stock at Radar's first sighting.")
    out = {"verdict": "not_enough_data", "rule": rule, "rated": rated, "timed": timed,
           "useful_share": round(ratings["useful"] / rated, 4) if rated else None,
           "ahead_share": round(ahead / timed, 4) if timed else None}
    if rated < MIN_RATED:
        return {**out, "reason": f"{rated} of {MIN_RATED} rated events needed."}
    if timed < MIN_TIMED:
        return {**out, "reason": f"{timed} of {MIN_TIMED} stock events with recorded Movers to compare."}
    if out["useful_share"] >= USEFUL_SHARE and out["ahead_share"] >= AHEAD_SHARE:
        return {**out, "verdict": "helping", "reason": "Rated useful often enough and usually ahead of Movers."}
    misses = [m for m, ok in (("too few rated useful", out["useful_share"] >= USEFUL_SHARE),
                               ("Movers usually had it first", out["ahead_share"] >= AHEAD_SHARE)) if not ok]
    return {**out, "verdict": "not_helping", "reason": "; ".join(misses).capitalize() + "."}


def briefed_symbols(db: Session) -> dict[date, set[str]]:
    rows = db.exec(select(MorningBriefingPacket.day, MorningBriefingRecord.body_json)
                   .join(MorningBriefingPacket, MorningBriefingPacket.id == MorningBriefingRecord.packet_id)
                   .where(MorningBriefingRecord.redacted_at.is_(None))).all()
    out: dict[date, set[str]] = defaultdict(set)
    for day, body in rows:
        parsed = json.loads(body or "{}")
        out[day] |= {i["symbol"] for i in [*parsed.get("opportunities", []), *parsed.get("items", [])] if i.get("symbol")}
    return out


def build(store: RadarStore, db: Session, universe: dict) -> dict:
    events = store.events()
    newest = max(events, key=lambda e: epoch(e["first_seen_at"]), default=None)
    version = newest["rule_version"] if newest else None
    events = [e for e in events if e["rule_version"] == version]
    latest = store.latest_ratings()
    ratings = Counter(latest.get(e["event_id"], "unrated") for e in events)
    briefs = briefed_symbols(db)
    stocks = [e for e in events if e["kind"] in STOCK_KINDS]
    timeline_of = {}
    for session in sorted({e["session_date"] for e in stocks}):
        passes = store.passes(session)
        timeline_of[session] = movers_timeline(universe, passes, store.pass_quotes(p["id"] for p in passes))
    timing, brief, leads = Counter(), Counter(), []
    for e in stocks:
        moved = movers_timing(e, timeline_of[e["session_date"]])
        timing[moved["result"]] += 1
        if moved["result"] == "radar_first":
            leads.append(moved["lead_minutes"])
        brief[brief_timing(e["symbols"][0], date.fromisoformat(e["session_date"]), briefs)] += 1
    return {
        "state": "ok" if events else "no_data", "reason": None if events else "No Radar events recorded yet.",
        "rule_version": version, "sessions": len({e["session_date"] for e in events}),
        "events": len(events), "stock_events": len(stocks), "group_events": len(events) - len(stocks),
        "ratings": {r: ratings[r] for r in (*RATINGS, "unrated")},
        "movers": {k: timing[k] for k in ("radar_first", "not_in_movers", "movers_first", "unavailable")},
        "median_lead_minutes": median(leads) if leads else None,
        "brief": {k: brief[k] for k in ("radar_first", "brief_first", "not_in_brief")},
        "verdict": verdict(ratings, timing),
    }
