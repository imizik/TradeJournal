"""Market data for the four-family strategy search (research/strategy-search): Alpaca SIP bars for a fixed ETF list.

- ``minutes/{SYMBOL}.json.gz``: one-minute bars, split-adjusted, regular session 09:30-15:59 New York, 2016-2026
  (day -> [[minute, o, h, l, c, v], ...]).
- ``daily.json.gz``: daily bars, adjusted for splits and dividends, 2015-2026 (symbol -> [[day, o, h, l, c, v], ...]).

Market data only; the files stay outside the repository.

Run from backend:
    ALPACA_DATA_FEED=sip python -m scripts.strategy_search_data DATA --env-file .env
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from pathlib import Path
import sys

from scripts import opening_breakout_study as v1
from scripts import opening_breakout_top5_study as t5

INTRADAY = ("SPY", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "SMH")
DAILY = ("QQQ", *INTRADAY)
MINUTE_START, DAILY_START, END = date(2016, 1, 1), date(2015, 1, 1), date(2026, 11, 13)
OPEN_MINUTE, LAST_MINUTE = 570, 959


def fetch(root: Path, env_file: Path, per_minute: int = 150) -> None:
    import httpx
    from scripts.radar_long_history import alpaca_bars, keys_from
    _, headers = keys_from(env_file)
    (root / "minutes").mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=90, event_hooks={"request": [t5.Throttle(per_minute)]}) as client:
        daily_path = root / "daily.json.gz"
        if not daily_path.exists():
            rows = alpaca_bars(client, headers, list(DAILY), "1Day", f"{DAILY_START.isoformat()}T00:00:00Z",
                               f"{END.isoformat()}T23:59:59Z", "all")
            out = {s: [[b["t"][:10], b["o"], b["h"], b["l"], b["c"], b["v"]] for b in rows.get(s, [])] for s in DAILY}
            v1.save(daily_path, out)
            print("daily: " + ", ".join(f"{s} {len(out[s])}" for s in DAILY), flush=True)
        for symbol in INTRADAY:
            path = root / "minutes" / f"{symbol}.json.gz"
            if path.exists():
                continue
            by_day: dict[str, list] = defaultdict(list)
            for year in range(MINUTE_START.year, END.year + 1):
                last = min(date(year, 12, 31), END)
                rows = alpaca_bars(client, headers, [symbol], "1Min", f"{year}-01-01T00:00:00Z",
                                   f"{last.isoformat()}T23:59:59Z", "split").get(symbol, [])
                for b in rows:
                    day, minute = v1.minute_of(b["t"])
                    if OPEN_MINUTE <= minute <= LAST_MINUTE:
                        by_day[day].append([minute, b["o"], b["h"], b["l"], b["c"], b["v"]])
                print(f"{symbol} {year}: {len(rows)} bars", flush=True)
            v1.save(path, dict(by_day))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data", type=Path)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--per-minute", type=int, default=150)
    args = parser.parse_args(argv)
    fetch(args.data, args.env_file, args.per_minute)


if __name__ == "__main__":
    sys.exit(main())
