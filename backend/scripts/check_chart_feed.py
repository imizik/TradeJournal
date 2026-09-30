"""Read-only Tradier/Webull chart-access probe. Never opens the journal DB.

Run from backend: .venv/bin/python -m scripts.check_chart_feed [--symbol SPY]
An optional --env-file loads only provider credentials, not database settings.
No orders, subscriptions, tokens, or account state are created or modified.
"""

import argparse
from datetime import datetime, timedelta
import json
import os

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--env-file")
    args = parser.parse_args()
    keys = ("TRADIER_API_KEY", "WEBULL_APP_KEY", "WEBULL_APP_SECRET", "WEBULL_ACCESS_TOKEN")
    if args.env_file:
        values = dotenv_values(args.env_file)
        for key in keys:
            if values.get(key):
                os.environ[key] = values[key]

    from app.engine import tradier
    from app.engine.chart_math import ET
    from app.engine.webull_client import WebullHttpClient, webull_configured

    now = datetime.now(ET)
    print(json.dumps({"checked_at": now.isoformat(), "symbol": args.symbol.upper()}))
    if tradier.tradier_configured():
        headers = {"Authorization": f"Bearer {tradier.TRADIER_API_KEY}", "Accept": "application/json"}
        endpoints = [
            ("quotes", "/v1/markets/quotes", {"symbols": args.symbol.upper()}),
            ("candles", "/v1/markets/timesales", {"symbol": args.symbol.upper(), "interval": "1min", "session_filter": "all",
             "start": (now - timedelta(days=3)).strftime("%Y-%m-%d 04:00"), "end": now.strftime("%Y-%m-%d %H:%M")}),
        ]
        for kind, path, params in endpoints:
            try:
                response = httpx.get(f"{tradier.TRADIER_BASE_URL}{path}", params=params, headers=headers, timeout=15)
                report = {"provider": "Tradier", "kind": kind, "http": response.status_code, "requests_per_minute": response.headers.get("X-Ratelimit-Allowed")}
                if response.is_success:
                    data = response.json()
                    if kind == "quotes":
                        quote = (data.get("quotes") or {}).get("quote") or {}
                        if isinstance(quote, list):
                            quote = quote[0] if quote else {}
                        stamp = quote.get("trade_date")
                        report["last"] = quote.get("last")
                        report["last_trade_age_seconds"] = round(datetime.now(ET).timestamp() - float(stamp) / 1000, 2) if stamp else None
                    else:
                        bars = (data.get("series") or {}).get("data") or []
                        bars = [bars] if isinstance(bars, dict) else bars
                        report["bars"] = len(bars)
                        report["last_bar"] = bars[-1].get("time") if bars else None
                print(json.dumps(report))
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                print(json.dumps({"provider": "Tradier", "kind": kind, "error_type": type(exc).__name__}))
    else:
        print(json.dumps({"provider": "Tradier", "configured": False}))

    if webull_configured():
        client = WebullHttpClient()
        path = "/market-data/stocks/snapshots/list"
        params = {"symbols": args.symbol.upper(), "category": "US_STOCK", "extend_hour_required": "true", "overnight_required": "false"}
        # Market Data v3 differs from the existing account/import v2 client.
        # This probe doesn't change the account client's protocol or tokens.
        headers = client._build_signed_headers(path=path, query_params=params, body_string=None)
        headers["x-version"] = "v3"
        try:
            response = httpx.get(client.describe()["base_url"] + path, params=params, headers=headers, timeout=15)
            data = response.json()
            message = str(data.get("msg") or data.get("message") or "") if isinstance(data, dict) else ""
            for key in keys:
                if os.environ.get(key):
                    message = message.replace(os.environ[key], "<redacted>")
            print(json.dumps({"provider": "Webull", "http": response.status_code, "message": message[:250]}))
        except (httpx.HTTPError, ValueError) as exc:
            print(json.dumps({"provider": "Webull", "error_type": type(exc).__name__}))
    else:
        print(json.dumps({"provider": "Webull", "configured": False}))


if __name__ == "__main__":
    main()
