"""Research only: downside put setups for the S1 setup scanner.

Not wired into the live scanner. Replays the s1-v1 adoption window
(135 sessions, 2026-03-02 .. 2026-09-11; 2026-09-14 onward stays held out)
on Alpaca SIP 1-minute bars for the s1-v1 universe and prices each paper
trade from historical Alpaca option 1-minute bars.

Setups:
  orb_call   - s1-v1 opening-range break call, unchanged (baseline under the same pricing)
  orb_put    - mirror: first completed 5-min bar closing below the 09:30-09:45 low,
               closing by 10:45, below VWAP, volume >= opening-range average.
               Stop OR midpoint, target 2x stop distance, one per symbol per day.
  trend_put  - continuation: EMA9 below VWAP, the previous 5-min bar pulled back to
               touch EMA9 from below and closed below EMA9 and VWAP, the current bar
               closes below the previous bar's low, below EMA9 and below the opening-range low. Stop = pullback high
               + 0.05 ATR, target 2x stop distance, at most two per symbol per day.

Paper trade (contract rules from docs/agent/setup-scanner-contract.md):
  expiry same day if listed else nearest 3-7 DTE; delta 0.25-0.45 closest to 0.35
  (delta from Black-Scholes on the last option trade before detection); option volume
  >= 100 before detection. OI and spread cannot be checked historically.
  Entry/exit at the VWAP of the option's first 1-min bar starting at/after the decision
  minute (within 2 minutes, else unresolved); underlying stop/target on 1-min bars after
  the entry minute; 60-min time stop; flat 15:45 (0DTE) / 15:50. $0.65 per side.
  Costs: trade price plus a haircut h each side (h = 0, 3%, 6% of premium).

Run from the repo root with the main checkout's venv and .env:
  ALPACA_DATA_FEED=sip python research/s1_downside_puts/backtest.py
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("ALPACA_DATA_FEED", "sip")

from app.engine import alpaca, scanner_rules as R  # noqa: E402

MAIN_CACHE = Path(os.environ.get("ALPACA_CACHE_DIR", "/Users/user/TradeJournal/backend/data/alpaca_cache"))
alpaca.CACHE_DIR = MAIN_CACHE
OUT = Path(os.environ.get("OUT_DIR", Path(__file__).parent / "out"))
OUT.mkdir(exist_ok=True)
CONTRACT_CACHE = OUT / "contracts_cache"
CONTRACT_CACHE.mkdir(exist_ok=True)

ET = ZoneInfo("America/New_York")
START, END = date(2026, 3, 2), date(2026, 9, 11)
UNIVERSE = R.UNIVERSE
RATE = 0.04
HAIRCUTS = (0.0, 0.03, 0.06)
TREND_MAX_PER_DAY = 2
# Live S1 prices from quotes within 2 minutes; historical trade bars are sparser, so allow 5.
FILL_WINDOW = 5 * 60


# ------------------------------------------------------------------ data

def sessions() -> list[date]:
    days = sorted(p.stem for p in (MAIN_CACHE / "stocks/1Min/sip/SPY").glob("*.json"))
    return [date.fromisoformat(d) for d in days if START.isoformat() <= d <= END.isoformat()]


def minutes_for(symbol: str, day: date) -> list[dict]:
    raw = alpaca.fetch_minute_bars_for_date([symbol], day).get(symbol, [])
    out = []
    for b in raw:
        t = int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp())
        out.append({"time": t, "end_time": t + 60, "open": b["o"], "high": b["h"], "low": b["l"],
                    "close": b["c"], "volume": b["v"]})
    return out


def session_bounds(day: date) -> tuple[int, int]:
    o = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)
    return int(o.timestamp()), int(o.timestamp()) + 390 * 60


def daily_by_symbol(end: date | None = None) -> dict[str, list[dict]]:
    bars = alpaca.fetch_daily_bars(list(UNIVERSE), date(2025, 12, 1), end or END)
    out = {}
    for sym, rows in bars.items():
        out[sym] = [{"date": r["t"][:10], "high": r["h"], "low": r["l"], "close": r["c"], "open": r["o"]} for r in rows]
    return out


def _paper_get(path: str, params: dict) -> dict:
    headers = {"APCA-API-KEY-ID": alpaca.ALPACA_API_KEY, "APCA-API-SECRET-KEY": alpaca.ALPACA_API_SECRET}
    for _ in range(5):
        alpaca._limiter.wait()
        r = httpx.get(f"https://paper-api.alpaca.markets{path}", params=params, headers=headers, timeout=30)
        if r.status_code == 429:
            import time
            time.sleep(20)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("contracts request failed")


def listed_contracts(symbol: str, day: date, kind: str, spot: float) -> list[dict]:
    key = CONTRACT_CACHE / f"{symbol}_{day}_{kind}.json"
    if key.exists():
        return json.loads(key.read_text())
    rows = []
    # Expirations still in the future at run time are listed as active, not inactive.
    statuses = ("inactive", "active") if day + timedelta(days=7) >= date.today() else ("inactive",)
    for status in statuses:
        token = None
        while True:
            params = {"underlying_symbols": symbol, "expiration_date_gte": day.isoformat(),
                      "expiration_date_lte": (day + timedelta(days=7)).isoformat(), "type": kind,
                      "status": status, "strike_price_gte": f"{spot * 0.9:.2f}",
                      "strike_price_lte": f"{spot * 1.1:.2f}", "limit": 10000}
            if token:
                params["page_token"] = token
            data = _paper_get("/v2/options/contracts", params)
            rows += [{"symbol": c["symbol"], "expiration": c["expiration_date"], "strike": float(c["strike_price"]),
                      "multiplier": int(float(c.get("multiplier") or 100)), "root": c.get("root_symbol")}
                     for c in data.get("option_contracts", [])]
            token = data.get("next_page_token")
            if not token:
                break
    key.write_text(json.dumps(rows))
    return rows


def option_minutes(symbols: list[str], day: date) -> dict[str, list[dict]]:
    o, c = session_bounds(day)
    start = datetime.fromtimestamp(o, ET)
    end = datetime.fromtimestamp(c, ET)
    raw = alpaca.fetch_option_bars(symbols, "1Min", start, end)
    out = {}
    for sym, rows in raw.items():
        out[sym] = [{"time": int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp()),
                     "close": b["c"], "vwap": b.get("vw") or b["c"], "volume": b["v"]} for b in rows]
    return out


# ------------------------------------------------------------------ black-scholes

def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(kind, s, k, t, vol):
    if t <= 0 or vol <= 0:
        return max(0.0, s - k) if kind == "call" else max(0.0, k - s)
    d1 = (math.log(s / k) + (RATE + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if kind == "call":
        return s * _ncdf(d1) - k * math.exp(-RATE * t) * _ncdf(d2)
    return k * math.exp(-RATE * t) * _ncdf(-d2) - s * _ncdf(-d1)


def bs_delta(kind, s, k, t, price):
    lo, hi = 0.01, 5.0
    if price <= bs_price(kind, s, k, t, lo) or price >= bs_price(kind, s, k, t, hi):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if bs_price(kind, s, k, t, mid) > price:
            hi = mid
        else:
            lo = mid
    vol = (lo + hi) / 2
    d1 = (math.log(s / k) + (RATE + vol * vol / 2) * t) / (vol * math.sqrt(t))
    return _ncdf(d1) if kind == "call" else _ncdf(d1) - 1


def years_to_expiry(now: int, expiration: str) -> float:
    e = date.fromisoformat(expiration)
    close = datetime(e.year, e.month, e.day, 16, 0, tzinfo=ET).timestamp()
    return max(close - now, 15 * 60) / (365 * 24 * 3600)


# ------------------------------------------------------------------ setups

def scan_extra(bars, atr, open_at, last_end):
    """orb_put and trend_put signals for one symbol-day (own cooldown applied later)."""
    opening = [b for b in bars if b["start"] < open_at + R.FIRST_BAR_AFTER]
    if len(opening) < R.FIRST_BAR_AFTER // R.BAR_SECONDS:
        return []
    or_high, or_low = max(b["high"] for b in opening), min(b["low"] for b in opening)
    or_volume = sum(b["volume"] for b in opening) / len(opening)
    orb_close_by = open_at + (R.ORB_LAST_CLOSE_MINUTE - 9 * 60 - 30) * 60
    out, orb_done, prev = [], False, None
    for bar in bars:
        vwap = bar["vwap"]
        if vwap is None:
            prev = bar
            continue
        if bar["start"] >= open_at + R.FIRST_BAR_AFTER and bar["end"] <= last_end and prev is not None:
            if not orb_done and bar["close"] < or_low:
                orb_done = True
                if bar["end"] <= orb_close_by and bar["close"] < vwap and bar["volume"] >= R.ORB_VOLUME_RATIO * or_volume:
                    stop = (or_high + or_low) / 2
                    s = R._signal(bar, "orb_put", "short", stop, bar["close"] - R.ORB_TARGET_R * (stop - bar["close"]),
                                  atr, or_high, or_low)
                    out.append(s)
            pv = prev["vwap"]
            if (pv is not None and prev["ema9"] < pv and bar["ema9"] < vwap
                    and prev["high"] >= prev["ema9"] and prev["close"] < prev["ema9"] and prev["close"] < pv
                    and bar["close"] < prev["low"] and bar["close"] < bar["ema9"] and bar["close"] < or_low):
                stop = max(prev["high"], bar["high"]) + R.FADE_STOP_BUFFER_ATR * atr
                out.append(R._signal(bar, "trend_put", "short", stop,
                                     bar["close"] - R.ORB_TARGET_R * (stop - bar["close"]), atr, or_high, or_low))
        prev = bar
    return out


# ------------------------------------------------------------------ paper trade

def first_bar_at(rows, moment):
    """The first option trade bar starting in the decision minute or within FILL_WINDOW after it."""
    minute = moment // 60 * 60
    for r in rows:
        if minute <= r["time"] <= minute + FILL_WINDOW:
            return r
        if r["time"] > minute + FILL_WINDOW:
            return None
    return None


def choose(symbol, day, sig, minutes):
    kind = "call" if sig["direction"] == "long" else "put"
    now = sig["bar_end"]
    spot = sig["facts"]["close"]
    contracts = listed_contracts(symbol, day, kind, spot)
    exps = sorted({date.fromisoformat(c["expiration"]) for c in contracts})
    exp = R.pick_expiration(exps, day)
    if exp is None:
        return None, "no_expiration"
    pool = sorted((c for c in contracts if c["expiration"] == exp.isoformat()), key=lambda c: abs(c["strike"] - spot))[:24]
    bars = option_minutes([c["symbol"] for c in pool], day)
    best = None
    for c in pool:
        rows = [r for r in bars.get(c["symbol"], []) if r["time"] + 60 <= now]
        if not rows or sum(r["volume"] for r in rows) < R.CONTRACT["min_volume"] or now - rows[-1]["time"] > 10 * 60:
            continue
        delta = bs_delta(kind, spot, c["strike"], years_to_expiry(now, c["expiration"]), rows[-1]["close"])
        if delta is None or not (R.CONTRACT["delta_min"] <= abs(delta) <= R.CONTRACT["delta_max"]):
            continue
        rank = (abs(abs(delta) - R.CONTRACT["delta_target"]), c["strike"])
        if best is None or rank < best[0]:
            best = (rank, c, delta)
    if best is None:
        return None, "no_contract"
    c = dict(best[1], delta=round(best[2], 3), dte=(exp - day).days)
    c["bars"] = bars[c["symbol"]]
    return c, None


def simulate(symbol, day, sig, minutes, open_at, close_at):
    contract, why = choose(symbol, day, sig, minutes)
    if contract is None:
        return {"status": why}
    entry_at = sig["bar_end"]
    flat = R.flat_at(open_at, close_at, contract["dte"] == 0)
    ex = R.exit_condition(sig["direction"], sig["stop"], sig["target"], minutes, entry_at,
                          entry_at + R.TIME_STOP_SECONDS, flat, close_at + 3600, 0)
    entry = first_bar_at(contract["bars"], entry_at)
    out = first_bar_at(contract["bars"], ex["condition_at"]) if ex else None
    base = {"contract": contract["symbol"], "delta": contract["delta"], "dte": contract["dte"],
            "exit_reason": ex["reason"] if ex else None, "exit_at": ex["condition_at"] if ex else None}
    if entry is None or out is None:
        return dict(base, status="unresolved")
    m = contract["multiplier"]
    res = {}
    for h in HAIRCUTS:
        paid = entry["vwap"] * (1 + h)
        got = out["vwap"] * (1 - h)
        pnl = (got - paid) * m - 2 * R.COMMISSION_PER_SIDE
        res[f"pnl_h{int(h*100)}"] = round(pnl, 2)
        res[f"rop_h{int(h*100)}"] = round(pnl / (paid * m + R.COMMISSION_PER_SIDE), 4)
    return dict(base, status="filled", entry=entry["vwap"], exit=out["vwap"], **res)


# ------------------------------------------------------------------ main

def classify(day_minutes, open_at, close_at, atr):
    rows = [m for m in day_minutes if open_at <= m["time"] < close_at]
    if not rows:
        return None
    o, c = rows[0]["open"], rows[-1]["close"]
    hi, lo = max(r["high"] for r in rows), min(r["low"] for r in rows)
    move = (c - o) / atr
    pos = (c - lo) / (hi - lo) if hi > lo else 0.5
    if move <= -0.5 and pos <= 0.3:
        kind = "trend_down"
    elif move >= 0.5 and pos >= 0.7:
        kind = "trend_up"
    else:
        kind = "choppy"
    return {"type": kind, "open": o, "close": c, "high": hi, "low": lo, "move_atr": round(move, 3)}


def main():
    days = sessions()
    daily = daily_by_symbol()
    results, daytypes = [], []
    for n, day in enumerate(days, 1):
        open_at, close_at = session_bounds(day)
        last_end = open_at + (R.LAST_BAR_END_MINUTE - 9 * 60 - 30) * 60
        for sym in UNIVERSE:
            hist = [d for d in daily.get(sym, []) if d["date"] < day.isoformat()]
            atr = R.atr14(hist)
            mins = minutes_for(sym, day)
            if atr is None or not mins:
                print("skip", sym, day, file=sys.stderr)
                continue
            bars = R.five_minute_bars(mins, open_at, close_at)
            dayinfo = classify(mins, open_at, close_at, atr)
            daytypes.append({"day": day.isoformat(), "symbol": sym, **dayinfo})
            sigs = [s for s in R.scan(bars, atr, open_at, last_end, set()) if s["setup"] == "orb"]
            for s in sigs:
                s["setup"] = "orb_call"
            sigs += scan_extra(bars, atr, open_at, last_end)
            session_mins = [m for m in mins if open_at <= m["time"] < close_at]
            kept, last, counts, busy = [], {}, {}, {}
            for s in sorted(sigs, key=lambda s: s["bar_end"]):
                k = s["setup"]
                cap = TREND_MAX_PER_DAY if k == "trend_put" else 1
                if counts.get(k, 0) >= cap or s["bar_end"] < busy.get(k, 0) or s["bar_end"] - last.get(k, -10**9) < R.COOLDOWN_SECONDS:
                    continue
                trade = simulate(sym, day, s, session_mins, open_at, close_at)
                counts[k] = counts.get(k, 0) + 1
                last[k] = s["bar_end"]
                busy[k] = trade.get("exit_at") or s["bar_end"]
                results.append({"day": day.isoformat(), "symbol": sym, "setup": k, "direction": s["direction"],
                                "time": datetime.fromtimestamp(s["bar_end"], ET).strftime("%H:%M"),
                                "flags": s["flags"], "entry_px": s["facts"]["close"], "stop": s["stop"],
                                "target": s["target"], "or_high": s["facts"]["opening_range_high"],
                                "or_low": s["facts"]["opening_range_low"], "day_type": dayinfo["type"],
                                "day_close": dayinfo["close"], "day_move_atr": dayinfo["move_atr"], **trade})
        print(f"{n}/{len(days)} {day} trades so far {len(results)}", file=sys.stderr, flush=True)
    (OUT / "daytypes.json").write_text(json.dumps(daytypes))
    (OUT / "trades.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
