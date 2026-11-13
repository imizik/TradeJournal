"""Entry horizon study: measured on the stock, do the owner's option entries move
the trade's way over one to five sessions by more than matched control entries?

Protocol, committed before any outcome here was computed:
    research/entry-horizon/protocol.json   entry-horizon-20261112-v1
The clock, the controls and the extract are those of entry-skill-20261112-v1
(``scripts.entry_skill_study``); only the horizons differ: the close of the entry
session and of the sessions 1, 3 and 5 later. Changing a constant below makes a
different study: register a new protocol id rather than editing these.

Read-only. ``fetch`` writes SIP daily closes (raw and split-adjusted) to a data
folder; ``run`` reads them, the extract and the cached SIP minute bars, and
writes ``<out>/entry-horizon/results.json`` and ``trades.jsonl``. Both are
personal and the repository is public: keep ``<out>`` outside it.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.entry_horizon_study fetch --trades /private/x/trades.json --data /private/x/daily --env-file .env
    python -m scripts.entry_horizon_study run --trades /private/x/trades.json --cache data/alpaca_cache --data /private/x/daily --out /private/x
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import random
import sys

from app.engine.factory_rules import CORE_UNIVERSE
from scripts import entry_skill_study as e
from scripts import exit_counterfactual_study as x

PROTOCOL_ID = "entry-horizon-20261112-v1"
HORIZONS, PRIMARY = (0, 1, 3, 5), 1  # sessions after the entry session
AGREE = (0, 3)  # the horizons that must also be above zero
BASELINES = ("day", "stock")
LEVEL = 1 - 0.05 / len(BASELINES)
SPLIT_LEVEL = 0.90
MATTERS = 0.25
BOOTSTRAP = 2000
SEED = 20261112
PERIODS = ("exploration", "check")
DAILY_START, DAILY_END = "2025-06-01", "2026-11-11"


# ---------------------------------------------------------------- prices


def reference(session: dict, minute: int) -> float | None:
    """The open of the first bar after the entry minute (the entry skill study's reference)."""
    return next((session[r][0] for r in range(minute + 1, minute + 1 + e.REF_WITHIN) if r in session), None)


class Daily:
    """Raw and split-adjusted daily closes, {symbol: {day: close}}, over the sessions SPY traded."""

    def __init__(self, raw: dict, split: dict):
        self.raw, self.split = raw, split
        self.sessions = sorted(raw.get("SPY", {}))
        self.index = {d: i for i, d in enumerate(self.sessions)}

    def later(self, day: str, ahead: int) -> str | None:
        i = self.index.get(day)
        return self.sessions[i + ahead] if i is not None and i + ahead < len(self.sessions) else None

    def moves(self, symbol: str, day: str, ref: float | None, side: int) -> dict[str, float | None]:
        """Signed % move from ``ref`` (a raw price on ``day``) to each horizon's close, on one share basis."""
        out = {str(h): None for h in HORIZONS}
        raw, adjusted = self.raw.get(symbol, {}).get(day), self.split.get(symbol, {}).get(day)
        if not ref or not raw or not adjusted:
            return out
        out["0"] = side * (raw / ref - 1) * 100
        basis = ref * adjusted / raw
        for h in HORIZONS[1:]:
            close = self.split.get(symbol, {}).get(self.later(day, h) or "")
            if close:
                out[str(h)] = side * (close / basis - 1) * 100
        return out

    def overnight(self, symbol: str, day: str, side: int) -> float | None:
        """Signed % move from the entry session's close to the next session's close."""
        first, second = self.split.get(symbol, {}).get(day), self.split.get(symbol, {}).get(self.later(day, 1) or "")
        return side * (second / first - 1) * 100 if first and second else None


# ---------------------------------------------------------------- one trade


def score_trade(trade: dict, fills: list[dict], bars, daily: Daily) -> tuple[dict | None, str | None]:
    entry = e.first_entry(fills)
    if entry is None:
        return None, "no buy_to_open fill"
    day, minute = entry.date(), entry.hour * 60 + entry.minute
    if not e.OPEN <= minute < e.close_minute(day):
        return None, "first entry outside the regular session"
    stock = e.underlying(trade["ticker"])
    own = bars(stock, day)
    if not own:
        return None, "no minute bars for the underlying on the entry session"
    side = 1 if trade["option_type"] == "call" else -1
    text = day.isoformat()
    year, week, _ = day.isocalendar()
    row = {"id": trade["id"], "day": text, "week": f"{year}-W{week:02d}", "underlying": stock,
           "side": "call" if side == 1 else "put", "period": "exploration" if day < x.CHECK_START else "check",
           "held": date.fromisoformat(trade["closed_at"][:10]) > day, "overnight": daily.overnight(stock, text, side),
           "move": daily.moves(stock, text, reference(own, minute), side), "edge": {name: {} for name in BASELINES}}
    controls = {
        "day": [daily.moves(stock, d.isoformat(), reference(s, minute), side)
                for d in e.neighbor_sessions(day) if (s := bars(stock, d))],
        "stock": [daily.moves(t, text, reference(s, minute), side)
                  for t in CORE_UNIVERSE if t != stock and (s := bars(t, day))],
    }
    for name, rows in controls.items():
        for h in map(str, HORIZONS):
            base = e.control_mean([r[h] for r in rows])
            row["edge"][name][h] = None if base is None or row["move"][h] is None else row["move"][h] - base
    return row, None


# ---------------------------------------------------------------- summary


def edges(rows: list[dict], name: str, horizon: int, **where) -> list[tuple[str, float]]:
    """(week, edge) for every row with an edge on this baseline and horizon."""
    return [(r["week"], r["edge"][name][str(horizon)]) for r in rows
            if r["edge"][name].get(str(horizon)) is not None and all(r[k] == v for k, v in where.items())]


def summarize_baseline(rows: list[dict], name: str, rng: random.Random) -> dict:
    primary = edges(rows, name, PRIMARY)
    interval, error = e.day_interval(primary, rng, LEVEL)  # the keys are weeks: whole weeks are resampled
    out = {"n": len(primary), "weeks": len({w for w, _ in primary}), "interval": interval, "standard_error": error,
           "no_controls": sum(1 for r in rows if r["move"][str(PRIMARY)] is not None and r["edge"][name][str(PRIMARY)] is None),
           "horizons": {str(h): e.cell(edges(rows, name, h)) for h in HORIZONS},
           "periods": {p: e.cell(edges(rows, name, PRIMARY, period=p)) for p in PERIODS},
           "sides": {s: e.cell(edges(rows, name, PRIMARY, side=s)) for s in ("call", "put")}}
    out["decision"] = decide(out)
    out["large_enough_to_matter"] = out["decision"] == "beats chance" and out["horizons"][str(PRIMARY)]["mean"] >= MATTERS
    return out


def decide(b: dict) -> str:
    if not b["interval"]:
        return "no evidence either way"
    low, high = b["interval"]
    above = lambda c: c["mean"] is not None and c["mean"] > 0  # noqa: E731
    if low > 0 and all(above(b["periods"][p]) for p in PERIODS) and all(above(b["horizons"][str(h)]) for h in AGREE):
        return "beats chance"
    if high < 0:
        return "worse than chance"
    return "no evidence either way"


def hold_choice(rows: list[dict], rng: random.Random) -> dict | None:
    """Held past the entry session minus closed in it: the next-session stock move, resampling whole weeks."""
    by_week = defaultdict(lambda: ([], []))
    for r in rows:
        if r["overnight"] is not None:
            by_week[r["week"]][0 if r["held"] else 1].append(r["overnight"])
    held = [v for a, _ in by_week.values() for v in a]
    closed = [v for _, b in by_week.values() for v in b]
    if not held or not closed:
        return None
    weeks, draws = sorted(by_week), []
    for _ in range(BOOTSTRAP):
        a, b = [], []
        for _ in weeks:
            pick = by_week[weeks[rng.randrange(len(weeks))]]
            a += pick[0]
            b += pick[1]
        if a and b:
            draws.append(sum(a) / len(a) - sum(b) / len(b))
    draws.sort()
    tail = (1 - SPLIT_LEVEL) / 2
    return {"held": {"n": len(held), "mean": round(sum(held) / len(held), 4)},
            "closed_same_session": {"n": len(closed), "mean": round(sum(closed) / len(closed), 4)},
            "difference": round(sum(held) / len(held) - sum(closed) / len(closed), 4),
            "interval": [round(draws[int(tail * len(draws))], 4), round(draws[min(len(draws) - 1, int((1 - tail) * len(draws)))], 4)]}


def raw_moves(rows: list[dict]) -> dict:
    out = {}
    for label in ("all", "call", "put"):
        out[label] = {}
        for h in map(str, HORIZONS):
            values = [r["move"][h] for r in rows if r["move"][h] is not None and label in ("all", r["side"])]
            out[label][h] = {"n": len(values), "mean": None if not values else round(sum(values) / len(values), 4),
                             "above_zero": None if not values else round(sum(v > 0 for v in values) / len(values), 4)}
    return out


# ---------------------------------------------------------------- data and commands


def load_daily(folder: Path) -> Daily:
    data = json.loads((folder / "daily.json").read_text())
    return Daily(data["raw"], data["split"])


def fetch(trades_path: Path, folder: Path, env_file: Path) -> dict:
    import httpx
    from scripts.radar_long_history import alpaca_bars, keys_from
    _, headers = keys_from(env_file)
    trades, _ = e.load(trades_path)
    symbols = sorted({e.underlying(t["ticker"]) for t in trades} | set(CORE_UNIVERSE) | {"SPY"})
    out = {}
    with httpx.Client(timeout=90) as client:
        for adjustment in ("raw", "split"):
            bars = alpaca_bars(client, headers, symbols, "1Day", DAILY_START, DAILY_END + "T23:59:59Z", adjustment)
            out[adjustment] = {s: {b["t"][:10]: b["c"] for b in rows} for s, rows in bars.items()}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "daily.json").write_text(json.dumps(out))
    return {"symbols": len(symbols), "with_bars": len(out["raw"]), "sessions": len(out["raw"].get("SPY", {}))}


def run(trades_path: Path, cache: Path, folder: Path, out: Path) -> dict:
    trades, fills = e.load(trades_path)
    bars, daily = e.bar_reader(cache), load_daily(folder)
    rows, excluded = [], defaultdict(int)
    for t in sorted(trades, key=lambda t: (t["opened_at"], t["id"])):
        row, reason = score_trade(t, fills.get(t["id"], []), bars, daily)
        if row is None:
            excluded[reason] += 1
        else:
            rows.append(row)
    rng = random.Random(SEED)
    results = {"protocol_id": PROTOCOL_ID, "provenance": {**e.provenance(trades_path), "protocol_id": PROTOCOL_ID},
               "extract_trades": len(trades), "scored": len(rows),
               "scored_at_primary": sum(1 for r in rows if r["move"][str(PRIMARY)] is not None),
               "excluded": dict(excluded), "level": LEVEL,
               "baselines": {name: summarize_baseline(rows, name, rng) for name in BASELINES},
               "hold_choice": hold_choice(rows, rng), "descriptive": {"raw_moves": raw_moves(rows)}}
    target = out / "entry-horizon"
    target.mkdir(parents=True, exist_ok=True)
    (target / "results.json").write_text(json.dumps(results, indent=2))
    (target / "trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--trades", type=Path, required=True)
    f.add_argument("--data", type=Path, required=True)
    f.add_argument("--env-file", type=Path, default=Path(".env"))
    r = sub.add_parser("run")
    r.add_argument("--trades", type=Path, required=True)
    r.add_argument("--cache", type=Path, required=True)
    r.add_argument("--data", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True, help="a private folder outside the repository")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        print(json.dumps(fetch(args.trades, args.data, args.env_file), indent=2))
    else:
        print(json.dumps(run(args.trades, args.cache, args.data, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
