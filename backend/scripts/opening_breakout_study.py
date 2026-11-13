"""Opening breakout study: a 5-minute opening range breakout on the day's stocks in play, after retail costs.

Protocol, committed before any outcome here was computed:
    research/opening-breakout/protocol.json   opening-breakout-20261113-v1
Changing a constant below makes a different study: register a new protocol id.

Market data only (no journal, no personal data). ``fetch`` writes Alpaca SIP bars under ``DATA`` (outside the
repository): daily bars for every listed common stock, each session's 09:30-09:34 bars for the candidates, then the
rest of the session for the day's selected names. ``run`` replays the rules and writes ``results.json`` there and,
being market data, a copy beside the protocol.

Run from backend:
    python -m scripts.opening_breakout_study fetch DATA --env-file .env
    python -m scripts.opening_breakout_study run DATA
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import gzip
import json
from pathlib import Path
import random
import sys
from zoneinfo import ZoneInfo

PROTOCOL_ID = "opening-breakout-20261113-v1"
START, END = date(2024, 1, 2), date(2026, 11, 12)
DAILY_START = date(2023, 11, 1)
CHECK_START = date(2025, 7, 1)
HALF_DAYS = {date(2024, 7, 3), date(2024, 11, 29), date(2024, 12, 24), date(2025, 7, 3), date(2025, 11, 28),
             date(2025, 12, 24)}
NEW_LISTING = "2026-11-12"
MIN_PRICE, MIN_SHARES, MIN_ATR, WINDOW = 5.0, 1_000_000, 0.50, 14
RVOL_DAYS, MIN_RVOL_DAYS, MIN_RVOL, TOP, AHEAD = 14, 10, 1.0, 20, 20
OPEN_MINUTE, RANGE_MINUTES, LAST_ENTRY, LAST_BAR = 570, 5, 955, 959
MIN_RANGE_BARS = 3
STOP_ATR = 0.10
CENT, BPS = 0.01, 0.0002
SPLIT_TOLERANCE = 0.01
BOOTSTRAP, SEED, LEVEL = 2000, 20261113, 1 - 0.05 / 2
NY = ZoneInfo("America/New_York")


# ---------------------------------------------------------------- selection (pure)


def true_ranges(rows: list[list]) -> list[float | None]:
    """``rows`` are [day, open, high, low, close, volume]; each day's true range (None for the first)."""
    out: list[float | None] = [None]
    for prev, row in zip(rows, rows[1:]):
        pc, h, low = prev[4], row[2], row[3]
        out.append(max(h - low, abs(h - pc), abs(low - pc)))
    return out


def candidate(rows: list[list], ratios: dict[str, float], i: int) -> dict | None:
    """Whether the name is a candidate on the session after ``rows[i]`` (its own last bar), from bars through ``i``."""
    if i + 1 < WINDOW + 1:
        return None
    window = rows[i + 1 - WINDOW:i + 1]
    ranges = true_ranges(rows[i - WINDOW:i + 1])[1:]
    if rows[i][4] < MIN_PRICE or any(r is None for r in ranges):
        return None
    atr = sum(ranges) / WINDOW
    shares = sum(r[5] for r in window) / WINDOW
    if shares < MIN_SHARES or atr < MIN_ATR:
        return None
    held = [ratios.get(r[0]) for r in rows[i - WINDOW:i + 1]]
    if any(v is None for v in held) or max(held) > min(held) * (1 + SPLIT_TOLERANCE):
        return None
    return {"atr": atr, "close": rows[i][4]}


def opening_range(bars: dict[int, list]) -> dict | None:
    """``bars``: minute -> [open, high, low, close, volume] for 09:30-09:34."""
    inside = [m for m in sorted(bars) if OPEN_MINUTE <= m < OPEN_MINUTE + RANGE_MINUTES]
    if len(inside) < MIN_RANGE_BARS:
        return None
    first, last = bars[inside[0]][0], bars[inside[-1]][3]
    side = 1 if last > first else -1 if last < first else 0
    return {"high": max(bars[m][1] for m in inside), "low": min(bars[m][2] for m in inside), "side": side,
            "volume": sum(bars[m][4] for m in inside)}


def relative_volume(today: float, history: list[float]) -> float | None:
    if len(history) < MIN_RVOL_DAYS:
        return None
    mean = sum(history) / len(history)
    return today / mean if mean > 0 else None


def in_play(rows: list[dict]) -> list[dict]:
    """``rows``: {symbol, side, rvol, ...}; the top ``TOP`` with a side and relative volume of at least 1."""
    kept = [r for r in rows if r["side"] != 0 and r["rvol"] is not None and r["rvol"] >= MIN_RVOL]
    return sorted(kept, key=lambda r: (-r["rvol"], r["symbol"]))[:TOP]


# ---------------------------------------------------------------- one trade (pure)


def cost(price: float, multiple: float = 1.0) -> float:
    return (CENT + BPS * price) * multiple


def trade(pick: dict, bars: dict[int, list], cost_multiple: float = 1.0, worst_case: bool = False) -> dict | None:
    """Replay one selected name. ``pick``: side, high, low, atr. ``bars``: minute -> [o, h, l, c, v] from 09:35."""
    side, risk = pick["side"], STOP_ATR * pick["atr"]
    level = pick["high"] if side > 0 else pick["low"]
    minutes = sorted(m for m in bars if m >= OPEN_MINUTE + RANGE_MINUTES)
    fill = stop = entered = None
    for m in minutes:
        o, h, low, c, _ = bars[m]
        if fill is None:
            if m > LAST_ENTRY:
                return None
            if (side > 0 and h >= level) or (side < 0 and low <= level):
                fill = max(level, o) if side > 0 else min(level, o)
                stop = fill - side * risk
                entered = m
                if worst_case:
                    beyond = low <= stop if side > 0 else h >= stop
                else:
                    beyond = c <= stop if side > 0 else c >= stop
                if beyond:
                    return _result(pick, fill, stop, m, m, "stop", risk, cost_multiple)
            continue
        if (side > 0 and low <= stop) or (side < 0 and h >= stop):
            out = min(stop, o) if side > 0 else max(stop, o)
            return _result(pick, fill, out, entered, m, "stop", risk, cost_multiple)
    if fill is None:
        return None
    last = max(m for m in minutes if m <= LAST_BAR)
    return _result(pick, fill, bars[last][3], entered, last, "close", risk, cost_multiple)


def _result(pick: dict, fill: float, out: float, entered: int, left: int, how: str, risk: float, multiple: float) -> dict:
    gross = (out - fill) * pick["side"]
    net = gross - cost(fill, multiple) - cost(out, multiple)
    return {"symbol": pick["symbol"], "side": pick["side"], "rank": pick["rank"], "fill": fill, "exit": out,
            "entered": entered, "left": left, "how": how, "risk": risk, "r": net / risk, "gross_r": gross / risk}


# ---------------------------------------------------------------- summary (pure)


def mean_r(by_day: dict[str, list[float]], days: list[str]) -> float | None:
    values = [r for d in days for r in by_day[d]]
    return sum(values) / len(values) if values else None


def interval(by_day: dict[str, list[float]], rng: random.Random) -> list[float] | None:
    days = sorted(d for d in by_day if by_day[d])
    if not days:
        return None
    draws = sorted(v for v in (mean_r(by_day, [days[rng.randrange(len(days))] for _ in days]) for _ in range(BOOTSTRAP))
                   if v is not None)
    tail = (1 - LEVEL) / 2
    return [round(draws[int(tail * len(draws))], 4), round(draws[min(len(draws) - 1, int((1 - tail) * len(draws)))], 4)]


def by_day(trades: list[dict], key: str = "r") -> dict[str, list[float]]:
    out = defaultdict(list)
    for t in trades:
        out[t["day"]].append(t[key])
    return out


def cell(trades: list[dict], key: str = "r") -> dict:
    rs = [t[key] for t in trades]
    wins, losses = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    days = by_day(trades, key)
    return {"trades": len(rs), "mean_r": round(sum(rs) / len(rs), 4) if rs else None, "total_r": round(sum(rs), 2),
            "win_rate": round(len(wins) / len(rs), 3) if rs else None,
            "mean_win_r": round(sum(wins) / len(wins), 3) if wins else None,
            "mean_loss_r": round(sum(losses) / len(losses), 3) if losses else None,
            "sessions": len(days), "sessions_positive": round(sum(1 for v in days.values() if sum(v) > 0) / len(days), 3) if days else None}


def decide(band: list[float] | None, periods: dict, tripled: float | None) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "loses money"
    if band[0] > 0 and all(periods[p] is not None and periods[p] > 0 for p in periods) and tripled is not None and tripled > 0:
        return "worth a paper test"
    return "no evidence either way"


def summarize(trades: list[dict], tripled: list[dict], selected: int) -> dict:
    out = {}
    for name, keep in (("both_sides", lambda t: True), ("long_side", lambda t: t["side"] > 0)):
        own = [t for t in trades if keep(t)]
        days = by_day(own)
        periods = {p: mean_r(days, [d for d in days if (d < CHECK_START.isoformat()) == (p == "exploration")])
                   for p in ("exploration", "check")}
        three = [t for t in tripled if keep(t)]
        tripled_mean = sum(t["r"] for t in three) / len(three) if three else None
        band = interval(days, random.Random(SEED))
        out[name] = {**cell(own), "interval": band, "periods": {k: None if v is None else round(v, 4) for k, v in periods.items()},
                     "mean_r_costs_tripled": None if tripled_mean is None else round(tripled_mean, 4),
                     "decision": decide(band, periods, tripled_mean)}
    ranked = lambda lo, hi: [t for t in trades if lo <= t["rank"] <= hi]  # noqa: E731
    best = sorted(by_day(trades).items(), key=lambda kv: -sum(kv[1]))
    trim = {d for d, _ in best[:max(1, len(best) // 100)]}
    out["descriptive"] = {
        "selected": selected, "triggered_share": round(len(trades) / selected, 3) if selected else None,
        "short_side": cell([t for t in trades if t["side"] < 0]),
        "by_year": {y: cell([t for t in trades if t["day"][:4] == y]) for y in sorted({t["day"][:4] for t in trades})},
        "rank_1_5": cell(ranked(1, 5)), "rank_6_10": cell(ranked(6, 10)), "rank_11_20": cell(ranked(11, 20)),
        "top_10": cell(ranked(1, 10)), "costs_zero": cell(trades, "gross_r"), "costs_tripled": cell(tripled),
        "without_best_1pct_sessions": cell([t for t in trades if t["day"] not in trim]),
        "exits": {k: sum(1 for t in trades if t["how"] == k) for k in ("stop", "close")}}
    return out


# ---------------------------------------------------------------- data


def load(path: Path):
    return json.loads(gzip.decompress(path.read_bytes()))


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode()))
    tmp.replace(path)


def minute_of(stamp: str) -> tuple[str, int]:
    at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(NY)
    return at.date().isoformat(), at.hour * 60 + at.minute


def all_sessions(days: list[str]) -> list[str]:
    """Every full session with enough daily bars before it to judge candidates (history for relative volume)."""
    return [d for d in days[WINDOW + 1:] if date.fromisoformat(d) not in HALF_DAYS]


def sessions(days: list[str]) -> list[str]:
    """The sessions traded."""
    return [d for d in all_sessions(days) if START <= date.fromisoformat(d) <= END]


def candidates_by_day(daily: dict, days: list[str]) -> dict[str, dict[str, dict]]:
    """session -> {symbol: {atr, close}} from bars strictly before the session."""
    index = {d: i for i, d in enumerate(days)}
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    wanted = set(all_sessions(days))
    for symbol, rows in daily["raw"].items():
        ratios = {d: raw_c / adj for d, raw_c, adj in daily["ratios"].get(symbol, []) if adj}
        for i, row in enumerate(rows[:-1]):
            nxt = rows[i + 1][0]
            if nxt not in wanted or index.get(nxt, -1) != index.get(row[0], -9) + 1:
                continue  # the name must have the previous session's bar
            got = candidate(rows, ratios, i)
            today, before = ratios.get(nxt), ratios.get(row[0])
            if got is None or today is None or before is None or abs(today / before - 1) > SPLIT_TOLERANCE:
                continue  # a split on the session itself breaks the comparison with the days before
            out[nxt][symbol] = got
    return out


def _window(day: str, first: int, last: int) -> tuple[str, str]:
    d = date.fromisoformat(day)
    to_utc = lambda m: datetime(d.year, d.month, d.day, m // 60, m % 60, tzinfo=NY).astimezone(ZoneInfo("UTC"))  # noqa: E731
    return to_utc(first).strftime("%Y-%m-%dT%H:%M:%SZ"), (to_utc(last) + timedelta(seconds=59)).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(root: Path, env_file: Path) -> None:
    import httpx
    from scripts.radar_long_history import alpaca_bars, keys_from, polygon_listing
    keys, headers = keys_from(env_file)
    source = Path("/Users/user/TradeJournal-research/radar-long-history-data/listings.json.gz")
    lists_path = root / "listings.json.gz"
    with httpx.Client(timeout=90) as client:
        lists = load(lists_path) if lists_path.exists() else (load(source) if source.exists() else {})
        if NEW_LISTING not in lists:
            lists[NEW_LISTING] = sorted(polygon_listing(client, keys["POLYGON_API_KEY"], NEW_LISTING))
            save(lists_path, lists)
        names = sorted({s for v in lists.values() for s in v if s.replace(".", "").isalpha() and s.upper() == s})
        print(f"{len(names)} names", flush=True)
        daily_path = root / "daily.json.gz"
        if not daily_path.exists():
            span = (DAILY_START.isoformat(), END.isoformat() + "T23:59:59Z")
            raw, ratios = {}, {}
            for i in range(0, len(names), 200):
                chunk = names[i:i + 200]
                got = alpaca_bars(client, headers, chunk, "1Day", *span, "raw")
                adj = alpaca_bars(client, headers, chunk, "1Day", *span, "split")
                for s in chunk:
                    rows = [[b["t"][:10], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in got.get(s, [])
                            if all(isinstance(b.get(k), (int, float)) for k in ("o", "h", "l", "c", "v"))]
                    if rows:
                        raw[s] = rows
                        adjusted = {b["t"][:10]: b["c"] for b in adj.get(s, [])}
                        ratios[s] = [[r[0], r[4], adjusted.get(r[0])] for r in rows]
                print(f"daily {min(i + 200, len(names))}/{len(names)}", flush=True)
            spy = alpaca_bars(client, headers, ["SPY"], "1Day", *span, "raw")["SPY"]
            save(daily_path, {"days": [b["t"][:10] for b in spy], "raw": raw, "ratios": ratios})
        daily = load(daily_path)
        days = daily["days"]
        picks = candidates_by_day(daily, days)
        history = all_sessions(days)
        first = max(0, history.index(sessions(days)[0]) - RVOL_DAYS - 1)
        order = history[first:]
        for n, day in enumerate(order):
            path = root / "opening" / f"{day}.json.gz"
            if path.exists():
                continue
            want = sorted({s for d in order[n:n + AHEAD + 1] for s in picks.get(d, {})})
            got = {}
            for i in range(0, len(want), 400):
                rows = alpaca_bars(client, headers, want[i:i + 400], "1Min", *_window(day, OPEN_MINUTE, OPEN_MINUTE + RANGE_MINUTES - 1), "raw")
                for s, bars in rows.items():
                    got[s] = [[minute_of(b["t"])[1], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bars]
            save(path, got)
            print(f"opening {day}: {len(got)} names", flush=True)
        cache: dict = {}
        for day in sessions(days):
            path = root / "session" / f"{day}.json.gz"
            if path.exists():
                continue
            chosen = select(root, day, history, picks, cache)
            rows = alpaca_bars(client, headers, [c["symbol"] for c in chosen], "1Min",
                               *_window(day, OPEN_MINUTE + RANGE_MINUTES, LAST_BAR), "raw") if chosen else {}
            save(path, {"picks": chosen, "bars": {s: [[minute_of(b["t"])[1], b["o"], b["h"], b["l"], b["c"], b["v"]]
                                                       for b in bars] for s, bars in rows.items()}})
            print(f"session {day}: {len(chosen)} picks", flush=True)


def _opening(root: Path, day: str, cache: dict) -> dict:
    if day not in cache:
        path = root / "opening" / f"{day}.json.gz"
        cache[day] = load(path) if path.exists() else {}
    return cache[day]


def select(root: Path, day: str, order: list[str], picks: dict, cache: dict | None = None) -> list[dict]:
    cache = {} if cache is None else cache
    n = order.index(day)
    today = _opening(root, day, cache)
    rows = []
    for symbol, info in picks.get(day, {}).items():
        bars = {b[0]: b[1:] for b in today.get(symbol, [])}
        rng = opening_range(bars)
        if rng is None:
            continue
        history = []
        for prior in order[max(0, n - RVOL_DAYS):n]:
            past = {b[0]: b[1:] for b in _opening(root, prior, cache).get(symbol, [])}
            r = opening_range(past) if past else None
            if r is not None:
                history.append(r["volume"])
        rows.append({"symbol": symbol, **rng, "atr": info["atr"], "rvol": relative_volume(rng["volume"], history)})
    keep = set(order[max(0, n - RVOL_DAYS):n + 1])
    for old in [k for k in cache if k not in keep]:
        del cache[old]  # only the relative-volume window is needed again
    chosen = in_play(rows)
    return [{**c, "rank": i + 1} for i, c in enumerate(chosen)]


def run(root: Path, out: Path | None = None) -> dict:
    daily = load(root / "daily.json.gz")
    order = sessions(daily["days"])
    trades, tripled, worst, selected = [], [], [], 0
    for day in order:
        path = root / "session" / f"{day}.json.gz"
        if not path.exists():
            raise SystemExit(f"missing session file {day}: run fetch first")
        data = load(path)
        selected += len(data["picks"])
        for pick in data["picks"]:
            bars = {b[0]: b[1:] for b in data["bars"].get(pick["symbol"], [])}
            for target, kw in ((trades, {}), (tripled, {"cost_multiple": 3.0}), (worst, {"worst_case": True})):
                t = trade(pick, bars, **kw)
                if t is not None:
                    target.append({**t, "day": day})
    results = {"protocol_id": PROTOCOL_ID, "sessions": len(order), **summarize(trades, tripled, selected)}
    results["descriptive"]["fill_bar_worst_case"] = cell(worst)
    (root / "results.json").write_text(json.dumps(results, indent=2))
    if out is not None:
        out.write_text(json.dumps(results, indent=2) + "\n")
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("data", type=Path)
    f.add_argument("--env-file", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("data", type=Path)
    r.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.data, args.env_file)
    else:
        print(json.dumps(run(args.data, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
