"""Option contracts on a replayed day (docs/copilot-lab.md § Paper replay): which calls and puts the replay ticket offers
on a past day, and each contract's own one-minute trades that price its replayed fills.

- **No stored chain.** The app keeps no past option chain, so the candidates are derived: expirations from the standard
  calendars (each Friday, a Thursday when that Friday is a market holiday, the monthly third Friday, and every trading
  day for the tickers with daily expirations), and strikes on a grid around the underlying's replayed price, named by
  the OCC symbol rules (``occ.occ_symbol``). Only a contract whose own trades come back for that day is offered: one
  that did not exist, or did not trade, is never shown.
- **Each contract's trades.** Tradier's 1-minute time and sales for the OCC symbol, the read the desk's Contract chart
  makes (``desk_contract``), through the shared chart feed as a background (``low``) read: its single-flight, its four
  places and its 60-calls-a-minute budget. Checked lazily, only when he picks a type and an expiration (or names a
  strike), one contract at a time, at most ``PROBES_PER_MINUTE`` new reads a minute; beyond that the rest wait,
  labelled, never a burst. A past day never changes, so each answer is kept in memory (the whole day), but only the
  trades that ended by the replay clock decide what is offered or shown: a contract that has not traded yet by then
  is not offered, so nothing about the rest of the day leaks.
- **Older days.** Tradier keeps about the last 20 days of 1-minute history; on an older day options are off with that
  reason, and shares still replay.
- **The assumed spread.** Prints carry no bid or ask, so a replayed option fill pays the minute's close plus an assumed
  half-spread (``half_spread``): half that minute's high−low range, rounded up to the cent, at least 1¢ and at least
  ``FLOOR_PCT`` of the price. A fill at a minute's open (an automatic exit) or during it (a limit) uses the previous
  traded minute's range, the one already known then (``half_before``). Never a made-up price: a minute in which the
  contract did not trade is no price.

Pure reads: nothing is written. Never Robinhood.
"""
from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from datetime import date, datetime, timedelta

from app.engine.chart_math import ET

WINDOW_DAYS = 20  # Tradier's 1-minute history reaches back about this many days
STRIKES_SHOWN = 6  # strikes checked around the price per pick
EXPIRIES_SHOWN = 6
PROBES_PER_MINUTE = 12  # new contract reads a minute, one at a time
FLOOR_PCT = 0.005  # the assumed half-spread is at least 0.5% of the price
MIN_HALF = 0.01
DAILY = frozenset({"SPY", "QQQ", "IWM"})  # tickers with an expiration every trading day
KEPT = 400  # contract-days of trades kept in memory

_kept: OrderedDict[tuple[str, date], list[dict]] = OrderedDict()
_reads: deque[float] = deque()
_lock = threading.Lock()  # the kept answers and the read budget (never held across a read)
_reading = threading.Lock()  # one contract read at a time


class OptionsOff(Exception):
    """Options cannot be replayed on this day or for this contract; the message says why."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _when(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, ET).strftime("%I:%M %p").lstrip("0")


# --- whether the day can have options -----------------------------------------------------------------------------------

def off_reason(day: date, now: float) -> str | None:
    """Why options cannot be replayed on ``day``, or None (a pure check: no read)."""
    from app.engine import tradier
    if not tradier.tradier_configured():
        return "Option replay reads each contract's own trades from Tradier, and Tradier is not connected here. Shares only."
    today = datetime.fromtimestamp(now, ET).date()
    if (today - day).days > WINDOW_DAYS:
        return (f"Option replay needs each contract's own minute trades, and Tradier keeps only about the last {WINDOW_DAYS} "
                f"days of them: {day:%b %-d} is older. Shares only on this day.")
    return None


# --- the candidates -----------------------------------------------------------------------------------------------------

def _trading(day: date) -> bool:
    from app.engine import paper_replay
    return paper_replay.regular(day) is not None


def _friday_expiry(friday: date) -> date:
    """A week's standard expiration: its Friday, or the Thursday before when that Friday is a market holiday."""
    return friday if _trading(friday) else friday - timedelta(days=1)


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def expiries(symbol: str, day: date, count: int = EXPIRIES_SHOWN) -> list[str]:
    """The expirations a contract on ``day`` could have, nearest first: every trading day for ``DAILY`` tickers, each
    week's Friday (Thursday on a holiday Friday) and the monthly third Friday. Candidates only: a contract is offered
    only once its own trades on ``day`` are found."""
    found: set[date] = set()
    if symbol in DAILY:
        probe = day
        while len(found) < 5:
            if _trading(probe):
                found.add(probe)
            probe += timedelta(days=1)
    friday = day + timedelta(days=(4 - day.weekday()) % 7)
    for week in range(5):
        found.add(_friday_expiry(friday + timedelta(weeks=week)))
    for months in (0, 1):
        month = (day.month - 1 + months) % 12 + 1
        found.add(_friday_expiry(_third_friday(day.year + (day.month - 1 + months) // 12, month)))
    return [d.isoformat() for d in sorted(d for d in found if d >= day)][:count]


def strike_step(symbol: str, price: float) -> float:
    """The strike grid checked around ``price``: the listed exchanges' common increments by price."""
    if symbol in DAILY or 25 <= price < 200:
        return 1.0
    if price < 25:
        return 0.5
    if price < 500:
        return 2.5
    return 5.0


def strikes(symbol: str, price: float, count: int = STRIKES_SHOWN) -> list[float]:
    """The ``count`` grid strikes nearest ``price``, low to high."""
    step = strike_step(symbol, price)
    below = math.floor(price / step + 1e-9)
    grid = [round((below + k) * step, 2) for k in range(-count, count + 2)]
    grid = [s for s in grid if s > 0]
    return sorted(sorted(grid, key=lambda s: (abs(s - price), s))[:count])


# --- each contract's trades on the day ----------------------------------------------------------------------------------

def _params(occ: str, day: date) -> dict:
    return {"symbol": occ, "interval": "1min", "session_filter": "open",
            "start": day.strftime("%Y-%m-%d 09:30"), "end": day.strftime("%Y-%m-%d 16:15")}


def cached(occ: str, day: date) -> list[dict] | None:
    with _lock:
        return _kept.get((occ, day))


def _budget_left(now: float) -> int:
    while _reads and _reads[0] <= now - 60:
        _reads.popleft()
    return PROBES_PER_MINUTE - len(_reads)


def trades(occ: str, day: date) -> list[dict]:
    """The contract's one-minute bars on ``day`` (regular session, minutes it traded only), oldest first: kept, else one
    background read through the chart feed. An empty list is "it did not trade that day". Raises OptionsOff when the
    read is refused or over this module's budget (nothing is kept then, so a later pick tries again)."""
    from app.engine.chart_feed import ChartFeedError, _rows, chart_feed
    from app.engine.chart_math import normalize_bars
    with _lock:
        found = _kept.get((occ, day))
        if found is not None:
            _kept.move_to_end((occ, day))
            return found
    with _reading:  # one read at a time: picks queue here, never a burst
        with _lock:
            found = _kept.get((occ, day))  # read by the pick ahead of this one
            if found is not None:
                return found
            if _budget_left(time.time()) <= 0:
                raise OptionsOff("Checked enough contracts for this minute (it keeps the chart data allowance): try again in a minute.", 503)
            _reads.append(time.time())
        try:
            data, _fetched, issue = chart_feed.read("/v1/markets/timesales", _params(occ, day), 0, keep=False, low=True)
        except ChartFeedError as exc:
            raise OptionsOff(f"The contract's trades could not be read: {exc}", 503) from None
        if issue:
            raise OptionsOff(f"The contract's trades could not be read: {issue}", 503)
        found = [b for b in normalize_bars(_rows(data, "series", "data"))
                 if b["volume"] > 0 and datetime.fromtimestamp(b["time"], ET).date() == day]
        with _lock:
            _kept[(occ, day)] = found
            while len(_kept) > KEPT:
                _kept.popitem(last=False)
        return found


def last_trade(found: list[dict], at: float) -> dict | None:
    """The contract's newest minute bar that ended by ``at``: nothing later is seen."""
    done = [b for b in found if b["time"] + 60 <= at]
    return done[-1] if done else None


def half_spread(bar: dict) -> tuple[float, str]:
    """The assumed half-spread around a replayed option minute and where it came from (``range``, ``floor`` for
    ``FLOOR_PCT`` of the close, ``min`` for 1¢): half the bar's high−low range, rounded up to the cent, at least both."""
    span = math.ceil(round((float(bar["high"]) - float(bar["low"])) / 2 * 100, 6)) / 100
    pct = math.ceil(round(float(bar["close"]) * FLOOR_PCT * 100, 6)) / 100
    floor, source = (pct, "floor") if pct >= MIN_HALF else (MIN_HALF, "min")
    return (span, "range") if span >= floor else (floor, source)


def half_before(by_minute: dict[int, dict], minute: int) -> float:
    """The half-spread known at the open of ``minute``: the contract's previous traded minute's (``half_spread``), else
    the 1¢ minimum."""
    earlier = [t for t in by_minute if t < minute]
    return half_spread(by_minute[max(earlier)])[0] if earlier else MIN_HALF


def quote_at(found: list[dict], at: float, label: str) -> dict:
    """The replayed option price at ``at``: the contract's trade bar for the minute just ended, its close and the
    assumed bid and ask around it. A minute it did not trade is refused with its last trade's time."""
    bar = last_trade(found, at)
    if bar is None:
        raise OptionsOff(f"No trade in {label} yet by {_when(at)} on this day: no fill without a trade.")
    if bar["time"] + 60 <= at - 60:
        raise OptionsOff(f"No trade in {label} in the {_when(at - 60)} minute: its last trade was the {_when(bar['time'])} bar. "
                         "No fill on a stale price.")
    close = float(bar["close"])
    half, source = half_spread(bar)
    return {"close": close, "half_spread": half, "half_from": source, "low": float(bar["low"]), "high": float(bar["high"]),
            "bid": round(max(close - half, 0.0), 4), "ask": round(close + half, 4), "bar": bar["time"], "at": bar["time"] + 59}
