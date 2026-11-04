"""Historical SIP reconstruction of the fixed 90 sessions preceding Radar's recorder.

From backend, run python -m scripts.radar_historical_replay fetch SNAPSHOT
[--cache-root /path/to/alpaca_cache], then ... report SNAPSHOT --out REPORT.
fetch uses only the Alpaca historical bars GET endpoint and a separate local snapshot.
"""
import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import gzip
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
from statistics import mean, median
from typing import NamedTuple

from app.engine import radar_movers, radar_rules
from app.engine.chart_math import ET
from app.engine.radar_store import load_universe
from scripts.radar_outcomes import _rel
from scripts.radar_replay import _time

CUTOFF = date(2026, 10, 22)
DATA = Path(__file__).resolve().parents[1] / "app" / "data"
HORIZONS = (30, 60, 120)


def dates():
    """One base session and exactly 90 scored sessions, independently of bar availability."""
    closed = set(json.loads((DATA / "macro_calendar.json").read_text())["market_closed"])
    days = []
    day = CUTOFF
    while len(days) < 91:
        day -= timedelta(days=1)
        if day.weekday() < 5 and day.isoformat() not in closed:
            days.append(day)
    return days[::-1]


def bounds(day):
    # All sessions in this fixed June–October 2026 period have ordinary hours.
    return (datetime.combine(day, time(9, 30), ET), datetime.combine(day, time(16), ET))


def write_snapshot(path, data):
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as out:
        json.dump(data, out, separators=(",", ":"), allow_nan=False)
    tmp.replace(path)


def get_bars(client, symbols, timeframe, start, end, adjustment):
    params = dict(symbols=",".join(symbols), timeframe=timeframe, feed="sip", start=start,
                  end=end, adjustment=adjustment, limit=10000)
    result = defaultdict(list)
    while True:
        response = client.get("https://data.alpaca.markets/v2/stocks/bars", params=params)
        response.raise_for_status()
        page = response.json()
        for symbol, rows in page["bars"].items():
            result[symbol].extend(rows)
        if not page.get("next_page_token"):
            return result
        params["page_token"] = page["next_page_token"]


def fetch(root, cache, universe):
    import httpx
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if os.getenv("ALPACA_DATA_FEED") != "sip":
        raise ValueError("fetch requires ALPACA_DATA_FEED=sip")
    headers = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
               "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"]}
    root.mkdir(parents=True, exist_ok=True)
    symbols = [s["symbol"] for s in universe["symbols"]]
    days = dates()
    daily_file = root / "daily.json.gz"
    with httpx.Client(headers=headers, timeout=45) as client:
        if not daily_file.exists():
            daily = {adj: get_bars(client, symbols, "1Day", days[0].isoformat(),
                                   days[-1].isoformat() + "T23:59:59Z", adj) for adj in ("raw", "split")}
            write_snapshot(daily_file, daily)
        for day in days[1:]:
            path = root / f"{day}.json.gz"
            if path.exists():
                continue
            rows, missing = {}, []
            for symbol in symbols:
                local = cache / "stocks" / "1Min" / "sip" / symbol / f"{day}.json" if cache else None
                if local and local.is_file():
                    rows[symbol] = json.loads(local.read_text())
                else:
                    missing.append(symbol)
            start, end = bounds(day)
            if missing:
                rows.update(get_bars(client, missing, "1Min", start.isoformat(),
                                     (end - timedelta(minutes=1)).isoformat(), "raw"))
            compact = {}
            for symbol in symbols:
                minutes = {}
                for bar in rows.get(symbol, []):
                    at = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                    if start <= at < end:
                        offset = (at - start).total_seconds() / 60
                        if not offset.is_integer() or int(offset) in minutes:
                            raise ValueError(f"{day} {symbol}: duplicate or off-minute bar")
                        minutes[int(offset)] = [bar["o"], bar["c"]]
                compact[symbol] = minutes
            write_snapshot(path, compact)
            print(f"{day} saved ({len(missing)} symbols requested)", flush=True)


def positive(value):
    return isinstance(value, (int, float)) and isfinite(value) and value > 0


def daily_inputs(daily, prior, day):
    """Previous close on today's share basis, plus a separate end-of-day outcome."""
    previous, closing = {}, {}
    for symbol, split in daily["split"].items():
        before, today = split.get(prior), split.get(day)
        raw = daily["raw"].get(symbol, {}).get(day)
        if not (before and today and raw):
            continue
        if all(positive(v) for v in (before["c"], today["o"], raw["o"])):
            # The ratio is solely a share-unit conversion, known when the market opens.
            previous[symbol] = before["c"] * (raw["o"] / today["o"])
            if positive(raw["c"]):
                closing[symbol] = raw["c"]
    return previous, closing


def reconstruct(day, universe, bars, previous):
    """Pass ID = minutes after 09:30. A bar labelled 09:30 first exists at 09:31."""
    start, end = bounds(day)
    n = int((end - start).total_seconds() // 60)
    passes, quotes = [], {}
    for minute in range(1, n + 1):
        at = start + timedelta(minutes=minute)
        stamp = at.isoformat()
        passes.append(dict(id=minute, started_at=stamp, finished_at=stamp, session_date=day.isoformat(),
                           universe_version=universe["version"], status="partial"))
        quotes[minute] = {}
    for row in universe["symbols"]:
        sym = row["symbol"]
        if not positive(previous.get(sym)):
            continue
        opening = None
        for offset, (bar_open, close) in sorted(bars[sym].items(), key=lambda item: int(item[0])):
            minute = int(offset) + 1
            if not 1 <= minute <= n:
                raise ValueError(f"{day} {sym}: bar outside regular hours")
            if minute == 1 and positive(bar_open):
                opening = bar_open
            if positive(close):
                p = passes[minute - 1]
                # A close is available at bar end. Bar start bounds the oldest possible trade.
                trade_ms = int(start.timestamp() + (minute - 1) * 60) * 1000
                quotes[minute][sym] = dict(symbol=sym, pass_id=minute, last=close, prev_close=previous[sym],
                                           open=opening, trade_time_ms=trade_ms, retrieved_at=p["finished_at"])
    for p in passes:
        count = len(quotes[p["id"]])
        if count == len(universe["symbols"]):
            p["status"] = "ok"
        elif not count:
            p["status"] = "failed"
    return radar_rules.session_passes(passes, day.isoformat()), quotes


class Flag(NamedTuple):
    minute: int
    rule: str
    direction: str
    symbols: tuple
    group: str | None = None


def flags(universe, passes, quotes):
    # The same session_passes -> replay path used by scripts.radar_replay.replay_session.
    by_stamp = {p["finished_at"]: p["id"] for p in passes}
    radar = [Flag(by_stamp[e["first_seen_at"]], e["kind"], e["direction"], tuple(e["symbols"]), e["group"])
             for e, _ in radar_rules.replay(universe, passes, quotes, radar_rules.V0)]
    first = {}
    for p in passes:
        ranked = radar_movers.build_movers(universe, list(quotes[p["id"]].values()), None, latest=p)
        for side, direction in (("leaders", "up"), ("laggards", "down")):
            for row in ranked[side]:
                sym = row["symbol"]
                first.setdefault((sym, direction), Flag(p["id"], side, direction, (sym,)))
    return radar, list(first.values())


def forward(flag, prices):
    result = []
    for h in HORIZONS:
        end = prices.get(flag.minute + h, {})
        values = [_rel(s, 1, prices[flag.minute], end) for s in flag.symbols]
        result.append(mean(values) if all(v is not None for v in values) else None)
    return result


def fmt(value):
    return "—" if value is None else f"{value:+.2f}"


def table(headers):
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]


def timing_summary(values):
    return f"{median(values):g}" if values else "—"


def percentage(hits, total):
    return f"{hits}/{total} ({100 * hits / total:.1f}%)" if total else "—"


def analyze(day, universe, bars, previous, closing, totals):
    passes, quotes = reconstruct(day, universe, bars, previous)
    prices = {m: {s: q["last"] for s, q in rows.items()} for m, rows in quotes.items()}
    stocks = [r["symbol"] for r in universe["symbols"] if r["kind"] == "stock" and not r["benchmark"]]
    moves = {s: _rel(s, 1, previous, closing) for s in stocks}
    eligible = {s: v for s, v in moves.items() if v is not None}
    if len(eligible) < 20 or not any("SPY" in rows for rows in quotes.values()):
        raise ValueError(f"{day}: insufficient daily or intraday coverage")
    top = sorted(eligible, key=lambda s: (-abs(eligible[s]), s))[:20]
    radar, movers = flags(universe, passes, quotes)
    clock = {p["id"]: _time(p["finished_at"]) for p in passes}
    close_id = len(quotes)
    hits = {}
    for name, events in (("Radar", radar), ("Movers", movers)):
        hits[name] = {}
        for e in events:
            if not e.group:
                hits[name].setdefault((e.symbols[0], e.direction), e)
    excluded = sorted(set(stocks) - eligible.keys())
    any_quotes = set().union(*(q.keys() for q in quotes.values()))
    absent = sorted({s["symbol"] for s in universe["symbols"]} - any_quotes)
    observed = sum(map(len, quotes.values()))
    possible = close_id * len(universe["symbols"])
    totals["observed"].append(observed)
    totals["possible"].append(possible)
    lines = [f"## {day}", "",
             f"Usable symbol-minutes {observed:,}/{possible:,}. No usable minutes: {', '.join(absent) or 'none'}. "
             f"Daily ranking covers {len(eligible)}/{len(stocks)} stocks. Excluded: {', '.join(excluded) or 'none'}.",
             "", "### Closing top 20", "", *table(["Rank", "Ticker", "vs SPY (pp)", "Radar ET", "Movers ET"])]
    for rank, sym in enumerate(top, 1):
        move = eligible[sym]
        key = (sym, "up" if move > 0 else "down")
        pair = [hits[name].get(key) if move else None for name in ("Radar", "Movers")]
        for name, event in zip(("Radar", "Movers"), pair):
            totals[name + " targets"].append(key)
            if event:
                totals[name + " lead"].append(close_id - event.minute)
        if all(pair):
            totals["paired"].append(pair[1].minute - pair[0].minute)
        seen = [clock[e.minute] if e else "miss" for e in pair]
        lines.append(f"| {rank} | {sym} | {fmt(move)} | {seen[0]} | {seen[1]} |")
    for name, events in (("Radar", radar), ("Movers", movers)):
        lines.extend(["", f"### {name} flags ({len(events)})", "",
                      *table(["ET", "Ticker or group (members)", "Rule", "Side", "+30", "+60", "+120"])])
        for e in events:
            values = forward(e, prices)
            for h, v in zip(HORIZONS, values):
                totals[name, h].append(None if v is None else v * (1 if e.direction == "up" else -1))
            subject = ", ".join(e.symbols)
            if e.group:
                subject = f"{e.group} ({subject})"
            lines.append(f"| {clock[e.minute]} | {subject} | {e.rule} | {e.direction} | "
                         + " | ".join(map(fmt, values)) + " |")
        if not events:
            lines.append("| — | No flags | — | — | — | — | — |")
    return lines


def report(root, out, universe):
    digest = hashlib.sha256()

    def read(name):
        payload = gzip.decompress((root / name).read_bytes())
        digest.update(name.encode() + b"\0" + payload)
        return json.loads(payload)

    daily = {adj: {s: {date.fromisoformat(b["t"][:10]): b for b in rows} for s, rows in data.items()}
             for adj, data in read("daily.json.gz").items()}
    days = dates()
    totals, sessions = defaultdict(list), []
    for prior, day in zip(days, days[1:]):
        previous, closing = daily_inputs(daily, prior, day)
        bars = read(f"{day}.json.gz")
        sessions.extend(analyze(day, universe, bars, previous, closing, totals))
        sessions.append("")
        print(f"{day} scored", flush=True)
    summary = ["# Historical Radar v0 and Movers replay", "",
               f"{len(days)-1} regular sessions, {days[1]} through {days[-1]}. All times are New York time.", "",
               *table(["Method", "Closing top-20 hits", "Misses", "Median minutes before close (hits)"])]
    for name in ("Radar", "Movers"):
        lead = totals[name + " lead"]
        count = len(totals[name + " targets"])
        summary.append(f"| {name} | {percentage(len(lead), count)} | {count-len(lead)} | {timing_summary(lead)} |")
    paired = totals["paired"]
    summary.extend(["", f"Among {len(paired)} stock-days both methods caught, median Movers time minus Radar time "
                    f"was {timing_summary(paired)} minutes (positive means Radar was earlier). "
                    f"Radar was earlier on {sum(v > 0 for v in paired)}, tied on {paired.count(0)}, "
                    f"and later on {sum(v < 0 for v in paired)}.", "",
                    *table(["Method", "Horizon", "Continued in flag direction", "Unscored", "Mean directional vs SPY (pp)"])])
    for name in ("Radar", "Movers"):
        for h in HORIZONS:
            all_values = totals[name, h]
            values = [v for v in all_values if v is not None]
            summary.append(f"| {name} | +{h} | {percentage(sum(v > 0 for v in values), len(values))} | "
                           f"{len(all_values)-len(values)} | {fmt(mean(values) if values else None)} |")
    roster = hashlib.sha256(json.dumps(universe, sort_keys=True).encode()).hexdigest()
    summary.extend(["", "## Reading the comparison", "",
        "- Each day contributes the 20 tracked stocks with the largest absolute split-comparable daily close-to-close "
        "return minus SPY’s return. Ties at four decimal places go to the ticker first alphabetically. A hit requires "
        "a first sighting on the closing move’s side by 16:00. A miss means no such sighting in the available minutes. "
        "Lead time runs from that sighting to the close, including zero for a closing-minute hit.",
        "- Radar uses frozen radar-rules-v0 on minute passes. Stock vs SPY and stock vs sector flags count as stock hits. "
        "Group events and their originally flagged members are listed separately. Revisions are excluded. Movers uses "
        "the unchanged top 10 leaders and 10 laggards each minute. Its flag is the first appearance per stock and side "
        "per day. This ranking includes opening gaps, while Radar needs a persistent intraday move.",
        "- Individual flag rows show the raw subsequent stock return minus SPY in percentage points, including for down "
        "flags. The continuation summary signs those values by flag direction. Group returns equally weight the flagged "
        "members. A dash means the exact minute was outside regular hours or an endpoint for SPY or any member was "
        "missing. Each method’s continuation rate uses its own scored flags.",
        "- Inputs are historical Alpaca SIP bars. A 09:30 bar first becomes a quote at 09:31. Each pass uses only the "
        "just-completed minute’s close and its start as the conservative trade-time proxy. Empty minutes stay empty. "
        "Previous close comes from the preceding scheduled session’s split-adjusted daily close, converted to that "
        "day’s raw share units using the current raw/split opening-price ratio. Daily closing prices are used only "
        "to label the top 20 after the session. This reconstructs minute-end sightings, with different print timing "
        "and coverage from Tradier’s live snapshots.",
        f"- The fixed {universe['version']} roster contains {len(universe['symbols'])} symbols and was assembled "
        "after most of this period, which introduces selection bias. Coverage across all tracked names was "
        f"{sum(totals['observed']):,}/{sum(totals['possible']):,} usable symbol-minutes. Each day lists exclusions. "
        "The pre-recorder sessions are separate from the live 20-session experiment.",
        "", f"Input SHA-256 (uncompressed daily then ordered minute snapshots): `{digest.hexdigest()}`. "
        f"Roster SHA-256 (sorted-key JSON): `{roster}`.", "",
        "From `backend`, run `ALPACA_DATA_FEED=sip python -m scripts.radar_historical_replay fetch SNAPSHOT "
        "--cache-root /path/to/alpaca_cache`, then `python -m scripts.radar_historical_replay report SNAPSHOT "
        "--out REPORT.md`. The second step runs offline.", ""])
    out.write_text("\n".join(summary + sessions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("fetch")
    download.add_argument("snapshot", type=Path)
    download.add_argument("--cache-root", type=Path)
    render = sub.add_parser("report")
    render.add_argument("snapshot", type=Path)
    render.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    universe = load_universe()
    if args.command == "fetch":
        fetch(args.snapshot, args.cache_root, universe)
    else:
        report(args.snapshot, args.out, universe)


if __name__ == "__main__":
    main()
