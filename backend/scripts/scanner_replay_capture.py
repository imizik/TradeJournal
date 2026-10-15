"""Capture finite historical Alpaca SIP/raw S1 market bundles, without app or DB imports.

Example: python3 scripts/scanner_replay_capture.py --dates 2026-08-25,2026-08-26 --output-dir /private/tmp/scanner-replay
No option data, model calls or writes to TradeJournal services are made.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import httpx

ET = ZoneInfo("America/New_York")
UNIVERSE = ("AAPL", "AMZN", "GOOGL", "META", "SPY", "QQQ", "NBIS", "MU", "CRDO", "MRVL", "LLY", "AMD")
HOLDOUT_START = date(2026, 9, 14)
STOCKS = "https://data.alpaca.markets/v2/stocks/bars"
CALENDAR = "https://api.alpaca.markets/v2/calendar"
MAX_DATES = 10
MAX_DATE_SPAN_DAYS = 366
DAILY_LOOKBACK_DAYS = 90
MIN_PRIOR_SESSIONS = 15
MAX_PAGES = 32
MAX_PAGE_BYTES = 2 * 1024 * 1024


class InsufficientDailyHistory(ValueError):
    """Safe diagnostic: fixed-universe symbols and counts only."""


def _read(client: httpx.Client, url: str, params: dict) -> dict | list:
    try:
        with client.stream("GET", url, params=params) as response:
            if response.status_code != 200:
                raise ValueError(f"Alpaca HTTP {response.status_code}; no feed fallback")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                if len(data) + len(chunk) > MAX_PAGE_BYTES:
                    raise ValueError("Provider response exceeded page byte bound")
                data.extend(chunk)
        return json.loads(data)
    except httpx.HTTPError as exc:
        raise ValueError(f"Alpaca request unavailable: {type(exc).__name__}") from None


def _bars(client: httpx.Client, start: datetime, end: datetime, timeframe: str) -> dict[str, list]:
    params = {"symbols": ",".join(UNIVERSE), "timeframe": timeframe, "feed": "sip", "adjustment": "raw",
              "start": start.isoformat(), "end": end.isoformat(), "sort": "asc", "limit": 10000}
    result = {symbol: [] for symbol in UNIVERSE}
    tokens = set()
    for _ in range(MAX_PAGES):
        page = _read(client, STOCKS, params)
        if not isinstance(page, dict) or not isinstance(page.get("bars"), dict):
            raise ValueError("Malformed Alpaca stock bars")
        if set(page["bars"]) - set(UNIVERSE):
            raise ValueError("Unexpected symbol from Alpaca")
        for symbol, rows in page["bars"].items():
            if not isinstance(rows, list):
                raise ValueError("Malformed symbol bars")
            result[symbol].extend(rows)
        token = page.get("next_page_token")
        if token is None:
            return result
        if not isinstance(token, str) or not token or len(token) > 2048 or token in tokens:
            raise ValueError("Malformed Alpaca pagination")
        tokens.add(token)
        params["page_token"] = token
    raise ValueError("Alpaca response exceeded bounded page count")


def _utc_epoch(value: str) -> int:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("Provider bar has no timezone")
    return int(moment.timestamp())


def _calendar(client: httpx.Client, days: list[date]) -> dict[date, tuple[int, int]]:
    if not days or len(days) > MAX_DATES or (max(days) - min(days)).days > MAX_DATE_SPAN_DAYS:
        raise ValueError("Requested calendar exceeds bounded date span")
    data = _read(client, CALENDAR, {"start": min(days).isoformat(), "end": max(days).isoformat()})
    if not isinstance(data, list):
        raise ValueError("Malformed Alpaca calendar")
    sessions = {}
    for row in data:
        day = date.fromisoformat(row["date"])
        if day not in days:
            continue
        opening = datetime.combine(day, time.fromisoformat(row["open"]), ET)
        closing = datetime.combine(day, time.fromisoformat(row["close"]), ET)
        if opening.time() != time(9, 30) or not opening < closing <= opening + timedelta(hours=6, minutes=30):
            raise ValueError("Provider calendar is outside regular-session bounds")
        sessions[day] = (int(opening.timestamp()), int(closing.timestamp()))
    if set(sessions) != set(days):
        raise ValueError("A requested day has no regular Alpaca session")
    return sessions


def capture(client: httpx.Client, days: list[date]) -> list[dict]:
    """Read one calendar and at most two bounded bar series per session."""
    sessions = _calendar(client, days)
    bundles = []
    for day in days:
        open_at, close_at = sessions[day]
        minute_raw = _bars(client, datetime.fromtimestamp(open_at, UTC), datetime.fromtimestamp(close_at, UTC), "1Min")
        daily_raw = _bars(client, datetime.combine(day - timedelta(days=DAILY_LOOKBACK_DAYS), time(), ET),
                          datetime.combine(day, time(), ET), "1Day")
        symbols = {}
        shortages = []
        for symbol in UNIVERSE:
            minutes = []
            for bar in minute_raw[symbol]:
                at = _utc_epoch(bar["t"])
                if open_at <= at < close_at:
                    minutes.append({"time": at, "end_time": at + 60, "open": bar["o"], "high": bar["h"],
                                    "low": bar["l"], "close": bar["c"], "volume": bar["v"]})
            daily = []
            for bar in daily_raw[symbol]:
                # The provider's 1Day timestamp names the stock session date.
                # Do not turn it into a prior NY date through timezone conversion.
                session_day = date.fromisoformat(bar["t"][:10])
                if session_day < day:
                    daily.append({"time": int(datetime.combine(session_day, time(12), ET).timestamp()),
                                  "date": session_day.isoformat(), "high": bar["h"], "low": bar["l"],
                                  "close": bar["c"], "volume": bar["v"]})
            prior_dates = {row["date"] for row in daily}
            if len(prior_dates) != len(daily):
                raise ValueError("Provider returned a duplicate prior daily session")
            if len(prior_dates) < MIN_PRIOR_SESSIONS:
                shortages.append(f"{symbol}({len(prior_dates)})")
            symbols[symbol] = {"minutes": sorted(minutes, key=lambda b: b["time"]),
                               "daily": sorted(daily, key=lambda b: b["time"])}
        if shortages:
            raise InsufficientDailyHistory("fewer than 15 prior daily sessions: " + ", ".join(shortages))
        bundles.append({"session_date": day.isoformat(), "retrieved_at": datetime.now(UTC).isoformat(),
                        "open_at": open_at, "close_at": close_at, "symbols": symbols,
                        "feed": "sip", "adjustment": "raw", "provider": "alpaca"})
    return bundles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", required=True, help="Comma-separated session dates, up to ten")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-holdout", action="store_true", help="Explicitly permit sessions on/after 2026-09-14")
    args = parser.parse_args()
    try:
        dates = [date.fromisoformat(value.strip()) for value in args.dates.split(",")]
        if not dates or len(dates) > MAX_DATES or len(set(dates)) != len(dates):
            raise ValueError("Require 1-10 unique dates")
        if (max(dates) - min(dates)).days > MAX_DATE_SPAN_DAYS:
            raise ValueError("Requested dates span more than one year")
        if any(day >= HOLDOUT_START for day in dates) and not args.allow_holdout:
            raise ValueError("Holdout date requires --allow-holdout")
        if any(day >= datetime.now(ET).date() for day in dates):
            raise ValueError("Capture only completed past sessions")
        if os.environ.get("ALPACA_DATA_FEED", "sip").strip().lower() != "sip":
            raise ValueError("Configured Alpaca stock feed must be SIP")
        key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_API_SECRET")
        if not key or not secret:
            raise ValueError("Existing Alpaca SIP credentials are required")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if any((args.output_dir / f"bundle-{day}.json").exists() for day in dates):
            raise ValueError("A capture file already exists; immutable capture will not be replaced")
        with httpx.Client(timeout=20, trust_env=False, follow_redirects=False,
                          headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}) as client:
            bundles = capture(client, dates)
        for bundle in bundles:
            path = args.output_dir / f"bundle-{bundle['session_date']}.json"
            data = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=args.output_dir, prefix=".bundle-", delete=False) as output:
                    temporary = Path(output.name)
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.link(temporary, path)  # atomic publication; an existing capture is never replaced
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            print(json.dumps({"saved": str(path), "bytes": len(data), "symbols": len(bundle["symbols"])}))
    except InsufficientDailyHistory as exc:
        parser.exit(2, f"Scanner replay capture refused: {exc}\n")
    except (ValueError, OSError, KeyError, TypeError):
        parser.exit(2, "Scanner replay capture refused: invalid request or unavailable provider data.\n")


if __name__ == "__main__":
    main()
