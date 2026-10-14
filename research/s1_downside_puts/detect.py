"""Research only: can an intraday check tell a real SPY trend day early?

No option prices. For each session (2026-03-02 .. 2026-10-13) and each check time,
every check returns 'down', 'up' or None from data available at that time. Scored
two ways:
  hit rate   - share of firings on days SPY ended as a trend day that way (hindsight
               label from backtest.classify: >= 0.5 ATR open-to-close, close in the
               outer 30% of the range)
  follow-on  - SPY move from the check time to the close, in daily ATRs, signed in the
               check's direction (what was still there to trade after the check fired)

  python research/s1_downside_puts/detect.py fetch   # fill the minute-bar cache
  python research/s1_downside_puts/detect.py         # score
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import backtest as B  # noqa: E402
from backtest import R, alpaca  # noqa: E402
from trend_mode import at_minute, weekdays  # noqa: E402

START, END = date(2026, 3, 2), date(2026, 10, 13)
BREADTH = ("AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA JPM LLY V UNH XOM MA COST HD PG JNJ WMT NFLX "
           "ABBV BAC CRM ORCL AMD KO PEP MRK CVX ADBE TMO CSCO ACN MCD WFC LIN INTU QCOM TXN IBM "
           "GE CAT AMGN DIS GS UBER NOW ISRG PFE MU").split()
EXTRA = ["SPY", "QQQ", "IWM", "VIXY"]
CHECK_TIMES = (10 * 60 + 30, 11 * 60, 12 * 60, 13 * 60, 14 * 60)
VOLUME_LOOKBACK = 20


def all_days():
    return [d for d in weekdays(START - timedelta(days=35), END)]


def fetch():
    for day in all_days():
        syms = EXTRA + (BREADTH if day >= START else [])
        alpaca.fetch_minute_bars_for_date(syms, day)
        print("fetched", day, file=sys.stderr, flush=True)


def normalize(rows):
    from datetime import datetime
    out = []
    for b in rows:
        t = int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp())
        out.append({"time": t, "end_time": t + 60, "open": b["o"], "high": b["h"], "low": b["l"],
                    "close": b["c"], "volume": b["v"]})
    return out


def session_data(day):
    o, c = B.session_bounds(day)
    raw = alpaca.fetch_minute_bars_for_date(EXTRA + (BREADTH if day >= START else []), day, cache_only=True)
    data = {}
    for sym, rows in raw.items():
        mins = [m for m in normalize(rows) if o <= m["time"] < c]
        if mins:
            data[sym] = {"mins": mins, "fives": R.five_minute_bars(mins, o, c)}
    return data


def upto(fives, t):
    return [b for b in fives if b["end"] <= t]


def side_ok(sign, close, line):
    return sign * (close - line) > 0


# ------------------------------------------------------------------ checks

def check_base(ctx, t, sign):
    """SPY >= 0.3 ATR from the open and on the same side of VWAP every bar since 10:00."""
    bs = upto(ctx["spy"], t)
    since = [b for b in bs if b["end"] >= at_minute(ctx["open_at"], 600)]
    return (sign * (bs[-1]["close"] - ctx["spy_open"]) / ctx["atr"] >= 0.3
            and all(side_ok(sign, b["close"], b["vwap"]) for b in since))


def check_breadth(ctx, t, sign, share=0.7):
    """At least `share` of the 50 large caps on the trend side of their VWAP and outside their opening range."""
    n = good = 0
    for fives in ctx["breadth"]:
        bs = upto(fives, t)
        opening = [b for b in fives if b["start"] < ctx["open_at"] + R.FIRST_BAR_AFTER]
        if not bs or len(opening) < 3:
            continue
        n += 1
        edge = min(b["low"] for b in opening) if sign < 0 else max(b["high"] for b in opening)
        if side_ok(sign, bs[-1]["close"], bs[-1]["vwap"]) and side_ok(sign, bs[-1]["close"], edge):
            good += 1
    return n >= 40 and good / n >= share


def check_volume(ctx, t, sign, ratio=1.3):
    """SPY volume so far >= ratio x its average to the same time over the prior 20 sessions."""
    if ctx["vol_avg"] is None:
        return False
    minute = (t - ctx["open_at"]) // 60
    avg = ctx["vol_avg"].get(minute)
    return bool(avg) and sum(b["volume"] for b in upto(ctx["spy"], t)) >= ratio * avg


def check_vix(ctx, t, sign):
    """VIXY moving opposite to SPY: above its VWAP and up >= 2% from the open on a down check."""
    if ctx["vixy"] is None:
        return False
    bs = upto(ctx["vixy"], t)
    if not bs:
        return False
    move = (bs[-1]["close"] - ctx["vixy"][0]["open"]) / ctx["vixy"][0]["open"]
    return side_ok(-sign, bs[-1]["close"], bs[-1]["vwap"]) and -sign * move >= 0.02


def check_aligned(ctx, t, sign):
    """SPY, QQQ and IWM all on the trend side of VWAP every bar since 10:00."""
    for fives in (ctx["spy"], ctx["qqq"], ctx["iwm"]):
        if fives is None:
            return False
        since = [b for b in upto(fives, t) if b["end"] >= at_minute(ctx["open_at"], 600)]
        if not since or not all(side_ok(sign, b["close"], b["vwap"]) for b in since):
            return False
    return True


def check_coiled(ctx, t, sign):
    """Prior day an inside day or the narrowest range of the last 7, and the base check holds."""
    return ctx["coiled"] and check_base(ctx, t, sign)


def check_afternoon(ctx, t, sign):
    """From 13:00: SPY >= 0.3 ATR from the open, beyond VWAP, and a new session extreme made after 12:00."""
    if t < at_minute(ctx["open_at"], 13 * 60):
        return False
    bs = upto(ctx["spy"], t)
    before = [b for b in bs if b["end"] <= at_minute(ctx["open_at"], 12 * 60)]
    after = [b for b in bs if b["end"] > at_minute(ctx["open_at"], 12 * 60)]
    if not before or not after:
        return False
    if sign < 0:
        new_extreme = min(b["low"] for b in after) < min(b["low"] for b in before)
    else:
        new_extreme = max(b["high"] for b in after) > max(b["high"] for b in before)
    return (new_extreme and side_ok(sign, bs[-1]["close"], bs[-1]["vwap"])
            and sign * (bs[-1]["close"] - ctx["spy_open"]) / ctx["atr"] >= 0.3)


def check_failed_bounce(ctx, t, sign):
    """After 11:00: SPY was beyond VWAP, a bar since 11:00 reached back to VWAP and closed on the trend side,
    and the latest close is past that bar's low (down; mirrored for up)."""
    bs = upto(ctx["spy"], t)
    late = [b for b in bs if b["end"] > at_minute(ctx["open_at"], 11 * 60)]
    for i, b in enumerate(late[:-1]):
        reached = b["high"] >= b["vwap"] if sign < 0 else b["low"] <= b["vwap"]
        if reached and side_ok(sign, b["close"], b["vwap"]):
            trigger = b["low"] if sign < 0 else b["high"]
            if side_ok(sign, bs[-1]["close"], trigger) and side_ok(sign, bs[-1]["close"], bs[-1]["vwap"]):
                return sign * (bs[-1]["close"] - ctx["spy_open"]) / ctx["atr"] >= 0.2
    return False


CHECKS = {
    "base (SPY 0.3 ATR + VWAP side)": check_base,
    "breadth 70%": check_breadth,
    "SPY volume 1.3x": lambda c, t, s: check_volume(c, t, s) and check_base(c, t, s),
    "VIXY confirms": lambda c, t, s: check_vix(c, t, s) and check_base(c, t, s),
    "SPY+QQQ+IWM aligned": check_aligned,
    "coiled prior day + base": check_coiled,
    "afternoon new extreme": check_afternoon,
    "failed bounce": check_failed_bounce,
    "base + breadth": lambda c, t, s: check_base(c, t, s) and check_breadth(c, t, s),
    "base + breadth + volume": lambda c, t, s: check_base(c, t, s) and check_breadth(c, t, s) and check_volume(c, t, s),
    "breadth + VIXY": lambda c, t, s: check_breadth(c, t, s) and check_vix(c, t, s),
    "2 of breadth/volume/VIXY + base": lambda c, t, s: check_base(c, t, s) and (
        check_breadth(c, t, s) + check_volume(c, t, s) + check_vix(c, t, s) >= 2),
}


# ------------------------------------------------------------------ scoring

def main():
    daily = B.daily_by_symbol(END)
    spy_daily = alpaca.fetch_daily_bars(["SPY"], date(2025, 12, 1), END)["SPY"]
    spy_daily = [{"date": r["t"][:10], "high": r["h"], "low": r["l"], "close": r["c"]} for r in spy_daily]
    vol_history: list[list[int]] = []
    results = []
    for day in all_days():
        o, c = B.session_bounds(day)
        data = session_data(day)
        if "SPY" not in data:
            continue
        cum, run = [], 0
        for m in data["SPY"]["mins"]:
            run += m["volume"]
            cum.append(run)
        if day < START:
            vol_history.append(cum)
            continue
        hist = vol_history[-VOLUME_LOOKBACK:]
        vol_avg = ({i: sum(h[min(i, len(h) - 1)] for h in hist) / len(hist) for i in range(390)}
                   if len(hist) == VOLUME_LOOKBACK else None)
        vol_history.append(cum)
        prior = [d for d in spy_daily if d["date"] < day.isoformat()]
        y, ranges = prior[-1], [d["high"] - d["low"] for d in prior[-7:]]
        coiled = (y["high"] <= prior[-2]["high"] and y["low"] >= prior[-2]["low"]) or ranges[-1] == min(ranges)
        atr = R.atr14([d for d in daily["SPY"] if d["date"] < day.isoformat()])
        info = B.classify(data["SPY"]["mins"], o, c, atr)
        ctx = {"open_at": o, "atr": atr, "spy": data["SPY"]["fives"], "spy_open": data["SPY"]["mins"][0]["open"],
               "qqq": data.get("QQQ", {}).get("fives"), "iwm": data.get("IWM", {}).get("fives"),
               "vixy": data.get("VIXY", {}).get("fives"), "vol_avg": vol_avg, "coiled": coiled,
               "breadth": [data[s]["fives"] for s in BREADTH if s in data]}
        spy_close = data["SPY"]["mins"][-1]["close"]
        row = {"day": day.isoformat(), "type": info["type"], "fired": {}}
        for name, fn in CHECKS.items():
            for side, sign in (("down", -1), ("up", 1)):
                for t_min in CHECK_TIMES:
                    t = at_minute(o, t_min)
                    if fn(ctx, t, sign):
                        px = upto(ctx["spy"], t)[-1]["close"]
                        row["fired"][f"{name}|{side}"] = {"at": t_min, "follow": round(sign * (spy_close - px) / atr, 3)}
                        break
        results.append(row)
        print(day, info["type"], len(row["fired"]), file=sys.stderr, flush=True)
    (B.OUT / "detect.json").write_text(json.dumps(results, indent=1))
    report(results)


def report(results):
    n = len(results)
    truth = {s: sum(r["type"] == f"trend_{s}" for r in results) for s in ("down", "up")}
    print(f"{n} sessions; SPY trend-down days {truth['down']}, trend-up days {truth['up']}. "
          "Each check fires at most once a day, at the first check time it holds "
          f"({', '.join(f'{m // 60}:{m % 60:02d}' for m in CHECK_TIMES)}).\n")
    for side in ("down", "up"):
        print(f"### {side}\n")
        print("| check | days fired | right | hit rate | caught | avg follow-on (ATR) | follow-on > 0 | median time |")
        print("|---|---|---|---|---|---|---|---|")
        for name in CHECKS:
            hits = [r for r in results if f"{name}|{side}" in r["fired"]]
            if not hits:
                print(f"| {name} | 0 | | | 0/{truth[side]} | | | |")
                continue
            right = sum(r["type"] == f"trend_{side}" for r in hits)
            fol = [r["fired"][f"{name}|{side}"]["follow"] for r in hits]
            times = sorted(r["fired"][f"{name}|{side}"]["at"] for r in hits)
            mt = times[len(times) // 2]
            print(f"| {name} | {len(hits)} | {right} | {right / len(hits):.0%} | {right}/{truth[side]} | "
                  f"{sum(fol) / len(fol):+.2f} | {sum(f > 0 for f in fol) / len(fol):.0%} | {mt // 60}:{mt % 60:02d} |")
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        fetch()
    elif len(sys.argv) > 1 and sys.argv[1] == "report":
        report(json.loads((B.OUT / "detect.json").read_text()))
    else:
        main()
