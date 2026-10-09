"""Root-only finite historical provider capture; no app/database imports."""
import argparse
import json
import os
import stat
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dot_market_capture import CONFIG, fetch, read_provider_values

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def capture(credentials, day, clock, *, reader=fetch, now=None):
    actual = now or datetime.now(UTC)
    yesterday = actual.astimezone(ET).date() - timedelta(days=1)
    if day > yesterday or day.year < 2020 or clock.tzinfo is not None or clock.minute % 15 or clock.second or clock.microsecond:
        raise ValueError("Use a completed historical date and aligned cutoff")
    if not credentials.get("ALPACA_API_KEY") or not credentials.get("ALPACA_API_SECRET"):
        raise ValueError("Configured provider access is required")
    feed = credentials.get("ALPACA_DATA_FEED", "iex")
    if feed not in {"iex", "sip"}:
        raise ValueError("Unsupported configured feed")
    calendar = None
    for origin in ("https://paper-api.alpaca.markets", "https://api.alpaca.markets"):
        try:
            rows = reader(origin+"/v2/calendar", {"start": day.isoformat(),
                "end": min(day+timedelta(days=7), yesterday).isoformat()}, credentials)
            if not isinstance(rows, list) or not 2 <= len(rows) <= 6:
                raise ValueError("Two past sessions are required")
            def minute(value):
                h, m = (int(part) for part in value.split(":"))
                if not 0 <= h < 24 or not 0 <= m < 60:
                    raise ValueError("Invalid calendar time")
                return h*60+m
            dates = [date.fromisoformat(row["date"]) for row in rows]
            if dates != sorted(set(dates)) or dates[0] != day or any(d > yesterday for d in dates):
                raise ValueError("Historical calendar does not match request")
            calendar = [{"day": row["date"], "open": minute(row["open"]), "close": minute(row["close"]),
                "source": "alpaca_calendar"} for row in rows[:2]]
            if any(not 0 <= row["open"] < row["close"] < 1440 for row in calendar):
                raise ValueError("Invalid regular session")
            break
        except (OSError, ValueError, KeyError, TypeError):
            calendar = None
    if calendar is None:
        raise ValueError("Historical calendar unavailable")
    cutoff = datetime.combine(day, clock, ET)
    if not calendar[0]["open"]+60 <= clock.hour*60+clock.minute < calendar[0]["close"]:
        raise ValueError("Cutoff must leave a completed hour in the regular session")
    packets = {}
    for symbol in ("MU", "NBIS"):
        bars = []
        for i, session in enumerate(calendar):
            midnight = datetime.combine(date.fromisoformat(session["day"]), datetime.min.time(), ET)
            opening = midnight+timedelta(minutes=session["open"])
            closing = midnight+timedelta(minutes=session["close"])
            start = max(opening, cutoff-timedelta(hours=1)) if i == 0 else opening
            response = reader("https://data.alpaca.markets/v2/stocks/bars", {"symbols": symbol, "timeframe": "1Min",
                "start": start.astimezone(UTC).isoformat(), "end": closing.astimezone(UTC).isoformat(),
                "limit": 1000, "adjustment": "raw", "currency": "USD", "feed": feed, "sort": "desc"}, credentials)
            if not isinstance(response, dict) or response.get("next_page_token"):
                raise ValueError("Historical response incomplete")
            selected = response["bars"][symbol]
            if not isinstance(selected, list) or len(selected) > 1000:
                raise ValueError("Historical response too large")
            for bar in selected:
                at = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                if at.tzinfo is None:
                    raise ValueError("Historical minute timezone unavailable")
                if start <= at and at+timedelta(minutes=1) <= closing:
                    bars.append({k: bar[k] for k in ("t", "o", "h", "l", "c", "v")} | {"vw": bar.get("vw")})
        bars.sort(key=lambda b: datetime.fromisoformat(b["t"].replace("Z", "+00:00")), reverse=True)
        if not bars or len(bars) > 840:
            raise ValueError("Actual bounded provider history is required")
        packets[symbol] = {"symbol": symbol, "data_source": "alpaca_"+feed, "recent_minute_bars": bars, "missing": []}
    return {"version": 1, "captured_at": (actual if now else datetime.now(UTC)).isoformat(),
        "simulated_as_of": cutoff.astimezone(UTC).isoformat(), "sessions": calendar, "packets": packets}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True)
    parser.add_argument("--cutoff", default="13:45")
    args = parser.parse_args()
    if os.geteuid() != 0 or CONFIG.is_symlink() or not CONFIG.is_dir():
        raise ValueError("Run only as root on the approved trial")
    day = date.fromisoformat(args.day)
    clock = time.fromisoformat(args.cutoff)
    if clock.strftime("%H:%M") != args.cutoff:
        raise ValueError("Cutoff is an Eastern HH:MM time")
    target = CONFIG / ("historical-handoff-"+day.isoformat()+"T"+clock.strftime("%H%M")+".json")
    if target.exists():
        if target.is_symlink() or not target.is_file() or target.stat().st_uid != 0 or stat.S_IMODE(target.stat().st_mode) != 0o600:
            raise ValueError("Invalid retained historical handoff")
        print("Historical handoff retained; no provider call or cutoff change.")
        return
    credentials = read_provider_values()
    os.environ.clear()
    os.environ["PATH"] = os.defpath
    bundle = capture(credentials, day, clock)
    data = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > 1_048_576:
        raise ValueError("Historical handoff too large")
    with tempfile.NamedTemporaryFile(dir=CONFIG, delete=False) as staged:
        staging = Path(staged.name)
        staged.write(data)
        staged.flush()
        os.fsync(staged.fileno())
    try:
        staging.chmod(0o600)
        os.link(staging, target)
    finally:
        staging.unlink()
    print("Actual historical MU/NBIS bars saved privately. No credentials imported or printed.")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 -- never reflect credentials in root-command errors
        raise SystemExit("Historical capture failed; no credential details printed") from None
