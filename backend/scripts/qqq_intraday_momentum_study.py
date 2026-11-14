"""QQQ intraday momentum ("noise area", Zarattini, Aziz and Barbon 2024): a settings search on 2016-2021, then one
exam of the chosen settings on 2022-2026.

Protocol, committed before any result of this rule on QQQ was computed here:
    research/qqq-intraday-momentum/protocol.json   qqq-intraday-momentum-20261114-v1
Changing a constant below makes a different study: register a new protocol id.

Each session, the noise area at a check time HH:MM is the open (or the previous close, whichever is further out) times
1 plus or minus VM x sigma, where sigma is the average absolute move from the open to HH:MM over the previous
LOOKBACK sessions. At each check time the strategy goes long above the upper band and short below the lower band; a
held position closes at a check time when price crosses its stop (and reverses when price is beyond the opposite
band), and everything closes at the session's end. Decisions use the close of the minute before the check time; fills
are at the check minute's open plus a cost a share. Every combination in GRID is scored on the search years by the
Sharpe ratio of its daily returns at 1x; the best one, alone, is then run once on the exam years.

Market data only: QQQ one-minute bars already downloaded for the QQQ opening range breakout (``bars.json.gz``, minutes
09:30 to 15:59, from ``scripts.qqq_orb_study fetch``). No network.

Run from backend:
    python -m scripts.qqq_intraday_momentum_study DATA --out ../research/qqq-intraday-momentum/results.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from itertools import product
import json
import math
from pathlib import Path
import random
import sys

from scripts import opening_breakout_study as v1
from scripts import qqq_orb_study as orb

PROTOCOL_ID = "qqq-intraday-momentum-20261114-v1"
OPEN_MINUTE = 9 * 60 + 30
LAST_MINUTE = 15 * 60 + 59  # the session's last bar; its close stands in for the 16:00 close
HALF_CLOSE_MINUTE = 12 * 60 + 59  # an early close's last regular bar
FIRST_CHECK = 10 * 60
HALF_DAYS = orb.HALF_DAYS
SEARCH = ("2016-01-04", "2021-12-31")
EXAM = ("2022-01-03", "2026-11-13")
WARMUP = 90  # sessions before the first scored day, so every lookback in GRID has its history
EXAM_PERIODS = (("first", "2022-01-03", "2023-12-31"), ("second", "2024-01-01", "2026-11-13"))
GRID = {
    "lookback": (14, 30, 60, 90),
    "vm": (0.75, 1.0, 1.25, 1.5, 2.0),
    "every": (15, 30, 60),
    "stop": ("band_vwap", "band", "opposite"),
}
PAPER = {"lookback": 14, "vm": 1.0, "every": 30, "stop": "band_vwap"}
COST = 0.01  # dollars a share each side: about a cent-wide spread crossed plus slippage
STRESS_COST = 0.02
TARGET_VOL, MAX_LEVERAGE, VOL_DAYS = 0.02, 4.0, 14  # the paper's sizing
LEVEL = 0.95
BOOTSTRAP = 2000
SEED = 20261114


@dataclass
class Day:
    day: str
    bars: dict[int, list]  # minute -> [o, h, l, c, v]
    open: float
    prev_close: float | None
    close: float  # the last regular bar's close


# ---------------------------------------------------------------- data shaping (pure)


def last_minute(day: str) -> int:
    return HALF_CLOSE_MINUTE if day in HALF_DAYS else LAST_MINUTE


def price_before(bars: dict[int, list], minute: int) -> float | None:
    """The close of the last bar before ``minute`` (the price at HH:MM:00), or None."""
    for m in range(minute - 1, OPEN_MINUTE - 1, -1):
        if m in bars:
            return bars[m][3]
    return None


def fill_at(bars: dict[int, list], minute: int, end: int) -> float | None:
    """The open of the first bar at or after ``minute`` and at or before ``end``."""
    for m in range(minute, end + 1):
        if m in bars:
            return bars[m][0]
    return None


def build_days(by_day: dict[str, list]) -> list[Day]:
    days, prev = [], None
    for d in sorted(by_day):
        end = last_minute(d)
        bars = {r[0]: r[1:] for r in by_day[d] if r[0] <= end}
        if OPEN_MINUTE not in bars:
            prev = None
            continue
        close = bars[max(bars)][3]
        days.append(Day(d, bars, bars[OPEN_MINUTE][0], prev, close))
        prev = close
    return days


def check_minutes(every: int) -> list[int]:
    return list(range(FIRST_CHECK, LAST_MINUTE, every))


def sigmas(days: list[Day], lookback: int) -> dict[str, dict[int, float]]:
    """Per full session, per check minute (every quarter hour from 10:00), the average absolute move from the open
    over the previous ``lookback`` full sessions (early closes left out of the history)."""
    minutes = check_minutes(15)
    moves: list[dict[int, float]] = []
    out = {}
    for d in days:
        if d.day in HALF_DAYS:
            continue
        if len(moves) >= lookback:
            window = moves[-lookback:]
            out[d.day] = {m: sum(w[m] for w in window) / lookback for m in minutes if all(m in w for w in window)}
        row = {}
        for m in minutes:
            p = price_before(d.bars, m)
            if p is not None:
                row[m] = abs(p / d.open - 1)
        moves.append(row)
    return out


def vwaps(d: Day) -> dict[int, float]:
    """VWAP at each check minute (every quarter hour from 10:00), from regular-session bars before it."""
    out, pv, vol = {}, 0.0, 0.0
    targets = iter(check_minutes(15))
    target = next(targets, None)
    for m in range(OPEN_MINUTE, LAST_MINUTE + 1):
        while target is not None and m == target:
            if vol > 0:
                out[target] = pv / vol
            target = next(targets, None)
        if m in d.bars:
            o, h, low, c, v = d.bars[m]
            pv += (h + low + c) / 3 * v
            vol += v
    return out


def daily_vol(days: list[Day]) -> dict[str, float]:
    """The sample standard deviation of the previous ``VOL_DAYS`` close-to-close returns, per session."""
    out, rets = {}, []
    for a, b in zip(days, days[1:]):
        if len(rets) >= VOL_DAYS:
            w = rets[-VOL_DAYS:]
            mu = sum(w) / len(w)
            out[b.day] = math.sqrt(sum((x - mu) ** 2 for x in w) / (len(w) - 1))
        rets.append(b.close / a.close - 1)
    return out


# ---------------------------------------------------------------- the rule (pure)


def trade_day(d: Day, sigma: dict[int, float], vwap: dict[int, float], vm: float, every: int, stop: str,
              cost: float) -> dict | None:
    """One session at 1x: the day's net return (fraction of the open), its trades, and how each ended."""
    if d.prev_close is None or d.day in HALF_DAYS:
        return None
    hi_ref, lo_ref = max(d.open, d.prev_close), min(d.open, d.prev_close)
    side, entry, trades, gross, paid = 0, 0.0, [], 0.0, 0.0

    def close_out(price: float, how: str):
        nonlocal side, gross, paid
        gross += side * (price - entry)
        paid += cost
        trades.append({"side": side, "how": how})
        side = 0

    for m in check_minutes(every):
        if m not in sigma:
            continue
        p = price_before(d.bars, m)
        fill = fill_at(d.bars, m, LAST_MINUTE)
        if p is None or fill is None:
            continue
        ub, lb = hi_ref * (1 + vm * sigma[m]), lo_ref * (1 - vm * sigma[m])
        v = vwap.get(m)
        # A side opens only beyond its own trailing level (band_vwap: the band and VWAP), so it never opens already
        # stopped out; after a stop the same check can open only the opposite side.
        long_level = max(ub, v) if stop == "band_vwap" and v is not None else ub
        short_level = min(lb, v) if stop == "band_vwap" and v is not None else lb
        stopped = 0
        if side != 0:
            if stop == "opposite":
                level = lb if side > 0 else ub
            else:
                level = long_level if side > 0 else short_level
            if (p < level) if side > 0 else (p > level):
                stopped = side
                close_out(fill, "stop")
        if side == 0:
            want = 1 if p > long_level else -1 if p < short_level else 0
            if want and want != stopped:
                side, entry = want, fill
                paid += cost
    if side != 0:
        close_out(d.close, "close")
    return {"day": d.day, "r": (gross - paid) / d.open, "trades": trades}


def run_combo(days: list[Day], sig: dict[str, dict[int, float]], vw: dict[str, dict[int, float]], combo: dict,
              lo: str, hi: str, cost: float = COST) -> list[dict]:
    out = []
    for d in days:
        if lo <= d.day <= hi and d.day in sig:
            t = trade_day(d, sig[d.day], vw[d.day], combo["vm"], combo["every"], combo["stop"], cost)
            if t is not None:
                out.append(t)
    return out


# ---------------------------------------------------------------- summary (pure)


def sharpe(rows: list[dict], key: str = "r") -> float | None:
    xs = [t[key] for t in rows]
    if len(xs) < 2:
        return None
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
    return None if sd == 0 else mu / sd * math.sqrt(252)


def interval(rows: list[dict], key: str, rng: random.Random) -> list[float] | None:
    groups = defaultdict(list)
    for t in rows:
        groups[t["day"][:7]].append(t[key])
    keys = sorted(groups)
    if not keys:
        return None
    draws = []
    for _ in range(BOOTSTRAP):
        values = [x for _ in keys for x in groups[keys[rng.randrange(len(keys))]]]
        draws.append(sum(values) / len(values))
    draws.sort()
    edge = int((1 - LEVEL) / 2 * len(draws))
    return [round(draws[edge] * 1e4, 3), round(draws[len(draws) - 1 - edge] * 1e4, 3)]


def bp(x: float | None) -> float | None:
    return None if x is None else round(x * 1e4, 3)


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def decide(band, periods: dict, stress: float | None) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "loses money"
    if band[0] > 0 and all(v is not None and v > 0 for v in periods.values()) and stress is not None and stress > 0:
        return "worth a paper test"
    return "no evidence either way"


def sized(rows: list[dict], vol: dict[str, float]) -> list[dict]:
    """The paper's sizing: each day's 1x return times min(4, 2% / the previous 14 days' volatility)."""
    return [{**t, "r": t["r"] * min(MAX_LEVERAGE, TARGET_VOL / vol[t["day"]])} for t in rows if vol.get(t["day"])]


def growth(rows: list[dict]) -> float | None:
    g = 1.0
    for t in sorted(rows, key=lambda t: t["day"]):
        g *= 1 + t["r"]
    return round(g, 3) if rows else None


def drawdown(rows: list[dict]) -> float | None:
    g = peak = 1.0
    worst = 0.0
    for t in sorted(rows, key=lambda t: t["day"]):
        g *= 1 + t["r"]
        peak = max(peak, g)
        worst = min(worst, g / peak - 1)
    return round(worst, 4) if rows else None


def cell(rows: list[dict]) -> dict:
    xs = [t["r"] for t in rows]
    traded = [t for t in rows if t["trades"]]
    return {"days": len(rows), "days_traded": len(traded), "mean_bp": bp(mean(xs)), "sharpe": None if sharpe(rows) is None else round(sharpe(rows), 3),
            "up_days": round(sum(x > 0 for x in xs) / len(xs), 3) if xs else None,
            "trades": sum(len(t["trades"]) for t in rows), "growth_of_1": growth(rows), "max_drawdown": drawdown(rows)}


def study(days: list[Day]) -> dict:
    vw = {d.day: vwaps(d) for d in days}
    vol = daily_vol(days)
    sig_by = {lb: sigmas(days, lb) for lb in GRID["lookback"]}
    full = [d.day for d in days if d.day not in HALF_DAYS]
    search_start = max(SEARCH[0], full[WARMUP]) if len(full) > WARMUP else SEARCH[0]
    table = []
    for lb, vm_, every, stop in product(*GRID.values()):
        combo = {"lookback": lb, "vm": vm_, "every": every, "stop": stop}
        rows = run_combo(days, sig_by[lb], vw, combo, search_start, SEARCH[1])
        table.append({**combo, "sharpe": sharpe(rows), "mean_bp": bp(mean([t["r"] for t in rows])), "days": len(rows)})
    ranked = sorted((t for t in table if t["sharpe"] is not None),
                    key=lambda t: (-t["sharpe"], t["lookback"], t["vm"], t["every"], t["stop"]))
    best = {k: ranked[0][k] for k in GRID}
    exam = run_combo(days, sig_by[best["lookback"]], vw, best, *EXAM)
    stress = run_combo(days, sig_by[best["lookback"]], vw, best, *EXAM, cost=STRESS_COST)
    periods = {name: bp(mean([t["r"] for t in exam if lo <= t["day"] <= hi])) for name, lo, hi in EXAM_PERIODS}
    band = interval(exam, "r", random.Random(SEED))
    stress_mean = bp(mean([t["r"] for t in stress]))
    paper_exam = run_combo(days, sig_by[PAPER["lookback"]], vw, PAPER, *EXAM)
    hows = defaultdict(int)
    for t in exam:
        for tr in t["trades"]:
            hows[("long " if tr["side"] > 0 else "short ") + tr["how"]] += 1
    return {
        "search": {"years": [search_start, SEARCH[1]], "combinations": len(table), "chosen": best,
                   "chosen_search": ranked[0], "top_10": ranked[:10],
                   "paper_settings_search": next(t for t in table if all(t[k] == PAPER[k] for k in GRID)),
                   "share_with_positive_sharpe": round(sum(1 for t in ranked if t["sharpe"] > 0) / len(ranked), 3),
                   "table": sorted(table, key=lambda t: (t["lookback"], t["vm"], t["every"], t["stop"]))},
        "exam": {"years": list(EXAM), "settings": best, **cell(exam), "interval_bp": band, "periods_bp": periods,
                 "mean_bp_stress_cost": stress_mean, "decision": decide(band, periods, stress_mean)},
        "descriptive": {
            "exam_exits": dict(hows),
            "exam_long_trades": sum(1 for t in exam for tr in t["trades"] if tr["side"] > 0),
            "exam_short_trades": sum(1 for t in exam for tr in t["trades"] if tr["side"] < 0),
            "exam_by_year": {y: cell([t for t in exam if t["day"][:4] == y]) for y in sorted({t["day"][:4] for t in exam})},
            "exam_with_paper_sizing": cell(sized(exam, vol)),
            "paper_settings_exam": cell(paper_exam),
            "paper_settings_exam_with_paper_sizing": cell(sized(paper_exam, vol)),
            "qqq_buy_and_hold_exam": _buy_hold(days, *EXAM),
        },
    }


def _buy_hold(days: list[Day], lo: str, hi: str) -> dict | None:
    inside = [d for d in days if lo <= d.day <= hi]
    if not inside:
        return None
    rows = [{"day": inside[0].day, "r": inside[0].close / inside[0].open - 1, "trades": []}]
    rows += [{"day": b.day, "r": b.close / a.close - 1, "trades": []} for a, b in zip(inside, inside[1:])]
    return {"growth_of_1": round(inside[-1].close / inside[0].open, 3), "max_drawdown": drawdown(rows),
            "sharpe": None if sharpe(rows) is None else round(sharpe(rows), 3)}


def run(bars_path: Path, out: Path | None = None) -> dict:
    by_day = v1.load(bars_path)
    days = build_days({d: rows for d, rows in by_day.items() if SEARCH[0] <= d <= EXAM[1]})
    results = {"protocol_id": PROTOCOL_ID, **study(days)}
    if out is not None:
        out.write_text(json.dumps(results, indent=2) + "\n")
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data", type=Path, help="the folder holding bars.json.gz from scripts.qqq_orb_study fetch")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    results = run(args.data / "bars.json.gz", args.out)
    print(json.dumps({k: results[k] for k in ("protocol_id", "exam")}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
