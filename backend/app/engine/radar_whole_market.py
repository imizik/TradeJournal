"""Liquid US common stocks, using the dated R6 roster and raw SIP bars."""
from collections import defaultdict
from datetime import date, time
from decimal import Decimal
from math import isfinite

from app.engine.premarket_archive import BATCH, at, positive, timestamp

LOOKBACK = 20
MIN_ADV = 20_000_000
MIN_PRICE = 5


def sessions(market, start, end):
    rows = market.get("https://paper-api.alpaca.markets/v2/calendar",
                      {"start": start.isoformat(), "end": end.isoformat()}, market.sip)
    days = {date.fromisoformat(r["date"]): time.fromisoformat(r["close"]) for r in rows}
    if len(days) != len(rows) or list(days) != sorted(days):
        raise ValueError("Invalid exchange sessions")
    return days


def daily_inputs(market, day, prior_days, *, include_close=False):
    """ADV over the preceding 20 sessions, split-comparable prior close, optional outcome."""
    if len(prior_days) != LOOKBACK or sorted(set(prior_days)) != prior_days or prior_days[-1] >= day:
        raise ValueError("Expected twenty preceding sessions")
    stocks = market.symbols(day, kinds=("CS",))
    symbols = sorted(set(stocks) | {"SPY"})
    end = day if include_close else prior_days[-1]
    adv, previous, closing = {}, {}, {}
    for i in range(0, len(symbols), BATCH):
        daily = defaultdict(dict)
        for symbol, bars in market.bars(symbols[i:i+BATCH], "1Day", at(prior_days[0], 0), at(end, 23), day):
            for bar in bars:
                d = timestamp(bar).date()
                if d in daily[symbol] or d not in prior_days and d != end:
                    raise ValueError("Unexpected daily SIP bar")
                daily[symbol][d] = bar
        for symbol, history in daily.items():
            if not all(d in history for d in prior_days):
                continue
            if any(not isinstance(history[d].get(k), (float, int)) or not isfinite(history[d][k])
                   or history[d][k] <= 0 for d in prior_days for k in ("vw", "v")):
                continue
            avg = sum(positive(history[d]["vw"]) * positive(history[d]["v"]) for d in prior_days) / LOOKBACK
            if symbol != "SPY" and avg < MIN_ADV:
                continue
            adv[symbol] = float(avg)
            previous[symbol] = positive(history[prior_days[-1]]["c"])
            if include_close and day in history:
                closing[symbol] = float(positive(history[day]["c"]))
    if "SPY" not in previous or include_close and "SPY" not in closing:
        raise ValueError("Missing benchmark bar")
    # The provider also returns actions on illiquid/OTC names. Only actions on
    # a ranked stock or SPY can affect this price comparison.
    splits = market.splits(day, symbols=previous.keys())
    previous = {s: float(close * splits.get(s, Decimal(1))) for s, close in previous.items()}
    return adv, previous, closing
