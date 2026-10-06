"""What the options market prices as a move (symbol info T2.1).

Pure: the caller hands in normalized chains, the underlying's price and the
next earnings date; nothing here fetches.

The implied move is the at-the-money straddle's mid: the call's and the put's
mid prices at the listed strike nearest the price, added. It is *calculated*,
from quotes with their times, and it prices a move either way by expiry, not a
direction. A strike missing either leg is not at the money for this purpose,
since a straddle needs both; a one-sided leg (no bid, or no ask) or a leg
whose spread is wider than its own mid leaves the expiration without a number
rather than with a guess.

The range bands (Charts C2.7) draw a captured straddle as two levels, the price
at capture plus and minus the move: what the options market charged then for a
move either way by that expiration, not a forecast of where price will stay.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Mapping

from app.engine.chart_levels import Level
from app.engine.options_models import OptionChain, OptionContract
from app.engine.options_positioning import primary_root, unexpired

# A leg whose bid-ask spread exceeds this share of its mid is too wide to read a price from.
MAX_SPREAD = 1.0
MAX_QUOTE_AGE = 60  # seconds, required only when capturing a new session reference
FRIDAY = 4


def targets(listed: Iterable[date], root: str, now: datetime, earnings: date | None,
            closes: Mapping[date, int | None] | None = None) -> dict[str, date | None]:
    """The expirations the Forecast tab reads: the nearest, the nearest Friday, and the
    first one after the next earnings date (strictly after it: the report's time of day
    is unknown, so an expiration on the report date may close before it)."""
    live = unexpired(listed, root, now, closes)
    return {
        "nearest": live[0] if live else None,
        "friday": next((d for d in live if d.weekday() == FRIDAY), None),
        "earnings": next((d for d in live if d > earnings), None) if earnings else None,
    }


def straddle(chain: OptionChain, spot: float, root: str | None = None, now: datetime | None = None) -> dict:
    """The at-the-money straddle of one expiration, or why there is none.

    ``state`` is ``ready`` (with ``move`` in dollars per share and ``percent`` of
    the price), ``too_wide`` (with ``reason``) or ``none`` (nothing listed).
    """
    root = root or primary_root(chain.underlying)
    legs: dict[float, dict[str, OptionContract]] = {}
    for contract in chain.contracts:
        if contract.root == root:
            legs.setdefault(contract.strike, {})[contract.option_type] = contract
    paired = [strike for strike, pair in legs.items() if "call" in pair and "put" in pair]
    if not paired or spot <= 0:
        return {"state": "none", "expiration": chain.expiration.isoformat(), "reason": "No strike lists both a call and a put."}
    strike = min(paired, key=lambda value: (abs(value - spot), value))  # a tie takes the lower strike
    call, put = legs[strike]["call"], legs[strike]["put"]
    base = {"expiration": chain.expiration.isoformat(), "strike": strike,
            "call": _leg(call), "put": _leg(put), "quoted_at": _quoted_at(call, put)}
    for name, leg in (("call", call), ("put", put)):
        if not leg.bid or not leg.ask:
            return {**base, "state": "too_wide", "reason": f"The {strike:g} {name} has no {'bid' if not leg.bid else 'ask'}."}
        if leg.ask < leg.bid:
            return {**base, "state": "too_wide", "reason": f"The {strike:g} {name}'s quote is crossed."}
        if leg.ask - leg.bid > MAX_SPREAD * (leg.bid + leg.ask) / 2:
            return {**base, "state": "too_wide", "reason": f"The {strike:g} {name} is {leg.bid:.2f} bid, {leg.ask:.2f} ask: wider than its own price."}
    if now is not None:
        times = [stamp for leg in (call, put) for stamp in (leg.bid_time, leg.ask_time)]
        if any(stamp is None for stamp in times):
            return {**base, "state": "stale", "reason": "Option quote timestamps are unavailable; a fresh session band cannot be priced."}
        if any(not 0 <= (now - stamp).total_seconds() <= MAX_QUOTE_AGE for stamp in times):
            return {**base, "state": "stale", "reason": "Option bid/ask quotes must all be within the last minute to price a session band."}
    move = (call.bid + call.ask) / 2 + (put.bid + put.ask) / 2
    ivs = [leg.iv for leg in (call, put) if leg.iv is not None]
    return {**base, "state": "ready", "move": round(move, 4), "percent": move / spot,
            "iv": sum(ivs) / len(ivs) if ivs else None}


def _leg(contract: OptionContract) -> dict:
    return {"symbol": contract.symbol, "bid": contract.bid, "ask": contract.ask, "iv": contract.iv}


def _quoted_at(*contracts: OptionContract) -> int | None:
    """The oldest quote time among the legs, UTC seconds: the straddle is as fresh as its stalest side."""
    times = [stamp for c in contracts for stamp in (c.bid_time, c.ask_time) if stamp is not None]
    return int(min(times).timestamp()) if times else None


def days_to(expiration: date, today: date) -> int:
    return (expiration - today) // timedelta(days=1)


def band_name(band: dict) -> str:
    """"0DTE" for today's expiration, else its weekday ("Fri")."""
    return "0DTE" if band["today"] else date.fromisoformat(band["expiration"]).strftime("%a")


def expected_move_levels(bands: Iterable[dict]) -> list[Level]:
    """Each captured band as its upper and lower level: the price at capture plus and minus
    the straddle, *calculated*, formed when it was captured and fixed for the session."""
    levels = []
    for band in bands:
        name = band_name(band)
        for kind, side, sign in (("expected_move_high", "high", 1), ("expected_move_low", "low", -1)):
            levels.append(Level(kind, f"EM {name} {side}", round(band["anchor"] + sign * band["move"], 2), "calculated",
                                None, "tradier", formed_at=band["captured_at"]))
    return levels
