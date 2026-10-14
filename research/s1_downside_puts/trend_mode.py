"""Research only: "trend mode" — play the day's trend either way.

Not wired into the scanner. Reuses backtest.py's data, contract choice and pricing.

Market gate (no hindsight; judged on SPY 5-minute bars completed by the signal bar):
  down: SPY close below its 09:30-09:45 low and below VWAP, SPY VWAP lower than 30
        minutes earlier, and no SPY 5-minute close above VWAP in the last 30 minutes.
  up:   the mirror. Gate considered from the bar closing 10:00; entries until 14:30.
Symbol entry (down; up mirrors): close below its own opening-range low and VWAP, EMA9
  below VWAP, the previous bar touched EMA9 from below and closed below it, and this bar
  closes below the previous bar's low. Stop = higher of the two bars' highs + 0.05 ATR.
Exits compared:
  s1     - 2x stop distance target, 60-minute time stop (S1's exits)
  ema9   - trail: out on the first 5-minute close back across EMA9
  vwap   - trail: out on the first 5-minute close back across VWAP
  All keep the stop and flat by 15:45 (0DTE) / 15:50.
Gate "none" runs the same entries without the SPY gate.

  python research/s1_downside_puts/trend_mode.py design   # 2026-03-02 .. 2026-09-11
  python research/s1_downside_puts/trend_mode.py recent   # 2026-09-14 .. 2026-10-13
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import backtest as B  # noqa: E402
from backtest import R  # noqa: E402

WINDOWS = {"design": (date(2026, 3, 2), date(2026, 9, 11)), "recent": (date(2026, 9, 14), date(2026, 10, 13))}
GATE_FROM_MINUTE = 10 * 60
LAST_ENTRY_MINUTE = 14 * 60 + 30
MAX_PER_DAY = 2
EXITS = ("s1", "ema9", "vwap")
GATES = ("spy", "none")


def weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def at_minute(open_at, minute):
    return open_at + (minute - 9 * 60 - 30) * 60


def opening_range(bars, open_at):
    opening = [b for b in bars if b["start"] < open_at + R.FIRST_BAR_AFTER]
    if len(opening) < 3:
        return None
    return max(b["high"] for b in opening), min(b["low"] for b in opening)


def spy_gate(spy_bars, open_at):
    """{bar_end: 'down'|'up'|None} for every SPY 5-minute bar."""
    rng = opening_range(spy_bars, open_at)
    out = {}
    if rng is None:
        return out
    hi, lo = rng
    for i, b in enumerate(spy_bars):
        out[b["end"]] = None
        if b["end"] < at_minute(open_at, GATE_FROM_MINUTE) or i < 6 or b["vwap"] is None:
            continue
        recent = spy_bars[i - 5:i + 1]
        then = spy_bars[i - 6]["vwap"]
        if (b["close"] < lo and b["close"] < b["vwap"] and b["vwap"] < then
                and all(r["close"] <= r["vwap"] for r in recent)):
            out[b["end"]] = "down"
        elif (b["close"] > hi and b["close"] > b["vwap"] and b["vwap"] > then
              and all(r["close"] >= r["vwap"] for r in recent)):
            out[b["end"]] = "up"
    return out


def entries(bars, atr, open_at):
    rng = opening_range(bars, open_at)
    if rng is None:
        return []
    hi, lo = rng
    out = []
    for prev, b in zip(bars, bars[1:]):
        if b["end"] < at_minute(open_at, GATE_FROM_MINUTE) or b["end"] > at_minute(open_at, LAST_ENTRY_MINUTE):
            continue
        if b["vwap"] is None or prev["vwap"] is None:
            continue
        if (b["close"] < lo and b["close"] < b["vwap"] and b["ema9"] < b["vwap"]
                and prev["high"] >= prev["ema9"] and prev["close"] < prev["ema9"] and b["close"] < prev["low"]):
            stop = max(prev["high"], b["high"]) + R.FADE_STOP_BUFFER_ATR * atr
            out.append(R._signal(b, "trend", "short", stop, b["close"] - 2 * (stop - b["close"]), atr, hi, lo))
        elif (b["close"] > hi and b["close"] > b["vwap"] and b["ema9"] > b["vwap"]
              and prev["low"] <= prev["ema9"] and prev["close"] > prev["ema9"] and b["close"] > prev["high"]):
            stop = min(prev["low"], b["low"]) - R.FADE_STOP_BUFFER_ATR * atr
            out.append(R._signal(b, "trend", "long", stop, b["close"] + 2 * (b["close"] - stop), atr, hi, lo))
    return out


def trail_exit(kind, sig, minutes, fives, entry_at, flat):
    """Stop on 1-minute bars after the entry minute, or a 5-minute close back across EMA9/VWAP."""
    down = sig["direction"] == "short"
    first_start = (int(entry_at) // 60 + 1) * 60
    events = []
    for m in minutes:
        if m["time"] >= first_start and (m["high"] >= sig["stop"] if down else m["low"] <= sig["stop"]):
            events.append((m["end_time"], "stop"))
            break
    for f in fives:
        if f["end"] <= entry_at:
            continue
        line = f["ema9"] if kind == "ema9" else f["vwap"]
        if line is not None and (f["close"] > line if down else f["close"] < line):
            events.append((f["end"], "trail"))
            break
    events.append((flat, "flat"))
    at, reason = min(events)
    return {"condition_at": at, "reason": reason}


_chosen = {}


def price(sym, day, sig, minutes, fives, open_at, close_at, exit_kind):
    key = (sym, sig["bar_end"], sig["direction"])
    if key not in _chosen:
        _chosen[key] = B.choose(sym, day, sig, minutes)
    contract, why = _chosen[key]
    if contract is None:
        return {"status": why}
    entry_at = sig["bar_end"]
    flat = R.flat_at(open_at, close_at, contract["dte"] == 0)
    if exit_kind == "s1":
        ex = R.exit_condition(sig["direction"], sig["stop"], sig["target"], minutes, entry_at,
                              entry_at + R.TIME_STOP_SECONDS, flat, close_at + 3600, 0)
    else:
        ex = trail_exit(exit_kind, sig, minutes, fives, entry_at, flat)
    entry = B.first_bar_at(contract["bars"], entry_at)
    out = B.first_bar_at(contract["bars"], ex["condition_at"])
    base = {"contract": contract["symbol"], "delta": contract["delta"], "dte": contract["dte"],
            "exit_reason": ex["reason"], "exit_at": ex["condition_at"],
            "held_min": round((ex["condition_at"] - entry_at) / 60)}
    if entry is None or out is None:
        return dict(base, status="unresolved")
    m = contract["multiplier"]
    res = {}
    for h in B.HAIRCUTS:
        paid, got = entry["vwap"] * (1 + h), out["vwap"] * (1 - h)
        pnl = (got - paid) * m - 2 * R.COMMISSION_PER_SIDE
        res[f"pnl_h{int(h * 100)}"] = round(pnl, 2)
        res[f"rop_h{int(h * 100)}"] = round(pnl / (paid * m + R.COMMISSION_PER_SIDE), 4)
    return dict(base, status="filled", entry_premium=entry["vwap"], exit_premium=out["vwap"], **res)


def main(window):
    start, end = WINDOWS[window]
    daily = B.daily_by_symbol(end)
    results, days_info = [], []
    days = list(weekdays(start, end))
    for n, day in enumerate(days, 1):
        open_at, close_at = B.session_bounds(day)
        spy_min = B.minutes_for("SPY", day)
        if not [m for m in spy_min if open_at <= m["time"] < close_at]:
            continue
        spy_bars = R.five_minute_bars(spy_min, open_at, close_at)
        gate = spy_gate(spy_bars, open_at)
        spy_atr = B.R.atr14([d for d in daily["SPY"] if d["date"] < day.isoformat()])
        days_info.append({"day": day.isoformat(), "gate_down": any(v == "down" for v in gate.values()),
                          "gate_up": any(v == "up" for v in gate.values()),
                          "spy": B.classify(spy_min, open_at, close_at, spy_atr)})
        for sym in B.UNIVERSE:
            atr = R.atr14([d for d in daily.get(sym, []) if d["date"] < day.isoformat()])
            mins = B.minutes_for(sym, day)
            if atr is None or not mins:
                print("skip", sym, day, file=sys.stderr)
                continue
            session_mins = [m for m in mins if open_at <= m["time"] < close_at]
            fives = R.five_minute_bars(mins, open_at, close_at)
            info = B.classify(mins, open_at, close_at, atr)
            sigs = entries(fives, atr, open_at)
            for g in GATES:
                for ex in EXITS:
                    count, last, busy = 0, -10**9, 0
                    for s in sigs:
                        want = "down" if s["direction"] == "short" else "up"
                        if g == "spy" and gate.get(s["bar_end"]) != want:
                            continue
                        if count >= MAX_PER_DAY or s["bar_end"] < busy or s["bar_end"] - last < R.COOLDOWN_SECONDS:
                            continue
                        t = price(sym, day, s, session_mins, fives, open_at, close_at, ex)
                        count, last = count + 1, s["bar_end"]
                        busy = t.get("exit_at") or s["bar_end"]
                        results.append({"window": window, "gate": g, "exit": ex, "day": day.isoformat(),
                                        "symbol": sym, "direction": s["direction"],
                                        "time": datetime.fromtimestamp(s["bar_end"], B.ET).strftime("%H:%M"),
                                        "flags": s["flags"], "entry_px": s["facts"]["close"], "stop": s["stop"],
                                        "day_type": info["type"], "spy_day_type": days_info[-1]["spy"]["type"],
                                        "day_close": info["close"], **t})
        print(f"{n}/{len(days)} {day} rows {len(results)}", file=sys.stderr, flush=True)
    (B.OUT / f"trend_mode_{window}.json").write_text(json.dumps({"trades": results, "days": days_info}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "design")
