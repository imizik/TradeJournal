"""Read-only live check of the chart price basis across one real split.

Run from backend: .venv/bin/python -m scripts.check_chart_splits --symbol NVDA --ex-date 2024-06-10
An optional --env-file loads only Alpaca/Tradier credentials, never database
settings. Nothing is written: split records go to a temporary directory, and
the journal database, fills and chart caches are not opened.

It compares, for the last session before the split and the ex-date session:
the split record Alpaca publishes, Alpaca's raw minutes adjusted by the chart's
own code, Alpaca's server-side split-adjusted daily close, and Tradier's daily
close. A clean run prints `"ok": true`; record the output with its date.
"""

import argparse
from datetime import date, datetime, time as wall_time, timedelta, timezone
import json
import os
import tempfile

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="NVDA")
    parser.add_argument("--ex-date", default="2024-06-10")
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if args.env_file:
        values = dotenv_values(args.env_file)
        for key in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "TRADIER_API_KEY"):
            if values.get(key):
                os.environ[key] = values[key]

    from pathlib import Path
    from app.engine import alpaca, tradier
    from app.engine.chart_adjust import adjust_minutes
    from app.engine.chart_math import ET, normalize_bars
    from app.engine.chart_splits import ChartSplits

    symbol, ex = args.symbol.upper(), date.fromisoformat(args.ex_date)
    with tempfile.TemporaryDirectory() as scratch:
        info = ChartSplits(Path(scratch)).get(symbol)
    split = next((s for s in info["splits"] if s["ex_date"] == ex.isoformat()), None)
    report = {"checked_at": datetime.now(ET).isoformat(), "symbol": symbol, "ex_date": ex.isoformat(),
              "split_source": "Alpaca /v1/corporate-actions", "split_status": info["status"], "split": split}
    if split is None:
        print(json.dumps({**report, "ok": False, "problem": "split not found in provider data"}))
        raise SystemExit(1)

    headers = {"APCA-API-KEY-ID": alpaca.ALPACA_API_KEY, "APCA-API-SECRET-KEY": alpaca.ALPACA_API_SECRET}
    days = [ex - timedelta(days=1)]
    while days[0].weekday() >= 5:
        days[0] -= timedelta(days=1)
    days.append(ex)

    def bars(day: date, **extra):
        start = datetime.combine(day, wall_time(4), ET).astimezone(timezone.utc)
        end = datetime.combine(day, wall_time(20), ET).astimezone(timezone.utc)
        params = {"timeframe": "1Min", "start": start.isoformat(), "end": end.isoformat(), "limit": 10000, "feed": "sip", "adjustment": "raw", **extra}
        out = []
        while True:
            body = httpx.get(f"{alpaca.DATA_URL}/v2/stocks/{symbol}/bars", params=params, headers=headers, timeout=20).json()
            out += body.get("bars") or []
            if not body.get("next_page_token"):
                return out
            params["page_token"] = body["next_page_token"]

    def last_regular_close(day: date, rows):
        keep = [r for r in rows if datetime.fromisoformat(r["t"].replace("Z", "+00:00")).astimezone(ET).time() < wall_time(16)]
        return keep[-1]["c"] if keep else None

    sessions, ok = {}, True
    for day in days:
        raw = bars(day)
        normalized = normalize_bars([{"timestamp": int(datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp()), "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"], "volume": r["v"]} for r in raw], source="alpaca_sip")
        adjusted = adjust_minutes(normalized, day, [split])
        reference = httpx.get(f"{alpaca.DATA_URL}/v2/stocks/{symbol}/bars", headers=headers, timeout=20, params={
            "timeframe": "1Day", "start": day.isoformat(), "end": day.isoformat(), "adjustment": "split", "feed": "sip"}).json()["bars"]
        tradier_row = None
        if tradier.tradier_configured():
            history = httpx.get(f"{tradier.TRADIER_BASE_URL}/v1/markets/history", headers={"Authorization": f"Bearer {tradier.TRADIER_API_KEY}", "Accept": "application/json"},
                                params={"symbol": symbol, "interval": "daily", "start": day.isoformat(), "end": day.isoformat()}, timeout=20).json()
            row = (history.get("history") or {}).get("day")
            tradier_row = row[0] if isinstance(row, list) else row
        minute_close = last_regular_close(day, [{"t": datetime.fromtimestamp(b["time"], timezone.utc).isoformat(), "c": b["close"]} for b in adjusted])
        raw_close = last_regular_close(day, raw)
        sessions[day.isoformat()] = {"alpaca_raw_minute_close": raw_close, "chart_adjusted_minute_close": minute_close,
                                     "alpaca_split_daily_close": reference[0]["c"] if reference else None,
                                     "tradier_daily_close": float(tradier_row["close"]) if tradier_row else None}
        # Minute close at 15:59 vs the daily official close differ slightly; a few percent still separates raw from adjusted by 10x.
        agree = reference and abs(minute_close / reference[0]["c"] - 1) < 0.01
        if tradier_row:
            agree = agree and abs(minute_close / float(tradier_row["close"]) - 1) < 0.01
        ok = ok and bool(agree)
    print(json.dumps({**report, "sessions": sessions, "ok": ok}, indent=1))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
