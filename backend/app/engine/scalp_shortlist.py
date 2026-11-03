"""Run the owner-only, finite 9:40 ET scalp shortlist paper study.

This job stores only study market bars and paper decisions in its isolated
directory. It never reads or writes the trade journal or brokerage.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from datetime import date, datetime, time as wall_time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from app.engine import alpaca, market_http
from app.engine.scalp_shortlist_store import publish_once, study_dir

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
SCHEMA = 1
UNIVERSE_PATH = Path(__file__).resolve().parents[1] / "data" / "radar_universe.json"
# Frozen November 3 roster; a later Radar edit must not silently change this cohort.
ROSTER_HASH = "5f4b2364e81dca08e4d9c2a15dd49da2d64a246eb4053bfbaaccbe6e881ce6ed"
DATA_DIR = study_dir()
SESSIONS = tuple(day.isoformat() for day in (
    date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6), date(2026, 11, 9),
    date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 13),
    date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19),
    date(2026, 11, 20), date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25),
    date(2026, 11, 27), date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 2),
))


class StudyError(RuntimeError):
    """The study cannot make a complete, deadline-valid result."""


class FeedUnavailable(StudyError):
    """The requested data feed is explicitly denied by the provider."""


def load_universe(path: Path = UNIVERSE_PATH) -> dict[str, str]:
    """Read 146 stocks and their versioned comparison ETFs."""
    payload = json.loads(path.read_text())
    stocks = {row["symbol"]: row["sector"] for row in payload["symbols"]
              if row.get("kind") == "stock" and isinstance(row.get("sector"), str)}
    if _universe_hash(stocks) != ROSTER_HASH:
        raise StudyError("Radar stock or sector assignments differ from the frozen 146-stock roster.")
    return stocks


def _universe_hash(stocks: dict[str, str]) -> str:
    encoded = json.dumps(stocks, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_minute_bars(payload: dict, day: date) -> dict[str, dict[int, dict]]:
    """Validate response minutes, retaining only regular-session bars through 9:51."""
    output: dict[str, dict[int, dict]] = {}
    for symbol, rows in (payload.get("bars") or {}).items():
        bars: dict[int, dict] = {}
        for row in rows:
            try:
                stamp = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
                at = stamp.astimezone(ET)
                minute = (at.hour * 60 + at.minute) - (9 * 60 + 30)
                values = [row[key] for key in ("o", "h", "l", "c", "v")]
                if (stamp.utcoffset() is None or stamp.second or stamp.microsecond or at.date() != day or not 0 <= minute <= 21
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
                        or row["v"] < 0
                        or min(row["o"], row["h"], row["l"], row["c"]) <= 0
                        or row["h"] < max(row["o"], row["c"]) or row["l"] > min(row["o"], row["c"])
                        or minute in bars):
                    raise ValueError
            except (TypeError, ValueError, KeyError, AttributeError):
                raise StudyError(f"Malformed or duplicate minute bar for {symbol}.") from None
            bars[minute] = dict(zip(("o", "h", "l", "c", "v"), values))
        output[symbol] = bars
    return output


def _opening_volume(bars: dict[int, dict]) -> float:
    return sum(row["v"] for minute, row in bars.items() if 0 <= minute <= 9)


def rank_picks(
    bars: dict[str, dict[int, dict]], prior_opening_volumes: list[dict[str, float]],
    stocks: dict[str, str],
) -> tuple[int, list[dict], list[dict]]:
    """Use the exact frozen comparison: 2x median RVOL plus directional sector lead."""
    if len(prior_opening_volumes) != 20:
        raise StudyError("A complete same-feed 20-session volume baseline is required.")
    moves: dict[str, float] = {}
    volumes = {symbol: _opening_volume(rows) for symbol, rows in bars.items()}
    for symbol, rows in bars.items():
        if 0 in rows and 9 in rows:
            moves[symbol] = rows[9]["c"] / rows[0]["o"] - 1

    eligible = 0
    shortlist = []
    ranking_rows = []
    for symbol, sector in stocks.items():
        if symbol not in moves or sector not in moves:
            continue
        history = [row.get(symbol, 0.0) for row in prior_opening_volumes]
        if min(history, default=0.0) <= 0:
            continue
        eligible += 1
        move = moves[symbol]
        relative_volume = volumes.get(symbol, 0.0) / median(history)
        lead = (move - moves[sector]) * (1 if move > 0 else -1)
        candidate = {"symbol": symbol, "direction": "up" if move > 0 else "down",
                     "relative_volume": relative_volume, "sector_lead_pct": lead * 100}
        ranking_rows.append((abs(move), symbol, candidate))
        if move != 0 and relative_volume >= 2 and lead > 0:
            shortlist.append(candidate)

    movers = [{"symbol": row["symbol"], "direction": row["direction"]}
              for _, _, row in sorted(ranking_rows, key=lambda item: (-item[0], item[1]))[:3]]
    picks = sorted(shortlist, key=lambda row: (-row["sector_lead_pct"], row["symbol"]))[:3]
    return eligible, picks, movers


def _request_bars(day: date, *, feed: str, symbols: list[str], start_minute: int, end_minute: int) -> dict[str, dict[int, dict]]:
    """Request a bounded date/symbol window using the existing Alpaca credentials."""
    if feed not in {"sip", "iex"}:
        raise ValueError("unsupported feed")
    start = datetime.combine(day, wall_time(9, 30), ET) + timedelta(minutes=start_minute)
    end = datetime.combine(day, wall_time(9, 30), ET) + timedelta(minutes=end_minute)
    params: dict[str, Any] = {"symbols": ",".join(symbols), "timeframe": "1Min",
                              "start": start.astimezone(UTC).isoformat(), "end": end.astimezone(UTC).isoformat(),
                              "limit": 10000, "feed": feed, "adjustment": "raw", "asof": "2026-11-03"}
    pages: dict[str, list] = {}
    for _ in range(5):
        try:
            response = market_http.get(
                f"{alpaca.DATA_URL}/v2/stocks/bars", params=params,
                headers=alpaca._headers(), timeout=20,
            )
        except httpx.HTTPError as exc:
            raise alpaca.AlpacaFastFailure(f"Alpaca could not be reached ({type(exc).__name__}).") from None
        if response.status_code == 403:
            message = response.text[:500]
            if feed == "sip" and "subscription" in message.lower() and "sip" in message.lower():
                raise FeedUnavailable("Alpaca account is not entitled to this SIP read.")
            raise StudyError("Alpaca denied the market-data request.")
        if response.status_code == 429:
            raise StudyError("Alpaca market-data request was rate limited.")
        if response.status_code >= 400:
            raise StudyError(f"Alpaca market-data request failed ({response.status_code}).")
        try:
            payload = response.json()
        except ValueError:
            raise StudyError("Alpaca market-data response was not valid JSON.") from None
        for symbol, rows in (payload.get("bars") or {}).items():
            pages.setdefault(symbol, []).extend(rows)
        token = payload.get("next_page_token")
        if not token:
            return _parse_minute_bars({"bars": pages}, day)
        params["page_token"] = token
    raise StudyError("Too many market-data pages for the frozen universe.")


def warmup(day: date, *, root: Path = DATA_DIR, fetch: Callable = _request_bars,
           stocks: dict[str, str] | None = None) -> dict:
    """Pre-open: persist exactly 20 prior opening-volume windows in each feed."""
    if day.isoformat() not in SESSIONS:
        raise StudyError("Date is outside the frozen 20-session cohort.")
    stock_map = stocks or load_universe()
    prior_days = _previous_sessions(day)
    symbols = sorted(set(stock_map) | set(stock_map.values()))
    profiles = {}
    for feed in ("iex", "sip"):
        profile_path = root / "baseline" / feed / f"{day.isoformat()}.json"
        if profile_path.exists():
            saved = json.loads(profile_path.read_text())
            if (saved.get("feed") != feed or saved.get("day") != day.isoformat()
                    or saved.get("universe_hash") != _universe_hash(stock_map)
                    or len(saved.get("opening_volumes", [])) != 20):
                raise StudyError("Opening-volume baseline snapshot has invalid provenance.")
            profiles[feed] = saved
            continue
        values = []
        for prior in prior_days:
            daily_path = root / "baseline" / feed / "sessions" / f"{prior.isoformat()}.json"
            if daily_path.exists():
                daily = json.loads(daily_path.read_text())
                if (daily.get("feed") != feed or daily.get("day") != prior.isoformat()
                        or daily.get("universe_hash") != _universe_hash(stock_map)):
                    raise StudyError("An opening-volume cache has invalid provenance.")
                values.append(daily["opening_volumes"])
                continue
            bars = fetch(prior, feed=feed, symbols=symbols, start_minute=0, end_minute=9)
            opening_volumes = {symbol: _opening_volume(rows) for symbol, rows in bars.items()}
            if not opening_volumes or max(opening_volumes.values(), default=0) <= 0:
                raise StudyError(f"{feed.upper()} opening-volume history was empty.")
            values.append(publish_once(daily_path, {"schema": SCHEMA, "feed": feed, "day": prior.isoformat(),
                                                     "universe_hash": _universe_hash(stock_map),
                                                     "opening_volumes": opening_volumes})["opening_volumes"])
        profiles[feed] = publish_once(profile_path, {"schema": SCHEMA, "feed": feed,
                                                       "day": day.isoformat(), "universe_hash": _universe_hash(stock_map),
                                                       "sessions": [d.isoformat() for d in prior_days],
                                                       "opening_volumes": values})
    return {"day": day.isoformat(), "baseline_feeds": list(profiles), "sessions": [d.isoformat() for d in prior_days]}


def _previous_sessions(day: date) -> list[date]:
    """Known NYSE holidays within the 2026 lookback; weekday filter handles weekends."""
    holidays = {date(2026, 11, 26)}
    found = []
    cursor = day - timedelta(days=1)
    while len(found) < 20:
        if cursor.weekday() < 5 and cursor not in holidays:
            found.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(found))


def capture_live(day: date, *, root: Path = DATA_DIR, now: Callable = lambda: datetime.now(ET),
                 fetch: Callable = _request_bars, stocks: dict[str, str] | None = None) -> dict:
    """Capture an immutable 9:40 slate. Incomplete feeds fail closed."""
    if day.isoformat() not in SESSIONS:
        raise StudyError("Date is outside the frozen 20-session cohort.")
    clock = now().astimezone(ET)
    if clock.date() != day or clock < datetime.combine(day, wall_time(9, 40), ET):
        raise StudyError("The 9:40 selection window has not opened.")
    path = root / day.isoformat() / "live.json"
    if path.exists():
        return json.loads(path.read_text())
    if clock >= datetime.combine(day, wall_time(9, 41), ET):
        raise StudyError("The selection window closed. No backfill is allowed.")
    stock_map = stocks or load_universe()
    symbols = sorted(set(stock_map) | set(stock_map.values()))
    feed = "sip"
    try:
        bars = fetch(day, feed=feed, symbols=symbols, start_minute=0, end_minute=9)
    except FeedUnavailable:
        feed = "iex"
        bars = fetch(day, feed=feed, symbols=symbols, start_minute=0, end_minute=9)
    baseline_file = root / "baseline" / feed / f"{day.isoformat()}.json"
    if not baseline_file.exists():
        raise StudyError("Opening-volume baseline is unavailable.")
    baseline = json.loads(baseline_file.read_text())
    if baseline.get("feed") != feed or baseline.get("universe_hash") != _universe_hash(stock_map):
        raise StudyError("The opening-volume baseline has invalid provenance.")
    eligible, picks, movers = rank_picks(bars, baseline["opening_volumes"], stock_map)
    if eligible == 0:
        raise StudyError("No eligible stocks in the live data response.")
    saved_at = now().astimezone(ET)
    if saved_at >= datetime.combine(day, wall_time(9, 41), ET):
        raise StudyError("Market data returned after the 9:41 selection cutoff.")
    record = {"schema": SCHEMA, "day": day.isoformat(), "captured_at": saved_at.isoformat(),
              "feed": feed, "eligible": eligible, "picks": picks, "movers": movers}
    return publish_once(path, record)


def make_recap(day: date, *, root: Path = DATA_DIR, fetch: Callable = _request_bars,
               now: Callable = lambda: datetime.now(ET), stocks: dict[str, str] | None = None) -> dict:
    """Score saved live picks, comparison Movers and official SIP picks at 10:15."""
    if day.isoformat() not in SESSIONS:
        raise StudyError("Date is outside the frozen 20-session cohort.")
    live_path = root / day.isoformat() / "live.json"
    recap_path = root / day.isoformat() / "recap.json"
    if recap_path.exists():
        return json.loads(recap_path.read_text())
    clock = now().astimezone(ET)
    if clock < datetime.combine(day, wall_time(10, 15), ET):
        raise StudyError("The recap window has not opened.")
    live = json.loads(live_path.read_text()) if live_path.exists() else {
        "feed": None, "eligible": 0, "picks": [], "movers": []}
    stock_map = stocks or load_universe()
    bars = fetch(day, feed="sip", symbols=sorted(set(stock_map) | set(stock_map.values())),
                 start_minute=0, end_minute=21)
    baseline_path = root / "baseline" / "sip" / f"{day.isoformat()}.json"
    if not baseline_path.exists():
        raise StudyError("Official SIP result is unavailable because its same-feed baseline is missing.")
    official_baseline = json.loads(baseline_path.read_text())
    if official_baseline.get("universe_hash") != _universe_hash(stock_map):
        raise StudyError("Official SIP baseline has a different frozen universe.")
    eligible, official, movers = rank_picks(bars, official_baseline["opening_volumes"], stock_map)
    if eligible == 0:
        raise StudyError("Official SIP result unavailable or missing the minimum coverage.")
    official_side = [{"symbol": p["symbol"], "direction": p["direction"]} for p in official]
    shown_side = [{"symbol": p["symbol"], "direction": p["direction"]} for p in live["picks"]]

    def scores(items: Iterable[dict]) -> list[dict]:
        out = []
        for item in items:
            rows = bars.get(item["symbol"], {})
            entry = rows.get(11, {}).get("o")
            exit_price = rows.get(21, {}).get("o")
            result = None
            if entry and exit_price and entry > 0:
                sign = 1 if item["direction"] == "up" else -1
                result = round(sign * (exit_price / entry - 1) * 100, 6)
            out.append({"symbol": item["symbol"], "direction": item["direction"], "return_pct": result})
        return out

    record = {"schema": SCHEMA, "day": day.isoformat(), "captured_at": clock.isoformat(),
              "feed": "sip", "shown_feed": live["feed"], "eligible": eligible,
              "official": scores(official_side), "shown": scores(shown_side), "movers": scores(movers)}
    return publish_once(recap_path, record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("warmup", "live", "recap"))
    parser.add_argument("--day", type=date.fromisoformat, default=datetime.now(ET).date())
    parser.add_argument("--root", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    handlers = {"warmup": lambda: warmup(args.day, root=args.root),
                "live": lambda: capture_live(args.day, root=args.root),
                "recap": lambda: make_recap(args.day, root=args.root)}
    print(json.dumps(handlers[args.action](), sort_keys=True))


if __name__ == "__main__":
    main()
