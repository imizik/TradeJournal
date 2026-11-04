"""Offline protocol-registered search. Run design, commit the ranked picks, then confirm."""
import argparse
from collections import defaultdict
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean, median

import numpy as np

from scripts import radar_historical_replay as replay
from scripts.radar_outcomes import _rel
from scripts.radar_volume_snapshot import volume_days

STUDY = Path(__file__).resolve().parents[2] / "research/radar-v2"
LABELS = ("cc", "oc")


def read(root, name, digest):
    payload = gzip.decompress((root / name).read_bytes())
    digest.update(name.encode() + b"\0" + payload)
    return json.loads(payload)


def lag(x, minutes):
    out = np.full_like(x, np.nan)
    out[minutes:] = x[:-minutes]
    return out


def change(before, after):
    return (after / before - 1) * 100


def volume_matrix(rows, symbols):
    out = np.full((390, len(symbols)), np.nan)
    for j, sym in enumerate(symbols):
        for offset, value in rows.get(sym, {}).items():
            out[int(offset), j] = value
    return out


def candidates(universe, symbols, last, opening, previous, vol, past, definitions):
    """Rows are bar ends; each row uses only opening facts and trailing features."""
    spy = symbols.index("SPY")
    stocks = [r for r in universe["symbols"] if r["kind"] == "stock" and not r["benchmark"]]
    stock = [symbols.index(r["symbol"]) for r in stocks]
    sectors = [symbols.index(r["sector"]) if r.get("sector") else -1 for r in stocks]

    def relative(move):
        return move[:, stock] - move[:, [spy]]

    gap = change(previous, opening)
    gap = gap[stock] - gap[spy]
    day = relative(change(previous, last))
    since_open = relative(change(opening, last))
    one, five, fifteen = [relative(change(lag(last, n), last)) for n in (1, 5, 15)]
    trail = change(lag(last, 15), last)
    sector = trail[:, stock] - trail[:, sectors]
    sector[:, np.array(sectors) < 0] = np.nan
    avg = np.mean(past, axis=0)
    surge = lag(((avg > 0) & (vol >= 3 * avg)).astype(float), 1)[:, stock] == 1
    minutes = np.arange(1, 391)[:, None]
    positions = {r["symbol"]: j for j, r in enumerate(stocks)}
    groups = [[positions[s] for s in g["members"] if s in positions] for g in universe["groups"]]
    events = defaultdict(list)
    for sign, direction in ((1, "up"), (-1, "down")):
        m15 = sign * fifteen
        breadth = np.zeros_like(m15, dtype=bool)
        for members in groups:
            if len(members) < 5:
                continue
            peers = m15[:, members]
            valid, agrees = np.isfinite(peers), peers >= 0.5
            count = valid.sum(axis=1, keepdims=True) - valid
            yes = agrees.sum(axis=1, keepdims=True) - agrees
            breadth[:, members] |= (count >= 4) & (yes >= 0.75 * count)
        g, d, o, m5 = sign * gap, sign * day, sign * since_open, sign * five
        clauses = {
            "hold": (minutes >= 5) & (minutes <= 45) & (g >= 2) & (d >= 0.8 * g) & (o >= -0.25),
            "surge": surge & (sign * one >= 0.35) & (m5 >= 0.75),
            "sector": (sign * sector >= 1.25) & (m15 >= 0.75),
            "group": breadth & (m15 >= 1),
            "reverse": (minutes <= 120) & (g <= -2) & (o >= 1.75) & (m5 >= 0.5),
            "drive": (minutes >= 5) & (o >= 2) & (m5 >= 0.5),
            "day": d >= 2.5,
            "drift": (m15 >= 1.25) & (m5 >= 0.4),
        }
        for name, expr in definitions.items():
            mask = np.logical_or.reduce([np.logical_and.reduce([clauses[word] for word in term.split(" AND ")])
                                         for term in expr.split(" OR ")])
            for j in np.flatnonzero(mask.any(axis=0)):
                minute = int(mask[:, j].argmax()) + 1
                events[name].append(replay.Flag(minute, name, direction, (stocks[j]["symbol"],)))
    return events


def candidate_prices(bars, symbols):
    """Independent minute inputs, including current-session data for newly listed stocks."""
    last = np.full((390, len(symbols)), np.nan)
    opening = np.full(len(symbols), np.nan)
    prices = {minute: {} for minute in range(1, 391)}
    for j, symbol in enumerate(symbols):
        for offset, (bar_open, close) in bars[symbol].items():
            i = int(offset)
            if not 0 <= i < 390:
                raise ValueError("Bar outside regular hours")
            if i == 0 and replay.positive(bar_open):
                opening[j] = bar_open
            if replay.positive(close):
                last[i, j] = close
                prices[i + 1][symbol] = close
    return last, opening, prices


def raw_daily_prices(daily, day, field):
    return {s: bs[day][field] for s, bs in daily["raw"].items()
            if day in bs and replay.positive(bs[day].get(field))}


def targets(stocks, base, closing):
    values = {s: _rel(s, 1, base, closing) for s in stocks}
    eligible = sorted((s for s in stocks if values[s] is not None), key=lambda s: (-abs(values[s]), s))
    if len(eligible) < 20:
        raise ValueError("Insufficient top-20 coverage")
    return {(s, "up" if values[s] > 0 else "down") for s in eligible[:20] if values[s]}


def first_flags(events):
    first = {}
    for e in events:
        if not e.group:
            key = (e.symbols[0], e.direction)
            first[key] = min(first.get(key, e.minute), e.minute)
    return first


def score(events, labels, movers, prices):
    first = first_flags(events)
    row = {"flags": len(events), "horizons": [[0, 0, 0.] for _ in replay.HORIZONS]}
    for label, top in labels.items():
        shared = sorted(top & first.keys() & movers.keys())
        row[label] = {"hits": len(top & first.keys()), "precision_n": 0,
                      "leads": [movers[k] - first[k] for k in shared]}
    for e in events:
        sign = 1 if e.direction == "up" else -1
        forward = replay.forward(e, prices)
        for col, value in zip(row["horizons"], forward):
            if value is not None:
                col[0] += 1
                col[1] += int(value * sign > 0)
                col[2] += value * sign
        for label, top in labels.items():
            continued = forward[1] is not None and sign * forward[1] >= 2
            if continued or (not e.group and (e.symbols[0], e.direction) in top):
                row[label]["precision_n"] += 1
    return row


def summarize(rows):
    totals = {}
    for name in rows[0]["methods"]:
        daily = [r["methods"][name] for r in rows]
        flags = sum(r["flags"] for r in daily)
        result = {"flags": flags, "per_session": flags / len(rows)}
        for label in LABELS:
            hits = sum(r[label]["hits"] for r in daily)
            precision_n = sum(r[label]["precision_n"] for r in daily)
            hit, precision = hits / (20 * len(rows)), precision_n / flags if flags else 0
            leads = [v for r in daily for v in r[label]["leads"]]
            result[label] = {"hit": hit, "precision": precision, "shared": len(leads),
                             "lead": median(leads) if leads else None,
                             "f1": 2 * hit * precision / (hit + precision) if hit and precision else 0}
        result["horizons"] = []
        for i in range(3):
            n, pos, total = map(sum, zip(*(r["horizons"][i] for r in daily)))
            result["horizons"].append([n, pos / n if n else None, total / n if n else None])
        totals[name] = result
    return totals


def ranking(summary):
    def rank(name):
        scores = [summary[name][label]["f1"] for label in LABELS]
        return -min(scores), -mean(scores), name
    return sorted((n for n in summary if n.startswith("C")), key=rank)


def run(split, root, volume, out):
    protocol = json.loads((STUDY / "protocol.json").read_text())
    if split == "confirm":
        if any((out / f"confirm-{suffix}").exists() for suffix in ("sessions.jsonl", "summary.json")):
            raise ValueError("CONFIRM results already exist in the output directory")
        picks = json.loads((out / "design-picks.json").read_text())["ranked_finalists"]
        design = json.loads((out / "design-summary.json").read_text())["methods"]
        if picks != ranking(design)[:3]:
            raise ValueError("Finalists do not match DESIGN ranking")
    price_hash, volume_hash = hashlib.sha256(), hashlib.sha256()
    daily = {adj: {s: {date.fromisoformat(b["t"][:10]): b for b in bars} for s, bars in data.items()}
             for adj, data in read(root, "daily.json.gz", price_hash).items()}
    universe = replay.load_universe()
    symbols = [r["symbol"] for r in universe["symbols"]]
    stocks = [r["symbol"] for r in universe["symbols"] if r["kind"] == "stock" and not r["benchmark"]]
    rows, past = [], []
    sessions = volume_days()
    start, end = map(date.fromisoformat, protocol[split])
    for i in range(sessions.index(start) - 20, sessions.index(end) + 1):
        day = sessions[i]
        vol = volume_matrix(read(volume, f"{day}.json.gz", volume_hash), symbols)
        if day >= start:
            previous, _ = replay.daily_inputs(daily, sessions[i - 1], day)
            bars = read(root, f"{day}.json.gz", price_hash)
            passes, quotes = replay.reconstruct(day, universe, bars, previous)
            last, opening, prices = candidate_prices(bars, symbols)
            prev = np.array([previous.get(s, np.nan) for s in symbols])
            events = candidates(universe, symbols, last, opening, prev, vol, past, protocol["candidates"])
            events["v0"], events["Movers"] = replay.flags(universe, passes, quotes)
            movers = first_flags(events["Movers"])
            raw_open = raw_daily_prices(daily, day, "o")
            closing = raw_daily_prices(daily, day, "c")
            labels = {k: targets(stocks, base, closing) for k, base in zip(LABELS, [previous, raw_open])}
            methods = {name: score(events[name], labels, movers, prices)
                       for name in ["v0", "Movers", *protocol["candidates"]]}
            rows.append({"session": str(day), "methods": methods})
            print(f"{split} {day}", flush=True)
        past = (past + [vol])[-20:]
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    (out / f"{split}-sessions.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    (out / f"{split}-summary.json").write_text(json.dumps({"price_sha256": price_hash.hexdigest(),
        "volume_sha256": volume_hash.hexdigest(), "sessions": len(rows), "methods": summary}, indent=2) + "\n")
    if split == "design":
        (out / "design-picks.json").write_text(json.dumps({"ranked_finalists": ranking(summary)[:3]}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("split", choices=["design", "confirm"])
    parser.add_argument("prices", type=Path)
    parser.add_argument("volume", type=Path)
    parser.add_argument("--out", type=Path, default=STUDY)
    args = parser.parse_args()
    run(args.split, args.prices, args.volume, args.out)
