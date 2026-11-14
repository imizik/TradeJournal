"""QQQ overnight hold (buy near the close, sell at the next open) with fills from the consolidated quotes, 2016-2026.

Protocol, committed before any overnight or intraday QQQ return was computed here:
    research/qqq-overnight/protocol.json   qqq-overnight-20261114-v1
Changing a constant below makes a different study: register a new protocol id.

Each full session buys QQQ with a market order at 15:59:00 and sells it with a market order at the next session's
09:30:00; both fill one second later at the quote in effect. Fills reuse the top-5 study's quote machinery
(``scripts.opening_breakout_top5_study``): ``fetch`` asks Alpaca's SIP quotes only at those two moments and saves
every answer in the session file; ``run`` replays the same functions from the saved answers, so the run reads no
market data. Market data only (no journal, no personal data); the data stays outside the repository.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.qqq_overnight_study fetch DATA --env-file .env
    python -m scripts.qqq_overnight_study run DATA --out ../research/qqq-overnight/results.json
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
from scripts import qqq_orb_study as orb

PROTOCOL_ID = "qqq-overnight-20261114-v1"
SYMBOL = "QQQ"
START, END = date(2016, 1, 4), date(2026, 11, 13)  # first entry day; last exit day
PERIODS = (("first", "2016-01-04", "2019-12-31"), ("second", "2020-01-01", "2022-12-31"),
           ("third", "2023-01-01", "2026-11-12"))  # periods are by entry day
OPEN_MINUTE = 9 * 60 + 30
ENTRY_MINUTE = 15 * 60 + 59  # the buy goes at 15:59:00
HALF_DAYS = orb.HALF_DAYS  # early closes (13:00): no entry, since 15:59 is after hours there
EXTRA_CENT = 0.01
LEVEL = 0.95
BOOTSTRAP = 2000
SEED = 20261114
DELAY = t5.DELAY
BP = 10_000


# ---------------------------------------------------------------- rules (pure)


def holds(by_day: dict[str, list]) -> list[tuple[str, str]]:
    """(entry day, exit day) pairs: every full session in the window and the next session in the data."""
    days = sorted(d for d in by_day if START.isoformat() <= d <= END.isoformat())
    return [(d, nxt) for d, nxt in zip(days, days[1:]) if d not in HALF_DAYS]


def tape_hold(entry_day: str, exit_day: str, entry_bars: dict[int, list], exit_bars: dict[int, list], src) -> dict:
    """One overnight hold filled at the quotes (``src``: quote_at, as in the top-5 study)."""
    base = {"day": entry_day, "exit_day": exit_day}
    eq = src.quote_at(SYMBOL, t5.minute_ns(entry_day, ENTRY_MINUTE) + DELAY)
    if not t5.valid_quote(eq):
        return {**base, "status": "no fill quote"}
    fill = eq[2]
    xq = src.quote_at(SYMBOL, t5.minute_ns(exit_day, OPEN_MINUTE) + DELAY)
    if t5.valid_quote(xq):
        out, how = xq[1], "bid"
    else:
        out, how = exit_bars[min(m for m in exit_bars if m >= OPEN_MINUTE)][0], "open from bar"
    return {**base, "status": "held", "fill": fill, "exit": out, "how": how,
            "bp": (out - fill) / fill * BP, "bp_extra_cent": (out - fill - 2 * EXTRA_CENT) / fill * BP,
            "spread_bp": (eq[2] - eq[1]) / fill * BP}


def bar_hold(entry_day: str, exit_day: str, entry_bars: dict[int, list], exit_bars: dict[int, list]) -> dict:
    """The same hold on minute bars, no costs: the 15:59 bar's close to the next session's 09:30 bar open."""
    p0, p1 = entry_bars[ENTRY_MINUTE][3], exit_bars[OPEN_MINUTE][0]
    return {"day": entry_day, "bp": (p1 - p0) / p0 * BP}


def bar_intraday(day: str, bars: dict[int, list]) -> dict:
    """The rest of the same session on bars, no costs: the 09:30 bar's open to the 15:59 bar's close."""
    p0, p1 = bars[OPEN_MINUTE][0], bars[ENTRY_MINUTE][3]
    return {"day": day, "bp": (p1 - p0) / p0 * BP}


def has_bars(entry_bars: dict, exit_bars: dict) -> bool:
    return ENTRY_MINUTE in entry_bars and OPEN_MINUTE in entry_bars and OPEN_MINUTE in exit_bars


# ---------------------------------------------------------------- summary (pure)


def month(t: dict) -> str:
    return t["day"][:7]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _r(x: float | None, n: int = 3) -> float | None:
    return None if x is None else round(x, n)


def interval(rows: list[dict], key: str, rng: random.Random) -> list[float] | None:
    groups = defaultdict(list)
    for t in rows:
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
    return [round(draws[edge], 3), round(draws[len(draws) - 1 - edge], 3)]


def period_means(rows: list[dict], key: str = "bp") -> dict:
    return {name: _r(mean([t[key] for t in rows if lo <= t["day"] <= hi])) for name, lo, hi in PERIODS}


def decide(band: list[float] | None, periods: dict, extra_cent: float | None, intraday: float | None,
           net: float | None) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "loses money"
    if (band[0] > 0 and all(v is not None and v > 0 for v in periods.values()) and extra_cent is not None
            and extra_cent > 0 and intraday is not None and net is not None and net > intraday):
        return "worth a paper test"
    return "no evidence either way"


def cell(rows: list[dict], key: str = "bp") -> dict:
    vals = sorted(t[key] for t in rows)
    if not vals:
        return {"holds": 0}
    return {"holds": len(vals), "mean_bp": round(sum(vals) / len(vals), 3), "median_bp": round(vals[len(vals) // 2], 3),
            "up_rate": round(sum(v > 0 for v in vals) / len(vals), 3)}


def growth(rows: list[dict], key: str = "bp") -> float | None:
    """Compounded growth of $1 over the rows in day order, as a multiple."""
    if not rows:
        return None
    g = 1.0
    for t in sorted(rows, key=lambda t: t["day"]):
        g *= 1 + t[key] / BP
    return round(g, 3)


def summarize(tape: list[dict], bars: list[dict], intraday: list[dict], counts: dict, buy_hold: float | None) -> dict:
    held = [t for t in tape if t["status"] == "held"]
    net = mean([t["bp"] for t in held])
    raw_periods = {name: mean([t["bp"] for t in held if lo <= t["day"] <= hi]) for name, lo, hi in PERIODS}
    raw_extra = mean([t["bp_extra_cent"] for t in held])
    periods, extra = {k: _r(v) for k, v in raw_periods.items()}, _r(raw_extra)
    days = {t["day"] for t in held}  # every bar line covers the same holds as the test
    same_intraday = [t for t in intraday if t["day"] in days]
    same_bars = [t for t in bars if t["day"] in days]
    intra = mean([t["bp"] for t in same_intraday])
    band = interval(held, "bp", random.Random(SEED))
    by_month = defaultdict(float)
    for t in held:
        by_month[month(t)] += t["bp"]
    best = sorted(by_month, key=lambda k: -by_month[k])[:max(1, len(by_month) // 100)]
    spreads = sorted(t["spread_bp"] for t in held)
    weekday = lambda t: date.fromisoformat(t["day"]).strftime("%a")  # noqa: E731
    return {
        "test": {**cell(held), "interval_bp": band, "periods_bp": periods, "mean_bp_extra_cent": extra,
                 "intraday_same_days_bp": _r(intra), "decision": decide(band, raw_periods, raw_extra, intra, net)},
        "descriptive": {
            **counts, "no_fill_quote": sum(1 for t in tape if t["status"] == "no fill quote"),
            "exits": {k: sum(1 for t in held if t["how"] == k) for k in ("bid", "open from bar")},
            "by_year": {y: cell([t for t in held if t["day"][:4] == y]) for y in sorted({t["day"][:4] for t in held})},
            "intraday_by_year_on_bars": {y: cell([t for t in same_intraday if t["day"][:4] == y])
                                         for y in sorted({t["day"][:4] for t in same_intraday})},
            "by_entry_weekday": {d: cell([t for t in held if weekday(t) == d]) for d in ("Mon", "Tue", "Wed", "Thu", "Fri")},
            "without_best_1pct_months": cell([t for t in held if month(t) not in best]),
            "on_bars_no_costs": cell(same_bars),
            "intraday_on_bars_no_costs": cell(same_intraday),
            "entry_spread_bp": {"mean": _r(mean(spreads)), "median": _r(spreads[len(spreads) // 2]) if spreads else None},
            "growth_of_1": {"overnight_net": growth(held), "overnight_extra_cent": growth(held, "bp_extra_cent"),
                            "overnight_on_bars": growth(same_bars), "intraday_on_bars": growth(same_intraday),
                            "buy_and_hold_on_bars": buy_hold}}}


# ---------------------------------------------------------------- data


def run(root: Path, out: Path | None = None) -> dict:
    by_day = v1.load(root / "bars.json.gz")
    pairs = holds(by_day)
    in_window = [d for d in by_day if START.isoformat() <= d <= END.isoformat()]
    counts = {"entry_sessions": len(in_window) - 1, "holds_possible": len(pairs),
              "early_closes_left_out": sum(1 for d in sorted(in_window)[:-1] if d in HALF_DAYS), "missing_bars": 0}
    tape, bars_out, intra = [], [], []
    for entry_day, exit_day in pairs:
        eb, xb = ({r[0]: r[1:] for r in by_day[d]} for d in (entry_day, exit_day))
        if not has_bars(eb, xb):
            counts["missing_bars"] += 1
            continue
        path = root / "session" / f"{entry_day}.json.gz"
        if not path.exists():
            raise SystemExit(f"missing session file {entry_day}: run fetch first")
        src = t5.Replay(v1.load(path)["ticks"])
        tape.append(tape_hold(entry_day, exit_day, eb, xb, src))
        bars_out.append(bar_hold(entry_day, exit_day, eb, xb))
        intra.append(bar_intraday(entry_day, eb))
    first, last = sorted(in_window)[0], sorted(in_window)[-1]
    fb, lb = ({r[0]: r[1:] for r in by_day[d]} for d in (first, last))
    buy_hold = round(lb[ENTRY_MINUTE][3] / fb[OPEN_MINUTE][0], 3) if OPEN_MINUTE in fb and ENTRY_MINUTE in lb else None
    results = {"protocol_id": PROTOCOL_ID, **summarize(tape, bars_out, intra, counts, buy_hold)}
    (root / "results.json").write_text(json.dumps(results, indent=2))
    if out is not None:
        out.write_text(json.dumps(results, indent=2) + "\n")
    return results


def fetch(root: Path, env_file: Path, per_minute: int = 150) -> None:
    """Quotes for every hold. Reuses ``bars.json.gz`` (minutes 09:30 to 15:59) when it is already in ``root``."""
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
                    if OPEN_MINUTE <= minute <= ENTRY_MINUTE:
                        by_day[day].append([minute, b["o"], b["h"], b["l"], b["c"], b["v"]])
                print(f"bars {year}: {len(rows)}", flush=True)
            v1.save(bars_path, dict(by_day))
        by_day = v1.load(bars_path)
        get = lambda p, params: get_json(client, "https://data.alpaca.markets" + p, params, headers)  # noqa: E731
        for entry_day, exit_day in holds(by_day):
            path = root / "session" / f"{entry_day}.json.gz"
            if path.exists():
                continue
            eb, xb = ({r[0]: r[1:] for r in by_day[d]} for d in (entry_day, exit_day))
            log: dict = {}
            if has_bars(eb, xb):
                tape_hold(entry_day, exit_day, eb, xb, t5.Recorder(get, log))
            v1.save(path, {"ticks": log})
            print(f"hold {entry_day} -> {exit_day}: {len(log)} quote answers", flush=True)


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
