"""The trade origin chain in Copilot Lab's reviews (docs/copilot-lab.md § Origin).

A pre-trade plan records what prompted it (``TradeCapture.origin_kind``, ``origin_ref``, ``origin_text``):
a Radar event, a thesis-watch ping, the pre-market prep, a page's Plan a trade, the lab itself, or the owner.

- ``trade_origin``: for one trade, the origin of the plan linked to it, in words, and for a Radar event that
  event's summary and the owner's rating, read from the Radar file. No id goes out: references are used only to
  look things up, and ids inside the context line are removed.
- ``week_origins``: the week's closed trades by the origin of their plan, with P&L.

Kept apart from ``copilot_review`` so its prompt and sections can change without touching this.
"""
from __future__ import annotations

import os
import re

TEXT = 240
LABELS = {
    "radar_event": "a Radar event", "thesis_watch": "a thesis-watch ping", "premarket_prep": "the pre-market prep",
    "chart": "Plan a trade on the chart", "dashboard": "Plan a trade on the dashboard", "copilot": "a Copilot Lab conversation",
    "manual": "the owner's own idea",
}
UUIDS = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def origin_text(text: str | None) -> str | None:
    """The context line in words: without the "Plan a trade:" prefix, a ping's instructions to the copilot, or any id."""
    words = re.sub(r"^Plan a trade:\s*", "", text or "", flags=re.I)
    words = re.sub(r"\s*(What changed\?|Does it still hold\?).*$", "", words)
    words = " ".join(UUIDS.sub("", words).split())
    return words[:TEXT] or None


def _first_plan(db, trade):
    from app.engine import capture_links
    plans = capture_links.for_trade(db, trade.id)
    return min(plans, key=lambda c: c.received_at) if plans else None


def radar_event(ref: str) -> dict:
    """The Radar event's summary, when it was first seen, and the owner's latest rating; read-only."""
    from app.engine.radar_runner import enabled
    from app.engine.radar_store import RadarStore
    path = os.environ.get("RADAR_STORE", "").strip()
    if not enabled() or not path or not os.path.isabs(path):
        return {"state": "unavailable", "reason": "Radar is not switched on here."}
    store = RadarStore(path, read_only=True)
    event = store.event(ref)
    if event is None:
        return {"state": "unavailable", "reason": "The Radar event is no longer in the Radar file."}
    return {"state": "ok", "summary": event["summary"][:TEXT], "first_seen_at": event["first_seen_at"],
            "rating": store.latest_ratings().get(ref) or "unrated"}


def trade_origin(db, trade) -> dict:
    """What prompted the plan linked to ``trade``."""
    plan = _first_plan(db, trade)
    if plan is None:
        return {"state": "none", "reason": "No plan is linked to this trade, so nothing records what prompted it."}
    if not plan.origin_kind:
        return {"state": "unknown", "reason": "The plan was saved before the app recorded what prompted plans."}
    out = {"state": "ok", "kind": plan.origin_kind, "from": LABELS.get(plan.origin_kind, plan.origin_kind),
           "text": origin_text(plan.origin_text)}
    if plan.origin_kind == "radar_event" and plan.origin_ref:
        try:
            out["radar_event"] = radar_event(plan.origin_ref)
        except Exception:  # an unreadable Radar file leaves the rest of the origin
            out["radar_event"] = {"state": "unavailable", "reason": "The Radar file could not be read right now."}
    return {k: v for k, v in out.items() if v is not None}


def week_origins(db, trades) -> str:
    """One line: the week's closed trades by what prompted their plan, with P&L, most trades first (``no_plan``: none
    linked; ``unrecorded``: a plan saved before origins were recorded). E.g. "radar_event 2 +$140; no_plan 5 -$320"."""
    by_kind: dict[str, list] = {}
    for trade in trades:
        plan = _first_plan(db, trade)
        kind = "no_plan" if plan is None else plan.origin_kind or "unrecorded"
        row = by_kind.setdefault(kind, [0, 0.0])
        row[0] += 1
        row[1] += float(trade.realized_pnl or 0)
    return "; ".join(f"{kind} {n} {'-' if pnl < 0 else '+'}${abs(pnl):,.0f}"
                     for kind, (n, pnl) in sorted(by_kind.items(), key=lambda kv: -kv[1][0]))
