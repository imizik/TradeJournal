"""Should I add? One open long option against the owner's own record of adding below cost.

The November 24, 2026 edge audit found the money leaking in short-dated options held while down and added to below
cost. This reads the position now (days to expiry, percent down, time held) and the closed positions where he
bought more below cost in the same kind of spot, with what those positions and the added contracts themselves made
or lost. Pure: the publisher builds the record rows from the narrow fill view, the check service reads them.
Advice only; nothing here places, sizes or changes an order.
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from statistics import median
from typing import Iterable, Optional

ADD_VERSION = "pretrade-add-v1"
SHORT_DATED_DAYS = 3  # calendar days to expiry: the audit's short-dated group (fill_interrupts.BUILT_DAYS)
DEEP_PCT = 20.0  # percent below cost: the audit's "down 20% or more"
LONG_HOLD_MINUTES = 60
MIN_POSITIONS = 8  # below this a group is "not enough history" (pretrade_check.MIN_TRADES)
RECENT = 5
EPS = 1e-9
ADD_ROW_KEYS = frozenset({"closed_at", "underlying", "side", "realized_pnl", "adds"})
ADD_KEYS = frozenset({"dte", "below_cost_pct", "minutes_held", "premium", "pnl"})


def _when(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _day(value):
    return _when(value).date() if isinstance(value, (str, datetime)) else value


def add_history_rows(records: Iterable[dict]) -> list[dict]:
    """One row per closed long option position with at least one buy below cost, from the per-fill view rows.

    Fills replay first in, first out in the view's ``seq`` (the reconstructor's order). An entry is an add below
    cost when the position is still open and its price is under the open lots' average cost, the same test as
    ``fill_interrupts.adds_to_loser``. Each add carries the P&L of its own contracts: what their sales brought
    against what they cost, or minus their cost when the position expired with them still open.
    """
    by_trade: dict = defaultdict(list)
    for item in records:
        by_trade[item["trade_key"]].append(dict(item))
    rows = []
    for fills in by_trade.values():
        fills.sort(key=lambda f: f["seq"])
        trade = fills[0]
        if trade["realized_pnl"] is None or any(f["side"] != "buy_to_open" for f in fills if f["role"] == "entry"):
            continue  # a short or mixed position reads inverted; the record is bought options only
        opened = _when(fills[0]["executed_at"])
        expiration = _day(trade["expiration"]) if trade["expiration"] else None
        lots: deque[list] = deque()  # [contracts still open, price, the add it belongs to or None]
        adds = []
        for fill in fills:
            qty, price, at = float(fill["contracts"]), float(fill["price"]), _when(fill["executed_at"])
            if fill["role"] == "entry":
                held = sum(lot[0] for lot in lots)
                cost = sum(lot[0] * lot[1] for lot in lots) / held if held > EPS else None
                add = None
                if cost is not None and price < cost - EPS and expiration is not None:
                    add = {"dte": (expiration - at.date()).days, "below_cost_pct": round((cost - price) / cost * 100, 2),
                           "minutes_held": max(0, round((at - opened).total_seconds() / 60)),
                           "premium": round(qty * price, 2), "pnl": 0.0}
                    adds.append(add)
                lots.append([qty, price, add])
                continue
            while qty > EPS and lots:
                lot = lots[0]
                used = min(lot[0], qty)
                if lot[2] is not None:
                    lot[2]["pnl"] += (price - lot[1]) * used
                lot[0] -= used
                qty -= used
                if lot[0] <= EPS:
                    lots.popleft()
        for lot in lots:  # still open at the end: expired worthless, so those contracts lost what they cost
            if lot[2] is not None:
                lot[2]["pnl"] = lot[2]["pnl"] - lot[0] * lot[1] if trade["status"] == "expired" else None
        if not adds or any(add["pnl"] is None for add in adds):
            continue  # closed with contracts unmatched: the fills do not explain the P&L, so it is not counted
        side = trade["option_type"] if trade["option_type"] in ("call", "put") else None
        rows.append({"closed_at": _when(trade["closed_at"]).isoformat(), "underlying": trade["ticker"].upper(),
                     "side": side, "realized_pnl": round(float(trade["realized_pnl"]), 2),
                     "adds": [{**add, "pnl": round(add["pnl"], 2)} for add in adds]})
    return sorted(rows, key=lambda row: (row["closed_at"], row["underlying"], row["realized_pnl"]))


def _cohort(name: str, rows: list[dict], match) -> dict:
    """The positions with at least one add below cost that ``match`` accepts, and those adds' own dollars."""
    hits = [(row, [add for add in row["adds"] if match(add)]) for row in rows]
    hits = [(row, adds) for row, adds in hits if adds]
    out = {"name": name, "positions": len(hits), "enough": len(hits) >= MIN_POSITIONS}
    if not hits:
        return out
    position_pnl = [row["realized_pnl"] for row, _ in hits]
    added = [add for _, adds in hits for add in adds]
    return {**out, "ended_green": sum(1 for value in position_pnl if value > 0),
            "position_pnl": round(sum(position_pnl), 2), "median_position_pnl": round(median(position_pnl), 2),
            "worst_position_pnl": round(min(position_pnl), 2), "adds": len(added),
            "added_premium": round(sum(add["premium"] for add in added), 2),
            "added_contracts_pnl": round(sum(add["pnl"] for add in added), 2),
            "adds_that_made_money": sum(1 for add in added if add["pnl"] > 0)}


def add_view(view: dict, rows: Optional[Iterable[dict]], receipt_ny: datetime) -> dict:
    """The answer for one open position: ``view`` is ``pretrade_check.position_view``'s result, ``rows`` the
    published add record (None when it is not published). ``answer`` is ``no`` when the contracts he added below cost in
    this kind of spot lost money over enough positions, ``no_clear_record`` when they did not or are too few,
    ``not_below_cost`` when the position is not under its average entry, ``not_covered`` for anything but a
    bought option, and ``insufficient_data`` without a live quote or a record."""
    position = view["position"]
    base = {"add_version": ADD_VERSION, "ticker": position["ticker"].upper(), "position": position,
            "now": None, "leak_pattern": None, "record": None, "reasons": []}
    if position["instrument_type"] != "option" or position.get("option_type") not in ("call", "put"):
        return {**base, "answer": "not_covered",
                "headline": "The add record covers bought calls and puts only; nothing is computed for shares."}
    mid, entry, dte = (view.get("option") or {}).get("mid"), position.get("avg_entry_premium"), view["days_to_expiration"]
    if not mid or not entry or dte is None:
        return {**base, "answer": "insufficient_data",
                "headline": "No live quote for this contract, so how far below cost it is cannot be read."}
    down = round((mid * 100 - entry) / entry * 100, 2)  # option fills store dollars per contract
    held = view["held_minutes"]
    now = {"days_to_expiration": dte, "pct_vs_cost": down, "held_minutes": held, "avg_entry_per_contract": entry,
           "mid_per_contract": round(mid * 100, 2), "contracts": position.get("contracts"),
           "paid": position.get("total_premium_paid"), "unrealized_pnl": (view.get("mark") or {}).get("unrealized_pnl"),
           "basis": "live mid against the average entry of every buy; a fill could differ by the spread"}
    short_dated, deep, long_hold = dte <= SHORT_DATED_DAYS, down <= -DEEP_PCT, held >= LONG_HOLD_MINUTES
    pattern = {"short_dated": short_dated, "down_20_or_more": deep, "held_over_an_hour": long_hold,
               "all_three": short_dated and deep and long_hold,
               "note": f"the November 24, 2026 audit's leak: {SHORT_DATED_DAYS} or fewer days to expiry, down "
                       f"{DEEP_PCT:.0f}% or more after an hour, then adding below cost"}
    base = {**base, "now": now, "leak_pattern": pattern}
    if down >= 0:
        return {**base, "answer": "not_below_cost",
                "headline": f"This position is {down:+.1f}% against cost, so an add here is not an add below cost; "
                            "that record does not apply and no other is computed."}
    if rows is None:
        return {**base, "answer": "insufficient_data",
                "headline": "The record of past adds below cost is not published yet; nothing was invented."}
    prior = [row for row in rows if datetime.fromisoformat(row["closed_at"]) < receipt_ny]
    dated = "short_dated" if short_dated else "longer_dated"
    depth = "down_20_or_more" if deep else "down_under_20"

    def same_dte(add):
        return (0 <= add["dte"] <= SHORT_DATED_DAYS) if short_dated else add["dte"] > SHORT_DATED_DAYS

    def same_depth(add):
        return same_dte(add) and ((add["below_cost_pct"] >= DEEP_PCT) == deep)

    ticker = [row for row in prior if row["underlying"] == base["ticker"]]
    cohorts = [_cohort(f"{dated}_{depth}", prior, same_depth), _cohort(dated, prior, same_dte),
               _cohort(f"{dated}_same_ticker", ticker, same_dte)]
    decided = next((c for c in cohorts[:2] if c["enough"]), None)  # the ticker group is colour, never the decider
    recent = [{"closed": row["closed_at"][:10], "underlying": row["underlying"], "side": row["side"],
               "position_pnl": row["realized_pnl"], "adds": [add for add in row["adds"] if same_dte(add)]}
              for row in reversed(prior) if any(same_dte(add) for add in row["adds"])][:RECENT]
    record = {"cohorts": cohorts, "decided_by": decided and decided["name"], "recent": recent,
              "basis": "closed bought-option positions with a buy below the open contracts' average cost; "
                       "added_contracts_pnl is first in, first out on the added contracts alone"}
    spot = (f"{dte} days to expiry" if dte != 1 else "1 day to expiry") + f", {abs(down):.0f}% below cost, held {held} min"
    reasons = [f"Now: {spot}."]
    if pattern["all_three"]:
        reasons.append("This is the audit's leak spot: short-dated, down 20% or more, held over an hour.")
    if decided is None:
        return {**base, "record": record, "reasons": reasons, "answer": "no_clear_record",
                "headline": f"Too few past adds below cost in this kind of spot to read (fewer than {MIN_POSITIONS} "
                            "positions); your record neither backs nor argues against this add."}
    summary = (f"{decided['positions']} positions where you added below cost in this kind of spot: "
               f"{decided['ended_green']} ended green, ${decided['position_pnl']:+,.0f} in total, and the added "
               f"contracts themselves made ${decided['added_contracts_pnl']:+,.0f} on ${decided['added_premium']:,.0f} added.")
    reasons.append(summary)
    lost = decided["added_contracts_pnl"] < 0
    if lost:
        headline = (f"No. Adding below cost here has cost you money: the added contracts lost "
                    f"${-decided['added_contracts_pnl']:,.0f} across {decided['positions']} positions "
                    f"({decided['ended_green']} ended green).")
    else:
        headline = (f"Your record does not say no: across {decided['positions']} positions the added contracts made "
                    f"${decided['added_contracts_pnl']:+,.0f} and the positions ${decided['position_pnl']:+,.0f}. "
                    "That is history, not a go.")
    return {**base, "record": record, "reasons": reasons, "answer": "no" if lost else "no_clear_record",
            "headline": headline}
