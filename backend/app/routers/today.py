"""The owner's Today screen (GET /today): what matters right now, in priority order, from readers that already exist.

Sections, each built on its own so one failure reads ``{"state": "unavailable"}`` and the rest stand
(``copilot_context._section``'s pattern):

- ``act_now``: open positions (``plan_positions.positions``) within ``NEAR_PCT`` of an armed invalidation, past a
  hit one, expiring today (New York), with the give-back alert fired, or with a time stop due within
  ``STOP_MINUTES``;
- ``plans``: armed Copilot Lab plans not yet in a position (``copilot_plans.board``) within ``NEAR_PCT`` of their
  entry or invalidation;
- ``new``: Radar events since the last Radar visit (the feed's own ``since_last_visit``), thesis-watch triggers
  fired today and today's pre-market prep;
- ``held``: pings the notification policy held today (merged, suppressed or over the cap), with their text;
- ``week``: the plan streak's numbers and this week's planned/total entries.

The two plan readers share one batched underlying quote read. Read-only: no store, no pings, no Radar visit.
The only ids out are the ones each row links to: trade ids, Radar event ids and investigation ids (inside paths).
"""

from datetime import UTC, date, datetime
import logging
import time
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.database import get_session
from app.engine.chart_math import ET

log = logging.getLogger(__name__)
router = APIRouter()

NEAR_PCT = 1.0
STOP_MINUTES = 30
MAX_ROWS = 12

_now = time.time  # tests pin the clock here


def _section(db: Session, name: str, build):
    try:
        return build()
    except Exception as exc:  # one failing source must not take the screen down
        log.warning("today %s unavailable: %s", name, type(exc).__name__)
        db.rollback()  # a failed read must not leave the session unusable for the next section
        return {"state": "unavailable"}


def _iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _naive_iso(moment: datetime | None) -> str | None:
    return moment.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if moment else None


def investigation_path(investigation_id: str) -> str:
    return "/copilot-lab?" + urlencode({"investigation": investigation_id})


class SharedQuotes:
    """One batched quote read for every reader on the screen: the first call reads, later calls reuse what it got
    and read only symbols it has not seen (none, in practice: the board reads first, and a position's armed
    invalidation belongs to an armed plan on it)."""

    def __init__(self):
        self.last: dict[str, float] = {}
        self.seen: set[str] = set()
        self.at: float | None = None
        self.issue: str | None = None
        self.reads = 0

    def __call__(self, symbols: list[str]):
        from app.engine import copilot_plans
        missing = sorted(set(symbols) - self.seen)
        if missing:
            self.reads += 1
            last, at, issue = copilot_plans._quotes(missing)
            self.seen.update(missing)
            self.last.update(last)
            self.at = at if at is not None else self.at
            self.issue = issue or self.issue
        return {s: self.last[s] for s in symbols if s in self.last}, self.at, self.issue


# --------------------------------------------------------------------------- sections

def _act_now(db: Session, quotes: SharedQuotes, now: float, today: date, book: dict | None = None) -> dict:
    """``book``: a ``plan_positions.positions`` read the caller already made (the desk's thread list)."""
    from app.engine import plan_positions
    from app.models import Trade
    book = book or plan_positions.positions(db, quotes=quotes)
    expiring = set()
    for row in book["positions"]:
        trade = db.get(Trade, uuid.UUID(row["trade_id"]))
        if trade is not None and trade.instrument_type == "option" and trade.expiration == today:
            expiring.add(row["trade_id"])
    rows = []
    for row in book["positions"]:
        reasons = []
        plan = row["plan"] or {}
        level = plan.get("invalidation")
        if level and level["state"] == "hit":
            reasons.append({"kind": "invalidation_hit", "text": f"Invalidation {level['price']:.2f} hit"})
        elif level and "distance_pct" in level and abs(level["distance_pct"]) <= NEAR_PCT:
            reasons.append({"kind": "invalidation_near",
                            "text": f"{abs(level['distance_pct']):.1f}% from invalidation {level['price']:.2f}"})
        if row["trade_id"] in expiring:
            reasons.append({"kind": "expires_today", "text": "Expires today"})
        if row["giveback"] == "fired":
            reasons.append({"kind": "giveback", "text": "Give-back fired"})
        stop = plan.get("time_stop")
        if stop and stop["state"] == "pending":
            left = (stop["due_at"] - now) / 60
            if left <= STOP_MINUTES:
                minutes = max(0, int(-(-left // 1)))
                reasons.append({"kind": "time_stop", "text": f"Time stop {stop['clock']} · {f'{minutes} min' if minutes else 'due now'}"})
        if reasons:
            rows.append({"trade_id": row["trade_id"], "symbol": row["symbol"], "contract": row["contract"],
                         "quantity": row["quantity"], "unrealized_usd": row["unrealized_usd"],
                         "unrealized_pct": row["unrealized_pct"], "reasons": reasons,
                         # what the Copilot desk's decision bar says beside the reasons: the plan's level and the alert's time
                         "direction": row["direction"], "invalidation": level, "time_stop": stop,
                         "latest_alert": row["latest_alert"]})
    return {"state": "ok", "rows": rows, "open_positions": book["count"]}


def _plans(db: Session, quotes: SharedQuotes) -> dict:
    from app.engine import copilot_plans
    board = copilot_plans.board(db, quotes=quotes)
    rows = []
    for plan in board["plans"]:
        if plan["position"] == "in_position":  # an open position's plan shows under Act now
            continue
        near = [(role, level) for role, level in (("entry", plan["entry"]), ("invalidation", plan["invalidation"]))
                if level and level["state"] == "armed" and "distance_pct" in level and abs(level["distance_pct"]) <= NEAR_PCT]
        if not near:
            continue
        role, level = min(near, key=lambda pair: abs(pair[1]["distance_pct"]))
        rows.append({"symbol": plan["symbol"], "direction": plan["direction"], "thesis": plan["thesis"], "last": plan["last"],
                     "trigger": role, "price": level["price"], "distance_pct": level["distance_pct"],
                     "position": plan["position"], "path": investigation_path(plan["investigation_id"])})
    return {"state": "ok", "rows": rows, "armed": len(board["plans"])}


def _radar(now: float, symbol: str | None = None) -> dict:
    """``symbol``: only events on it (the Charts dock's loop), counted before the row cap."""
    from app.routers import radar
    store, reason = radar._store(read_only=True)
    if store is None:
        return {"state": "off", "reason": reason, "rows": [], "count": 0}
    feed = radar._read_feed(store, None, None, now)
    new = set(feed["since_last_visit"])
    events = [e for e in feed["events"] if e["event_id"] in new and (symbol is None or symbol in (e.get("symbols") or []))]
    events.sort(key=lambda e: e["first_seen_at"], reverse=True)
    rows = [{"event_id": e["event_id"], "symbol": (e.get("symbols") or [""])[0], "kind": e.get("kind"),
             "direction": e.get("direction"), "summary": e.get("summary"), "first_seen_at": e.get("first_seen_at"),
             "path": "/radar?" + urlencode({"event": e["event_id"]})} for e in events[:MAX_ROWS]]
    return {"state": "ok", "rows": rows, "count": len(events), "last_visit_at": feed["last_visit_at"]}


def _thesis(db: Session, today: date, symbol: str | None = None) -> dict:
    from app.models import ThesisWatchTrigger
    query = select(ThesisWatchTrigger).where(ThesisWatchTrigger.day == today.isoformat())
    if symbol is not None:
        query = query.where(ThesisWatchTrigger.symbol == symbol)
    found = db.exec(query.order_by(ThesisWatchTrigger.fired_at.desc())).all()
    rows = [{"symbol": t.symbol, "kind": t.kind, "text": t.text, "fired_at": _naive_iso(t.fired_at), "delivery": t.delivery,
             "path": t.path} for t in found[:MAX_ROWS]]
    return {"state": "ok", "rows": rows, "count": len(found)}


def _prep(db: Session, today: date) -> dict:
    from app.engine import premarket_prep
    from app.models import PremarketPrep
    row = db.exec(select(PremarketPrep).where(PremarketPrep.day == today)).first()
    if row is None:
        return {"state": "ok", "prep": None}
    return {"state": "ok", "prep": {
        "lines": premarket_prep.lines(row.body or "")[:premarket_prep.MAX_LINES], "fallback": row.fallback,
        "delivery": row.delivery, "at": _naive_iso(row.detected_at),
        "path": investigation_path(row.investigation_id) if row.investigation_id else None}}


def _held(db: Session, now: float) -> dict:
    from app.engine import notification_policy as policy
    from app.models import PhonePing
    start, end = policy.day_bounds(now)
    found = db.exec(select(PhonePing).where(PhonePing.decision.in_(policy.HELD), PhonePing.decided_at >= start,
                                            PhonePing.decided_at < end).order_by(PhonePing.decided_at.desc())).all()
    rows = [{"kind": policy._label(p.kind), "decision": p.decision, "symbol": p.symbol, "title": p.title, "body": p.body,
             "reason": p.reason, "at": _naive_iso(p.decided_at)} for p in found[:MAX_ROWS]]
    return {"state": "ok", "rows": rows, "count": len(found)}


def _week(db: Session, now: float) -> dict:
    from app.engine import plan_streak
    s = plan_streak.streak(db, datetime.fromtimestamp(now, UTC).replace(tzinfo=None))
    return {"state": "ok", "show": s["show"], "current": s["current"], "best": s["best"], "pending": s["pending"],
            "planned": s["this_week"]["planned"], "total": s["this_week"]["total"], "week_pending": s["this_week"]["pending"]}


@router.get("")
def today_screen(db: Session = Depends(get_session)):
    now = _now()
    today = datetime.fromtimestamp(now, ET).date()
    quotes = SharedQuotes()
    # The board first: its read covers every armed plan, so the positions' invalidations need no second read.
    plans = _section(db, "plans", lambda: _plans(db, quotes))
    act = _section(db, "act_now", lambda: _act_now(db, quotes, now, today))
    return {
        "as_of": _iso(now), "day": today.isoformat(), "quotes_at": quotes.at, "quote_issue": quotes.issue,
        "act_now": act, "plans": plans,
        "new": {"radar": _section(db, "radar", lambda: _radar(now)), "thesis": _section(db, "thesis", lambda: _thesis(db, today)),
                "prep": _section(db, "prep", lambda: _prep(db, today))},
        "held": _section(db, "held", lambda: _held(db, now)),
        "week": _section(db, "week", lambda: _week(db, now)),
    }
