"""QQQ 5-minute opening range breakout (Zarattini and Aziz, 2023) with fills from the consolidated tape, 2016-2026.

Protocol, committed before any result of this rule on QQQ was computed:
    research/qqq-orb/protocol.json   qqq-orb-20261114-v1
Changing a constant below makes a different study: register a new protocol id.

The first five minutes decide the direction; the trade enters at 09:35 with its stop at the far end of the first
candle and a target at 10 R, else it leaves at the close. Fills reuse the top-5 study's tape machinery
(``scripts.opening_breakout_top5_study``): ``fetch`` asks Alpaca's SIP trades and quotes only the questions the rules
ask and saves every answer in the session file; ``run`` replays the same functions from the saved answers, so the run
reads no market data. Market data only (no journal, no personal data); the data stays outside the repository.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.qqq_orb_study fetch DATA --env-file .env
    python -m scripts.qqq_orb_study run DATA --out ../research/qqq-orb/results.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import random
import sys

from scripts import opening_breakout_study as v1
from scripts import opening_breakout_top5_study as t5

PROTOCOL_ID = "qqq-orb-20261114-v1"
SYMBOL = "QQQ"
START, END = date(2016, 1, 4), date(2026, 11, 13)
PERIODS = (("first", "2016-01-04", "2019-12-31"), ("second", "2020-01-01", "2023-02-17"),
           ("third", "2023-02-21", "2026-11-13"))
OPEN_MINUTE = 9 * 60 + 30
FIRST = tuple(range(OPEN_MINUTE, OPEN_MINUTE + 5))  # 09:30 .. 09:34
ENTRY_MINUTE = OPEN_MINUTE + 5  # 09:35
LAST_STOP_MINUTE = 15 * 60 + 58  # stops and the target are watched until 15:58:59
EXIT_MINUTE = 15 * 60 + 59  # the close order goes at 15:59:00
# Early closes (13:00) from the earlier studies' lists; none falls in 2026 before END. Alpaca's minute bars include
# after-hours trading, so a bar after 13:00 does not show a full session.
HALF_DAYS = {d.isoformat() for d in t5.HALF_DAYS | v1.HALF_DAYS}
TARGET_R = 10
THROUGH = 0.01  # the target's limit fills only on a trade a cent beyond it
EXTRA_CENT = 0.01
LEVEL = 0.99
BOOTSTRAP = 2000
SEED = 20261114
DELAY = t5.DELAY


# ---------------------------------------------------------------- rules (pure)


def setup(bars: dict[int, list]) -> dict:
    """The day's trade from its minute bars (minute -> [o, h, l, c, v]), or why there is none."""
    if any(m not in bars for m in (*FIRST, ENTRY_MINUTE)):
        return {"status": "missing bars"}
    o, c = bars[FIRST[0]][0], bars[FIRST[-1]][3]
    if c == o:
        return {"status": "doji"}
    side = 1 if c > o else -1
    high, low = max(bars[m][1] for m in FIRST), min(bars[m][2] for m in FIRST)
    p = bars[ENTRY_MINUTE][0]
    stop = low if side > 0 else high
    risk = (p - stop) * side
    if risk <= 0:
        return {"status": "no room"}
    # Prices are cents, but a float target carries rounding error that could shift the one-cent-through rule;
    # both levels are rounded to the cent (a sub-penny P gives a target rounded to the nearest cent).
    target = round(p + side * TARGET_R * risk, 2)
    return {"status": "setup", "side": side, "p": p, "stop": stop, "risk": risk, "target": target,
            "through": round(target + side * THROUGH, 2)}


def _reaches_stop(bar: list, s: dict) -> bool:
    return bar[2] <= s["stop"] if s["side"] > 0 else bar[1] >= s["stop"]


def _reaches_target(bar: list, s: dict) -> bool:
    level = s["through"]
    return bar[1] >= level if s["side"] > 0 else bar[2] <= level


def tape_trade(s: dict, bars: dict[int, list], src, day: str, target: bool = True) -> dict:
    """One session's trade filled from the tape (``src``: through / quote_at, as in the top-5 study)."""
    side, stop, risk = s["side"], s["stop"], s["risk"]
    t0 = t5.minute_ns(day, ENTRY_MINUTE)
    fq = src.quote_at(SYMBOL, t0 + DELAY)
    if not t5.valid_quote(fq):
        return {"day": day, "side": side, "status": "no fill quote"}
    fill = fq[2] if side > 0 else fq[1]
    start = t0 + DELAY
    windows = [(start, t5.minute_ns(day, ENTRY_MINUTE + 1), True, target)]
    for m in sorted(bars):
        if ENTRY_MINUTE < m <= LAST_STOP_MINUTE:
            hits_stop, hits_target = _reaches_stop(bars[m], s), target and _reaches_target(bars[m], s)
            if hits_stop or hits_target:
                windows.append((t5.minute_ns(day, m), t5.minute_ns(day, m + 1), hits_stop, hits_target))
    out = how = None
    for lo, hi, look_stop, look_target in windows:
        s_hit = t5._first_tape_trade(src, SYMBOL, lo, hi, stop, -side) if look_stop else None
        t_hit = t5._first_tape_trade(src, SYMBOL, lo, hi, s["through"], side) if look_target else None
        if t_hit is not None and (s_hit is None or t_hit < s_hit):
            out, how = s["target"], "target"
            break
        if s_hit is not None:
            sq = src.quote_at(SYMBOL, s_hit + DELAY)
            out, how = ((sq[1] if side > 0 else sq[2]), "stop") if t5.valid_quote(sq) else (stop, "stop at level")
            break
    if out is None:
        eq = src.quote_at(SYMBOL, t5.minute_ns(day, EXIT_MINUTE) + DELAY)
        if t5.valid_quote(eq):
            out, how = (eq[1] if side > 0 else eq[2]), "close"
        else:
            last = max(m for m in bars if m <= EXIT_MINUTE)
            out, how = bars[last][3], "close from bar"
    gross = (out - fill) * side
    return {"day": day, "side": side, "status": "traded", "risk": risk, "fill": fill, "exit": out, "how": how,
            "r": gross / risk, "r_extra_cent": (gross - 2 * EXTRA_CENT) / risk, "spread_r": (fq[2] - fq[1]) / risk}


def bar_trade(s: dict, bars: dict[int, list], day: str) -> dict:
    """The paper's version on one-minute bars: entry at P, levels as orders, stop first when a bar reaches both."""
    side, p = s["side"], s["p"]
    out = how = None
    for m in sorted(bars):
        if ENTRY_MINUTE <= m <= LAST_STOP_MINUTE:
            _, h, low, _, _ = bars[m]
            if (low <= s["stop"]) if side > 0 else (h >= s["stop"]):
                out, how = s["stop"], "stop"
                break
            if (h >= s["target"]) if side > 0 else (low <= s["target"]):
                out, how = s["target"], "target"
                break
    if out is None:
        out, how = bars[max(m for m in bars if m <= EXIT_MINUTE)][3], "close"
    return {"day": day, "side": side, "how": how, "r": (out - p) * side / s["risk"]}


# ---------------------------------------------------------------- summary (pure)


def month(t: dict) -> str:
    return t["day"][:7]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


def interval(trades: list[dict], key: str, rng: random.Random) -> list[float] | None:
    groups = defaultdict(list)
    for t in trades:
        groups[month(t)].append(t[key])
    keys = sorted(groups)
    if not keys:
        return None
    draws = []
    for _ in range(BOOTSTRAP):
        values = [x for _ in keys for x in groups[keys[rng.randrange(len(keys))]]]
        draws.append(sum(values) / len(values))
    draws.sort()
    edge = int((1 - LEVEL) / 2 * len(draws))
    return [round(draws[edge], 4), round(draws[len(draws) - 1 - edge], 4)]


def period_means(trades: list[dict], key: str = "r") -> dict:
    return {name: _r(mean([t[key] for t in trades if lo <= t["day"] <= hi])) for name, lo, hi in PERIODS}


def decide(band: list[float] | None, periods: dict, extra_cent: float | None) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "loses money"
    if band[0] > 0 and all(v is not None and v > 0 for v in periods.values()) and extra_cent is not None and extra_cent > 0:
        return "worth a paper test"
    return "no evidence either way"


def cell(trades: list[dict], key: str = "r") -> dict:
    vals = sorted(t[key] for t in trades)
    if not vals:
        return {"trades": 0}
    return {"trades": len(vals), "mean_r": round(sum(vals) / len(vals), 4), "median_r": round(vals[len(vals) // 2], 4),
            "win_rate": round(sum(v > 0 for v in vals) / len(vals), 3)}


def summarize(tape: list[dict], no_target: list[dict], bars: list[dict], counts: dict) -> dict:
    traded = [t for t in tape if t["status"] == "traded"]
    periods = period_means(traded)
    extra = _r(mean([t["r_extra_cent"] for t in traded]))
    band = interval(traded, "r", random.Random(SEED))
    by_month = defaultdict(float)
    for t in traded:
        by_month[month(t)] += t["r"]
    best = sorted(by_month, key=lambda k: -by_month[k])[:max(1, len(by_month) // 100)]
    ranked = sorted(traded, key=lambda t: t["risk"])
    fifths = [ranked[len(ranked) * k // 5:len(ranked) * (k + 1) // 5] for k in range(5)] if ranked else []
    spreads = sorted(t["spread_r"] for t in traded)
    return {
        "test": {**cell(traded), "interval_r": band, "periods_r": periods, "mean_r_extra_cent": extra,
                 "decision": decide(band, periods, extra)},
        "descriptive": {
            **counts, "no_fill_quote": sum(1 for t in tape if t["status"] == "no fill quote"),
            "exits": {k: sum(1 for t in traded if t["how"] == k)
                      for k in ("target", "stop", "stop at level", "close", "close from bar")},
            "long_side": cell([t for t in traded if t["side"] > 0]),
            "short_side": cell([t for t in traded if t["side"] < 0]),
            "by_year": {y: cell([t for t in traded if t["day"][:4] == y]) for y in sorted({t["day"][:4] for t in traded})},
            "without_best_1pct_months": cell([t for t in traded if month(t) not in best]),
            "paper_version_on_bars": cell(bars),
            "tape_without_target": cell([t for t in no_target if t["status"] == "traded"]),
            "entry_spread_r": {"mean": _r(mean(spreads)), "median": _r(spreads[len(spreads) // 2]) if spreads else None},
            "by_risk_fifth": [{"risk_cents": [round(100 * f[0]["risk"], 1), round(100 * f[-1]["risk"], 1)], **cell(f)}
                              for f in fifths if f]}}


# ---------------------------------------------------------------- data


def sessions(bars_by_day: dict[str, list]) -> list[str]:
    """Full sessions in the window (early closes left out)."""
    return sorted(d for d in bars_by_day if START.isoformat() <= d <= END.isoformat() and d not in HALF_DAYS)


def run(root: Path, out: Path | None = None) -> dict:
    by_day = v1.load(root / "bars.json.gz")
    days = sessions(by_day)
    tape, no_target, bars_out = [], [], []
    counts = {"sessions": len(days), "early_closes_left_out": sum(1 for d in by_day if START.isoformat() <= d <= END.isoformat()) - len(days),
              "missing_bars": 0, "doji": 0, "no_room": 0}
    for day in days:
        bars = {r[0]: r[1:] for r in by_day[day]}
        s = setup(bars)
        if s["status"] != "setup":
            counts[s["status"].replace(" ", "_")] += 1
            continue
        path = root / "session" / f"{day}.json.gz"
        if not path.exists():
            raise SystemExit(f"missing session file {day}: run fetch first")
        src = t5.Replay(v1.load(path)["ticks"])
        tape.append(tape_trade(s, bars, src, day))
        no_target.append(tape_trade(s, bars, src, day, target=False))
        bars_out.append(bar_trade(s, bars, day))
    results = {"protocol_id": PROTOCOL_ID, **summarize(tape, no_target, bars_out, counts)}
    (root / "results.json").write_text(json.dumps(results, indent=2))
    if out is not None:
        out.write_text(json.dumps(results, indent=2) + "\n")
    return results


def fetch(root: Path, env_file: Path, per_minute: int = 150) -> None:
    import httpx
    from scripts.radar_long_history import alpaca_bars, get_json, keys_from
    _, headers = keys_from(env_file)
    with httpx.Client(timeout=90, event_hooks={"request": [t5.Throttle(per_minute)]}) as client:
        bars_path = root / "bars.json.gz"
        if not bars_path.exists():
            by_day: dict[str, list] = defaultdict(list)
            for year in range(START.year, END.year + 1):
                last = min(date(year, 12, 31), END)  # SIP refuses a window that reaches past the recent hours
                rows = alpaca_bars(client, headers, [SYMBOL], "1Min", f"{year}-01-01T00:00:00Z",
                                   f"{last.isoformat()}T23:59:59Z", "raw").get(SYMBOL, [])
                for b in rows:
                    day, minute = v1.minute_of(b["t"])
                    if OPEN_MINUTE <= minute <= EXIT_MINUTE:
                        by_day[day].append([minute, b["o"], b["h"], b["l"], b["c"], b["v"]])
                print(f"bars {year}: {len(rows)}", flush=True)
            v1.save(bars_path, dict(by_day))
        by_day = v1.load(bars_path)
        get = lambda p, params: get_json(client, "https://data.alpaca.markets" + p, params, headers)  # noqa: E731
        for day in sessions(by_day):
            path = root / "session" / f"{day}.json.gz"
            if path.exists():
                continue
            bars = {r[0]: r[1:] for r in by_day[day]}
            s = setup(bars)
            log: dict = {}
            if s["status"] == "setup":
                recorder = t5.Recorder(get, log)
                tape_trade(s, bars, recorder, day)
                tape_trade(s, bars, recorder, day, target=False)
            v1.save(path, {"ticks": log})
            print(f"session {day}: {len(log)} tape answers", flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("data", type=Path)
    f.add_argument("--env-file", type=Path, required=True)
    f.add_argument("--per-minute", type=int, default=150)
    r = sub.add_parser("run")
    r.add_argument("data", type=Path)
    r.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.data, args.env_file, args.per_minute)
    else:
        print(json.dumps(run(args.data, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
