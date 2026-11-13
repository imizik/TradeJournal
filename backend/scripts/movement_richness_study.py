"""Movement richness study: did trades whose options priced in much more
movement than the stock had recently been making lose more to movement?

Protocol, committed before any outcome here was computed:
    research/movement-richness/protocol.json   movement-richness-20261113-v1
Changing a constant below makes a different study: register a new protocol id.

Read-only. Richness at entry uses only what was known then: the first entry
fill's price and underlying price, and the stock's minute bars over the 20
sessions before the entry day (the movement price study's profile). The
outcome is each trade's movement from the movement price study's run
(``trades.jsonl``, pinned by hash). ``run`` writes
``<out>/movement-richness/results.json`` and ``trades.jsonl``: personal, keep
them outside the repository.

Run from backend:
    python -m scripts.movement_richness_study run --trades /private/x/trades.json --fills /private/x/fills.json \
        --movement /private/x/movement-price/trades.jsonl --cache data/alpaca_cache --out /private/x
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import random
from statistics import median
import sys

from scripts import entry_skill_study as es
from scripts import exit_counterfactual_study as x
from scripts import movement_price_study as mp

PROTOCOL_ID = "movement-richness-20261113-v1"
REGISTERED_MOVEMENT_SHA256 = "f77e8363a9b78814526691f51d7e26f786e3f5f3af68d0a1a634b025684b76bc"
GROUPS = ("lower", "middle", "upper")
BOOTSTRAP, SEED, LEVEL = 2000, 20261114, 0.95
PERIODS = mp.PERIODS


# ---------------------------------------------------------------- richness at entry (pure)


def daily_variance(days: list[tuple[dict | None, dict | None]]) -> float | None:
    """The stock's average variance of a whole day (night plus session) over the usable profile sessions."""
    used = [v for v in (mp.session_variance(p, s) for p, s in days) if v is not None]
    if len(used) < mp.MIN_PROFILE_SESSIONS:
        return None
    return sum(night + sum(buckets) for night, buckets in used) / len(used)


def richness(entry: dict, trade: dict, shape: dict | None, daily: float | None) -> tuple[float | None, str | None]:
    """Priced variance per typical day from the first entry fill, over the stock's recent variance per day."""
    if shape is None or daily is None:
        return None, "fewer than 10 usable sessions of minute bars in the 20 before entry"
    if entry["underlying"] is None:
        return None, "an entry fill without an underlying price"
    kind, strike = trade["option_type"], float(trade["strike"])
    expiry = mp.close_at(date.fromisoformat(trade["expiration"]))
    left = mp.units(shape, entry["at"], expiry)
    if left <= 0:
        return None, "an entry with no trading time left before expiry"
    sd0 = mp.solve_stdev(float(entry["price"]) / 100, float(entry["underlying"]), strike,
                         mp.RATE * mp.years(entry["at"], expiry), kind)
    if sd0 is None:
        return None, "an entry price no Black-Scholes volatility reproduces"
    if daily <= 0:
        return None, "a stock that did not move in its profile sessions"
    return sd0 ** 2 / left / daily, None


# ---------------------------------------------------------------- summary (pure)


def assign(rows: list[dict]) -> None:
    """Thirds by richness, ties broken by trade id; the middle third takes any remainder."""
    ordered = sorted(rows, key=lambda r: (r["richness"], r["id"]))
    n = len(ordered)
    cuts = (n // 3, n - n // 3)
    for i, r in enumerate(ordered):
        r["group"] = "lower" if i < cuts[0] else "middle" if i < cuts[1] else "upper"


def rate(rows: list[dict], key: str) -> float | None:
    premium = sum(r["premium"] for r in rows)
    return sum(r[key] for r in rows) / premium if premium else None


def gap(rows: list[dict]) -> float | None:
    upper, lower = [r for r in rows if r["group"] == "upper"], [r for r in rows if r["group"] == "lower"]
    a, b = rate(upper, "movement"), rate(lower, "movement")
    return None if a is None or b is None else a - b


def interval(rows: list[dict], rng: random.Random) -> list[float] | None:
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r)
    days = sorted(by_day)
    if not days:
        return None
    draws = []
    for _ in range(BOOTSTRAP):
        sample = [r for _ in days for r in by_day[days[rng.randrange(len(days))]]]
        value = gap(sample)
        if value is not None:
            draws.append(value)
    if not draws:
        return None
    draws.sort()
    tail = (1 - LEVEL) / 2
    return [round(draws[int(tail * len(draws))] * 100, 2), round(draws[min(len(draws) - 1, int((1 - tail) * len(draws)))] * 100, 2)]


def cell(rows: list[dict]) -> dict:
    priced = sum(r["priced"] for r in rows)
    pct = lambda v: None if v is None else round(v * 100, 2)  # noqa: E731
    return {"trades": len(rows), "median_richness": round(median(r["richness"] for r in rows), 3) if rows else None,
            "movement": round(sum(r["movement"] for r in rows), 2), "option_pnl": round(sum(r["option_pnl"] for r in rows), 2),
            "movement_per_premium_pct": pct(rate(rows, "movement")), "option_pnl_per_premium_pct": pct(rate(rows, "option_pnl")),
            "movement_ratio": round(sum(r["moved"] for r in rows) / priced, 3) if priced else None}


def decide(band: list[float] | None, periods: dict) -> str:
    if not band:
        return "no evidence either way"
    signs = [periods[p]["gap_pct"] for p in PERIODS]
    if band[1] < 0 and all(s is not None and s < 0 for s in signs):
        return "richer options lost more to movement"
    if band[0] > 0 and all(s is not None and s > 0 for s in signs):
        return "richer options lost less to movement"
    return "no evidence either way"


def summarize(rows: list[dict]) -> dict:
    assign(rows)
    whole = gap(rows)
    periods = {}
    for p in PERIODS:
        own = [r for r in rows if r["period"] == p]
        value = gap(own)
        periods[p] = {"gap_pct": None if value is None else round(value * 100, 2), **{g: cell([r for r in own if r["group"] == g]) for g in GROUPS}}
    band = interval(rows, random.Random(SEED))
    held = {h: {g: cell([r for r in rows if r["held"] == h and r["group"] == g]) for g in GROUPS} for h in sorted({r["held"] for r in rows})}
    bounds = {g: [round(min(r["richness"] for r in rows if r["group"] == g), 3), round(max(r["richness"] for r in rows if r["group"] == g), 3)]
              for g in GROUPS if any(r["group"] == g for r in rows)}
    return {"gap_pct": None if whole is None else round(whole * 100, 2), "interval_pct": band, "periods": periods,
            "decision": decide(band, periods), "groups": {g: cell([r for r in rows if r["group"] == g]) for g in GROUPS},
            "descriptive": {"richness_bounds": bounds, "held": held,
                            "share_richer_than_recent_pct": round(sum(r["richness"] > 1 for r in rows) / len(rows) * 100, 1) if rows else None}}


# ---------------------------------------------------------------- command


def run(trades_path: Path, fills_path: Path, movement_path: Path, cache: Path, out: Path) -> dict:
    data = json.loads(trades_path.read_text())
    if data.get("protocol_id") != x.PROTOCOL_ID:
        raise SystemExit(f"extract is not the {x.PROTOCOL_ID} extract")
    extra = {f["fill_id"]: f for f in json.loads(fills_path.read_text())}
    outcome = {r["id"]: r for r in map(json.loads, movement_path.read_text().splitlines()) if not r["earnings"]}
    trades = {t["id"]: t for t in data["trades"]}
    entries = {}
    for f in sorted(data["fills"], key=lambda f: (f["executed_at"], f["fill_id"])):
        if f["side"] == x.ENTRY and f["trade_id"] not in entries:
            entries[f["trade_id"]] = {"at": datetime.fromisoformat(f["executed_at"]), "price": f["price"],
                                      "underlying": extra.get(f["fill_id"], {}).get("underlying")}
    bars = es.bar_reader(cache)
    rows, excluded, memo = [], defaultdict(int), {}
    for tid in sorted(outcome, key=lambda i: (outcome[i]["day"], i)):
        trade, entry = trades[tid], entries.get(tid)
        stock = mp.BARS.get(trade["ticker"], trade["ticker"])
        first = date.fromisoformat(outcome[tid]["day"])
        if (stock, first) not in memo:
            days = mp.sessions_before(first, mp.PROFILE_SESSIONS + 1)
            pairs = [(bars(stock, a), bars(stock, b)) for a, b in zip(days, days[1:])]
            memo[(stock, first)] = (mp.profile(pairs), daily_variance(pairs))
        shape, daily = memo[(stock, first)]
        value, reason = (None, "no first entry fill") if entry is None else richness(entry, trade, shape, daily)
        if value is None:
            excluded[reason] += 1
            continue
        rows.append({**{k: outcome[tid][k] for k in ("id", "day", "period", "held", "dte", "side", "movement", "option_pnl",
                                                    "premium", "moved", "priced")}, "richness": round(value, 6)})
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    receipt = {**x.provenance(trades_path), "protocol_id": PROTOCOL_ID, "fills_sha256": digest(fills_path),
               "movement_sha256": digest(movement_path)}
    receipt["inputs_are_registered"] = (receipt["extract_sha256"], receipt["fills_sha256"], receipt["movement_sha256"]) == (
        mp.REGISTERED_EXTRACT_SHA256, mp.REGISTERED_FILLS_SHA256, REGISTERED_MOVEMENT_SHA256)
    results = {"protocol_id": PROTOCOL_ID, "provenance": receipt, "outcome_trades": len(outcome), "scored": len(rows),
               "excluded": dict(excluded), **summarize(rows)}
    folder = out / "movement-richness"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(results, indent=2))
    (folder / "trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    for name in ("--trades", "--fills", "--movement", "--cache", "--out"):
        r.add_argument(name, type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.trades, args.fills, args.movement, args.cache, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
