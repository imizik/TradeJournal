"""Supplement the #665 price snapshot with raw SIP regular-session minute volume."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values

from scripts.radar_historical_replay import DATA, bounds, dates, get_bars, load_universe, write_snapshot


def volume_days():
    sessions = dates()[1:]
    closed = set(json.loads((DATA / "macro_calendar.json").read_text())["market_closed"])
    day = sessions[0]
    for _ in range(20):
        day -= timedelta(days=1)
        while day.weekday() >= 5 or day.isoformat() in closed:
            day -= timedelta(days=1)
        sessions.insert(0, day)
    return sessions


def fetch(root, cache, env_file):
    keys = {**dotenv_values(env_file), **os.environ}
    if keys.get("ALPACA_DATA_FEED") != "sip":
        raise ValueError("SIP feed required")
    headers = {"APCA-API-KEY-ID": keys["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": keys["ALPACA_API_SECRET"]}
    stocks = [r["symbol"] for r in load_universe()["symbols"] if r["kind"] == "stock" and not r["benchmark"]]
    root.mkdir(parents=True, exist_ok=True)

    def day_file(day):
        path = root / f"{day}.json.gz"
        if path.exists():
            return
        start, end = bounds(day)
        missing, rows = [], {}
        for s in stocks:
            source = cache / "stocks/1Min/sip" / s / f"{day}.json" if cache else None
            if source and source.is_file():
                rows[s] = json.loads(source.read_text())
            else:
                missing.append(s)
        if missing:
            rows.update(get_bars(client, missing, "1Min", start.isoformat(),
                                 (end - timedelta(minutes=1)).isoformat(), "raw"))
        data = {}
        for s in stocks:
            volumes = {}
            for b in rows.get(s, []):
                at = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
                if start <= at < end:
                    offset = (at - start).total_seconds() / 60
                    if not offset.is_integer() or int(offset) in volumes or not math.isfinite(b["v"]) or b["v"] < 0:
                        raise ValueError(f"invalid minute volume for {s} on {day}")
                    volumes[int(offset)] = b["v"]
            data[s] = volumes
        write_snapshot(path, data)
        print(f"{day} saved", flush=True)

    with httpx.Client(headers=headers, timeout=60) as client, ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(day_file, volume_days()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    fetch(args.root, args.cache_root, args.env_file)
