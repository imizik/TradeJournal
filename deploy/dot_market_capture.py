"""Root-only bounded provider read. No app/database import or integration startup."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
from zoneinfo import ZoneInfo

CONFIG = Path("/etc/tradejournal-dot-trial")
PROVIDER_ENV = Path("/etc/tradejournal/backend.env")
ET = ZoneInfo("America/New_York")
UTC = timezone.utc
MAX_BYTES = 1_048_576


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_provider_values(path=PROVIDER_ENV):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Provider configuration is unavailable")
    values = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_DATA_FEED"}:
            values[key] = value.strip().strip('"').strip("'")
    return values


def fetch(url, params, credentials):
    headers = {"APCA-API-KEY-ID": credentials["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": credentials["ALPACA_API_SECRET"], "Accept": "application/json"}
    request = Request(url + "?" + urlencode(params), headers=headers, method="GET")
    # Keys never follow a redirect or environment-supplied proxy.
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=10) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Provider response is too large")
    return json.loads(data)


def capture(credentials, *, reader=fetch, now=None):
    fixed_clock = now is not None
    now = now or datetime.now(UTC)
    day = now.astimezone(ET).date()
    hours = {"status": "unavailable", "open": None, "close": None, "source": "alpaca_calendar"}
    if credentials.get("ALPACA_API_KEY") and credentials.get("ALPACA_API_SECRET"):
        for origin in ("https://paper-api.alpaca.markets", "https://api.alpaca.markets"):
            try:
                rows = reader(origin + "/v2/calendar", {"start": day.isoformat(), "end": day.isoformat()}, credentials)
                if not isinstance(rows, list) or len(rows) > 1:
                    raise ValueError("Invalid calendar")
                if not rows:
                    hours["status"] = "closed"
                else:
                    row = rows[0]
                    if row["date"] != day.isoformat():
                        raise ValueError("Wrong calendar date")
                    def minute(value):
                        h, m = (int(part) for part in value.split(":"))
                        if not 0 <= h < 24 or not 0 <= m < 60:
                            raise ValueError("Invalid calendar hours")
                        return h * 60 + m
                    hours.update(status="open", open=minute(row["open"]), close=minute(row["close"]))
                    if hours["open"] >= hours["close"]:
                        raise ValueError("Invalid calendar hours")
                break
            except (OSError, ValueError, KeyError, TypeError):
                hours = {"status": "unavailable", "open": None, "close": None, "source": "alpaca_calendar"}
    packets = {s: {"symbol": s, "data_source": "unavailable", "recent_minute_bars": [],
        "missing": ["Provider/calendar evidence unavailable"]} for s in ("MU", "NBIS")}
    feed = credentials.get("ALPACA_DATA_FEED", "iex")
    if hours["status"] == "open" and feed in {"iex", "sip"}:
        opening = datetime.combine(day, datetime.min.time(), ET) + timedelta(minutes=hours["open"])
        closing = datetime.combine(day, datetime.min.time(), ET) + timedelta(minutes=hours["close"])
        end = min(now.replace(second=0, microsecond=0), closing)
        if end > opening:
            for symbol in packets:
                try:
                    response = reader("https://data.alpaca.markets/v2/stocks/bars", {
                        "symbols": symbol, "timeframe": "1Min", "start": opening.astimezone(UTC).isoformat(),
                        "end": end.astimezone(UTC).isoformat(), "limit": 1000, "adjustment": "raw", "currency": "USD", "feed": feed, "sort": "desc"}, credentials)
                    if not isinstance(response, dict) or response.get("next_page_token"):
                        raise ValueError("Incomplete provider response")
                    source = response["bars"][symbol]
                    if not isinstance(source, list) or len(source) > 1000:
                        raise ValueError("Invalid provider bars")
                    bars = []
                    for bar in source:
                        at = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                        if at.tzinfo is None:
                            raise ValueError("Missing minute timezone")
                        if opening <= at and at + timedelta(minutes=1) <= end:
                            bars.append({k: bar[k] for k in ("t", "o", "h", "l", "c", "v")} | {"vw": bar.get("vw")})
                    bars.sort(key=lambda b: datetime.fromisoformat(b["t"].replace("Z", "+00:00")), reverse=True)
                    packets[symbol] = {"symbol": symbol, "data_source": "alpaca_" + feed,
                        "recent_minute_bars": bars[:60], "missing": [] if bars else ["No completed regular-session provider minutes"]}
                except (OSError, ValueError, KeyError, TypeError):
                    # No provider exception text/account details enter the handoff.
                    packets[symbol]["missing"] = ["Provider minute retrieval failed; no substitute data"]
    # Capture time is sampled AFTER the bounded reads. Request end stays fixed
    # before them, so no later continuation or unfinished minute can be imported.
    captured = now if fixed_clock else datetime.now(UTC)
    return {"version": 1, "captured_at": captured.isoformat(), "day": day.isoformat(), "calendar": hours, "packets": packets}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.geteuid() != 0 or CONFIG.is_symlink() or not CONFIG.is_dir():
        raise ValueError("Run only as root on the approved VPS trial")
    destination = CONFIG / ("market-handoff-" + datetime.now(ET).date().isoformat() + ".json")
    if destination.exists():
        if destination.is_symlink() or destination.stat().st_uid != 0 or stat.S_IMODE(destination.stat().st_mode) != 0o600:
            raise ValueError("Invalid retained handoff permissions")
        print("Today's frozen handoff already exists; cutoff and data retained. No provider call.")
        return
    values = read_provider_values()
    os.environ.clear()
    os.environ["PATH"] = os.defpath
    bundle = capture(values)
    data = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with tempfile.NamedTemporaryFile(dir=CONFIG, delete=False) as target:
        staging = Path(target.name)
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    try:
        staging.chmod(0o600)
        os.link(staging, destination)  # atomic publication; never replace an existing cutoff
    finally:
        staging.unlink()
    print("Frozen MU/NBIS market handoff saved privately. Provider keys never imported or printed.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Market capture failed; no credential details printed") from None
