"""
The strategy factory: judge a candidate strategy automatically and record it.

A candidate is a JSON spec in `research/specs/` (a family of entry rules from
`app/engine/factory_rules.py` plus its settings, exits, costs and filters,
and optionally a learned filter). `run` puts it through the gates in
`app/engine/factory_gates.py` (a screen on the discovery period, confirmation
on later data with a bar that rises with every candidate tried, a one-time
exam on the locked holdout) and appends the result to
`research/ledger.jsonl`. See docs/strategy-factory.md.

Bars are Alpaca SIP minute bars from the local cache (`prepare` fills it and
needs the API key; `run` and `ledger` never touch the network).

Usage:
    python scripts/strategy_factory.py prepare
    python scripts/strategy_factory.py run ../research/specs/recovery_swing_v0.1.json
    python scripts/strategy_factory.py ledger
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import pickle
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.engine.factory_data import FEATURES, Series, session_bars  # noqa: E402
from app.engine.factory_gates import (  # noqa: E402
    Evaluation,
    evaluate,
    ledger_record,
    period_of,
    prior_candidates,
    report,
    required_t,
    signal_day,
)
from app.engine.factory_rules import CORE_UNIVERSE, MARKET, Spec, parse_spec, spec_id  # noqa: E402
from app.engine.market_map import ET, Bar, bars_from_alpaca, resample  # noqa: E402

LEDGER = REPO_ROOT / "research" / "ledger.jsonl"
DATA_START = date(2023, 6, 1)
CACHE_VERSION = 1
DEFAULT_OUT = BACKEND_ROOT / "data" / "factory"


class MinuteSource(Protocol):
    """Where minute bars come from: Alpaca's cache, or a stub in tests."""

    feed: str

    def days(self, ticker: str) -> list[date]: ...

    def minute_bars(self, ticker: str, day: date) -> list[dict]: ...


class AlpacaCache:
    """The minute bars `app.engine.alpaca` has cached on disk. Reads only."""

    def __init__(self) -> None:
        from app.engine import alpaca

        self.alpaca = alpaca
        self.feed = alpaca.ALPACA_DATA_FEED
        self.root = alpaca.CACHE_DIR / "stocks" / "1Min" / self.feed

    def days(self, ticker: str) -> list[date]:
        folder = self.root / ticker
        if not folder.is_dir():
            return []
        return sorted(date.fromisoformat(path.stem) for path in folder.glob("*.json"))

    def minute_bars(self, ticker: str, day: date) -> list[dict]:
        return self.alpaca.fetch_minute_bars_for_date([ticker], day, cache_only=True).get(ticker, [])


class BarStore:
    """Session bars per ticker and timeframe, built once from the minute cache
    and kept as a pickle under `data/factory/bars/`, rebuilt when the minute
    cache has newer days. `load` cuts them at a day and builds the `Series`."""

    def __init__(self, source: MinuteSource, root: Path, progress: Callable[[str], None] = lambda _: None):
        self.source = source
        self.root = root / "bars" / source.feed
        self.progress = progress
        self.memory: dict[tuple[str, int], list[Bar]] = {}
        self.requests: list[tuple[str, int, date | None]] = []

    def _bars(self, ticker: str, timeframe: int) -> list[Bar]:
        key = (ticker, timeframe)
        if key in self.memory:
            return self.memory[key]
        days = [day for day in self.source.days(ticker) if day >= DATA_START]
        path = self.root / f"{ticker}_{timeframe}m.pkl"
        through = days[-1] if days else None
        rows = None
        if path.exists():
            with path.open("rb") as handle:
                cached = pickle.load(handle)
            if cached.get("version") == CACHE_VERSION and cached.get("through") == through:
                rows = cached["bars"]
        if rows is None:
            self.progress(f"  building {ticker} {timeframe}-minute bars from {len(days)} days of minute bars")
            minutes = []
            for day in days:
                minutes += session_bars(bars_from_alpaca(self.source.minute_bars(ticker, day)))
            bars = resample(minutes, timeframe)
            rows = [(bar.time.timestamp(), bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                pickle.dump({"version": CACHE_VERSION, "through": through, "bars": rows}, handle)
        bars = [Bar(datetime.fromtimestamp(row[0], timezone.utc), *row[1:]) for row in rows]
        if timeframe >= 5:
            self.memory[key] = bars
        return bars

    def last_day(self, ticker: str) -> date | None:
        days = self.source.days(ticker)
        return days[-1] if days else None

    def load(self, ticker: str, timeframe: int, through: date | None) -> Series | None:
        self.requests.append((ticker, timeframe, through))
        bars = self._bars(ticker, timeframe)
        if through is not None:
            bars = [bar for bar in bars if bar.time.astimezone(ET).date() <= through]
        return Series.build(ticker, bars, timeframe) if bars else None


# --- the ledger -------------------------------------------------------------------


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_ledger(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=False) + "\n")


def code_version() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "app/engine", "scripts/strategy_factory.py"],
                               cwd=BACKEND_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("-dirty" if dirty else "")


def trades_csv(ev: Evaluation) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    names = list(FEATURES)
    writer.writerow(["ticker", "period", "side", "signal_time", "entry_time", "entry_price", "stop", "target",
                     "exit_time", "exit_price", "exit_reason", "r", "sessions_held", *names])
    for t in sorted(ev.trades, key=lambda t: (t.entry_time, t.ticker)):
        writer.writerow([
            t.ticker, period_of(signal_day(t)), "long" if t.side == 1 else "short",
            t.signal_time.astimezone(ET).isoformat(), t.entry_time.astimezone(ET).isoformat(), t.entry_price,
            t.stop, t.target, t.exit_time.astimezone(ET).isoformat() if t.exit_time else "", t.exit_price,
            t.exit_reason, round(t.r, 4), t.sessions_held,
            *[round(t.features.get(name, float("nan")), 4) for name in names],
        ])
    return out.getvalue()


def load_spec(path: Path) -> Spec:
    return parse_spec(json.loads(path.read_text()))


# --- commands ---------------------------------------------------------------------


def run_one(spec: Spec, store: BarStore, ledger: Path, out: Path, exam: bool,
            progress: Callable[[str], None]) -> tuple[Evaluation, Path]:
    records = read_ledger(ledger)
    ev = evaluate(spec, store.load, prior_candidates(records, excluding=spec_id(spec)), exam=exam, progress=progress)
    now = datetime.now(ET)
    record = ledger_record(ev, now, code_version(), store.last_day(MARKET))
    append_ledger(ledger, record)
    run_dir = out / "runs" / f"{now:%Y%m%d-%H%M%S}-{ev.id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.txt").write_text(report(ev) + "\n")
    (run_dir / "trades.csv").write_text(trades_csv(ev))
    return ev, run_dir


def command_run(args: argparse.Namespace, store: BarStore, progress: Callable[[str], None]) -> int:
    spec = load_spec(args.spec)
    records = read_ledger(args.ledger)
    # Hand-research lines share an id with the spec they describe, so a spec
    # tried by hand still runs here once; it is counted once either way.
    known = {record["id"]: record for record in records if record.get("source") == "factory"}
    queue = [spec]
    parent = spec.parent()
    if parent is not None and spec_id(parent) not in known:
        # The model learns from the rules without it, and looking at those
        # rules is a trial of its own, so they are judged and counted first.
        queue.insert(0, parent)
    for candidate in queue:
        identifier = spec_id(candidate)
        if identifier in known and not args.rerun:
            print(f"{identifier} ({candidate.name}) is already in the ledger: {known[identifier]['verdict']}. "
                  f"Use --rerun to run it again.")
            continue
        progress(f"{candidate.name} ({identifier})")
        ev, run_dir = run_one(candidate, store, args.ledger, args.out, not args.no_exam, progress)
        print(report(ev))
        print(f"\nWrote {run_dir} and a line in {args.ledger}", file=sys.stderr)
    return 0


def command_ledger(args: argparse.Namespace) -> int:
    records = read_ledger(args.ledger)
    for record in records:
        periods = record.get("periods") or {}
        numbers = []
        for name in ("discovery", "confirm", "holdout"):
            stats = periods.get(name)
            if stats and stats.get("n"):
                edge_t = stats.get("edge_t")
                numbers.append(f"{name} {stats['n']} trades {stats['mean_r']:+.3f}R"
                               + (f" t={edge_t:.2f}" if edge_t is not None else ""))
        print(f"{record['id']:18s} {record['verdict']:20s} {record['name']}")
        if numbers or record.get("summary"):
            print(f"{'':18s} {'; '.join(numbers) or record.get('summary')}")
    count = prior_candidates(records)
    print(f"\n{len(records)} candidates in the ledger, {count} reached confirmation; "
          f"the next one there needs t >= {required_t(count + 1):.2f}.")
    return 0


def command_prepare(args: argparse.Namespace, progress: Callable[[str], None]) -> int:
    from app.engine import alpaca

    if not alpaca.alpaca_configured():
        raise SystemExit("ALPACA_API_KEY and ALPACA_API_SECRET are not set; prepare fetches bars and needs them.")
    cache = AlpacaCache()
    through = args.through or (datetime.now(ET).date() - timedelta(days=1))
    for ticker in args.tickers:
        have = cache.days(ticker)
        cached = set(have)
        # A ticker that listed after DATA_START (NBIS) starts at its first cached day,
        # so the days before its listing are not asked for again each time.
        day = have[0] if have else DATA_START
        wanted = []
        while day <= through:
            if day.weekday() < 5 and day not in cached:
                wanted.append(day)
            day += timedelta(days=1)
        progress(f"{ticker}: {len(wanted)} weekdays to fetch")
        for index, day in enumerate(wanted, start=1):
            alpaca.fetch_minute_bars_for_date([ticker], day)
            if index % 50 == 0:
                progress(f"  {index}/{len(wanted)}")
    return 0


def main(argv: list[str] | None = None, source_factory: Callable[[], MinuteSource] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--feed", choices=("iex", "sip"), default="sip", help="the Alpaca feed (default sip)")
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="judge a spec and record it in the ledger")
    run.add_argument("spec", type=Path)
    run.add_argument("--rerun", action="store_true", help="run a spec that is already in the ledger again")
    run.add_argument("--no-exam", action="store_true", help="stop after confirmation, holdout untouched")
    sub.add_parser("ledger", help="list the ledger and the current bar")
    prepare = sub.add_parser("prepare", help="fetch the minute bars the factory needs (needs the Alpaca key)")
    prepare.add_argument("--tickers", nargs="+", default=[*CORE_UNIVERSE, MARKET])
    prepare.add_argument("--through", type=date.fromisoformat)
    args = parser.parse_args(argv)

    os.environ["ALPACA_DATA_FEED"] = args.feed

    def progress(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    if args.command == "ledger":
        return command_ledger(args)
    if args.command == "prepare":
        return command_prepare(args, progress)
    store = BarStore((source_factory or AlpacaCache)(), args.out, progress)
    return command_run(args, store, progress)


if __name__ == "__main__":
    raise SystemExit(main())
