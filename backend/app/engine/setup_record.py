"""The owner's own record for a new option plan's setup, for the Copilot desk's plan card (docs/copilot-lab.md § The
desk).

His closed option trades opened in the session's first hour (``OPENING``), split as the October 29, 2026 opening review
split them:
- **gap**: against today's gap (a call after a gap down of ``GAP_PCT`` or more, a put after a gap up), with it, or a
  small gap;
- **trend**: below (calls) or above (puts) the 20-day average at entry, against the trend, or with it;
- **size**: his usual premium (the median) and how his largest quarter by premium went.

History comes from the journal: each trade's first entry fill and its market context (``entry_gap_pct``, and the entry
price against ``entry_sma_20``, the 20-day average as of the prior close). Today's gap and 20-day average come from
the chart feed's daily bars, so a plan drafted before today's daily bar has no gap line. A cohort of fewer than
``MIN_TRADES`` is left out. Webull trades are left out, as everywhere. Read-only; no model call, no order.
"""
from __future__ import annotations

from datetime import date, datetime
from statistics import median
from typing import Callable

from sqlmodel import Session, select

from app.engine.chart_math import ET
from app.models import Account, Fill, FillMarketContext, Trade, TradeFill

OPENING = (9 * 60 + 30, 10 * 60 + 30)  # first entry fill, New York wall clock, end exclusive
GAP_PCT = 1.0
MIN_TRADES = 5
SMA_DAYS = 20
EXCLUDED_BROKERS = {"webull"}
SIGN = {"call": 1, "put": -1}


def opening_trades(db: Session) -> list[dict]:
    """Each closed option trade opened in the first hour: side, gap and distance from the 20-day average at entry
    (percent, None without market context), premium paid and realized P&L."""
    found = db.exec(select(Trade, Account.broker).join(Account, Trade.account_id == Account.id)
                    .where(Trade.instrument_type == "option", Trade.status != "open", Trade.realized_pnl.is_not(None),
                           Trade.option_type.in_(tuple(SIGN)))).all()
    trades = [t for t, broker in found if (broker or "").lower() not in EXCLUDED_BROKERS
              and OPENING[0] <= t.opened_at.hour * 60 + t.opened_at.minute < OPENING[1]]
    if not trades:
        return []
    entries = db.exec(select(TradeFill.trade_id, Fill.id, Fill.executed_at, Fill.raw_email_id)
                      .join(Fill, Fill.id == TradeFill.fill_id)
                      .where(TradeFill.trade_id.in_([t.id for t in trades]), TradeFill.role == "entry")).all()
    first: dict = {}
    for row in sorted(entries, key=lambda r: (r.executed_at, r.raw_email_id or "", str(r.id))):
        first.setdefault(row.trade_id, row.id)
    contexts = {c.fill_id: c for c in db.exec(select(FillMarketContext)
                                              .where(FillMarketContext.fill_id.in_(list(first.values())))).all()}
    out = []
    for t in trades:
        c = contexts.get(first.get(t.id))
        price, sma = (c.entry_underlying_price, c.entry_sma_20) if c else (None, None)
        out.append({"side": t.option_type, "gap_pct": c.entry_gap_pct if c else None,
                    "vs_sma_pct": (price / sma - 1) * 100 if price and sma else None,
                    "premium": float(t.total_premium_paid), "pnl": float(t.realized_pnl)})
    return out


def gap_relation(side: str, gap_pct: float | None) -> str | None:
    if gap_pct is None:
        return None
    signed = SIGN[side] * gap_pct
    return "against" if signed <= -GAP_PCT else "with" if signed >= GAP_PCT else "small"


def trend_relation(side: str, vs_sma_pct: float | None) -> str | None:
    return None if vs_sma_pct is None else "against" if SIGN[side] * vs_sma_pct < 0 else "with"


def _summary(rows: list[dict]) -> dict | None:
    if len(rows) < MIN_TRADES:
        return None
    return {"trades": len(rows), "won": sum(r["pnl"] > 0 for r in rows), "pnl": round(sum(r["pnl"] for r in rows), 2)}


def record(trades: list[dict], gap_pct: float | None, vs_sma_pct: float | None) -> dict:
    """Per side, today's relation to the gap and the trend with the matching cohort's record (None when today's
    relation is unknown or the cohort is thin), and the size record over all of them."""
    sides = {}
    for side in SIGN:
        mine = [t for t in trades if t["side"] == side]
        gap, trend = gap_relation(side, gap_pct), trend_relation(side, vs_sma_pct)
        sides[side] = {
            "gap": None if gap is None else {"relation": gap, "record": _summary(
                [t for t in mine if gap_relation(side, t["gap_pct"]) == gap])},
            "trend": None if trend is None else {"relation": trend, "record": _summary(
                [t for t in mine if trend_relation(side, t["vs_sma_pct"]) == trend])},
        }
    premiums = sorted(t["premium"] for t in trades)
    size = None
    if len(premiums) >= 4 * MIN_TRADES:
        top = premiums[(3 * len(premiums)) // 4]
        size = {"usual": round(median(premiums), 2), "top_quarter_from": round(top, 2),
                "top_quarter": _summary([t for t in trades if t["premium"] >= top])}
    return {"calls": sides["call"], "puts": sides["put"], "size": size}


def today_context(daily: list[dict], today: date) -> dict:
    """Today's gap (percent, None before today's daily bar) and the latest price against the 20-day average of the
    closes before today (percent), from daily bars (``time``, ``open``, ``close``)."""
    def day(bar):
        return datetime.fromtimestamp(bar["time"], ET).date()
    prior = [b for b in daily if day(b) < today]
    current = next((b for b in daily if day(b) == today), None)
    if not prior:
        return {"gap_pct": None, "vs_sma_pct": None}
    close = prior[-1]["close"]
    sma = sum(b["close"] for b in prior[-SMA_DAYS:]) / SMA_DAYS if len(prior) >= SMA_DAYS else None
    last = current["close"] if current else close
    return {"gap_pct": round((current["open"] / close - 1) * 100, 2) if current and close else None,
            "vs_sma_pct": round((last / sma - 1) * 100, 2) if sma else None}


def _daily_bars(symbol: str) -> list[dict]:
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    data = chart_feed.workspace(symbol, ["1D"], [], "extended", calendar=chart_calendar, quotes=False)
    return list(((data.get("panels") or {}).get("1D") or {}).get("bars") or [])


def for_symbol(db: Session, symbol: str, now: float, daily: Callable[[str], list[dict]] | None = None) -> dict:
    """The plan card's setup lines for ``symbol``: today's context and, per side, the owner's matching record. A daily
    read that fails leaves the context empty (no gap or trend line); the size record stands on its own."""
    try:
        context = today_context((daily or _daily_bars)(symbol), datetime.fromtimestamp(now, ET).date())
    except Exception:  # noqa: BLE001 - a missing chart read is a missing line, never a failed plan card
        context = {"gap_pct": None, "vs_sma_pct": None}
    return {**context, **record(opening_trades(db), context["gap_pct"], context["vs_sma_pct"])}
