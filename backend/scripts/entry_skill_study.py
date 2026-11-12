"""Entry skill study: measured on the stock, do the owner's option entries move
the trade's way by more than matched control entries?

Protocol, committed before any outcome here was computed:
    research/entry-skill/protocol.json   entry-skill-20261112-v1
Changing a constant below makes a different study: register a new protocol id
rather than editing these. Every result is exploratory: earlier studies read
these trades.

Read-only. ``run`` reads the extract written by
``python -m scripts.exit_counterfactual_study extract`` and cached Alpaca SIP
minute bars; ``fetch`` fills the cache (market data only, ALPACA_DATA_FEED=sip).
``run`` writes ``<out>/entry-skill/results.json`` (aggregates) and
``trades.jsonl`` (per trade). Both are personal and the repository is public:
keep ``<out>`` outside it. Nothing here writes the journal or suggests an order.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.entry_skill_study fetch --trades /private/x/trades.json --cache data/alpaca_cache
    python -m scripts.entry_skill_study run --trades /private/x/trades.json --cache data/alpaca_cache --out /private/x
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
import json
from pathlib import Path
import random
from statistics import pstdev
import sys

from app.engine.factory_rules import CORE_UNIVERSE
from scripts import exit_counterfactual_study as x
from scripts.personal_trading_studies import HOLIDAYS

PROTOCOL_ID = "entry-skill-20261112-v1"
REGISTERED_EXTRACT_SHA256 = "4ada80b1977230773bd0d919cd3ea42f766b8fcc651d5484fee8253de7c33a47"
UNDERLYING = {"SPXW": "SPY", "SPX": "SPY"}
OPEN, CLOSE, EARLY_CLOSE = 570, 960, 780  # minutes after midnight, New York
BUCKETS = ((570, 600), (600, 690), (690, 840), (840, 960))
HORIZONS, PRIMARY = (15, 30, 60), 30
REF_WITHIN = 3  # the reference bar is at entry minute + 1, + 2 or + 3
END_BACK = 3  # the horizon bar, or the latest in the three minutes before it
GAP = 5  # a timing control is at least this many minutes from the entry
DAY_SPAN = 10  # sessions before and after for the day control
MIN_CONTROLS = 5
BASELINES = ("timing", "day", "stock")  # the three tests
EXTRA = ("session",)  # descriptive: timing over the whole session
LEVEL = 1 - 0.05 / len(BASELINES)
MATTERS = 0.10
BOOTSTRAP = 2000
SEED = 20261112
PERIODS = ("exploration", "check")
FEED = "sip"


# ---------------------------------------------------------------- clock and prices


def close_minute(day: date) -> int:
    return EARLY_CLOSE if day in x.EARLY_CLOSES else CLOSE


def underlying(ticker: str) -> str:
    return UNDERLYING.get(ticker, ticker)


def session_bars(raw: list[dict], day: date) -> dict[int, tuple[float, float]]:
    """Regular-session bars of one day as {minute of day: (open, close)}."""
    out = {}
    for bar in raw:
        stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).astimezone(x.ET)
        minute = stamp.hour * 60 + stamp.minute
        if stamp.date() == day and OPEN <= minute < close_minute(day):
            out[minute] = (float(bar["o"]), float(bar["c"]))
    return out


def signed_move(session: dict, minute: int, horizon: int, side: int, close_min: int) -> float | None:
    """The move in the trade's direction, in percent, from the open of the first bar after ``minute`` over ``horizon`` minutes."""
    ref = next((r for r in range(minute + 1, minute + 1 + REF_WITHIN) if r in session), None)
    if ref is None or ref + horizon > close_min:
        return None
    last = ref + horizon - 1
    end = next((e for e in range(last, last - END_BACK - 1, -1) if e >= ref and e in session), None)
    if end is None:
        return None
    return side * (session[end][1] / session[ref][0] - 1) * 100


def timing_minutes(minute: int, close_min: int, whole: bool = False) -> list[int]:
    """Control minutes in the entry's time-of-day bucket (or the whole session), at least GAP minutes away."""
    if whole:
        lo, hi = OPEN, close_min
    else:
        lo, hi = next((a, min(b, close_min)) for a, b in BUCKETS if a <= minute < b)
    return [c for c in range(lo, hi) if abs(c - minute) >= GAP]


def neighbor_sessions(day: date, span: int = DAY_SPAN) -> list[date]:
    """The ``span`` sessions before and the ``span`` after ``day``."""
    out = []
    for step in (-1, 1):
        cursor, found = day, 0
        while found < span:
            cursor += timedelta(days=step)
            if cursor.weekday() < 5 and cursor not in HOLIDAYS:
                out.append(cursor)
                found += 1
    return sorted(out)


def control_mean(values: list) -> float | None:
    scored = [v for v in values if v is not None]
    return sum(scored) / len(scored) if len(scored) >= MIN_CONTROLS else None


# ---------------------------------------------------------------- one trade


def first_entry(fills: list[dict]) -> datetime | None:
    """New York wall-clock time of the first buy_to_open fill."""
    entries = sorted(datetime.fromisoformat(f["executed_at"]) for f in fills if f["side"] == x.ENTRY)
    return entries[0] if entries else None


def last_exit(fills: list[dict]) -> datetime | None:
    exits = sorted(datetime.fromisoformat(f["executed_at"]) for f in fills if f["side"] == x.EXIT)
    return exits[-1] if exits else None


def score_trade(trade: dict, fills: list[dict], bars) -> tuple[dict | None, str | None]:
    """One trade's signed moves and its edge over each control; (None, reason) when it cannot be scored."""
    entry = first_entry(fills)
    if entry is None:
        return None, "no buy_to_open fill"
    day, minute = entry.date(), entry.hour * 60 + entry.minute
    close_min = close_minute(day)
    if not OPEN <= minute < close_min:
        return None, "first entry outside the regular session"
    stock = underlying(trade["ticker"])
    own = bars(stock, day)
    if not own:
        return None, "no minute bars for the underlying on the entry session"
    side = 1 if trade["option_type"] == "call" else -1
    row = {"id": trade["id"], "day": day.isoformat(), "minute": minute, "underlying": stock,
           "side": "call" if side == 1 else "put",
           "period": "exploration" if day < x.CHECK_START else "check",
           "move": {}, "edge": {name: {} for name in BASELINES + EXTRA}}
    for h in HORIZONS:
        move = signed_move(own, minute, h, side, close_min)
        row["move"][str(h)] = move
        if move is None:
            continue
        controls = {
            "timing": [signed_move(own, c, h, side, close_min) for c in timing_minutes(minute, close_min)],
            "session": [signed_move(own, c, h, side, close_min) for c in timing_minutes(minute, close_min, whole=True)],
            "day": [signed_move(s, minute, h, side, close_minute(d))
                    for d in neighbor_sessions(day) if (s := bars(stock, d))],
            "stock": [signed_move(s, minute, h, side, close_min)
                      for t in CORE_UNIVERSE if t != stock and (s := bars(t, day))],
        }
        for name, values in controls.items():
            base = control_mean(values)
            row["edge"][name][str(h)] = None if base is None else move - base
    row["cost"] = contract_cost_row(trade, fills, own, entry, side)
    return row, None


def contract_cost_row(trade: dict, fills: list[dict], own: dict, entry: datetime, side: int) -> dict | None:
    """For a trade closed in its entry session: did the stock move its way by the final exit, and did the option pay?"""
    leave = last_exit(fills)
    premium = float(trade["total_premium_paid"] or 0)
    if trade["status"] != "closed" or leave is None or leave.date() != entry.date() or trade["realized_pnl"] is None or premium <= 0:
        return None
    minute, out = entry.hour * 60 + entry.minute, leave.hour * 60 + leave.minute
    ref = next((r for r in range(minute + 1, minute + 1 + REF_WITHIN) if r in own), None)
    if ref is None:
        return None
    end = next((e for e in range(out, out - END_BACK - 1, -1) if e >= ref and e in own), None)
    if end is None:
        return None
    pnl = float(trade["realized_pnl"])
    return {"stock_right": side * (own[end][1] / own[ref][0] - 1) > 0, "option_won": pnl > 0, "return_pct": pnl / premium * 100}


# ---------------------------------------------------------------- summary


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def edges(rows: list[dict], name: str, horizon: int, **where) -> list[tuple[str, float]]:
    """(day, edge) for every row with an edge on this baseline and horizon, optionally filtered by row fields."""
    return [(r["day"], r["edge"][name][str(horizon)]) for r in rows
            if r["edge"][name].get(str(horizon)) is not None and all(r[k] == v for k, v in where.items())]


def day_interval(pairs: list[tuple[str, float]], rng: random.Random, level: float = LEVEL) -> tuple[list[float], float] | tuple[None, None]:
    """Percentile interval and standard error of the mean, resampling whole trading days."""
    by_day = defaultdict(list)
    for day, value in pairs:
        by_day[day].append(value)
    days = sorted(by_day)
    if not days:
        return None, None
    draws = []
    for _ in range(BOOTSTRAP):
        sample = [v for _ in days for v in by_day[days[rng.randrange(len(days))]]]
        draws.append(sum(sample) / len(sample))
    draws.sort()
    tail = (1 - level) / 2
    low, high = draws[int(tail * len(draws))], draws[min(len(draws) - 1, int((1 - tail) * len(draws)))]
    return [round(low, 4), round(high, 4)], round(pstdev(draws), 4)


def cell(pairs: list[tuple[str, float]]) -> dict:
    values = [v for _, v in pairs]
    return {"n": len(values), "mean": None if not values else round(mean(values), 4)}


def summarize_baseline(rows: list[dict], name: str, rng: random.Random) -> dict:
    primary = edges(rows, name, PRIMARY)
    interval, error = day_interval(primary, rng)
    out = {"n": len(primary), "days": len({d for d, _ in primary}), "interval": interval, "standard_error": error,
           "no_controls": sum(1 for r in rows if r["move"].get(str(PRIMARY)) is not None
                              and r["edge"][name].get(str(PRIMARY)) is None),
           "horizons": {str(h): cell(edges(rows, name, h)) for h in HORIZONS},
           "periods": {p: cell(edges(rows, name, PRIMARY, period=p)) for p in PERIODS},
           "sides": {s: cell(edges(rows, name, PRIMARY, side=s)) for s in ("call", "put")}}
    if name in BASELINES:
        out["decision"] = decide(out)
        out["large_enough_to_matter"] = out["decision"] == "beats chance" and out["horizons"][str(PRIMARY)]["mean"] >= MATTERS
    return out


def decide(b: dict) -> str:
    if not b["interval"]:
        return "no evidence either way"
    low, high = b["interval"]
    above = lambda c: c["mean"] is not None and c["mean"] > 0  # noqa: E731
    if low > 0 and all(above(b["periods"][p]) for p in PERIODS) and all(above(b["horizons"][str(h)]) for h in HORIZONS):
        return "beats chance"
    if high < 0:
        return "worse than chance"
    return "no evidence either way"


def raw_moves(rows: list[dict]) -> dict:
    out = {}
    for label, keep in (("all", None), ("call", "call"), ("put", "put")):
        out[label] = {}
        for h in HORIZONS:
            values = [r["move"][str(h)] for r in rows if r["move"].get(str(h)) is not None and keep in (None, r["side"])]
            out[label][str(h)] = {"n": len(values), "mean": None if not values else round(mean(values), 4),
                                  "above_zero": None if not values else round(sum(v > 0 for v in values) / len(values), 4)}
    return out


def contract_cost(rows: list[dict]) -> dict:
    cells = defaultdict(list)
    for r in rows:
        if r["cost"]:
            key = ("stock right" if r["cost"]["stock_right"] else "stock wrong") + ", " + \
                  ("option won" if r["cost"]["option_won"] else "option lost")
            cells[key].append(r["cost"]["return_pct"])
    return {"covered": sum(len(v) for v in cells.values()),
            "cells": {k: {"n": len(v), "mean_return_pct": round(mean(v), 2)} for k, v in sorted(cells.items())}}


# ---------------------------------------------------------------- data


def load(path: Path) -> tuple[list[dict], dict[str, list[dict]]]:
    data = json.loads(path.read_text())
    if data.get("protocol_id") != x.PROTOCOL_ID:
        raise SystemExit(f"extract is not the {x.PROTOCOL_ID} extract")
    fills = defaultdict(list)
    for f in data["fills"]:
        fills[f["trade_id"]].append(f)
    return data["trades"], fills


def bar_reader(cache: Path):
    @lru_cache(maxsize=8000)
    def read(ticker: str, day: date) -> dict | None:
        path = cache / "stocks" / "1Min" / FEED / ticker / f"{day.isoformat()}.json"
        return session_bars(json.loads(path.read_text()), day) if path.exists() else None
    return read


def needed(trades: list[dict], fills: dict[str, list[dict]]) -> dict[date, set[str]]:
    """The tickers whose minute bars each session needs."""
    out = defaultdict(set)
    for t in trades:
        entry = first_entry(fills.get(t["id"], []))
        if entry is None:
            continue
        day, stock = entry.date(), underlying(t["ticker"])
        out[day].update((stock, *CORE_UNIVERSE))
        for d in neighbor_sessions(day):
            out[d].add(stock)
    return out


def fetch(trades_path: Path, cache: Path) -> dict:
    from app.engine import alpaca
    if alpaca.ALPACA_DATA_FEED != FEED:
        raise SystemExit("set ALPACA_DATA_FEED=sip: the protocol's prices are SIP bars")
    alpaca.CACHE_DIR = cache
    trades, fills = load(trades_path)
    want = needed(trades, fills)
    missing = 0
    for day in sorted(want):
        got = alpaca.fetch_minute_bars_for_date(sorted(want[day]), day)
        missing += sum(1 for t in want[day] if not got.get(t))
    return {"sessions": len(want), "ticker_sessions": sum(len(v) for v in want.values()), "without_bars": missing}


def provenance(trades_path: Path) -> dict:
    receipt = {**x.provenance(trades_path), "protocol_id": PROTOCOL_ID}
    receipt["extract_is_registered"] = receipt["extract_sha256"] == REGISTERED_EXTRACT_SHA256
    return receipt


def run(trades_path: Path, cache: Path, out: Path) -> dict:
    trades, fills = load(trades_path)
    bars = bar_reader(cache)
    rows, excluded = [], defaultdict(int)
    ordered = sorted(trades, key=lambda t: (t["opened_at"], t["id"]))
    for t in ordered:
        row, reason = score_trade(t, fills.get(t["id"], []), bars)
        if row is None:
            excluded[reason] += 1
        else:
            rows.append(row)
    rng = random.Random(SEED)
    results = {"protocol_id": PROTOCOL_ID, "provenance": provenance(trades_path), "extract_trades": len(trades),
               "scored": len(rows), "scored_at_primary": sum(1 for r in rows if r["move"].get(str(PRIMARY)) is not None),
               "excluded": dict(excluded), "level": round(LEVEL, 4),
               "baselines": {name: summarize_baseline(rows, name, rng) for name in BASELINES},
               "descriptive": {"raw_moves": raw_moves(rows),
                               "whole_session_timing": summarize_baseline(rows, "session", rng),
                               "contract_cost": contract_cost(rows)}}
    folder = out / "entry-skill"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(results, indent=2))
    (folder / "trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "run"):
        p = sub.add_parser(name)
        p.add_argument("--trades", type=Path, required=True, help="the exit_counterfactual_study extract")
        p.add_argument("--cache", type=Path, required=True)
        if name == "run":
            p.add_argument("--out", type=Path, required=True, help="a private folder outside the repository")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        print(json.dumps(fetch(args.trades, args.cache), indent=2))
    else:
        print(json.dumps(run(args.trades, args.cache, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
