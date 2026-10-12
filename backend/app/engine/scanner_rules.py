"""Setup scanner S1 rules (``docs/agent/setup-scanner-contract.md``), pure.

Everything here is a function of bars, chains and quotes passed in, so the
rules are unit-testable without a network and a restart recomputes the same
answers. ``setup_scanner.py`` reads the data and stores what these decide.

Prices are underlying prices unless a name says premium. Times are UTC epoch
seconds. A 5-minute bar is built from the regular session's 1-minute bars.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

VERSION = "s1-v1"
UNIVERSE = ("AAPL", "AMZN", "GOOGL", "META", "SPY", "QQQ", "NBIS", "MU", "CRDO", "MRVL", "LLY", "AMD")
BAR_SECONDS = 300
FIRST_BAR_AFTER = 15 * 60  # bars start at or after 09:45 (15 minutes after the open)
LAST_BAR_END_MINUTE = 15 * 60  # no candidate from a bar closing after 15:00 New York
FADE_STRETCH_ATR = 0.35
FADE_STOP_BUFFER_ATR = 0.05
FADE_MAX_PER_DAY = 2
ORB_LAST_CLOSE_MINUTE = 10 * 60 + 45
ORB_VOLUME_RATIO = 1.0
ORB_TARGET_R = 2.0
COOLDOWN_SECONDS = 30 * 60
EXPIRY_SECONDS = 10 * 60
TIME_STOP_SECONDS = 60 * 60
FLAT_SAME_DAY_MINUTE = 15 * 60 + 45
FLAT_OTHER_MINUTE = 15 * 60 + 50
MAX_DELAY_SECONDS = 120  # a bar, exit condition or quote judged later than this is not acted on
EXTENDED_VWAP_PCT = 1.5
EXTENDED_EMA9_PCT = 0.8
CONTRACT = {"dte_min": 3, "dte_max": 7, "delta_min": 0.25, "delta_max": 0.45, "delta_target": 0.35,
            "min_open_interest": 500, "min_volume": 100, "max_spread_of_mid": 0.10}
COMMISSION_PER_SIDE = 0.65

PARAMS = {
    "version": VERSION, "universe": list(UNIVERSE), "bar_seconds": BAR_SECONDS,
    "first_bar_after_open_seconds": FIRST_BAR_AFTER, "last_bar_end_minute": LAST_BAR_END_MINUTE,
    "fade": {"stretch_atr": FADE_STRETCH_ATR, "stop_buffer_atr": FADE_STOP_BUFFER_ATR, "max_per_day": FADE_MAX_PER_DAY},
    "orb": {"last_close_minute": ORB_LAST_CLOSE_MINUTE, "volume_ratio": ORB_VOLUME_RATIO, "target_r": ORB_TARGET_R},
    "cooldown_seconds": COOLDOWN_SECONDS, "expiry_seconds": EXPIRY_SECONDS, "time_stop_seconds": TIME_STOP_SECONDS,
    "flat_minutes": {"same_day": FLAT_SAME_DAY_MINUTE, "other": FLAT_OTHER_MINUTE},
    "max_delay_seconds": MAX_DELAY_SECONDS, "extended": {"vwap_pct": EXTENDED_VWAP_PCT, "ema9_pct": EXTENDED_EMA9_PCT},
    "contract": CONTRACT, "commission_per_side": COMMISSION_PER_SIDE,
}
PARAMS_HASH = hashlib.sha256(json.dumps(PARAMS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ------------------------------------------------------------------ bars


def five_minute_bars(minutes: list[dict], open_at: int, close_at: int) -> list[dict]:
    """Regular-session 5-minute bars from normalized 1-minute bars, each with session VWAP and EMA9 at its close."""
    groups: dict[int, list[dict]] = {}
    for m in minutes:
        if open_at <= m["time"] < close_at:
            groups.setdefault(open_at + (m["time"] - open_at) // BAR_SECONDS * BAR_SECONDS, []).append(m)
    bars, pv, vol, ema = [], 0.0, 0.0, None
    for start in sorted(groups):
        rows = sorted(groups[start], key=lambda r: r["time"])
        bar = {"start": start, "end": min(start + BAR_SECONDS, close_at), "open": rows[0]["open"],
               "high": max(r["high"] for r in rows), "low": min(r["low"] for r in rows),
               "close": rows[-1]["close"], "volume": sum(r["volume"] for r in rows)}
        for r in rows:
            pv += (r["high"] + r["low"] + r["close"]) / 3 * r["volume"]
            vol += r["volume"]
        bar["vwap"] = pv / vol if vol > 0 else None
        ema = bar["close"] if ema is None else ema + 0.2 * (bar["close"] - ema)
        bar["ema9"] = ema
        bars.append(bar)
    return bars


def atr14(daily: list[dict]) -> float | None:
    """Mean true range of the last 14 completed sessions; ``daily`` is oldest first and excludes today."""
    if len(daily) < 15:
        return None
    rows = daily[-15:]
    ranges = [max(rows[i]["high"], rows[i - 1]["close"]) - min(rows[i]["low"], rows[i - 1]["close"]) for i in range(1, 15)]
    value = sum(ranges) / 14
    return value if value > 0 else None


# ------------------------------------------------------------------ setups


def scan(bars: list[dict], atr: float, open_at: int, last_end: int, taken: set[tuple[str, int]]) -> list[dict]:
    """Every setup the day's bars produce, oldest first.

    ``taken`` holds (setup, bar end) of candidates already saved for this symbol
    and day. A saved fade resets the stretch and counts toward the daily limit,
    exactly as the historical replay did; the caller applies cooldown and the
    one-open-trade rule to the newest signal only. At most one signal per bar:
    an opening-range break first, then a long fade, then a short fade.
    """
    opening = [b for b in bars if b["start"] < open_at + FIRST_BAR_AFTER]
    if not opening or len(opening) < FIRST_BAR_AFTER // BAR_SECONDS:
        return []
    or_high, or_low = max(b["high"] for b in opening), min(b["low"] for b in opening)
    or_volume = sum(b["volume"] for b in opening) / len(opening)
    orb_close_by = open_at + (ORB_LAST_CLOSE_MINUTE - 9 * 60 - 30) * 60
    signals, low, high, prev, orb_done, fades = [], None, None, None, False, 0
    for bar in bars:
        vwap = bar["vwap"]
        if vwap is None:
            prev = bar
            continue
        if bar["low"] <= vwap - FADE_STRETCH_ATR * atr:
            low = bar["low"] if low is None else min(low, bar["low"])
        if bar["high"] >= vwap + FADE_STRETCH_ATR * atr:
            high = bar["high"] if high is None else max(high, bar["high"])
        if bar["close"] >= vwap:
            low = None
        if bar["close"] <= vwap:
            high = None
        if bar["start"] >= open_at + FIRST_BAR_AFTER and bar["end"] <= last_end and prev is not None:
            found = None
            if not orb_done and bar["close"] > or_high:
                orb_done = True
                if bar["end"] <= orb_close_by and bar["close"] > vwap and bar["volume"] >= ORB_VOLUME_RATIO * or_volume:
                    stop = (or_high + or_low) / 2
                    found = ("orb", "long", stop, bar["close"] + ORB_TARGET_R * (bar["close"] - stop))
            if found is None and fades < FADE_MAX_PER_DAY and low is not None and bar["close"] > prev["high"] and bar["close"] < vwap:
                stop = low - FADE_STOP_BUFFER_ATR * atr
                if vwap - bar["close"] >= bar["close"] - stop:
                    found = ("fade", "long", stop, vwap)
            if found is None and fades < FADE_MAX_PER_DAY and high is not None and bar["close"] < prev["low"] and bar["close"] > vwap:
                stop = high + FADE_STOP_BUFFER_ATR * atr
                if bar["close"] - vwap >= stop - bar["close"]:
                    found = ("fade", "short", stop, vwap)
            if found is not None:
                setup, direction, stop, target = found
                signals.append(_signal(bar, setup, direction, stop, target, atr, or_high, or_low))
                if (setup, bar["end"]) in taken and setup == "fade":
                    fades += 1
                    low = high = None
        prev = bar
    return signals


def _signal(bar, setup, direction, stop, target, atr, or_high, or_low) -> dict:
    sign = 1 if direction == "long" else -1
    vs_vwap = (bar["close"] - bar["vwap"]) / bar["vwap"] * 100
    vs_ema9 = (bar["close"] - bar["ema9"]) / bar["ema9"] * 100
    flags = []
    if direction == "short" and (sign * vs_vwap > EXTENDED_VWAP_PCT or sign * vs_ema9 > EXTENDED_EMA9_PCT):
        flags.append("put_extended")
    return {
        "setup": setup, "direction": direction, "bar_start": bar["start"], "bar_end": bar["end"],
        "stop": round(stop, 4), "target": round(target, 4), "flags": flags,
        "facts": {"open": bar["open"], "high": bar["high"], "low": bar["low"], "close": bar["close"],
                  "volume": bar["volume"], "vwap": round(bar["vwap"], 4), "ema9": round(bar["ema9"], 4),
                  "daily_atr14": round(atr, 4), "opening_range_high": or_high, "opening_range_low": or_low,
                  "vs_vwap_pct": round(vs_vwap, 4), "vs_ema9_pct": round(vs_ema9, 4)},
    }


# ------------------------------------------------------------------ contracts


def pick_expiration(expirations: list[date], today: date) -> date | None:
    """Same day if listed; otherwise the nearest 3–7 days out. Never 1–2 days out."""
    if today in expirations:
        return today
    later = sorted(e for e in expirations if CONTRACT["dte_min"] <= (e - today).days <= CONTRACT["dte_max"])
    return later[0] if later else None


def choose_contract(contracts, direction: str) -> dict | None:
    """The listed contract closest to 0.35 delta that meets every liquidity limit; None when none does."""
    wanted = "call" if direction == "long" else "put"
    best = None
    for c in contracts:
        if c.option_type != wanted or c.delta is None or c.bid is None or c.ask is None or not c.multiplier:
            continue
        delta, mid = abs(c.delta), (c.bid + c.ask) / 2
        if not (CONTRACT["delta_min"] <= delta <= CONTRACT["delta_max"]) or c.bid <= 0 or c.ask < c.bid:
            continue
        if (c.open_interest or 0) < CONTRACT["min_open_interest"] or (c.volume or 0) < CONTRACT["min_volume"]:
            continue
        if c.ask - c.bid > CONTRACT["max_spread_of_mid"] * mid:
            continue
        rank = (abs(delta - CONTRACT["delta_target"]), c.ask - c.bid, c.strike)
        if best is None or rank < best[0]:
            best = (rank, c)
    if best is None:
        return None
    c = best[1]
    return {"symbol": c.symbol, "expiration": c.expiration.isoformat(), "option_type": c.option_type,
            "strike": c.strike, "multiplier": c.multiplier, "bid": c.bid, "ask": c.ask, "delta": c.delta,
            "open_interest": c.open_interest, "volume": c.volume,
            "bid_time": c.bid_time.isoformat() if c.bid_time else None,
            "ask_time": c.ask_time.isoformat() if c.ask_time else None}


# ------------------------------------------------------------------ the paper trade


def exit_condition(direction: str, stop: float, target: float, minutes: list[dict], entry_at: float,
                   time_stop_at: float, flat_at: float, now: float, lateness: float) -> dict | None:
    """The first exit condition after entry, judged on the underlying.

    Completed 1-minute bars that started after the entry minute are checked for
    the stop and the target (a bar touching both counts as the stop). The time
    stop and the flat-by time are clock conditions. Returns None while none has
    happened."""
    first_start = (int(entry_at) // 60 + 1) * 60
    found = []
    for bar in minutes:
        if bar["time"] < first_start or bar["end_time"] + lateness > now:
            continue
        hit_stop = bar["low"] <= stop if direction == "long" else bar["high"] >= stop
        hit_target = bar["high"] >= target if direction == "long" else bar["low"] <= target
        if hit_stop or hit_target:
            found.append({"reason": "stop" if hit_stop else "target", "condition_at": bar["end_time"],
                          "bar_start": bar["time"], "reference": stop if hit_stop else target})
            break
    for reason, moment in (("time_stop", time_stop_at), ("flat", flat_at)):
        if now >= moment:
            found.append({"reason": reason, "condition_at": moment, "bar_start": None, "reference": None})
    return min(found, key=lambda f: f["condition_at"]) if found else None


def flat_at(open_at: int, close_at: int, same_day: bool) -> int:
    minute = FLAT_SAME_DAY_MINUTE if same_day else FLAT_OTHER_MINUTE
    return min(open_at + (minute - 9 * 60 - 30) * 60, close_at - 10 * 60)


def result(entry: dict, exit_: dict, multiplier: int) -> dict:
    """Per-contract dollars: base (ask in, bid out) and a pessimistic view at twice each observed spread."""
    fees = 2 * COMMISSION_PER_SIDE
    base = (exit_["bid"] - entry["ask"]) * multiplier - fees
    paid = entry["ask"] * multiplier + COMMISSION_PER_SIDE
    worse_in = entry["ask"] + (entry["ask"] - entry["bid"]) / 2
    worse_out = exit_["bid"] - (exit_["ask"] - exit_["bid"]) / 2
    return {"pnl": round(base, 2), "return_on_premium": round(base / paid, 4) if paid > 0 else None,
            "pnl_2x_spread": round((worse_out - worse_in) * multiplier - fees, 2)}
