"""Exit counterfactual study: would the live position alerts' conditions have
kept more money than the actual exits on past long option trades?

Protocol ``exit-counterfactual-20261024-v1`` (``research/exit-counterfactual/protocol.json``)
was committed before any outcome here was computed. Changing a constant below
makes a different study: register a new protocol id rather than editing this one.

Read-only. ``extract`` runs one ``READ ONLY`` transaction (a plain SELECT: COPY's text format would escape the newlines json_agg emits) against the journal
over SSH and writes trades and fills to a local file (personal data: keep it
out of git). ``run`` reads that file and the Alpaca option minute-bar cache,
fetching a missing window only with ``--fetch``, and writes ``results.json``.
Nothing here writes the journal, places or suggests an order.

Run from backend:
    python -m scripts.exit_counterfactual_study extract --ssh ubuntu@HOST --out /tmp/x/trades.json
    python -m scripts.exit_counterfactual_study run --trades /tmp/x/trades.json --cache data/alpaca_cache --out /tmp/x
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import defaultdict, deque
from datetime import UTC, date, datetime, time as day_time, timedelta
from decimal import Decimal
import json
from pathlib import Path
import random
import subprocess
import sys
from zoneinfo import ZoneInfo

PROTOCOL_ID = "exit-counterfactual-20261024-v1"
ET = ZoneInfo("America/New_York")
FIRST_DAY, LAST_DAY = date(2025, 7, 10), date(2026, 10, 19)
CHECK_START = date(2026, 4, 1)
MAX_WINDOW_DAYS = 10
EARLY_CLOSES = {date(2025, 11, 28), date(2025, 12, 24), date(2026, 11, 27), date(2026, 12, 24)}

ARM_PCT, ARM_DOLLARS, FIRE_PCT = Decimal("0.10"), Decimal("50"), Decimal("0.03")
HOLD_MINUTES = 60
EXPIRY_MINUTES_BEFORE_CLOSE = 90
FILL_WITHIN = timedelta(minutes=5)
COST_BASE, COST_STRESS = Decimal("0.03"), Decimal("0.09")
MIN_HAIRCUT = Decimal("1")  # $0.01 per share, per contract
RULES = ("giveback", "hold_hour", "expiry_day")
RANDOM_DRAWS = 200
BOOTSTRAP = 2000
SEED = 20261024
LEVEL = 1 - 0.05 / len(RULES)  # Bonferroni across the three rules
ENTRY, EXIT = "buy_to_open", "sell_to_close"

EXTRACT_SQL = f"""
BEGIN READ ONLY;
WITH t AS (
    SELECT tr.id, tr.ticker, tr.option_type, tr.strike, tr.expiration, tr.status,
           tr.opened_at, tr.closed_at, tr.realized_pnl, tr.total_premium_paid, a.type AS account_type
    FROM trade tr JOIN account a ON a.id = tr.account_id
    WHERE tr.instrument_type = 'option' AND tr.status IN ('closed', 'expired')
      AND tr.opened_at >= '{FIRST_DAY}' AND tr.opened_at < '{LAST_DAY + timedelta(days=1)}'
  )
  SELECT json_build_object(
    'protocol_id', '{PROTOCOL_ID}',
    'trades', (SELECT coalesce(json_agg(t ORDER BY t.opened_at, t.id), '[]') FROM t),
    'fills', (SELECT coalesce(json_agg(x ORDER BY x.executed_at, x.fill_id), '[]') FROM (
      SELECT tf.trade_id, tf.fill_id, tf.role, f.side, f.contracts, f.price, f.executed_at
      FROM tradefill tf JOIN fill f ON f.id = tf.fill_id JOIN t ON t.id = tf.trade_id) x)
  );
COMMIT;
"""


# ---------------------------------------------------------------- times


def et(naive: str | datetime) -> datetime:
    """Journal timestamps are naive New York wall clock."""
    value = datetime.fromisoformat(naive) if isinstance(naive, str) else naive
    return value.replace(tzinfo=ET).astimezone(UTC)


def session_close(day: date) -> datetime:
    return datetime.combine(day, day_time(13 if day in EARLY_CLOSES else 16), ET).astimezone(UTC)


def regular(stamp: datetime) -> bool:
    local = stamp.astimezone(ET)
    return day_time(9, 30) <= local.time() and stamp < session_close(local.date())


def occ(ticker: str, expiration: date, option_type: str, strike) -> str:
    root = "".join(ch for ch in ticker.upper() if ch.isalnum())
    side = "C" if option_type.lower() == "call" else "P"
    return f"{root}{expiration:%y%m%d}{side}{int(round(float(strike) * 1000)):08d}"


# ---------------------------------------------------------------- positions


class Position:
    """FIFO ledger of the actual fills, read as of any instant."""

    def __init__(self, fills: list[dict]):
        self.fills = sorted(fills, key=lambda f: (f["at"], f["side"] != ENTRY))

    def state(self, before: datetime):
        """(realized, open lots, entry premium) from fills strictly before ``before``."""
        lots, realized, cost = deque(), Decimal(0), Decimal(0)
        for fill in self.fills:
            if fill["at"] >= before:
                break
            qty, price = fill["contracts"], fill["price"]
            if fill["side"] == ENTRY:
                lots.append([qty, price])
                cost += qty * price
                continue
            while qty > 0:
                if not lots:
                    raise ValueError("exit without an open lot")
                used = min(qty, lots[0][0])
                realized += (price - lots[0][1]) * used
                lots[0][0] -= used
                qty -= used
                if lots[0][0] <= 0:
                    lots.popleft()
        return realized, lots, cost

    @property
    def first_entry(self) -> datetime:
        return next(f["at"] for f in self.fills if f["side"] == ENTRY)

    @property
    def final_exit(self) -> datetime | None:
        exits = [f["at"] for f in self.fills if f["side"] == EXIT]
        return exits[-1] if exits else None


def haircut_price(open_price: Decimal, cost: Decimal) -> Decimal:
    gross = open_price * 100
    return max(gross - max(gross * cost, MIN_HAIRCUT), Decimal(0))


def judged_bars(position: Position, bars: list[dict], end: datetime) -> list[tuple[dict, Decimal, Decimal]]:
    """Regular-session bars with an open position and no fill inside: (bar, gain, gain_pct)."""
    fill_times = [f["at"] for f in position.fills]
    out = []
    for bar in bars:
        stamp = bar["t"]
        if stamp < position.first_entry or stamp + timedelta(minutes=1) > end or not regular(stamp):
            continue
        if any(stamp <= t < stamp + timedelta(minutes=1) for t in fill_times):
            continue
        realized, lots, cost = position.state(stamp)
        if not lots or cost <= 0:
            continue
        open_value = sum(q for q, _ in lots) * bar["c"] * 100
        basis = sum(q * p for q, p in lots)
        gain = realized + open_value - basis
        out.append((bar, gain, gain / cost))
    return out


def trigger_time(rule: str, trade: dict, position: Position, judged: list) -> datetime | None:
    if rule == "giveback":
        armed = False
        for bar, gain, pct in judged:
            if not armed and pct >= ARM_PCT and gain >= ARM_DOLLARS:
                armed = True
            elif armed and pct <= FIRE_PCT:
                return bar["t"] + timedelta(minutes=1)
        return None
    if rule == "hold_hour":
        first = position.first_entry
        day = first.astimezone(ET).date()
        anchor = max(first, datetime.combine(day, day_time(9, 30), ET).astimezone(UTC))
        at = anchor + timedelta(minutes=HOLD_MINUTES)
        return at if at < session_close(day) else None
    if rule == "expiry_day":
        expiry = trade["expiration"]
        return session_close(expiry) - timedelta(minutes=EXPIRY_MINUTES_BEFORE_CLOSE)
    raise ValueError(rule)


def execute(position: Position, bars: list[dict], stamps: list[datetime], at: datetime,
            end: datetime, cost: Decimal) -> dict | None:
    """Sell everything still open at the first bar opening in [at, at + 5 min) before ``end``."""
    i = bisect_left(stamps, at)
    if i == len(stamps) or stamps[i] >= at + FILL_WITHIN or stamps[i] >= end:
        return None
    bar = bars[i]
    realized, lots, premium = position.state(bar["t"])
    if not lots:
        return None
    price = haircut_price(bar["o"], cost)
    pnl = realized + sum(q * (price - p) for q, p in lots)
    return {"exit_at": bar["t"].isoformat(), "exit_price": float(price), "pnl": pnl, "premium": premium}


def actual_outcome(position: Position) -> tuple[Decimal, Decimal]:
    realized, lots, premium = position.state(datetime.max.replace(tzinfo=UTC))
    return realized - sum(q * p for q, p in lots), premium  # what is left open expired worthless


def simulate_trade(trade: dict, fills: list[dict], bars: list[dict], rng: random.Random) -> dict:
    """Every rule's counterfactual for one trade, at both costs, plus its random-exit mean."""
    position = Position(fills)
    actual_pnl, actual_premium = actual_outcome(position)
    end = position.final_exit if trade["status"] == "closed" else session_close(trade["expiration"])
    if end is None:
        end = et(trade["closed_at"])
    bars = sorted((b for b in bars if b["t"] < end), key=lambda b: b["t"])
    stamps = [b["t"] for b in bars]
    judged = judged_bars(position, bars, end)
    row = {"id": trade["id"], "day": position.first_entry.astimezone(ET).date().isoformat(),
           "actual_pnl": float(actual_pnl), "actual_premium": float(actual_premium),
           "actual_pct": float(actual_pnl / actual_premium * 100) if actual_premium else None,
           "judged_bars": len(judged), "rules": {}}
    random_cache = None
    for rule in RULES:
        at = trigger_time(rule, trade, position, judged)
        base = execute(position, bars, stamps, at, end, COST_BASE) if at else None
        if base is None:
            row["rules"][rule] = None
            continue
        stress = execute(position, bars, stamps, at, end, COST_STRESS)
        if random_cache is None:
            random_cache = random_exit_mean(position, bars, stamps, judged, end, rng)
        row["rules"][rule] = {
            "trigger_at": at.isoformat(), "exit_at": base["exit_at"], "exit_price": base["exit_price"],
            "diff": float(base["pnl"] - actual_pnl), "diff_stress": float(stress["pnl"] - actual_pnl),
            "cf_pct": float(base["pnl"] / base["premium"] * 100) if base["premium"] else None,
            "random_diff": None if random_cache is None else float(random_cache - actual_pnl),
        }
    return row


def random_exit_mean(position, bars, stamps, judged, end, rng) -> Decimal | None:
    """Mean P&L of exits decided at uniformly random judged bar closes."""
    if not judged:
        return None
    results = []
    for _ in range(RANDOM_DRAWS):
        bar = judged[rng.randrange(len(judged))][0]
        done = execute(position, bars, stamps, bar["t"] + timedelta(minutes=1), end, COST_BASE)
        if done:
            results.append(done["pnl"])
    return sum(results) / len(results) if results else None


# ---------------------------------------------------------------- statistics


def day_bootstrap(by_day: dict[str, list[float]], statistic, rng: random.Random) -> tuple[float, float]:
    days = sorted(by_day)
    draws = []
    for _ in range(BOOTSTRAP):
        sample = [by_day[days[rng.randrange(len(days))]] for _ in days]
        value = statistic(sample)
        if value is not None:
            draws.append(value)
    draws.sort()
    tail = (1 - LEVEL) / 2
    return draws[int(tail * len(draws))], draws[min(len(draws) - 1, int((1 - tail) * len(draws)))]


def total(sample):
    return sum(sum(values) for values in sample)


def mean(sample):
    values = [v for day in sample for v in day]
    return sum(values) / len(values) if values else None


def summarize(rows: list[dict], rule: str, rng: random.Random) -> dict:
    by_day_diff, by_day_pct, by_day_timing = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        by_day_diff[row["day"]]  # every population day is in the resampling
        result = row["rules"][rule]
        if result is None:
            continue
        by_day_diff[row["day"]].append(result["diff"])
        if result["cf_pct"] is not None and row["actual_pct"] is not None:
            by_day_pct[row["day"]].append(result["cf_pct"] - row["actual_pct"])
        if result["random_diff"] is not None:
            by_day_timing[row["day"]].append(result["diff"] - result["random_diff"])
    touched = [row["rules"][rule] for row in rows if row["rules"][rule]]
    out = {
        "trades": len(rows), "touched": len(touched),
        "dollar_diff": round(sum(r["diff"] for r in touched), 2),
        "dollar_diff_stress": round(sum(r["diff_stress"] for r in touched), 2),
        "saved": sum(1 for r in touched if r["diff"] > 0), "cost": sum(1 for r in touched if r["diff"] < 0),
        "pct_diff_mean": None, "timing_value": None, "random_dollar_diff": None,
    }
    if not touched:
        return out
    out["dollar_diff_interval"] = [round(x, 2) for x in day_bootstrap(by_day_diff, total, rng)]
    if by_day_pct:
        out["pct_diff_mean"] = round(mean(list(by_day_pct.values())), 2)
        out["pct_diff_interval"] = [round(x, 2) for x in day_bootstrap(by_day_pct, mean, rng)]
    if by_day_timing:
        out["random_dollar_diff"] = round(sum(r["random_diff"] for r in touched if r["random_diff"] is not None), 2)
        out["timing_value"] = round(sum(sum(v) for v in by_day_timing.values()), 2)
        keyed = {d: by_day_timing.get(d, []) for d in by_day_diff}
        out["timing_value_interval"] = [round(x, 2) for x in day_bootstrap(keyed, total, rng)]
    return out


def decide(full: dict, periods: dict[str, dict]) -> str:
    if not full["touched"]:
        return "no trades touched"
    low, high = full["dollar_diff_interval"]
    if high < 0:
        return "reject: following the rule mechanically would have cost money"
    supported = (low > 0 and full["dollar_diff_stress"] > 0
                 and all(p["touched"] and p["dollar_diff"] > 0 and (p["pct_diff_mean"] or 0) > 0 for p in periods.values()))
    if not supported:
        return "reject as a demonstrated saving (interval includes 0 or periods disagree)"
    timing = full.get("timing_value_interval")
    if timing and timing[0] > 0:
        return "eligible for prospective testing as an exit trigger"
    return "investigate further: the money is in exiting sooner, not in the alert's moment"


# ---------------------------------------------------------------- data


def load_extract(path: Path) -> tuple[list[dict], dict[str, list[dict]], dict]:
    data = json.loads(path.read_text())
    if data.get("protocol_id") != PROTOCOL_ID:
        raise SystemExit(f"extract is not for {PROTOCOL_ID}")
    fills = defaultdict(list)
    for f in data["fills"]:
        fills[f["trade_id"]].append({"side": f["side"], "contracts": Decimal(str(f["contracts"])),
                                     "price": Decimal(str(f["price"])), "at": et(f["executed_at"]),
                                     "role": f["role"]})
    trades = []
    excluded = defaultdict(int)
    for t in data["trades"]:
        t["expiration"] = date.fromisoformat(t["expiration"]) if t["expiration"] else None
        own = fills.get(t["id"], [])
        if not t["expiration"] or not t["option_type"] or t["strike"] is None:
            excluded["incomplete contract"] += 1
        elif not own or any(f["side"] not in (ENTRY, EXIT) for f in own):
            excluded["not a long option (side other than buy_to_open/sell_to_close)"] += 1
        elif (et(t["closed_at"]).date() - et(t["opened_at"]).date()).days + 1 > MAX_WINDOW_DAYS:
            excluded["window over 10 days"] += 1
        else:
            trades.append(t)
    return trades, fills, dict(excluded)


def cached_bars(cache: Path, symbol: str, start: datetime, end: datetime) -> list[dict] | None:
    """Bars from any cached window covering [start, end], merged; None when none covers it."""
    folder = cache / "options" / "1Min" / symbol
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json")):
        try:
            lo, hi = (datetime.strptime(part, "%Y-%m-%dT%H%M%S%z") for part in path.stem.split("_"))
        except ValueError:
            continue
        if lo <= start and hi >= end:
            return [parse_bar(b) for b in json.loads(path.read_text())]
    return None


def parse_bar(bar: dict) -> dict:
    return {"t": datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
            "o": Decimal(str(bar["o"])), "c": Decimal(str(bar["c"]))}


def fetch_bars(cache: Path, symbol: str, start: datetime, end: datetime) -> list[dict]:
    from app.engine import alpaca
    alpaca.CACHE_DIR = cache
    return [parse_bar(b) for b in alpaca.fetch_option_bars([symbol], "1Min", start.astimezone(ET), end.astimezone(ET)).get(symbol, [])]


# ---------------------------------------------------------------- commands


def run(trades_path: Path, cache: Path, out: Path, fetch: bool) -> dict:
    trades, fills, excluded = load_extract(trades_path)
    rng = random.Random(SEED)
    rows, fetched = [], 0
    for trade in trades:
        symbol = occ(trade["ticker"], trade["expiration"], trade["option_type"], trade["strike"])
        start, end = et(trade["opened_at"]), et(trade["closed_at"])
        bars = cached_bars(cache, symbol, start, end)
        if bars is None and fetch:
            bars = fetch_bars(cache, symbol, start, end) or None
            fetched += 1
        if not bars:
            excluded["no option minute bars"] = excluded.get("no option minute bars", 0) + 1
            continue
        try:
            row = simulate_trade(trade, fills[trade["id"]], bars, rng)
        except ValueError:
            excluded["fills do not allocate FIFO"] = excluded.get("fills do not allocate FIFO", 0) + 1
            continue
        row["period"] = "check" if date.fromisoformat(row["day"]) >= CHECK_START else "exploration"
        row["recorded_pnl"] = float(trade["realized_pnl"]) if trade["realized_pnl"] is not None else None
        rows.append(row)
    results = {"protocol_id": PROTOCOL_ID, "extract_trades": len(trades) + sum(excluded.values()),
               "analyzed": len(rows), "excluded": excluded, "fetched_windows": fetched,
               "recorded_pnl_mismatch": sum(1 for r in rows if r["recorded_pnl"] is not None
                                            and abs(r["recorded_pnl"] - r["actual_pnl"]) > 0.5),
               "actual_total": round(sum(r["actual_pnl"] for r in rows), 2), "rules": {}}
    for rule in RULES:
        periods = {name: summarize([r for r in rows if r["period"] == name], rule, rng)
                   for name in ("exploration", "check")}
        full = summarize(rows, rule, rng)
        results["rules"][rule] = {"all": full, **periods, "decision": decide(full, periods)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2))
    (out / "trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return results


def extract(ssh: str, out: Path) -> None:
    command = ["ssh", ssh, "sudo -u postgres psql -d tradejournal -X -q -A -t -v ON_ERROR_STOP=1"]
    done = subprocess.run(command, input=EXTRACT_SQL, capture_output=True, text=True, check=True)
    payload = done.stdout.strip()  # -q -A -t: only the JSON value, which json_agg spreads over lines
    json.loads(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--ssh", required=True)
    e.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--trades", type=Path, required=True)
    r.add_argument("--cache", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--fetch", action="store_true", help="fetch an uncached window from Alpaca (market data only)")
    args = parser.parse_args(argv)
    if args.command == "extract":
        extract(args.ssh, args.out)
    else:
        print(json.dumps(run(args.trades, args.cache, args.out, args.fetch), indent=2))


if __name__ == "__main__":
    sys.exit(main())
