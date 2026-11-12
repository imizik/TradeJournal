"""Radar long-history study (research/radar-long-history/protocol.json): offline, protocol-registered.

Do the two live setup rules (gap reversal, dip turn), entered one minute after the flag, beat random stocks carded at
the same minute on 2024-01-02 to 2026-06-12, sessions no Radar study has read? Each day's roster is the 150 most
traded common stocks as of the day before, so nothing is picked with hindsight.

From backend, with a data folder outside the repository (about 400 MB):
  ALPACA_DATA_FEED=sip python -m scripts.radar_long_history roster DATA --env-file .env
  ALPACA_DATA_FEED=sip python -m scripts.radar_long_history minutes DATA --env-file .env
  python -m scripts.radar_long_history earnings DATA --env-file .env
  python -m scripts.radar_long_history run DATA --out RESULTS

The fetch steps use only market-data and reference GET endpoints. ``run`` reads the folder and writes
``summary.json`` and ``cards.jsonl.gz``. Research only: nothing here is read by the app or changes a rule.
"""
import argparse
from bisect import bisect_left
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import gzip
import hashlib
import json
import math
from multiprocessing import Pool
import os
from pathlib import Path
import re
from statistics import median
import time
from urllib.parse import parse_qs, urlsplit

import numpy as np

from app.engine import radar_dip
from app.engine.symbol_info_events import parse_earnings, report_dates
from scripts import radar_historical_replay as replay
from scripts.radar_setup_lab import card, cumulative, exit_trade, live_flags
from scripts.radar_v2_search import candidate_prices

STUDY = "radar-long-history-20261112-v1"
START, END = date(2024, 1, 2), date(2026, 6, 12)
DAILY_START = date(2023, 11, 1)  # room for the 20-session roster rule and the dip rule's 20 closes
HALF_DAYS = {date(2024, 7, 3), date(2024, 11, 29), date(2024, 12, 24), date(2025, 7, 3), date(2025, 11, 28),
             date(2025, 12, 24)}
LISTING_DATES = ("2024-01-02", "2024-07-01", "2025-01-02", "2025-07-01", "2026-01-02", "2026-06-12")
ROSTER, LOOKBACK, MIN_ADV, MIN_PRICE = 150, 20, 20_000_000, 5.0
SYMBOL = re.compile(r"[A-Z]+(\.[A-Z])?")
SETUPS = ("dip", "reversal")
DELAYS = (1, 0)  # 1 is the registered entry; 0 (the lab's) is descriptive
DRAWS, RESAMPLES, SEED = 20, 2000, 20261112
LEVEL, SPLIT_LEVEL = 95, 90
MATTERS, TRIM = 0.10, 0.01
YEARS = ("2024", "2025", "2026")
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


# ------------------------------------------------------------------ the roster (pure)


def daily_rosters(days, symbols, close, dollar, size=ROSTER):
    """{day: symbols} for days[LOOKBACK:]: the ``size`` names with the highest mean dollar volume over the 20
    preceding sessions, among those with all 20 bars, a latest close of at least $5 and a mean of at least $20M.

    ``close`` and ``dollar`` are [symbol, day] matrices (NaN where there is no bar); column i is never read for day i."""
    out = {}
    for i in range(LOOKBACK, len(days)):
        window = dollar[:, i - LOOKBACK:i]
        whole = np.isfinite(window).all(axis=1)
        safe = np.where(np.isfinite(window), window, 0.0)
        adv = np.where(whole, safe.mean(axis=1), -np.inf)
        ok = whole & (safe > 0).all(axis=1) & (close[:, i - 1] >= MIN_PRICE) & (adv >= MIN_ADV)
        ranked = sorted((int(j) for j in np.flatnonzero(ok)), key=lambda j: (-adv[j], symbols[j]))[:size]
        out[days[i]] = [symbols[j] for j in ranked]
    return out


# ------------------------------------------------------------------ one card (pure)


def delayed(closes, minute, sign, opening, delay):
    """The card flagged at ``minute`` (levels as the live card), entered ``delay`` minutes later at that minute's
    close and exited by the live rules counted from the entry; None when there is no card, entry or exit."""
    found = card(closes, minute, sign, opening)
    if found is None:
        return None
    level = found[1]
    start = minute + delay
    if start > len(closes):
        return None
    entry = closes[start - 1]
    if not np.isfinite(entry) or not sign * (entry - level) > 0:
        return None
    out = exit_trade(closes, start, sign, level)
    if out is None:
        return None
    pct = sign * (out[1] / entry - 1) * 100
    risk = abs(entry - level) / entry * 100
    return {"entry": float(entry), "level": level, "exit_minute": out[0], "reason": out[2], "pct": pct, "r": pct / risk}


def on_earnings(dates, day, prior):
    """True when a report date is the session or the one before, None when the stock has no calendar rows."""
    if dates is None:
        return None
    return day.isoformat() in dates or prior.isoformat() in dates


def session_cards(day, prior, roster, minutes, previous, daily_ctx, earnings):
    """Every dip and reversal flag of one session as scored rows, one per flag and entry delay."""
    symbols = list(roster) + ["SPY"]
    bars = {s: {k: v[:2] for k, v in minutes.get(s, {}).items()} for s in symbols}
    universe = {"version": "research", "groups": [],
                "symbols": [dict(symbol=s, kind="stock", benchmark=s == "SPY", sector=None) for s in symbols]}
    last, opening, _ = candidate_prices(bars, symbols)
    col = {s: j for j, s in enumerate(symbols)}
    passes, quotes = replay.reconstruct(day, universe, bars, previous)
    for s in roster:
        cum = cumulative({k: v[2] for k, v in minutes.get(s, {}).items()})
        for minute, rows in quotes.items():
            if s in rows:
                rows[s]["volume"] = int(cum[minute - 1])
    cache = {}

    def trade(symbol, minute, sign, with_open, delay):
        key = (symbol, minute, sign, with_open, delay)
        if key not in cache:
            j = col[symbol]
            cache[key] = delayed(last[:, j], minute, sign, opening[j] if with_open else None, delay)
        return cache[key]

    rows = []
    for setup, symbol, sign, minute in sorted(set(live_flags(universe, passes, quotes, daily_ctx)),
                                              key=lambda f: (f[3], f[0], f[1], f[2])):
        with_open = setup == "reversal"
        for delay in DELAYS:
            own = trade(symbol, minute, sign, with_open, delay)
            row = {"session": day.isoformat(), "setup": setup, "symbol": symbol, "direction": "up" if sign > 0 else "down",
                   "minute": minute, "delay": delay, "carded": own is not None,
                   "earnings": on_earnings(earnings.get(symbol), day, prior), "base_pct": None}
            if own:
                row.update({k: round(v, 6) if isinstance(v, float) else v for k, v in own.items()})
                pool = [s for s in roster if s != symbol and trade(s, minute, sign, with_open, delay) is not None]
                if pool:
                    text = f"{STUDY}|{day}|{setup}|{symbol}|{minute}|{sign}|{delay}"
                    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
                    picks = np.random.default_rng(seed).choice(len(pool), size=min(DRAWS, len(pool)), replace=False)
                    drawn = [trade(pool[i], minute, sign, with_open, delay) for i in sorted(picks)]
                    row.update(base_pct=float(np.mean([t["pct"] for t in drawn])),
                               base_green=float(np.mean([t["pct"] > 0 for t in drawn])), base_n=len(drawn))
            rows.append(row)
    return rows


# ------------------------------------------------------------------ summaries (pure)


def session_means(rows, days, index):
    """Resampled mean edges: each resample draws whole sessions with replacement."""
    position = {d: i for i, d in enumerate(days)}
    sums, counts = np.zeros(len(days)), np.zeros(len(days))
    for r in rows:
        sums[position[r["session"]]] += r["pct"] - r["base_pct"]
        counts[position[r["session"]]] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        means = sums[index].sum(axis=1) / counts[index].sum(axis=1)
    return means, sums, counts


def cell(rows, days, index):
    """One cell's statistics over ``days``; ``index`` is the [resample, session] draw matrix for those days."""
    inside = set(days)
    rows = [r for r in rows if r["session"] in inside]
    scored = [r for r in rows if r["carded"]]
    matched = [r for r in scored if r["base_pct"] is not None]
    out = {"flags": len(rows), "cards": len(scored), "per_session": round(len(scored) / len(days), 3) if days else 0,
           "with_baseline": len(matched)}
    if scored:
        pct = [r["pct"] for r in scored]
        out.update(green=float(np.mean([p > 0 for p in pct])), mean_pct=float(np.mean(pct)), median_pct=float(median(pct)),
                   mean_r=float(np.mean([r["r"] for r in scored])), median_r=float(median(r["r"] for r in scored)),
                   stopped=float(np.mean([r["reason"] == "stop" for r in scored])))
    if matched:
        edge = np.sort(np.array([r["pct"] - r["base_pct"] for r in matched]))
        means, sums, counts = session_means(matched, days, index)
        means = means[np.isfinite(means)]
        tail = (100 - LEVEL) / 2
        keep = edge[:len(edge) - math.ceil(TRIM * len(edge))]
        out.update(base_pct=float(np.mean([r["base_pct"] for r in matched])),
                   base_green=float(np.mean([r["base_green"] for r in matched])),
                   edge_pct=float(edge.mean()), edge_low=float(np.percentile(means, tail)),
                   edge_high=float(np.percentile(means, 100 - tail)), standard_error=float(means.std()),
                   edge_trimmed=float(keep.mean()) if len(keep) else None,
                   sessions_with_cards=int((counts > 0).sum()),
                   sessions_positive=float((sums[counts > 0] > 0).mean()))
    return out


def decide(whole, by_year):
    """The registered verdict for a primary cell."""
    if "edge_pct" not in whole:
        return "inconclusive"
    years_up = all(by_year[y].get("edge_pct", 0) > 0 for y in YEARS)
    if (whole["edge_low"] > 0 and whole["edge_pct"] >= MATTERS and years_up
            and whole["edge_trimmed"] is not None and whole["edge_trimmed"] > 0):
        return "holds up"
    if whole["edge_high"] < MATTERS:
        return "retire as a trade idea"
    return "inconclusive"


def split_difference(rows, days, index):
    """Reversal without a report minus with one: the mean-edge difference and its 90% session-resampled range."""
    groups = {flag: [r for r in rows if r["carded"] and r["base_pct"] is not None and r["earnings"] is flag]
              for flag in (False, True)}
    if not groups[False] or not groups[True]:
        return None
    off, on = (session_means(groups[flag], days, index)[0] for flag in (False, True))
    diff = (off - on)[np.isfinite(off - on)]
    tail = (100 - SPLIT_LEVEL) / 2
    point = float(np.mean([r["pct"] - r["base_pct"] for r in groups[False]])
                  - np.mean([r["pct"] - r["base_pct"] for r in groups[True]]))
    return {"difference": point, "low": float(np.percentile(diff, tail)), "high": float(np.percentile(diff, 100 - tail)),
            "without_report": len(groups[False]), "with_report": len(groups[True])}


def draws(count):
    return np.random.default_rng(SEED).integers(0, count, size=(RESAMPLES, count)) if count else np.zeros((RESAMPLES, 0), int)


def summarize(cards, days):
    index = draws(len(days))
    by_year = {y: [d for d in days if d.startswith(y)] for y in YEARS}
    year_index = {y: draws(len(v)) for y, v in by_year.items()}
    picks = {"dip": lambda r: r["setup"] == "dip", "reversal": lambda r: r["setup"] == "reversal",
             "reversal_up": lambda r: r["setup"] == "reversal" and r["direction"] == "up",
             "reversal_down": lambda r: r["setup"] == "reversal" and r["direction"] == "down"}
    out = {"cells": {}, "verdicts": {}, "splits": {}}
    for delay in DELAYS:
        for name, pick in picks.items():
            rows = [r for r in cards if r["delay"] == delay and pick(r)]
            entry = {"all": cell(rows, days, index),
                     "years": {y: cell(rows, by_year[y], year_index[y]) for y in YEARS},
                     "earnings": {label: cell([r for r in rows if r["earnings"] is flag], days, index)
                                  for label, flag in (("with_report", True), ("without_report", False), ("unknown", None))}}
            out["cells"][f"{name}:delay{delay}"] = entry
            if delay == DELAYS[0] and name in SETUPS:
                out["verdicts"][name] = decide(entry["all"], entry["years"])
            if delay == DELAYS[0] and name == "reversal":
                out["splits"]["reversal_without_minus_with_report"] = split_difference(rows, days, index)
    return out


# ------------------------------------------------------------------ fetching


def get_json(client, url, params, headers):
    for attempt in range(10):
        response = client.get(url, params=params, headers=headers)
        if response.status_code == 429 and attempt < 9:
            time.sleep(15)
            continue
        response.raise_for_status()
        return response.json()


def alpaca_bars(client, headers, symbols, timeframe, start, end, adjustment):
    params = dict(symbols=",".join(symbols), timeframe=timeframe, feed="sip", start=start, end=end,
                  adjustment=adjustment, limit=10000)
    out = defaultdict(list)
    while True:
        page = get_json(client, BARS_URL, params, headers)
        for symbol, rows in (page.get("bars") or {}).items():
            out[symbol].extend(rows)
        if not page.get("next_page_token"):
            return out
        params["page_token"] = page["next_page_token"]


def polygon_listing(client, key, day):
    params, found = dict(date=day, market="stocks", active="true", type="CS", limit=1000), set()
    url, headers = "https://api.polygon.io/v3/reference/tickers", {"Authorization": "Bearer " + key}
    while True:
        page = get_json(client, url, params, headers)
        found.update(row["ticker"] for row in page.get("results") or [])
        if not page.get("next_url"):
            return sorted(found)
        # The cursor alone falls back to 100 rows a page, which a 5-requests-a-minute key cannot afford.
        cursor, = parse_qs(urlsplit(page["next_url"]).query)["cursor"]
        params = {"cursor": cursor, "limit": 1000}


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def keys_from(env_file):
    from dotenv import dotenv_values
    keys = {**dotenv_values(env_file), **os.environ}
    if keys.get("ALPACA_DATA_FEED") != "sip":
        raise SystemExit("set ALPACA_DATA_FEED=sip: the protocol's prices are SIP bars")
    return keys, {"APCA-API-KEY-ID": keys["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": keys["ALPACA_API_SECRET"]}


def fetch_roster(root, env_file):
    import httpx
    keys, headers = keys_from(env_file)
    root.mkdir(parents=True, exist_ok=True)
    span = (DAILY_START.isoformat(), END.isoformat() + "T23:59:59Z")
    with httpx.Client(timeout=90) as client:
        listing = root / "listings.json.gz"
        lists = load(listing) if listing.exists() else {}
        for d in LISTING_DATES:
            if d not in lists:
                lists[d] = polygon_listing(client, keys["POLYGON_API_KEY"], d)
                replay.write_snapshot(listing, lists)
                print(f"listing {d}: {len(lists[d])} common stocks", flush=True)
        names = sorted({s for v in lists.values() for s in v if SYMBOL.fullmatch(s)})
        days = [b["t"][:10] for b in alpaca_bars(client, headers, ["SPY"], "1Day", *span, "raw")["SPY"]]
        column = {d: i for i, d in enumerate(days)}
        kept, closes, dollars = [], [], []
        for i in range(0, len(names), 200):
            bars = alpaca_bars(client, headers, names[i:i + 200], "1Day", *span, "raw")
            for s in names[i:i + 200]:
                c, dv = np.full(len(days), np.nan), np.full(len(days), np.nan)
                for b in bars.get(s, []):
                    j = column.get(b["t"][:10])
                    if j is not None and all(isinstance(b.get(k), (int, float)) for k in ("c", "vw", "v")):
                        c[j], dv[j] = b["c"], b["vw"] * b["v"]
                if np.isfinite(dv).any() and np.nanmax(dv) >= MIN_ADV:  # a 20-day mean cannot reach the floor otherwise
                    kept.append(s), closes.append(c), dollars.append(dv)
            print(f"daily {min(i + 200, len(names))}/{len(names)} candidates, {len(kept)} kept", flush=True)
        rosters = daily_rosters(days, kept, np.array(closes), np.array(dollars))
        sessions = [d for d in days if START <= date.fromisoformat(d) <= END and date.fromisoformat(d) not in HALF_DAYS]
        union = sorted({s for d in sessions for s in rosters[d]} | {"SPY"})
        replay.write_snapshot(root / "roster.json.gz", {"days": days, "sessions": sessions,
                                                        "roster": {d: rosters[d] for d in sessions}})
        slim = lambda rows: [{k: b[k] for k in ("t", "o", "c")} for b in rows]  # noqa: E731
        daily = {}
        for adjustment in ("raw", "split", "all"):
            got = {}
            for i in range(0, len(union), 200):
                got.update({s: slim(rows) for s, rows in alpaca_bars(client, headers, union[i:i + 200], "1Day", *span,
                                                                     adjustment).items()})
            daily[adjustment] = got
        replay.write_snapshot(root / "daily.json.gz", {k: daily[k] for k in ("raw", "split")})
        replay.write_snapshot(root / "daily-all.json.gz", daily["all"])
    print(f"{len(sessions)} sessions, {len(union) - 1} roster names in all", flush=True)


def fetch_minutes(root, env_file):
    import httpx
    _, headers = keys_from(env_file)
    data = load(root / "roster.json.gz")
    folder = root / "minutes"
    folder.mkdir(exist_ok=True)

    def one(day):
        path = folder / f"{day}.json.gz"
        if path.exists():
            return
        start, end = replay.bounds(date.fromisoformat(day))
        symbols = data["roster"][day] + ["SPY"]
        bars = alpaca_bars(client, headers, symbols, "1Min", start.isoformat(), (end - timedelta(minutes=1)).isoformat(), "raw")
        compact = {}
        for s in symbols:
            rows = {}
            for b in bars.get(s, []):
                offset = (datetime.fromisoformat(b["t"].replace("Z", "+00:00")) - start).total_seconds() / 60
                if offset.is_integer() and 0 <= offset < 390:
                    rows[int(offset)] = [b["o"], b["c"], b["v"]]
            compact[s] = rows
        replay.write_snapshot(path, compact)
        print(f"{day} saved", flush=True)

    with httpx.Client(timeout=90) as client, ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, data["sessions"]))


def fetch_earnings(root, env_file):
    import httpx
    from dotenv import dotenv_values
    keys = {**dotenv_values(env_file), **os.environ}
    base = keys.get("TRADIER_BASE_URL", "https://api.tradier.com").rstrip("/")
    headers = {"Authorization": f"Bearer {keys['TRADIER_API_KEY']}", "Accept": "application/json"}
    data = load(root / "roster.json.gz")
    union = sorted({s for names in data["roster"].values() for s in names})
    out = {}
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(union), 20):
            payload = get_json(client, f"{base}/beta/markets/fundamentals/calendars",
                               {"symbols": ",".join(union[i:i + 20])}, headers)
            for symbol, rows in parse_earnings(payload).items():
                dates = sorted({r["date"] for r in report_dates(rows)})
                if dates:
                    out[symbol] = dates
            print(f"earnings {min(i + 20, len(union))}/{len(union)}", flush=True)
            time.sleep(1.1)
    replay.write_snapshot(root / "earnings.json.gz", out)


# ------------------------------------------------------------------ run

_STATE = {}


def _start(root):
    daily = load(root / "daily.json.gz")
    _STATE.update(root=root, earnings=load(root / "earnings.json.gz"), roster=load(root / "roster.json.gz"),
                  daily={adj: {s: {date.fromisoformat(b["t"][:10]): b for b in rows} for s, rows in data.items()}
                         for adj, data in daily.items()},
                  dip={s: (rows, [b["t"][:10] for b in rows]) for s, rows in load(root / "daily-all.json.gz").items()})


def recent(symbols, day, span=60):
    """Each symbol's 'all'-adjusted daily bars from the ``span`` calendar days before ``day`` (none on or after it)."""
    lo, hi, out = (day - timedelta(days=span)).isoformat(), day.isoformat(), {}
    for s in symbols:
        rows, stamps = _STATE["dip"].get(s, ([], []))
        out[s] = rows[bisect_left(stamps, lo):bisect_left(stamps, hi)]
    return out


def _session(text):
    day = date.fromisoformat(text)
    days = _STATE["roster"]["days"]
    prior = date.fromisoformat(days[days.index(text) - 1])
    roster = _STATE["roster"]["roster"][text]
    minutes = {s: {int(k): v for k, v in rows.items()} for s, rows in load(_STATE["root"] / "minutes" / f"{text}.json.gz").items()}
    previous, _ = replay.daily_inputs(_STATE["daily"], prior, day)
    context = radar_dip.daily_context(recent(roster, day), text)
    return session_cards(day, prior, roster, minutes, previous, context, _STATE["earnings"])


def input_hash(root):
    digest = hashlib.sha256()
    for path in sorted([root / n for n in ("roster.json.gz", "daily.json.gz", "daily-all.json.gz", "earnings.json.gz")]
                       + list((root / "minutes").glob("*.json.gz"))):
        digest.update(path.name.encode() + b"\0" + gzip.decompress(path.read_bytes()))
    return digest.hexdigest()


def run(root, out, workers):
    if (out / "summary.json").exists():
        raise SystemExit("results already exist in the output folder: one run per protocol id")
    sessions = load(root / "roster.json.gz")["sessions"]
    with Pool(workers, initializer=_start, initargs=(root,)) as pool:
        cards = [row for rows in pool.imap(_session, sessions, chunksize=4) for row in rows]
    summary = {"protocol_id": STUDY, "sessions": len(sessions), "first": sessions[0], "last": sessions[-1],
               "input_sha256": input_hash(root), **summarize(cards, sessions)}
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / "cards.jsonl.gz", "wt") as f:
        f.writelines(json.dumps(c, separators=(",", ":")) + "\n" for c in cards)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("roster", "minutes", "earnings"):
        p = sub.add_parser(name)
        p.add_argument("data", type=Path)
        p.add_argument("--env-file", type=Path, default=Path(".env"))
    p = sub.add_parser("run")
    p.add_argument("data", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.command == "run":
        result = run(args.data, args.out, args.workers)
        print(json.dumps({"verdicts": result["verdicts"], "splits": result["splits"]}, indent=2))
    else:
        {"roster": fetch_roster, "minutes": fetch_minutes, "earnings": fetch_earnings}[args.command](args.data, args.env_file)
