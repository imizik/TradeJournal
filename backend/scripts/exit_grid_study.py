"""Exit settings grid: does one simple combination of give-back, loss stop and
expiry-day exit beat the actual exits on long option trades, and does the best
one found on older trades hold up on newer ones?

Protocol ``exit-grid-20261120-v1`` (kept with the private results, not in the
repo) was written before any outcome here was computed. Changing a constant
below makes a different study.

It reuses the replay of ``exit_counterfactual_study``: the FIFO position from
the actual fills, judged at regular-session bar closes, sold at the next
minute's open less the 3% haircut (9% stress). Read-only: ``extract`` turns
JSON already pulled from the app's GET endpoints (``/trades`` and
``/trades/fills/bulk``) into the study's extract; nothing here calls the
journal, writes it, or places or suggests an order.

Run from backend:
    python -m scripts.exit_grid_study extract --trades trades.json --fills fills.json --out x/extract.json
    python -m scripts.exit_grid_study search --extract x/extract.json --cache data/alpaca_cache --out x
    python -m scripts.exit_grid_study exam --extract x/extract.json --cache data/alpaca_cache --out x --combo 30,40,12:00
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, date, datetime, time as day_time, timedelta
from decimal import Decimal
from itertools import product
import json
from pathlib import Path
import random
import sys

from scripts import exit_counterfactual_study as cf

PROTOCOL_ID = "exit-grid-20261120-v1"
SPLIT = date(2026, 10, 24)  # search: opened before; exam: opened on or after
GIVEBACKS = (None, Decimal("0.30"), Decimal("0.40"), Decimal("0.50"))  # share of peak profit
ARM = Decimal("0.20")  # give-back only once the peak gain reached +20%
LOSS_STOPS = (None, Decimal("0.40"), Decimal("0.60"))  # of entry premium
EXPIRY_TIMES = (None, day_time(12), day_time(15, 30))  # ET on the expiration day
COMBOS = tuple(product(GIVEBACKS, LOSS_STOPS, EXPIRY_TIMES))
BOOTSTRAP = 2000
SEED = 20261120
LEVEL = 0.95
MOSTLY = 0.80  # share of bootstrap draws above zero that counts as "mostly above zero"


def combo_name(combo) -> str:
    giveback, loss, expiry = combo
    return "/".join([
        f"giveback {int(giveback * 100)}%" if giveback is not None else "no giveback",
        f"stop -{int(loss * 100)}%" if loss is not None else "no stop",
        f"expiry {expiry:%H:%M}" if expiry is not None else "no expiry exit",
    ])


def parse_combo(text: str):
    giveback, loss, expiry = text.split(",")
    return (None if giveback == "none" else Decimal(giveback) / 100,
            None if loss == "none" else Decimal(loss) / 100,
            None if expiry == "none" else day_time.fromisoformat(expiry))


def combo_trigger(combo, trade: dict, judged: list) -> datetime | None:
    """Earliest moment any part of the combo says sell (a bar close, or the expiry-day clock)."""
    giveback, loss, expiry = combo
    fired, peak = None, None
    if giveback is not None or loss is not None:
        for bar, _gain, pct in judged:
            peak = pct if peak is None else max(peak, pct)
            if (loss is not None and pct <= -loss) or (
                    giveback is not None and peak >= ARM and pct <= (1 - giveback) * peak):
                fired = bar["t"] + timedelta(minutes=1)
                break
    if expiry is not None:
        at = datetime.combine(trade["expiration"], expiry, cf.ET).astimezone(UTC)
        if at < cf.session_close(trade["expiration"]) and (fired is None or at < fired):
            fired = at
    return fired


def prepare(trade: dict, fills: list[dict], bars: list[dict]):
    """The replay's inputs for one trade, as ``cf.simulate_trade`` builds them."""
    position = cf.Position(fills)
    actual_pnl, _ = cf.actual_outcome(position)
    end = position.final_exit if trade["status"] == "closed" else cf.session_close(trade["expiration"])
    if end is None:
        end = cf.et(trade["closed_at"])
    bars = sorted((b for b in bars if b["t"] < end), key=lambda b: b["t"])
    return position, actual_pnl, end, bars, [b["t"] for b in bars], cf.judged_bars(position, bars, end)


def combo_diffs(combo, trade, prepared) -> tuple[float, float] | None:
    """(difference vs actual at 3%, at 9%), or None when the combo never sells this trade."""
    position, actual_pnl, end, bars, stamps, judged = prepared
    at = combo_trigger(combo, trade, judged)
    if at is None:
        return None
    base = cf.execute(position, bars, stamps, at, end, cf.COST_BASE)
    if base is None:
        return None
    stress = cf.execute(position, bars, stamps, at, end, cf.COST_STRESS)
    return float(base["pnl"] - actual_pnl), float(stress["pnl"] - actual_pnl)


# ---------------------------------------------------------------- statistics


def bootstrap(by_day: dict[str, float], rng: random.Random) -> dict:
    """Day-resampled total: 95% range and the share of draws above zero."""
    days = sorted(by_day)
    draws = sorted(sum(by_day[days[rng.randrange(len(days))]] for _ in days) for _ in range(BOOTSTRAP))
    tail = (1 - LEVEL) / 2
    return {"range": [round(draws[int(tail * len(draws))], 2), round(draws[min(len(draws) - 1, int((1 - tail) * len(draws)))], 2)],
            "share_above_zero": round(sum(1 for d in draws if d > 0) / len(draws), 3)}


def summarize(rows: list[dict], key: str, rng: random.Random | None) -> dict:
    by_day = defaultdict(float)
    touched = []
    for row in rows:
        by_day[row["day"]] += 0.0  # every day of the set is in the resampling
        result = row[key]
        if result is None:
            continue
        by_day[row["day"]] += result[0]
        touched.append(result)
    diffs = [d for d, _ in touched]
    out = {"trades": len(rows), "touched": len(touched), "dollar_diff": round(sum(diffs), 2),
           "dollar_diff_stress": round(sum(s for _, s in touched), 2),
           "saved": sum(1 for d in diffs if d > 0), "cost": sum(1 for d in diffs if d < 0),
           "biggest_trade": round(max(diffs), 2) if diffs else None,
           "without_biggest": round(sum(diffs) - max(diffs), 2) if diffs else 0.0}
    if rng is not None and touched:
        out.update(bootstrap(by_day, rng))
    return out


def passes(summary: dict) -> bool:
    return (summary["dollar_diff"] > 0 and summary.get("share_above_zero", 0) >= MOSTLY
            and summary["without_biggest"] > 0)


# ---------------------------------------------------------------- data


def build_extract(trades: list[dict], fills_by_trade: dict[str, list[dict]]) -> dict:
    """The study's extract from the app's ``/trades`` and ``/trades/fills/bulk`` JSON."""
    keep = [t for t in trades if t["instrument_type"] == "option" and t["status"] in ("closed", "expired")]
    keep.sort(key=lambda t: (t["opened_at"], t["id"]))
    fields = ("id", "ticker", "option_type", "strike", "expiration", "status", "opened_at", "closed_at",
              "realized_pnl", "total_premium_paid", "account_id")
    fills = [{"trade_id": t["id"], "fill_id": f["id"], "role": None, "side": f["side"],
              "contracts": f["contracts"], "price": f["price"], "executed_at": f["executed_at"]}
             for t in keep for f in fills_by_trade.get(t["id"], [])]
    fills.sort(key=lambda f: (f["executed_at"], f["fill_id"]))
    return {"protocol_id": PROTOCOL_ID, "trades": [{k: t.get(k) for k in fields} for t in keep], "fills": fills}


def replay_inputs(extract: Path, cache: Path, fetch: bool):
    """(trade, its fills, its bars) for every usable trade, plus exclusion counts."""
    trades, fills, excluded = cf.load_extract(extract, PROTOCOL_ID)
    usable = []
    for trade in trades:
        symbol = cf.occ(trade["ticker"], trade["expiration"], trade["option_type"], trade["strike"])
        start, end = cf.et(trade["opened_at"]), cf.et(trade["closed_at"])
        bars = cf.cached_bars(cache, symbol, start, end)
        if bars is None and fetch:
            bars = cf.fetch_bars(cache, symbol, start, end) or None
        if not bars:
            excluded["no option minute bars"] = excluded.get("no option minute bars", 0) + 1
            continue
        usable.append((trade, fills[trade["id"]], bars))
    return usable, excluded


def in_exam(trade: dict) -> bool:
    return datetime.fromisoformat(trade["opened_at"]).date() >= SPLIT


def search(extract: Path, cache: Path, out: Path, fetch: bool) -> dict:
    usable, excluded = replay_inputs(extract, cache, fetch)
    rows = []
    for trade, fills, bars in usable:
        if in_exam(trade):
            continue
        try:
            prepared = prepare(trade, fills, bars)
        except ValueError:
            excluded["fills do not allocate FIFO"] = excluded.get("fills do not allocate FIFO", 0) + 1
            continue
        row = {"id": trade["id"], "day": trade["opened_at"][:10], "actual_pnl": float(prepared[1])}
        for combo in COMBOS:
            row[combo_name(combo)] = combo_diffs(combo, trade, prepared)
        rows.append(row)
    rng = random.Random(SEED)
    grid = {combo_name(c): summarize(rows, combo_name(c), None) for c in COMBOS if any(c)}
    best = max(grid, key=lambda name: grid[name]["dollar_diff"])
    grid[best] = summarize(rows, best, rng)
    results = {"protocol_id": PROTOCOL_ID, "set": "search", "trades": len(rows), "excluded": excluded,
               "actual_total": round(sum(r["actual_pnl"] for r in rows), 2), "best": best,
               "goes_to_exam": grid[best]["dollar_diff"] > 0, "grid": grid}
    out.mkdir(parents=True, exist_ok=True)
    (out / "results-search.json").write_text(json.dumps(results, indent=2, default=str))
    return results


def exam(extract: Path, cache: Path, out: Path, fetch: bool, combo) -> dict:
    target = out / "results-exam.json"
    if target.exists():
        raise SystemExit("the exam runs once: results-exam.json already exists")
    usable, excluded = replay_inputs(extract, cache, fetch)
    name = combo_name(combo)
    rows, rng_live = [], random.Random(SEED)
    for trade, fills, bars in usable:
        if not in_exam(trade):
            continue
        try:
            prepared = prepare(trade, fills, bars)
            live = cf.simulate_trade(trade, fills, bars, rng_live)
        except ValueError:
            excluded["fills do not allocate FIFO"] = excluded.get("fills do not allocate FIFO", 0) + 1
            continue
        row = {"id": trade["id"], "day": trade["opened_at"][:10], "ticker": trade["ticker"],
               "actual_pnl": float(prepared[1]), name: combo_diffs(combo, trade, prepared)}
        for rule in cf.RULES:
            result = live["rules"][rule]
            row[f"live {rule}"] = None if result is None else (result["diff"], result["diff_stress"])
        rows.append(row)
    rng = random.Random(SEED)
    chosen = summarize(rows, name, rng)
    results = {"protocol_id": PROTOCOL_ID, "set": "exam", "trades": len(rows), "excluded": excluded,
               "actual_total": round(sum(r["actual_pnl"] for r in rows), 2), "combo": name, "chosen": chosen,
               "passes": passes(chosen),
               "live_baseline": {rule: summarize(rows, f"live {rule}", rng) for rule in cf.RULES},
               "rows": rows}
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, indent=2, default=str))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--trades", type=Path, required=True)
    e.add_argument("--fills", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    for name in ("search", "exam"):
        p = sub.add_parser(name)
        p.add_argument("--extract", type=Path, required=True)
        p.add_argument("--cache", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--fetch", action="store_true", help="fetch an uncached window from Alpaca (market data only)")
        if name == "exam":
            p.add_argument("--combo", required=True, help="giveback%%,stop%%,HH:MM with 'none' for an unused part")
    args = parser.parse_args(argv)
    if args.command == "extract":
        payload = build_extract(json.loads(args.trades.read_text()), json.loads(args.fills.read_text()))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload))
        return
    if args.command == "search":
        results = search(args.extract, args.cache, args.out, args.fetch)
        print(json.dumps({k: v for k, v in results.items() if k != "grid"} | {"best_summary": results["grid"][results["best"]]}, indent=2))
    else:
        results = exam(args.extract, args.cache, args.out, args.fetch, parse_combo(args.combo))
        print(json.dumps({k: v for k, v in results.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
