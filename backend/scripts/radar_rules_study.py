"""Radar flag rules study: do the live stock flags, or a simple variant of them, beat a coin flip?

Registered protocol (kept outside the repository with the results): the live rule ``radar-rules-v0`` is replayed
exactly on minute passes rebuilt from historical SIP bars (``radar_historical_replay.reconstruct``), and a small grid
of SPY-relative variants (window, trigger, time of day, side, a liquidity filter) is detected on the same passes.
One episode per stock per day. Score = side x (stock minus SPY return from one minute after the flag to +60 minutes
or the close, minus the same stock's mean over that clock window on its previous 20 sessions).

From backend, with a data folder outside the repository:
  ALPACA_DATA_FEED=sip python -m scripts.radar_rules_study fetch DATA --env-file .env [--cache-root CACHE]
  python -m scripts.radar_rules_study prepare DATA
  python -m scripts.radar_rules_study search DATA --out RESULTS
  python -m scripts.radar_rules_study exam DATA --out RESULTS     # once, reads RESULTS/results-search.json

The fetch step uses only Alpaca market-data GET endpoints. Research only: nothing here is read by the app or
changes a rule.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import json
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from app.engine import radar_rules
from app.engine.radar_store import load_universe
from scripts import radar_historical_replay as replay
from scripts.radar_long_history import alpaca_bars, keys_from, load

STUDY = "radar-rules-20261121-v1"
FIRST, LAST = date(2023, 1, 3), date(2026, 11, 20)
SEARCH_END = date(2024, 12, 31)
# 13:00 closes; late prints after the close mean a bar-count test cannot find them
HALF_DAYS = {"2023-07-03", "2023-11-24", "2024-07-03", "2024-11-29", "2024-12-24", "2025-07-03", "2025-11-28",
             "2025-12-24"}
DAILY_START = date(2022, 11, 25)  # room for 20 sessions of dollar volume before the first session
MINUTES = 390  # pass ids 1..390; pass m is the close of the bar that started m-1 minutes after 09:30
FLOOR_PCT, PERSIST = radar_rules.V0.own_move_floor_pct, radar_rules.V0.persist_passes
HOUR, NORMAL_DAYS, NORMAL_MIN = 60, 20, 10
LIQUID_LOOKBACK, LIQUID_PRICE = 20, 10.0
DRAWS, SEED, MOSTLY, DROP_DAYS, MIN_SEARCH, MIN_EXAM = 2000, 20261121, 0.80, 5, 200, 100
STOCK_KINDS = ("relative_to_spy", "relative_to_sector")
SLICES = {"open": (1, 60), "midday": (61, 270), "late": (271, MINUTES - 1)}


@dataclass(frozen=True)
class Variant:
    name: str
    window: int
    trigger: float
    side: int  # +1 follow, -1 fade
    first: int = 1  # flag pass range, inclusive
    last: int = MINUTES - 1
    liquid: bool = False


def grid() -> list[Variant]:
    out = []
    for w in (15, 30, 60):
        for t in (3.0, 4.5, 6.0):
            for side, label in ((1, "follow"), (-1, "fade")):
                out.append(Variant(f"W{w}-T{t:g}-{label}", w, t, side))
    for slice_name, (a, b) in SLICES.items():
        for side, label in ((1, "follow"), (-1, "fade")):
            out.append(Variant(f"W30-T4.5-{slice_name}-{label}", 30, 4.5, side, a, b))
    for side, label in ((1, "follow"), (-1, "fade")):
        out.append(Variant(f"W30-T4.5-liquid-{label}", 30, 4.5, side, liquid=True))
    return out


# ------------------------------------------------------------------ detection (pure)


def detect(prices: np.ndarray, spy: int, stocks: list[int], window: int, trigger: float,
           first: int = 1, last: int = MINUTES - 1) -> dict[int, tuple[int, int]]:
    """{stock row: (flag pass, +1 up / -1 down)} — the first pass in [first, last] where the stock's ``window``-minute
    return minus SPY's is at least ``trigger`` points the same way, with its own move at least the live floor, on
    ``PERSIST`` consecutive passes. ``prices`` is [row, pass 0..MINUTES] last prices, NaN where a pass has no quote
    (column 0 unused); a reading needs a quote at both ends, as in ``radar_rules._readings``.

    Known gaps against the live code, none of which touch the live baseline (that comes from the exact replay): a
    pass with no quotes at all is not skipped over (the live rule would use a neighbouring pass), and a flag on the
    last pass is not reported (it could not be scored anyway)."""
    end = prices[:, window:]
    start = prices[:, :-window].copy()
    # at pass ``window`` the live rule's nearest pass to the (missing) pass 0 is pass 1, inside its 90 s tolerance
    start[:, 0] = prices[:, 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        own = (end / start - 1) * 100  # column j is pass j + window
        rel = own - own[spy]
        floor = np.abs(own) >= FLOOR_PCT
        up = floor & (rel >= trigger)
        down = floor & (rel <= -trigger)
    out = {}
    for s in stocks:
        for sign, hit in ((1, up[s]), (-1, down[s])):
            run = np.convolve(hit.astype(int), np.ones(PERSIST, int), "full")[:hit.size] >= PERSIST
            passes = np.flatnonzero(run) + window
            passes = passes[(passes >= max(first, window)) & (passes <= last)]
            if passes.size and (s not in out or passes[0] < out[s][0]):
                out[s] = (int(passes[0]), sign)
    return out


def ffill(prices: np.ndarray) -> np.ndarray:
    """Last trade at or before each pass, along each row."""
    out = prices.copy()
    for j in range(1, out.shape[1]):
        gap = np.isnan(out[:, j])
        out[gap, j] = out[gap, j - 1]
    return out


def relative(filled: np.ndarray, spy: int, row: int, entry: int, end: int) -> float:
    """Stock minus SPY return over [entry, end], in points; NaN when a price is missing."""
    a, b, sa, sb = filled[row, entry], filled[row, end], filled[spy, entry], filled[spy, end]
    return float(((b / a) - (sb / sa)) * 100)


def horizons(flag: int, delay: int = 1) -> tuple[int, int, int] | None:
    """(entry, +60 end, close end) passes, or None when the entry would be at or after the last pass."""
    entry = flag + delay
    if entry >= MINUTES:
        return None
    return entry, min(entry + HOUR, MINUTES), MINUTES


def normal(history: list[np.ndarray], spy: int, row: int, entry: int, end: int) -> float:
    """Mean relative return of the same stock over the same clock window on the previous sessions given (oldest
    first); the last ``NORMAL_DAYS`` usable ones, 0 when fewer than ``NORMAL_MIN``."""
    values = []
    for filled in reversed(history):
        v = relative(filled, spy, row, entry, end)
        if np.isfinite(v):
            values.append(v)
            if len(values) == NORMAL_DAYS:
                break
    return float(np.mean(values)) if len(values) >= NORMAL_MIN else 0.0


# ------------------------------------------------------------------ statistics (pure)


def summarize(day_index: list[str], scores: list[tuple[str, float]], rng_seed: int = SEED) -> dict:
    """Mean, share positive, day bootstrap and the drop-top-days check for (day, score) pairs."""
    values = np.array([v for _, v in scores], float)
    if not values.size:
        return {"episodes": 0}
    sums, counts = _per_day(day_index, scores)
    draws = _draws(sums, counts, len(day_index), rng_seed)
    top = np.argsort(-sums)[:DROP_DAYS]
    keep = np.ones(len(day_index), bool)
    keep[top] = False
    dropped = sums[keep].sum() / counts[keep].sum() if counts[keep].sum() else float("nan")
    return {"episodes": int(values.size), "days_with_episodes": int((counts > 0).sum()),
            "mean": float(values.mean()), "positive_share": float((values > 0).mean()),
            "median": float(np.median(values)),
            "draws_above_zero": float((draws > 0).mean()),
            "range95": [float(np.nanpercentile(draws, 2.5)), float(np.nanpercentile(draws, 97.5))],
            "mean_without_top_days": float(dropped)}


def _per_day(day_index, scores):
    at = {d: i for i, d in enumerate(day_index)}
    sums, counts = np.zeros(len(day_index)), np.zeros(len(day_index))
    for d, v in scores:
        sums[at[d]] += v
        counts[at[d]] += 1
    return sums, counts


def _resample(n, seed):
    return np.random.default_rng(seed).integers(0, n, (DRAWS, n))


def _draws(sums, counts, n, seed):
    idx = _resample(n, seed)
    with np.errstate(invalid="ignore", divide="ignore"):
        return sums[idx].sum(1) / counts[idx].sum(1)


def paired_share(day_index, a, b, seed=SEED) -> float:
    """Share of day draws (the same draws for both) where mean(a) - mean(b) > 0."""
    sa, ca = _per_day(day_index, a)
    sb, cb = _per_day(day_index, b)
    da, db = _draws(sa, ca, len(day_index), seed), _draws(sb, cb, len(day_index), seed)
    return float(((da - db) > 0).mean())


def passes_exam(chosen: dict, edge_share: float) -> dict:
    checks = {"mean_and_hit_rate": chosen.get("mean", 0) > 0 and chosen.get("positive_share", 0) > 0.5,
              "mostly_above_zero": chosen.get("draws_above_zero", 0) >= MOSTLY,
              "beats_live": edge_share >= MOSTLY,
              "not_a_few_days": chosen.get("mean_without_top_days", -1) > 0,
              "enough_episodes": chosen.get("episodes", 0) >= MIN_EXAM}
    return {"checks": checks, "passed": all(checks.values())}


def live_edge(s: dict) -> bool:
    return s.get("mean", 0) > 0 and s.get("draws_above_zero", 0) >= MOSTLY and s.get("mean_without_top_days", -1) > 0


# ------------------------------------------------------------------ fetching


def sessions_from(spy_minutes_days: list[str]) -> list[str]:
    return [d for d in spy_minutes_days if FIRST <= date.fromisoformat(d) <= LAST]


def fetch(root: Path, env_file: Path, cache_root: Path | None):
    import httpx
    _, headers = keys_from(env_file)
    universe = load_universe()
    symbols = [s["symbol"] for s in universe["symbols"]]
    root.mkdir(parents=True, exist_ok=True)
    span = (DAILY_START.isoformat(), LAST.isoformat() + "T23:59:59Z")
    with httpx.Client(timeout=90) as client:
        daily_file = root / "daily.json.gz"
        if not daily_file.exists():
            daily = {}
            for adjustment in ("raw", "split"):
                got = alpaca_bars(client, headers, symbols, "1Day", *span, adjustment)
                daily[adjustment] = {s: [{k: b.get(k) for k in ("t", "o", "c", "v", "vw")} for b in rows]
                                     for s, rows in got.items()}
            replay.write_snapshot(daily_file, daily)
            print("daily saved", flush=True)
        daily = load(daily_file)
        days = [b["t"][:10] for b in daily["raw"]["SPY"]]
        folder = root / "minutes"
        folder.mkdir(exist_ok=True)

        def one(day):
            path = folder / f"{day}.json.gz"
            if path.exists():
                return
            start, end = replay.bounds(date.fromisoformat(day))
            rows, missing = {}, []
            for s in symbols:
                local = cache_root / "stocks" / "1Min" / "sip" / s / f"{day}.json" if cache_root else None
                if local and local.is_file():
                    rows[s] = json.loads(local.read_text())
                else:
                    missing.append(s)
            if missing:
                rows.update(alpaca_bars(client, headers, missing, "1Min", start.isoformat(),
                                        (end - timedelta(minutes=1)).isoformat(), "raw"))
            compact = {}
            for s in symbols:
                minutes = {}
                for b in rows.get(s, []):
                    offset = (datetime.fromisoformat(b["t"].replace("Z", "+00:00")) - start).total_seconds() / 60
                    if offset.is_integer() and 0 <= offset < MINUTES:
                        minutes[int(offset)] = [b["o"], b["c"]]
                compact[s] = minutes
            replay.write_snapshot(path, compact)
            print(f"{day} saved ({len(missing)} fetched)", flush=True)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(one, sessions_from(days)))


# ------------------------------------------------------------------ preparing one day (live replay + price matrix)


_STATE = {}


def _start(root):
    universe = load_universe()
    daily = load(root / "daily.json.gz")
    _STATE.update(root=root, universe=universe,
                  daily={adj: {s: {date.fromisoformat(b["t"][:10]): b for b in rows} for s, rows in data.items()}
                         for adj, data in daily.items()})


def prepare_day(args):
    prior, day = args
    root, universe, daily = _STATE["root"], _STATE["universe"], _STATE["daily"]
    out = root / "prepared" / f"{day}.npz"
    if out.exists() and np.load(out)["prices"].dtype == np.float64:
        return day, "cached"
    symbols = [s["symbol"] for s in universe["symbols"]]
    previous, _ = replay.daily_inputs(daily, date.fromisoformat(prior), date.fromisoformat(day))
    bars = load(root / "minutes" / f"{day}.json.gz")
    if day in HALF_DAYS or not any(int(k) >= 360 for k in bars.get("SPY", {})):  # half day or a missing tape
        return day, "skipped"
    passes, quotes = replay.reconstruct(date.fromisoformat(day), universe, bars, previous)
    prices = np.full((len(symbols), MINUTES + 1), np.nan, np.float64)
    row = {s: i for i, s in enumerate(symbols)}
    for m, rows in quotes.items():
        for s, q in rows.items():
            prices[row[s], m] = q["last"]
    by_stamp = {p["finished_at"]: p["id"] for p in passes}
    events = [(by_stamp[e["first_seen_at"]], e["kind"], e["direction"], e["symbols"])
              for e, _ in radar_rules.replay(universe, passes, quotes, radar_rules.V0)]
    out.parent.mkdir(exist_ok=True)
    tmp = out.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, prices=prices, events=json.dumps(events))  # float64: no rounding at the trigger edge
    tmp.replace(out)
    return day, "prepared"


def prepare(root: Path, workers: int):
    daily = load(root / "daily.json.gz")
    days = [b["t"][:10] for b in daily["raw"]["SPY"]]
    pairs = [(days[i - 1], days[i]) for i in range(1, len(days)) if FIRST <= date.fromisoformat(days[i]) <= LAST]
    with Pool(workers, initializer=_start, initargs=(root,)) as pool:
        for day, status in pool.imap_unordered(prepare_day, pairs):
            print(f"{day} {status}", flush=True)


# ------------------------------------------------------------------ scoring


def liquid_rows(daily_raw, symbols, stocks, days, i):
    """Stock rows in the top half by mean dollar volume over the 20 sessions before days[i], last close >= $10."""
    window = days[max(0, i - LIQUID_LOOKBACK):i]
    adv = {}
    for s in stocks:
        bars = daily_raw.get(symbols[s], {})
        rows = [bars.get(d) for d in window]
        if len(window) == LIQUID_LOOKBACK and all(rows) and rows[-1]["c"] >= LIQUID_PRICE:
            adv[s] = np.mean([(b.get("vw") or b["c"]) * b["v"] for b in rows])
    ranked = sorted(adv, key=lambda s: -adv[s])
    return set(ranked[:len(stocks) // 2])


class Book:
    """All prepared sessions in memory: last prices filled forward, live events, the stock rows."""

    def __init__(self, root: Path):
        universe = load_universe()
        self.symbols = [s["symbol"] for s in universe["symbols"]]
        self.spy = self.symbols.index("SPY")
        self.stocks = [i for i, s in enumerate(universe["symbols"]) if s["kind"] == "stock" and not s["benchmark"]]
        daily = load(root / "daily.json.gz")
        all_days = [b["t"][:10] for b in daily["raw"]["SPY"]]
        self.daily_raw = {s: {b["t"][:10]: b for b in rows} for s, rows in daily["raw"].items()}
        self.days, self.raw, self.filled, self.events, self.liquid = [], {}, {}, {}, {}
        for i, d in enumerate(all_days):
            path = root / "prepared" / f"{d}.npz"
            if d in HALF_DAYS or not FIRST <= date.fromisoformat(d) <= LAST:
                continue
            if not path.exists():
                raise SystemExit(f"{d} is not prepared; run prepare to completion first")
            z = np.load(path)
            if z["prices"].dtype != np.float64:
                raise SystemExit(f"{d} was prepared at reduced precision; run prepare again")
            self.days.append(d)
            self.raw[d] = z["prices"].astype(np.float64)
            self.filled[d] = ffill(self.raw[d])
            self.events[d] = json.loads(str(z["events"]))
            self.liquid[d] = liquid_rows(self.daily_raw, self.symbols, self.stocks, all_days, i)
        self.position = {d: i for i, d in enumerate(self.days)}

    def history(self, day):
        i = self.position[day]
        return [self.filled[d] for d in self.days[:i]]  # normal() stops at the latest 20 usable

    def score(self, day, row, flag, sign, delay=1) -> dict | None:
        span = horizons(flag, delay)
        if span is None:
            return None
        entry, hour_end, close_end = span
        hist = self.history(day)
        out = {}
        for label, end in (("h60", hour_end), ("close", close_end)):
            r = relative(self.filled[day], self.spy, row, entry, end)
            if not np.isfinite(r):
                return None
            out[label] = sign * (r - normal(hist, self.spy, row, entry, end))
        return out

    def live(self, days, delay=1) -> list[dict]:
        rows = {s: i for i, s in enumerate(self.symbols)}
        out = []
        for d in days:
            first = {}
            for minute, kind, direction, symbols in self.events[d]:
                if kind in STOCK_KINDS and symbols[0] not in first:
                    first[symbols[0]] = (minute, 1 if direction == "up" else -1, kind)
            for sym, (minute, sign, kind) in first.items():
                s = self.score(d, rows[sym], minute, sign, delay)
                if s:
                    out.append({"day": d, "symbol": sym, "minute": minute, "sign": sign, "kind": kind, **s})
        return out

    def groups(self, days) -> list[dict]:
        rows = {s: i for i, s in enumerate(self.symbols)}
        out = []
        for d in days:
            seen = set()
            for minute, kind, direction, symbols in self.events[d]:
                if kind != "group_move" or (tuple(symbols), direction) in seen:
                    continue
                seen.add((tuple(symbols), direction))
                sign = 1 if direction == "up" else -1
                scored = [self.score(d, rows[s], minute, sign) for s in symbols]
                scored = [s for s in scored if s]
                if scored:
                    out.append({"day": d, "minute": minute, "h60": float(np.mean([s["h60"] for s in scored])),
                                "close": float(np.mean([s["close"] for s in scored]))})
        return out

    def variant(self, v: Variant, days) -> list[dict]:
        out = []
        for d in days:
            stocks = [s for s in self.stocks if s in self.liquid[d]] if v.liquid else self.stocks
            for row, (flag, direction) in detect(self.raw[d], self.spy, stocks, v.window, v.trigger,
                                                 v.first, v.last).items():
                s = self.score(d, row, flag, direction * v.side)
                if s:
                    out.append({"day": d, "symbol": self.symbols[row], "minute": flag, "sign": direction * v.side, **s})
        return out


def stats(days, rows) -> dict:
    return {h: summarize(days, [(r["day"], r[h]) for r in rows]) for h in ("h60", "close")}


def by_year(rows) -> dict:
    years = defaultdict(list)
    for r in rows:
        years[r["day"][:4]].append(r["h60"])
    return {y: {"episodes": len(v), "mean": float(np.mean(v)), "positive_share": float(np.mean(np.array(v) > 0))}
            for y, v in sorted(years.items())}


def search(root: Path, out: Path):
    book = Book(root)
    days = [d for d in book.days if date.fromisoformat(d) <= SEARCH_END]
    live = book.live(days)
    result = {"study": STUDY, "period": [days[0], days[-1]], "sessions": len(days),
              "live": {**stats(days, live), "years": by_year(live)},
              "live_flag_pass_entry": stats(days, book.live(days, delay=0)),
              "live_spy_only": stats(days, [r for r in live if r["kind"] == "relative_to_spy"]),
              "groups": stats(days, book.groups(days)), "variants": {}}
    for v in grid():
        rows = book.variant(v, days)
        result["variants"][v.name] = {"spec": asdict(v), **stats(days, rows), "years": by_year(rows)}
        print(f"{v.name}: {result['variants'][v.name]['h60'].get('episodes')} episodes", flush=True)
    # the live W30/T4.5 follow variant should land on the same first SPY-relative flags as the exact replay
    spy_live = {}
    for d in days:
        for minute, kind, direction, symbols in book.events[d]:
            if kind == "relative_to_spy":
                spy_live.setdefault((d, symbols[0]), (minute, 1 if direction == "up" else -1))
    mine = {(r["day"], r["symbol"]): (r["minute"], r["sign"]) for r in book.variant(next(v for v in grid() if v.name == "W30-T4.5-follow"), days)}
    result["replay_check"] = {"live_spy_first_events": len(spy_live), "variant": len(mine),
                              "same": sum(mine.get(k) == v for k, v in spy_live.items())}
    eligible = {k: v for k, v in result["variants"].items() if v["h60"].get("episodes", 0) >= MIN_SEARCH}
    best = max(eligible, key=lambda k: eligible[k]["h60"]["mean"]) if eligible else None
    goes = bool(best) and eligible[best]["h60"]["mean"] > 0 and eligible[best]["h60"]["draws_above_zero"] >= MOSTLY
    result["chosen"] = best if goes else None
    result["best_on_search"] = best
    out.mkdir(parents=True, exist_ok=True)
    (out / "results-search.json").write_text(json.dumps(result, indent=1))
    print(f"best {best}; goes to exam: {goes}", flush=True)


def exam(root: Path, out: Path):
    found = json.loads((out / "results-search.json").read_text())
    if (out / "results-exam.json").exists():
        raise SystemExit("the exam has been run already")
    book = Book(root)
    days = [d for d in book.days if date.fromisoformat(d) > SEARCH_END]
    live = book.live(days)
    result = {"study": STUDY, "period": [days[0], days[-1]], "sessions": len(days),
              "live": {**stats(days, live), "years": by_year(live)},
              "live_flag_pass_entry": stats(days, book.live(days, delay=0)),
              "live_spy_only": stats(days, [r for r in live if r["kind"] == "relative_to_spy"]),
              "groups": stats(days, book.groups(days))}
    result["live_edge"] = live_edge(result["live"]["h60"])
    if found["chosen"]:
        v = next(x for x in grid() if x.name == found["chosen"])
        rows = book.variant(v, days)
        chosen = stats(days, rows)
        share = paired_share(days, [(r["day"], r["h60"]) for r in rows], [(r["day"], r["h60"]) for r in live])
        result["chosen"] = {"name": v.name, **chosen, "years": by_year(rows), "beats_live_share": share,
                            **passes_exam(chosen["h60"], share)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "results-exam.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ("live_edge",)} | {"chosen": result.get("chosen", {}).get("passed")}))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("fetch", "prepare", "search", "exam"))
    p.add_argument("data", type=Path)
    p.add_argument("--env-file", type=Path, default=Path(".env"))
    p.add_argument("--cache-root", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--workers", type=int, default=6)
    a = p.parse_args()
    if a.command == "fetch":
        fetch(a.data, a.env_file, a.cache_root)
    elif a.command == "prepare":
        prepare(a.data, a.workers)
    elif a.command == "search":
        search(a.data, a.out)
    else:
        exam(a.data, a.out)


if __name__ == "__main__":
    main()
