"""Rank daily liquid US common-stock movers and replay frozen v0 SPY first sightings."""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from statistics import median

from dotenv import dotenv_values
import httpx

from app.engine import radar_rules
from app.engine.premarket_archive import ET, Market, timestamp
from app.engine.radar_store import load_universe
from app.engine.radar_whole_market import LOOKBACK, MIN_PRICE, daily_inputs, sessions
from app.engine.scalp_shortlist_store import publish_once
from scripts.radar_historical_replay import bounds, reconstruct
from scripts.radar_outcomes import _rel


def first_seen(day, close, market, targets, previous):
    opening, _ = bounds(day)
    cutoff = datetime.combine(day, close, ET)
    symbols = sorted(set(targets) | {"SPY"})
    bars = {s: {} for s in symbols}
    for s, rows in market.bars(symbols, "1Min", opening, cutoff - timedelta(minutes=1), day):
        for bar in rows:
            minutes = (timestamp(bar) - opening).total_seconds() / 60
            if not minutes.is_integer() or not 0 <= minutes < (cutoff-opening).total_seconds()/60 or minutes in bars[s]:
                raise ValueError("Unexpected SIP minute")
            bars[s][int(minutes)] = [bar["o"], bar["c"]]
    if not bars["SPY"]:
        raise ValueError("Missing benchmark minutes")
    subset = dict(version="research", groups=[], symbols=[
        dict(symbol=s, kind="stock", benchmark=s == "SPY", sector=None) for s in symbols])
    passes, quotes = reconstruct(day, subset, bars, previous)
    seen = {}
    for i, p in enumerate(passes):
        for kind, sym, side in radar_rules._qualifying(subset, passes, i, quotes, radar_rules.V0):
            if (kind == "relative_to_spy" and side == ("up" if targets[sym] > 0 else "down")
                    and quotes[p["id"]][sym]["last"] >= MIN_PRICE):
                seen.setdefault(sym, p["finished_at"][11:16])
    return {s: seen.get(s, "miss" if bars[s] else "no bars") for s in targets}


def score(market, day, prior, close, tracked):
    adv, previous, closing = daily_inputs(market, day, prior, include_close=True)
    moves = {s: _rel(s, 1, previous, closing) for s in closing if s != "SPY" and closing[s] >= MIN_PRICE}
    if len(moves) < 20:
        raise ValueError("Insufficient stocks for top 20")
    top = sorted(moves, key=lambda s: (-abs(moves[s]), s))[:20]
    targets = {s: moves[s] for s in top if s not in tracked}
    seen = first_seen(day, close, market, targets, previous)
    return dict(day=day.isoformat(), eligible=len(moves), missing_close=len(adv)-len(closing),
                outside=targets, seen=seen)


def report(rows, out):
    count = sum(len(r["outside"]) for r in rows)
    times = [v for r in rows for v in r["seen"].values() if ":" in v]
    minute = median(int(v[:2])*60 + int(v[3:]) for v in times) if times else None
    typical = f"{int(minute)//60:02}:{int(minute)%60:02} ET" if minute is not None else "unavailable"
    lines = ["# Whole-market movers outside Radar", "",
        f"{rows[0]['day']} through {rows[-1]['day']} · {len(rows)} completed sessions · historical SIP bars.",
        "", f"**{count:,} of {20*len(rows):,} closing top-20 stock-days were outside the 169.** "
        f"Frozen v0 saw {len(times):,} of those on the closing side. Median first sighting among hits was {typical}.",
        "", "Each session uses its date-effective US common-stock roster. Eligibility requires a $5 closing price "
        "and at least $20M mean daily VWAP × volume across all 20 preceding exchange sessions. Missing daily histories "
        "are excluded. Rank is absolute close-to-close return minus SPY in percentage points, with split-comparable "
        "prior closes and alphabetical ties at four decimals. A symbol can recur across sessions.",
        "", "Times below are ET at the end of a completed SIP minute. The historical replay applies frozen v0's "
        "30-minute stock-vs-SPY window, 4.5pp threshold, 2% own-move floor and three consecutive qualifying passes. "
        "First sighting requires price ≥ $5 and the closing side. A miss means no qualifying observation in the "
        "available minutes. These retrospective targets and minute-by-minute sightings do not measure four-checkpoint "
        "capture, live SIP access, or subsequent returns.", "",
        "| Session | Eligible stocks | Liquid names missing close | Outside / 20 | Outside names in rank order · signed pp vs SPY · first sighting ET |",
        "|---|---:|---:|---:|---|"]
    for r in rows:
        names = ", ".join(f"{s} {v:+.2f} ({r['seen'][s]})" for s, v in r["outside"].items())
        lines.append(f"| {r['day']} | {r['eligible']} | {r['missing_close']} | {len(r['outside'])} | {names or '—'} |")
    lines.extend(["", "## Timing across the 90 sessions", "",
        "| By time ET | Outside stock-days first seen by then |", "|---|---:|"])
    for cutoff in ("09:45", "10:30", "12:00", "14:00", "16:00"):
        lines.append(f"| {cutoff} | {sum(t <= cutoff for t in times):,} / {count:,} |")
    missing = sum(v == "no bars" for r in rows for v in r["seen"].values())
    lines.extend(["", f"{missing} outside stock-days had no regular-session minute bars. "
        "Cumulative counts include earlier sightings even if the move had faded by the checkpoint.", "",
        "To reproduce, run `python -m scripts.radar_whole_market_replay` from `backend/` with "
        f"`--through {rows[-1]['day']}`, an existing market-data credentials file (`--credentials`), "
        "a fresh local result cache (`--cache`) and the report path (`--out`)."])
    out.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.through >= datetime.now(ET).date():
        parser.error("Use a completed prior session")
    tracked = {r["symbol"] for r in load_universe()["symbols"]}
    with httpx.Client(timeout=60) as client:
        market = Market(client, dotenv_values(args.credentials))
        calendar = sessions(market, args.through-timedelta(days=180), args.through)
        days = list(calendar)[-(90+LOOKBACK):]
        if len(days) != 90+LOOKBACK:
            raise ValueError("Incomplete calendar")

        def session(i):
            day = days[i]
            file = args.cache / f"{day}.json"
            if file.exists():
                return json.loads(file.read_text())
            row = score(market, day, days[i-LOOKBACK:i], calendar[day], tracked)
            print(f"{day}: {len(row['outside'])}/20 outside", flush=True)
            return publish_once(file, row)

        rows = [session(i) for i in range(LOOKBACK, len(days))]
    report(rows, args.out)


if __name__ == "__main__":
    main()
