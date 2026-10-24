"""Score the premarket pilot's saved lists against what Radar recorded after the open.

Read-only: opens the Radar store and its ``-premarket.sqlite`` sibling in SQLite read-only mode and writes
nothing. A stock's outcome is its largest regular-session move against SPY over Radar's own usable passes; an
"important" move is at least ``IMPORTANT_PCT`` points either way. Prints per-session lists and the pilot's
pass/fail checks from ``docs/radar.md``.

    python scripts/radar_premarket_eval.py /abs/path/radar.sqlite [--checkpoint 09:20] [--quiet]
"""
import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from app.engine import radar_premarket, radar_rules
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore

IMPORTANT_PCT = 5.0
SEEN_PCT = 3.0  # an important move already this far from SPY at the checkpoint counts toward recall


def outcomes(store: RadarStore, session: str) -> dict[str, float]:
    """Largest regular-session |move vs SPY| per symbol (signed), from usable quotes only."""
    passes = radar_rules.session_passes(store.passes(session), session)
    by_pass = store.pass_quotes(p["id"] for p in passes)
    best: dict[str, float] = {}
    for p in passes:
        quotes = by_pass.get(p["id"], {})
        spy = quotes.get("SPY")
        if not radar_rules.usable(spy):
            continue
        spy_move = (spy["last"] / spy["prev_close"] - 1) * 100
        for symbol, q in quotes.items():
            if symbol != "SPY" and radar_rules.usable(q):
                excess = (q["last"] / q["prev_close"] - 1) * 100 - spy_move
                if abs(excess) > abs(best.get(symbol, 0.0)):
                    best[symbol] = excess
    return best


def first_events(store: RadarStore, session: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for event in store.events(session):
        at = datetime.fromisoformat(event["first_seen_at"].replace("Z", "+00:00")).astimezone(ET).strftime("%H:%M")
        for symbol in event["symbols"]:
            out.setdefault(symbol, at)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("store", type=Path)
    parser.add_argument("--checkpoint", default="09:20", help="the list the pass/fail checks score")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    radar = RadarStore(args.store.resolve(), read_only=True)
    pre = radar_premarket.PremarketStore(radar_premarket.store_path(args.store.resolve()), read_only=True)
    scans = pre.scans()
    sessions = sorted({s["session_date"] for s in scans})
    totals = defaultdict(int)
    sizes = []
    for session in sessions:
        best = outcomes(radar, session)
        events = first_events(radar, session)
        for scan in (s for s in scans if s["session_date"] == session):
            rows = pre.readings(scan["id"])
            flagged = [r for r in rows if r["flagged"]]
            hits = [r for r in flagged if abs(best.get(r["symbol"], 0.0)) >= IMPORTANT_PCT]
            seen = [r for r in rows if r["excess_pct"] is not None and abs(r["excess_pct"]) >= SEEN_PCT
                    and abs(best.get(r["symbol"], 0.0)) >= IMPORTANT_PCT]
            print(f"\n{session} {scan['checkpoint']} {scan['status']}: read {scan['symbols_read']}/{scan['symbols_requested']}"
                  f" ({scan['symbols_with_bars']} with premarket trades), flagged {len(flagged)},"
                  f" became >= {IMPORTANT_PCT:g}% moves {len(hits)}, important moves already >= {SEEN_PCT:g}% {len(seen)}"
                  + (f"  [{scan['error'] or scan['skip_reason']}]" if scan["error"] or scan["skip_reason"] else ""))
            if not args.quiet:
                for r in sorted(flagged, key=lambda r: -abs(r["excess_pct"])):
                    after = best.get(r["symbol"])
                    print(f"  {r['symbol']:<6} premarket {r['excess_pct']:+.1f} vs SPY, ${r['dollar_volume'] / 1e6:.1f}M traded;"
                          f" after the open {'no data' if after is None else f'{after:+.1f}'}"
                          f"; Radar v0 {events.get(r['symbol'], 'no event')}")
            if scan["checkpoint"] == args.checkpoint and not best:
                print("  (no usable Radar passes for this session; not scored)")
            elif scan["checkpoint"] == args.checkpoint:
                totals["sessions"] += 1
                totals["ok_scans"] += scan["status"] in ("ok", "partial")
                totals["requested"] += scan["symbols_requested"] + sum(r["read_error"] == "deadline" for r in rows)
                totals["read"] += scan["symbols_read"]
                totals["flagged"] += len(flagged)
                totals["hits"] += len(hits)
                totals["seen"] += len(seen)
                totals["seen_flagged"] += sum(1 for r in seen if r["flagged"])
                sizes.append(len(flagged))
    n = totals["sessions"]
    if not n:
        print("\nNo scored sessions yet.")
        return
    precision = totals["hits"] / totals["flagged"] if totals["flagged"] else 0.0
    recall = totals["seen_flagged"] / totals["seen"] if totals["seen"] else 0.0
    reads = totals["read"] / totals["requested"] if totals["requested"] else 0.0
    median = sorted(sizes)[len(sizes) // 2]
    print(f"\n{args.checkpoint} list over {n} scored sessions")
    print(f"  coverage: scans recorded {totals['ok_scans']}/{n}, reads {reads:.0%}  -> {'pass' if totals['ok_scans'] >= 0.9 * n and reads >= 0.95 else 'FAIL'}")
    print(f"  list size: median {median} a session  -> {'pass' if 8 <= median <= 35 else 'FAIL'}")
    print(f"  precision: {totals['hits']}/{totals['flagged']} = {precision:.0%}  -> {'pass' if precision >= 0.5 else 'FAIL'}")
    print(f"  recall: {totals['seen_flagged']}/{totals['seen']} = {recall:.0%}  -> {'pass' if recall >= 0.6 else 'FAIL'}")
    stops = [name for name, hit in (("precision under 40%", totals["flagged"] and precision < 0.4),
                                    ("over 40 names a session", median > 40),
                                    ("coverage failed on 3+ sessions", n - totals["ok_scans"] >= 3)) if hit]
    print(f"  stop rules: {', '.join(stops) if stops else 'none hit'}")


if __name__ == "__main__":
    main()
