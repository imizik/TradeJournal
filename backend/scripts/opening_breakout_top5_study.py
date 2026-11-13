"""Opening breakout, top 5 stocks in play, on 2016-2023 with fills from the consolidated tape's trades and quotes.

Protocol, committed before any data of these years was read:
    research/opening-breakout-top5/protocol.json   opening-breakout-top5-20261113-v1
Changing a constant below makes a different study: register a new protocol id.

Selection reuses v1's pure rules (``scripts.opening_breakout_study``) and keeps its top 5. Fills come from
``tape_trade``: it asks a tape source for trades through a price and for the quote in effect at a time. ``fetch``
answers those questions from Alpaca's SIP trades and quotes and saves every question with its answer in the session
file; ``run`` replays the same function from the saved answers, so the run reads no market data and is exactly the
saved one. Market data only (no journal, no personal data); the data stays outside the repository.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.opening_breakout_top5_study fetch DATA --env-file .env [--select-only]
    python -m scripts.opening_breakout_top5_study run DATA --out ../research/opening-breakout-top5/results.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import random
import sys
import threading
import time

from scripts import opening_breakout_study as v1

PROTOCOL_ID = "opening-breakout-top5-20261113-v1"
START, END = date(2016, 1, 4), date(2023, 12, 29)
SECOND_HALF = date(2020, 1, 1)
HALF_DAYS = {date.fromisoformat(d) for d in (
    "2016-11-25", "2017-07-03", "2017-11-24", "2018-07-03", "2018-11-23", "2018-12-24", "2019-07-03", "2019-11-29",
    "2019-12-24", "2020-11-27", "2020-12-24", "2021-11-26", "2022-11-25", "2023-07-03", "2023-11-24")}
LISTING_DATES = ("2016-01-04", "2016-07-01", "2017-01-03", "2017-07-03", "2018-01-02", "2018-07-02", "2019-01-02",
                 "2019-07-01", "2020-01-02", "2020-07-01", "2021-01-04", "2021-07-01", "2022-01-03", "2022-07-01",
                 "2023-01-03", "2023-07-03", "2024-01-02")
TOP = 5
MIN_TRADE_SHARES = 100
QUOTE_AGE = 60 * 10**9  # ns: the quote in effect must be at most this old
DELAY = 10**9  # ns: an order reaches the market one second after its trigger
TOLERANCE_CENTS, TOLERANCE_SHARE = 0.01, 0.002
LAST_STOP_MINUTE = 958  # stops are watched until 15:58:59; the exit order goes at 15:59:00
EXTRA_CENT = 0.01
SEED = 20261113
NY = v1.NY
UTC = timezone.utc


# ---------------------------------------------------------------- time


def ns_of(stamp: str) -> int:
    """An RFC 3339 UTC stamp (to the nanosecond or coarser) as integer nanoseconds since the epoch."""
    text = stamp.rstrip("Z")
    whole, _, frac = text.partition(".")
    base = datetime.fromisoformat(whole).replace(tzinfo=UTC)
    return int(base.timestamp()) * 10**9 + int((frac + "000000000")[:9])


def stamp_of(ns: int) -> str:
    secs, frac = divmod(ns, 10**9)
    return datetime.fromtimestamp(secs, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{frac:09d}Z"


def minute_ns(day: str, minute: int) -> int:
    """New York ``minute`` (minutes after midnight) of ``day`` in epoch nanoseconds."""
    d = date.fromisoformat(day)
    at = datetime(d.year, d.month, d.day, minute // 60, minute % 60, tzinfo=NY)
    return int(at.timestamp()) * 10**9


def minute_at(day: str, ns: int) -> int:
    """The New York minute (minutes after midnight) that contains ``ns``."""
    at = datetime.fromtimestamp(ns // 10**9, NY)
    return at.hour * 60 + at.minute


# ---------------------------------------------------------------- tape fills (pure, given a source)


def valid_quote(q) -> bool:
    return q is not None and q[1] > 0 and q[2] > 0 and q[2] >= q[1]


def confirmed(price: float, quote) -> bool:
    """A trade counts only within the quote in effect, widened by the larger of a cent and 0.2% of the midpoint."""
    if not valid_quote(quote):
        return False
    tol = max(TOLERANCE_CENTS, TOLERANCE_SHARE * (quote[1] + quote[2]) / 2)
    return quote[1] - tol <= price <= quote[2] + tol


def _first_tape_trade(src, symbol: str, lo: int, hi: int, threshold: float, side: int) -> int | None:
    """Time of the first tape trade in [lo, hi) at or above (side 1) / at or below (side -1) ``threshold``."""
    for t, price in src.through(symbol, lo, hi, threshold, side):
        if confirmed(price, src.quote_at(symbol, t)):
            return t
    return None


def tape_trade(pick: dict, bars: dict[int, list], src, day: str) -> dict | None:
    """One pick filled from the tape. ``bars``: minute -> [o, h, l, c, v] from 09:35. None when it never triggered."""
    symbol, side, risk = pick["symbol"], pick["side"], v1.STOP_ATR * pick["atr"]
    level = pick["high"] if side > 0 else pick["low"]
    minutes = sorted(m for m in bars if m >= v1.OPEN_MINUTE + v1.RANGE_MINUTES)
    trigger = None
    for m in minutes:
        if m > v1.LAST_ENTRY:
            break
        _, h, low, _, _ = bars[m]
        if (side > 0 and h >= level) or (side < 0 and low <= level):
            trigger = _first_tape_trade(src, symbol, minute_ns(day, m), minute_ns(day, m + 1), level, side)
            if trigger is not None:
                break
    if trigger is None:
        return None
    base = {"day": day, "symbol": symbol, "side": side, "rank": pick["rank"], "risk": risk,
            "entered": minute_at(day, trigger)}
    fq = src.quote_at(symbol, trigger + DELAY)
    if not valid_quote(fq):
        return {**base, "status": "no fill quote"}
    fill = fq[2] if side > 0 else fq[1]
    stop = fill - side * risk
    start = trigger + DELAY
    first = minute_at(day, start)
    windows = [(start, minute_ns(day, first + 1))] if first <= LAST_STOP_MINUTE else []
    for m in minutes:
        if first < m <= LAST_STOP_MINUTE:
            _, h, low, _, _ = bars[m]
            if (side > 0 and low <= stop) or (side < 0 and h >= stop):
                windows.append((minute_ns(day, m), minute_ns(day, m + 1)))
    out = how = None
    for lo, hi in windows:
        hit = _first_tape_trade(src, symbol, lo, hi, stop, -side)
        if hit is not None:
            sq = src.quote_at(symbol, hit + DELAY)
            out, how = ((sq[1] if side > 0 else sq[2]), "stop") if valid_quote(sq) else (stop, "stop at level")
            break
    if out is None:
        eq = src.quote_at(symbol, minute_ns(day, v1.LAST_BAR) + DELAY)
        if valid_quote(eq):
            out, how = (eq[1] if side > 0 else eq[2]), "close"
        else:
            last = max(m for m in minutes if m <= v1.LAST_BAR)
            out, how = bars[last][3], "close from bar"
    gross = (out - fill) * side
    return {**base, "status": "traded", "fill": fill, "exit": out, "how": how, "r": gross / risk,
            "r_extra_cent": (gross - 2 * EXTRA_CENT) / risk, "spread_r": (fq[2] - fq[1]) / risk}


# ---------------------------------------------------------------- tape sources


class Replay:
    """Answers from a saved session file; a question that was not saved is an error, never a guess."""

    def __init__(self, log: dict):
        self.log = log

    def through(self, symbol, lo, hi, threshold, side):
        return self.log[through_key(symbol, lo, hi, threshold, side)]

    def quote_at(self, symbol, t):
        return self.log[quote_key(symbol, t)]


def through_key(symbol, lo, hi, threshold, side) -> str:
    return f"T|{symbol}|{lo}|{hi}|{threshold!r}|{side}"


def quote_key(symbol, t) -> str:
    return f"Q|{symbol}|{t}"


class Recorder:
    """Answers from Alpaca SIP trades and quotes and writes every answer to ``log``."""

    def __init__(self, get, log: dict):
        self.get, self.log = get, log  # get(path, params) -> json
        self._minutes: dict = {}
        self._quotes: dict[str, list] = defaultdict(list)  # symbol -> [(covered_from, covered_to, [[t, bp, ap]...])]

    def _trades(self, symbol: str, minute_start: int) -> list:
        key = (symbol, minute_start)
        if key not in self._minutes:
            rows, params = [], {"start": stamp_of(minute_start), "end": stamp_of(minute_start + 60 * 10**9 - 1),
                                "feed": "sip", "limit": 10000}
            while True:
                page = self.get(f"/v2/stocks/{symbol}/trades", params)
                rows += [[ns_of(r["t"]), r["p"]] for r in page.get("trades") or []
                         if r.get("s", 0) >= MIN_TRADE_SHARES and r.get("p", 0) > 0]
                if not page.get("next_page_token"):
                    break
                params = {**params, "page_token": page["next_page_token"]}
            self._minutes[key] = sorted(rows)
        return self._minutes[key]

    def through(self, symbol, lo, hi, threshold, side):
        key = through_key(symbol, lo, hi, threshold, side)
        if key not in self.log:
            found, start = [], lo - (lo % (60 * 10**9))
            while start < hi:
                found += [[t, p] for t, p in self._trades(symbol, start)
                          if lo <= t < hi and (p >= threshold if side > 0 else p <= threshold)]
                start += 60 * 10**9
            self.log[key] = found
        return self.log[key]

    def quote_at(self, symbol, t):
        key = quote_key(symbol, t)
        if key not in self.log:
            self.log[key] = self._quote(symbol, t)
        return self.log[key]

    def _quote(self, symbol, t):
        for lo, hi, rows in self._quotes[symbol]:
            if lo <= t <= hi:
                return _in_effect(rows, t)
        # One read ending a second after ``t`` answers both the trigger's check and its fill.
        hi, floor = t + DELAY, t - QUOTE_AGE
        rows, params = [], {"start": stamp_of(floor), "end": stamp_of(hi), "feed": "sip", "limit": 1000,
                            "sort": "desc"}
        while True:
            page = self.get(f"/v2/stocks/{symbol}/quotes", params)
            got = [[ns_of(r["t"]), r.get("bp", 0), r.get("ap", 0)] for r in page.get("quotes") or []]
            rows += got
            token = page.get("next_page_token")
            earliest = min((r[0] for r in rows), default=hi)
            if not token or (earliest <= t and any(valid_quote(r) for r in rows if r[0] <= t)):
                break
            params = {**params, "page_token": token}
        rows.sort()
        answer = _in_effect(rows, t)
        # Reusable for a later time only where the rows hold its whole answer: from the first valid quote read (the
        # last valid quote at or before any later time is then among them), or, if none is valid and the read went
        # back the full minute, from ``t`` (no valid quote anywhere in the window).
        first_valid = next((r[0] for r in rows if valid_quote(r)), None)
        if first_valid is not None:
            self._quotes[symbol].append((first_valid, hi, rows))
        elif not token:
            self._quotes[symbol].append((t, hi, rows))
        return answer


def _in_effect(rows: list, t: int):
    """The last valid quote at or before ``t`` and at most ``QUOTE_AGE`` old, as [time, bid, ask], or None."""
    best = None
    for row in rows:
        if row[0] > t:
            break
        if valid_quote(row) and row[0] >= t - QUOTE_AGE:
            best = row
    return None if best is None else list(best)


# ---------------------------------------------------------------- selection (v1's pure rules, top 5)


def all_sessions(days: list[str]) -> list[str]:
    return [d for d in days[v1.WINDOW + 1:] if date.fromisoformat(d) not in HALF_DAYS]


def sessions(days: list[str]) -> list[str]:
    return [d for d in all_sessions(days) if START <= date.fromisoformat(d) <= END]


def candidates_for(raw: dict, ratios: dict, days: list[str]) -> dict[str, list]:
    """session -> [[symbol, atr, close]] from bars strictly before the session (v1's rules, one chunk of names)."""
    index = {d: i for i, d in enumerate(days)}
    wanted = set(all_sessions(days))
    out: dict[str, list] = defaultdict(list)
    for symbol, rows in raw.items():
        held = {d: raw_c / adj for d, raw_c, adj in ratios.get(symbol, []) if adj}
        for i, row in enumerate(rows[:-1]):
            nxt = rows[i + 1][0]
            if nxt not in wanted or index.get(nxt, -1) != index.get(row[0], -9) + 1:
                continue
            got = v1.candidate(rows, held, i)
            today, before = held.get(nxt), held.get(row[0])
            if got is None or today is None or before is None or abs(today / before - 1) > v1.SPLIT_TOLERANCE:
                continue
            out[nxt].append([symbol, got["atr"], got["close"]])
    return out


def select(opening: dict[str, dict], day: str, order: list[str], candidates: dict[str, list]) -> list[dict]:
    """The top 5 for ``day``. ``opening``: session -> {symbol: [[minute, o, h, l, c, v], ...]}."""
    n = order.index(day)
    rows = []
    for symbol, atr, _close in candidates.get(day, []):
        bars = {b[0]: b[1:] for b in opening.get(day, {}).get(symbol, [])}
        rng = v1.opening_range(bars)
        if rng is None:
            continue
        history = []
        for prior in order[max(0, n - v1.RVOL_DAYS):n]:
            past = {b[0]: b[1:] for b in opening.get(prior, {}).get(symbol, [])}
            r = v1.opening_range(past) if past else None
            if r is not None:
                history.append(r["volume"])
        rows.append({"symbol": symbol, **rng, "atr": atr, "rvol": v1.relative_volume(rng["volume"], history)})
    return [{**c, "rank": i + 1} for i, c in enumerate(v1.in_play(rows)[:TOP])]


# ---------------------------------------------------------------- summary (pure)


def decide(band, halves: dict, extra_cent: float | None) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "loses money"
    if band[0] > 0 and all(v is not None and v > 0 for v in halves.values()) and extra_cent is not None and extra_cent > 0:
        return "worth a paper test"
    return "no evidence either way"


def summarize(tape: list[dict], bars: list[dict], worst: list[dict], selected: int, triggered: int) -> dict:
    traded = [t for t in tape if t["status"] == "traded"]
    out = {}
    for name, keep in (("both_sides", lambda t: True), ("long_side", lambda t: t["side"] > 0)):
        own = [t for t in traded if keep(t)]
        days = v1.by_day(own)
        halves = {h: v1.mean_r(days, [d for d in days if (d < SECOND_HALF.isoformat()) == (h == "first_half")])
                  for h in ("first_half", "second_half")}
        extra = [t["r_extra_cent"] for t in own]
        extra_mean = sum(extra) / len(extra) if extra else None
        band = v1.interval(days, random.Random(SEED))
        out[name] = {**v1.cell(own), "interval": band,
                     "halves": {k: None if v is None else round(v, 4) for k, v in halves.items()},
                     "mean_r_extra_cent": None if extra_mean is None else round(extra_mean, 4),
                     "decision": decide(band, halves, extra_mean)}
    best = sorted(v1.by_day(traded).items(), key=lambda kv: -sum(kv[1]))
    trim = {d for d, _ in best[:max(1, len(best) // 100)]}
    paired_bars = {(t["day"], t["symbol"]): t["r"] for t in bars}
    gaps = [t["r"] - paired_bars[(t["day"], t["symbol"])] for t in traded if (t["day"], t["symbol"]) in paired_bars]
    spreads = [t["spread_r"] for t in traded]
    out["descriptive"] = {
        "selected": selected, "triggered": triggered,
        "triggered_share": round(triggered / selected, 3) if selected else None,
        "no_fill_quote": sum(1 for t in tape if t["status"] == "no fill quote"),
        "exits": {k: sum(1 for t in traded if t["how"] == k) for k in ("stop", "stop at level", "close", "close from bar")},
        "short_side": v1.cell([t for t in traded if t["side"] < 0]),
        "by_year": {y: v1.cell([t for t in traded if t["day"][:4] == y]) for y in sorted({t["day"][:4] for t in traded})},
        "by_rank": {str(k): v1.cell([t for t in traded if t["rank"] == k]) for k in range(1, TOP + 1)},
        "without_best_1pct_sessions": v1.cell([t for t in traded if t["day"] not in trim]),
        "bar_replay_v1_rules": v1.cell(bars), "bar_replay_fill_bar_worst_case": v1.cell(worst),
        "tape_minus_bar_r": {"trades": len(gaps), "mean": round(sum(gaps) / len(gaps), 4) if gaps else None},
        "entry_spread_r": {"mean": round(sum(spreads) / len(spreads), 4) if spreads else None,
                           "median": round(sorted(spreads)[len(spreads) // 2], 4) if spreads else None}}
    return out


def run(root: Path, out: Path | None = None) -> dict:
    days = v1.load(root / "candidates.json.gz")["days"]
    tape, bars, worst, selected, triggered = [], [], [], 0, 0
    for day in sessions(days):
        path = root / "session" / f"{day}.json.gz"
        if not path.exists():
            raise SystemExit(f"missing session file {day}: run fetch first")
        data = v1.load(path)
        src = Replay(data["ticks"])
        selected += len(data["picks"])
        for pick in data["picks"]:
            minute_bars = {b[0]: b[1:] for b in data["bars"].get(pick["symbol"], [])}
            t = tape_trade(pick, minute_bars, src, day) if minute_bars else None
            if t is not None:
                triggered += 1
                tape.append(t)
            for target, kw in ((bars, {}), (worst, {"worst_case": True})):
                b = v1.trade(pick, minute_bars, **kw) if minute_bars else None
                if b is not None:
                    target.append({**b, "day": day})
    results = {"protocol_id": PROTOCOL_ID, "sessions": len(sessions(days)),
               **summarize(tape, bars, worst, selected, triggered)}
    (root / "results.json").write_text(json.dumps(results, indent=2))
    if out is not None:
        out.write_text(json.dumps(results, indent=2) + "\n")
    return results


# ---------------------------------------------------------------- data


class Throttle:
    """At most ``per_minute`` requests a minute across threads (the market-data key's limit is shared)."""

    def __init__(self, per_minute: int):
        self.gap, self.next, self.lock = 60.0 / per_minute, 0.0, threading.Lock()

    def __call__(self, _request=None):
        with self.lock:
            now = time.monotonic()
            wait = max(0.0, self.next - now)
            self.next = max(now, self.next) + self.gap
        if wait:
            time.sleep(wait)


def fetch(root: Path, env_file: Path, select_only: bool = False, per_minute: int = 120) -> None:
    import httpx
    from scripts.radar_long_history import alpaca_bars, get_json, keys_from, polygon_listing
    keys, headers = keys_from(env_file)
    throttle = Throttle(per_minute)
    with httpx.Client(timeout=90, event_hooks={"request": [throttle]}) as client:
        lists_path = root / "listings.json.gz"
        lists = v1.load(lists_path) if lists_path.exists() else {}
        for d in LISTING_DATES:
            if d not in lists:
                lists[d] = sorted(polygon_listing(client, keys["POLYGON_API_KEY"], d))
                v1.save(lists_path, lists)
                print(f"listing {d}: {len(lists[d])}", flush=True)
        names = sorted({s for v in lists.values() for s in v if s.replace(".", "").isalpha() and s.upper() == s})
        print(f"{len(names)} names", flush=True)
        span = (START.isoformat(), END.isoformat() + "T23:59:59Z")
        cand_path = root / "candidates.json.gz"
        if not cand_path.exists():
            spy = alpaca_bars(client, headers, ["SPY"], "1Day", *span, "raw")["SPY"]
            days = [b["t"][:10] for b in spy]
            candidates: dict[str, list] = defaultdict(list)
            for i in range(0, len(names), 200):
                chunk = names[i:i + 200]
                got = alpaca_bars(client, headers, chunk, "1Day", *span, "raw")
                adj = alpaca_bars(client, headers, chunk, "1Day", *span, "split")
                raw, ratios = {}, {}
                for s in chunk:
                    rows = [[b["t"][:10], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in got.get(s, [])
                            if all(isinstance(b.get(k), (int, float)) for k in ("o", "h", "l", "c", "v"))]
                    if rows:
                        raw[s] = rows
                        adjusted = {b["t"][:10]: b["c"] for b in adj.get(s, [])}
                        ratios[s] = [[r[0], r[4], adjusted.get(r[0])] for r in rows]
                for d, rows in candidates_for(raw, ratios, days).items():
                    candidates[d] += rows
                print(f"daily {min(i + 200, len(names))}/{len(names)}", flush=True)
            v1.save(cand_path, {"days": days, "by_day": candidates})
        saved = v1.load(cand_path)
        days, candidates = saved["days"], saved["by_day"]
        order = all_sessions(days)
        for n, day in enumerate(order):
            path = root / "opening" / f"{day}.json.gz"
            if path.exists():
                continue
            want = sorted({row[0] for d in order[n:n + v1.AHEAD + 1] for row in candidates.get(d, [])})
            got = {}
            for i in range(0, len(want), 400):
                rows = alpaca_bars(client, headers, want[i:i + 400], "1Min",
                                   *v1._window(day, v1.OPEN_MINUTE, v1.OPEN_MINUTE + v1.RANGE_MINUTES - 1), "raw")
                for s, bs in rows.items():
                    got[s] = [[v1.minute_of(b["t"])[1], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bs]
            v1.save(path, got)
            print(f"opening {day}: {len(got)} names", flush=True)
        if select_only:
            return
        get = lambda p, params: get_json(client, "https://data.alpaca.markets" + p, params, headers)  # noqa: E731
        opening: dict[str, dict] = {}
        for day in sessions(days):
            path = root / "session" / f"{day}.json.gz"
            n = order.index(day)
            for d in order[max(0, n - v1.RVOL_DAYS):n + 1]:
                if d not in opening:
                    opening[d] = v1.load(root / "opening" / f"{d}.json.gz")
            for old in [d for d in opening if d not in order[max(0, n - v1.RVOL_DAYS):n + 1]]:
                del opening[old]
            if path.exists():
                continue
            chosen = select(opening, day, order, candidates)
            rows = alpaca_bars(client, headers, [c["symbol"] for c in chosen], "1Min",
                               *v1._window(day, v1.OPEN_MINUTE + v1.RANGE_MINUTES, v1.LAST_BAR), "raw") if chosen else {}
            minute_rows = {s: [[v1.minute_of(b["t"])[1], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in bs]
                           for s, bs in rows.items()}
            log: dict = {}
            recorder = Recorder(get, log)
            for pick in chosen:
                bars = {b[0]: b[1:] for b in minute_rows.get(pick["symbol"], [])}
                if bars:
                    tape_trade(pick, bars, recorder, day)
            v1.save(path, {"picks": chosen, "bars": minute_rows, "ticks": log})
            print(f"session {day}: {len(chosen)} picks, {len(log)} tape answers", flush=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("data", type=Path)
    f.add_argument("--env-file", type=Path, required=True)
    f.add_argument("--select-only", action="store_true", help="stop after the selection inputs (no outcomes read)")
    f.add_argument("--per-minute", type=int, default=120)
    r = sub.add_parser("run")
    r.add_argument("data", type=Path)
    r.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.data, args.env_file, args.select_only, args.per_minute)
    else:
        print(json.dumps(run(args.data, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
