"""Chart-only calculations on supplied bars. Never changes journal enrichment.

Times are UTC seconds. Intraday buckets are anchored to New York sessions;
regular, premarket and postmarket bars never collapse into the same candle.
"""

from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
INTERVALS = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440, "1W": 10080}


def normalize_bars(rows: list[dict], *, daily: bool = False, source: str = "tradier") -> list[dict]:
    """Reject malformed OHLCV, sort and deduplicate by the provider timestamp."""
    result = {}
    for row in rows:
        try:
            if daily:
                dt = datetime.fromisoformat(row["date"]).replace(hour=9, minute=30, tzinfo=ET)
                stamp = int(dt.timestamp())
                end = int(dt.replace(hour=16, minute=0).timestamp())
            else:
                stamp = int(row["timestamp"])
                end = stamp + 60
            prices = {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}
            if not all(isfinite(v) for v in prices.values()):
                continue
            if min(prices[k] for k in ("open", "high", "low", "close")) <= 0 or prices["volume"] < 0:
                continue
            if prices["high"] < max(prices["open"], prices["close"], prices["low"]):
                continue
            if prices["low"] > min(prices["open"], prices["close"]):
                continue
            if stamp <= 0:
                continue
            result[stamp] = {"time": stamp, "end_time": end, "source": source, **prices}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [result[k] for k in sorted(result)]


def session_part(dt: datetime) -> tuple[str, int, int] | None:
    minute = dt.hour * 60 + dt.minute
    if dt.weekday() >= 5:
        return None
    if 240 <= minute < 570:
        return "pre", 240, 570
    if 570 <= minute < 960:
        return "regular", 570, 960
    if 960 <= minute < 1200:
        return "post", 960, 1200
    return None


def chart_bars(minutes: list[dict], daily: list[dict], interval: str, session: str) -> list[dict]:
    if interval == "1D":
        return indicators([{**b, "source": b.get("source", "tradier"), "extended": False, "vwap": None} for b in daily])
    if interval == "1W":
        groups: dict[int, dict] = {}
        for b in daily:
            dt = datetime.fromtimestamp(b["time"], ET)
            monday = dt - timedelta(days=dt.weekday())
            stamp = int(monday.timestamp())
            end = int((monday + timedelta(days=4)).replace(hour=16, minute=0).timestamp())
            _merge(groups, stamp, end, b, False, None)
        return indicators(list(groups.values()))

    width = INTERVALS[interval]
    groups = {}
    current_day = None
    pv = volume = 0.0
    for b in minutes:
        dt = datetime.fromtimestamp(b["time"], ET)
        part = session_part(dt)
        if part is None or (session == "regular" and part[0] != "regular"):
            continue
        if dt.date() != current_day:
            current_day, pv, volume = dt.date(), 0.0, 0.0
        # RTH VWAP is always based on minute HLC3, never on resampled candles.
        # It is absent outside RTH, so extended-hours volume cannot dilute it.
        vwap = None
        if part[0] == "regular":
            pv += (b["high"] + b["low"] + b["close"]) / 3 * b["volume"]
            volume += b["volume"]
            vwap = pv / volume if volume else None
        minute = dt.hour * 60 + dt.minute
        anchor = part[1] + ((minute - part[1]) // width) * width
        start = dt.replace(hour=anchor // 60, minute=anchor % 60, second=0, microsecond=0)
        finish = min(anchor + width, part[2])
        end = dt.replace(hour=finish // 60, minute=finish % 60, second=0, microsecond=0)
        _merge(groups, int(start.timestamp()), int(end.timestamp()), b, part[0] != "regular", vwap)
    return indicators(list(groups.values()))


def _merge(groups: dict, stamp: int, end: int, bar: dict, extended: bool, vwap: float | None):
    if stamp not in groups:
        groups[stamp] = {**bar, "source": bar.get("source", "tradier"), "time": stamp, "end_time": end, "extended": extended, "vwap": vwap}
    else:
        b = groups[stamp]
        b.update(high=max(b["high"], bar["high"]), low=min(b["low"], bar["low"]),
                 close=bar["close"], volume=b["volume"] + bar["volume"], vwap=vwap)


def indicators(bars: list[dict]) -> list[dict]:
    """First-close EMA, Wilder RSI(14); missing warmup remains missing."""
    emas: dict[int, float] = {}
    gains = losses = 0.0
    previous = None
    out = []
    for i, bar in enumerate(bars):
        close = bar["close"]
        row = dict(bar)
        for length in (9, 20, 50, 200):
            emas[length] = close if length not in emas else emas[length] + 2 / (length + 1) * (close - emas[length])
            row[f"ema{length}"] = emas[length] if i + 1 >= length else None
        rsi = None
        if previous is not None:
            gain, loss = max(close - previous, 0), max(previous - close, 0)
            if i <= 14:
                gains += gain / 14
                losses += loss / 14
            else:
                gains = (gains * 13 + gain) / 14
                losses = (losses * 13 + loss) / 14
            if i >= 14:
                rsi = 50.0 if gains == losses == 0 else 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
        row["rsi"] = rsi
        previous = close
        out.append(row)
    return out
