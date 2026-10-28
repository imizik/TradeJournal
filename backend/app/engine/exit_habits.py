"""Exit habits: what happened after each open-trade phone alert, and the four
costly exit habits from the October 21, 2026 behavior audit
(``backend/reports/behavior_audit_2026-10-21.md``), recent trades against the
trades before the alerts went live. Read-only: nothing here writes a trade,
fill or stored money value.

**Alert follow-up.** Each sent (or ``unknown``-delivery) ``position_alert`` is
matched to its position the way ``position_alerts`` anchors it: the trade that
holds the fill whose source ID is the alert's ``source_key``, in its account.
The contracts open at the alert are the oldest lots then, so under first in,
first out the first ``contracts`` sold after the alert are theirs; anything
bought later sits behind them. From those sales:

- ``closed_15m``: all of them sold within 15 minutes of the alert;
- ``trimmed_15m``: some, not all, sold within 15 minutes;
- ``expired``: some still held when the option expired;
- ``closed_later``: all sold later the same day (ET);
- ``held_overnight``: the last of them sold on a later day;
- ``still_open``: some are still held and the option has not expired.

``vs_alert`` is what those contracts brought in (zero for any that expired)
minus their value at the alert's midpoint mark, in dollars: positive means
proceeds exceeded the recorded midpoint value. This reference mark is not
a guaranteed executable exit price. Cost cancels out of the difference, so it
is the same as realized P&L minus P&L at the mark. It is None,
with a reason, when the alert had no mark, the position is still open, or the
fills no longer show the alert's contracts open at the alert.

**Habits.** Closed long-option trades (status closed or expired, every entry a
``buy_to_open``), by close date: the trades before ``GO_LIVE`` are the
baseline; the latest ``WINDOW`` trades closed since then are compared with it.
A trade missing what a habit needs is left out of that habit and counted as
excluded, never counted as a zero.

- ``green_to_red``: option path peak at least +10% of cost and $50
  (``option_mfe_pct``, ``option_peak_unrealized_pnl``), then closed red;
- ``held_hour_lost``: held 60 minutes or more, closed the same ET day, red;
- ``expired_worthless``: written off at expiration;
- ``opened_green``: the first entry fill came while that account's realized P&L
  for the day was above zero (``realized_pnl_today_before``).

**Verdict** (the /proof page): ``helping``, ``not_helping`` or, by default,
``not_enough_data``, with the rule and sample stated; see ``verdict``.
"""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from math import sqrt

from sqlmodel import Session, select

from app.engine.analytics import wall_time
from app.engine.chart_journal import OPEN_SIDES
from app.engine.chart_math import ET
from app.models import Fill, FillMarketContext, PositionAlert, Trade, TradeFill, TradePathMetrics

GO_LIVE = date(2026, 10, 21)  # POSITION_ALERTS_ENABLED=true on the VPS
WINDOW = 30
RESPONSE_MINUTES = 15
PEAK_PCT = 10.0  # option_mfe_pct is in percent
PEAK_DOLLARS = 50.0
HOUR = 60
ALERTS_SHOWN = 20
EPS = 1e-9
# The /proof verdict: a habit moved when its recent rate is at least Z binomial standard errors (at the
# baseline rate) from the baseline, over at least MIN_HABIT_TRADES counted trades.
Z = 2.0
MIN_HABIT_TRADES = 20
HABITS_TO_HELP = 2


def _et(moment_utc: datetime) -> datetime:
    """A naive UTC moment (``position_alert`` columns) as naive ET wall clock (``fill.executed_at``)."""
    return moment_utc.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)


def _open_before(fills: list[dict], cut: datetime, inclusive: bool) -> float:
    held = 0.0
    for f in fills:
        if f["executed_at"] < cut or (inclusive and f["executed_at"] == cut):
            held += f["contracts"] if f["side"] in OPEN_SIDES else -f["contracts"]
    return held


def follow_up(alert: dict, fills: list[dict] | None, status: str | None) -> dict:
    """What happened to the contracts open at one alert. ``alert`` needs ``detected_at`` (naive UTC),
    ``contracts`` and ``mark`` (per contract); ``fills`` are the position's fills (naive ET), or None
    when the position could not be found."""
    out = {"response": None, "vs_alert": None, "realized_after": None, "value_at_alert": None, "closed_at": None, "note": None}
    if not fills:
        out["note"] = "The position's fills could not be found, so what happened after the alert is unknown."
        return out
    held, at = alert["contracts"], _et(alert["detected_at"])
    ordered = sorted(fills, key=lambda f: (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, str(f.get("id", ""))))
    # Fills carry the broker's minute; one in the alert's own minute may be either side of it.
    minute = at.replace(second=0, microsecond=0)
    if abs(_open_before(ordered, at, True) - held) <= EPS:
        after = [f for f in ordered if f["executed_at"] > at]
    elif abs(_open_before(ordered, minute, False) - held) <= EPS:
        after = [f for f in ordered if f["executed_at"] >= minute]
    else:
        out["note"] = "The fills no longer show the alert's contracts open at that time, so nothing is matched."
        return out
    left, proceeds, soon, last = held, 0.0, 0.0, None
    for f in after:
        if f["side"] in OPEN_SIDES or left <= EPS:
            continue
        used = min(left, f["contracts"])
        left -= used
        proceeds += used * f["price"]
        last = f["executed_at"]
        if f["executed_at"] <= at + timedelta(minutes=RESPONSE_MINUTES):
            soon += used
    expired = left > EPS and status == "expired"
    if left <= EPS:
        out["closed_at"] = last
    if left <= EPS and soon >= held - EPS:
        out["response"] = "closed_15m"
    elif soon > EPS:
        out["response"] = "trimmed_15m"
    elif expired:
        out["response"] = "expired"
    elif left <= EPS:
        out["response"] = "closed_later" if last.date() == at.date() else "held_overnight"
    else:
        out["response"] = "still_open"
    if left > EPS and not expired:
        out["note"] = "Still open, so there is no result yet."
        return out
    out["realized_after"] = round(proceeds, 2)
    if alert.get("mark") is None:
        out["note"] = "The alert had no midpoint mark, so there is no price to compare with."
        return out
    out["value_at_alert"] = round(alert["mark"] * held, 2)
    out["vs_alert"] = round(proceeds - alert["mark"] * held, 2)
    return out


# ------------------------------------------------------------------ habits

HABITS = (
    ("green_to_red", "Was up 10% and $50, then closed red"),
    ("held_hour_lost", "Held an hour or more, closed red the same day"),
    ("expired_worthless", "Expired worthless"),
    ("opened_green", "Opened while the day was already green"),
)


def habit_flags(trade: dict) -> dict:
    """Each habit for one closed trade: True, False, or None when the data it needs is missing.
    ``trade`` holds realized_pnl, opened_at, closed_at (naive ET), hold_duration_mins, expired_worthless,
    peak_pct, peak_dollars and day_pnl_before."""
    pnl = trade["realized_pnl"]
    red = pnl is not None and pnl < 0
    peak_pct, peak_dollars = trade.get("peak_pct"), trade.get("peak_dollars")
    hold = trade.get("hold_duration_mins")
    day = trade.get("day_pnl_before")
    return {
        "green_to_red": None if pnl is None or peak_pct is None or peak_dollars is None
        else red and peak_pct >= PEAK_PCT and peak_dollars >= PEAK_DOLLARS,
        "held_hour_lost": None if pnl is None or hold is None or trade.get("closed_at") is None
        else red and hold >= HOUR and trade["opened_at"].date() == trade["closed_at"].date(),
        "expired_worthless": bool(trade.get("expired_worthless")),
        "opened_green": None if day is None else day > 0,
    }


def tally(trades: list[dict]) -> dict:
    """Per habit: trades counted, excluded (data missing), how many had it, their share and their realized $."""
    out = {}
    for key, _ in HABITS:
        counted = hits = excluded = 0
        dollars = 0.0
        for trade in trades:
            flag = trade["flags"][key]
            if flag is None:
                excluded += 1
                continue
            counted += 1
            if flag:
                hits += 1
                dollars += trade["realized_pnl"] or 0.0
        out[key] = {"n": hits, "trades": counted, "excluded": excluded,
                    "pct": round(hits / counted, 4) if counted else None, "pnl": round(dollars, 2)}
    return out


def scorecard(trades: list[dict], go_live: date = GO_LIVE, window: int = WINDOW) -> dict:
    """The latest ``window`` trades closed on or after ``go_live`` against every trade closed before it."""
    for trade in trades:
        trade["flags"] = habit_flags(trade)
    dated = sorted((t for t in trades if t.get("closed_at") is not None), key=lambda t: (t["closed_at"], str(t["id"])))
    baseline = [t for t in dated if t["closed_at"].date() < go_live]
    since = [t for t in dated if t["closed_at"].date() >= go_live]
    recent = since[-window:]
    base, now = tally(baseline), tally(recent)
    return {
        "go_live": go_live.isoformat(), "window": window,
        "since_go_live": len(since), "recent_trades": len(recent), "baseline_trades": len(baseline),
        "undated": len(trades) - len(dated),
        "habits": [{"key": key, "label": label, "recent": now[key], "baseline": base[key]} for key, label in HABITS],
    }


def habit_change(recent: dict, baseline: dict) -> str | None:
    """``lower``, ``higher`` or ``same`` against the baseline rate; None when either side is too thin to compare."""
    rate = baseline["pct"]
    if recent["trades"] < MIN_HABIT_TRADES or rate is None or rate <= 0 or rate >= 1:
        return None
    gap = Z * sqrt(rate * (1 - rate) / recent["trades"])
    diff = recent["n"] / recent["trades"] - rate
    return "lower" if diff <= -gap else "higher" if diff >= gap else "same"


def verdict(card: dict) -> dict:
    """Describe changes in habit rates; the legacy verdict keys do not establish causation."""
    rule = (f"Lower habit rates: {HABITS_TO_HELP}+ of the 4 habits lower than before alerts by {Z:g} standard errors and none higher, "
            f"over the last {card['window']} trades. No consistent decrease: none lower, or any higher.")
    out = {"verdict": "not_enough_data", "rule": rule, "sample": card["recent_trades"], "changes": {}}
    if not card["baseline_trades"]:
        return {**out, "reason": "No trades before the alerts went live, so there is no baseline."}
    if card["recent_trades"] < card["window"]:
        return {**out, "reason": f"{card['recent_trades']} of {card['window']} trades closed since the alerts went live."}
    changes = {h["key"]: habit_change(h["recent"], h["baseline"]) for h in card["habits"]}
    out["changes"] = changes
    counts = Counter(changes.values())
    lower, higher = counts["lower"], counts["higher"]
    if sum(c is not None for c in changes.values()) < HABITS_TO_HELP:
        return {**out, "reason": "Too few habits have enough counted trades to compare."}
    if higher:
        return {**out, "verdict": "not_helping", "reason": f"{higher} habit(s) more frequent than before alerts."}
    if lower >= HABITS_TO_HELP:
        return {**out, "verdict": "helping", "reason": f"{lower} habits less frequent than before alerts."}
    if lower:
        return {**out, "reason": "One habit is less frequent; two are needed to call it."}
    return {**out, "verdict": "not_helping", "reason": "No habit is clearly less frequent than before alerts."}


# ------------------------------------------------------------------ database

def _epoch(moment: datetime | None) -> int | None:
    return None if moment is None else int(moment.replace(tzinfo=UTC).timestamp())


def _et_epoch(moment: datetime | None) -> int | None:
    return None if moment is None else int(wall_time(moment).replace(tzinfo=ET).timestamp())


def _num(value) -> float | None:
    return None if value is None else float(value)


def long_rows(db: Session, trades: list[Trade], fills_of: dict) -> list[dict]:
    """The closed long-option trades among ``trades`` (every entry a ``buy_to_open``) as the rows ``habit_flags`` reads.
    ``fills_of`` maps each trade id to its fills (``role``, ``side``, ``id``, ``executed_at``)."""
    closed = [t for t in trades if t.status in ("closed", "expired")]
    entries = {t.id: [f for f in fills_of.get(t.id, ()) if f["role"] == "entry"] for t in closed}
    longs = [t for t in closed if entries[t.id] and all(f["side"] == "buy_to_open" for f in entries[t.id])]
    first = {t.id: min(entries[t.id], key=lambda f: (f["executed_at"], str(f["id"])))["id"] for t in longs}
    ids = [t.id for t in longs]
    paths = {p.trade_id: p for p in db.exec(select(TradePathMetrics).where(TradePathMetrics.trade_id.in_(ids))).all()} if ids else {}
    contexts = {c.fill_id: c.realized_pnl_today_before for c in db.exec(
        select(FillMarketContext).where(FillMarketContext.fill_id.in_(list(first.values())))).all()} if first else {}
    rows = []
    for t in longs:
        path = paths.get(t.id)
        rows.append({
            "id": t.id, "realized_pnl": _num(t.realized_pnl), "hold_duration_mins": t.hold_duration_mins,
            "opened_at": wall_time(t.opened_at), "closed_at": wall_time(t.closed_at) if t.closed_at else None,
            "expired_worthless": t.expired_worthless, "pnl_pct": _num(t.pnl_pct),
            "peak_pct": _num(path.option_mfe_pct) if path else None,
            "peak_dollars": _num(path.option_peak_unrealized_pnl) if path else None,
            "day_pnl_before": _num(contexts.get(first[t.id])),
        })
    return rows


def build(db: Session, go_live: date = GO_LIVE) -> dict:
    trades = db.exec(select(Trade).where(Trade.instrument_type == "option")).all()
    by_id = {t.id: t for t in trades}
    links = db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.account_id, Fill.side, Fill.contracts, Fill.price,
                           Fill.executed_at, Fill.raw_email_id)
                    .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(list(by_id)))).all() if by_id else []
    fills_of: dict = defaultdict(list)
    trade_of_source: dict = {}
    for row in links:
        fills_of[row.trade_id].append({"id": row.id, "role": row.role, "side": row.side, "contracts": float(row.contracts),
                                       "price": float(row.price), "executed_at": wall_time(row.executed_at)})
        trade_of_source[(row.account_id, row.raw_email_id)] = row.trade_id
        trade_of_source[(row.account_id, str(row.id))] = row.trade_id

    out = scorecard(long_rows(db, trades, fills_of), go_live)

    out["verdict"] = verdict(out)
    # Every sent alert counts toward the follow-up tally; only the newest ALERTS_SHOWN are listed.
    alerts = db.exec(select(PositionAlert).where(PositionAlert.delivery.in_(("sent", "unknown")))
                     .order_by(PositionAlert.detected_at.desc())).all()
    listed = []
    for a in alerts:
        trade_id = trade_of_source.get((a.account_id, a.source_key))
        trade = by_id.get(trade_id)
        result = follow_up({"detected_at": a.detected_at, "contracts": float(a.contracts), "mark": _num(a.mark)},
                           fills_of.get(trade_id), trade.status if trade else None)
        listed.append({
            "id": str(a.id), "kind": a.kind, "contract": a.contract, "contracts": float(a.contracts),
            "detected_at": _epoch(a.detected_at), "delivery": a.delivery, "mark": _num(a.mark),
            # Unmatched: no link, since the stored trade id may predate a rebuild.
            "trade_id": str(trade_id) if trade_id else None, **{k: v for k, v in result.items() if k != "closed_at"},
            "closed_at": _et_epoch(result["closed_at"]),
        })
    out["responses"] = dict(Counter(a["response"] or "unmatched" for a in listed))
    out["alerts_total"] = len(listed)
    out["alerts"] = listed[:ALERTS_SHOWN]
    return out
