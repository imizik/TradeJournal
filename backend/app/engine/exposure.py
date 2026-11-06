"""At risk now: one deterministic exposure line for the Desk and the 09:00 morning brief (docs/copilot-lab.md § Exposure).

"At risk now: $6,400 in 3 options · usual day $2,100". No model call, no provider read; journal rows only.

- ``at_risk_usd``: the premium still paid for the open long option positions, every account but Webull (dormant): for
  each open position, the cost of the contracts still open, first in, first out (``chart_journal.open_lots``, the
  replay the position lines and the add-to-loser interrupt use). Option prices are stored per contract, so contracts x
  price is dollars. Stocks are left out (long holds, not premium at risk); shorts receive premium and are left out.
- ``usual_day_usd``: the median, over the last ``USUAL_DAYS`` New York days before today that had at least one long
  option entry, of that day's total ``buy_to_open`` option premium (every account but Webull). Under ``MIN_DAYS`` such
  days it is null and the line leaves it off.

Any failure returns ``state: unavailable`` and no line, never an exception in a caller.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import logging
from statistics import median

from sqlalchemy import or_
from sqlmodel import Session, select

from app.engine.chart_journal import open_lots
from app.engine.chart_math import ET
from app.models import Account, Fill, Trade, TradeFill

log = logging.getLogger(__name__)

USUAL_DAYS = 60  # entry days in the usual-day median
MIN_DAYS = 10  # fewer entry days than this: no usual day
COST_RULE = "fifo"  # the open contracts' cost: first in, first out (chart_journal.open_lots)


def _not_webull():
    return or_(Account.broker.is_(None), Account.broker != "webull")  # Dormant by the owner's choice.


def _at_risk(db: Session) -> tuple[float, int]:
    trades = db.exec(select(Trade.id).join(Account, Account.id == Trade.account_id)
                     .where(Trade.status == "open", Trade.instrument_type == "option").where(_not_webull())).all()
    if not trades:
        return 0.0, 0
    fills: dict = defaultdict(list)
    for row in db.exec(select(TradeFill.trade_id, Fill.id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at)
                       .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(list(trades)))).all():
        fills[row.trade_id].append({"id": row.id, "side": row.side, "contracts": row.contracts, "price": row.price,
                                    "executed_at": row.executed_at})
    total, count = 0.0, 0
    for trade_id in trades:
        lots = open_lots(fills.get(trade_id, []))
        if lots["direction"] == "long" and lots["open"] > 0 and lots["avg_cost"] is not None:
            total += lots["open"] * lots["avg_cost"]
            count += 1
    return total, count


def _usual_day(db: Session, today) -> tuple[float | None, int]:
    start = datetime.combine(today, datetime.min.time())  # journal times are naive New York wall clocks
    rows = db.exec(select(Fill.executed_at, Fill.contracts, Fill.price).join(Account, Account.id == Fill.account_id)
                   .where(Fill.side == "buy_to_open", Fill.instrument_type == "option", Fill.executed_at < start)
                   .where(_not_webull())).all()
    by_day: dict = defaultdict(float)
    for executed_at, contracts, price in rows:
        by_day[executed_at.date()] += float(contracts) * float(price)
    days = sorted(by_day, reverse=True)[:USUAL_DAYS]
    if len(days) < MIN_DAYS:
        return None, len(days)
    return median(by_day[d] for d in days), len(days)


def now(db: Session, at: datetime) -> dict:
    """The exposure summary at ``at`` (aware, or a naive New York wall clock); New York's date picks today."""
    at_et = at.astimezone(ET) if at.tzinfo else at.replace(tzinfo=ET)
    try:
        at_risk, positions = _at_risk(db)
        usual, sample = _usual_day(db, at_et.date())
    except Exception as exc:  # noqa: BLE001 - the line is extra; a caller never fails on it
        log.warning("exposure unavailable: %s", type(exc).__name__)
        return {"state": "unavailable", "at_risk_usd": None, "positions": None, "usual_day_usd": None, "sample_days": None,
                "as_of": at_et.isoformat(timespec="seconds")}
    return {"state": "ok", "at_risk_usd": round(at_risk, 2), "positions": positions,
            "usual_day_usd": None if usual is None else round(usual, 2), "sample_days": sample,
            "as_of": at_et.isoformat(timespec="seconds")}


def line(summary: dict | None) -> str | None:
    """"At risk now: $6,400 in 3 options · usual day $2,100"; None when unavailable or no long option is open."""
    if not summary or summary.get("state") != "ok" or not summary.get("positions"):
        return None
    n = summary["positions"]
    out = f"At risk now: ${summary['at_risk_usd']:,.0f} in {n} option{'' if n == 1 else 's'}"
    if summary.get("usual_day_usd") is not None:
        out += f" · usual day ${summary['usual_day_usd']:,.0f}"
    return out
