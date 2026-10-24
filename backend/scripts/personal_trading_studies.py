"""Personal trading studies on the exit-counterfactual extract: stopping once
the day is green, a position-size cap, and exiting long holds sooner.

Protocols, committed before any outcome here was computed:
    research/stop-after-green/protocol.json   stop-after-green-20261024-v1
    research/size-cap/protocol.json           size-cap-20261024-v1
    research/long-holds/protocol.json         long-holds-20261024-v1
Changing a constant below makes a different study: register a new protocol id
rather than editing these. Every result is exploratory: the October 21 audit
read both periods.

Read-only. Each command reads the extract written by
``python -m scripts.exit_counterfactual_study extract`` (the same file that study
ran on); ``long-holds`` also reads the Alpaca option daily-bar cache, fetching a
missing window only with ``--fetch``. Each writes ``<out>/<study>/results.json``
(aggregates) and ``trades.jsonl`` (per trade, personal: keep it out of git).
Nothing here writes the journal, places or suggests an order.

Run from backend:
    python -m scripts.personal_trading_studies stop-after-green --trades /tmp/x/trades.json --out /tmp/x
    python -m scripts.personal_trading_studies size-cap --trades /tmp/x/trades.json --out /tmp/x
    python -m scripts.personal_trading_studies long-holds --trades /tmp/x/trades.json --cache data/alpaca_cache --out /tmp/x
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import groupby
import json
from pathlib import Path
import random
from statistics import median
import sys

from scripts import exit_counterfactual_study as x

STOP_ID = "stop-after-green-20261024-v1"
CAP_ID = "size-cap-20261024-v1"
LONG_ID = "long-holds-20261024-v1"
REGISTERED_EXTRACT_SHA256 = "023e0e11302cdc685f789dfd452d103feeb36d87385232c819fc8eedb1878eda"
SEED = x.SEED
BOOTSTRAP = x.BOOTSTRAP
PERIODS = ("exploration", "check")

STOP_RULES = {"stop_above_0": Decimal(0), "stop_above_250": Decimal(250), "stop_above_500": Decimal(500)}
STOP_LEVEL = 1 - 0.05 / len(STOP_RULES)

CAP_RULES = {"cap_1_5x": Decimal("1.5"), "cap_2x": Decimal(2)}
CAP_LEVEL = 1 - 0.05 / len(CAP_RULES)
TRAILING = 20

LONG_RULES = {"exit_session_1": 1, "exit_session_3": 3, "exit_session_5": 5}  # x.LEVEL: Bonferroni across 3
MISSING_BAR_SESSIONS = 2
MIN_PERIOD_TOUCHED = 5
HOLIDAYS = {date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25), date(2026, 1, 1),
            date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
            date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}


# ---------------------------------------------------------------- data


def load_trades(path: Path) -> tuple[list[dict], dict]:
    """Every long option trade in the extract, replayed FIFO; nothing filtered by holding window."""
    data = json.loads(path.read_text())
    if data.get("protocol_id") != x.PROTOCOL_ID:
        raise SystemExit(f"extract is not the {x.PROTOCOL_ID} extract")
    fills = defaultdict(list)
    for f in data["fills"]:
        fills[f["trade_id"]].append({"side": f["side"], "contracts": Decimal(str(f["contracts"])),
                                     "price": Decimal(str(f["price"])), "at": x.et(f["executed_at"]),
                                     "role": f["role"]})
    trades, excluded = [], defaultdict(int)
    for t in data["trades"]:
        own = fills.get(t["id"], [])
        if not own or any(f["side"] not in (x.ENTRY, x.EXIT) for f in own):
            excluded["not a long option (side other than buy_to_open/sell_to_close)"] += 1
            continue
        position = x.Position(own)
        try:
            pnl, premium = x.actual_outcome(position)
        except ValueError:
            excluded["fills do not allocate FIFO"] += 1
            continue
        day = position.first_entry.astimezone(x.ET).date()
        t.update(expiration=date.fromisoformat(t["expiration"]) if t["expiration"] else None,
                 position=position, pnl=pnl, premium=premium, first_entry=position.first_entry,
                 closed=x.et(t["closed_at"]), day=day, period="check" if day >= x.CHECK_START else "exploration",
                 window_days=(x.et(t["closed_at"]).date() - x.et(t["opened_at"]).date()).days + 1)
        trades.append(t)
    return trades, dict(excluded)


def provenance(protocol_id: str, trades_path: Path) -> dict:
    receipt = {**x.provenance(trades_path), "protocol_id": protocol_id}
    receipt["extract_is_registered"] = receipt["extract_sha256"] == REGISTERED_EXTRACT_SHA256
    return receipt


def recorded_mismatch(trades: list[dict]) -> int:
    return sum(1 for t in trades if t["realized_pnl"] is not None and abs(float(t["realized_pnl"]) - float(t["pnl"])) > 0.5)


def write(out: Path, study: str, results: dict, rows: list[dict]) -> dict:
    folder = out / study
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(results, indent=2))
    (folder / "trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return results


# ---------------------------------------------------------------- scaled trades (stop and cap)


def stop_skips(trades: list[dict], threshold: Decimal) -> set[str]:
    """Trades not taken: first entry strictly after the close that lifts the day's realized P&L above ``threshold``."""
    opened, closes = defaultdict(list), defaultdict(list)
    for t in trades:
        opened[t["day"]].append(t)
        closes[t["closed"].astimezone(x.ET).date()].append(t)
    skipped: set[str] = set()
    for day in sorted(set(opened) | set(closes)):
        realized, trigger = Decimal(0), None
        kept = sorted((t for t in closes.get(day, []) if t["id"] not in skipped), key=lambda t: t["closed"])
        for at, group in groupby(kept, key=lambda t: t["closed"]):
            realized += sum(t["pnl"] for t in group)
            if realized > threshold:
                trigger = at
                break
        if trigger is not None:
            skipped |= {t["id"] for t in opened.get(day, []) if t["first_entry"] > trigger}
    return skipped


def cap_references(trades: list[dict]) -> dict[str, Decimal | None]:
    """Median entry premium already paid, as of each trade's first entry, by the 20 trades opened before it."""
    ordered = sorted(trades, key=lambda t: (t["first_entry"], t["id"]))
    refs: dict[str, Decimal | None] = {}
    for i, t in enumerate(ordered):
        prior = ordered[i - TRAILING:i] if i >= TRAILING else None
        refs[t["id"]] = median(p["position"].state(t["first_entry"])[2] for p in prior) if prior else None
    return refs


def cap_factor(premium: Decimal, reference: Decimal | None, multiple: Decimal) -> Decimal:
    if reference is None or premium <= 0:
        return Decimal(1)
    return min(Decimal(1), multiple * reference / premium)


def scaled_sums(records: list[dict], rule: str) -> tuple[float, float, float, float]:
    """(actual P&L, actual premium, dollar difference, counterfactual premium)."""
    pnl = premium = diff = kept = 0.0
    for r in records:
        f = r["factors"][rule]
        pnl += r["pnl"]
        premium += r["premium"]
        diff += (f - 1) * r["pnl"]
        kept += f * r["premium"]
    return pnl, premium, diff, kept


def scaled_values(pnl: float, premium: float, diff: float, kept: float) -> tuple[float, float]:
    """(dollar difference, selection value): the difference less a flat cut of the same premium from every trade."""
    flat = (kept / premium - 1) * pnl if premium else 0.0
    return diff, diff - flat


def bootstrap_intervals(by_day: dict[str, list[dict]], statistic, rng: random.Random, level: float) -> list[list[float]]:
    """Day-clustered percentile intervals for each value the statistic returns."""
    days = sorted(by_day)
    draws = []
    for _ in range(BOOTSTRAP):
        draws.append(statistic([r for _ in days for r in by_day[days[rng.randrange(len(days))]]]))
    tail = (1 - level) / 2
    out = []
    for column in zip(*draws):
        column = sorted(column)
        out.append([round(column[int(tail * len(column))], 2),
                    round(column[min(len(column) - 1, int((1 - tail) * len(column)))], 2)])
    return out


def mean_pct(records: list[dict]) -> float | None:
    values = [r["pct"] for r in records if r["pct"] is not None]
    return sum(values) / len(values) if values else None


def summarize_scaled(records: list[dict], rule: str, rng: random.Random, level: float) -> dict:
    affected = [r for r in records if r["factors"][rule] < 1]
    others = [r for r in records if r["factors"][rule] >= 1]
    premium = sum(r["premium"] for r in records)
    cf_premium = sum(r["factors"][rule] * r["premium"] for r in records)
    pnl = sum(r["pnl"] for r in records)
    cf_pnl = sum(r["factors"][rule] * r["pnl"] for r in records)
    diff, selection = scaled_values(*scaled_sums(records, rule))
    by_day = defaultdict(list)
    for r in records:
        by_day[r["day"]].append(r)
    day_sums = {day: [scaled_sums(rows, rule)] for day, rows in by_day.items()}
    worst = defaultdict(lambda: [0.0, 0.0])
    for r in records:
        worst[r["day"]][0] += r["pnl"]
        worst[r["day"]][1] += r["factors"][rule] * r["pnl"]
    affected_pct, other_pct = mean_pct(affected), mean_pct(others)
    out = {
        "trades": len(records), "affected": len(affected),
        "actual_pnl": round(pnl, 2), "counterfactual_pnl": round(cf_pnl, 2),
        "dollar_diff": round(diff, 2), "affected_pnl": round(sum(r["pnl"] for r in affected), 2),
        "premium_removed": round(premium - cf_premium, 2),
        "rop_actual": round(pnl / premium * 100, 2) if premium else None,
        "rop_counterfactual": round(cf_pnl / cf_premium * 100, 2) if cf_premium else None,
        "rop_diff": round((cf_pnl / cf_premium - pnl / premium) * 100, 2) if premium and cf_premium else None,
        "affected_pct_mean": None if affected_pct is None else round(affected_pct, 2),
        "others_pct_mean": None if other_pct is None else round(other_pct, 2),
        "pct_gap": None if affected_pct is None or other_pct is None else round(affected_pct - other_pct, 2),
        "flat_cut_diff": round(diff - selection, 2), "selection_value": round(selection, 2),
        "largest_loss": [round(min((r["pnl"] for r in records), default=0), 2),
                         round(min((r["factors"][rule] * r["pnl"] for r in records), default=0), 2)],
        "worst_day": [round(min((v[0] for v in worst.values()), default=0), 2),
                      round(min((v[1] for v in worst.values()), default=0), 2)],
    }
    if affected:
        out["dollar_diff_interval"], out["selection_value_interval"] = bootstrap_intervals(
            day_sums, lambda sample: scaled_values(*(sum(column) for column in zip(*sample))), rng, level)
    return out


def decide_stop(full: dict, periods: dict[str, dict]) -> str:
    if not full["affected"]:
        return "no trades skipped"
    low, high = full["dollar_diff_interval"]
    if high < 0:
        return "reject: stopping once green would have cost money"
    supported = low > 0 and all(p["affected"] and p["dollar_diff"] > 0 and (p["rop_diff"] or 0) > 0
                                and p["pct_gap"] is not None and p["pct_gap"] < 0 for p in periods.values())
    if not supported:
        return "reject as a demonstrated saving (interval includes 0 or periods disagree)"
    if full["selection_value_interval"][0] > 0:
        return "eligible for prospective testing as a daily stop"
    return "investigate further: the saving is trading less, not stopping once green"


def decide_cap(full: dict, periods: dict[str, dict]) -> str:
    if not full["affected"]:
        return "no trades capped"
    low, high = full["dollar_diff_interval"]
    if high < 0:
        return "reject: the cap would have cost money"
    supported = low > 0 and all(p["affected"] and p["dollar_diff"] > 0 and (p["rop_diff"] or 0) > 0
                                for p in periods.values())
    if not supported:
        return "reject as a demonstrated saving (interval includes 0 or periods disagree)"
    if full["selection_value_interval"][0] > 0:
        return "eligible for prospective testing as a size cap"
    return "investigate further: the saving is trading smaller overall, not capping the large trades"


def scaled_record(t: dict, factors: dict[str, Decimal]) -> dict:
    return {"id": t["id"], "day": t["day"].isoformat(), "period": t["period"], "pnl": float(t["pnl"]),
            "premium": float(t["premium"]), "pct": float(t["pnl"] / t["premium"] * 100) if t["premium"] else None,
            "factors": {rule: float(f) for rule, f in factors.items()}}


def run_scaled(protocol_id: str, study: str, rules: dict, factors_for, level: float, decide,
               trades_path: Path, out: Path) -> dict:
    trades, excluded = load_trades(trades_path)
    rng = random.Random(SEED)
    factors = factors_for(trades)
    records = [scaled_record(t, {rule: factors[rule][t["id"]] for rule in rules}) for t in trades]
    results = {"protocol_id": protocol_id, "provenance": provenance(protocol_id, trades_path),
               "extract_trades": len(trades) + sum(excluded.values()), "analyzed": len(records),
               "excluded": excluded, "recorded_pnl_mismatch": recorded_mismatch(trades),
               "actual_total": round(sum(r["pnl"] for r in records), 2), "rules": {}}
    for rule in rules:
        periods = {name: summarize_scaled([r for r in records if r["period"] == name], rule, rng, level)
                   for name in PERIODS}
        full = summarize_scaled(records, rule, rng, level)
        results["rules"][rule] = {"all": full, **periods, "decision": decide(full, periods)}
    return write(out, study, results, records)


def stop_factors(trades: list[dict]) -> dict[str, dict[str, Decimal]]:
    out = {}
    for rule, threshold in STOP_RULES.items():
        skipped = stop_skips(trades, threshold)
        out[rule] = {t["id"]: Decimal(0) if t["id"] in skipped else Decimal(1) for t in trades}
    return out


def cap_factors(trades: list[dict]) -> dict[str, dict[str, Decimal]]:
    refs = cap_references(trades)
    return {rule: {t["id"]: cap_factor(t["premium"], refs[t["id"]], multiple) for t in trades}
            for rule, multiple in CAP_RULES.items()}


def run_stop(trades_path: Path, out: Path) -> dict:
    return run_scaled(STOP_ID, "stop-after-green", STOP_RULES, stop_factors, STOP_LEVEL, decide_stop, trades_path, out)


def run_cap(trades_path: Path, out: Path) -> dict:
    return run_scaled(CAP_ID, "size-cap", CAP_RULES, cap_factors, CAP_LEVEL, decide_cap, trades_path, out)


# ---------------------------------------------------------------- long holds


def sessions_from(day: date, count: int) -> list[date]:
    out = []
    while len(out) < count:
        if day.weekday() < 5 and day not in HOLIDAYS:
            out.append(day)
        day += timedelta(days=1)
    return out


def session_exit(position: x.Position, closes: dict[date, Decimal], n: int, end: datetime, cost: Decimal) -> dict | None:
    """Sell everything still open at the close of session n (or of the next two sessions with a bar)."""
    candidates = sessions_from(position.first_entry.astimezone(x.ET).date(), n + MISSING_BAR_SESSIONS)[n - 1:]
    day = next((d for d in candidates if d in closes), None)
    if day is None:
        return None
    at = x.session_close(day)
    if at >= end:
        return None
    realized, lots, premium = position.state(at)
    if not lots:
        return None
    price = x.haircut_price(closes[day], cost)
    pnl = realized + sum(q * (price - p) for q, p in lots)
    return {"exit_day": day.isoformat(), "exit_price": float(price), "pnl": pnl, "premium": premium}


def simulate_long(trade: dict, bars: list[dict]) -> dict:
    position = trade["position"]
    actual_pnl, actual_premium = trade["pnl"], trade["premium"]
    end = position.final_exit if trade["status"] == "closed" else x.session_close(trade["expiration"])
    if end is None:
        end = trade["closed"]
    closes = {b["t"].astimezone(x.ET).date(): b["c"] for b in bars}
    row = {"id": trade["id"], "day": trade["day"].isoformat(), "period": trade["period"],
           "window_days": trade["window_days"], "actual_pnl": float(actual_pnl), "actual_premium": float(actual_premium),
           "actual_pct": float(actual_pnl / actual_premium * 100) if actual_premium else None, "rules": {}}
    for rule, n in LONG_RULES.items():
        base = session_exit(position, closes, n, end, x.COST_BASE)
        if base is None:
            row["rules"][rule] = None
            continue
        stress = session_exit(position, closes, n, end, x.COST_STRESS)
        row["rules"][rule] = {
            "exit_day": base["exit_day"], "exit_price": base["exit_price"],
            "diff": float(base["pnl"] - actual_pnl), "diff_stress": float(stress["pnl"] - actual_pnl),
            "cf_pct": float(base["pnl"] / base["premium"] * 100) if base["premium"] else None,
            "random_diff": None,  # no random benchmark registered for this study
        }
    return row


def summarize_long(rows: list[dict], rule: str, rng: random.Random) -> dict:
    out = x.summarize(rows, rule, rng)  # x.LEVEL is Bonferroni across 3, as registered here
    for key in ("timing_value", "random_dollar_diff"):
        out.pop(key, None)
    touched = [(row["actual_pnl"], row["rules"][rule]["diff"]) for row in rows if row["rules"][rule]]
    out["diff_on_losers"] = round(sum(d for pnl, d in touched if pnl < 0), 2)
    out["diff_on_winners"] = round(sum(d for pnl, d in touched if pnl >= 0), 2)
    return out


def decide_long(full: dict, periods: dict[str, dict]) -> str:
    if not full["touched"]:
        return "no trades touched"
    low, high = full["dollar_diff_interval"]
    if high < 0:
        return "reject: exiting by that session would have cost money"
    if low <= 0:
        return "reject as a demonstrated saving (interval includes 0 or periods disagree)"
    if any(p["touched"] < MIN_PERIOD_TOUCHED for p in periods.values()):
        return "investigate further: too few long holds in a period to check consistency"
    if full["dollar_diff_stress"] > 0 and all(p["dollar_diff"] > 0 and (p["pct_diff_mean"] or 0) > 0
                                              for p in periods.values()):
        return "eligible for prospective testing as a hold limit"
    return "reject as a demonstrated saving (interval includes 0 or periods disagree)"


def window_day(part: str) -> date:
    """A cache file name's window bound: a date, or an ET timestamp as app.engine.alpaca writes it."""
    try:
        return date.fromisoformat(part)
    except ValueError:
        return datetime.strptime(part, "%Y-%m-%dT%H%M%S%z").astimezone(x.ET).date()


def cached_daily_bars(cache: Path, symbol: str, start: date, end: date) -> list[dict] | None:
    folder = cache / "options" / "1Day" / symbol
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json")):
        try:
            lo, hi = (window_day(part) for part in path.stem.split("_"))
        except ValueError:
            continue
        if lo <= start and hi >= end:
            return [x.parse_bar(b) for b in json.loads(path.read_text())]
    return None


def fetch_daily_bars(cache: Path, symbol: str, start: date, end: date) -> list[dict]:
    from app.engine import alpaca
    alpaca.CACHE_DIR = cache
    return [x.parse_bar(b) for b in alpaca.fetch_option_bars([symbol], "1Day", start, end).get(symbol, [])]


def run_long(trades_path: Path, cache: Path, out: Path, fetch: bool) -> dict:
    trades, excluded = load_trades(trades_path)
    extract_trades = len(trades) + sum(excluded.values())
    rng = random.Random(SEED)
    population = [t for t in trades if t["window_days"] > x.MAX_WINDOW_DAYS]
    rows, fetched = [], 0
    for trade in population:
        if not trade["expiration"] or not trade["option_type"] or trade["strike"] is None:
            excluded["incomplete contract"] = excluded.get("incomplete contract", 0) + 1
            continue
        symbol = x.occ(trade["ticker"], trade["expiration"], trade["option_type"], trade["strike"])
        start, end = trade["day"], trade["closed"].astimezone(x.ET).date() + timedelta(days=1)
        bars = cached_daily_bars(cache, symbol, start, end)
        if bars is None and fetch:
            bars = fetch_daily_bars(cache, symbol, start, end) or None
            fetched += 1
        if not bars:
            excluded["no option daily bars"] = excluded.get("no option daily bars", 0) + 1
            continue
        rows.append(simulate_long(trade, bars))
    results = {"protocol_id": LONG_ID, "provenance": provenance(LONG_ID, trades_path),
               "extract_trades": extract_trades,
               "population": len(population), "population_actual_total": round(sum(float(t["pnl"]) for t in population), 2),
               "analyzed": len(rows), "excluded": excluded, "fetched_windows": fetched,
               "recorded_pnl_mismatch": recorded_mismatch(population),
               "actual_total": round(sum(r["actual_pnl"] for r in rows), 2), "rules": {}}
    for rule in LONG_RULES:
        periods = {name: summarize_long([r for r in rows if r["period"] == name], rule, rng) for name in PERIODS}
        full = summarize_long(rows, rule, rng)
        results["rules"][rule] = {"all": full, **periods, "decision": decide_long(full, periods)}
    return write(out, "long-holds", results, rows)


# ---------------------------------------------------------------- commands


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("stop-after-green", "size-cap", "long-holds"):
        p = sub.add_parser(name)
        p.add_argument("--trades", type=Path, required=True, help="the exit_counterfactual_study extract")
        p.add_argument("--out", type=Path, required=True)
        if name == "long-holds":
            p.add_argument("--cache", type=Path, required=True)
            p.add_argument("--fetch", action="store_true", help="fetch an uncached window from Alpaca (market data only)")
    args = parser.parse_args(argv)
    if args.command == "stop-after-green":
        results = run_stop(args.trades, args.out)
    elif args.command == "size-cap":
        results = run_cap(args.trades, args.out)
    else:
        results = run_long(args.trades, args.cache, args.out, args.fetch)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    sys.exit(main())
