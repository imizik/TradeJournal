"""Generation-only frequency report from private captures and grouped live counts.

No provider, database or Jo calls. Zero-setup sessions stay in every denominator.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import scanner_replay_market as market  # noqa: E402
from scripts.scanner_replay_operator import private_json, write_private_report  # noqa: E402

KINDS = ("fade:long", "fade:short", "orb:long")


def stats(values):
    if not values:
        return {"sessions": 0, "total": 0, "mean": None, "median": None, "min": None, "max": None}
    return {"sessions": len(values), "total": sum(values), "mean": statistics.mean(values),
            "median": statistics.median(values), "min": min(values), "max": max(values)}


def analyze(bundles):
    if not 1 <= len(bundles) <= 150 or len({b["session_date"] for b in bundles}) != len(bundles):
        raise ValueError("Require 1–150 distinct captured practice sessions")
    rows = []
    for bundle in sorted(bundles, key=lambda b: b["session_date"]):
        generated = market.generate_session(bundle)
        strict = market.strict_v1_setup_counts(bundle)
        symbols, kinds = Counter(), Counter()
        for setup in generated["setups"]:
            c = setup["packet"]["candidate"]
            symbols[c["symbol"]] += 1
            kinds[c["setup"] + ":" + c["direction"]] += 1
        rows.append({"session_date": bundle["session_date"], "setups": sum(symbols.values()),
            "strict_v1_setups": strict["total"], "by_symbol": dict(symbols), "by_setup": dict(kinds),
            "strict_by_symbol": strict["symbols"], "strict_by_setup": strict["by_setup"],
            "coverage": generated["coverage"]["totals"]})
    return {"sessions": rows, "parity": stats([r["setups"] for r in rows]),
            "strict": stats([r["strict_v1_setups"] for r in rows]),
            "by_symbol": {s: stats([r["by_symbol"].get(s, 0) for r in rows]) for s in market.rules.UNIVERSE},
            "by_setup": {s: stats([r["by_setup"].get(s, 0) for r in rows]) for s in KINDS},
            "policy": market.scoring_policy(), "no_jo": True}


def _table(groups):
    lines = ["| Group | Sessions | Total | Mean | Median | Min | Max |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, row in groups.items():
        cells = [name, str(row["sessions"]), str(row["total"])]
        cells.extend("—" if row[k] is None else f"{row[k]:.2f}" for k in ("mean", "median", "min", "max"))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render(result, live):
    live_rows = live.get("rows", [])
    live_days = {}
    live_symbols, live_kinds = Counter(), Counter()
    for row in live_rows:
        count = row["setups"]
        if (type(count) is not int or count < 0 or row["symbol"] not in market.rules.UNIVERSE
                or row["setup"] + ":" + row["direction"] not in KINDS
                or date.fromisoformat(row["session_date"]).isoformat() != row["session_date"]):
            raise ValueError("Invalid grouped live count")
        live_days[row["session_date"]] = live_days.get(row["session_date"], 0) + count
        live_symbols[row["symbol"]] += count
        live_kinds[row["setup"] + ":" + row["direction"]] += count
    days = result["sessions"]
    lines = ["# Scanner replay setup frequency — generation only", "",
             f"Practice range: {days[0]['session_date']} through {days[-1]['session_date']}; {len(days)} regular sessions. "
             "September 14 onward is excluded. No Jo decisions or profit results were used.", "",
             f"Policy: `{result['policy']['version']}`; hash `{result['policy']['hash']}`. "
             f"Scanner: `{market.rules.VERSION}`; parameters `{market.rules.PARAMS_HASH}`.", ""]
    live_mean = stats(list(live_days.values()))["mean"]
    if live_mean:
        delta = 100 * (result["parity"]["mean"] / live_mean - 1)
        lines.extend([f"Replay mean versus observed live mean: {delta:+.1f}%. This compares different dates and "
                      "feed/execution proxies; it does not isolate an implementation effect.", ""])
    if len(days) == 135 and days[0]["session_date"] == "2026-03-02" and days[-1]["session_date"] == "2026-09-11":
        delta = 100 * (result["parity"]["total"] / 1193 - 1)
        lines.extend([f"Earlier same-range calibration: 1,193 setups, 8.8/session on split-adjusted five-minute "
                      f"bars; this raw-minute total differs by {delta:+.1f}%.", ""])
    lines.extend(_table({"Strict v1 selection": result["strict"], "Live-bucket parity v2": result["parity"],
                         "Live observed sessions with stored candidates": stats(list(live_days.values()))}))
    lines.extend(["", "Live since-enable comparison:", "", "| Date ET | Live setups | Status |",
                  "| --- | ---: | --- |"])
    enablement = live["enablement_date_ny"]
    if date.fromisoformat(enablement).isoformat() != enablement:
        raise ValueError("Invalid enablement date")
    if enablement not in live_days:
        lines.append(f"| {enablement} | 0 | Enablement date; no stored candidates. Not an accepted full forward session. |")
    for day, count in sorted(live_days.items()):
        lines.append(f"| {day} | {count} | Activation baseline; not an accepted full SC-2 session |")
    lines.extend(["", "The live zero on enablement day is listed but excluded from the comparison mean: exposure was not established "
                  "as a full uninterrupted session. One observed candidate-bearing live day cannot establish a stable live frequency. "
                  "This uses raw one-minute bars and prior raw daily ATR, plus the explicitly disclosed underlying "
                  "open-trade proxy. No scanner parameters were tuned.", "",
                  "Sparse selection matches live: aggregate only supplied completed minutes; evaluate occupied partial buckets, "
                  "skip an empty current bucket, and resume later. No synthetic/forward-filled bars and no claim that absence proves "
                  "no trades. Missing required scoring minutes remain unresolved. Invalid live stop/target geometry remains counted "
                  "as a signal but gets no proxy entry/P&L.", "",
                  "## By symbol (all replay sessions, including zeroes)", ""])
    lines.extend(_table(result["by_symbol"]))
    lines.extend(["", "Live totals by symbol: " + "; ".join(f"{s} {live_symbols[s]}" for s in market.rules.UNIVERSE),
                  "", "## By setup type (all replay sessions, including zeroes)", ""])
    lines.extend(_table(result["by_setup"]))
    lines.extend(["", "Live totals by type: " + "; ".join(f"{s} {live_kinds[s]}" for s in KINDS),
                  "", "## Per-session counts and gap-policy change", "",
                  "| Session | Strict v1 | Live-bucket parity v2 | Change | Missing symbol-minutes | Partial scan buckets | Empty scan buckets |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for row in days:
        coverage = row["coverage"]
        lines.append(f"| {row['session_date']} | {row['strict_v1_setups']} | {row['setups']} | "
                     f"{row['setups'] - row['strict_v1_setups']:+d} | {coverage['missing_minutes']} | "
                     f"{coverage['partial_scan_buckets']} | {coverage['empty_scan_buckets']} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--live-counts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = sorted(args.bundle_dir.glob("bundle-*.json"))
    if not 1 <= len(paths) <= 150:
        raise ValueError("Capture count outside the bounded practice range")
    result = analyze([private_json(p, 20 * 1024 * 1024) for p in paths])
    write_private_report(args.output, render(result, private_json(args.live_counts, 2 * 1024 * 1024)))
    print(json.dumps({"sessions": result["parity"]["sessions"], "setups": result["parity"]["total"],
                      "strict_setups": result["strict"]["total"], "report": str(args.output)}))


if __name__ == "__main__":
    main()
