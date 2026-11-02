"""The copilot's market breadth and options positioning (docs/copilot-lab.md § Breadth and positioning).

``get_breadth`` asks whether the average stock is taking part: one Tradier quote request for the S&P 500 list in
``app/data/sp500.json`` gives advancers and decliners, the median and equal-weight day change, new 52-week highs and
lows, how many sit near their high or 20% or more below it, and the same by sector. ``get_positioning`` asks how
afraid the options market is: the Cboe volatility indexes' term structure (VIX9D, VIX, VIX3M, VIX6M), VVIX and SKEW,
and for one underlying (SPY by default) the near and about-30-day expiries' at-the-money implied volatility, 25-delta
put-call skew and put/call volume and open interest from the options feed's cached chains. Both read current data
only, so replay says they are unavailable; the fixture serves fixed numbers. Nothing here writes.
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from datetime import date, datetime
from pathlib import Path

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

INDEX_FILE = Path(__file__).resolve().parent.parent / "data" / "sp500.json"
BREADTH_TTL_S = 180
NEAR_HIGH = 0.05
BEAR = 0.20
BREADTH_NOTE = ("One quote per S&P 500 member from the hand-kept list (list_as_of). day_pct is against the previous "
                "close; a new high or low is today's high or low reaching the provider's 52-week figure. Equal weight: "
                "every member counts once, so this is the average stock, not the index.")
VOL_INDEXES = ("VIX9D", "VIX", "VIX3M", "VIX6M", "VVIX", "SKEW")
POSITIONING_NOTE = ("VIX9D < VIX < VIX3M (contango) is the calm shape; front above back (backwardation) is stress now. "
                    "skew_25d is the 25-delta put's implied volatility minus the 25-delta call's, in vol points: higher "
                    "means puts are bid (null when no strike is within 0.10 of 25 delta). Put/call ratios count this expiry's "
                    "contracts on the symbol's primary root; open interest is last night's. as_of is the oldest chain's read. "
                    "Greeks and IV are the provider's, refreshed hourly.")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def members() -> tuple[dict[str, str], str | None]:
    """``{symbol: sector}`` from the hand-kept list, and its as-of date."""
    doc = json.loads(INDEX_FILE.read_text())
    return {s: sector for sector, symbols in doc["sectors"].items() for s in symbols}, doc.get("as_of")


def _provider(symbol: str) -> str:
    return symbol.replace(".", "/")  # Tradier quotes BRK.B as BRK/B


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _tally(rows: list[dict]) -> dict:
    moves = [r["day_pct"] for r in rows if r["day_pct"] is not None]
    off = [r["off_high"] for r in rows if r["off_high"] is not None]
    return {"members": len(rows), "quoted": len(moves),
            "advancers": sum(m > 0 for m in moves), "decliners": sum(m < 0 for m in moves),
            "up_share": _share(sum(m > 0 for m in moves), len(moves)),
            "median_day_pct": round(statistics.median(moves), 2) if moves else None,
            "equal_weight_day_pct": round(statistics.fmean(moves), 2) if moves else None,
            "new_52w_highs": sum(r["new_high"] for r in rows), "new_52w_lows": sum(r["new_low"] for r in rows),
            "within_5pct_of_52w_high": _share(sum(o <= NEAR_HIGH for o in off), len(off)),
            "20pct_or_more_below_52w_high": _share(sum(o >= BEAR for o in off), len(off))}


def breadth(quotes: dict[str, dict], index: dict[str, str]) -> dict:
    """The tally over ``index`` (symbol -> sector) from Tradier quote rows keyed by our symbols."""
    rows, sectors = [], {}
    for symbol, sector in index.items():
        q = quotes.get(symbol) or {}
        last, prev, high, low = (_num(q.get(k)) for k in ("last", "prevclose", "high", "low"))
        top, bottom = _num(q.get("week_52_high")), _num(q.get("week_52_low"))
        row = {"day_pct": round((last / prev - 1) * 100, 3) if last and prev else None,
               "off_high": 1 - last / top if last and top else None,
               "new_high": bool(high and top and high >= top), "new_low": bool(low and bottom and low <= bottom)}
        rows.append(row)
        sectors.setdefault(sector, []).append(row)
    by_sector = {name: {k: v for k, v in _tally(part).items() if k not in ("members", "quoted")}
                 for name, part in sorted(sectors.items())}
    return {**_tally(rows), "by_sector": by_sector}


def live_breadth(now: datetime) -> dict:
    from app.engine import tradier
    with _lock:
        hit = _cache.get("breadth")
        if hit and time.time() - hit[0] < BREADTH_TTL_S:
            return hit[1]
    index, as_of = members()
    try:
        quoted = tradier.get_quotes_once([_provider(s) for s in index])
    except tradier.TradierError as exc:
        return {"state": "unavailable", "reason": f"Tradier quotes could not be read: {exc}"[:200]}
    rows = {s: (quoted.get(_provider(s)).raw or {}) for s in index if quoted.get(_provider(s))}
    out = {"state": "ok" if len(rows) >= 0.95 * len(index) else "partial", "as_of": now.astimezone(ET).isoformat(timespec="minutes"),
           "list_as_of": as_of, **breadth(rows, index), "note": BREADTH_NOTE}
    with _lock:
        _cache["breadth"] = (time.time(), out)
    return out


DELTA_TOLERANCE = 0.10  # a thin chain's nearest strike may be far from 25 delta: then there is no 25-delta figure


def _nearest(contracts, target: float):
    found = min(contracts, key=lambda c: abs(abs(c.delta) - target), default=None)
    return found if found is not None and abs(abs(found.delta) - target) <= DELTA_TOLERANCE else None


def chain_stats(chain, spot: float, today: date, root: str | None = None) -> dict:
    """One expiry's at-the-money IV, 25-delta skew and put/call ratios, over one root (SPX and SPXW never merge)."""
    contracts = [c for c in chain.contracts if root is None or c.root == root]
    calls = [c for c in contracts if c.option_type == "call"]
    puts = [c for c in contracts if c.option_type == "put"]
    both = {c.strike for c in calls if c.iv} & {c.strike for c in puts if c.iv}  # an ATM IV is the call and put's mean
    strike = min(both or {c.strike for c in contracts}, key=lambda k: abs(k - spot))
    atm = [c.iv for c in contracts if c.strike == strike and c.iv]
    call25 = _nearest([c for c in calls if c.delta is not None and c.iv], 0.25)
    put25 = _nearest([c for c in puts if c.delta is not None and c.iv], 0.25)

    def ratio(field: str) -> float | None:
        p, c = sum(getattr(x, field) or 0 for x in puts), sum(getattr(x, field) or 0 for x in calls)
        return round(p / c, 2) if c else None
    return {"expiration": chain.expiration.isoformat(), "days": (chain.expiration - today).days, "atm_strike": strike,
            "atm_iv_pct": round(statistics.fmean(atm) * 100, 1) if atm else None,
            "put_25d_iv_pct": round(put25.iv * 100, 1) if put25 else None,
            "call_25d_iv_pct": round(call25.iv * 100, 1) if call25 else None,
            "skew_25d": round((put25.iv - call25.iv) * 100, 1) if put25 and call25 else None,
            "put_call_volume": ratio("volume"), "put_call_open_interest": ratio("open_interest")}


def pick_two(live: list[date], today: date) -> list[date]:
    """The nearest expiry at least five days out and the one nearest 30 days."""
    later = [d for d in live if (d - today).days >= 5]
    if not later:
        return []
    month = min(later, key=lambda d: abs((d - today).days - 30))
    return list(dict.fromkeys([later[0], month]))


def vol_indexes(quotes: dict[str, dict]) -> dict:
    out = {k: {"last": _num(q.get("last")), "change_pct": _num(q.get("change_percentage"))}
           for k in VOL_INDEXES if (q := quotes.get(k))}
    front, mid, back = ((out.get(k) or {}).get("last") for k in ("VIX9D", "VIX", "VIX3M"))
    if front and mid and back:
        out["curve"] = "contango" if front < mid < back else "backwardation" if front > mid > back else "mixed"
    return out


def live_positioning(symbol: str, now: datetime) -> dict:
    from app.engine import tradier
    from app.engine.options_feed import options_feed
    from app.engine.quotes import get_stock_quotes
    today = now.astimezone(ET).date()
    out: dict = {"symbol": symbol, "as_of": now.astimezone(ET).isoformat(timespec="minutes"), "note": POSITIONING_NOTE}
    try:
        out["vol_indexes"] = vol_indexes({k: q.raw or {} for k, q in tradier.get_quotes_once(list(VOL_INDEXES)).items()})
    except tradier.TradierError as exc:
        out["vol_indexes"] = {"state": "unavailable", "reason": str(exc)[:160]}
    spot = get_stock_quotes([symbol]).get(symbol)
    if not isinstance(spot, (int, float)) or not spot > 0:
        return {**out, "state": "partial", "expiries": [], "reason": f"No current {symbol} price, so strikes cannot be placed."}
    try:
        reads, issue = options_feed.chains(symbol, lambda live: pick_two(live, today))
    except ValueError:
        return {**out, "state": "partial", "expiries": [], "reason": f"{symbol} is not an optionable underlying symbol."}
    from app.engine.options_positioning import primary_root
    expiries = [chain_stats(read.value, float(spot), today, primary_root(symbol)) for read in reads if read.value.contracts]
    out.update(spot=round(float(spot), 2), expiries=expiries, state="ok" if expiries and not issue else "partial")
    if issue:
        out["reason"] = issue
    if reads:
        # A chain read earlier today is served from the feed's cache: the result is as old as its oldest chain.
        out["as_of"] = out["chains_fetched_at"] = datetime.fromtimestamp(min(r.fetched for r in reads), ET).isoformat(timespec="minutes")
    return out


REPLAY_REASON = "{} reads current quotes and chains, not the frozen moment's, so it is unavailable in replay."


def fixture_breadth() -> dict:
    return {"state": "ok", "as_of": "2026-10-23T11:12-04:00", "list_as_of": "2026-11-02", "members": 503, "quoted": 503,
            "advancers": 188, "decliners": 309, "up_share": 0.378, "median_day_pct": -0.41, "equal_weight_day_pct": -0.37,
            "new_52w_highs": 9, "new_52w_lows": 14, "within_5pct_of_52w_high": 0.21, "20pct_or_more_below_52w_high": 0.18,
            "by_sector": {"Information Technology": {"advancers": 21, "decliners": 46, "up_share": 0.313, "median_day_pct": -1.12,
                                                     "equal_weight_day_pct": -1.31, "new_52w_highs": 1, "new_52w_lows": 3,
                                                     "within_5pct_of_52w_high": 0.15, "20pct_or_more_below_52w_high": 0.27}},
            "note": BREADTH_NOTE}


def fixture_positioning(symbol: str) -> dict:
    return {"symbol": symbol, "state": "ok", "as_of": "2026-10-23T11:12-04:00", "spot": 655.2, "note": POSITIONING_NOTE,
            "vol_indexes": {"VIX9D": {"last": 19.8, "change_pct": 9.1}, "VIX": {"last": 19.1, "change_pct": 6.2},
                            "VIX3M": {"last": 20.4, "change_pct": 3.0}, "curve": "mixed"},
            "expiries": [{"expiration": "2026-10-30", "days": 7, "atm_strike": 655.0, "atm_iv_pct": 18.4, "put_25d_iv_pct": 22.9,
                          "call_25d_iv_pct": 15.6, "skew_25d": 7.3, "put_call_volume": 1.42, "put_call_open_interest": 1.61}]}
