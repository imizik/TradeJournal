"""
Backtest Isaac Market Map over many tickers from Alpaca bars.

Runs the Python port of `docs/pine/isaac_market_map.pine`
(`app/engine/market_map.py`) on each ticker, prints a cohort report in R, and
writes a TradingView-shaped "List of trades" CSV per ticker that imports into
Strategy Lab (source timezone America/New_York).

Bars come from the cached Alpaca clients in `app/engine/alpaca.py`: 1-minute
bars resampled to the chart timeframe, daily bars for the prior-day ATR. The
default IEX feed sees a small share of volume, which moves RVOL and so the
grade and size; use `--feed sip` when the key allows it.

Usage:
    python scripts/backtest_market_map.py MU META AAPL NBIS SPY --days 365
    python scripts/backtest_market_map.py AMD LLY --days 180 --set allow_shorts=true
    # parity with the committed v1.0.0 Strategy Tester exports (see docs/pine/README.md)
    python scripts/backtest_market_map.py --profile v1.0.0 --feed sip --extended-hours \\
        --start 2025-10-14 --end 2026-09-24 --parity "TradingView/IMM_v1.0.0_*.csv"
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.engine.market_map import (  # noqa: E402
    ET,
    BacktestResult,
    Bar,
    MarketMapConfig,
    bars_from_alpaca,
    daily_from_alpaca,
    daily_from_bars,
    regular_session,
    resample,
    run_market_map,
)
from app.engine.market_map_report import (  # noqa: E402
    cohort_report,
    compare_to_export,
    load_tradingview_export,
    parity_text,
    tradingview_csv,
)

DEFAULT_OUT = BACKEND_ROOT / "data" / "market_map"
ATR_WARMUP_DAYS = 120


class BarLoader(Protocol):
    def minute_bars(self, symbols: list[str], day: date) -> dict[str, list[dict]]: ...

    def daily_bars(self, symbols: list[str], start: date, end: date) -> dict[str, list[dict]]: ...


class AlpacaLoader:
    """The cached Alpaca clients. Imported lazily so `--feed` can set the feed first."""

    def __init__(self) -> None:
        from app.engine import alpaca

        if not alpaca.alpaca_configured():
            raise SystemExit("ALPACA_API_KEY and ALPACA_API_SECRET are not set; nothing to backtest.")
        self.alpaca = alpaca
        self.feed = alpaca.ALPACA_DATA_FEED

    def minute_bars(self, symbols: list[str], day: date) -> dict[str, list[dict]]:
        return self.alpaca.fetch_minute_bars_for_date(symbols, day)

    def daily_bars(self, symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
        return self.alpaca.fetch_daily_bars(symbols, start, end)


@dataclass
class RunOptions:
    start: date
    end: date
    warmup_days: int = 20
    extended_hours: bool = False
    atr_source: str = "daily"


def _weekdays(start: date, end: date) -> list[date]:
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def load_bars(
    loader: BarLoader,
    symbols: list[str],
    options: RunOptions,
    timeframe: int,
    progress: Callable[[str], None] = lambda _: None,
) -> tuple[dict[str, list[Bar]], dict[str, list]]:
    """Chart bars and daily bars per symbol, from the warm-up start to `end`.

    Daily history reaches `ATR_WARMUP_DAYS` further back than the chart
    bars, whichever source builds it, so ATR is seeded before the first
    reported session.
    """
    first = options.start - timedelta(days=options.warmup_days)
    atr_first = first - timedelta(days=ATR_WARMUP_DAYS)
    minutes: dict[str, list[dict]] = {symbol: [] for symbol in symbols}
    days = _weekdays(atr_first if options.atr_source == "minutes" else first, options.end)
    for index, day in enumerate(days, start=1):
        for symbol, raw in loader.minute_bars(symbols, day).items():
            if symbol in minutes:
                minutes[symbol].extend(raw)
        if index % 20 == 0 or index == len(days):
            progress(f"  minute bars: {index}/{len(days)} days")
    chart: dict[str, list[Bar]] = {}
    daily: dict[str, list] = {}
    for symbol, raw in minutes.items():
        bars = bars_from_alpaca(raw)
        if options.atr_source == "minutes":
            daily[symbol] = daily_from_bars(bars)
        bars = [bar for bar in bars if bar.time.astimezone(ET).date() >= first]
        if not options.extended_hours:
            bars = regular_session(bars)
        chart[symbol] = resample(bars, timeframe)
    if options.atr_source == "daily":
        # ATR is the prior day's, so the last day's own bar is never read. Asking
        # for it anyway makes SIP refuse the whole request on that same evening
        # ("recent SIP data" is a 403, which comes back as no bars at all).
        raw_daily = loader.daily_bars(symbols, atr_first, options.end - timedelta(days=1))
        daily = {symbol: daily_from_alpaca(raw_daily.get(symbol, [])) for symbol in symbols}
    return chart, daily


def atr_ready(daily: list, start: date, length: int) -> bool:
    """Whether at least `length` completed daily bars precede `start`."""
    return sum(1 for bar in daily if bar.day < start) >= length


def run_backtest(
    loader: BarLoader,
    tickers: list[str],
    config: MarketMapConfig,
    options: RunOptions,
    progress: Callable[[str], None] = lambda _: None,
) -> dict[str, BacktestResult]:
    benchmark = config.benchmark_ticker
    symbols = list(dict.fromkeys([*tickers, benchmark]))
    chart, daily = load_bars(loader, symbols, options, config.timeframe_minutes, progress)
    if options.atr_source == "daily":
        for symbol in symbols:
            mismatched = adjustment_mismatches(chart[symbol], daily[symbol])
            if mismatched:
                progress(
                    f"WARNING: {symbol} daily closes differ from minute closes by >2% on {len(mismatched)} days "
                    f"(first {mismatched[0]}); a split or adjustment would distort ATR. Try --atr-source minutes."
                )
    for symbol in symbols:
        if not atr_ready(daily[symbol], options.start, config.atr_length):
            progress(
                f"WARNING: {symbol} has fewer than {config.atr_length} daily bars before {options.start}; "
                "early sessions have no ATR and cannot trade."
            )
    results = {}
    for ticker in tickers:
        result = run_market_map(ticker, chart[ticker], daily[ticker], chart[benchmark], config)
        # Warm-up bars build state (RVOL history, EMAs, levels); their trades are not reported.
        result.trades = [t for t in result.trades if t.entry_time.astimezone(ET).date() >= options.start]
        result.signals = [s for s in result.signals if s.time.astimezone(ET).date() >= options.start]
        results[ticker] = result
    return results


def _coerce(field: dataclasses.Field, text: str):
    kind = field.type if isinstance(field.type, str) else field.type.__name__
    if kind == "bool":
        if text.lower() not in ("true", "false"):
            raise SystemExit(f"--set {field.name} expects true or false")
        return text.lower() == "true"
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    return text


def build_config(profile: str, overrides: list[str], timeframe: int) -> MarketMapConfig:
    config = MarketMapConfig.v1_0_0() if profile == "v1.0.0" else MarketMapConfig()
    fields = {field.name: field for field in dataclasses.fields(MarketMapConfig)}
    changes: dict[str, object] = {"timeframe_minutes": timeframe}
    for item in overrides:
        name, _, value = item.partition("=")
        if name not in fields or not _:
            raise SystemExit(f"--set expects name=value with a MarketMapConfig field; got {item!r}")
        changes[name] = _coerce(fields[name], value)
    return dataclasses.replace(config, **changes)


def export_ticker(path: str) -> str:
    """`IMM_v1.0.0_NASDAQ_MU_2026-09-24.csv` -> `MU`, the way imm_export_cohorts.py reads it."""
    return Path(path).stem.split("_")[-2].upper()


def find_exports(pattern: str) -> list[str]:
    """Match from the working directory first, then from backend/."""
    return sorted(glob.glob(pattern)) or sorted(glob.glob(str(BACKEND_ROOT / pattern)))


def export_version(path: str) -> str | None:
    """`IMM_v1.0.0_NASDAQ_MU_2026-09-24.csv` -> `1.0.0`."""
    parts = Path(path).stem.split("_")
    return parts[1][1:] if len(parts) > 1 and parts[1].startswith("v") else None


def adjustment_mismatches(chart: list[Bar], daily: list) -> list[date]:
    """Days where the daily close and the last regular-session bar disagree by more than 2%.

    Alpaca daily bars are split- and dividend-adjusted and minute bars are
    raw, so a split inside the window shows up here and would distort ATR.
    """
    closes = {bar.day: bar.close for bar in daily}
    return [
        bar.day
        for bar in daily_from_bars(chart)
        if bar.day in closes and closes[bar.day] > 0 and abs(bar.close / closes[bar.day] - 1) > 0.02
    ]


def main(argv: list[str] | None = None, loader_factory: Callable[[], BarLoader] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--days", type=int, default=365, help="calendar days back from --end (default 365)")
    parser.add_argument("--start", type=date.fromisoformat, help="first reported day; overrides --days")
    parser.add_argument("--end", type=date.fromisoformat, help="last day (default: yesterday)")
    parser.add_argument("--timeframe", type=int, default=5, help="chart minutes, a divisor of 30 (default 5)")
    parser.add_argument("--warmup-days", type=int, default=20, help="calendar days of bars before --start")
    parser.add_argument("--extended-hours", action="store_true", help="feed premarket and after-hours bars")
    parser.add_argument("--atr-source", choices=("daily", "minutes"), default="daily",
                        help="daily ATR from Alpaca daily bars, or from regular-session minute bars")
    parser.add_argument("--profile", choices=("v1.1.0", "v1.0.0"), default="v1.1.0")
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="FIELD=VALUE",
                        help="override a MarketMapConfig field, e.g. allow_shorts=true")
    parser.add_argument("--feed", choices=("iex", "sip"), help="sets ALPACA_DATA_FEED for this run")
    parser.add_argument("--parity", metavar="GLOB", help="compare entries with Strategy Tester exports")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.feed:
        os.environ["ALPACA_DATA_FEED"] = args.feed
    exports = find_exports(args.parity) if args.parity else []
    if args.parity and not exports:
        raise SystemExit(f"No exports match {args.parity}")
    tickers = [t.upper() for t in args.tickers] or list(dict.fromkeys(export_ticker(p) for p in exports))
    if not tickers:
        parser.error("name at least one ticker, or --parity exports to take them from")

    end = args.end or (datetime.now(ET).date() - timedelta(days=1))
    start = args.start or (end - timedelta(days=args.days))
    config = build_config(args.profile, args.overrides, args.timeframe)
    options = RunOptions(start, end, args.warmup_days, args.extended_hours, args.atr_source)

    for path in exports:
        if export_version(path) not in (None, config.indicator_version):
            print(f"WARNING: {Path(path).name} is v{export_version(path)} but this run is "
                  f"v{config.indicator_version}; pass --profile to match it.", file=sys.stderr)

    loader = (loader_factory or AlpacaLoader)()
    feed = getattr(loader, "feed", os.environ.get("ALPACA_DATA_FEED", "iex"))
    if feed == "iex":
        print(
            "WARNING: IEX feed. IEX prints a small share of consolidated volume, so RVOL (grade A vs B, "
            "full vs half size) will not match TradingView. Use --feed sip if your key allows it.",
            file=sys.stderr,
        )

    print(f"Isaac Market Map {config.indicator_version} ({args.profile}), {args.timeframe}m, "
          f"{start} to {end}, feed {feed}, {len(tickers)} tickers", file=sys.stderr)
    results = run_backtest(loader, tickers, config, options, lambda line: print(line, file=sys.stderr))

    run_dir = args.out / f"{datetime.now(ET):%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trades = [trade for result in results.values() for trade in result.closed_trades]
    header = (f"Isaac Market Map {config.indicator_version}, {args.timeframe}m, {start} to {end}, feed {feed}. "
              f"R = net PnL / risk budget (${config.risk_per_trade:g} full, half for half size).")
    report = header + "\n" + cohort_report(trades)
    print(report)
    (run_dir / "report.txt").write_text(report + "\n")
    for ticker, result in results.items():
        name = f"IMM_py_v{config.indicator_version}_{ticker}_{end.isoformat()}.csv"
        (run_dir / name).write_text("﻿" + tradingview_csv(result.trades, config))
        open_trades = [t for t in result.trades if not t.closed]
        if open_trades:
            print(f"{ticker}: {len(open_trades)} trade still open at the end of the data, not reported",
                  file=sys.stderr)

    if exports:
        sections = []
        for path in exports:
            ticker = export_ticker(path)
            if ticker not in results:
                continue
            exported = load_tradingview_export(Path(path).read_text(encoding="utf-8-sig"))
            parity = compare_to_export(results[ticker].trades, results[ticker].signals, exported, start, end)
            sections.append(parity_text(ticker, parity))
        parity_report = "\n\n".join(sections)
        print("\n== Parity with Strategy Tester exports\n" + parity_report)
        (run_dir / "parity.txt").write_text(parity_report + "\n")
    print(f"\nWrote {run_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
