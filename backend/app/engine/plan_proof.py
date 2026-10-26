"""Does planning help? The /proof page's secondary read: closed trades entered with a plan saved before the entry
against trades entered with no plan, since the plan card went live (``GO_LIVE``). Read-only.

**Trades.** Closed long-option trades (status closed or expired, every entry a ``buy_to_open``; the rows
``exit_habits.long_rows`` builds) opened on or after ``GO_LIVE`` in a Robinhood account; Webull stays out (dormant).
Each is grouped by the earliest plan linked to it and that plan's timing (``capture_links.timing``), as the week
review does:

- ``planned``: the plan was captured before the entry (``pre_entry``);
- ``unplanned``: no plan linked;
- ``late``: a plan captured inside the entry's minute (``unverified``) or after it (``retrospective``). Shown, never
  counted in the verdict.

Per group: trades, P&L, mean and median return on premium paid (``pnl_pct``), win rate, and the four exit habits
(``exit_habits.habit_flags`` / ``tally``). A trade with no return on premium is left out of the return figures and
counted as excluded.

**Verdict** (modelled on ``exit_habits.verdict``): ``not_enough_data`` by default; it needs ``MIN_TRADES`` counted
trades in each group. ``helping`` when the planned group's mean return on premium beats the unplanned group's by at
least ``Z`` standard errors and its green-to-red rate is not higher; ``not_helping`` when it is worse by the same
margin. The standard error is the day-clustered one for a difference of means: trades are grouped by their New York
entry day (trades on one day are not independent, which is why the behavior audit resamples by trading day), with
the small-sample factor G/(G-1) for G days.

**Selection bias.** The owner plans the trades he is more careful about, so this can only show that planned trades
do better, never that planning causes it. ``CAVEAT`` says so in the response and on the page.
"""

from collections import defaultdict
from datetime import date
from math import sqrt
from statistics import median

from sqlmodel import Session, select

from app.engine import capture_links, exit_habits
from app.engine.analytics import wall_time
from app.models import Account, CaptureLink, Fill, Trade, TradeCapture, TradeFill

GO_LIVE = date(2026, 10, 25)  # the pre-trade plan card on the Plans board
MIN_TRADES = 20
Z = 2.0
GROUPS = (
    ("planned", "Plan saved before the entry", True),
    ("unplanned", "No plan", True),
    ("late", "Plan saved late, or timing unverified (shown, not counted)", False),
)
CAVEAT = ("Selection-biased: you plan the trades you are more careful about, so this can show that planned trades do "
          "better, not that planning causes it.")


def group_of(timing: str | None) -> str:
    """``planned``, ``unplanned`` or ``late`` for the earliest linked plan's timing (None: no plan)."""
    if timing is None:
        return "unplanned"
    return "planned" if timing == "pre_entry" else "late"


def summarize(rows: list[dict]) -> dict:
    """One group: trades, P&L, return on premium (percent), win rate and the four habits."""
    returns = [r["pnl_pct"] for r in rows if r.get("pnl_pct") is not None]
    pnls = [r["realized_pnl"] for r in rows if r.get("realized_pnl") is not None]
    return {
        "trades": len(rows), "counted": len(returns), "excluded": len(rows) - len(returns),
        "pnl": round(sum(pnls), 2),
        "mean_return_pct": round(100 * sum(returns) / len(returns), 2) if returns else None,
        "median_return_pct": round(100 * median(returns), 2) if returns else None,
        "win_rate": round(sum(p > 0 for p in pnls) / len(pnls), 4) if pnls else None,
        "habits": exit_habits.tally(rows),
    }


def clustered_difference(planned: list[dict], unplanned: list[dict]) -> tuple[float, float | None, int]:
    """(planned mean - unplanned mean, its day-clustered standard error, days), returns as fractions. The error is
    None with fewer than two days."""
    xs = [(r["day"], r["pnl_pct"]) for r in planned if r.get("pnl_pct") is not None]
    ys = [(r["day"], r["pnl_pct"]) for r in unplanned if r.get("pnl_pct") is not None]
    m1, m2 = sum(v for _, v in xs) / len(xs), sum(v for _, v in ys) / len(ys)
    per_day: dict = defaultdict(float)
    for day, value in xs:
        per_day[day] += (value - m1) / len(xs)
    for day, value in ys:
        per_day[day] -= (value - m2) / len(ys)
    days = len(per_day)
    if days < 2:
        return m1 - m2, None, days
    return m1 - m2, sqrt(days / (days - 1) * sum(a * a for a in per_day.values())), days


def verdict(rows: list[dict]) -> dict:
    """Do planned trades do better? Defaults to not_enough_data; never claims a difference the sample cannot show."""
    by = {key: [r for r in rows if r["group"] == key] for key, _, _ in GROUPS}
    planned = [r for r in by["planned"] if r.get("pnl_pct") is not None]
    unplanned = [r for r in by["unplanned"] if r.get("pnl_pct") is not None]
    rule = (f"Helping: at least {MIN_TRADES} trades in each group, the planned trades' mean return on premium higher than "
            f"the unplanned trades' by {Z:g} standard errors (clustered by entry day), and their green-to-red rate not "
            f"higher. Not helping: lower by the same margin. Late plans are shown, not counted.")
    out = {"verdict": "not_enough_data", "rule": rule, "planned": len(planned), "unplanned": len(unplanned),
           "difference_pct": None, "se_pct": None, "days": None, "caveat": CAVEAT}
    if len(planned) < MIN_TRADES or len(unplanned) < MIN_TRADES:
        return {**out, "reason": f"{len(planned)} planned and {len(unplanned)} unplanned of {MIN_TRADES} each needed."}
    diff, se, days = clustered_difference(planned, unplanned)
    out.update(difference_pct=round(100 * diff, 2), se_pct=None if se is None else round(100 * se, 2), days=days)
    if se is None:
        return {**out, "reason": "Every trade is from one day, so there is no spread to judge a difference by."}
    if se <= 0:
        return {**out, "reason": "The returns do not vary from day to day, so there is no spread to judge a difference by."}
    if diff <= -Z * se:
        return {**out, "verdict": "not_helping",
                "reason": f"Planned trades returned {abs(100 * diff):.1f} points less on premium than unplanned ones."}
    if diff < Z * se:
        return {**out, "reason": f"Planned trades differ by {100 * diff:+.1f} points, inside {Z:g} standard errors ({100 * se:.1f})."}
    g2r = {key: exit_habits.tally(by[key])["green_to_red"]["pct"] for key in ("planned", "unplanned")}
    if g2r["planned"] is None or g2r["unplanned"] is None:
        return {**out, "reason": "Planned trades returned more, but the green-to-red rates cannot be compared yet."}
    if g2r["planned"] > g2r["unplanned"]:
        return {**out, "reason": "Planned trades returned more, but went green to red more often."}
    return {**out, "verdict": "helping",
            "reason": f"Planned trades returned {100 * diff:.1f} points more on premium than unplanned ones."}


def card(rows: list[dict], go_live: date = GO_LIVE) -> dict:
    for row in rows:
        row["flags"] = exit_habits.habit_flags(row)
    groups = [{"key": key, "label": label, "in_verdict": counted, **summarize([r for r in rows if r["group"] == key])}
              for key, label, counted in GROUPS]
    return {"go_live": go_live.isoformat(), "trades": len(rows), "groups": groups, "caveat": CAVEAT, "verdict": verdict(rows)}


# ------------------------------------------------------------------ database

def _timings(db: Session) -> dict[str, str]:
    """Each linked trade's earliest plan's timing, through the links as they resolve now."""
    active = db.exec(select(CaptureLink.capture_id).where(CaptureLink.unlinked_at.is_(None))).all()
    captures = list(db.exec(select(TradeCapture).where(TradeCapture.id.in_(active))).all()) if active else []
    received = {c.id: c.received_at for c in captures}
    earliest: dict[str, tuple] = {}
    for capture_id, row in capture_links.link_rows(db, captures).items():
        link = row["link"]
        if not link or not link.get("trade_id"):
            continue
        key = (received[capture_id], str(capture_id))
        if link["trade_id"] not in earliest or key < earliest[link["trade_id"]][0]:
            earliest[link["trade_id"]] = (key, link["timing"])
    return {trade_id: timing for trade_id, (_, timing) in earliest.items()}


def build(db: Session, go_live: date = GO_LIVE) -> dict:
    accounts = [a.id for a in db.exec(select(Account)).all() if (a.broker or "robinhood") == "robinhood"]
    trades = [t for t in db.exec(select(Trade).where(Trade.instrument_type == "option", Trade.account_id.in_(accounts),
                                                     Trade.status.in_(("closed", "expired")))).all()
              if wall_time(t.opened_at).date() >= go_live] if accounts else []
    ids = [t.id for t in trades]
    fills_of: dict = defaultdict(list)
    if ids:
        for row in db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.side, Fill.executed_at)
                           .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(ids))).all():
            fills_of[row.trade_id].append({"id": row.id, "role": row.role, "side": row.side, "executed_at": wall_time(row.executed_at)})
    timings = _timings(db) if ids else {}
    rows = exit_habits.long_rows(db, trades, fills_of)
    for row in rows:
        row["group"] = group_of(timings.get(str(row["id"])))
        row["day"] = row["opened_at"].date()
    return card(rows, go_live)
