"""Historical SessionData for the opening lab (SPY and QQQ minute + daily bars).

Minute bars, in order: the lab cache (``research/opening_lab/.cache/``), the
read-only Alpaca SIP minute cache in the main checkout, then, only when
``fetch=True``, Alpaca's market-data REST API. Daily bars come ONLY from the
lab cache, fetched raw (``adjustment=raw``, feed sip): the main checkout's
daily cache is dividend-adjusted and must not be mixed with raw minutes.
Fetched data is written to the lab cache only; the main cache is never written.

``load_session`` returns the SessionData dict described in ``contract.py`` with
``news`` and ``macro`` left empty for ``context.attach_context``.

CLI: ``python -m research.opening_lab.data prefetch --start YYYY-MM-DD --end YYYY-MM-DD``
"""

import argparse
import json
import math
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from research.opening_lab.contract import ET, SYMBOLS, UTC, et_datetime, et_hhmm

LAB_DIR = Path(__file__).resolve().parent
CACHE_DIR = LAB_DIR / ".cache"
MAIN_CACHE_DIR = Path("/Users/user/TradeJournal/backend/data/alpaca_cache/stocks")
ENV_PATH = Path("/Users/user/TradeJournal/backend/.env")

DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
CALENDAR_URL = "https://paper-api.alpaca.markets/v2/calendar"
FEED = "sip"

WINDOW_START, WINDOW_END = "04:00", "11:00"  # kept minutes, ET (end exclusive)
RTH_OPEN, RTH_END = "09:30", "10:30"          # usability window, ET (end exclusive)
MIN_USABLE_MINUTES = 30                        # of the 60 in the usability window
PROFILE_SESSIONS = 20
PROFILE_MAX_LOOKBACK = 40
DAILY_SESSIONS = 30
FETCH_CHUNK_SESSIONS = 6
MIN_REQUEST_INTERVAL = 0.45                    # ~130 requests/minute

_last_request = 0.0


class SessionUnavailable(Exception):
    """The session's minute data is missing or too thin to replay."""


# --- HTTP ---------------------------------------------------------------------
def alpaca_headers():
    """Auth headers from the main checkout's .env. Never print the result."""
    from dotenv import dotenv_values

    env = dotenv_values(ENV_PATH)
    key = env.get("ALPACA_API_KEY") or os.environ.get("ALPACA_API_KEY")
    secret = env.get("ALPACA_API_SECRET") or os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError("Alpaca keys not found (ALPACA_API_KEY / ALPACA_API_SECRET)")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _request(url, params):
    """Throttled GET returning parsed JSON; retries 429/5xx a few times."""
    global _last_request
    import httpx

    headers = alpaca_headers()
    for attempt in range(4):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=30)
        except httpx.TransportError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == 3:
                resp.raise_for_status()
            time.sleep(2 ** (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")


def _utc_iso(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_bars(timeframe, start, end, symbols=SYMBOLS):
    """All raw bars for ``symbols`` (default SPY, QQQ) between two aware datetimes:
    {symbol: [raw bars]}."""
    out = {s: [] for s in symbols}
    params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": _utc_iso(start),
              "end": _utc_iso(end), "feed": FEED, "adjustment": "raw", "limit": 10000}
    while True:
        page = _request(DATA_URL, params)
        for sym, bars in (page.get("bars") or {}).items():
            if sym in out:
                out[sym].extend(bars)
        token = page.get("next_page_token")
        if not token:
            return out
        params = {**params, "page_token": token}


# --- Normalization ------------------------------------------------------------
def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def normalize_bars(raw, day):
    """Raw Alpaca 1Min bars -> (Bar1m list for ``day`` 04:00-11:00 ET, stats)."""
    lo = int(et_datetime(day, WINDOW_START).timestamp())
    hi = int(et_datetime(day, WINDOW_END).timestamp())
    stats = {"raw": len(raw), "malformed": 0, "outside_window": 0, "duplicates": 0}
    by_t = {}
    for r in raw:
        try:
            t = _epoch(r["t"])
            o, h, l, c, v = r["o"], r["h"], r["l"], r["c"], r["v"]
        except (KeyError, TypeError, ValueError, AttributeError):
            stats["malformed"] += 1
            continue
        if not all(_finite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0 or h < l:
            stats["malformed"] += 1
            continue
        if not lo <= t < hi:
            stats["outside_window"] += 1
            continue
        vw, n = r.get("vw"), r.get("n")
        if t in by_t:
            stats["duplicates"] += 1
        by_t[t] = {"t": t, "o": float(o), "h": float(h), "l": float(l), "c": float(c),
                   "v": int(v), "vw": float(vw) if _finite(vw) else None,
                   "n": int(n) if _finite(n) else None}
    bars = [by_t[t] for t in sorted(by_t)]
    stats["kept"] = len(bars)
    return bars, stats


def _daily_bar(r):
    """Raw Alpaca daily bar -> Bar1D, or None if malformed."""
    try:
        d = datetime.fromisoformat(r["t"].replace("Z", "+00:00")).astimezone(ET).date().isoformat()
        o, h, l, c, v = r["o"], r["h"], r["l"], r["c"], r["v"]
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not all(_finite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0 or h < l:
        return None
    return {"date": d, "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": int(v)}


# --- Cache files ---------------------------------------------------------------
def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")))
    tmp.replace(path)


def _lab_minutes_path(sym, day):
    return CACHE_DIR / "minutes" / sym / f"{day}.json"


def _main_minutes_path(sym, day):
    return MAIN_CACHE_DIR / "1Min" / FEED / sym / f"{day}.json"


def _session_complete(day, now=None):
    """True once the session's extended hours (to 20:00 ET) have ended."""
    now = now or datetime.now(ET)
    return now >= et_datetime(day, "20:00")


def cached_minutes(sym, day):
    """(bars, source) from the caches, or (None, None) when not cached.

    A main-cache file is accepted only if it runs past the kept window (so a
    file written mid-session is not mistaken for a full day). A lab-cache file
    may be an empty list: that records "fetched, Alpaca had nothing".
    """
    lab = _read_json(_lab_minutes_path(sym, day))
    if isinstance(lab, list):
        return lab, "lab_cache"
    raw = _read_json(_main_minutes_path(sym, day))
    if isinstance(raw, list) and raw:
        cutoff = int(et_datetime(day, WINDOW_END).timestamp())
        try:
            reaches_cutoff = max(_epoch(r["t"]) for r in raw) >= cutoff
        except (KeyError, TypeError, ValueError):
            reaches_cutoff = False
        if reaches_cutoff:
            return normalize_bars(raw, day)[0], "main_cache"
    return None, None


def _missing_minute_days(days):
    return [d for d in days if any(cached_minutes(s, d)[0] is None for s in SYMBOLS)]


def ensure_minutes(days, fetch):
    """Fetch (and cache) minutes for completed sessions in ``days`` that are not cached."""
    if not fetch:
        return
    missing = [d for d in _missing_minute_days(days) if _session_complete(d)]
    for i in range(0, len(missing), FETCH_CHUNK_SESSIONS):
        chunk = missing[i:i + FETCH_CHUNK_SESSIONS]
        raw = _fetch_bars("1Min", et_datetime(chunk[0], WINDOW_START), et_datetime(chunk[-1], "20:00"))
        for sym in SYMBOLS:
            for d in chunk:
                bars, _ = normalize_bars(raw[sym], d)
                _write_json(_lab_minutes_path(sym, d), bars)


def _daily_maps():
    """{symbol: {date: Bar1D}} from the lab's raw daily cache only.

    The main checkout's 1Day cache is deliberately not read: the app fetches it
    with adjustment=all (dividend-adjusted), which would not match raw minutes.
    """
    out = {}
    for sym in SYMBOLS:
        bars = (_daily_bar(r) if "date" not in r else r for r in _read_json(CACHE_DIR / "daily" / f"{sym}.json") or [])
        out[sym] = {b["date"]: b for b in bars if b}
    return out


def ensure_daily(days, fetch):
    """Fetch raw daily bars for completed sessions in ``days`` missing from the lab cache.

    Stored bars are never rewritten: a completed session's raw bar is final."""
    if not fetch:
        return
    maps = _daily_maps()
    missing = [d for d in days if _session_complete(d) and any(d not in maps[s] for s in SYMBOLS)]
    if not missing:
        return
    raw = _fetch_bars("1Day", et_datetime(missing[0], "00:00"), et_datetime(missing[-1], "20:00"))
    for sym in SYMBOLS:
        have = _read_json(CACHE_DIR / "daily" / f"{sym}.json") or []
        merged = {b["date"]: b for b in have}
        for r in raw[sym]:
            bar = _daily_bar(r)
            if bar and bar["date"] not in merged and _session_complete(bar["date"]):
                merged[bar["date"]] = bar
        _write_json(CACHE_DIR / "daily" / f"{sym}.json", [merged[d] for d in sorted(merged)])


# --- Calendar -----------------------------------------------------------------
def _calendar_cache():
    cache = _read_json(CACHE_DIR / "calendar.json")
    if not isinstance(cache, dict):
        cache = {}
    return {"days": cache.get("days", {}), "covered": cache.get("covered", [])}


def _derived_calendar(start, end):
    """Fallback when no calendar is cached: weekdays that have SPY data, regular hours."""
    dates = set()
    for folder in (MAIN_CACHE_DIR / "1Min" / FEED / "SPY", CACHE_DIR / "minutes" / "SPY"):
        if folder.is_dir():
            dates.update(p.stem for p in folder.glob("*.json") if p.stat().st_size > 2)
    dates.update(_daily_maps()["SPY"])
    return {d: {"open": "09:30", "close": "16:00"} for d in sorted(dates)
            if start <= d <= end and date.fromisoformat(d).weekday() < 5}


def calendar(start, end, *, fetch=False):
    """({date: {"open", "close"}}, source) for sessions in [start, end]; source is
    "alpaca" (cached or fetched) or "derived" (inferred from cached data)."""
    cache = _calendar_cache()
    if not any(s <= start and end <= e for s, e in cache["covered"]):
        if not fetch:
            return _derived_calendar(start, end), "derived"
        rows = _request(CALENDAR_URL, {"start": start, "end": end})
        for r in rows:
            cache["days"][r["date"]] = {"open": r["open"], "close": r["close"]}
        cache["covered"].append([start, end])
        _write_json(CACHE_DIR / "calendar.json", cache)
    return {d: v for d, v in sorted(cache["days"].items()) if start <= d <= end}, "alpaca"


def trading_days(start, end, *, fetch=False):
    """Session dates in [start, end] (weekends and market holidays excluded)."""
    return list(calendar(start, end, fetch=fetch)[0])


def _shift(day, days):
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


# --- History (shared with live.py) --------------------------------------------
def history(day, *, fetch=False):
    """Prior-session context for ``day``: daily bars, volume profiles, provenance.

    Returns ``(per_symbol, prov)`` where ``per_symbol[sym]`` has ``daily`` (up to
    30 sessions strictly before ``day``, oldest first) and ``volume_profile``.
    """
    cal, cal_source = calendar(_shift(day, -75), day, fetch=fetch)
    prior = [d for d in cal if d < day]
    gaps = []
    ensure_daily(prior[-DAILY_SESSIONS:], fetch)
    maps = _daily_maps()
    candidates = [d for d in reversed(prior) if cal[d]["close"] == "16:00"][:PROFILE_MAX_LOOKBACK]
    ensure_minutes(candidates, fetch)

    per_symbol, prov = {}, {"calendar": cal_source, "daily": {}, "volume_profile": {}}
    for sym in SYMBOLS:
        daily = [maps[sym][d] for d in sorted(maps[sym]) if d < day][-DAILY_SESSIONS:]
        if prior and (not daily or daily[-1]["date"] != prior[-1]):
            gaps.append(f"{sym}:daily_missing_prior_session={prior[-1]}")
        prov["daily"][sym] = {"count": len(daily), "last": daily[-1]["date"] if daily else None,
                              "source": "lab_cache", "adjustment": "raw", "feed": FEED}

        totals, used = {}, []
        for d in candidates:
            if len(used) == PROFILE_SESSIONS:
                break
            bars, _ = cached_minutes(sym, d)
            rth = [b for b in bars or [] if "09:30" <= et_hhmm(b["t"]) < "11:00"]
            if not rth:
                continue
            used.append(d)
            for b in rth:
                key = et_hhmm(b["t"])
                totals[key] = totals.get(key, 0) + b["v"]
        profile = {}
        for m in range(90):
            key = f"{9 + (30 + m) // 60:02d}:{(30 + m) % 60:02d}"
            profile[key] = totals.get(key, 0) / len(used) if used else 0.0
        if len(used) < PROFILE_SESSIONS:
            gaps.append(f"{sym}:volume_profile_sessions={len(used)}")
        prov["volume_profile"][sym] = {"sessions_used": len(used),
                                       "first": min(used) if used else None,
                                       "last": max(used) if used else None}
        per_symbol[sym] = {"daily": daily, "volume_profile": profile}
    prov["gaps"] = gaps
    return per_symbol, prov


# --- Public API ---------------------------------------------------------------
def load_session(day, *, fetch=False):
    """SessionData for one New York session date (``news`` and ``macro`` empty)."""
    cal, cal_source = calendar(day, day, fetch=fetch)
    if cal_source == "alpaca" and day not in cal:
        raise SessionUnavailable(f"{day}: not a trading day")
    ensure_minutes([day], fetch)
    per_symbol, hist_prov = history(day, fetch=fetch)

    gaps = list(hist_prov.pop("gaps"))
    prov = {"feed": FEED, "adjustment": "raw", "minutes": {}, **hist_prov}
    start, end = int(et_datetime(day, RTH_OPEN).timestamp()), int(et_datetime(day, RTH_END).timestamp())
    symbols = {}
    for sym in SYMBOLS:
        bars, source = cached_minutes(sym, day)
        if bars is None:
            if not _session_complete(day):
                raise SessionUnavailable(f"{day}: session is not complete yet (data is final after 20:00 ET)")
            raise SessionUnavailable(f"{day}: no minute data for {sym}" + ("" if fetch else " (try fetch=True)"))
        present = len({b["t"] for b in bars if start <= b["t"] < end})
        if present < MIN_USABLE_MINUTES:
            raise SessionUnavailable(f"{day}: {sym} has {present}/60 minutes in 09:30-10:30")
        if present < 60:
            gaps.append(f"{sym}:missing_minutes_0930_1030={60 - present}")
        prov["minutes"][sym] = {"source": source, "count": len(bars), "rth_0930_1030": present}
        symbols[sym] = {**per_symbol[sym], "minutes": bars}

    close = cal.get(day, {"close": "16:00"})["close"]
    prov["gaps"] = gaps
    return {"date": day,
            "schedule": {"open": "09:30", "close": close, "early_close": close != "16:00"},
            "symbols": symbols, "news": [], "macro": [], "provenance": prov}


def prefetch(start, end):
    """Make sure minutes (plus 20 prior sessions for volume profiles), daily bars and
    the calendar are cached for SPY and QQQ over [start, end]. Returns a summary."""
    cal, _ = calendar(_shift(start, -75), end, fetch=True)
    sessions = [d for d in cal if start <= d <= end]
    prior = [d for d in cal if d < start and cal[d]["close"] == "16:00"][-PROFILE_MAX_LOOKBACK:]
    needed = prior + sessions
    before = len(_missing_minute_days(needed))
    ensure_minutes(needed, fetch=True)
    ensure_daily([d for d in cal if d <= end][-(len(sessions) + DAILY_SESSIONS + 5):], fetch=True)
    still_missing = _missing_minute_days(needed)
    empty = [d for d in sessions if any(not (cached_minutes(s, d)[0]) for s in SYMBOLS)]
    return {"start": start, "end": end, "sessions": len(sessions), "prior_sessions": len(prior),
            "minute_days_fetched": before - len(still_missing),
            "minute_days_still_missing": still_missing, "sessions_without_minutes": empty,
            "early_closes": [d for d in sessions if cal[d]["close"] != "16:00"]}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.opening_lab.data")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prefetch", help="cache SPY/QQQ bars for a date range")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prefetch(args.start, args.end), indent=2))


if __name__ == "__main__":
    main()
