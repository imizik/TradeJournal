"""The Radar scorecard (docs/copilot-lab.md § The desk): for each stock Radar hit, what the owner decided on the desk
and what the stock did after, so whether Radar helps shows in the decisions it prompted.

Read-only over the Radar file and the day journal; no provider or model call, nothing recomputed into an event.

- Hits: stock events (``relative_to_spy``, ``relative_to_sector``) first seen in the last ``WINDOW_DAYS``, newest
  first. Group events name no one stock to decide on, so they stay on the Radar page.
- Decision: the first ``decision`` day-journal entry for the hit's stock logged at or after it was first seen, on its
  session's New York day and before the stock's next hit that day ("watching", "passing" or "planning", from the
  entry's first word); none means no decision was logged. The journal keeps the symbol, not the event.
- Planned and traded: a plan naming the hit as its origin, and whether that plan is linked to a trade
  (``radar_proof.planned_events``).
- After: the stock's move against SPY in the hit's direction, in percent, from the pass the hit was first seen in to
  the pass nearest 60 minutes later and to the session's last pass (the outcome scorer's ``60m`` and ``close``,
  ``scripts/radar_outcomes.py``). Positive means it kept going the way Radar flagged. ``None`` with a reason when a
  price is missing, the pass was never recorded, quotes were pruned (after 20 sessions) or the session is still open.

Radar times are ISO UTC strings; journal times are naive UTC (domain rules).
"""
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.engine import radar_proof
from app.engine.chart_math import ET
from app.engine.radar_comparison import _endpoint, epoch
from app.engine.radar_store import RadarStore
from app.models import DayJournalEntry

WINDOW_DAYS = 30
MAX_ROWS = 60
STOCK_KINDS = ("relative_to_spy", "relative_to_sector")
KIND = {"relative_to_spy": "vs SPY", "relative_to_sector": "vs sector"}
CHOICES = ("watching", "passing", "planning")
USABLE = ("ok", "partial")
HOUR, TOLERANCE = 60 * 60, 120  # the outcome scorer's 60-minute horizon and its pass tolerance


def choice(text: str) -> str | None:
    word = text.strip().split(" ", 1)[0].strip(".,").lower()
    return word if word in CHOICES else None


def _naive_utc(value: str) -> datetime:
    return datetime.fromtimestamp(epoch(value), UTC).replace(tzinfo=None)


def _price(store: RadarStore, record: dict, symbol: str) -> float | None:
    rows = store.quotes(pass_id=record["id"], symbol=symbol)
    point, _ = _endpoint(rows[0] if rows else None, record)
    return point["price"] if point else None


def _move(store: RadarStore, sign: int, symbol: str, start: dict, end: dict | None, prices: dict) -> tuple[float | None, str | None]:
    if end is None:
        return None, "no pass recorded then"
    for record in (start, end):
        for name in (symbol, "SPY"):
            key = (record["id"], name)
            if key not in prices:
                prices[key] = _price(store, record, name)
    a, b, spy_a, spy_b = prices[(start["id"], symbol)], prices[(end["id"], symbol)], prices[(start["id"], "SPY")], prices[(end["id"], "SPY")]
    if None in (a, b, spy_a, spy_b):
        return None, "no price then"
    return round(sign * ((b / a - 1) - (spy_b / spy_a - 1)) * 100, 2) + 0.0, None  # + 0.0: never "-0"


def _after(store: RadarStore, event: dict, passes: list[dict], session_over: bool, prices: dict) -> dict:
    start = next((p for p in passes if p["finished_at"] == event["first_seen_at"]), None)
    if start is None:
        return {"hour_pct": None, "close_pct": None, "why": "the pass it was seen in was not recorded"}
    sign = 1 if event["direction"] == "up" else -1
    symbol = event["symbols"][0]
    later = [p for p in passes if epoch(p["started_at"]) > epoch(start["started_at"])]
    target = epoch(start["started_at"]) + HOUR
    near = [p for p in later if abs(epoch(p["started_at"]) - target) <= TOLERANCE]
    hour = min(near, key=lambda p: (abs(epoch(p["started_at"]) - target), p["id"])) if near else None
    hour_pct, why = _move(store, sign, symbol, start, hour, prices)
    if session_over:
        close_pct, close_why = _move(store, sign, symbol, start, later[-1] if later else None, prices)
    else:
        close_pct, close_why = None, "the session is still open"
    return {"hour_pct": hour_pct, "close_pct": close_pct, "why": why or close_why}


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def scorecard(store: RadarStore, db: Session, now: float, days: int = WINDOW_DAYS) -> dict:
    today = datetime.fromtimestamp(now, ET).date()
    start = today - timedelta(days=days)
    since = start.isoformat()  # Radar's session names are ISO dates; the journal's day column is a date
    hits = []
    for session in sorted(s for s in store.sessions() if s >= since):
        hits += [e for e in store.events(session) if e.get("kind") in STOCK_KINDS and e.get("symbols")]
    hits.sort(key=lambda e: (e["first_seen_at"], e["event_id"]))
    symbols = {e["symbols"][0] for e in hits}
    decisions = list(db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "decision", DayJournalEntry.symbol.in_(symbols),
                                                           DayJournalEntry.day >= start)
                             .order_by(DayJournalEntry.created_at)).all()) if symbols else []
    plans = radar_proof.planned_events(db, [e["event_id"] for e in hits])
    passes: dict[str, list[dict]] = {}
    prices: dict = {}
    rows = []
    for i, event in enumerate(hits):
        symbol, session = event["symbols"][0], event["session_date"]
        seen = _naive_utc(event["first_seen_at"])
        nxt = next((_naive_utc(o["first_seen_at"]) for o in hits[i + 1:] if o["symbols"][0] == symbol and o["session_date"] == session), None)
        decided = next((d for d in decisions if d.symbol == symbol and d.day.isoformat() == session and d.created_at >= seen
                        and (nxt is None or d.created_at < nxt) and choice(d.text)), None)
        if session not in passes:
            passes[session] = sorted((p for p in store.passes(session) if p["status"] in USABLE), key=lambda p: (p["started_at"], p["id"]))
        plan = plans.get(event["event_id"], {"planned": False, "traded": False})
        rows.append({
            "event_id": event["event_id"], "at": int(epoch(event["first_seen_at"])), "symbol": symbol, "kind": event["kind"],
            "kind_label": KIND.get(event["kind"], "Radar"), "direction": event["direction"], "summary": event.get("summary") or None,
            "decision": choice(decided.text) if decided else None,
            "decided_at": int(decided.created_at.replace(tzinfo=UTC).timestamp()) if decided else None,
            "planned": plan["planned"], "traded": plan["traded"],
            "after": _after(store, event, passes[session], session < today.isoformat(), prices),
        })
    summary = {}
    for decision in (*CHOICES, None):
        mine = [r for r in rows if r["decision"] == decision]
        closes = [r["after"]["close_pct"] for r in mine if r["after"]["close_pct"] is not None]
        summary["none" if decision is None else decision] = {
            "hits": len(mine), "measured": len(closes), "kept_going": sum(1 for v in closes if v > 0),
            "avg_close_pct": _mean(closes),
        }
    rows.reverse()
    return {"state": "ok", "window_days": days, "hits": len(rows), "summary": summary, "rows": rows[:MAX_ROWS],
            "truncated": len(rows) > MAX_ROWS}
