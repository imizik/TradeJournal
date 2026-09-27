"""
Backtest the VWAP reclaim/rejection strategy, version 0.1, over Alpaca bars.

The rules are `app/engine/vwap_reclaim.py`: the first build of the Pine
research framework (one-minute regular-session bars, arm on a VWAP reclaim or
rejection, confirm within three bars, 1.5R target, 20-minute hold, two entries
a session). Bars come from the cached Alpaca clients through the Market Map
backtester's loader. The report is in R, with the framework's acceptance
measures (independent days, expectancy, drawdown, the result without the best
trade and the best day, by side, ticker and month), and a TradingView-shaped
CSV per ticker imports into Strategy Lab (source timezone America/New_York).

Usage:
    python scripts/backtest_vwap_reclaim.py MU META --start 2025-10-14 --end 2026-09-24 --feed sip
    python scripts/backtest_vwap_reclaim.py MU --start 2025-10-14 --end 2026-09-24 --feed sip --set slippage_bps=3
    python scripts/backtest_vwap_reclaim.py MU --start 2025-10-14 --end 2026-09-24 --feed sip --timeframe 3
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPTS.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(SCRIPTS))

from backtest_market_map import AlpacaLoader, BarLoader, RunOptions, _coerce, load_bars  # noqa: E402

from app.engine.market_map import ET  # noqa: E402
from app.engine.market_map_report import tradingview_csv  # noqa: E402
from app.engine.vwap_reclaim import (  # noqa: E402
    ReclaimConfig,
    ReclaimResult,
    entry_comment,
    exit_comment,
    report,
    run_vwap_reclaim,
)

DEFAULT_OUT = BACKEND_ROOT / "data" / "vwap_reclaim"


def build_config(overrides: list[str], timeframe: int) -> ReclaimConfig:
    fields = {field.name: field for field in dataclasses.fields(ReclaimConfig)}
    changes: dict[str, object] = {"timeframe_minutes": timeframe}
    for item in overrides:
        name, _, value = item.partition("=")
        if name not in fields or not _:
            raise SystemExit(f"--set expects name=value with a ReclaimConfig field; got {item!r}")
        changes[name] = _coerce(fields[name], value)
    return dataclasses.replace(ReclaimConfig(), **changes)


def run_backtest(
    loader: BarLoader,
    tickers: list[str],
    config: ReclaimConfig,
    start: date,
    end: date,
    warmup_days: int,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, ReclaimResult]:
    options = RunOptions(start, end, warmup_days, extended_hours=False, atr_source="daily")
    chart, _daily = load_bars(loader, tickers, options, config.timeframe_minutes, progress)
    results = {}
    for ticker in tickers:
        result = run_vwap_reclaim(ticker, chart[ticker], config)
        # Warm-up sessions seed EMA 9 and ATR(14); their trades are not reported.
        result.trades = [t for t in result.trades if t.entry_time.astimezone(ET).date() >= start]
        result.events = [e for e in result.events if e.time.astimezone(ET).date() >= start]
        results[ticker] = result
    return results


def event_summary(results: dict[str, ReclaimResult]) -> str:
    counts = Counter()
    for result in results.values():
        for event in result.events:
            counts[f"{event.kind}: {event.detail}" if event.detail else event.kind] += 1
    return "\n".join(f"  {count:6d}  {label}" for label, count in sorted(counts.items(), key=lambda item: -item[1]))


def main(argv: list[str] | None = None, loader_factory: Callable[[], BarLoader] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--days", type=int, default=365, help="calendar days back from --end (default 365)")
    parser.add_argument("--start", type=date.fromisoformat, help="first reported day; overrides --days")
    parser.add_argument("--end", type=date.fromisoformat, help="last day (default: yesterday)")
    parser.add_argument("--timeframe", type=int, default=1, help="chart minutes, a divisor of 30 (default 1)")
    parser.add_argument("--warmup-days", type=int, default=5, help="calendar days of bars before --start")
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="FIELD=VALUE",
                        help="override a ReclaimConfig field, e.g. target_r=2 or slippage_bps=3")
    parser.add_argument("--feed", choices=("iex", "sip"), help="sets ALPACA_DATA_FEED for this run")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.feed:
        os.environ["ALPACA_DATA_FEED"] = args.feed
    tickers = [t.upper() for t in args.tickers]
    end = args.end or (datetime.now(ET).date() - timedelta(days=1))
    start = args.start or (end - timedelta(days=args.days))
    config = build_config(args.overrides, args.timeframe)

    loader = (loader_factory or AlpacaLoader)()
    feed = getattr(loader, "feed", os.environ.get("ALPACA_DATA_FEED", "iex"))
    if feed == "iex":
        print("WARNING: IEX feed. IEX prints a small share of volume, so VWAP will differ from the "
              "consolidated tape. Use --feed sip if your key allows it.", file=sys.stderr)
    print(f"VWAP reclaim {config.version}, {args.timeframe}m, {start} to {end}, feed {feed}, "
          f"{len(tickers)} tickers", file=sys.stderr)
    results = run_backtest(loader, tickers, config, start, end, args.warmup_days,
                           lambda line: print(line, file=sys.stderr))

    changed = {f.name: getattr(config, f.name) for f in dataclasses.fields(ReclaimConfig)
               if getattr(config, f.name) != f.default}
    header = (f"VWAP reclaim {config.version}, {args.timeframe}m, {start} to {end}, feed {feed}, "
              f"settings {changed or 'default'}. R = price move from the fill over the fill-to-stop risk.")
    trades = [trade for result in results.values() for trade in result.closed_trades]
    text = header + "\n" + report(trades) + "\n\n== setup events\n" + event_summary(results)
    print(text)

    run_dir = args.out / f"{datetime.now(ET):%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.txt").write_text(text + "\n")
    for ticker, result in results.items():
        name = f"VWR_py_v{config.version}_{ticker}_{end.isoformat()}.csv"
        csv_text = tradingview_csv(result.trades, config, entry_comment, exit_comment)
        (run_dir / name).write_text("﻿" + csv_text)
    print(f"\nWrote {run_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
