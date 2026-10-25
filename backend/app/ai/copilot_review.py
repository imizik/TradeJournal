"""Copilot Lab's trade and position review (docs/copilot-lab.md § Review a trade or position).

``trade_review`` gathers, for one trade the owner opened from its trade page or
a position alert, what the journal already holds about it, from services that
exist. For a closed trade:

- ``trade``: contract, entry and exit (New York wall clock with its offset),
  prices, P&L in $ and %, hold minutes, status, expired worthless;
- ``fills``: how many entries and exits made it;
- ``path``: ``TradePathMetrics`` (option peak %, peak unrealized $, give-back);
- ``plan``: the plan captured before it (``capture_links.for_trade``) and when
  it was captured relative to the entry (``capture_links.timing``);
- ``alerts``: phone alerts sent for the position (``position_alerts.for_trade``)
  and what followed each (``exit_habits.follow_up``);
- ``habits``: this trade against the behavior audit's four exit habits
  (``exit_habits.habit_flags``), closed long options only;
- ``comparison``: the symbol's latest other closed trades (``copilot_book.trades``).

For an open position the same ``trade`` (no exit yet), ``plan``, ``alerts`` (what
followed so far) and ``comparison``, plus ``now``: the current mark and open P&L
(``copilot_book.position_rows``, the dashboard's quote engine), minutes held,
days to expiry, the give-back watch's peak and give-back, and the latest alert.
There is no path or habits section until it closes.

Read-only. The trade id comes in from the owner's UI and never goes back out:
no trade, fill, account or broker id is returned, and an account appears only by
its name with digit runs removed. Webull stays out (dormant).
"""
from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

from app.ai import copilot_book

MAX_REVIEW_CHARS = 5800  # inside copilot_tools.MAX_RESULT_CHARS, so a review is never cut mid-JSON
MAX_ALERTS = 6
MAX_COMPARISON = 4
TEXT = 240

PROVENANCE = {
    "trade": "measured: the journal's reconstructed trade and its fills",
    "path": "measured: the trade's recorded price path after the fact",
    "plan": "owner said: the plan they captured; timing says whether it came before the entry",
    "alerts": "measured: phone alerts sent for this position and what the fills show happened after each",
    "habits": "measured: the behavior audit's four exit habits for this one trade; associations, not rules",
    "comparison": "measured: the symbol's latest other closed trades",
}
OPEN_PROVENANCE = {
    "trade": "measured: the journal's reconstructed open position and its fills so far",
    "now": "fetched: the current mark and open P&L; measured: minutes held, expiry, the give-back watch's peak and the latest alert",
    "plan": PROVENANCE["plan"],
    "alerts": "measured: phone alerts sent for this position and what the fills show since each",
    "comparison": PROVENANCE["comparison"],
}


class ReviewNotFound(LookupError):
    pass


def _trim(text, most: int = TEXT) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= most else text[: most - 1] + "…"


def _pct(fraction) -> float | None:
    return None if fraction is None else round(100 * float(fraction), 1)


def _num(value, places: int = 2) -> float | None:
    return None if value is None else round(float(value), places)


def _fills(db, trade) -> list[dict]:
    from sqlmodel import select
    from app.engine.analytics import wall_time
    from app.models import Fill, TradeFill
    rows = db.exec(select(TradeFill.role, Fill.id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at)
                   .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id == trade.id)).all()
    return [{"id": r.id, "role": r.role, "side": r.side, "contracts": float(r.contracts), "price": float(r.price),
             "executed_at": wall_time(r.executed_at)} for r in rows]


def _path(db, trade) -> dict:
    from app.models import TradePathMetrics
    path = db.get(TradePathMetrics, trade.id)
    if path is None:
        return {"state": "missing", "reason": "No path metrics were recorded for this trade."}
    return {k: v for k, v in {
        "state": "ok", "quality": path.option_path_quality,
        "option_peak_pct": _num(path.option_mfe_pct, 1), "option_peak_unrealized_usd": _num(path.option_peak_unrealized_pnl),
        "option_giveback_from_peak_usd": _num(path.option_giveback_from_peak), "option_giveback_pct": _num(path.option_giveback_pct, 1),
        "option_worst_unrealized_usd": _num(path.option_worst_unrealized_pnl),
        "underlying_peak_pct": _num(path.underlying_mfe_pct), "underlying_worst_pct": _num(path.underlying_mae_pct),
        "post_exit_best_move_30m_pct": _num(path.post_exit_mfe_30m),
    }.items() if v is not None}


def _plan(db, trade) -> dict:
    from app.engine import capture_links
    plans = capture_links.for_trade(db, trade.id)
    if not plans:
        return {"state": "none", "reason": "No plan was captured and linked to this trade."}
    plan = sorted(plans, key=lambda c: c.received_at)[0]
    return {k: v for k, v in {
        "state": "ok", "setup": _trim(plan.setup_label, 60), "side": plan.side, "mode": plan.mode,
        "wording": _trim(plan.wording), "note": _trim(plan.note), "planned_quantity": plan.quantity,
        "captured_at": copilot_book._iso(plan.received_at),
        "timing": capture_links.timing(plan.received_at, trade.opened_at),
    }.items() if v is not None}


def _alerts(db, trade, fills: list[dict]) -> dict:
    from app.engine import exit_habits, position_alerts
    sent = [a for a in position_alerts.for_trade(db, trade)["alerts"] if a["delivery"] in ("sent", "unknown")]
    rows = []
    for a in sent[-MAX_ALERTS:]:
        after = exit_habits.follow_up({"detected_at": datetime.fromtimestamp(a["detected_at"], UTC).replace(tzinfo=None),
                                       "contracts": float(a["contracts"]), "mark": a["mark"]}, fills, trade.status)
        rows.append({k: v for k, v in {
            "kind": a["kind"], "at": copilot_book._iso(a["detected_at"]), "contracts_open": float(a["contracts"]),
            "mark": a["mark"], "gain_usd": a["gain"], "gain_pct": _pct(a["gain_pct"]),
            "peak_gain_usd": a["peak_gain"], "peak_gain_pct": _pct(a["peak_gain_pct"]),
            "then": after["response"], "vs_closing_at_alert_usd": after["vs_alert"], "value_at_alert_usd": after["value_at_alert"],
            "realized_after_usd": after["realized_after"], "closed_at": copilot_book._journal_time(after["closed_at"]),
            "note": after["note"],
        }.items() if v is not None})
    return {"state": "ok", "sent": len(sent), "shown": len(rows), "alerts": rows,
            "then": "closed_15m, trimmed_15m, closed_later (same day), held_overnight, expired; vs_closing_at_alert_usd > 0 "
                    "means what was done beat closing at the alert's mark"}


def _habits(db, trade, fills: list[dict]) -> dict:
    from app.engine import exit_habits
    from app.engine.analytics import wall_time
    from app.models import FillMarketContext, TradePathMetrics
    entries = [f for f in fills if f["role"] == "entry"]
    if trade.instrument_type != "option" or not entries or any(f["side"] != "buy_to_open" for f in entries):
        return {"state": "not_applicable", "reason": "The audit's four habits are measured on closed long options only."}
    first = min(entries, key=lambda f: (f["executed_at"], str(f["id"])))
    context = db.get(FillMarketContext, first["id"])
    path = db.get(TradePathMetrics, trade.id)
    flags = exit_habits.habit_flags({
        "realized_pnl": None if trade.realized_pnl is None else float(trade.realized_pnl),
        "opened_at": wall_time(trade.opened_at), "closed_at": wall_time(trade.closed_at) if trade.closed_at else None,
        "hold_duration_mins": trade.hold_duration_mins, "expired_worthless": trade.expired_worthless,
        "peak_pct": None if path is None or path.option_mfe_pct is None else float(path.option_mfe_pct),
        "peak_dollars": None if path is None or path.option_peak_unrealized_pnl is None else float(path.option_peak_unrealized_pnl),
        "day_pnl_before": None if context is None or context.realized_pnl_today_before is None else float(context.realized_pnl_today_before),
    })
    return {"state": "ok", "habits": [{"habit": label, "this_trade": {True: "yes", False: "no", None: "unknown (data missing)"}[flags[key]]}
                                      for key, label in exit_habits.HABITS]}


def _now(db, trade) -> dict:
    from app.engine import position_alerts
    from app.engine.chart_math import ET
    pairs, _ = copilot_book.position_rows(db, limit=1, only=trade)
    if not pairs:
        return {"state": "unavailable", "reason": "The journal shows nothing open for this position."}
    row = pairs[0][1]
    now_et = datetime.now(ET)
    opened = trade.opened_at.replace(tzinfo=ET) if trade.opened_at.tzinfo is None else trade.opened_at.astimezone(ET)
    out = {"state": "ok", "mark": row["mark"], "mark_as_of": row.get("mark_as_of"),
           "open_quantity": row["quantity"], "avg_entry": row["avg_entry"],
           "open_pnl_usd": row["unrealized_usd"], "open_pnl_pct": row["unrealized_pct"],
           "minutes_held": max(0, int((now_et - opened).total_seconds() // 60)),
           "quote": None if row["mark"] is not None else "No current quote came back, so the open P&L is unknown."}
    if trade.instrument_type == "option" and trade.expiration:
        out["days_to_expiry"] = (trade.expiration - now_et.date()).days
        out["expires_today"] = trade.expiration == now_et.date()
        watch = position_alerts.for_trade(db, trade)
        if w := watch.get("watch"):
            out["peak_gain_usd"], out["peak_gain_pct"] = w.get("peak_gain"), _pct(w.get("peak_gain_pct"))
            if w.get("peak_gain") is not None and row["unrealized_usd"] is not None:
                out["given_back_from_peak_usd"] = round(max(0.0, w["peak_gain"] - row["unrealized_usd"]), 2)
            out["giveback_watch"] = "fired" if w.get("fired") else "armed" if w.get("armed") else "not armed"
        sent = [a for a in watch.get("alerts", []) if a["delivery"] in ("sent", "unknown")]
        if sent:
            a = sent[-1]
            out["latest_alert"] = {"kind": a["kind"], "at": copilot_book._iso(a["detected_at"]), "gain_usd": a["gain"],
                                   "gain_pct": _pct(a["gain_pct"])}
    return {k: v for k, v in out.items() if v is not None}


def _comparison(db, trade) -> dict:
    rows = copilot_book.trades(trade.ticker, MAX_COMPARISON, session=db, exclude=trade.id)["trades"]
    for row in rows:
        row.pop("account", None)
    return {"state": "ok", "symbol": trade.ticker, "trades": rows}


def _section(build) -> dict:
    try:
        return build()
    except Exception as exc:  # one failing source must not take the review down
        import logging
        logging.getLogger(__name__).warning("trade review section unavailable: %s", type(exc).__name__)
        return {"state": "unavailable"}


def trade_review(trade_id: str, session=None) -> dict:
    """The review of one closed trade or open position; ``ReviewNotFound`` when no trade has that id."""
    from sqlmodel import Session
    from app.database import engine
    from app.engine.chart_journal import contract_label
    from app.models import Account, Trade
    with (Session(engine) if session is None else nullcontext(session)) as db:
        trade = db.get(Trade, uuid.UUID(trade_id))
        if trade is None:
            raise ReviewNotFound(trade_id)
        account = db.get(Account, trade.account_id)
        if account is not None and account.broker == "webull":
            return {"state": "unavailable", "reason": "Webull trades are left out (dormant by the owner's choice)."}
        fills = _fills(db, trade)
        about = {
            "symbol": trade.ticker, "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type,
                                                               trade.strike, trade.expiration),
            "instrument": trade.instrument_type, "account": copilot_book._label(account.name if account else None),
            "quantity": float(trade.contracts), "entry_time": copilot_book._journal_time(trade.opened_at),
            "entry_price": copilot_book._round(float(trade.avg_entry_premium)), "premium_paid_usd": _num(trade.total_premium_paid),
            "status": trade.status,
            "fills": {"count": len(fills), "entries": sum(f["role"] == "entry" for f in fills),
                      "exits": sum(f["role"] != "entry" for f in fills)},
        }
        if trade.status == "open":
            return shed({
                "state": "ok", "as_of": copilot_book._now(), "provenance": OPEN_PROVENANCE, "trade": about,
                "now": _section(lambda: _now(db, trade)),
                "plan": _section(lambda: _plan(db, trade)),
                "alerts": _section(lambda: _alerts(db, trade, fills)),
                "comparison": _section(lambda: _comparison(db, trade)),
                "units": "Option prices are per contract as the journal stores them (premium x 100); stock prices per share. "
                         "Percentages are percent. Times are New York.",
                "note": "An open position: lead with the decision now. Keep the thesis apart from the position (time held, gain "
                        "given back, expiry near), and compare with the plan's invalidation and time stop if one was captured. "
                        "The owner decides; nothing here is an order.",
            })
        review = {
            "state": "ok", "as_of": copilot_book._now(), "provenance": PROVENANCE,
            "trade": {
                **about, "exit_time": copilot_book._journal_time(trade.closed_at),
                "exit_price": None if trade.avg_exit_premium is None else copilot_book._round(float(trade.avg_exit_premium)),
                "pnl_usd": _num(trade.realized_pnl), "pnl_pct": _pct(trade.pnl_pct), "hold_minutes": trade.hold_duration_mins,
                "expired_worthless": bool(trade.expired_worthless),
            },
            "path": _section(lambda: _path(db, trade)),
            "plan": _section(lambda: _plan(db, trade)),
            "alerts": _section(lambda: _alerts(db, trade, fills)),
            "habits": _section(lambda: _habits(db, trade, fills)),
            "comparison": _section(lambda: _comparison(db, trade)),
            "units": "Option prices are per contract as the journal stores them (premium x 100); stock prices per share. "
                     "Percentages are percent. Times are New York.",
            "note": "One trade: compare the plan with what happened and keep thesis apart from execution. A single trade "
                    "rarely supports a lesson on its own.",
        }
    return shed(review)


def _keep(review: dict, section: str, key: str, rows: slice) -> None:
    part = review.get(section)
    if isinstance(part, dict) and key in part:
        part[key] = part[key][rows]
        if "shown" in part:
            part["shown"] = len(part[key])


def _shed_steps(review: dict):
    yield lambda: review.pop("provenance", None)
    yield lambda: _keep(review, "comparison", "trades", slice(0, 2))
    yield lambda: _keep(review, "alerts", "alerts", slice(-3, None))
    yield lambda: _keep(review, "comparison", "trades", slice(0, 0))


def shed(review: dict) -> dict:
    """Drop the least decision-relevant parts until the review fits ``MAX_REVIEW_CHARS``; the trade and plan stay."""
    for step in _shed_steps(review):
        if len(json.dumps(review, default=str, separators=(",", ":"))) <= MAX_REVIEW_CHARS:
            return review
        step()
        review["trimmed"] = True
    return review
