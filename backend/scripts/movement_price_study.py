"""Movement price study: did the owner's options price in more movement than
the stock then made while he held them?

Protocol, committed before any outcome here was computed:
    research/movement-price/protocol.json   movement-price-20261113-v1
Changing a constant below makes a different study: register a new protocol id.

Read-only. Inputs are files that already exist outside the repository (the
exit study's extract, the instrument study's fill join, the entry horizon
study's raw daily closes), cached Alpaca SIP minute bars, and earnings report
dates. ``fetch-bars`` fills the minute cache (market data only,
ALPACA_DATA_FEED=sip); ``fetch-earnings`` writes report dates from Tradier's
corporate calendar. ``run`` writes ``<out>/movement-price/results.json`` and
``trades.jsonl``. Both are personal and the repository is public: keep them
outside it. Nothing here writes the journal or suggests an order.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.movement_price_study fetch-bars --trades /private/x/trades.json --cache data/alpaca_cache
    python -m scripts.movement_price_study fetch-earnings --trades /private/x/trades.json --env-file .env --out /private/x/earnings.json
    python -m scripts.movement_price_study run --trades /private/x/trades.json --fills /private/x/fills.json \
        --daily /private/x/daily.json --earnings /private/x/earnings.json --cache data/alpaca_cache --out /private/x
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import NormalDist
import sys
import time

from scripts import entry_skill_study as es
from scripts import exit_counterfactual_study as x
from scripts import instrument_study as ins
from scripts.personal_trading_studies import HOLIDAYS

PROTOCOL_ID = "movement-price-20261113-v1"
REGISTERED_EXTRACT_SHA256 = "4ada80b1977230773bd0d919cd3ea42f766b8fcc651d5484fee8253de7c33a47"
REGISTERED_FILLS_SHA256 = "ecea7c6511f111300d58aff6ec7f99d56f9e700c0de1bcef261bbf4f378a55e3"
REGISTERED_DAILY_SHA256 = "e102bc240d96a843c349e7ff3622c366079a368be64fbfc7611482e9f13a2a4c"
RATE = 0.0372  # the journal enricher's default risk-free rate
MAX_STDEV = 10.0  # the solver's upper bound on total standard deviation to expiry
PROFILE_SESSIONS, MIN_PROFILE_SESSIONS = 20, 10
BUCKET = 5  # minutes
LATEST_LAST_BAR = 955  # a profile session must have a bar at or after 15:55
OPEN, CLOSE, EARLY_CLOSE = es.OPEN, es.CLOSE, es.EARLY_CLOSE
CLOSED = HOLIDAYS | {date(2025, 6, 19)}
BARS = es.UNDERLYING  # SPXW is profiled from SPY minute bars
BOOTSTRAP, SEED, LEVEL = 2000, 20261113, 0.95
PERIODS = ins.PERIODS
PIECES = ("direction", "movement", "iv_and_spread")
N = NormalDist()


# ---------------------------------------------------------------- Black-Scholes in total standard deviation (pure)


def bs(spot: float, strike: float, stdev: float, rt: float, kind: str) -> float:
    """Per-share value with ``stdev`` = volatility x sqrt(years) and ``rt`` = rate x years."""
    disc = math.exp(-rt)
    if stdev <= 0:
        return max(0.0, spot - strike * disc) if kind == "call" else max(0.0, strike * disc - spot)
    d1 = math.log(spot / (strike * disc)) / stdev + stdev / 2
    d2 = d1 - stdev
    if kind == "call":
        return spot * N.cdf(d1) - strike * disc * N.cdf(d2)
    return strike * disc * N.cdf(-d2) - spot * N.cdf(-d1)


def bs_delta(spot: float, strike: float, stdev: float, rt: float, kind: str) -> float:
    if stdev <= 0:
        itm = spot > strike * math.exp(-rt) if kind == "call" else spot < strike * math.exp(-rt)
        return (1.0 if kind == "call" else -1.0) if itm else 0.0
    d1 = math.log(spot / (strike * math.exp(-rt))) / stdev + stdev / 2
    return N.cdf(d1) if kind == "call" else N.cdf(d1) - 1


def solve_stdev(price: float, spot: float, strike: float, rt: float, kind: str) -> float | None:
    """The total standard deviation that reproduces ``price`` per share, or None when none does."""
    lo, hi = 1e-6, MAX_STDEV
    if not bs(spot, strike, lo, rt, kind) < price < bs(spot, strike, hi, rt, kind):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if bs(spot, strike, mid, rt, kind) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- the variance clock (pure)


def is_session(day: date) -> bool:
    return day.weekday() < 5 and day not in CLOSED


def sessions_before(day: date, count: int) -> list[date]:
    out, cursor = [], day
    while len(out) < count:
        cursor -= timedelta(days=1)
        if is_session(cursor):
            out.append(cursor)
    return sorted(out)


def close_at(day: date) -> datetime:
    minute = es.close_minute(day)
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60)


def session_variance(previous: dict, session: dict) -> tuple[float, list[float]] | None:
    """Squared overnight log return and squared 5-minute log returns of one full session, or None."""
    if not previous or not session or max(session) < LATEST_LAST_BAR:
        return None
    last_close = previous[max(previous)][1]
    price = session[min(session)][0]
    overnight = math.log(price / last_close) ** 2
    last = {}
    for m in sorted(session):
        last[(m - OPEN) // BUCKET] = session[m][1]
    buckets = []
    for b in range((CLOSE - OPEN) // BUCKET):
        now = last.get(b, price)
        buckets.append(math.log(now / price) ** 2)
        price = now
    return overnight, buckets


def profile(days: list[tuple[dict | None, dict | None]]) -> dict | None:
    """Each part of a typical day's variance as a share of the whole: one overnight share and one per 5-minute bucket."""
    used = [v for v in (session_variance(p, s) for p, s in days) if v is not None]
    if len(used) < MIN_PROFILE_SESSIONS:
        return None
    overnight = sum(u[0] for u in used) / len(used)
    buckets = [sum(u[1][b] for u in used) / len(used) for b in range(len(used[0][1]))]
    whole = overnight + sum(buckets)
    if whole <= 0:
        return None
    return {"overnight": overnight / whole, "buckets": [b / whole for b in buckets], "sessions": len(used)}


def units(shape: dict, start: datetime, end: datetime) -> float:
    """Typical-day variance units between two New York times: one per ordinary full session and the night before it."""
    if end <= start:
        return 0.0
    total, day = 0.0, start.date()
    while day <= end.date():
        if is_session(day):
            opens, closes = datetime(day.year, day.month, day.day, OPEN // 60, OPEN % 60), close_at(day)
            if start < opens <= end:
                total += shape["overnight"]
            lo, hi = max(start, opens), min(end, closes)
            for b, share in enumerate(shape["buckets"]):
                a = opens + timedelta(minutes=b * BUCKET)
                overlap = (min(hi, a + timedelta(minutes=BUCKET)) - max(lo, a)).total_seconds()
                if overlap > 0:
                    total += share * overlap / (BUCKET * 60)
        day += timedelta(days=1)
    return total


def years(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / (365.25 * 24 * 3600))


# ---------------------------------------------------------------- one trade (pure)


def piece(kind: str, strike: float, expiry: datetime, shape: dict, entry: tuple, exit_: tuple, qty: float) -> tuple[dict | None, str | None]:
    """One entry lot closed (in part) by one exit: ``entry``/``exit_`` are (time, option price per contract, stock price)."""
    t0, p0, s0 = entry
    t1, p1, s1 = exit_
    rt0, rt1 = RATE * years(t0, expiry), RATE * years(min(t1, expiry), expiry)
    left = units(shape, t0, expiry)
    if left <= 0:
        return None, "an entry with no trading time left before expiry"
    sd0 = solve_stdev(p0 / 100, s0, strike, rt0, kind)
    if sd0 is None:
        return None, "an entry price no Black-Scholes volatility reproduces"
    share = min(1.0, units(shape, t0, t1) / left)
    held_years, life_years = years(t0, min(t1, expiry)), years(t0, expiry)
    calendar_share = min(1.0, held_years / life_years) if life_years > 0 else 1.0
    direction = bs_delta(s0, strike, sd0, rt0, kind) * (s1 - s0) * 100 * qty
    start_value = bs(s0, strike, sd0, rt0, kind)
    actual = (p1 - p0) * qty

    def split(fraction: float) -> tuple[float, float]:
        moved = (bs(s1, strike, sd0 * math.sqrt(1 - fraction), rt1, kind) - start_value) * 100 * qty - direction
        return moved, actual - direction - moved

    movement, rest = split(share)
    movement_cal, rest_cal = split(calendar_share)
    return {"direction": direction, "movement": movement, "iv_and_spread": rest, "option_pnl": actual,
            "premium": p0 * qty, "moved": qty * math.log(s1 / s0) ** 2, "priced": qty * sd0 ** 2 * share,
            "contracts": qty, "moved_more": qty if math.log(s1 / s0) ** 2 > sd0 ** 2 * share else 0.0,
            "movement_calendar": movement_cal, "iv_and_spread_calendar": rest_cal}, None


def replay(trade: dict, fills: list[dict], close_on_expiry: float | None, shape: dict) -> tuple[dict | None, str | None]:
    """The trade's option P&L split into direction, movement against its price, and implied volatility and spread."""
    fills = sorted(fills, key=lambda f: (f["at"], f["fill_id"]))
    if not fills or any(f["side"] not in (x.ENTRY, x.EXIT) for f in fills):
        return None, "not a long option or fills do not allocate FIFO"
    kind, strike = trade["option_type"], float(trade["strike"])
    expiration = date.fromisoformat(trade["expiration"])
    expiry = close_at(expiration)
    lots: deque = deque()  # [contracts left, (time, price, stock)]
    parts = []
    for f in fills:
        if f["underlying"] is None:
            return None, "an entry fill without an underlying price" if f["side"] == x.ENTRY else "an exit fill without an underlying price"
        stamp = (f["at"], float(f["price"]), float(f["underlying"]))
        if f["side"] == x.ENTRY:
            lots.append([float(f["contracts"]), stamp])
            continue
        left = float(f["contracts"])
        while left > 1e-9:
            if not lots:
                return None, "not a long option or fills do not allocate FIFO"
            take = min(left, lots[0][0])
            parts.append((lots[0][1], stamp, take))
            lots[0][0] -= take
            left -= take
            if lots[0][0] <= 1e-9:
                lots.popleft()
    if lots:
        if close_on_expiry is None:
            return None, "an expired trade without the underlying's close on the expiration date"
        parts += [(stamp, (expiry, 0.0, close_on_expiry), qty) for qty, stamp in lots]
    total = defaultdict(float)
    for entry, exit_, qty in parts:
        one, reason = piece(kind, strike, expiry, shape, entry, exit_, qty)
        if one is None:
            return None, reason
        for key, value in one.items():
            total[key] += value
    return dict(total), None


# ---------------------------------------------------------------- summary (pure)


def interval(rows: list[dict], rng: random.Random) -> list[float] | None:
    by_day = defaultdict(float)
    for r in rows:
        by_day[r["day"]] += r["movement"]
    days = sorted(by_day)
    if not days:
        return None
    draws = sorted(sum(by_day[days[rng.randrange(len(days))]] for _ in days) for _ in range(BOOTSTRAP))
    tail = (1 - LEVEL) / 2
    return [round(draws[int(tail * len(draws))], 2), round(draws[min(len(draws) - 1, int((1 - tail) * len(draws)))], 2)]


def totals(rows: list[dict]) -> dict:
    add = lambda key: sum(r[key] for r in rows)  # noqa: E731
    premium, priced, contracts = add("premium"), add("priced"), add("contracts")
    out = {"trades": len(rows), **{k: round(add(k), 2) for k in (*PIECES, "option_pnl", "movement_calendar", "iv_and_spread_calendar")}}
    out["movement_per_premium_pct"] = round(out["movement"] / premium * 100, 2) if premium else None
    out["movement_ratio"] = round(add("moved") / priced, 3) if priced else None
    out["contracts_that_moved_more_pct"] = round(add("moved_more") / contracts * 100, 1) if contracts else None
    return out


def decide(band: list[float] | None, periods: dict) -> str:
    if not band:
        return "no evidence either way"
    if band[1] < 0:
        return "paid for more movement than he got"
    if band[0] > 0 and all(periods[p]["movement"] > 0 for p in PERIODS):
        return "got more movement than he paid for"
    return "no evidence either way"


def summarize(rows: list[dict]) -> dict:
    primary = [r for r in rows if not r["earnings"]]
    periods = {p: totals([r for r in primary if r["period"] == p]) for p in PERIODS}
    band = interval(primary, random.Random(SEED))
    split = lambda key: {v: totals([r for r in primary if r[key] == v]) for v in sorted({r[key] for r in primary})}  # noqa: E731
    return {"primary": {**totals(primary), "interval": band}, "periods": periods, "decision": decide(band, periods),
            "descriptive": {"held": split("held"), "dte": split("dte"), "side": split("side"),
                            "earnings_in_window": totals([r for r in rows if r["earnings"]]), "everything": totals(rows)}}


# ---------------------------------------------------------------- data and commands


def underlying_of(trades: list[dict], fills: dict[str, list[dict]]):
    for t in trades:
        entry = es.first_entry(fills.get(t["id"], []))
        if entry is not None:
            yield t, entry.date()


def fetch_bars(trades_path: Path, cache: Path) -> dict:
    from app.engine import alpaca
    if alpaca.ALPACA_DATA_FEED != es.FEED:
        raise SystemExit("set ALPACA_DATA_FEED=sip: the protocol's prices are SIP bars")
    alpaca.CACHE_DIR = cache
    trades, fills = es.load(trades_path)
    want = defaultdict(set)
    for t, day in underlying_of(trades, fills):
        for d in sessions_before(day, PROFILE_SESSIONS + 1):
            want[d].add(BARS.get(t["ticker"], t["ticker"]))
    missing = 0
    for day in sorted(want):
        got = alpaca.fetch_minute_bars_for_date(sorted(want[day]), day)
        missing += sum(1 for t in want[day] if not got.get(t))
    return {"sessions": len(want), "ticker_sessions": sum(len(v) for v in want.values()), "without_bars": missing}


def fetch_earnings(trades_path: Path, env_file: Path, out: Path) -> dict:
    import httpx
    from dotenv import dotenv_values
    import os
    from app.engine.symbol_info_events import parse_earnings, report_dates
    from scripts.radar_long_history import get_json
    keys = {**dotenv_values(env_file), **os.environ}
    base = keys.get("TRADIER_BASE_URL", "https://api.tradier.com").rstrip("/")
    headers = {"Authorization": f"Bearer {keys['TRADIER_API_KEY']}", "Accept": "application/json"}
    trades, _ = es.load(trades_path)
    symbols = sorted({t["ticker"] for t in trades} - {"SPXW", "SPX"})
    dates = {}
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(symbols), 20):
            payload = get_json(client, f"{base}/beta/markets/fundamentals/calendars", {"symbols": ",".join(symbols[i:i + 20])}, headers)
            for symbol, rows in parse_earnings(payload).items():
                found = sorted({r["date"] for r in report_dates(rows)})
                if found:
                    dates[symbol] = found
            time.sleep(1.1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"requested": symbols, "dates": dates}, indent=1))
    return {"requested": len(symbols), "with_dates": len(dates)}


def run(trades_path: Path, fills_path: Path, daily_path: Path, earnings_path: Path, cache: Path, out: Path) -> dict:
    data = json.loads(trades_path.read_text())
    if data.get("protocol_id") != x.PROTOCOL_ID:
        raise SystemExit(f"extract is not the {x.PROTOCOL_ID} extract")
    extra = {f["fill_id"]: f for f in json.loads(fills_path.read_text())}
    raw = json.loads(daily_path.read_text())["raw"]
    earnings = json.loads(earnings_path.read_text())
    reports = earnings["dates"]
    bars = es.bar_reader(cache)
    by_trade = defaultdict(list)
    for f in data["fills"]:
        more = extra.get(f["fill_id"], {})
        by_trade[f["trade_id"]].append({**f, "at": datetime.fromisoformat(f["executed_at"]), "underlying": more.get("underlying")})
    rows, excluded, shapes = [], defaultdict(int), {}
    for t in sorted(data["trades"], key=lambda t: (t["opened_at"], t["id"])):
        own = by_trade.get(t["id"], [])
        if not own:
            excluded["not a long option or fills do not allocate FIFO"] += 1
            continue
        first = min(f["at"] for f in own).date()
        last = max(f["at"] for f in own).date()
        expiration = date.fromisoformat(t["expiration"])
        if t["status"] == "expired":
            last = max(last, expiration)
        ticker = ins.UNDERLYING.get(t["ticker"], t["ticker"])
        if ins.spans_split(ticker, first, last):
            excluded["a hold that spans a share split of the underlying"] += 1
            continue
        stock = BARS.get(t["ticker"], t["ticker"])
        if (stock, first) not in shapes:
            days = sessions_before(first, PROFILE_SESSIONS + 1)
            shapes[(stock, first)] = profile([(bars(stock, a), bars(stock, b)) for a, b in zip(days, days[1:])])
        shape = shapes[(stock, first)]
        if shape is None:
            excluded["fewer than 10 usable sessions of minute bars in the 20 before entry"] += 1
            continue
        result, reason = replay(t, own, raw.get(ticker, {}).get(expiration.isoformat()), shape)
        if result is None:
            excluded[reason] += 1
            continue
        window = (first.isoformat(), expiration.isoformat())
        rows.append({"id": t["id"], "day": first.isoformat(), "period": "exploration" if first < x.CHECK_START else "check",
                     "side": t["option_type"], "dte": ins.dte_bucket(first, expiration),
                     "held": "past the entry session" if last > first else "same session",
                     "earnings": any(window[0] <= d <= window[1] for d in reports.get(t["ticker"], [])),
                     **{k: round(v, 6) for k, v in result.items()}})
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    receipt = {**x.provenance(trades_path), "protocol_id": PROTOCOL_ID, "fills_sha256": digest(fills_path),
               "daily_sha256": digest(daily_path), "earnings_sha256": digest(earnings_path)}
    receipt["inputs_are_registered"] = (receipt["extract_sha256"], receipt["fills_sha256"], receipt["daily_sha256"]) == (
        REGISTERED_EXTRACT_SHA256, REGISTERED_FILLS_SHA256, REGISTERED_DAILY_SHA256)
    results = {"protocol_id": PROTOCOL_ID, "provenance": receipt, "extract_trades": len(data["trades"]), "scored": len(rows),
               "excluded": dict(excluded),
               "symbols_without_report_dates": sorted(set(earnings["requested"]) - set(reports)), **summarize(rows)}
    folder = out / "movement-price"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "results.json").write_text(json.dumps(results, indent=2))
    (folder / "trades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("fetch-bars")
    b.add_argument("--trades", type=Path, required=True)
    b.add_argument("--cache", type=Path, required=True)
    e = sub.add_parser("fetch-earnings")
    for name in ("--trades", "--env-file", "--out"):
        e.add_argument(name, type=Path, required=True)
    r = sub.add_parser("run")
    for name in ("--trades", "--fills", "--daily", "--earnings", "--cache", "--out"):
        r.add_argument(name, type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "fetch-bars":
        print(json.dumps(fetch_bars(args.trades, args.cache), indent=2))
    elif args.command == "fetch-earnings":
        print(json.dumps(fetch_earnings(args.trades, args.env_file, args.out), indent=2))
    else:
        print(json.dumps(run(args.trades, args.fills, args.daily, args.earnings, args.cache, args.out), indent=2))


if __name__ == "__main__":
    sys.exit(main())
