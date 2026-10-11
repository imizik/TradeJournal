"""Operate the separately registered prospective MU study; market data only."""
import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine.market_map import ET  # noqa: E402
from app.engine.research_studio import session_close  # noqa: E402
from app.engine.research_studio_prospective import ProspectiveStudy, sessions, PROSPECTIVE_END  # noqa: E402

ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"
PAGE_BYTES = 2 * 1024 * 1024


def fetch_sip(day, symbols, *, client_factory=httpx.Client):
    if day not in sessions() or not symbols or set(symbols) - {"MU", "SPY"}:
        raise ValueError("provider request outside the frozen MU/SPY study")
    key, secret = os.environ.get("ALPACA_API_KEY", ""), os.environ.get("ALPACA_API_SECRET", "")
    if not key or not secret:
        raise ValueError("existing Alpaca SIP credentials are required; no feed fallback")
    closing = datetime.combine(day, time(session_close(day)//60, session_close(day)%60), ET)
    params = {"symbols": ",".join(symbols), "timeframe": "1Min", "feed": "sip", "adjustment": "raw", "asof": "-",
              "start": datetime.combine(day, time(9, 30), ET).isoformat(),
              "end": (closing-timedelta(seconds=1)).isoformat(), "limit": 10000, "sort": "asc"}
    result = {s: [] for s in symbols}
    tokens = set()
    try:
        with client_factory(timeout=15, trust_env=False, follow_redirects=False,
                            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}) as client:
            for _ in range(4):
                with client.stream("GET", ENDPOINT, params=params) as response:
                    if response.status_code != 200:
                        raise ValueError(f"Alpaca SIP HTTP {response.status_code}; no fallback or purchase")
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if len(data)+len(chunk) > PAGE_BYTES:
                            raise ValueError("provider page exceeded byte bound")
                        data.extend(chunk)
                page = json.loads(data)
                if type(page) is not dict:
                    raise ValueError("provider page must be an object")
                bars = page.get("bars")
                if type(bars) is not dict or set(bars)-set(symbols):
                    raise ValueError("provider returned an unexpected symbol set")
                for symbol, rows in bars.items():
                    if type(rows) is not list:
                        raise ValueError("provider bars must be lists")
                    result[symbol].extend(rows)
                token = page.get("next_page_token")
                if token is None:
                    return result
                if not isinstance(token, str) or len(token)>2048 or token in tokens:
                    raise ValueError("provider pagination token refused")
                tokens.add(token)
                params["page_token"] = token
            raise ValueError("provider exceeded four-page request budget")
    except httpx.HTTPError:
        raise ValueError("Alpaca SIP request unavailable; inspect collection status") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "seal", "status", "run", "review"))
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--warmup", type=Path, required=True)
    args = parser.parse_args()
    try:
        study = ProspectiveStudy(args.records, args.cache, args.warmup)
        now = datetime.now(timezone.utc)
        if args.action == "register":
            output = study.register(now)
        elif args.action == "seal":
            output = study.seal()
        elif args.action == "review":
            output = study.review(now)
        else:
            collection_error = None
            if args.action == "run":
                terminal = now.astimezone(ET) >= datetime.combine(PROSPECTIVE_END, time(20, 30), ET)
                try:
                    study.collect(fetch_sip, now)
                except ValueError:
                    if not terminal:
                        raise
                    collection_error = "Final collection failed; review uses committed sessions only."
                if terminal:
                    study.review(now)
            output = study.status(now)
            if collection_error:
                output["collection_error"] = collection_error
        print(json.dumps(output, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Prospective study refused: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
