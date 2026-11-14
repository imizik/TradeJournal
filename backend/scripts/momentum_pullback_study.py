"""Momentum pullback study: six-month leaders bought after a quiet three-day pullback, held up to ten sessions.

Protocol, committed before any outcome here was computed:
    research/momentum-pullback/protocol.json   momentum-pullback-20261113-v1
Changing a constant below makes a different study: register a new protocol id.

Market data only. ``fetch`` writes Alpaca SIP daily bars for every listed common stock, in chunks, under ``DATA``
(outside the repository). ``run`` replays the rules and writes ``results.json`` there and, being market data, a copy
beside the protocol.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.momentum_pullback_study fetch DATA --env-file .env
    python -m scripts.momentum_pullback_study run DATA --out ../research/momentum-pullback/results.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import gzip
import json
import math
from pathlib import Path
import random
import sys

PROTOCOL_ID = "momentum-pullback-20261113-v1"
DATA_START, DATA_END = date(2016, 1, 4), date(2026, 11, 12)
SIGNAL_START, SIGNAL_END = date(2016, 7, 1), date(2026, 10, 28)
PERIODS = (("first", "2016-07-01", "2019-12-31"), ("second", "2020-01-01", "2022-12-31"), ("third", "2023-01-01", "2026-10-28"))
LISTING_SOURCES = ("/Users/user/TradeJournal-research/opening-breakout-top5-data/listings.json.gz",
                   "/Users/user/TradeJournal-research/opening-breakout-data/listings.json.gz")
MIN_PRICE, MIN_DOLLAR, DOLLAR_DAYS = 10.0, 20_000_000, 20
LOOKBACK, SKIP, HISTORY = 126, 5, 131
TOP_SHARE, TREND_DAYS, EMA_SPAN, PULLBACK, QUIET_DAYS = 0.2, 50, 20, 3, 20
NO_PROGRESS_SESSION, MAX_SESSIONS = 3, 10
CONTROLS = 5
BPS, CENT = 0.0005, 0.01
BOOTSTRAP, SEED, LEVEL = 2000, 20261113, 1 - 0.05 / 2
CHUNK = 200


# ---------------------------------------------------------------- rules (pure)


def ema(values: list[float], span: int = EMA_SPAN) -> list[float | None]:
    """Exponential average started from the simple average of the first ``span`` values (None before)."""
    out: list[float | None] = [None] * len(values)
    if len(values) < span:
        return out
    k, level = 2 / (span + 1), sum(values[:span]) / span
    out[span - 1] = level
    for i in range(span, len(values)):
        level = values[i] * k + level * (1 - k)
        out[i] = level
    return out


def features(bars: dict, calendar_index: dict[str, int], start: str, end: str) -> list[tuple]:
    """``bars``: {"d", "o", "h", "l", "c", "v", "rc"} for one name (split-adjusted, plus unadjusted closes).

    Returns (day, momentum, uptrend, signal, pullback_low) for every session in [start, end] where the name is in the
    universe."""
    d, low, c, v, rc = bars["d"], bars["l"], bars["c"], bars["v"], bars["rc"]
    av = ema(c)
    # Running sums. Split-adjusted close x split-adjusted volume is the unadjusted dollar volume.
    sc, sv, sd = [0.0], [0.0], [0.0]
    for k in range(len(d)):
        sc.append(sc[-1] + c[k])
        sv.append(sv[-1] + v[k])
        sd.append(sd[-1] + c[k] * v[k])
    window = lambda s, a, b: s[b + 1] - s[a]  # noqa: E731  sum over bars a..b
    out = []
    for i in range(HISTORY, len(d)):
        day = d[i]
        if day < start or day > end or rc[i] < MIN_PRICE:
            continue
        here = calendar_index.get(day)
        if here is None or calendar_index.get(d[i - HISTORY]) != here - HISTORY:
            continue  # a calendar session is missing from the window
        if window(sd, i - DOLLAR_DAYS + 1, i) / DOLLAR_DAYS < MIN_DOLLAR:
            continue
        momentum = c[i - SKIP] / c[i - HISTORY] - 1
        uptrend = c[i] > window(sc, i - TREND_DAYS + 1, i) / TREND_DAYS
        falling = all(c[j] < c[j - 1] for j in range(i - PULLBACK + 1, i + 1))
        touched = av[i] is not None and low[i] <= av[i]
        quiet = (window(sv, i - PULLBACK + 1, i) / PULLBACK
                 < window(sv, i - PULLBACK - QUIET_DAYS + 1, i - PULLBACK) / QUIET_DAYS)
        out.append((day, momentum, uptrend, falling and touched and quiet, min(low[i - PULLBACK + 1:i + 1])))
    return out


def leaders(rows: list[tuple], benchmark: float | None) -> list[tuple]:
    """``rows``: (symbol, momentum, uptrend, signal, pullback_low) for one day's universe. The day's leaders."""
    if benchmark is None or not rows:
        return []
    ranked = sorted(rows, key=lambda r: (-r[1], r[0]))[:math.ceil(len(rows) * TOP_SHARE)]
    return [r for r in ranked if r[1] > benchmark and r[2]]


def cost(price_adj: float, ratio: float, multiple: float = 1.0) -> float:
    """One side's cost as a fraction of the price; ``ratio`` turns the adjusted price into the unadjusted one."""
    return multiple * (BPS + CENT / (price_adj * ratio))


def simulate(bars: dict, i: int, low: float) -> dict | None:
    """The trade from a signal on bar ``i`` with pullback low ``low``; None without a next bar to enter on."""
    d, o, c = bars["d"], bars["o"], bars["c"]
    if i + 1 >= len(d):
        return None
    entry = i + 1
    fill = o[entry]
    for j in range(entry, len(d)):
        session = j - entry + 1
        how = ("stop" if c[j] < low else
               "no progress" if session == NO_PROGRESS_SESSION and c[j] <= fill else
               "time" if session == MAX_SESSIONS else None)
        if how:
            if j + 1 < len(d):
                return _trade(bars, entry, j + 1, o[j + 1], how, fill, low)
            return _trade(bars, entry, j, c[j], "end of data", fill, low)
    return _trade(bars, entry, len(d) - 1, c[-1], "end of data", fill, low)


def _trade(bars: dict, entry: int, leave: int, out: float, how: str, fill: float, low: float) -> dict:
    ratio = lambda k: bars["rc"][k] / bars["c"][k]  # noqa: E731
    gross = out / fill - 1
    nets = {m: out * (1 - cost(out, ratio(leave), m)) / (fill * (1 + cost(fill, ratio(entry), m))) - 1 for m in (1.0, 2.0)}
    risk = (fill - low) / fill
    return {"entry_day": bars["d"][entry], "exit_day": bars["d"][leave], "at_close": how == "end of data",
            "hold": leave - entry + (1 if how == "end of data" else 0), "how": how, "gross": gross, "net": nets[1.0], "net_doubled": nets[2.0],
            "r": nets[1.0] / risk if risk > 0 else None}


def control(bars: dict, entry_day: str, exit_day: str, at_close: bool) -> float | None:
    """A control's net return: in at ``entry_day``'s open, out at ``exit_day``'s open (or the last close before it)."""
    d, o, c = bars["d"], bars["o"], bars["c"]
    try:
        entry = d.index(entry_day)
    except ValueError:
        return None
    k = entry
    while k + 1 < len(d) and d[k + 1] <= exit_day:
        k += 1
    out = o[k] if d[k] == exit_day and not at_close and k > entry else c[k]
    ratio = lambda j: bars["rc"][j] / c[j]  # noqa: E731
    return out * (1 - cost(out, ratio(k))) / (o[entry] * (1 + cost(o[entry], ratio(entry)))) - 1


def benchmark_return(spy: dict, entry_day: str, exit_day: str, at_close: bool) -> float:
    d = spy["d"]
    a, b = d.index(entry_day), d.index(exit_day)
    return (spy["c"][b] if at_close else spy["o"][b]) / spy["o"][a] - 1


# ---------------------------------------------------------------- statistics (pure)


def month(t: dict) -> str:
    return t["entry_day"][:7]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def interval(trades: list[dict], key: str, rng: random.Random) -> list[float] | None:
    groups = defaultdict(list)
    for t in trades:
        if t.get(key) is not None:
            groups[month(t)].append(t[key])
    keys = sorted(groups)
    if not keys:
        return None
    draws = []
    for _ in range(BOOTSTRAP):
        values = [x for _ in keys for x in groups[keys[rng.randrange(len(keys))]]]
        draws.append(sum(values) / len(values))
    draws.sort()
    tail = (1 - LEVEL) / 2
    edge = int(tail * len(draws))
    return [round(draws[edge], 5), round(draws[len(draws) - 1 - edge], 5)]


def period_means(trades: list[dict], key: str) -> dict:
    return {name: _r(mean([t[key] for t in trades if lo <= t["day"] <= hi and t.get(key) is not None]))
            for name, lo, hi in PERIODS}


def _r(x: float | None, n: int = 5) -> float | None:
    return None if x is None else round(x, n)


def decide_market(band: list[float] | None, periods: dict, doubled: float | None) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "loses to the market"
    if band[0] > 0 and all(v is not None and v > 0 for v in periods.values()) and doubled is not None and doubled > 0:
        return "worth a paper test"
    return "no evidence either way"


def decide_pullback(band: list[float] | None) -> str:
    if band and band[0] > 0:
        return "the pullback adds"
    if band and band[1] < 0:
        return "the pullback hurts"
    return "no evidence either way"


def cell(trades: list[dict], key: str = "net") -> dict:
    vals = [t[key] for t in trades if t.get(key) is not None]
    if not vals:
        return {"trades": 0}
    s = sorted(vals)
    return {"trades": len(vals), "mean_pct": round(100 * sum(vals) / len(vals), 3), "median_pct": round(100 * s[len(s) // 2], 3),
            "win_rate": round(sum(v > 0 for v in vals) / len(vals), 3)}


def summarize(trades: list[dict], skipped: int, signals: int) -> dict:
    market = [t for t in trades]
    band = interval(market, "excess", random.Random(SEED))
    periods = period_means(market, "excess")
    doubled = mean([t["excess_doubled"] for t in market])
    paired = [t for t in trades if t.get("vs_controls") is not None]
    band2 = interval(paired, "vs_controls", random.Random(SEED))
    best = sorted({month(t) for t in trades}, key=lambda m: -sum(t["excess"] for t in trades if month(t) == m))
    trim = set(best[:max(1, len(best) // 100)])
    return {
        "beats_market": {"trades": len(market), "mean_excess_pct": _r(100 * mean([t["excess"] for t in market]), 3),
                         "interval_pct": None if band is None else [round(100 * x, 3) for x in band],
                         "periods_pct": {k: None if v is None else round(100 * v, 3) for k, v in periods.items()},
                         "mean_excess_doubled_costs_pct": None if doubled is None else round(100 * doubled, 3),
                         "decision": decide_market(band, periods, doubled)},
        "pullback_adds": {"trades": len(paired), "mean_vs_controls_pct": _r(100 * mean([t["vs_controls"] for t in paired]), 3),
                          "interval_pct": None if band2 is None else [round(100 * x, 3) for x in band2],
                          "periods_pct": {k: None if v is None else round(100 * v, 3) for k, v in period_means(paired, "vs_controls").items()},
                          "decision": decide_pullback(band2)},
        "descriptive": {
            "signals": signals, "skipped_while_open": skipped,
            "net": cell(trades), "gross": cell(trades, "gross"), "net_doubled_costs": cell(trades, "net_doubled"),
            "spy_over_holds": cell(trades, "spy"), "controls_net": cell(paired, "controls_net"),
            "controls_excess": cell([{**t, "x": t["controls_net"] - t["spy"]} for t in paired], "x"),
            "mean_hold_sessions": _r(mean([t["hold"] for t in trades]), 2),
            "exits": {k: sum(1 for t in trades if t["how"] == k) for k in ("stop", "no progress", "time", "end of data")},
            "mean_r": _r(mean([t["r"] for t in trades if t.get("r") is not None]), 3),
            "opened_below_stop": sum(1 for t in trades if t.get("r") is None),
            "by_year": {y: cell([t for t in trades if t["day"][:4] == y], "excess") for y in sorted({t["day"][:4] for t in trades})},
            "without_best_1pct_months": cell([t for t in trades if month(t) not in trim], "excess")}}


# ---------------------------------------------------------------- data


def load(path: Path):
    return json.loads(gzip.decompress(path.read_bytes()))


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode()))
    tmp.replace(path)


def chunks(root: Path) -> list[Path]:
    return sorted((root / "daily").glob("chunk-*.json.gz"))


def run(root: Path, out: Path | None = None) -> dict:
    etf = load(root / "daily" / "etf.json.gz")
    spy, qqq = etf["SPY"], etf["QQQ"]
    calendar = spy["d"]
    index = {d: i for i, d in enumerate(calendar)}
    qqq_index = {d: i for i, d in enumerate(qqq["d"])}
    start, end = SIGNAL_START.isoformat(), SIGNAL_END.isoformat()

    by_day: dict[str, list[tuple]] = defaultdict(list)
    for path in chunks(root):
        for symbol, bars in load(path).items():
            for day, momentum, uptrend, signal, low in features(bars, index, start, end):
                by_day[day].append((symbol, momentum, uptrend, signal, low))

    rng = random.Random(SEED)
    wanted: dict[str, list[tuple]] = defaultdict(list)  # symbol -> [(day, low, controls)]
    for day in sorted(by_day):
        q = qqq_index.get(day)
        bench = qqq["c"][q - SKIP] / qqq["c"][q - HISTORY] - 1 if q is not None and q >= HISTORY else None
        lead = leaders(by_day[day], bench)
        pool = sorted(r[0] for r in lead if not r[3])
        for r in sorted((r for r in lead if r[3]), key=lambda r: r[0]):
            wanted[r[0]].append((day, r[4], rng.sample(pool, min(CONTROLS, len(pool)))))
    del by_day
    signals = sum(len(v) for v in wanted.values())

    trades, skipped = [], 0
    for path in chunks(root):
        for symbol, bars in load(path).items():
            busy_until = ""
            for day, low, picks in wanted.get(symbol, []):
                if day < busy_until:
                    skipped += 1
                    continue
                t = simulate(bars, bars["d"].index(day), low)
                if t is None:
                    continue
                busy_until = t["exit_day"]
                spy_ret = benchmark_return(spy, t["entry_day"], t["exit_day"], t["at_close"])
                trades.append({**t, "symbol": symbol, "day": day, "controls": picks, "spy": spy_ret,
                               "excess": t["net"] - spy_ret, "excess_doubled": t["net_doubled"] - spy_ret})

    need = defaultdict(list)
    for n, t in enumerate(trades):
        for s in t["controls"]:
            need[s].append(n)
    got = defaultdict(list)
    for path in chunks(root):
        for symbol, bars in load(path).items():
            for n in need.get(symbol, []):
                t = trades[n]
                value = control(bars, t["entry_day"], t["exit_day"], t["at_close"])
                if value is not None:
                    got[n].append(value)
    for n, t in enumerate(trades):
        t["controls_net"] = mean(got[n]) if got[n] else None
        t["vs_controls"] = None if t["controls_net"] is None else t["net"] - t["controls_net"]
        del t["controls"]

    results = {"protocol_id": PROTOCOL_ID, **summarize(trades, skipped, signals)}
    (root / "results.json").write_text(json.dumps(results, indent=2))
    save(root / "trades.json.gz", trades)
    if out is not None:
        out.write_text(json.dumps(results, indent=2) + "\n")
    return results


def fetch(root: Path, env_file: Path, per_minute: int = 150) -> None:
    import httpx
    from scripts.opening_breakout_top5_study import Throttle
    from scripts.radar_long_history import alpaca_bars, keys_from
    _, headers = keys_from(env_file)
    lists: dict = {}
    for source in LISTING_SOURCES:
        lists.update(load(Path(source)))
    names = sorted({s for v in lists.values() for s in v if s.replace(".", "").isalpha() and s.upper() == s})
    print(f"{len(lists)} listing snapshots, {len(names)} names", flush=True)
    span = (DATA_START.isoformat(), DATA_END.isoformat() + "T23:59:59Z")
    pack = lambda rows, raw: {"d": [b["t"][:10] for b in rows], **{k: [b[k] for b in rows] for k in "ohlcv"},  # noqa: E731
                              "rc": [raw.get(b["t"][:10]) for b in rows]}
    with httpx.Client(timeout=120, event_hooks={"request": [Throttle(per_minute)]}) as client:
        path = root / "daily" / "etf.json.gz"
        if not path.exists():
            adj = alpaca_bars(client, headers, ["SPY", "QQQ"], "1Day", *span, "split")
            save(path, {s: pack(adj[s], {b["t"][:10]: b["c"] for b in adj[s]}) for s in ("SPY", "QQQ")})
        for n, i in enumerate(range(0, len(names), CHUNK)):
            path = root / "daily" / f"chunk-{n:03d}.json.gz"
            if path.exists():
                continue
            part = names[i:i + CHUNK]
            adj = alpaca_bars(client, headers, part, "1Day", *span, "split")
            raw = alpaca_bars(client, headers, part, "1Day", *span, "raw")
            data = {}
            for s in part:
                closes = {b["t"][:10]: b["c"] for b in raw.get(s, [])}
                rows = [b for b in adj.get(s, []) if all(isinstance(b.get(k), (int, float)) for k in "ohlcv")
                        and b["c"] > 0 and b["o"] > 0 and closes.get(b["t"][:10])]
                if rows:
                    data[s] = pack(rows, closes)
            save(path, data)
            print(f"chunk {n}: {min(i + CHUNK, len(names))}/{len(names)} names, {len(data)} with bars", flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("data", type=Path)
    f.add_argument("--env-file", type=Path, default=Path(".env"))
    f.add_argument("--per-minute", type=int, default=150)
    r = sub.add_parser("run")
    r.add_argument("data", type=Path)
    r.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.data, args.env_file, args.per_minute)
    else:
        json.dump(run(args.data, args.out), sys.stdout, indent=2)
        print()


if __name__ == "__main__":
    main()
