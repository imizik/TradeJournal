"""Owner view of Jo's conditional price plans. Read-only; no store of its own.

Plans come from the immutable market-watch wake store (accepted by the app
monitor) and the Check outbox (saved by Jo, maybe not yet picked up). Monitoring
is claimed only from the derived status projection's fresh heartbeat.
"""

from datetime import UTC, datetime
import logging
import os
from pathlib import Path

from fastapi import APIRouter

from app.engine import ntfy
from conditional_plan_common import HEARTBEAT_SECONDS, MAX_DAILY_PLANS, read_json, status, validate_plan
from market_watch_common import parse_time, verify
from stock_watch_common import ET, stamp

router = APIRouter()
log = logging.getLogger(__name__)
LIMIT = 50
# How each recorded push result reads to the owner. "accepted" is ntfy taking the
# push, never proof the phone showed it; "sending" with no settled row may have gone out.
OUTCOMES = {"accepted": "sent", "failed": "failed", "unknown": "unknown", "sending": "unknown", "expired": "not_sent"}


def _now():
    return datetime.now(UTC)


def _paths():
    return [os.environ.get(k, "") for k in ("MARKET_WATCH_STORE", "MARKET_WATCH_SNAPSHOTS_DIR", "MARKET_WATCH_OUTBOX_DIR")]


def _readiness(directory, now):
    try:
        r = read_json(Path(directory) / "conditional-plan-readiness.json")
        verify(r)
        if r.get("format") != "conditional-plan-readiness-v1":
            raise ValueError("format")
    except FileNotFoundError:
        return {"heartbeat": "missing"}
    except Exception:
        log.exception("Conditional-plan readiness unreadable")
        return {"heartbeat": "unreadable"}
    age = (now - parse_time(r["created_at"])).total_seconds()
    opened, closed = (parse_time(r[k]) if r.get(k) else None for k in ("session_open_at", "session_close_at"))
    return {"heartbeat": "fresh" if 0 <= age <= HEARTBEAT_SECONDS else "stale", "heartbeat_at": r["created_at"],
            "monitor_enabled": r["enabled"] is True, "session_date": r["session_date"],
            "session_open_at": r["session_open_at"], "session_close_at": r["session_close_at"],
            "session_open_now": bool(opened and closed and opened <= now < closed),
            "symbols": r["symbols"], "selection_revision": r["selection_revision"]}


def _deliveries(attempts, events):
    states = {e["event_id"]: e["state"] for e in events}
    settled = {(a["event_id"], a["attempt"]) for a in attempts if a["result"] != "sending"}
    return [{"event_state": states.get(a["event_id"]), "attempt": a["attempt"], "result": a["result"],
             "outcome": OUTCOMES.get(a["result"], "unknown"), "error_code": a["error_code"],
             "transport_receipt_id": a["transport_receipt_id"], "occurred_at": a["occurred_at"]}
            for a in attempts if a["result"] != "sending" or (a["event_id"], a["attempt"]) not in settled]


@router.get("")
def list_plans():
    from app.engine.conditional_plans import enabled
    from app.engine.stock_watch import enabled as stock_enabled

    now = _now()
    store_path, snapshots, outbox = _paths()
    configured = all(p and Path(p).is_absolute() for p in (store_path, snapshots, outbox))
    view = {"checked_at": stamp(now), "app_flag": enabled(), "stock_watch": stock_enabled(), "configured": configured,
            "readiness": {"heartbeat": "missing"}, "max_daily_plans": MAX_DAILY_PLANS, "limit": LIMIT,
            "delivery": {"channel": "ntfy phone push", "configured": ntfy.configured()}, "plans": []}
    view["enabled"] = view["app_flag"] and view["stock_watch"]
    if not configured:
        return view
    view["readiness"] = _readiness(snapshots, now)

    plans, accepted = {}, set()
    store = None
    if Path(store_path).exists():
        from app.engine.market_watch_wakes import MarketWatchWakeStore

        store = MarketWatchWakeStore(store_path)
        for p in store.records("plan"):
            plans[p["plan_id"]] = p
            accepted.add(p["plan_id"])
    # Saved by Jo and exported, but not yet accepted by the monitor (e.g. while it is off).
    for path in Path(outbox).glob("conditional-plan-cpl_*.json"):
        try:
            p = validate_plan(read_json(path))
            if path.name == f"conditional-plan-{p['plan_id']}.json":
                plans.setdefault(p["plan_id"], p)
        except Exception:
            log.exception("Conditional plan export unreadable: %s", path.name)
    chosen = sorted(plans.values(), key=lambda p: p["created_at"], reverse=True)[:LIMIT]

    by_session = {}
    for day in {p["session_date"] for p in chosen}:
        by_session[day] = {k: store.records(k, day) if store else []
                           for k in ("plan_event", "plan_observation", "plan_push_attempt")}
    today = now.astimezone(ET).date().isoformat()
    view["plans_today"] = sum(p["session_date"] == today for p in plans.values())
    for p in chosen:
        records = by_session[p["session_date"]]
        events = [e for e in records["plan_event"] if e["plan_id"] == p["plan_id"]]
        observations = [o for o in records["plan_observation"] if o["plan_id"] == p["plan_id"]]
        ids = {e["event_id"] for e in events}
        attempts = [a for a in records["plan_push_attempt"] if a["event_id"] in ids]
        try:
            projected = status(snapshots, p, now)
        except Exception:
            log.exception("Conditional plan status unreadable: %s", p["plan_id"])
            projected = {"monitoring": False}
        last = observations[-1] if observations else None
        view["plans"].append({
            **{k: p[k] for k in ("plan_id", "actor", "session_date", "symbol", "direction", "trigger_price",
                                 "invalidation_price", "confirm_bars", "rationale", "source", "expires_at", "created_at")},
            "accepted_by_monitor": p["plan_id"] in accepted,
            "cancel_requested": (Path(outbox) / f"conditional-plan-cancel-{p['plan_id']}.json").exists(),
            "state": events[-1]["state"] if events else "pending_activation",
            "reason": events[-1]["reason"] if events else None,
            "state_at": events[-1]["occurred_at"] if events else None,
            # Never true for a stopped monitor, stale heartbeat, ended plan or switched-off flag.
            "monitoring": projected["monitoring"] is True and view["enabled"],
            "heartbeat_at": projected.get("checked_at"),
            "last_bar": last and {**last["bar"], "consecutive": last["consecutive"]},
            "last_evaluated_at": last and last["created_at"],
            "events": [{k: e[k] for k in ("state", "reason", "occurred_at", "bar")} for e in events],
            "deliveries": _deliveries(attempts, events),
        })
    return view
