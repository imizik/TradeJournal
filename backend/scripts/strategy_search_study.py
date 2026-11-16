"""Four strategy families, each searched over a settings grid on 2016-2021 and its single best setting examined once on
2022-2026 (one exam a family, at 99% because there are four).

Protocol, committed before any result of these rules on these ETFs was computed here:
    research/strategy-search/protocol.json   strategy-search-20261115-v1
Changing a constant below makes a different study: register a new protocol id.

Families:
- ``etf_momentum``: the noise-area intraday momentum rule (``scripts.qqq_intraday_momentum_study``, which passed on QQQ)
  on 13 other ETFs, one equal-weight book, the same 180-setting grid.
- ``dip_buy``: buy an ETF at the close after a short-term oversold reading (RSI) while above a trend average, sell on
  the bounce or after a time limit; 14 ETFs, one equal-weight book, 180 settings.
- ``trend_switch``: hold QQQ while its close is above a moving average (with a buffer), else cash; 48 settings; judged on
  Sharpe ratio against holding QQQ.
- ``gap``: fade or follow large opening gaps on 13 ETFs, out at a set time; one equal-weight book, 48 settings.

Market data only (``scripts.strategy_search_data``); the data stays outside the repository. No network.

Run from backend:
    python -m scripts.strategy_search_study DATA --out ../research/strategy-search/results.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import product
import json
import math
from pathlib import Path
import random
import sys

from scripts import opening_breakout_study as v1
from scripts import qqq_intraday_momentum_study as im
from scripts import strategy_search_data as data

PROTOCOL_ID = "strategy-search-20261115-v1"
SEARCH = ("2016-01-04", "2021-12-31")
EXAM = ("2022-01-03", "2026-11-13")
EXAM_PERIODS = (("first", "2022-01-03", "2023-12-31"), ("second", "2024-01-01", "2026-11-13"))
LEVEL = 0.99
BOOTSTRAP = 2000
SEED = 20261115
DAILY_COST, DAILY_STRESS = 0.0002, 0.0005  # a side, as a fraction of price, for close-to-close daily trades
MINUTE_COST, MINUTE_STRESS = im.COST, im.STRESS_COST  # dollars a share each side, intraday

GRIDS = {
    "etf_momentum": im.GRID,
    "dip_buy": {"rsi": (2, 3), "below": (5, 10, 15, 20, 25), "trend": (0, 100, 200), "exit_sma": (3, 5, 10),
                "max_days": (5, 10)},
    "trend_switch": {"sma": (20, 50, 100, 150, 200, 250), "buffer": (0.0, 0.01, 0.02, 0.03), "check": ("daily", "weekly")},
    "gap": {"gap_atr": (0.25, 0.5, 0.75, 1.0), "direction": ("fade", "follow"), "entry": (571, 600),
            "exit": (660, 720, 959)},
}


# ---------------------------------------------------------------- shared statistics (pure)


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def sharpe(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))
    return None if sd == 0 else mu / sd * math.sqrt(252)


def month_blocks(days: list[str]) -> list[list[int]]:
    groups = defaultdict(list)
    for i, d in enumerate(days):
        groups[d[:7]].append(i)
    return [groups[k] for k in sorted(groups)]


def interval(stat, days: list[str], rng: random.Random) -> list[float] | None:
    """Month-block bootstrap percentile interval of ``stat(indices)`` at ``LEVEL``."""
    blocks = month_blocks(days)
    if not blocks:
        return None
    draws = []
    for _ in range(BOOTSTRAP):
        idx = [i for _ in blocks for i in blocks[rng.randrange(len(blocks))]]
        value = stat(idx)
        if value is not None:
            draws.append(value)
    if not draws:
        return None
    draws.sort()
    edge = int((1 - LEVEL) / 2 * len(draws))
    return [round(draws[edge], 4), round(draws[len(draws) - 1 - edge], 4)]


def decide(band, periods: dict, stress) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "loses money"
    if band[0] > 0 and all(v is not None and v > 0 for v in periods.values()) and stress is not None and stress > 0:
        return "worth a paper test"
    return "no evidence either way"


def growth(xs: list[float]) -> float | None:
    g = 1.0
    for x in xs:
        g *= 1 + x
    return round(g, 3) if xs else None


def drawdown(xs: list[float]) -> float | None:
    g = peak = 1.0
    worst = 0.0
    for x in xs:
        g *= 1 + x
        peak = max(peak, g)
        worst = min(worst, g / peak - 1)
    return round(worst, 4) if xs else None


def book_cell(series: dict[str, float]) -> dict:
    days = sorted(series)
    xs = [series[d] for d in days]
    s = sharpe(xs)
    return {"days": len(xs), "mean_bp": None if not xs else round(mean(xs) * 1e4, 3), "sharpe": None if s is None else round(s, 3),
            "growth_of_1": growth(xs), "max_drawdown": drawdown(xs)}


def by_year(series: dict[str, float]) -> dict:
    return {y: book_cell({d: r for d, r in series.items() if d[:4] == y}) for y in sorted({d[:4] for d in series})}


def window(series: dict[str, float], lo: str, hi: str) -> dict[str, float]:
    return {d: r for d, r in series.items() if lo <= d <= hi}


def mean_exam(series: dict[str, float], stress: dict[str, float]) -> dict:
    """The exam for the return families: mean daily book return in bp, its interval, periods and the stress mean."""
    days = sorted(series)
    xs = [series[d] for d in days]
    band = interval(lambda idx: sum(xs[i] for i in idx) / len(idx) * 1e4, days, random.Random(SEED))
    periods = {n: None if not (w := [series[d] for d in days if lo <= d <= hi]) else round(mean(w) * 1e4, 3)
               for n, lo, hi in EXAM_PERIODS}
    stress_mean = round(mean(list(stress.values())) * 1e4, 3) if stress else None
    return {**book_cell(series), "interval_bp": band, "periods_bp": periods, "mean_bp_stress_cost": stress_mean,
            "decision": decide(band, periods, stress_mean)}


def book(per_symbol: dict[str, dict[str, float]]) -> dict[str, float]:
    """An equal-weight book: each sleeve holds 1/N of it for the N symbols, so a sleeve with no trade, or with no data
    that day, counts as 0 (the denominator is fixed)."""
    total = defaultdict(float)
    for series in per_symbol.values():
        for d, r in series.items():
            total[d] += r
    n = len(per_symbol)
    return {d: v / n for d, v in total.items()}


def choose(table: list[dict], grid: dict) -> list[dict]:
    """The table ranked by search Sharpe, best first; ties broken by each setting's position in the grid."""
    return sorted((t for t in table if t["sharpe"] is not None),
                  key=lambda t: (-t["sharpe"], *(grid[k].index(t[k]) for k in grid)))


# ---------------------------------------------------------------- family 1: intraday momentum on 13 ETFs


QQQ_LIKE = ("SPY", "XLK", "SMH")  # the ETFs that move most like QQQ intraday (the rule already passed on QQQ)


def momentum_family(all_days: dict[str, list[im.Day]]) -> dict:
    prepared = {}
    for symbol, days in all_days.items():
        days = [d for d in days if SEARCH[0] <= d.day <= EXAM[1]]
        prepared[symbol] = (days, {d.day: im.vwaps(d) for d in days}, {lb: im.sigmas(days, lb) for lb in im.GRID["lookback"]})
    starts = []
    for days, _, _ in prepared.values():
        full = [d.day for d in days if d.day not in im.HALF_DAYS]
        if len(full) > im.WARMUP:
            starts.append(full[im.WARMUP])
    start = max([SEARCH[0], *starts])

    def run(combo, lo, hi, cost=MINUTE_COST):
        sleeves = {}
        for symbol, (days, vw, sig) in prepared.items():
            rows = im.run_combo(days, sig[combo["lookback"]], vw, combo, lo, hi, cost)
            sleeves[symbol] = {t["day"]: t["r"] for t in rows}
        return book(sleeves), sleeves

    table = []
    for values in product(*im.GRID.values()):
        combo = dict(zip(im.GRID, values))
        series, _ = run(combo, start, SEARCH[1])
        table.append({**combo, "sharpe": sharpe([series[d] for d in sorted(series)]),
                      "mean_bp": round(mean(list(series.values())) * 1e4, 3) if series else None})
    ranked = choose(table, im.GRID)
    best = {k: ranked[0][k] for k in im.GRID}
    exam, sleeves = run(best, *EXAM)
    stress, _ = run(best, *EXAM, cost=MINUTE_STRESS)
    paper, _ = run(im.PAPER, *EXAM)
    return {"search": _search_summary(table, ranked, best, start), "exam": {"settings": best, **mean_exam(exam, stress)},
            "descriptive": {"exam_by_year": by_year(exam),
                            "exam_by_symbol": {s: book_cell(v) for s, v in sorted(sleeves.items())},
                            "exam_without_qqq_like": book_cell(book({k: v for k, v in sleeves.items() if k not in QQQ_LIKE})),
                            "paper_settings_exam": book_cell(paper)}}


# ---------------------------------------------------------------- family 2: dip buying on 14 ETFs (daily)


def rsi(closes: list[float], n: int) -> list[float | None]:
    """Wilder's RSI over ``n`` closes; None until it has ``n`` changes."""
    out: list[float | None] = [None] * len(closes)
    gain = loss = 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        g, lo = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            gain += g / n
            loss += lo / n
            if i < n:
                continue
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + lo) / n
        out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def sma(closes: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    run = 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= n:
            run -= closes[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def dip_sleeve(rows: list[list], combo: dict, cost: float, held_days: set | None = None) -> dict[str, float]:
    """One ETF's daily returns (as a fraction of the sleeve) under the dip rule: decide at each close, trade at it.
    ``held_days`` (when given) collects the days the sleeve held the ETF through the session."""
    days = [r[0] for r in rows]
    closes = [r[4] for r in rows]
    r_ = rsi(closes, combo["rsi"])
    trend = sma(closes, combo["trend"]) if combo["trend"] else [0.0] * len(closes)
    exit_ma = sma(closes, combo["exit_sma"])
    out, held, age = {}, False, 0
    for i in range(1, len(rows)):
        day_r = closes[i] / closes[i - 1] - 1 if held else 0.0
        if held:
            if held_days is not None:
                held_days.add(days[i])
            age += 1
            if (exit_ma[i] is not None and closes[i] > exit_ma[i]) or age >= combo["max_days"]:
                held, day_r = False, day_r - cost
        elif r_[i] is not None and trend[i] is not None and r_[i] < combo["below"] and closes[i] > trend[i]:
            held, age, day_r = True, 0, -cost
        out[days[i]] = day_r
    return out


def dip_family(daily: dict[str, list]) -> dict:
    def run(combo, lo, hi, cost=DAILY_COST):
        sleeves = {s: window(dip_sleeve(rows, combo, cost), lo, hi) for s, rows in daily.items()}
        return book(sleeves)

    def excess(combo, lo, hi, cost=DAILY_COST):
        """Exposure-matched: each sleeve's return minus its own ETF's return times the share of exam days that sleeve
        held it, so being invested in rising ETFs earns nothing by itself."""
        sleeves, invested = {}, {}
        for s, rows in daily.items():
            held: set = set()
            r = window(dip_sleeve(rows, combo, cost, held), lo, hi)
            ret = window({rows[i][0]: rows[i][4] / rows[i - 1][4] - 1 for i in range(1, len(rows))}, lo, hi)
            share = len([d for d in held if lo <= d <= hi]) / len(r) if r else 0.0
            sleeves[s] = {d: r[d] - share * ret.get(d, 0.0) for d in r}
            invested[s] = round(share, 3)
        return book(sleeves), invested

    keys = list(GRIDS["dip_buy"])
    table = []
    for values in product(*GRIDS["dip_buy"].values()):
        combo = dict(zip(keys, values))
        series = run(combo, *SEARCH)
        table.append({**combo, "sharpe": sharpe([series[d] for d in sorted(series)]),
                      "mean_bp": round(mean(list(series.values())) * 1e4, 3) if series else None})
    ranked = choose(table, GRIDS["dip_buy"])
    best = {k: ranked[0][k] for k in keys}
    exam, invested = excess(best, *EXAM)
    stress, _ = excess(best, *EXAM, cost=DAILY_STRESS)
    raw_exam = run(best, *EXAM)
    hold = book({s: window({rows[i][0]: rows[i][4] / rows[i - 1][4] - 1 for i in range(1, len(rows))}, *EXAM)
                 for s, rows in daily.items()})
    return {"search": _search_summary(table, ranked, best, SEARCH[0]), "exam": {"settings": best, **mean_exam(exam, stress)},
            "descriptive": {"exam_by_year_excess": by_year(exam), "exam_book_returns": book_cell(raw_exam),
                            "exam_book_by_year": by_year(raw_exam), "equal_weight_buy_and_hold_exam": book_cell(hold),
                            "share_of_exam_days_held_by_etf": invested}}


# ---------------------------------------------------------------- family 3: trend switch on QQQ (daily)


def switch_series(rows: list[list], combo: dict, cost: float) -> tuple[dict[str, float], dict[str, float]]:
    """(strategy daily returns, QQQ daily returns): decide at each close (weekly: the week's last session), hold the
    next session's close-to-close return while long; cash earns nothing."""
    days = [r[0] for r in rows]
    closes = [r[4] for r in rows]
    ma = sma(closes, combo["sma"])
    strat, hold, long_ = {}, {}, False
    for i in range(1, len(rows)):
        ret = closes[i] / closes[i - 1] - 1
        r = ret if long_ else 0.0
        last_of_week = i + 1 >= len(rows) or _week(days[i + 1]) != _week(days[i])
        if ma[i] is not None and (combo["check"] == "daily" or last_of_week):
            if not long_ and closes[i] > ma[i] * (1 + combo["buffer"]):
                long_, r = True, r - cost
            elif long_ and closes[i] < ma[i] * (1 - combo["buffer"]):
                long_, r = False, r - cost
        strat[days[i]], hold[days[i]] = r, ret
    return strat, hold


def _week(day: str) -> tuple[int, int]:
    from datetime import date
    y, w, _ = date.fromisoformat(day).isocalendar()
    return y, w


def sharpe_gap_exam(strat: dict[str, float], hold: dict[str, float], stress: dict[str, float]) -> dict:
    days = sorted(strat)
    s, h, st = [strat[d] for d in days], [hold[d] for d in days], [stress[d] for d in days]

    def gap(idx, a=s):
        x, y = sharpe([a[i] for i in idx]), sharpe([h[i] for i in idx])
        return None if x is None or y is None else x - y
    band = interval(gap, days, random.Random(SEED))
    periods = {}
    for n, lo, hi in EXAM_PERIODS:
        idx = [i for i, d in enumerate(days) if lo <= d <= hi]
        g = gap(idx)
        periods[n] = None if g is None else round(g, 4)
    full = gap(list(range(len(days))))
    stress_gap = gap(list(range(len(days))), st)
    return {"sharpe_minus_buy_and_hold": None if full is None else round(full, 4), "interval": band, "periods": periods,
            "stress_sharpe_minus_buy_and_hold": None if stress_gap is None else round(stress_gap, 4),
            "decision": decide(band, periods, stress_gap), **{f"strategy_{k}": v for k, v in book_cell(strat).items()},
            **{f"buy_and_hold_{k}": v for k, v in book_cell(hold).items()}}


def trend_family(daily: dict[str, list]) -> dict:
    rows = daily["QQQ"]
    keys = list(GRIDS["trend_switch"])
    table = []
    for values in product(*GRIDS["trend_switch"].values()):
        combo = dict(zip(keys, values))
        strat, _ = switch_series(rows, combo, DAILY_COST)
        w = window(strat, *SEARCH)
        table.append({**combo, "sharpe": sharpe([w[d] for d in sorted(w)]), "mean_bp": round(mean(list(w.values())) * 1e4, 3) if w else None})
    ranked = choose(table, GRIDS["trend_switch"])
    best = {k: ranked[0][k] for k in keys}
    strat, hold = switch_series(rows, best, DAILY_COST)
    stress, _ = switch_series(rows, best, DAILY_STRESS)
    strat, hold, stress = (window(x, *EXAM) for x in (strat, hold, stress))
    levered = {k: book_cell({d: k * r for d, r in strat.items()}) for k in (2, 3)}
    levered_hold = {k: book_cell({d: k * r for d, r in hold.items()}) for k in (2, 3)}
    return {"search": _search_summary(table, ranked, best, SEARCH[0]),
            "exam": {"settings": best, **sharpe_gap_exam(strat, hold, stress)},
            "descriptive": {"exam_by_year_strategy": by_year(strat), "exam_by_year_buy_and_hold": by_year(hold),
                            "levered_switch_exam": {f"{k}x": v for k, v in levered.items()},
                            "levered_buy_and_hold_exam": {f"{k}x": v for k, v in levered_hold.items()},
                            "share_of_days_with_a_return": round(sum(1 for d in strat if strat[d] != 0) / len(strat), 3) if strat else None}}


# ---------------------------------------------------------------- family 4: opening gaps on 13 ETFs


def atrs(days: list[im.Day]) -> dict[str, float]:
    """Per full session, the average (high - low) / close of the previous 14 full sessions' regular hours."""
    out, ranges = {}, []
    for d in days:
        if d.day in im.HALF_DAYS:
            continue
        if len(ranges) >= 14:
            out[d.day] = sum(ranges[-14:]) / 14
        ranges.append((max(b[1] for b in d.bars.values()) - min(b[2] for b in d.bars.values())) / d.close)
    return out


def gap_sleeve(days: list[im.Day], atr: dict[str, float], combo: dict, cost: float, lo: str, hi: str) -> dict[str, float]:
    """One ETF's daily returns under the gap rule (0 on days without a trade), full sessions only."""
    out = {}
    for d in days:
        if not (lo <= d.day <= hi) or d.day not in atr or not d.prev_close:
            continue
        gap = d.open / d.prev_close - 1
        r = 0.0
        if abs(gap) >= combo["gap_atr"] * atr[d.day]:
            side = (-1 if gap > 0 else 1) if combo["direction"] == "fade" else (1 if gap > 0 else -1)
            entry = im.fill_at(d.bars, combo["entry"], im.LAST_MINUTE)
            exit_ = d.close if combo["exit"] == im.LAST_MINUTE else im.fill_at(d.bars, combo["exit"], im.LAST_MINUTE)
            if entry is not None and exit_ is not None:
                r = (side * (exit_ - entry) - 2 * cost) / d.open
        out[d.day] = r
    return out


def gap_family(all_days: dict[str, list[im.Day]]) -> dict:
    prepared = {s: (days, atrs(days)) for s, days in all_days.items()}
    keys = list(GRIDS["gap"])

    def run(combo, lo, hi, cost=MINUTE_COST):
        return book({s: gap_sleeve(days, atr, combo, cost, lo, hi) for s, (days, atr) in prepared.items()})

    table = []
    for values in product(*GRIDS["gap"].values()):
        combo = dict(zip(keys, values))
        series = run(combo, *SEARCH)
        table.append({**combo, "sharpe": sharpe([series[d] for d in sorted(series)]),
                      "mean_bp": round(mean(list(series.values())) * 1e4, 3) if series else None})
    ranked = choose(table, GRIDS["gap"])
    best = {k: ranked[0][k] for k in keys}
    exam = run(best, *EXAM)
    stress = run(best, *EXAM, cost=MINUTE_STRESS)
    start = min((d for days, atr in prepared.values() for d in atr if d >= SEARCH[0]), default=SEARCH[0])
    return {"search": _search_summary(table, ranked, best, start), "exam": {"settings": best, **mean_exam(exam, stress)},
            "descriptive": {"exam_by_year": by_year(exam),
                            "share_of_days_traded": round(sum(1 for v in exam.values() if v != 0) / len(exam), 3) if exam else None}}


# ---------------------------------------------------------------- run


def _search_summary(table, ranked, best, start) -> dict:
    return {"start": start, "combinations": len(table), "chosen": best, "chosen_search": ranked[0], "top_10": ranked[:10],
            "share_with_positive_sharpe": round(sum(1 for t in ranked if t["sharpe"] > 0) / len(ranked), 3) if ranked else None}


def run(root: Path, out: Path | None = None) -> dict:
    daily = v1.load(root / "daily.json.gz")
    daily = {s: [r for r in rows if r[0] <= EXAM[1]] for s, rows in daily.items()}
    all_days = {}
    for symbol in data.INTRADAY:  # one ETF's raw minutes in memory at a time
        raw = v1.load(root / "minutes" / f"{symbol}.json.gz")
        all_days[symbol] = im.build_days({d: rows for d, rows in raw.items() if d <= EXAM[1]})
        del raw
    results = {"protocol_id": PROTOCOL_ID, "families": {
        "etf_momentum": momentum_family(all_days),
        "dip_buy": dip_family(daily),
        "trend_switch": trend_family(daily),
        "gap": gap_family(all_days),
    }}
    if out is not None:
        out.write_text(json.dumps(results, indent=2) + "\n")
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    results = run(args.data, args.out)
    print(json.dumps({f: r["exam"] for f, r in results["families"].items()}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
