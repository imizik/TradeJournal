"""Display-only consolidated Alpaca data for an unavailable Tradier chart feed."""

from datetime import date, datetime, time as wall_time, timedelta
from urllib.parse import quote

from app.engine.chart_adjust import BASIS, describe, suspect_gaps
from app.engine.chart_feed import ChartFeed, ChartFeedError, _number, chart_feed
from app.engine.chart_math import ET, chart_bars, daily_page, market_day, normalize_bars

PROVIDER = "Alpaca SIP"
SOURCE = "alpaca_sip"
FIRST_DAY = date(2016, 1, 1)
DELAY = timedelta(minutes=16)
feed = ChartFeed(use_alpaca=True)


def _timestamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Expected a time zone")
    return stamp


def _bars(symbol: str, start: datetime, end: datetime, *, daily: bool):
    path = f"/v2/stocks/{quote(symbol, safe='')}/bars"
    data, fetched, issue = feed.read(path, {
        "timeframe": "1Day" if daily else "1Min",
        "start": start.isoformat(), "end": end.isoformat(),
        "feed": "sip", "adjustment": "split" if daily else "raw", "limit": 10000,
    }, 86400 if daily else 15)
    rows = []
    try:
        if data.get("next_page_token") or data.get("symbol") != symbol:
            raise ValueError("Unexpected bars response")
        for raw in data.get("bars") or []:
            stamp = _timestamp(raw["t"])
            if start <= stamp < end:
                rows.append({"timestamp": int(stamp.timestamp()), "date": stamp.astimezone(ET).date().isoformat(),
                             "open": raw["o"], "high": raw["h"], "low": raw["l"], "close": raw["c"], "volume": raw["v"]})
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ChartFeedError("Alpaca returned unexpected chart bars.") from None
    return normalize_bars(rows, daily=daily, source=SOURCE), fetched, issue


def _daily(symbol: str, today: date):
    return _bars(symbol, datetime.combine(FIRST_DAY, wall_time(), ET),
                 datetime.combine(today - timedelta(days=1), wall_time(20), ET), daily=True)


def _quotes(symbols: list[str], today: date):
    from app.engine.chart_indices import is_index

    payload, fetched, issue = feed.read("/v2/stocks/snapshots", {
        "symbols": ",".join(sorted({symbol for symbol in symbols if not is_index(symbol)})), "feed": "delayed_sip",
    }, 15)
    rows = []
    for symbol, snapshot in payload.items():
        try:
            trade = snapshot["latestTrade"]
            stamp = _timestamp(trade["t"])
            daily = snapshot.get("dailyBar") or {}
            previous = snapshot.get("prevDailyBar") or {}
            current_day = bool(daily.get("t") and _timestamp(daily["t"]).astimezone(ET).date() == today)
            last = _number(trade["p"])
            # Before the open, today's daily bar can still be yesterday's final bar.
            prior_close = _number(previous.get("c") if current_day or stamp.astimezone(ET).date() != today else daily.get("c"))
            change = last - prior_close if last is not None and prior_close else None
            rows.append({"symbol": symbol, "name": symbol, "source": PROVIDER, "last": last,
                         "trade_time": int(stamp.timestamp()), "previous_close": prior_close,
                         "regular_close": _number(daily.get("c")) if current_day else None,
                         "change": change, "change_percentage": 100 * change / prior_close if change is not None else None,
                         "volume": _number(daily.get("v")) if current_day else None})
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            continue
    return rows, fetched, issue


def workspace(symbol: str, intervals: list[str], watchlist: list[str], session: str, *, calendar, quotes: bool) -> dict:
    now = datetime.now(ET)
    today = now.date()
    hours = calendar.hours(today)
    fetched = {}
    issues = []
    minutes, daily, rows = [], [], []

    def read(name, get):
        try:
            values, fetched[name], issue = get()
        except ChartFeedError as exc:
            issues.append(str(exc))
            return []
        if issue:
            issues.append(issue)
        return values

    if any(interval not in ("1D", "1W") for interval in intervals):
        start = datetime.combine(today, wall_time(4), ET)
        end = min(datetime.combine(today, wall_time(20), ET), now.replace(second=0, microsecond=0) - DELAY)
        if end > start:
            minutes = read("intraday", lambda: _bars(symbol, start, end, daily=False))
    if any(interval in ("1D", "1W") for interval in intervals):
        daily = read("daily", lambda: _daily(symbol, today))
    if quotes:
        rows = read("quotes", lambda: _quotes([symbol, *watchlist], today))
    if not minutes and not daily and issues:
        raise ChartFeedError(issues[0])

    info = chart_feed.splits.get(symbol)
    panels = {interval: {"bars": chart_bars(minutes, daily, interval, session, {today: hours})[-1200:],
                         "markers": []} for interval in intervals}
    return {"symbol": symbol, "provider": PROVIDER, "session": session, "delayed": True,
            "refresh_seconds": 15, "checked_at": int(now.timestamp()), "fetched_at": fetched,
            "panels": panels, "quotes": rows, "issues": list(dict.fromkeys(issues)),
            "intraday_as_of": minutes[-1]["time"] if minutes else None, "market": market_day(today, hours),
            "adjustment": describe(info, suspects=suspect_gaps(daily)),
            "history_note": "Alpaca consolidated SIP fallback. Intraday prices and watchlist updates are about 15 minutes delayed. Daily and weekly candles use completed sessions, split-adjusted only. Automatic levels and options overlays require the regular chart feed."}


def workspace_or_fallback(symbol, frames, watchlist, session, *, calendar, quotes=True, **kwargs):
    """Try the normal workspace first. Preserve useful primary data if fallback also fails."""
    from app.engine import alpaca
    from app.engine.chart_indices import is_index

    primary = None
    error = None
    try:
        primary = chart_feed.workspace(symbol, frames, watchlist, session, calendar=calendar, quotes=quotes, **kwargs)
    except ChartFeedError as exc:
        error = exc
    if not is_index(symbol) and alpaca.alpaca_configured() and (primary is None or primary.get("issues")):
        try:
            fallback = workspace(symbol, frames, watchlist, session, calendar=calendar, quotes=quotes)
            if primary is None or all(not panel["bars"] or fallback["panels"][frame]["bars"]
                                      for frame, panel in primary["panels"].items()):
                return fallback
        except ChartFeedError:
            pass
    if error is not None:
        raise error
    return primary


def page(symbol: str, interval: str, before: int, limit: int) -> dict:
    bars, _, issue = _daily(symbol, datetime.now(ET).date())
    if issue:
        raise ChartFeedError(issue)
    page_bars, cursor, exhausted = daily_page(chart_bars([], bars, interval, "regular"), before, limit)
    return {"symbol": symbol, "interval": interval, "before": before, "limit": limit, "bars": page_bars,
            "older_cursor": cursor, "exhausted": exhausted, "continuation": None, "warmup": "ready",
            "source": SOURCE, "price_basis": BASIS, "issue": None,
            "history_start": datetime.fromtimestamp(bars[0]["time"], ET).date().isoformat() if bars else None,
            "adjustment": describe(chart_feed.splits.get(symbol), suspects=suspect_gaps(page_bars))}
