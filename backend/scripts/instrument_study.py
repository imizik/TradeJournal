"""Instrument study: did trading options, instead of an equal-delta stock
position opened and closed at the same moments, add or cost money?

Protocol, committed before any outcome here was computed:
    research/instrument/protocol.json   instrument-20261113-v1
Changing a constant below makes a different study: register a new protocol id.

Read-only. ``extract-fills`` reads each fill's delta and underlying price from
production (one BEGIN READ ONLY query over ssh, like the exit study's extract).
``run`` joins them to the exit study's extract, reads raw daily closes for
expiries, and writes ``<out>/instrument/results.json`` and ``trades.jsonl``.
Both are personal and the repository is public: keep them outside it.

Run from backend:
    python -m scripts.instrument_study extract-fills --ssh ubuntu@<vps> --out /private/x/fills.json
    python -m scripts.instrument_study run --trades /private/x/trades.json --fills /private/x/fills.json \
        --daily /private/x/daily/daily.json --out /private/x
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

from scripts import exit_counterfactual_study as x

PROTOCOL_ID = "instrument-20261113-v1"
REGISTERED_EXTRACT_SHA256 = "4ada80b1977230773bd0d919cd3ea42f766b8fcc651d5484fee8253de7c33a47"
STOCK_COST = 0.0001  # 1 basis point of traded stock value a side
SPLITS = {"CRWD": date(2026, 7, 2), "CVNA": date(2026, 5, 8), "HON": date(2026, 6, 29),
          "NFLX": date(2025, 11, 17), "NOW": date(2025, 12, 18)}
UNDERLYING = {"SPXW": "SPX"}
BOOTSTRAP, SEED, LEVEL = 2000, 20261113, 0.95
PERIODS = ("exploration", "check")

FILLS_SQL = f"""
BEGIN READ ONLY;
SELECT coalesce(json_agg(x ORDER BY x.fill_id), '[]') FROM (
  SELECT f.id AS fill_id, f.delta_at_fill AS delta, f.underlying_price_at_fill AS underlying
  FROM tradefill tf JOIN fill f ON f.id = tf.fill_id JOIN trade tr ON tr.id = tf.trade_id
  WHERE tr.instrument_type = 'option' AND tr.status IN ('closed', 'expired')
    AND tr.opened_at >= '{x.FIRST_DAY}' AND tr.opened_at < '{x.LAST_DAY.isoformat()}'::date + 1) x;
COMMIT;
"""


# ---------------------------------------------------------------- one trade (pure)


def replay(trade: dict, fills: list[dict], close_on_expiry: float | None) -> tuple[dict | None, str | None]:
    """Option P&L from the fills (FIFO) beside the equal-delta stock replay; (None, reason) when it cannot be scored.

    ``fills`` carry side, contracts, price (per contract), at (naive New York), delta and underlying."""
    fills = sorted(fills, key=lambda f: (f["at"], f["fill_id"]))
    if not fills or any(f["side"] not in (x.ENTRY, x.EXIT) for f in fills):
        return None, "not a long option or fills do not allocate FIFO"
    lots: deque = deque()  # [contracts left, option price, shares per contract, stock price]
    option_pnl = stock_pnl = stock_cost = premium = 0.0
    for f in fills:
        qty, price = float(f["contracts"]), float(f["price"])
        if f["side"] == x.ENTRY:
            if f["delta"] is None or f["underlying"] is None:
                return None, "an entry fill without a delta or an underlying price"
            per = float(f["delta"]) * 100
            lots.append([qty, price, per, float(f["underlying"])])
            premium += qty * price
            stock_cost += abs(per * qty) * float(f["underlying"]) * STOCK_COST
            continue
        if f["underlying"] is None:
            return None, "an exit fill without an underlying price"
        left, under = qty, float(f["underlying"])
        while left > 1e-9:
            if not lots:
                return None, "not a long option or fills do not allocate FIFO"
            lot = lots[0]
            take = min(left, lot[0])
            option_pnl += take * (price - lot[1])
            stock_pnl += take * lot[2] * (under - lot[3])
            stock_cost += abs(take * lot[2]) * under * STOCK_COST
            lot[0] -= take
            left -= take
            if lot[0] <= 1e-9:
                lots.popleft()
    if lots:
        if close_on_expiry is None:
            return None, "an expired trade without the underlying's close on the expiration date"
        for qty, price, per, under in lots:
            option_pnl -= qty * price
            stock_pnl += qty * per * (close_on_expiry - under)
            stock_cost += abs(qty * per) * close_on_expiry * STOCK_COST
    stock_pnl -= stock_cost
    return {"option_pnl": option_pnl, "stock_pnl": stock_pnl, "difference": option_pnl - stock_pnl,
            "premium": premium}, None


def spans_split(ticker: str, first: date, last: date) -> bool:
    day = SPLITS.get(ticker)
    return day is not None and first < day <= last


def dte_bucket(first: date, expiration: date) -> str:
    days = (expiration - first).days
    return "0-1" if days <= 1 else "2-7" if days <= 7 else "8+"


# ---------------------------------------------------------------- summary (pure)


def interval(rows: list[dict], rng: random.Random) -> list[float] | None:
    by_day = defaultdict(float)
    for r in rows:
        by_day[r["day"]] += r["difference"]
    days = sorted(by_day)
    if not days:
        return None
    draws = sorted(sum(by_day[days[rng.randrange(len(days))]] for _ in days) for _ in range(BOOTSTRAP))
    tail = (1 - LEVEL) / 2
    return [round(draws[int(tail * len(draws))], 2), round(draws[min(len(draws) - 1, int((1 - tail) * len(draws)))], 2)]


def totals(rows: list[dict]) -> dict:
    premium = sum(r["premium"] for r in rows)
    diff = sum(r["difference"] for r in rows)
    return {"trades": len(rows), "option_pnl": round(sum(r["option_pnl"] for r in rows), 2),
            "stock_pnl": round(sum(r["stock_pnl"] for r in rows), 2), "difference": round(diff, 2),
            "difference_per_premium_pct": round(diff / premium * 100, 2) if premium else None,
            "option_beat_stock": sum(1 for r in rows if r["difference"] > 0)}


def decide(total: float, band: list[float] | None, periods: dict) -> str:
    if not band:
        return "no evidence either way"
    if band[0] > 0 and all(periods[p]["difference"] > 0 for p in PERIODS):
        return "options added value"
    if band[1] < 0:
        return "options cost money"
    return "no evidence either way"


def summarize(rows: list[dict]) -> dict:
    rng = random.Random(SEED)
    periods = {p: totals([r for r in rows if r["period"] == p]) for p in PERIODS}
    band = interval(rows, rng)
    whole = totals(rows)
    split = lambda key: {v: totals([r for r in rows if r[key] == v]) for v in sorted({r[key] for r in rows})}  # noqa: E731
    return {"all": {**whole, "interval": band}, "periods": periods,
            "decision": decide(whole["difference"], band, periods),
            "descriptive": {"dte": split("dte"), "side": split("side"), "held": split("held")}}


# ---------------------------------------------------------------- data and commands


def extract_fills(ssh: str, out: Path) -> None:
    command = ["ssh", ssh, "sudo -u postgres psql -d tradejournal -X -q -A -t -v ON_ERROR_STOP=1"]
    done = subprocess.run(command, input=FILLS_SQL, capture_output=True, text=True, check=True)
    payload = done.stdout.strip()
    json.loads(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload)


def run(trades_path: Path, fills_path: Path, daily_path: Path, out: Path) -> dict:
    data = json.loads(trades_path.read_text())
    if data.get("protocol_id") != x.PROTOCOL_ID:
        raise SystemExit(f"extract is not the {x.PROTOCOL_ID} extract")
    extra = {f["fill_id"]: f for f in json.loads(fills_path.read_text())}
    raw = json.loads(daily_path.read_text())["raw"]
    by_trade = defaultdict(list)
    for f in data["fills"]:
        more = extra.get(f["fill_id"], {})
        by_trade[f["trade_id"]].append({**f, "at": datetime.fromisoformat(f["executed_at"]),
                                        "delta": more.get("delta"), "underlying": more.get("underlying")})
    rows, excluded = [], defaultdict(int)
    for t in sorted(data["trades"], key=lambda t: (t["opened_at"], t["id"])):
        own = by_trade.get(t["id"], [])
        if not own:
            excluded["not a long option or fills do not allocate FIFO"] += 1
            continue
        first = min(f["at"] for f in own).date()
        last = max(f["at"] for f in own).date()
        expiration = date.fromisoformat(t["expiration"]) if t["expiration"] else None
        if expiration and t["status"] == "expired":
            last = max(last, expiration)
        ticker = UNDERLYING.get(t["ticker"], t["ticker"])
        if spans_split(ticker, first, last):
            excluded["a hold that spans a share split of the underlying"] += 1
            continue
        close = raw.get(ticker, {}).get(expiration.isoformat()) if expiration else None
        result, reason = replay(t, own, close)
        if result is None:
            excluded[reason] += 1
            continue
        held = last > first
        rows.append({"id": t["id"], "day": first.isoformat(), "period": "exploration" if first < x.CHECK_START else "check",
                     "side": t["option_type"], "dte": dte_bucket(first, expiration) if expiration else "unknown",
                     "held": "past the entry session" if held else "same session",
                     **{k: round(v, 4) for k, v in result.items()}})
    results = {"protocol_id": PROTOCOL_ID,
               "provenance": {**x.provenance(trades_path), "protocol_id": PROTOCOL_ID,
                              "fills_sha256": hashlib.sha256(fills_path.read_bytes()).hexdigest()},
               "extract_trades": len(data["trades"]), "scored": len(rows), "excluded": dict(excluded), **summarize(rows)}
    results["provenance"]["extract_is_registered"] = results["provenance"]["extract_sha256"] == REGISTERED_EXTRACT_SHA256
    folder = out / "instrument"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(results, indent=2))
    (folder / "trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("extract-fills")
    e.add_argument("--ssh", required=True)
    e.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("run")
    for name in ("--trades", "--fills", "--daily", "--out"):
        r.add_argument(name, type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "extract-fills":
        extract_fills(args.ssh, args.out)
    else:
        print(json.dumps(run(args.trades, args.fills, args.daily, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
