"""Provider-shaped browser fixture only. Not shipped to the VPS runtime."""
from datetime import datetime, timedelta, timezone
import uuid

from app.engine import market_practice
from app.engine.chart_math import ET


def prepare(db):
    now = datetime.now(timezone.utc)
    day = now.astimezone(ET).date()
    packets = {}
    for symbol, price in (("MU", 110), ("NBIS", 60)):
        bars = []
        for i in range(60):
            at = now.replace(second=0, microsecond=0) - timedelta(minutes=i + 1)
            if at.astimezone(ET).date() == day:
                bars.append({"t": at.isoformat(), "o": price, "h": price + 2, "l": price - 1,
                    "c": price, "v": 100 + i, "vw": price - .1})
        packets[symbol] = {"symbol": symbol, "data_source": "alpaca_iex", "recent_minute_bars": bars,
            "missing": ["Provider-shaped browser fixture; not a provider observation"]}
    return market_practice.prepare(db, {"version": 1, "day": day.isoformat(), "captured_at": now.isoformat(),
        "calendar": {"status": "open", "open": 0, "close": 1440, "source": "alpaca_calendar"}, "packets": packets},
        identifier="market-browser-" + uuid.uuid4().hex[:10], proof=True)
