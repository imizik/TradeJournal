"""Rule baselines: the null hypotheses Claude's judgment has to beat.

Every rule reads ONLY packet fields (``contract.PACKET_FIELDS``) and returns a
dict that passes ``contract.validate_forecast``. All parameters below were fixed
before any replay and must NOT be tuned on the replay window (July-October
2026): a rule tuned on the sample it is scored on stops being a null hypothesis.

Signals become probabilities through one bounded transform,
``p = clip(0.5 + SLOPE * z, P_MIN, P_MAX)``, so Brier scores stay comparable and
no rule claims more confidence than a simple rule deserves. A rule trades only
when |z| >= TAKE_Z and WAITs (p = 0.5) when an input it needs is null, e.g. at
09:30 (no completed bars) or in ``bars`` packets (``features`` is null).

Units: ``*_pct`` features are read as percent points (1.0 == 1 %). Price moves
are scaled by the daily ATR shrunk to the elapsed time,
``atr20_pct * sqrt(minutes / 390)``, the usual random-walk scaling.
"""

import math

from .contract import CHECKPOINTS_ET, SYMBOLS, validate_forecast

SLOPE = 0.05            # probability per unit of z
P_MIN, P_MAX = 0.35, 0.65
TAKE_Z = 1.0            # |z| needed to trade
SESSION_MINUTES = 390
ALWAYS_LONG_P = 0.52    # mild upward drift prior
FADE_MINUTES = 5        # fade_open: the first five one-minute bars
ORB_MINUTES = 15        # orb: opening range = first fifteen bars
ORB_Z = 1.2             # orb: fixed conviction on a breakout (p = 0.56)
GAP_MIN_ATR = 0.25      # gap_fill: |gap| must be >= a quarter of ATR
GAP_Z_PER_ATR = 4.0     # gap_fill: z = 4 * gap / ATR (threshold maps to z = 1)


# Packet readers ---------------------------------------------------------------
def _sym(packet, symbol):
    return ((packet or {}).get("symbols") or {}).get(symbol) or {}


def _features(packet, symbol):
    return _sym(packet, symbol).get("features") or {}


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _bars(packet, symbol):
    """Completed RTH bars as dicts keyed by BAR_COLUMNS names, oldest first."""
    block = _sym(packet, symbol).get("bars") or {}
    columns = block.get("columns") or ()
    return [dict(zip(columns, row)) for row in block.get("rows") or ()]


def _opening(packet, symbol, n):
    """The first n RTH bars (09:30 .. 09:30+n-1), or None unless all n are present."""
    cutoff = f"09:{30 + n:02d}"
    bars = [b for b in _bars(packet, symbol) if "09:30" <= str(b.get("et")) < cutoff]
    return bars if len(bars) == n else None


def _last(packet, symbol):
    """Last price: the packet's ``last`` (a number, or a dict with a price), else last close."""
    last = _sym(packet, symbol).get("last")
    if isinstance(last, dict):
        last = next((last[k] for k in ("price", "c", "close") if k in last), None)
    if _num(last) is not None:
        return _num(last)
    bars = _bars(packet, symbol)
    return _num(bars[-1].get("c")) if bars else None


def _minutes(packet):
    minutes = _num((packet or {}).get("minutes_since_open"))
    if minutes is None and (packet or {}).get("checkpoint_et") in CHECKPOINTS_ET:
        hh, mm = packet["checkpoint_et"].split(":")
        minutes = (int(hh) - 9) * 60 + int(mm) - 30
    return minutes


def _move_scale_pct(packet, symbol, minutes):
    """Expected |move| in percent over ``minutes`` from the daily ATR, or None."""
    atr = _num(_features(packet, symbol).get("atr20_pct"))
    if atr is None or atr <= 0 or not minutes or minutes <= 0:
        return None
    return atr * math.sqrt(minutes / SESSION_MINUTES)


# Forecast builder ---------------------------------------------------------------
def _p(z):
    return min(P_MAX, max(P_MIN, 0.5 + SLOPE * z))


def _forecast(zs, reason):
    """zs maps symbol -> z (positive = up) or None. Trade the strongest |z| >= TAKE_Z."""
    probs = {s: (_p(zs[s]) if zs.get(s) is not None else 0.5) for s in SYMBOLS}
    live = [(abs(zs[s]), -i, s) for i, s in enumerate(SYMBOLS)
            if zs.get(s) is not None and abs(zs[s]) >= TAKE_Z]
    action, symbol = "WAIT", None
    if live:
        symbol = max(live)[2]
        action = "LONG" if zs[symbol] > 0 else "SHORT"
    return validate_forecast({"spy_p_up": probs["SPY"], "qqq_p_up": probs["QQQ"],
                              "action": action, "symbol": symbol, "reason": reason[:400]})


# Rules ----------------------------------------------------------------------------
def coin(packet):
    """Calibration floor: p = 0.5 for both, never trades (Brier 0.25 by construction)."""
    return _forecast({}, "coin: no view")


def always_long(packet):
    """'Just take it': p = ALWAYS_LONG_P for both, LONG SPY at every checkpoint."""
    return validate_forecast({"spy_p_up": ALWAYS_LONG_P, "qqq_p_up": ALWAYS_LONG_P,
                              "action": "LONG", "symbol": "SPY",
                              "reason": "always_long: drift prior"})


def momentum(packet):
    """Continuation: z = return since open / ATR scaled to elapsed minutes."""
    minutes, zs = _minutes(packet), {}
    for s in SYMBOLS:
        ret = _num(_features(packet, s).get("return_since_open_pct"))
        scale = _move_scale_pct(packet, s, minutes)
        zs[s] = ret / scale if ret is not None and scale else None
    return _forecast(zs, "momentum: return since open vs ATR")


def fade_open(packet):
    """Mean reversion: bet against the first five-minute move, from 09:35 on."""
    zs = {}
    for s in SYMBOLS:
        bars = _opening(packet, s, FADE_MINUTES)
        scale = _move_scale_pct(packet, s, FADE_MINUTES)
        o, c = (_num(bars[0].get("o")), _num(bars[-1].get("c"))) if bars else (None, None)
        if not o or c is None or not scale:
            zs[s] = None
            continue
        zs[s] = -((c / o - 1) * 100) / scale
    return _forecast(zs, "fade_open: against the first 5-minute move")


def orb(packet):
    """15-minute opening-range breakout, from 09:45: last beyond the range -> that way."""
    zs = {}
    for s in SYMBOLS:
        bars, last = _opening(packet, s, ORB_MINUTES) or [], _last(packet, s)
        highs = [_num(b.get("h")) for b in bars]
        lows = [_num(b.get("l")) for b in bars]
        if not bars or last is None or None in highs or None in lows:
            zs[s] = None
        elif last > max(highs):
            zs[s] = ORB_Z
        elif last < min(lows):
            zs[s] = -ORB_Z
        else:
            zs[s] = 0.0
    return _forecast(zs, "orb: 15-minute opening range breakout")


def vwap_side(packet):
    """Trend vs VWAP: z = (last - session VWAP) / ATR scaled to elapsed minutes."""
    minutes, zs = _minutes(packet), {}
    for s in SYMBOLS:
        vwap, last = _num(_features(packet, s).get("session_vwap")), _last(packet, s)
        scale = _move_scale_pct(packet, s, minutes)
        ok = vwap and vwap > 0 and last is not None and scale
        zs[s] = ((last / vwap - 1) * 100) / scale if ok else None
    return _forecast(zs, "vwap_side: distance from session VWAP vs ATR")


def gap_fill(packet):
    """Gap fill: |gap| >= GAP_MIN_ATR * ATR and not yet filled -> bet toward prior close."""
    zs = {}
    for s in SYMBOLS:
        f = _features(packet, s)
        gap, atr = _num(f.get("gap_pct")), _num(f.get("atr20_pct"))
        prior, last = _num(f.get("prior_close")), _last(packet, s)
        if None in (gap, atr, prior, last) or atr <= 0 or abs(gap) < GAP_MIN_ATR * atr:
            zs[s] = None
        elif (gap > 0 and last <= prior) or (gap < 0 and last >= prior):
            zs[s] = None  # already filled
        else:
            zs[s] = -GAP_Z_PER_ATR * gap / atr
    return _forecast(zs, "gap_fill: toward the prior close")


BASELINES = {
    "coin": coin,
    "always_long": always_long,
    "momentum": momentum,
    "fade_open": fade_open,
    "orb": orb,
    "vwap_side": vwap_side,
    "gap_fill": gap_fill,
}
