"""Radar setup lab (research/radar-setup-lab/protocol.json): offline, protocol-registered.

From backend, with the Radar v2 search's price and volume snapshots:
  ALPACA_DATA_FEED=sip python -m scripts.radar_setup_lab fetch-daily DAILY   (once; the dip rule's 20-day closes)
  python -m scripts.radar_setup_lab design PRICES VOLUME DAILY --out RESULTS  (then commit design-picks.json)
  python -m scripts.radar_setup_lab confirm PRICES VOLUME DAILY --out RESULTS

Each setup flags (symbol, direction, minute) from data through that minute only; each flag becomes a card scored on
the stock with the live card's exits (radar_setup.levels, radar_setup_paper), beside 20 random roster stocks carded at
the same minute and direction. Research only: nothing here is read by the app.
"""
import argparse
from datetime import date
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
from statistics import median

import numpy as np

from app.engine import radar_dip, radar_reversal
from app.engine.first_pullback import first_trigger
from scripts import radar_historical_replay as replay
from scripts.radar_v2_search import candidate_prices, candidates, change, read, volume_matrix
from scripts.radar_volume_snapshot import volume_days

STUDY = Path(__file__).resolve().parents[2] / "research/radar-setup-lab"
SETUPS = ("dip", "reversal", "pullback", "laggard", "drive", "hold")
FILTERS = ("all", "dir_up", "dir_down", "time_0_30", "time_31_60", "time_61_plus", "spy_with", "spy_against",
           "vol_heavy", "vol_normal", "gap_big", "gap_small")
HOLD, FLAT_MINUTE, DRAWS, RESAMPLES, SEED = 60, 385, 20, 2000, 20261110
MIN_DESIGN, MIN_CONFIRM, SHORTLIST = 40, 25, 5
DAILY_START, DAILY_END = "2026-04-01", "2026-10-21"


# ------------------------------------------------------------------ the card and its exit (pure, minute-indexed)


def card(closes, minute, sign, opening=None):
    """(entry, invalidation, risk %) at ``minute`` from closes[0..minute-1] (row i = bar ending minute i+1), or None.

    Invalidation is the lowest (up) / highest (down) close so far, plus the open when given; no card unless it is
    strictly beyond the entry."""
    entry = closes[minute - 1]
    if not np.isfinite(entry):
        return None
    seen = closes[:minute][np.isfinite(closes[:minute])]
    if opening is not None and np.isfinite(opening):
        seen = np.append(seen, opening)
    level = float(seen.min() if sign > 0 else seen.max())
    if not sign * (entry - level) > 0:
        return None
    return float(entry), level, abs(entry - level) / entry * 100


def exit_trade(closes, minute, sign, level):
    """(exit minute, exit price, reason) for a card opened at ``minute``, or None when no later close exists."""
    target = minute + HOLD if minute + HOLD <= FLAT_MINUTE else FLAT_MINUTE
    for m in range(minute + 1, len(closes) + 1):
        price = closes[m - 1]
        if not np.isfinite(price):
            continue
        if sign * (price - level) <= 0:
            return m, float(price), "stop"
        if m >= target:
            return m, float(price), "time" if target == minute + HOLD else "close"
    return None


def score(closes, minute, sign, opening=None):
    """The card's scored trade: {entry, level, risk, exit_minute, reason, pct, r}, or None (no card / no exit)."""
    found = card(closes, minute, sign, opening)
    if found is None:
        return None
    entry, level, risk = found
    out = exit_trade(closes, minute, sign, level)
    if out is None:
        return None
    pct = sign * (out[1] / entry - 1) * 100
    return {"entry": entry, "level": level, "risk": risk, "exit_minute": out[0], "reason": out[2],
            "pct": pct, "r": pct / risk}


# ------------------------------------------------------------------ setups


def laggards(groups, since_open, window=(10, 120)):
    """[(column, sign, minute)] first minute a member lags a group moving >= 1 pp vs SPY from the open.

    ``since_open`` rows are bar ends (row i = minute i+1); each row reads only that row."""
    minutes = np.arange(1, len(since_open) + 1)[:, None]
    inside = (minutes >= window[0]) & (minutes <= window[1])
    out = []
    for sign in (1, -1):
        o = sign * since_open
        mask = np.zeros_like(o, dtype=bool)
        for members in groups:
            if len(members) < 5:
                continue
            peers = o[:, members]
            valid, agree = np.isfinite(peers), peers >= 1.0
            count = valid.sum(axis=1, keepdims=True) - valid
            yes = agree.sum(axis=1, keepdims=True) - agree
            mask[:, members] |= (count >= 4) & (yes >= 0.75 * count) & (peers <= 0.25) & inside
        out += [(int(j), sign, int(mask[:, j].argmax()) + 1) for j in np.flatnonzero(mask.any(axis=0))]
    return out


def pullback_bars(rows, volumes, opened):
    """first_pullback bars for 09:30-11:00 from snapshot (open, close) pairs, cut at the first missing minute."""
    bars = []
    for offset in range(90):
        pair, vol = rows.get(str(offset)) or rows.get(offset), volumes.get(str(offset), volumes.get(offset))
        if not pair or vol is None or not all(replay.positive(v) for v in pair):
            break
        bar_open, close = pair
        start = opened + offset * 60
        bars.append({"time": start, "end_time": start + 60, "high": max(bar_open, close),
                     "low": min(bar_open, close), "close": close, "volume": Decimal(str(vol))})
    return bars


def pullback_flag(bars, opened):
    """(sign, minute) of the live first trigger when it fires 09:47-10:59 as the alert would, else None."""
    signal = first_trigger(bars, opened, opened + 90 * 60)
    if signal is None:
        return None
    minute = (signal.end - opened) // 60
    return (signal.side, minute) if 17 <= minute < 90 else None


def live_flags(universe, passes, quotes, daily_ctx):
    by_stamp = {p["finished_at"]: p["id"] for p in passes}
    out = [("dip", e["symbols"][0], 1, by_stamp[e["first_seen_at"]])
           for e in radar_dip.replay(universe, passes, quotes, daily_ctx)]
    out += [("reversal", e["symbols"][0], 1 if e["direction"] == "up" else -1, by_stamp[e["first_seen_at"]])
            for e in radar_reversal.replay(universe, passes, quotes)]
    return out


# ------------------------------------------------------------------ one session


def cumulative(rows):
    out = np.zeros(390)
    for offset, value in rows.items():
        out[int(offset)] = value
    return np.cumsum(out)


class Session:
    def __init__(self, day, universe, bars, previous, vol_rows, past_rows, daily_ctx):
        self.day, self.universe = day, universe
        self.symbols = [r["symbol"] for r in universe["symbols"]]
        self.stocks = [r["symbol"] for r in universe["symbols"] if r["kind"] == "stock" and not r["benchmark"]]
        self.last, self.opening, _ = candidate_prices(bars, self.symbols)
        self.col = {s: j for j, s in enumerate(self.symbols)}
        self.prev = np.array([previous.get(s, np.nan) for s in self.symbols])
        self.bars, self.previous, self.vol_rows, self.past_rows, self.daily_ctx = bars, previous, vol_rows, past_rows, daily_ctx
        self.cache = {}

    def flags(self):
        universe, symbols = self.universe, self.symbols
        passes, quotes = replay.reconstruct(self.day, universe, self.bars, self.previous)
        cum = {s: cumulative(self.vol_rows.get(s, {})) for s in self.stocks}
        for minute, rows in quotes.items():
            for s, q in rows.items():
                if s in cum:
                    q["volume"] = int(cum[s][minute - 1])
        out = live_flags(universe, passes, quotes, self.daily_ctx)
        opened = int(replay.bounds(self.day)[0].timestamp())
        for s in self.stocks:
            hit = pullback_flag(pullback_bars(self.bars[s], self.vol_rows.get(s, {}), opened), opened)
            if hit:
                out.append(("pullback", s, hit[0], hit[1]))
        vol = volume_matrix(self.vol_rows, symbols)
        past = [volume_matrix(r, symbols) for r in self.past_rows]
        for name, events in candidates(universe, symbols, self.last, self.opening, self.prev, vol, past,
                                       {"drive": "drive", "hold": "hold"}).items():
            out += [(name, e.symbols[0], 1 if e.direction == "up" else -1, e.minute) for e in events]
        spy = self.col["SPY"]
        move = change(self.opening, self.last)
        stock_cols = [self.col[s] for s in self.stocks]
        position = {s: k for k, s in enumerate(self.stocks)}
        groups = [[position[s] for s in g["members"] if s in position] for g in universe["groups"]]
        for k, sign, minute in laggards(groups, move[:, stock_cols] - move[:, [spy]]):
            out.append(("laggard", self.stocks[k], sign, minute))
        return sorted(set(out), key=lambda f: (f[3], f[0], f[1], f[2]))

    def trade(self, symbol, minute, sign, with_open):
        key = (symbol, minute, sign, with_open)
        if key not in self.cache:
            j = self.col[symbol]
            self.cache[key] = score(self.last[:, j], minute, sign, self.opening[j] if with_open else None)
        return self.cache[key]

    def baseline(self, setup, symbol, minute, sign):
        with_open = setup == "reversal"
        pool = [s for s in self.stocks if s != symbol and self.trade(s, minute, sign, with_open) is not None]
        if not pool:
            return None
        seed = int.from_bytes(hashlib.sha256(f"{self.day}|{setup}|{symbol}|{minute}|{sign}".encode()).digest()[:8], "big")
        picks = np.random.default_rng(seed).choice(len(pool), size=min(DRAWS, len(pool)), replace=False)
        trades = [self.trade(pool[i], minute, sign, with_open) for i in sorted(picks)]
        return {"pct": float(np.mean([t["pct"] for t in trades])), "r": float(np.mean([t["r"] for t in trades])),
                "green": float(np.mean([t["pct"] > 0 for t in trades])), "n": len(trades)}

    def filters(self, symbol, minute, sign):
        j, spy = self.col[symbol], self.col["SPY"]
        levels = {"all": True, "dir_up": sign > 0, "dir_down": sign < 0, "time_0_30": minute <= 30,
                  "time_31_60": 31 <= minute <= 60, "time_61_plus": minute > 60}
        spy_now, spy_prev = self.last[minute - 1, spy], self.prev[spy]
        if np.isfinite(spy_now) and np.isfinite(spy_prev):
            with_market = sign * (spy_now / spy_prev - 1) >= 0
            levels.update(spy_with=bool(with_market), spy_against=not with_market)
        baseline = [cumulative(r[symbol])[minute - 1] for r in self.past_rows if r.get(symbol)]
        if len(baseline) == 20 and np.mean(baseline) > 0:
            heavy = cumulative(self.vol_rows.get(symbol, {}))[minute - 1] >= 2.0 * np.mean(baseline)
            levels.update(vol_heavy=bool(heavy), vol_normal=not heavy)
        if np.isfinite(self.opening[j]) and np.isfinite(self.prev[j]):
            big = abs(self.opening[j] / self.prev[j] - 1) * 100 >= 2.0
            levels.update(gap_big=bool(big), gap_small=not big)
        return [f for f in FILTERS if levels.get(f)]

    def cards(self):
        rows = []
        for setup, symbol, sign, minute in self.flags():
            trade = self.trade(symbol, minute, sign, setup == "reversal")
            row = {"session": str(self.day), "setup": setup, "symbol": symbol, "direction": "up" if sign > 0 else "down",
                   "minute": minute, "carded": trade is not None}
            if trade:
                row.update({k: round(v, 6) if isinstance(v, float) else v for k, v in trade.items()})
                row["baseline"] = self.baseline(setup, symbol, minute, sign)
                row["filters"] = self.filters(symbol, minute, sign)
            rows.append(row)
        return rows


# ------------------------------------------------------------------ summaries


def bootstrap_index(sessions):
    return np.random.default_rng(SEED).integers(0, sessions, size=(RESAMPLES, sessions))


def summarize(cards, sessions):
    days = sorted(sessions)
    position = {d: i for i, d in enumerate(days)}
    index = bootstrap_index(len(days))
    out = {}
    for setup in SETUPS:
        flagged = [c for c in cards if c["setup"] == setup]
        for f in FILTERS:
            scored = [c for c in flagged if c["carded"] and f in c["filters"]]
            matched = [c for c in scored if c["baseline"]]
            cell = {"flags": len(flagged) if f == "all" else None, "cards": len(scored),
                    "per_session": len(scored) / len(days), "with_baseline": len(matched)}
            if scored:
                pct, r = [c["pct"] for c in scored], [c["r"] for c in scored]
                cell.update(green=float(np.mean([p > 0 for p in pct])), mean_pct=float(np.mean(pct)),
                            median_pct=float(median(pct)), mean_r=float(np.mean(r)), median_r=float(median(r)),
                            stopped=float(np.mean([c["reason"] == "stop" for c in scored])),
                            median_risk=float(median(c["risk"] for c in scored)))
            if matched:
                edge = np.array([c["pct"] - c["baseline"]["pct"] for c in matched])
                sums, counts = np.zeros(len(days)), np.zeros(len(days))
                for c, e in zip(matched, edge):
                    sums[position[c["session"]]] += e
                    counts[position[c["session"]]] += 1
                with np.errstate(invalid="ignore", divide="ignore"):
                    means = sums[index].sum(axis=1) / counts[index].sum(axis=1)
                means = means[np.isfinite(means)]
                cell.update(base_pct=float(np.mean([c["baseline"]["pct"] for c in matched])),
                            base_green=float(np.mean([c["baseline"]["green"] for c in matched])),
                            base_r=float(np.mean([c["baseline"]["r"] for c in matched])),
                            edge_pct=float(edge.mean()),
                            edge_r=float(np.mean([c["r"] - c["baseline"]["r"] for c in matched])),
                            edge_low=float(np.percentile(means, 5)), edge_high=float(np.percentile(means, 95)))
            out[f"{setup}:{f}"] = cell
    return out


def ranking(summary):
    eligible = [n for n, c in summary.items() if c["with_baseline"] >= MIN_DESIGN and c["edge_low"] > 0]
    return sorted(eligible, key=lambda n: (-summary[n]["edge_low"], -summary[n]["edge_pct"], n))[:SHORTLIST]


def verdicts(summary, picks):
    out = {}
    for name in picks:
        c = summary[name]
        passed = (c["with_baseline"] >= MIN_CONFIRM and c.get("edge_pct", 0) > 0 and c.get("edge_low", 0) > 0
                  and c.get("mean_r", 0) > 0)
        out[name] = "pass" if passed else "fail"
    for setup in ("dip", "reversal"):
        c = summary[f"{setup}:all"]
        if not c["with_baseline"]:
            out[f"{setup}:all live"] = "no evidence either way"
        elif c["edge_high"] < 0:
            out[f"{setup}:all live"] = "demote"
        elif c["edge_low"] > 0:
            out[f"{setup}:all live"] = "keep"
        else:
            out[f"{setup}:all live"] = "no evidence either way"
    return out


def pct(v, places=2):
    return "—" if v is None else f"{v:+.{places}f}"


def markdown(summary, cells=None):
    lines = ["| Cell | Cards | /day | Green | Base green | Mean % | Median % | Mean R | Median R | Stopped | "
             "Base mean % | Edge % (90% range) | Edge R |", "|" + "---|" * 13]
    for name in cells or summary:
        c = summary[name]
        if not c["cards"]:
            lines.append(f"| {name} | 0 | 0 | — | — | — | — | — | — | — | — | — | — |")
            continue
        edge = (f"{pct(c['edge_pct'])} ({pct(c['edge_low'])} to {pct(c['edge_high'])})" if "edge_pct" in c else "—")
        lines.append(f"| {name} | {c['cards']} | {c['per_session']:.1f} | {c['green']:.0%} | "
                     f"{c['base_green']:.0%} | {pct(c['mean_pct'])} | {pct(c['median_pct'])} | {pct(c['mean_r'])} | "
                     f"{pct(c['median_r'])} | {c['stopped']:.0%} | {pct(c.get('base_pct'))} | {edge} | "
                     f"{pct(c.get('edge_r'))} |")
    return "\n".join(lines)


# ------------------------------------------------------------------ run


def fetch_daily(path):
    import httpx
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if os.getenv("ALPACA_DATA_FEED") != "sip":
        raise ValueError("fetch-daily requires ALPACA_DATA_FEED=sip")
    headers = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"]}
    symbols = [r["symbol"] for r in replay.load_universe()["symbols"]]
    with httpx.Client(headers=headers, timeout=45) as client:
        bars = replay.get_bars(client, symbols, "1Day", DAILY_START, DAILY_END + "T23:59:59Z", "all")
    path.mkdir(parents=True, exist_ok=True)
    replay.write_snapshot(path / "daily-all.json.gz", dict(bars))


def run(split, prices, volume, daily_root, out):
    protocol = json.loads((STUDY / "protocol.json").read_text())
    if split == "confirm":
        if (out / "confirm-summary.json").exists():
            raise ValueError("CONFIRM results already exist in the output directory")
        picks = json.loads((out / "design-picks.json").read_text())["shortlist"]
        if picks != ranking(json.loads((out / "design-summary.json").read_text())["cells"]):
            raise ValueError("Shortlist does not match the DESIGN ranking")
    hashes = {k: hashlib.sha256() for k in ("price", "volume", "daily")}
    daily = {adj: {s: {date.fromisoformat(b["t"][:10]): b for b in bars} for s, bars in data.items()}
             for adj, data in read(prices, "daily.json.gz", hashes["price"]).items()}
    dip_bars = read(daily_root, "daily-all.json.gz", hashes["daily"])
    universe = replay.load_universe()
    sessions = volume_days()
    start, end = map(date.fromisoformat, protocol[split])
    cards, days, past = [], [], []
    for i in range(sessions.index(start) - 20, sessions.index(end) + 1):
        day = sessions[i]
        vol_rows = read(volume, f"{day}.json.gz", hashes["volume"])
        if day >= start:
            previous, _ = replay.daily_inputs(daily, sessions[i - 1], day)
            bars = read(prices, f"{day}.json.gz", hashes["price"])
            session = Session(day, universe, bars, previous, vol_rows, past,
                              radar_dip.daily_context(dip_bars, day.isoformat()))
            cards += session.cards()
            days.append(str(day))
            print(f"{split} {day}", flush=True)
        past = (past + [vol_rows])[-20:]
    summary = summarize(cards, days)
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(out / f"{split}-cards.jsonl.gz", "wt") as f:
        f.writelines(json.dumps(c, separators=(",", ":")) + "\n" for c in cards)
    result = {**{f"{k}_sha256": h.hexdigest() for k, h in hashes.items()}, "sessions": len(days), "cells": summary}
    if split == "design":
        (out / "design-picks.json").write_text(json.dumps({"shortlist": ranking(summary)}, indent=2) + "\n")
    else:
        result["verdicts"] = verdicts(summary, picks)
    (out / f"{split}-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(markdown(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch-daily").add_argument("daily", type=Path)
    for name in ("design", "confirm"):
        p = sub.add_parser(name)
        p.add_argument("prices", type=Path)
        p.add_argument("volume", type=Path)
        p.add_argument("daily", type=Path)
        p.add_argument("--out", type=Path, default=STUDY)
    args = parser.parse_args()
    if args.command == "fetch-daily":
        fetch_daily(args.daily)
    else:
        run(args.command, args.prices, args.volume, args.daily, args.out)
