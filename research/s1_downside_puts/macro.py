"""Research only: do macro release days (CPI, PPI, jobs, FOMC) trend more, and do the
detect.py checks work better on them? Uses out/detect.json. Release dates from the BLS
news-release archives and the Federal Reserve FOMC calendar (fetched 2026-10-14).

  python research/s1_downside_puts/macro.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from backtest import alpaca  # noqa: E402
from datetime import date  # noqa: E402

MACRO = {
    "CPI": ["2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11"],
    "PPI": ["2026-03-18", "2026-04-14", "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-13", "2026-09-10"],
    "jobs": ["2026-03-06", "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07", "2026-09-04", "2026-10-02"],
    "FOMC": ["2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16"],
}
OUT = Path(__file__).parent / "out"
rows = {r["day"]: r for r in json.loads((OUT / "detect.json").read_text())}
spy = alpaca.fetch_daily_bars(["SPY"], date(2025, 12, 1), date(2026, 10, 13))["SPY"]
spy = [{"date": b["t"][:10], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]} for b in spy]
gap = {}
for i in range(15, len(spy)):
    tr = [max(spy[j]["h"], spy[j - 1]["c"]) - min(spy[j]["l"], spy[j - 1]["c"]) for j in range(i - 14, i)]
    gap[spy[i]["date"]] = (spy[i]["o"] - spy[i - 1]["c"]) / (sum(tr) / 14)

kinds = {}
for k, days in MACRO.items():
    for d in days:
        kinds.setdefault(d, []).append(k)
eight30 = {d for d in kinds if set(kinds[d]) & {"CPI", "PPI", "jobs"}}


def mix(days):
    c = Counter(rows[d]["type"] for d in days if d in rows)
    n = sum(c.values())
    return f"{n} days: trend-down {c['trend_down']} ({c['trend_down'] / n:.0%}), trend-up {c['trend_up']} ({c['trend_up'] / n:.0%}), choppy {c['choppy']}"


print("## Day mix\n")
print(f"- All sessions: {mix(rows)}")
for k, days in MACRO.items():
    print(f"- {k}: {mix(days)}")
print(f"- Any 08:30 release (CPI/PPI/jobs): {mix(eight30)}")
print(f"- No release: {mix([d for d in rows if d not in kinds])}")

print("\n## Gap after an 08:30 release (SPY open vs prior close, daily ATRs)\n")
print("| day | release | gap | day type |")
print("|---|---|---|---|")
for d in sorted(eight30):
    if d in rows:
        print(f"| {d} | {'/'.join(kinds[d])} | {gap[d]:+.2f} | {rows[d]['type']} |")
for thr in (0.2, 0.3, 0.5):
    for side, sign in (("down", -1), ("up", 1)):
        g = [d for d in eight30 if d in rows and sign * gap[d] >= thr]
        a = [d for d in rows if d not in eight30 and sign * gap.get(d, 0) >= thr]
        hit = lambda ds: f"{sum(rows[d]['type'] == 'trend_' + side for d in ds)}/{len(ds)}"
        print(f"\n- gap {side} >= {thr} ATR: release days trend {side} {hit(g)}; other days {hit(a)}")

print("\n## Detection checks on release days vs other days (hit rate = fired days that trended that way)\n")
names = sorted({k.split("|")[0] for r in rows.values() for k in r["fired"]})
print("| check | side | release days | other days |")
print("|---|---|---|---|")
for name in names:
    for side in ("down", "up"):
        def h(ds):
            f = [d for d in ds if f"{name}|{side}" in rows[d]["fired"]]
            return f"{sum(rows[d]['type'] == 'trend_' + side for d in f)}/{len(f)}" if f else "0/0"
        print(f"| {name} | {side} | {h([d for d in rows if d in kinds])} | {h([d for d in rows if d not in kinds])} |")
