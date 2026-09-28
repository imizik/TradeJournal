"""
Backtest the NBIS recovery swing, version 0.1, over Alpaca bars.

The rules are `app/engine/nbis_swing.py`, a follow-on module of the Pine
research framework: 15-minute candles, long only, armed by trading below the
prior day's EMA 20, triggered by a 15-minute EMA 20 reclaim that clears the
prior three highs, 2R target, at most two sessions. The report is in R with
the framework's acceptance measures, and repeats them for the intraday-only
exit on the same entries, which is the comparison the framework asks for.
A TradingView-shaped CSV per ticker imports into Strategy Lab.

Usage:
    python scripts/backtest_nbis_swing.py NBIS --start 2025-10-14 --end 2026-09-24 --feed sip
    python scripts/backtest_nbis_swing.py NBIS MU META --start 2024-10-14 --end 2025-10-13 --feed sip
    python scripts/backtest_nbis_swing.py NBIS --feed sip --set reclaim_level=daily_ema
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
from app.engine.nbis_swing import (  # noqa: E402
    SwingConfig,
    SwingResult,
    entry_comment,
    exit_comment,
    intraday_only,
    run_nbis_swing,
)
from app.engine.vwap_reclaim import report  # noqa: E402

DEFAULT_OUT = BACKEND_ROOT / "data" / "nbis_swing"


def build_config(overrides: list[str]) -> SwingConfig:
    fields = {field.name: field for field in dataclasses.fields(SwingConfig)}
    changes: dict[str, object] = {}
    for item in overrides:
        name, _, value = item.partition("=")
        if name not in fields or not _:
            raise SystemExit(f"--set expects name=value with a SwingConfig field; got {item!r}")
        changes[name] = _coerce(fields[name], value)
    return dataclasses.replace(SwingConfig(), **changes)


def run_backtest(
    loader: BarLoader,
    tickers: list[str],
    config: SwingConfig,
    start: date,
    end: date,
    warmup_days: int,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, SwingResult]:
    # The daily EMA comes from the same raw regular-session minute bars as the
    # 15-minute chart. Alpaca's daily bars are split- and dividend-adjusted
    # (older prices sit below raw ones for any dividend payer) and carry stale
    # history for relisted symbols (NBIS: 51 flat bars at the halted price).
    options = RunOptions(start, end, warmup_days, extended_hours=False, atr_source="minutes")
    chart, daily = load_bars(loader, tickers, options, config.timeframe_minutes, progress)
    results = {}
    for ticker in tickers:
        result = run_nbis_swing(ticker, chart[ticker], daily[ticker], config)
        # Warm-up sessions seed the 15-minute EMA 20 and ATR; their trades are not reported.
        result.trades = [t for t in result.trades if t.entry_time.astimezone(ET).date() >= start]
        result.events = [e for e in result.events if e.time.astimezone(ET).date() >= start]
        results[ticker] = result
    return results


def main(argv: list[str] | None = None, loader_factory: Callable[[], BarLoader] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--days", type=int, default=365, help="calendar days back from --end (default 365)")
    parser.add_argument("--start", type=date.fromisoformat, help="first reported day; overrides --days")
    parser.add_argument("--end", type=date.fromisoformat, help="last day (default: yesterday)")
    parser.add_argument("--warmup-days", type=int, default=10, help="calendar days of bars before --start")
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="FIELD=VALUE",
                        help="override a SwingConfig field, e.g. target_r=3 or reclaim_level=daily_ema")
    parser.add_argument("--feed", choices=("iex", "sip"), help="sets ALPACA_DATA_FEED for this run")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.feed:
        os.environ["ALPACA_DATA_FEED"] = args.feed
    tickers = [t.upper() for t in args.tickers]
    end = args.end or (datetime.now(ET).date() - timedelta(days=1))
    start = args.start or (end - timedelta(days=args.days))
    config = build_config(args.overrides)

    loader = (loader_factory or AlpacaLoader)()
    feed = getattr(loader, "feed", os.environ.get("ALPACA_DATA_FEED", "iex"))
    print(f"NBIS recovery swing {config.version}, {config.timeframe_minutes}m, {start} to {end}, feed {feed}, "
          f"{len(tickers)} tickers", file=sys.stderr)
    results = run_backtest(loader, tickers, config, start, end, args.warmup_days,
                           lambda line: print(line, file=sys.stderr))

    changed = {f.name: getattr(config, f.name) for f in dataclasses.fields(SwingConfig)
               if getattr(config, f.name) != f.default}
    trades = [trade for result in results.values() for trade in result.closed_trades]
    events = Counter(e.kind if not e.detail else f"{e.kind}: {e.detail}" for r in results.values() for e in r.events)
    overnight = sum(t.overnight for t in trades)
    text = "\n".join([
        f"NBIS recovery swing {config.version}, {config.timeframe_minutes}m, {start} to {end}, feed {feed}, "
        f"settings {changed or 'default'}. R = price move from the fill over the fill-to-stop risk.",
        report(trades),
        f"\n== intraday-only exits, same entries ({overnight} of {len(trades)} trades were carried overnight)",
        report([intraday_only(t) for t in trades], keys=("ticker",)),
        "\n== setup events",
        *(f"  {count:6d}  {label}" for label, count in events.most_common()),
    ])
    print(text)

    run_dir = args.out / f"{datetime.now(ET):%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.txt").write_text(text + "\n")
    for ticker, result in results.items():
        name = f"NBS_py_v{config.version}_{ticker}_{end.isoformat()}.csv"
        (run_dir / name).write_text("﻿" + tradingview_csv(result.trades, config, entry_comment, exit_comment))
    print(f"\nWrote {run_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
