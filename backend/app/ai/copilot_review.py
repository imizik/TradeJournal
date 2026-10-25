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

``week_review`` is the owner's week (Monday to Friday, New York; by default the
latest week with a closed trade) from the same per-trade pieces: totals, trades
by plan timing (pre-entry, late or unverified, none), the plans' follow-through
(their invalidation alert firing while held and the exit after it; time stops
due and what followed), phone alerts and their follow-up, the four habits this
week against the baseline (``exit_habits``), and the best and worst exits by
option give-back and by P&L.

Read-only. The trade id comes in from the owner's UI and never goes back out:
no trade, fill, account or broker id is returned, and an account appears only by
its name with digit runs removed. Webull stays out (dormant).
"""
from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta

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


def _flags(db, trade, fills: list[dict]) -> dict | None:
    """``exit_habits.habit_flags`` for one closed trade; None unless it is a long option (every entry a buy_to_open)."""
    from app.engine import exit_habits
    from app.engine.analytics import wall_time
    from app.models import FillMarketContext, TradePathMetrics
    entries = [f for f in fills if f["role"] == "entry"]
    if trade.instrument_type != "option" or not entries or any(f["side"] != "buy_to_open" for f in entries):
        return None
    first = min(entries, key=lambda f: (f["executed_at"], str(f["id"])))
    context = db.get(FillMarketContext, first["id"])
    path = db.get(TradePathMetrics, trade.id)
    return exit_habits.habit_flags({
        "realized_pnl": None if trade.realized_pnl is None else float(trade.realized_pnl),
        "opened_at": wall_time(trade.opened_at), "closed_at": wall_time(trade.closed_at) if trade.closed_at else None,
        "hold_duration_mins": trade.hold_duration_mins, "expired_worthless": trade.expired_worthless,
        "peak_pct": None if path is None or path.option_mfe_pct is None else float(path.option_mfe_pct),
        "peak_dollars": None if path is None or path.option_peak_unrealized_pnl is None else float(path.option_peak_unrealized_pnl),
        "day_pnl_before": None if context is None or context.realized_pnl_today_before is None else float(context.realized_pnl_today_before),
    })


def _habits(db, trade, fills: list[dict]) -> dict:
    from app.engine import exit_habits
    flags = _flags(db, trade, fills)
    if flags is None:
        return {"state": "not_applicable", "reason": "The audit's four habits are measured on closed long options only."}
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
           "minutes_held": max(0, int((now_et - opened).total_seconds() // 60)), "days_held": row["days_held"],
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
                         "Percentages are percent. Times are New York. minutes_held and days_held are calendar time since the "
                         "entry, nights and weekends included.",
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


# --------------------------------------------------------------------------- the week

MAX_WEEK_CHARS = MAX_REVIEW_CHARS
EXITS_SHOWN = 3
FOLLOW_SHOWN = 6
TIME_STOPS_SHOWN = 6
SMALL_WEEK = 10  # fewer closed trades than this and the review says the sample is small
OUT_MINUTES = 15  # "exited within 15 minutes" of the invalidation, as exit_habits' alert response
BUCKETS = (("pre_entry", "Plan captured before the entry"), ("late_or_unverified", "Plan captured late, or timing unverified"),
           ("none", "No plan"))

WEEK_PROVENANCE = {
    "totals": "measured: the week's closed trades (closed Monday to Friday, New York)",
    "planned": "measured: the week's trades by whether a plan was captured and linked, and when (owner-said plans, measured timing)",
    "follow_through": "measured: planned trades against their plan's invalidation alert and the fills; the plan's time stops and what followed",
    "alerts": "measured: phone alerts sent for the week's trades and what the fills show happened after each",
    "habits": "measured: the behavior audit's four exit habits this week against the trades before alerts went live; associations, not rules",
    "exits": "measured: the week's best and worst exits by option give-back from peak and by P&L",
}


def _week_of(day) -> tuple[datetime, datetime]:
    """Monday 00:00 to Saturday 00:00, New York wall clock (journal times), for the week holding ``day``."""
    from datetime import time
    monday = day - timedelta(days=day.weekday())
    start = datetime.combine(monday, time())
    return start, start + timedelta(days=5)


def _short(wall: datetime | None, day: datetime | None = None) -> str | None:
    """A compact New York time: ``Mon 10-20 10:05``, or only ``14:40`` on ``day``'s date."""
    from app.engine.analytics import wall_time
    if wall is None:
        return None
    wall = wall_time(wall)
    return wall.strftime("%H:%M") if day is not None and wall_time(day).date() == wall.date() else wall.strftime("%a %m-%d %H:%M")


def _rate(wins: int, n: int) -> float | None:
    return round(100 * wins / n, 1) if n else None


def _bucket(trades: list[dict]) -> dict:
    pnl = sum(t["pnl"] for t in trades)
    paid = sum(t["paid"] for t in trades)
    return {"trades": len(trades), "pnl_usd": round(pnl, 2), "pnl_on_premium_pct": round(100 * pnl / paid, 1) if paid else None,
            "win_rate_pct": _rate(sum(t["pnl"] > 0 for t in trades), len(trades))}


def _invalidation(db, capture, trade) -> dict:
    """Whether the plan's invalidation alert fired while the trade was held, and how soon after it the trade was closed.
    The plan card saves the capture and its time stop under one client id, and arms its alerts under the time stop's
    investigation; a plan without a time stop is matched to the copilot invalidation alert armed right after it."""
    from sqlmodel import select
    from app.engine import capture_links
    from app.models import LevelAlert, LevelAlertEvent, PlanTimeStop
    investigation = db.exec(select(PlanTimeStop.investigation_id).where(PlanTimeStop.client_id == capture.client_id)).first()
    alerts = db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", LevelAlert.plan_role == "invalidation",
                                              LevelAlert.symbol == capture.underlying)).all()
    if investigation:
        alerts = [a for a in alerts if a.source_id == investigation]
    else:
        alerts = [a for a in alerts if capture.received_at - timedelta(minutes=1) <= a.created_at <= capture.received_at + timedelta(minutes=10)]
    if not alerts:
        return {"invalidation": "no_alert"}
    opened, closed = capture_links.entry_utc(trade.opened_at), capture_links.entry_utc(trade.closed_at)
    hit = db.exec(select(LevelAlertEvent.event_at).where(LevelAlertEvent.alert_id.in_([a.id for a in alerts]),
                                                         LevelAlertEvent.event_at >= opened, LevelAlertEvent.event_at <= closed)
                  .order_by(LevelAlertEvent.event_at)).first()
    if hit is None:
        return {"invalidation": "not_hit_while_held", "level": alerts[0].price}
    minutes = int((closed - hit).total_seconds() // 60)
    return {"invalidation": "hit_while_held", "level": alerts[0].price, "hit_at": copilot_book._iso(hit),
            "minutes_to_exit": minutes,
            "then": "expired" if trade.status == "expired" else "out_15m" if minutes <= OUT_MINUTES else "held_past_15m"}


def _week_trade(db, trade, account) -> dict:
    """One closed trade's pieces for the week: plan and its timing, path, alerts and their follow-up, habit flags, and
    the invalidation's follow-through. Each source fails alone."""
    from app.engine import capture_links
    from app.engine.chart_journal import contract_label
    from app.models import TradePathMetrics
    fills = _fills(db, trade)
    plans = _section(lambda: {"rows": capture_links.for_trade(db, trade.id)}).get("rows") or []
    plan = min(plans, key=lambda c: c.received_at) if plans else None
    timing = capture_links.timing(plan.received_at, trade.opened_at) if plan else None
    path = _section(lambda: {"row": db.get(TradePathMetrics, trade.id)}).get("row")
    return {
        "trade": trade, "fills": fills, "pnl": float(trade.realized_pnl or 0), "paid": float(trade.total_premium_paid or 0),
        "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
        "account": copilot_book._label(account.name if account else None),
        "plan": "none" if plan is None else "pre_entry" if timing == "pre_entry" else "late_or_unverified",
        "timing": timing, "path": path,
        "alerts": _section(lambda: _alerts(db, trade, fills)),
        "flags": _section(lambda: {"flags": _flags(db, trade, fills)}).get("flags"),
        "follow": _section(lambda: _invalidation(db, plan, trade)) if plan is not None else None,
    }


def _note(row: dict) -> str | None:
    t, path, follow = row["trade"], row["path"], row["follow"] or {}
    parts = []
    if path is not None and path.option_mfe_pct is not None and path.option_peak_unrealized_pnl is not None:
        parts.append(f"peaked {float(path.option_mfe_pct):+.0f}% (${float(path.option_peak_unrealized_pnl):,.0f}), "
                     f"gave back ${float(path.option_giveback_from_peak or 0):,.0f}")
    if follow.get("invalidation") == "hit_while_held":
        parts.append(f"invalidation hit, out {follow['minutes_to_exit']} min later")
    sent = (row["alerts"] or {}).get("alerts") or []
    if sent:
        parts.append(f"{len(sent)} alert(s), then {sent[-1].get('then') or 'unmatched'}")
    if t.expired_worthless:
        parts.append("expired worthless")
    elif t.hold_duration_mins is not None:
        parts.append(f"held {t.hold_duration_mins} min")
    return _trim("; ".join(parts), 120)


def _exit_row(row: dict) -> dict:
    t, path = row["trade"], row["path"]
    return {k: v for k, v in {
        "contract": row["contract"], "entry": _short(t.opened_at), "exit": _short(t.closed_at, t.opened_at),
        "pnl_usd": _num(t.realized_pnl), "pnl_pct": _pct(t.pnl_pct),
        "giveback_usd": None if path is None else _num(path.option_giveback_from_peak),
        "plan": row["plan"], "note": _note(row),
    }.items() if v is not None}


def _best_worst(rows: list[dict], key) -> dict:
    ranked = sorted(rows, key=key)
    best = ranked[:EXITS_SHOWN]
    worst = [r for r in reversed(ranked) if r not in best][:EXITS_SHOWN]
    return {"best": [_exit_row(r) for r in best], "worst": [_exit_row(r) for r in worst]}


def _exits(rows: list[dict]) -> dict:
    peaked = [r for r in rows if r["path"] is not None and r["path"].option_giveback_from_peak is not None
              and float(r["path"].option_peak_unrealized_pnl or 0) > 0]
    out = {"state": "ok", "by_pnl": _best_worst(rows, lambda r: (-r["pnl"], r["trade"].closed_at))}
    out["by_giveback"] = (_best_worst(peaked, lambda r: (float(r["path"].option_giveback_from_peak), r["trade"].closed_at))
                          if peaked else {"state": "missing", "reason": "No trade this week has a recorded option path with a peak."})
    out["rule"] = ("by_pnl best is the highest P&L; by_giveback best gave back the least from its option peak (trades whose "
                   "path peaked above cost). A trade shows once per ranking.")
    return out


def _follow_through(db, rows: list[dict], start: datetime, end: datetime) -> dict:
    from collections import Counter
    from sqlmodel import select
    from app.engine import capture_links, exit_habits
    from app.models import PlanTimeStop, Trade
    planned = [r for r in rows if r["plan"] != "none"]
    follows = [(r, r["follow"]) for r in planned if isinstance(r["follow"], dict) and "invalidation" in r["follow"]]
    hits = [(r, f) for r, f in follows if f["invalidation"] == "hit_while_held"]
    out = {"state": "ok", "planned_trades": len(planned),
           "with_invalidation_alert": sum(f["invalidation"] != "no_alert" for _, f in follows),
           "invalidation_hit_while_held": len(hits),
           "out_within_15m": sum(f["then"] == "out_15m" for _, f in hits),
           "held_past_15m": sum(f["then"] == "held_past_15m" for _, f in hits),
           "held_past_pnl_usd": round(sum(r["pnl"] for r, f in hits if f["then"] != "out_15m"), 2),
           "hits": [{"contract": r["contract"], "level": f["level"], "hit_at": f["hit_at"], "minutes_to_exit": f["minutes_to_exit"],
                     "then": f["then"], "pnl_usd": round(r["pnl"], 2)} for r, f in hits][:FOLLOW_SHOWN]}
    # Time stops due this week (due_at is UTC; the week is New York), and what followed each ping.
    stops = db.exec(select(PlanTimeStop).where(PlanTimeStop.due_at >= capture_links.entry_utc(start),
                                               PlanTimeStop.due_at < capture_links.entry_utc(end))
                    .order_by(PlanTimeStop.due_at)).all()
    listed, then = [], Counter()
    for stop in stops:
        row = {"symbol": stop.symbol, "said": _trim(stop.text, 60), "due": copilot_book._iso(stop.due_at), "delivery": stop.delivery}
        trade = db.get(Trade, stop.trade_id) if stop.trade_id and stop.delivery in ("sent", "unknown") else None
        if trade is not None and not _webull(db, trade):
            fills = _fills(db, trade)
            held = exit_habits._open_before(sorted(fills, key=lambda f: f["executed_at"]), exit_habits._et(stop.detected_at or stop.due_at), True)
            after = exit_habits.follow_up({"detected_at": stop.detected_at or stop.due_at, "contracts": held, "mark": None},
                                          fills, trade.status) if held > 0 else {"response": None}
            row["then"] = after["response"] or "unmatched"
            then[row["then"]] += 1
        listed.append(row)
    out["time_stops"] = {"due": len(stops), "sent": sum(s.delivery in ("sent", "unknown") for s in stops),
                         "skipped": sum(s.delivery == "skipped" for s in stops), "then": dict(then),
                         "rows": listed[:TIME_STOPS_SHOWN]}
    out["then"] = ("hit_while_held: the plan's invalidation alert fired between the entry and the last exit; out_15m: the "
                   "trade was fully closed within 15 minutes of it. Time stop then: as phone alerts (closed_15m, trimmed_15m, "
                   "closed_later, held_overnight, expired, still_open).")
    return out


def _week_alerts(rows: list[dict]) -> dict:
    from collections import Counter
    sent = [a for r in rows for a in ((r["alerts"] or {}).get("alerts") or [])]
    compared = [a["vs_closing_at_alert_usd"] for a in sent if a.get("vs_closing_at_alert_usd") is not None]
    return {"state": "ok", "sent": sum((r["alerts"] or {}).get("sent", 0) for r in rows),
            "by_kind": dict(Counter(a["kind"] for a in sent)), "then": dict(Counter(a.get("then") or "unmatched" for a in sent)),
            "vs_closing_at_alert_usd": round(sum(compared), 2) if compared else None, "compared": len(compared),
            "rule": "vs_closing_at_alert_usd > 0 means what was done after the alerts beat closing at each alert's mark"}


def _week_habits(db, rows: list[dict]) -> dict:
    from app.engine import exit_habits
    longs = [{"flags": r["flags"], "realized_pnl": r["pnl"]} for r in rows if r["flags"]]
    if not longs:
        return {"state": "not_applicable", "reason": "No closed long options this week; the habits are measured on those only."}
    week = exit_habits.tally(longs)
    baseline = {h["key"]: h["baseline"] for h in exit_habits.build(db)["habits"]}
    return {"state": "ok", "long_options": len(longs), "habits": [{k: v for k, v in {
        "habit": label, "this_week": f"{week[key]['n']} of {week[key]['trades']}", "this_week_pct": _pct(week[key]["pct"]),
        "this_week_pnl_usd": week[key]["pnl"] if week[key]["n"] else None,
        "baseline_pct": _pct(baseline[key]["pct"]), "baseline_trades": baseline[key]["trades"],
    }.items() if v is not None} for key, label in exit_habits.HABITS],
        "baseline": f"every closed long option before {exit_habits.GO_LIVE.isoformat()}, when the phone alerts went live"}


def _webull(db, trade) -> bool:
    from app.models import Account
    account = db.get(Account, trade.account_id)
    return account is not None and account.broker == "webull"


def _latest_close(db):
    from sqlmodel import select
    from app.models import Account, Trade
    webull = list(db.exec(select(Account.id).where(Account.broker == "webull")).all())
    query = select(Trade.closed_at).where(Trade.status.in_(("closed", "expired")), Trade.closed_at.is_not(None))
    if webull:
        query = query.where(Trade.account_id.not_in(webull))
    return db.exec(query.order_by(Trade.closed_at.desc()).limit(1)).first()


def week_review(week_start: str | None = None, session=None) -> dict:
    """The owner's week: closed trades Monday to Friday (New York) of the week holding ``week_start`` (an ISO date), or
    by default the latest week with a closed trade. Webull stays out."""
    from sqlmodel import Session, select
    from app.database import engine
    from app.engine.analytics import wall_time
    from app.models import Account, Trade
    with (Session(engine) if session is None else nullcontext(session)) as db:
        latest = _latest_close(db)
        if week_start is None and latest is None:
            return {"state": "none", "reason": "The journal has no closed trades yet."}
        start, end = _week_of(date.fromisoformat(week_start) if week_start else wall_time(latest).date())
        trades = db.exec(select(Trade).where(Trade.status.in_(("closed", "expired")), Trade.closed_at >= start,
                                             Trade.closed_at < end).order_by(Trade.closed_at)).all()
        accounts = {a.id: a for a in db.exec(select(Account)).all()}
        trades = [t for t in trades if getattr(accounts.get(t.account_id), "broker", None) != "webull"]
        week = {"start": start.date().isoformat(), "end": (end.date() - timedelta(days=1)).isoformat(), "default": week_start is None}
        if not trades:
            return {"state": "none", "week": week, "reason": "No closed trades that week.",
                    "latest_week_with_trades": None if latest is None else _week_of(wall_time(latest).date())[0].date().isoformat()}
        rows = [_week_trade(db, t, accounts.get(t.account_id)) for t in trades]
        n = len(rows)
        review = {
            "state": "ok", "as_of": copilot_book._now(), "week": week, "provenance": WEEK_PROVENANCE,
            "sample": {"trades": n, "small": n < SMALL_WEEK,
                       **({"note": f"Only {n} closed trades: describe the week, but it cannot show that a habit changed."}
                          if n < SMALL_WEEK else {})},
            "totals": {**_bucket(rows), "expired_worthless": sum(bool(r["trade"].expired_worthless) for r in rows),
                       "accounts": sorted({r["account"] for r in rows})},
            "planned": {key: {"label": label, **_bucket([r for r in rows if r["plan"] == key])} for key, label in BUCKETS},
            "follow_through": _section(lambda: _follow_through(db, rows, start, end)),
            "alerts": _section(lambda: _week_alerts(rows)),
            "habits": _section(lambda: _week_habits(db, rows)),
            "exits": _section(lambda: _exits(rows)),
            "units": "P&L in $; pnl_on_premium_pct is P&L over premium paid, in percent; win rates in percent. Times are "
                     "New York (hit_at and due in UTC, with Z).",
            "note": "A week: lead with planned vs unplanned and the plans' follow-through; name at most one or two things "
                    "to practice next week, grounded in these counts. Counts are associations, not causes.",
        }
    return shed_week(review)


def _week_steps(review: dict):
    def keep(key: str, n: int):
        part = (review.get("exits") or {}).get(key)
        if isinstance(part, dict) and "best" in part:
            part["best"], part["worst"] = part["best"][:n], part["worst"][:n]

    def drop_notes():
        for key in ("by_pnl", "by_giveback"):
            for side in ("best", "worst"):
                for row in ((review.get("exits") or {}).get(key) or {}).get(side, []):
                    row.pop("note", None)
    follow = review.get("follow_through") or {}
    yield lambda: review.pop("provenance", None)
    yield lambda: (follow.get("time_stops") or {}).pop("rows", None)
    yield lambda: follow.pop("hits", None)
    yield lambda: keep("by_giveback", 2)
    yield lambda: keep("by_pnl", 2)
    yield drop_notes
    yield lambda: (review.get("exits") or {}).pop("by_giveback", None)


def shed_week(review: dict) -> dict:
    """Drop the least decision-relevant parts until the week fits ``MAX_WEEK_CHARS``; totals, planned vs unplanned and
    the follow-through counts stay."""
    for step in _week_steps(review):
        if len(json.dumps(review, default=str, separators=(",", ":"))) <= MAX_WEEK_CHARS:
            return review
        step()
        review["trimmed"] = True
    return review
