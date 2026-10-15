"""Explicit, labelled email -> Jo -> phone diagnostic. Never creates a trade."""

import argparse
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import uuid

from sqlmodel import Session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["delivery-diagnostic"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--code", required=True)
    args = parser.parse_args()
    from app.database import engine
    from app.engine.scanner_settings import read_settings
    from app.engine.stock_watch import StockWatcher, packet
    from app.engine.market_watch_wakes import MarketWatchWakeStore

    with Session(engine) as db:
        selection = read_settings(db)
    if args.symbol not in selection["symbols"]:
        parser.error("Diagnostic ticker must be in the explicitly saved selection")
    paths = [
        os.environ.get(k, "")
        for k in (
            "MARKET_WATCH_STORE",
            "MARKET_WATCH_SNAPSHOTS_DIR",
            "MARKET_WATCH_OUTBOX_DIR",
        )
    ]
    if not all(p and Path(p).is_absolute() for p in paths):
        parser.error(
            "Require the existing explicit stock-watch publication/store/outbox paths"
        )
    now = datetime.now(UTC)
    observed = now.replace(second=0, microsecond=0)
    bars = [
        {
            "time": (observed - timedelta(minutes=i + 1)).timestamp(),
            "end_time": (observed - timedelta(minutes=i)).timestamp(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        }
        for i in reversed(range(16))
    ]
    alert_id = "sta_" + str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"stock-diagnostic:{now.date()}:{args.code}")
    )
    alert = packet(
        args.symbol,
        "diagnostic",
        "up",
        bars,
        observed,
        now,
        selection,
        {
            "purpose": "Delivery diagnostic with invented flat prices; no market recommendation."
        },
        alert_id=alert_id,
        code=args.code,
    )
    watcher = StockWatcher(MarketWatchWakeStore(paths[0]), paths[1], paths[2])
    result = watcher.capture(alert)
    print(
        __import__("json").dumps(
            {
                "alert_id": result["alert_id"],
                "diagnostic_code": result["diagnostic_code"],
                "expires_at": result["expires_at"],
                "purpose": "delivery_diagnostic",
                "trade_created": False,
            }
        )
    )


if __name__ == "__main__":
    main()
