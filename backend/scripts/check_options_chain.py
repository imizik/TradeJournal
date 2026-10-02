"""Read-only live check of the Tradier option chain adapter.

Run from backend: .venv/bin/python -m scripts.check_options_chain --symbol SPY --symbol SPX
An optional --env-file loads only the Tradier token and base URL, never database
settings. Nothing is written. Each symbol costs two requests from the options
budget: its expiration list and its nearest expiration's chain.

For each symbol it prints the nearest expiration, how many contracts and roots
the chain listed, how many carry open interest and a usable implied volatility,
and the provider's greeks stamps. A clean run prints `"ok": true`; record the
output with its date.
"""

import argparse
from collections import Counter
from datetime import datetime
import json
import os

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", help="repeatable; defaults to SPY")
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if args.env_file:
        values = dotenv_values(args.env_file)
        for key in ("TRADIER_API_KEY", "TRADIER_BASE_URL"):
            if values.get(key):
                os.environ[key] = values[key]

    from app.engine.chart_math import ET
    from app.engine.options_chain import OptionsChainError, TradierOptions

    client = TradierOptions()
    report, ok = {"checked_at": datetime.now(ET).isoformat(), "symbols": {}}, True
    for symbol in args.symbol or ["SPY"]:
        try:
            dates = client.expirations(symbol, wait=True)
            if not dates:
                raise OptionsChainError("no listed expirations", "malformed")
            chain = client.chain(symbol, dates[0], wait=True)
        except OptionsChainError as exc:
            report["symbols"][symbol] = {"ok": False, "code": exc.code, "problem": str(exc)}
            ok = False
            continue
        contracts = chain.contracts
        report["symbols"][symbol] = {
            "ok": bool(contracts),
            "expirations": len(dates), "nearest": dates[0].isoformat(),
            "fetched_at": chain.fetched_at.isoformat(),
            "contracts": len(contracts),
            "roots": dict(Counter(c.root for c in contracts)),
            "multipliers": dict(Counter(str(c.multiplier) for c in contracts)),
            "with_open_interest": sum(1 for c in contracts if c.open_interest),
            "with_iv": sum(1 for c in contracts if c.iv is not None),
            "never_traded": sum(1 for c in contracts if c.trade_time is None),
            "greeks_updated_at": dict(Counter(str(c.greeks_updated_at) for c in contracts).most_common(3)),
            "latest_quote_time": max((c.bid_time for c in contracts if c.bid_time), default=None),
        }
        ok = ok and bool(contracts)
    print(json.dumps({**report, "ok": ok}, indent=1, default=str))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
