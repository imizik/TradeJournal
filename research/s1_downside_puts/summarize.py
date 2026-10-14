"""Summarize out/trades.json from backtest.py into the tables in RESULTS.md."""

import json
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).parent / "out"
trades = json.loads((OUT / "trades.json").read_text())
daytypes = json.loads((OUT / "daytypes.json").read_text())
SESSIONS = len({d["day"] for d in daytypes})
spy = {d["day"]: d["type"] for d in daytypes if d["symbol"] == "SPY"}


def stats(rows, h="h3"):
    filled = [r for r in rows if r["status"] == "filled"]
    pnl = [r[f"pnl_{h}"] for r in filled]
    wins = [p for p in pnl if p > 0]
    losses = [-p for p in pnl if p <= 0]
    pf = sum(wins) / sum(losses) if losses and sum(losses) > 0 else float("inf")
    rop = [r[f"rop_{h}"] for r in filled]
    return {
        "setups": len(rows), "per_session": round(len(rows) / SESSIONS, 2), "filled": len(filled),
        "no_contract": sum(r["status"] in ("no_contract", "no_expiration") for r in rows),
        "unresolved": sum(r["status"] == "unresolved" for r in rows),
        "win_rate": round(len(wins) / len(filled), 3) if filled else None,
        "pf": round(pf, 2) if filled else None,
        "avg_$": round(sum(pnl) / len(filled), 1) if filled else None,
        "total_$": round(sum(pnl)) if filled else None,
        "avg_rop": round(sum(rop) / len(rop), 3) if rop else None,
    }


def table(title, groups, h="h3"):
    print(f"\n### {title} (cost haircut {h[1:]}% each side)\n")
    cols = ["setups", "per_session", "filled", "no_contract", "unresolved", "win_rate", "pf", "avg_$", "total_$", "avg_rop"]
    print("| group | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for name, rows in groups:
        s = stats(rows, h)
        print(f"| {name} | " + " | ".join(str(s[c]) for c in cols) + " |")


by_setup = defaultdict(list)
for r in trades:
    by_setup[r["setup"]].append(r)
order = ["orb_call", "orb_put", "trend_put"]

print(f"Sessions: {SESSIONS}; SPY day types: " + ", ".join(
    f"{k} {sum(v == k for v in spy.values())}" for k in ("trend_down", "choppy", "trend_up")))
for h in ("h0", "h3", "h6"):
    table("By setup", [(s, by_setup[s]) for s in order], h)

for s in order:
    rows = by_setup[s]
    table(f"{s} by the symbol's own day type", [(k, [r for r in rows if r["day_type"] == k])
                                                 for k in ("trend_down", "choppy", "trend_up")])
    table(f"{s} by SPY day type", [(k, [r for r in rows if spy.get(r["day"]) == k])
                                   for k in ("trend_down", "choppy", "trend_up")])
    table(f"{s} by expiry", [("0DTE", [r for r in rows if r.get("dte") == 0]),
                             ("3-7 DTE", [r for r in rows if r.get("dte") not in (None, 0)])])
    table(f"{s} by put_extended flag", [("flagged", [r for r in rows if "put_extended" in r["flags"]]),
                                        ("not flagged", [r for r in rows if "put_extended" not in r["flags"]])])
    exits = defaultdict(int)
    for r in rows:
        if r["status"] == "filled":
            exits[r["exit_reason"]] += 1
    print(f"\n{s} exit reasons: {dict(exits)}")

print("\n### How often the puts fire on days that reverse\n")
for s in ("orb_put", "trend_put"):
    rows = by_setup[s]
    n = len(rows)
    above_entry = sum(r["day_close"] > r["entry_px"] for r in rows)
    above_stop = sum(r["day_close"] > r["stop"] for r in rows)
    above_orh = sum(r["day_close"] > r["or_high"] for r in rows)
    print(f"- {s}: {n} setups; day closed above entry {above_entry} ({above_entry / n:.0%}), "
          f"above the stop {above_stop} ({above_stop / n:.0%}), above the opening-range high {above_orh} ({above_orh / n:.0%}); "
          f"symbol day ended trend_up {sum(r['day_type'] == 'trend_up' for r in rows)}")
    rev = [r for r in rows if r["day_close"] > r["stop"]]
    table(f"{s} on reversal days (close above stop) vs not", [("reversed", rev),
                                                                ("held", [r for r in rows if r["day_close"] <= r["stop"]])])

if "--months" in sys.argv:
    for s in order:
        table(f"{s} by month", [(m, [r for r in by_setup[s] if r["day"][:7] == m])
                                for m in sorted({r["day"][:7] for r in trades})])
