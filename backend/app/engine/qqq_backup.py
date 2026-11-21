"""Alpaca backup reads for the QQQ paper books (``overnight_book``, ``intraday_momentum_book``) when Tradier fails.

The books ask Tradier first and come here only when its call fails or gives nothing usable, so a day Tradier is fine
costs no Alpaca request. Every read names its own feed and never inherits ``ALPACA_DATA_FEED`` (production may set it
to ``sip``, which the free plan delays by about 15 minutes):

- ``quote``: the latest IEX quote (real time on the free plan), returned in Tradier's shape with the quote's one
  timestamp as both the bid and the ask stamp, so the books apply their own freshness rule unchanged. IEX's own top of
  book is never better than the national best bid and offer, so a backup fill is at worst a little more costly.
- ``minutes``: one day's regular-session minute bars from 09:30, IEX for a live check (the decision bar is real time;
  its volume is IEX's own, so the VWAP is an IEX VWAP) or SIP for a finished session (the same consolidated bars the
  book's seed holds, available once the 15-minute delay has passed).
- ``previous_close``: the last SIP daily bar before a day (day and close), for the momentum band's anchor.

Each read is one request on Alpaca's short budget (no retry, no sleep) and returns None on any failure or an
unexpected shape; it never raises into the monitor loop.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from urllib.parse import quote as url_quote

from app.engine import alpaca
from app.engine.chart_math import ET, normalize_bars
from app.engine.tradier import TradierQuote

log = logging.getLogger(__name__)

SOURCE = "alpaca_iex"  # what a book records for a fill priced from this backup
SIGNAL_SOURCE = "alpaca"  # what a momentum check records when any of its inputs came from here


def _stamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Expected a time zone")
    return stamp


def _get(path: str, params: dict) -> dict | None:
    if not alpaca.alpaca_configured():
        return None
    try:
        data = alpaca._alpaca_get_fast(path, params)
    except Exception as exc:  # AlpacaFastFailure or anything unexpected: the caller treats it as no data
        log.warning("QQQ backup read failed (%s): %s", path, exc)
        return None
    return data if isinstance(data, dict) and data else None


def quote(symbol: str) -> TradierQuote | None:
    data = _get(f"/v2/stocks/{url_quote(symbol, safe='')}/quotes/latest", {"feed": "iex"})
    if data is None:
        return None
    try:
        raw = data["quote"]
        ms = int(_stamp(raw["t"]).timestamp() * 1000)
        return TradierQuote(symbol=symbol, bid=float(raw["bp"]), ask=float(raw["ap"]), bid_date=ms, ask_date=ms)
    except (KeyError, TypeError, ValueError, OverflowError):
        log.warning("QQQ backup quote came back unexpected")
        return None


def minutes(symbol: str, day: date, now: float, feed: str) -> list[dict] | None:
    """``day``'s minute bars from 09:30 up to ``now`` (16:00 at most), as ``normalize_bars`` leaves them."""
    start = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)
    end = min(datetime.fromtimestamp(now, ET), datetime(day.year, day.month, day.day, 16, 0, tzinfo=ET))
    if end <= start:
        return None
    data = _get(f"/v2/stocks/{url_quote(symbol, safe='')}/bars", {
        "timeframe": "1Min", "start": start.isoformat(), "end": end.isoformat(), "feed": feed,
        "adjustment": "raw", "limit": 10000})
    if data is None or data.get("next_page_token"):
        return None
    try:
        rows = [{"timestamp": int(_stamp(b["t"]).timestamp()), "open": b["o"], "high": b["h"], "low": b["l"],
                 "close": b["c"], "volume": b["v"]} for b in data.get("bars") or []]
    except (KeyError, TypeError, ValueError, OverflowError):
        log.warning("QQQ backup bars came back unexpected")
        return None
    return normalize_bars(rows, source=f"alpaca_{feed}") or None


def previous_close(symbol: str, day: date) -> tuple[date, float] | None:
    """The last SIP daily bar dated before ``day``: (its New York date, its close)."""
    data = _get(f"/v2/stocks/{url_quote(symbol, safe='')}/bars", {
        "timeframe": "1Day", "start": datetime.combine(day - timedelta(days=10), datetime.min.time(), ET).isoformat(),
        "end": datetime.combine(day, datetime.min.time(), ET).isoformat(), "feed": "sip", "adjustment": "raw",
        "limit": 50})
    if data is None:
        return None
    best: tuple[date, float] | None = None
    try:
        for b in data.get("bars") or []:
            d, close = _stamp(b["t"]).astimezone(ET).date(), float(b["c"])
            if d < day and close > 0 and (best is None or d > best[0]):
                best = (d, close)
    except (KeyError, TypeError, ValueError, OverflowError):
        log.warning("QQQ backup daily bars came back unexpected")
        return None
    return best
