"""The alert scorecard (docs/copilot-lab.md § The desk): for each position alert sent to the phone, what the owner
decided after it and what happened next, measured against selling at the alert.

An alert is a prompt to decide, not an exit rule (the 2026-10-24 exit study rejected each alert as a mechanical exit),
so its value can only show in the owner's decisions after it. Read-only; nothing here changes an alert or a threshold.

- Alerts: ``PositionAlert`` rows sent to the phone (or possibly sent) in the last ``WINDOW_DAYS``, newest first.
- Decision: the first ``decision`` day-journal entry for the alert's symbol logged after it, on the same New York day
  (the decision bar asks only that day) and before the same position's next alert ("holding" or "exiting", from the
  entry's first word); none means no decision was logged. The journal keeps the symbol, not the position, so two
  positions in one symbol alerting the same day would share a decision.
- Outcome, for the contracts the alert saw open (``PositionAlert.contracts``): selling them at the alert would have
  fetched the alert's bid times those contracts (its mark when no bid was quoted; ``basis`` says which). What they
  actually fetched is the closing fills from the alert's minute on (fill times carry minutes only), taken in order as
  FIFO closes the oldest lots first, up to the contracts the alert saw, plus
  nothing for contracts that expired. ``vs_alert_usd`` is actual minus selling at the alert: positive means holding
  past the alert paid. A position with contracts still open is ``open``; a short position, an alert with no price, or
  a trade that cannot be found is ``not_measured``.

Units follow the journal: an option fill's ``price`` and the alert's ``bid``/``mark``/``avg_cost`` are dollars per
contract. Alert and journal times are naive UTC; fill and trade times are naive New York wall clock (domain rules).
"""
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.engine.chart_math import ET
from app.engine.position_alerts import anchor
from app.models import DayJournalEntry, Fill, PositionAlert, Trade, TradeFill

WINDOW_DAYS = 30
MAX_ROWS = 60
SENT = ("sent", "unknown")
KIND = {"giveback": "Give-back", "hold_hour": "Held an hour", "expiry_first": "Expires today", "expiry_final": "30 minutes left",
        "expiry_eve": "Expires next session", "wrong_way": "Wrong way at 30 min", "same_day_1pm": "Same-day option at 1 PM"}
NOT_SCORED = ("no_exit",)  # a prompt to set an exit at the entry, not to sell: selling at it is not its alternative
EPSILON = 1e-9


def _ny(moment: datetime) -> datetime:
    """A naive UTC time as the naive New York wall clock fills and trades use."""
    return moment.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)


def _epoch_utc(moment: datetime) -> int:
    return int(moment.replace(tzinfo=UTC).timestamp())


def _epoch_ny(moment: datetime) -> int:
    return int(moment.replace(tzinfo=ET).timestamp())


def _fills(db: Session, trade_id, role: str) -> list[Fill]:
    return list(db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                        .where(TradeFill.trade_id == trade_id, TradeFill.role == role)).all())


def _trade(db: Session, alert: PositionAlert, found: dict) -> Trade | None:
    """The alert's position as a trade now. Trades are rebuilt with new ids, so the alert's own id is checked against the
    position's identity (its first entry fill) and, failing that, the account's trades in the symbol are searched."""
    key = (alert.account_id, alert.source_key)
    if key not in found:
        found[key] = position_trade(db, alert.account_id, (alert.contract or "").split(" ")[0], alert.source_key, alert.trade_id)
    return found[key]


def position_trade(db: Session, account_id, symbol: str, source_key: str, trade_id) -> Trade | None:
    """The trade now holding the position whose first entry fill anchors as ``source_key`` (``trade_id`` first: it was
    that trade when the ping fired), or None when no trade of the account's options in ``symbol`` is that position."""
    trade = db.get(Trade, trade_id)
    entries = _fills(db, trade.id, "entry") if trade is not None else []
    if entries and anchor(entries) == source_key:
        return trade
    for candidate in db.exec(select(Trade).where(Trade.account_id == account_id, Trade.ticker == symbol,
                                                 Trade.instrument_type == "option")).all():
        entries = _fills(db, candidate.id, "entry")
        if entries and anchor(entries) == source_key:
            return candidate
    return None


def _choice(entry: DayJournalEntry) -> str | None:
    word = entry.text.strip().split(" ", 1)[0].strip(".,").lower()
    return word if word in ("holding", "exiting") else None


def _outcome(db: Session, alert: PositionAlert, trade: Trade | None) -> dict:
    price, basis = (alert.bid, "bid") if alert.bid is not None else (alert.mark, "mark")
    if trade is None or price is None or not alert.contracts:
        return {"state": "not_measured", "why": "trade not found" if trade is None else "no price at the alert"}
    entries = _fills(db, trade.id, "entry")
    if any(f.side == "sell_to_open" for f in entries):
        return {"state": "not_measured", "why": "a short position"}
    held = float(alert.contracts)
    at_alert = round(float(price) * held, 2)
    after = _ny(alert.detected_at).replace(second=0, microsecond=0)  # fills are recorded to the minute
    exits = sorted((f for f in _fills(db, trade.id, "exit") if f.executed_at >= after),
                   key=lambda f: (f.executed_at, f.raw_email_id or "", str(f.id)))
    if any((f.raw_email_id or "").startswith("roll:") for f in exits):
        return {"state": "not_measured", "why": "rolled: the derived close is not a sale price"}
    taken = proceeds = 0.0
    ended = None
    for fill in exits:
        quantity = min(float(fill.contracts), held - taken)
        if quantity <= EPSILON:
            break
        proceeds += float(fill.price) * quantity
        taken += quantity
        ended = fill.executed_at
    left = held - taken
    how = "sold"
    if left > EPSILON:
        if trade.status == "closed":  # closed with fewer sells after the alert than it saw open: the books disagree
            return {"state": "not_measured", "why": "the closing sells do not match the alert"}
        if trade.status != "expired":
            return {"state": "open", "sell_at_alert_usd": at_alert, "basis": basis, "sold_so_far_usd": round(proceeds, 2),
                    "contracts_left": round(left, 6)}
        how, ended = "expired" if taken <= EPSILON else "sold_then_expired", trade.closed_at  # worthless: nothing more
    actual = round(proceeds, 2)
    return {"state": "closed", "how": how, "sell_at_alert_usd": at_alert, "basis": basis, "actual_usd": actual,
            "vs_alert_usd": round(actual - at_alert, 2), "ended_at": _epoch_ny(ended) if ended else None}


def _rows(db: Session, now: float, days: int) -> list[dict]:
    """Every scored alert of the window, oldest first (``scorecard``'s rows before they are cut)."""
    since = datetime.fromtimestamp(now, UTC).replace(tzinfo=None) - timedelta(days=days)
    alerts = list(db.exec(select(PositionAlert).where(PositionAlert.detected_at >= since, PositionAlert.delivery.in_(SENT),
                                                      PositionAlert.kind.not_in(NOT_SCORED))
                          .order_by(PositionAlert.detected_at)).all())
    later: dict[int, datetime] = {}
    for i, alert in enumerate(alerts):
        nxt = next((other.detected_at for other in alerts[i + 1:]
                    if other.account_id == alert.account_id and other.source_key == alert.source_key), None)
        if nxt is not None:
            later[i] = nxt
    symbols = {(a.contract or "").split(" ")[0] for a in alerts}
    decisions = list(db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "decision", DayJournalEntry.symbol.in_(symbols),
                                                           DayJournalEntry.created_at >= since)
                             .order_by(DayJournalEntry.created_at)).all()) if symbols else []
    found: dict = {}
    rows = []
    for i, alert in enumerate(alerts):
        symbol = (alert.contract or "").split(" ")[0]
        until = later.get(i)
        day = _ny(alert.detected_at).date()
        decided = next((d for d in decisions if d.symbol == symbol and d.created_at >= alert.detected_at
                        and _ny(d.created_at).date() == day and (until is None or d.created_at < until) and _choice(d)), None)
        rows.append({
            "at": _epoch_utc(alert.detected_at), "kind": alert.kind, "kind_label": KIND.get(alert.kind, "Position alert"),
            "contract": alert.contract, "symbol": symbol,
            "pnl_pct_at_alert": round(alert.gain_pct * 100, 1) if alert.gain_pct is not None else None,
            "decision": _choice(decided) if decided else None,
            "decided_at": _epoch_utc(decided.created_at) if decided else None,
            "outcome": _outcome(db, alert, _trade(db, alert, found)),
        })
    return rows


def scorecard(db: Session, now: float, days: int = WINDOW_DAYS) -> dict:
    rows = _rows(db, now, days)
    summary = {}
    for choice in ("holding", "exiting", None):
        mine = [r for r in rows if r["decision"] == choice]
        closed = [r["outcome"]["vs_alert_usd"] for r in mine if r["outcome"]["state"] == "closed"]
        summary["none" if choice is None else choice] = {
            "alerts": len(mine), "closed": len(closed), "better": sum(1 for v in closed if v > 0),
            "worse": sum(1 for v in closed if v < 0), "even": sum(1 for v in closed if v == 0),
            "open": sum(1 for r in mine if r["outcome"]["state"] == "open"),
            "not_measured": sum(1 for r in mine if r["outcome"]["state"] == "not_measured"),
            "vs_alert_usd": round(sum(closed), 2),
        }
    rows.reverse()
    return {"window_days": days, "alerts": len(rows), "summary": summary, "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


def habit(db: Session, now: float, kind: str, days: int = WINDOW_DAYS) -> dict:
    """What not acting on ``kind`` alerts did over the window, for the ping card's line: the alerts of that kind with no
    Exiting logged after them (held, or no decision), and for the closed ones what they fetched against selling at the
    alert (``vs_alert_usd``: negative means selling at the ping would have made that much more)."""
    held = [r for r in _rows(db, now, days) if r["kind"] == kind and r["decision"] != "exiting"]
    closed = [r["outcome"]["vs_alert_usd"] for r in held if r["outcome"]["state"] == "closed"]
    return {"kind": kind, "kind_label": KIND.get(kind, "Position alert"), "window_days": days, "held": len(held),
            "closed": len(closed), "better": sum(1 for v in closed if v > 0), "worse": sum(1 for v in closed if v < 0),
            "vs_alert_usd": round(sum(closed), 2)}


def week_cost(db: Session, start_utc: datetime, end_utc: datetime) -> dict:
    """What holding past the pings did, for the Sunday digest: the positions that got a sent position alert in the window
    (naive UTC), each measured once from its first alert there (several alerts on one position would count the same
    contracts again), as ``_outcome`` measures it. ``vs_alert_usd`` sums the closed ones: negative means selling at the
    first ping would have fetched that much more than what he did. Positions still open are counted apart."""
    alerts = db.exec(select(PositionAlert).where(PositionAlert.detected_at >= start_utc, PositionAlert.detected_at < end_utc,
                                                 PositionAlert.delivery.in_(SENT), PositionAlert.kind.not_in(NOT_SCORED))
                     .order_by(PositionAlert.detected_at)).all()
    first: dict = {}
    for alert in alerts:
        first.setdefault((alert.account_id, alert.source_key), alert)
    found: dict = {}
    closed = []
    still_open = 0
    for alert in first.values():
        outcome = _outcome(db, alert, _trade(db, alert, found))
        if outcome["state"] == "closed":
            closed.append(outcome["vs_alert_usd"])
        elif outcome["state"] == "open":
            still_open += 1
    return {"positions": len(first), "closed": len(closed), "open": still_open,
            "better": sum(1 for v in closed if v > 0), "worse": sum(1 for v in closed if v < 0),
            "vs_alert_usd": round(sum(closed), 2)}


def cost_line(cost: dict) -> str | None:
    """The digest's one line for ``week_cost``; None when no pinged position has closed."""
    if not cost["closed"]:
        return None
    n = cost["closed"]
    total = cost["vs_alert_usd"]
    head = f"Pings: {n} pinged position{'' if n == 1 else 's'} closed. "
    if total < 0:
        head += f"Selling at the first ping would have made ${-total:,.0f} more"
    elif total > 0:
        head += f"Holding past the pings made ${total:,.0f} more than selling at the first one"
    else:
        head += "Selling at the first ping would have come out the same"
    head += f" (selling then was better on {cost['worse']}, worse on {cost['better']})."
    if cost["open"]:
        head += f" {cost['open']} still open."
    return head


ACT_MINUTES = 15  # a sell of the pinged contract this soon after the ping counts as acting on it


def week_by_kind(db: Session, start_utc: datetime, end_utc: datetime) -> list[dict]:
    """The weekly ping scorecard: per ping type, the positions it pinged in the window (naive UTC), how many he acted on
    and what ignoring the rest did. Each position is counted once per type, from that type's first ping in the window.

    Acted: a closing fill of the position within ``ACT_MINUTES`` of the ping (fills carry minutes only), or an Exiting
    decision logged after it that New York day. Ignored: neither. For the ignored ones that have closed,
    ``ignored_vs_alert_usd`` is what they fetched against selling at the ping (``_outcome``): negative means ignoring
    the ping cost that much. The no-exit-order ping asks for an exit order, not a sale, so it is left out (``NOT_SCORED``).
    Types with no ping in the window are left out; the rest come in ``KIND`` order."""
    alerts = db.exec(select(PositionAlert).where(PositionAlert.detected_at >= start_utc, PositionAlert.detected_at < end_utc,
                                                 PositionAlert.delivery.in_(SENT), PositionAlert.kind.not_in(NOT_SCORED))
                     .order_by(PositionAlert.detected_at)).all()
    first: dict = {}
    for alert in alerts:
        first.setdefault((alert.kind, alert.account_id, alert.source_key), alert)
    symbols = {(a.contract or "").split(" ")[0] for a in first.values()}
    exiting = [d for d in db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "decision", DayJournalEntry.symbol.in_(symbols),
                                                                 DayJournalEntry.created_at >= start_utc)).all()
               if _choice(d) == "exiting"] if symbols else []
    found: dict = {}
    tally: dict[str, dict] = {}
    for (kind, _, _), alert in first.items():
        row = tally.setdefault(kind, {"kind": kind, "kind_label": KIND.get(kind, "Position alert"), "pings": 0, "acted": 0, "ignored": 0,
                                      "ignored_closed": 0, "ignored_open": 0, "ignored_better": 0, "ignored_worse": 0,
                                      "ignored_vs_alert_usd": 0.0})
        row["pings"] += 1
        trade = _trade(db, alert, found)
        symbol = (alert.contract or "").split(" ")[0]
        day = _ny(alert.detected_at).date()
        decided = any(d.symbol == symbol and d.created_at >= alert.detected_at and _ny(d.created_at).date() == day for d in exiting)
        sold = False
        if trade is not None:
            after = _ny(alert.detected_at).replace(second=0, microsecond=0)
            sold = any(after <= f.executed_at <= after + timedelta(minutes=ACT_MINUTES) for f in _fills(db, trade.id, "exit"))
        if decided or sold:
            row["acted"] += 1
            continue
        row["ignored"] += 1
        outcome = _outcome(db, alert, trade)
        if outcome["state"] == "closed":
            row["ignored_closed"] += 1
            row["ignored_vs_alert_usd"] += outcome["vs_alert_usd"]
            row["ignored_better"] += outcome["vs_alert_usd"] > 0
            row["ignored_worse"] += outcome["vs_alert_usd"] < 0
        elif outcome["state"] == "open":
            row["ignored_open"] += 1
    order = list(KIND)
    out = sorted(tally.values(), key=lambda r: order.index(r["kind"]) if r["kind"] in order else len(order))
    for row in out:
        row["ignored_vs_alert_usd"] = round(row["ignored_vs_alert_usd"], 2)
    return out


def kind_lines(rows: list[dict]) -> list[str]:
    """The Sunday digest's lines for ``week_by_kind``, one per ping type:
    "Give-back: acted on 1 of 3. Ignoring 2 cost $180 (1 still open)." """
    lines = []
    for r in rows:
        line = f"{r['kind_label']}: acted on {r['acted']} of {r['pings']}."
        if r["ignored_closed"]:
            n, total = r["ignored_closed"], r["ignored_vs_alert_usd"]
            what = f"cost ${-total:,.0f}" if total < 0 else f"paid ${total:,.0f}" if total > 0 else "came out even"
            line += f" Ignoring {n} {what}"
            line += f" ({r['ignored_open']} still open)." if r["ignored_open"] else "."
        elif r["ignored_open"]:
            line += f" {r['ignored_open']} ignored, still open."
        lines.append(line)
    return lines
