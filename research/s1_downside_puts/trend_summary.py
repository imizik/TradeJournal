"""Tables for trend_mode.py output: python trend_summary.py design|recent [h3]"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "out"
window = sys.argv[1] if len(sys.argv) > 1 else "design"
H = sys.argv[2] if len(sys.argv) > 2 else "h3"
data = json.loads((OUT / f"trend_mode_{window}.json").read_text())
trades, days = data["trades"], data["days"]
N = len(days)


def stats(rows):
    f = [r for r in rows if r["status"] == "filled"]
    pnl = [r[f"pnl_{H}"] for r in f]
    w = sum(p for p in pnl if p > 0)
    lo = -sum(p for p in pnl if p <= 0)
    held = sorted(r["held_min"] for r in f)
    return [len(rows), round(len(rows) / N, 2), len(f),
            f"{sum(p > 0 for p in pnl) / len(f):.0%}" if f else "—",
            round(w / lo, 2) if lo else "—", round(sum(pnl) / len(f), 1) if f else "—",
            round(sum(pnl)) if f else "—",
            f"{sum(r[f'rop_{H}'] for r in f) / len(f):+.1%}" if f else "—",
            held[len(held) // 2] if held else "—"]


def table(title, groups):
    print(f"\n### {title}\n")
    print("| group | setups | /session | priced | win | PF | $/contract | total $ | return on premium | median min held |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, rows in groups:
        print(f"| {name} | " + " | ".join(str(x) for x in stats(rows)) + " |")


def pick(**kw):
    return [r for r in trades if all(r[k] == v for k, v in kw.items())]


down = [d for d in days if d["gate_down"]]
up = [d for d in days if d["gate_up"]]
print(f"## {window}: {N} sessions, cost haircut {H[1:]}% each side\n")
print(f"SPY gate turned down on {len(down)} sessions (SPY hindsight: "
      f"{sum(d['spy']['type'] == 'trend_down' for d in down)} trend-down, "
      f"{sum(d['spy']['type'] == 'choppy' for d in down)} choppy, {sum(d['spy']['type'] == 'trend_up' for d in down)} trend-up); "
      f"up on {len(up)} ({sum(d['spy']['type'] == 'trend_up' for d in up)} trend-up, "
      f"{sum(d['spy']['type'] == 'choppy' for d in up)} choppy, {sum(d['spy']['type'] == 'trend_down' for d in up)} trend-down). "
      f"Hindsight SPY trend-down days: {sum(d['spy']['type'] == 'trend_down' for d in days)}, "
      f"caught {sum(d['spy']['type'] == 'trend_down' and d['gate_down'] for d in days)}; trend-up days: "
      f"{sum(d['spy']['type'] == 'trend_up' for d in days)}, caught {sum(d['spy']['type'] == 'trend_up' and d['gate_up'] for d in days)}.")

table("Gate x exit", [(f"{g} / {e}", pick(gate=g, exit=e)) for g in ("spy", "none") for e in ("s1", "ema9", "vwap")])
for e in ("s1", "ema9", "vwap"):
    table(f"SPY gate, {e} exit, by side", [("puts", pick(gate="spy", exit=e, direction="short")),
                                            ("calls", pick(gate="spy", exit=e, direction="long"))])
for e in ("ema9", "vwap"):
    rows = pick(gate="spy", exit=e)
    table(f"SPY gate, {e} exit, by SPY hindsight day type", [(k, [r for r in rows if r["spy_day_type"] == k])
                                                              for k in ("trend_down", "choppy", "trend_up")])
    table(f"SPY gate, {e} exit, by expiry", [("0DTE", [r for r in rows if r.get("dte") == 0]),
                                              ("3-7 DTE", [r for r in rows if r.get("dte") not in (None, 0)])])
    table(f"SPY gate, {e} exit, by symbol", [(s, [r for r in rows if r["symbol"] == s])
                                              for s in sorted({r["symbol"] for r in rows})])
    table(f"SPY gate, {e} exit, by month", [(m, [r for r in rows if r["day"][:7] == m])
                                             for m in sorted({r["day"][:7] for r in rows})])
