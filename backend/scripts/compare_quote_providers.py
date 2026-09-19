"""Price the open book through Tradier, yfinance and Alpaca in the same second.

Read-only. Opens the database to find open positions, makes one round of quote
requests per provider, and prints them side by side with wall-clock latency.
Nothing is written anywhere.

This exists because "Tradier has better quotes" is a claim, and the dashboard
currently prices every open position through yfinance -- unofficial, and a
whole option chain downloaded to read one contract. Which provider to keep is
an empirical question; this is the measurement.

    cd backend
    .venv/bin/python -m scripts.compare_quote_providers            # open positions
    .venv/bin/python -m scripts.compare_quote_providers --json     # machine readable
    .venv/bin/python -m scripts.compare_quote_providers \
        --option NVDA:2026-10-17:180:call --stock SPY,NVDA         # ad hoc, no DB

Run it several times across a session -- at the open, mid-morning, near the
close, and once after hours. One sample at 11am says nothing about a provider's
behaviour in the first five minutes of trading, which is when it matters most.

What to look at, in order:

1. **spread_pct** on options. A consolidated NBBO should be tighter than an
   indicative feed. If Tradier is not tighter, its main advantage is not real.
2. **Disagreement on mid.** Large gaps mean at least one provider is stale.
3. **latency_ms.** One batched Tradier call against N chain downloads.
4. **iv_updated_at.** Tradier's greeks are ORATS, refreshed hourly. If this
   timestamp is an hour old, the IV is an hour old -- do not treat it as live.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.database import engine
from app.engine.occ import occ_symbol
from app.models import Trade


@dataclass
class Row:
    label: str
    provider: str
    last: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    iv: Optional[float] = None
    iv_updated_at: Optional[str] = None
    error: Optional[str] = None

    @property
    def spread_pct(self) -> Optional[float]:
        if self.bid is None or self.ask is None or not self.mid:
            return None
        return (self.ask - self.bid) / self.mid * 100


@dataclass
class Position:
    ticker: str
    instrument_type: str
    expiration: Optional[date] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None

    @property
    def label(self) -> str:
        if self.instrument_type != "option":
            return self.ticker
        return f"{self.ticker} {self.expiration} {self.strike} {self.option_type}"

    @property
    def occ(self) -> Optional[str]:
        if self.instrument_type != "option" or not self.expiration or self.strike is None:
            return None
        return occ_symbol(self.ticker, self.expiration, self.option_type or "", float(self.strike))


# ---------------------------------------------------------------------------
# what to price
# ---------------------------------------------------------------------------

def open_positions() -> list[Position]:
    with Session(engine) as session:
        trades = session.exec(select(Trade).where(Trade.status == "open")).all()

    positions: list[Position] = []
    for trade in trades:
        positions.append(
            Position(
                ticker=trade.ticker,
                instrument_type=trade.instrument_type,
                expiration=trade.expiration,
                strike=float(trade.strike) if trade.strike is not None else None,
                option_type=trade.option_type,
            )
        )
    return positions


def parse_option_argument(raw: str) -> Position:
    """TICKER:YYYY-MM-DD:STRIKE:call|put"""
    parts = raw.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"--option wants TICKER:YYYY-MM-DD:STRIKE:call|put, got {raw!r}")
    ticker, expiration, strike, option_type = parts
    return Position(
        ticker=ticker.upper(),
        instrument_type="option",
        expiration=date.fromisoformat(expiration),
        strike=float(strike),
        option_type=option_type.lower(),
    )


# ---------------------------------------------------------------------------
# providers
#
# Each returns (rows, elapsed_ms) and never raises: a provider that cannot
# answer is part of the result, not the end of the run.
# ---------------------------------------------------------------------------

def price_with_tradier(positions: list[Position]) -> tuple[list[Row], float]:
    from app.engine.tradier import TradierError, get_quotes, tradier_configured

    if not tradier_configured():
        return [Row(p.label, "tradier", error="TRADIER_API_KEY not set") for p in positions], 0.0

    symbols: dict[str, Position] = {}
    for position in positions:
        symbol = position.occ if position.instrument_type == "option" else position.ticker.upper()
        if symbol:
            symbols[symbol] = position

    started = time.perf_counter()
    try:
        quotes = get_quotes(sorted(symbols), greeks=True)
    except TradierError as exc:
        return [Row(p.label, "tradier", error=str(exc)) for p in positions], _ms(started)
    elapsed = _ms(started)

    rows = []
    for symbol, position in symbols.items():
        quote = quotes.get(symbol)
        if not quote:
            rows.append(Row(position.label, "tradier", error="no quote"))
            continue
        rows.append(
            Row(
                label=position.label,
                provider="tradier",
                last=quote.last,
                bid=quote.bid,
                ask=quote.ask,
                mid=quote.mid,
                iv=quote.iv_mid,
                iv_updated_at=quote.greeks_updated_at,
            )
        )
    return rows, elapsed


def price_with_yfinance(positions: list[Position]) -> tuple[list[Row], float]:
    from app.engine.quotes import _fetch_option_chains, _fetch_stock_quotes

    options = [p for p in positions if p.instrument_type == "option" and p.expiration]
    stocks = [p for p in positions if p.instrument_type != "option"]

    started = time.perf_counter()
    rows: list[Row] = []

    if stocks:
        try:
            prices = _yfinance_only(_fetch_stock_quotes, [p.ticker.upper() for p in stocks])
            for position in stocks:
                rows.append(Row(position.label, "yfinance", last=prices.get(position.ticker.upper())))
        except Exception as exc:  # noqa: BLE001 - a provider comparison reports failures
            rows += [Row(p.label, "yfinance", error=repr(exc)) for p in stocks]

    by_ticker: dict[str, set[str]] = {}
    for position in options:
        by_ticker.setdefault(position.ticker.upper(), set()).add(position.expiration.isoformat())

    chains: dict[tuple[str, str], dict] = {}
    for ticker, expirations in by_ticker.items():
        try:
            fetched = _fetch_option_chains(ticker, expirations)
            for expiration, premiums in fetched.items():
                chains[(ticker, expiration)] = premiums
        except Exception as exc:  # noqa: BLE001
            rows += [
                Row(p.label, "yfinance", error=repr(exc))
                for p in options
                if p.ticker.upper() == ticker
            ]

    for position in options:
        premiums = chains.get((position.ticker.upper(), position.expiration.isoformat()))
        if premiums is None:
            continue
        result = premiums.get((round(float(position.strike), 4), (position.option_type or "").lower()))
        if result is None:
            rows.append(Row(position.label, "yfinance", error="contract not in chain"))
            continue
        rows.append(
            Row(
                label=position.label,
                provider="yfinance",
                last=result.last_price,
                bid=result.bid,
                ask=result.ask,
                mid=result.mid,
                iv=result.iv,
            )
        )

    return rows, _ms(started)


def _yfinance_only(fetch, tickers: list[str]) -> dict[str, Optional[float]]:
    """Call the yfinance fetcher regardless of what QUOTES_PROVIDER says."""
    import os

    previous = os.environ.get("QUOTES_PROVIDER")
    os.environ["QUOTES_PROVIDER"] = "yfinance"
    try:
        return fetch(tickers)
    finally:
        if previous is None:
            os.environ.pop("QUOTES_PROVIDER", None)
        else:
            os.environ["QUOTES_PROVIDER"] = previous


def price_with_alpaca(positions: list[Position]) -> tuple[list[Row], float]:
    from app.engine.alpaca import alpaca_configured, fetch_option_snapshots, fetch_snapshots

    if not alpaca_configured():
        return [Row(p.label, "alpaca", error="Alpaca not configured") for p in positions], 0.0

    options = {p.occ: p for p in positions if p.instrument_type == "option" and p.occ}
    stocks = [p for p in positions if p.instrument_type != "option"]

    started = time.perf_counter()
    rows: list[Row] = []

    if stocks:
        try:
            snaps = fetch_snapshots([p.ticker.upper() for p in stocks])
            for position in stocks:
                snap = snaps.get(position.ticker.upper()) or {}
                trade = snap.get("latestTrade") or {}
                rows.append(Row(position.label, "alpaca", last=trade.get("p")))
        except Exception as exc:  # noqa: BLE001
            rows += [Row(p.label, "alpaca", error=repr(exc)) for p in stocks]

    if options:
        try:
            snaps = fetch_option_snapshots(sorted(options))
            for symbol, position in options.items():
                snap = snaps.get(symbol)
                if not snap:
                    rows.append(Row(position.label, "alpaca", error="no snapshot"))
                    continue
                quote = snap.get("latestQuote") or {}
                trade = snap.get("latestTrade") or {}
                greeks = snap.get("greeks") or {}
                bid, ask = quote.get("bp"), quote.get("ap")
                rows.append(
                    Row(
                        label=position.label,
                        provider="alpaca",
                        last=trade.get("p"),
                        bid=bid,
                        ask=ask,
                        mid=round((bid + ask) / 2, 4) if bid and ask else None,
                        iv=snap.get("impliedVolatility"),
                        iv_updated_at=greeks.get("updated_at"),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            rows += [Row(p.label, "alpaca", error=repr(exc)) for p in options.values()]

    return rows, _ms(started)


PROVIDERS = {
    "tradier": price_with_tradier,
    "yfinance": price_with_yfinance,
    "alpaca": price_with_alpaca,
}


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def print_table(rows_by_provider: dict[str, list[Row]], timings: dict[str, float]) -> None:
    labels: list[str] = []
    for rows in rows_by_provider.values():
        for row in rows:
            if row.label not in labels:
                labels.append(row.label)

    header = f"{'position':<38} {'provider':<9} {'bid':>10} {'ask':>10} {'mid':>10} {'last':>10} {'spread%':>8} {'iv':>7}  iv_as_of"
    print(header)
    print("-" * len(header))

    for label in labels:
        for provider, rows in rows_by_provider.items():
            for row in rows:
                if row.label != label:
                    continue
                if row.error:
                    print(f"{label:<38} {provider:<9} {row.error}")
                    continue
                print(
                    f"{label:<38} {provider:<9} {_fmt(row.bid):>10} {_fmt(row.ask):>10} "
                    f"{_fmt(row.mid):>10} {_fmt(row.last):>10} "
                    f"{_fmt(row.spread_pct, 2):>8} {_fmt(row.iv, 4):>7}  {row.iv_updated_at or '-'}"
                )
        print()

    print("latency (one round per provider):")
    for provider, elapsed in timings.items():
        print(f"  {provider:<9} {elapsed:>8.1f} ms")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--option", action="append", default=[], metavar="TICKER:YYYY-MM-DD:STRIKE:call|put",
                        help="price this contract instead of reading the database (repeatable)")
    parser.add_argument("--stock", default="", metavar="SPY,NVDA",
                        help="price these tickers instead of reading the database")
    parser.add_argument("--provider", action="append", default=[], choices=sorted(PROVIDERS),
                        help="limit to these providers (default: all three)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()

    positions: list[Position] = [parse_option_argument(raw) for raw in args.option]
    positions += [
        Position(ticker=t.strip().upper(), instrument_type="stock")
        for t in args.stock.split(",")
        if t.strip()
    ]

    from_db = not positions
    if from_db:
        positions = open_positions()
    if not positions:
        print("No open positions and nothing passed on the command line.", file=sys.stderr)
        return 1

    chosen = args.provider or list(PROVIDERS)
    print(
        f"# {datetime.now().astimezone().isoformat(timespec='seconds')} — "
        f"{len(positions)} position(s) from {'the database' if from_db else 'the command line'}",
        file=sys.stderr,
    )

    rows_by_provider: dict[str, list[Row]] = {}
    timings: dict[str, float] = {}
    for name in chosen:
        rows, elapsed = PROVIDERS[name](positions)
        rows_by_provider[name] = rows
        timings[name] = elapsed

    if args.json:
        print(json.dumps(
            {
                "captured_at": datetime.now().astimezone().isoformat(),
                "latency_ms": timings,
                "rows": [
                    {**vars(row), "spread_pct": row.spread_pct}
                    for rows in rows_by_provider.values()
                    for row in rows
                ],
            },
            indent=2,
            default=str,
        ))
    else:
        print_table(rows_by_provider, timings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
