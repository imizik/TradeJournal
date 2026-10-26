"""Option candidates for the copilot's instrument question (docs/copilot-lab.md § Option candidates).

Read-only. Picks a few real contracts from the existing chain code (`options_feed`, Tradier, the same cache and
pacing as the Charts page) so the model can compare expiry, strike, premium, spread and break-even against the
owner's horizon. Every market number is the provider's quote passed through or plain arithmetic on it; delta and
implied volatility are reported as unavailable, never estimated. It ranks nothing and recommends nothing.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

from app.engine.options_implied import days_to
from app.engine.options_models import OptionChain, OptionContract
from app.engine.options_positioning import primary_root

MAX_CANDIDATES = 8
ITM, OTM = 0.05, 0.10  # strikes from about 5% in the money to 10% out
UNAVAILABLE = "unavailable"
SIDE = {"long": "call", "short": "put"}
UNITS = ("Premiums are per share as quoted (bid, ask, mid); per_contract is per share x the contract's multiplier. "
         "spread_pct is (ask - bid) / mid. to_strike_pct is the strike's distance from the price; breakeven_move_pct is "
         "the move the underlying needs by expiry to break even paying the ask. Open interest is OCC's previous-close "
         "figure; volume is today's so far.")
NOTE = ("Real contracts to compare against the horizon, not a recommendation: present the trade-offs and let the owner "
        "choose. Delta and implied volatility are unavailable here and must not be estimated.")


def pick_expirations(live: list[date], today: date, horizon_days: int) -> list[date]:
    """The expiries bracketing the horizon: the last one before it, the first at or after it, and the one after that.
    When nothing listed reaches the horizon, the last two listed."""
    target = today + timedelta(days=horizon_days)
    at = next((i for i, d in enumerate(live) if d >= target), None)
    if at is None:
        return live[-2:]
    return live[max(at - 1, 0):at + 2]


def _roles(chosen: list[date], today: date, horizon_days: int) -> dict[date, str]:
    target = today + timedelta(days=horizon_days)
    first = next((d for d in chosen if d >= target), None)
    return {d: "before" if d < target else "first_at_or_after" if d == first else "after" for d in chosen}


def _usable(c: OptionContract) -> bool:
    return c.ask is not None and c.ask > 0 and c.bid is not None and 0 <= c.bid <= c.ask


def _spread(contracts: list[OptionContract], spot: float, cap: int) -> list[OptionContract]:
    """Up to ``cap`` strikes across the window: the one nearest the price first, then each next the farthest from
    those already picked (the window's ends, then between; a tie goes to the farther from the price, then the one in
    the money), returned by strike."""
    if not contracts:
        return []
    picked = [min(contracts, key=lambda c: (abs(c.strike - spot), c.strike))]
    rest = [c for c in contracts if c is not picked[0]]

    def in_the_money(c: OptionContract) -> bool:
        return c.strike < spot if c.option_type == "call" else c.strike > spot
    while rest and len(picked) < cap:
        far = max(rest, key=lambda c: (min(abs(c.strike - p.strike) for p in picked), abs(c.strike - spot), in_the_money(c), -c.strike))
        picked.append(far)
        rest.remove(far)
    return sorted(picked, key=lambda c: c.strike)


def _row(c: OptionContract, spot: float, today: date, budget_usd: float | None) -> dict:
    mid = (c.bid + c.ask) / 2
    if c.option_type == "call":
        breakeven = c.strike + c.ask
    else:
        breakeven = c.strike - c.ask
    row = {"expiry": c.expiration.isoformat(), "days": days_to(c.expiration, today), "type": c.option_type, "strike": c.strike,
           "bid": round(c.bid, 4), "ask": round(c.ask, 4), "mid": round(mid, 4),
           "per_contract": UNAVAILABLE if not c.multiplier else
           {"bid": round(c.bid * c.multiplier, 2), "ask": round(c.ask * c.multiplier, 2), "mid": round(mid * c.multiplier, 2)},
           "spread_pct": round((c.ask - c.bid) / mid * 100, 1)}
    if c.open_interest is not None:
        row["open_interest"] = c.open_interest
    if c.volume is not None:
        row["volume"] = c.volume
    row.update(delta=UNAVAILABLE, iv=UNAVAILABLE, to_strike_pct=round((c.strike - spot) / spot * 100, 2),
               breakeven_move_pct=round((breakeven - spot) / spot * 100, 2))
    if budget_usd is not None:
        if c.multiplier:
            count = math.floor(budget_usd / (c.ask * c.multiplier) + 1e-9)
            row["budget_buys"] = {"contracts": count, "cost_usd": round(count * c.ask * c.multiplier, 2)}
        else:
            row["budget_buys"] = UNAVAILABLE
    return row


def _bounded(out: dict, most: int) -> dict:
    """Fewer rows, never a cut string: the tool's answer must stay valid JSON within the result limit."""
    while out["candidates"] and len(json.dumps(out, default=str, separators=(",", ":"))) > most:
        out["candidates"].pop()
        out["trimmed"] = out.get("trimmed", 0) + 1
    return out


def candidates(symbol: str, chosen: list[date], chains: dict[date, OptionChain], spot: float, today: date,
               horizon_days: int, direction: str, budget_usd: float | None = None, as_of: str | None = None,
               issue: str | None = None) -> dict:
    """At most ``MAX_CANDIDATES`` contracts across ``chosen`` expiries (the first at or after the horizon gets the most),
    calls for a long view and puts for a short one, strikes from about 5% in the money to 10% out."""
    from app.ai.copilot_tools import MAX_RESULT_CHARS
    side = SIDE[direction]
    root = primary_root(symbol)
    low, high = (spot * (1 - ITM), spot * (1 + OTM)) if side == "call" else (spot * (1 - OTM), spot * (1 + ITM))
    roles = _roles(chosen, today, horizon_days)
    order = sorted(chosen, key=lambda d: ("first_at_or_after", "after", "before").index(roles[d]))
    present = [d for d in order if d in chains]
    caps = {d: MAX_CANDIDATES // len(present) + (i < MAX_CANDIDATES % len(present)) for i, d in enumerate(present)} if present else {}
    rows, no_quote = [], 0
    for d in present:
        window = [c for c in chains[d].contracts if c.root == root and c.option_type == side and low <= c.strike <= high]
        usable = [c for c in window if _usable(c)]
        no_quote += len(window) - len(usable)
        rows += [_row(c, spot, today, budget_usd) for c in _spread(usable, spot, caps[d])]
    rows.sort(key=lambda r: (r["expiry"], r["strike"]))
    missing = [d for d in chosen if d not in chains]
    state = "ok" if rows and not missing else "partial" if rows else "unavailable" if missing else "none"
    out = {"symbol": symbol, "state": state, "as_of": as_of, "direction": direction, "side": f"{side}s",
           "horizon_days": horizon_days, "horizon_date": (today + timedelta(days=horizon_days)).isoformat(),
           "spot": round(spot, 4), "budget_usd": budget_usd,
           "expiries": [{"expiry": d.isoformat(), "days": days_to(d, today), "role": roles[d], "weekday": d.strftime("%a"),
                         **({"missing": True} if d in missing else {})} for d in sorted(chosen)],
           "reaches_horizon": any(role != "before" for role in roles.values()),
           "candidates": rows, "units": UNITS, "note": NOTE}
    if not out["reaches_horizon"]:
        out["horizon_note"] = "No listed expiration reaches the horizon; these are the longest listed."
    if no_quote:
        out["skipped_without_quote"] = no_quote
    if missing:
        out["reason"] = issue or "Some expirations' chains could not be read."
    elif not rows:
        out["reason"] = f"No {side} in the strike window has a usable bid and ask."
    return _bounded(out, MAX_RESULT_CHARS)


def _iso(stamp: float | datetime) -> str:
    moment = stamp if isinstance(stamp, datetime) else datetime.fromtimestamp(stamp, timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def live_candidates(symbol: str, horizon_days: int, direction: str, budget_usd: float | None = None) -> dict:
    """The live read: the price from the quote service, the chosen expiries' chains from the options feed's cache."""
    from app.engine.chart_math import ET
    from app.engine.options_feed import options_feed
    from app.engine.quotes import get_stock_quotes
    base = {"symbol": symbol, "direction": direction, "horizon_days": horizon_days, "candidates": []}
    spot = get_stock_quotes([symbol]).get(symbol)
    if not isinstance(spot, (int, float)) or not spot > 0:
        return {**base, "state": "unavailable", "reason": f"No current {symbol} price, so strikes cannot be placed."}
    today = datetime.now(ET).date()
    chosen: list[date] = []

    def pick(live: list[date]) -> list[date]:
        chosen[:] = pick_expirations(live, today, horizon_days)
        return chosen
    try:
        reads, issue = options_feed.chains(symbol, pick)
    except ValueError:  # the chain adapter's own symbol check
        return {**base, "state": "unavailable", "reason": f"{symbol} is not an optionable underlying symbol."}
    if not chosen:
        if issue:
            return {**base, "state": "unavailable", "reason": issue}
        return {**base, "state": "none", "reason": f"No listed {symbol} options."}
    chains = {read.value.expiration: read.value for read in reads}
    as_of = _iso(min(read.fetched for read in reads)) if reads else None
    return candidates(symbol, chosen, chains, float(spot), today, horizon_days, direction, budget_usd, as_of, issue)
