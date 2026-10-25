"""The Dashboard's Plans card: each open position beside the plan it was entered under.

One row per open position (Webull is dormant and left out), marked through
``copilot_book.position_rows`` as the copilot's own book view is. A position's
plan is the oldest capture linked to it (``capture_links.for_trade``). When
that capture came from a Copilot Lab plan card, its investigation (the
capture's ``context.investigation_id``, else its time stop's, which shares the
card's ``client_id``) gives the plan's invalidation alert and time stop, made
within ``copilot_plans.PLAN_WINDOW`` of the capture. The invalidation's
distance uses one batched underlying quote read, as the lab's Plans board does.

A position with no plan carries the one-tap link page when plans are suggested
for it (``plan_nudges.candidates``), else the plan-this-position deep link the
nudge opens. Read-only; the only id out is each row's trade id.
"""

from datetime import UTC, datetime
import math
import time
from urllib.parse import quote, urlencode

from sqlmodel import Session, select

from app.ai import copilot_book
from app.engine import capture_links, copilot_plans, notification_policy, plan_nudges, position_alerts
from app.engine.chart_journal import contract_label
from app.engine.chart_math import ET
from app.models import LevelAlert, PlanTimeStop, TradeCapture

MAX_ROWS = 30
TIMING = {"pre_entry": "pre_entry", "retrospective": "late", "unverified": "unverified"}

_now = time.time  # tests pin the clock here


def _clock(moment: datetime) -> str:
    """'15:30', New York time, from a naive UTC datetime."""
    return moment.replace(tzinfo=UTC).astimezone(ET).strftime("%H:%M")


def _plan_parts(db: Session, capture: TradeCapture) -> tuple[LevelAlert | None, PlanTimeStop | None]:
    """The invalidation alert and time stop a plan card saved with this capture, if it came from one."""
    stop = db.exec(select(PlanTimeStop).where(PlanTimeStop.client_id == capture.client_id)
                   .order_by(PlanTimeStop.created_at.desc())).first()
    investigation = plan_nudges._investigation(capture) or (stop.investigation_id if stop else None)
    if investigation is None:
        return None, stop
    since, until = capture.received_at - copilot_plans.PLAN_WINDOW, capture.received_at + copilot_plans.PLAN_WINDOW
    if stop is None:
        stop = db.exec(select(PlanTimeStop).where(PlanTimeStop.investigation_id == investigation, PlanTimeStop.symbol == capture.underlying,
                                                  PlanTimeStop.created_at >= since, PlanTimeStop.created_at <= until)
                       .order_by(PlanTimeStop.created_at.desc())).first()
    invalidation = db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", LevelAlert.source_id == investigation,
                                                    LevelAlert.plan_role == "invalidation", LevelAlert.symbol == capture.underlying,
                                                    LevelAlert.created_at >= since, LevelAlert.created_at <= until)
                           .order_by(LevelAlert.created_at.desc())).first()
    return invalidation, stop


def _time_stop(stop: PlanTimeStop | None, now: float) -> dict | None:
    if stop is None:
        return None
    due = position_alerts._epoch(stop.due_at)
    state = "pending" if stop.delivery == "scheduled" else stop.delivery
    out = {"text": stop.text, "due_at": int(due), "clock": _clock(stop.due_at), "state": state}
    if state == "pending":
        out["minutes_left"] = max(0, math.ceil((due - now) / 60))
    return out


def _watch(db: Session, trade) -> tuple[str | None, dict | None]:
    """The give-back watch state (options only) and the latest open-trade alert sent for this position."""
    found = position_alerts.for_trade(db, trade)
    watch = found.get("watch")
    giveback = None if watch is None else "fired" if watch.get("fired") else "armed" if watch.get("armed") else "watching"
    sent = [a for a in found.get("alerts", []) if a.get("delivery") in ("sent", "unknown")]
    return giveback, ({"kind": sent[-1]["kind"], "at": sent[-1]["detected_at"]} if sent else None)


def positions(db: Session) -> dict:
    now = _now()
    pairs, total = copilot_book.position_rows(db, limit=MAX_ROWS)
    planned = {}
    for trade, _row in pairs:
        linked = capture_links.for_trade(db, trade.id)
        if linked:
            planned[trade.id] = min(linked, key=lambda c: c.received_at)
    parts = {trade_id: _plan_parts(db, capture) for trade_id, capture in planned.items()}
    symbols = sorted({inv.symbol for inv, _stop in parts.values() if inv is not None and inv.state == "active"})
    last, fetched_at, issue = copilot_plans._quotes(symbols)

    rows = []
    for trade, row in pairs:
        giveback, latest = _watch(db, trade)
        out = {
            "trade_id": str(trade.id), "symbol": trade.ticker,
            "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
            "instrument": trade.instrument_type, "direction": row["direction"], "quantity": row["quantity"],
            "unrealized_usd": row["unrealized_usd"], "unrealized_pct": row["unrealized_pct"],
            "giveback": giveback, "latest_alert": latest,
            "plan": None, "link_path": None, "plan_path": None,
        }
        capture = planned.get(trade.id)
        if capture is not None:
            invalidation, stop = parts[trade.id]
            level = copilot_plans._level(invalidation, last.get(invalidation.symbol)) if invalidation is not None else None
            if level is not None:
                level.pop("interval", None)
            out["plan"] = {
                "setup": plan_nudges.plan_name(capture), "thesis": copilot_plans._thesis(capture.note),
                "timing": TIMING[capture_links.timing(capture.received_at, trade.opened_at)],
                "invalidation": level, "time_stop": _time_stop(stop, now),
            }
        else:
            page = plan_nudges.link_page(db, trade, now)
            if page and page["candidates"]:
                out["link_path"] = f"{plan_nudges.LINK_PATH}?" + urlencode({"trade": str(trade.id)})
            else:
                out["plan_path"] = page["plan_path"] if page else "/copilot-lab?" + urlencode(
                    {"symbol": trade.ticker, "context": f"Plan this position: {out['contract']}. Help me set an invalidation and a time stop."},
                    quote_via=quote)
        rows.append(out)
    return {"positions": rows, "count": total, "quotes_at": fetched_at, "quote_issue": issue,
            "held_back_today": notification_policy.held_back_today(db, now)}
