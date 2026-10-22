"""Two explicit macro instruments, using the existing chart feed's bounded GETs.

TNX is quoted at ten times yield percent. Never infer the scale from magnitude.
Index bars have no traded volume, stock sessions, splits or executable prices.
"""

from datetime import date, datetime, time as wall_time, timedelta

from app.engine.chart_daily import conflicting_days, history_rows
from app.engine.chart_math import ET, daily_page, indicators, normalize_bars

INSTRUMENTS = {
    "VIX": {"provider_symbol": "VIX", "name": "Cboe Volatility Index", "unit": "index_points", "scale": 1.0},
    "US10Y": {"provider_symbol": "TNX:CGI", "name": "Cboe 10-year Treasury yield (TNX / 10)", "unit": "percent", "scale": 0.1},
}
INTERVALS = ("4h", "1D")
INTRADAY_DAYS = 20  # a bounded recent window; never fall through to Alpaca stocks


def is_index(symbol: str) -> bool:
    return symbol in INSTRUMENTS


def provider_symbol(symbol: str) -> str:
    return INSTRUMENTS.get(symbol, {}).get("provider_symbol", symbol)


def index_quote(row: dict) -> dict:
    """Normalize an already serialized chart quote; retain the provider timestamp."""
    symbol = next((s for s, meta in INSTRUMENTS.items() if meta["provider_symbol"] == row["symbol"]), None)
    if symbol is None:
        return row
    meta = INSTRUMENTS[symbol]
    out = {**row, "symbol": symbol, "name": meta["name"], "instrument_type": "index",
           "unit": meta["unit"], "provider_symbol": meta["provider_symbol"], "volume": None}
    for key in ("last", "change", "previous_close", "regular_close", "day_high", "day_low", "week_52_high", "week_52_low"):
        if out.get(key) is not None:
            out[key] *= meta["scale"]
    if out.get("last") is not None and out.get("previous_close") is not None:
        out["change"] = out["last"] - out["previous_close"]
        out["change_percentage"] = out["change"] / out["previous_close"] * 100 if out["previous_close"] else None
    out["change_bps"] = out["change"] * 100 if symbol == "US10Y" and out.get("change") is not None else None
    return out


def normalize_index(rows: list[dict], symbol: str, daily: bool) -> tuple[list[dict], list[str]]:
    # A zero placeholder satisfies the common candle shape; the instrument
    # capability explicitly suppresses volume and volume-weighted studies.
    prepared = [{**row, "volume": 0} for row in rows]
    conflicts = conflicting_days(prepared) if daily else set()
    bars = normalize_bars(prepared, daily=daily)
    bars = [b for b in bars if datetime.fromtimestamp(b["time"], ET).date() not in conflicts]
    scale = INSTRUMENTS[symbol]["scale"]
    for bar in bars:
        for key in ("open", "high", "low", "close"):
            bar[key] *= scale
        if daily:
            day = datetime.fromtimestamp(bar["time"], ET).date()
            bar["time"] = int(datetime.combine(day, wall_time(), ET).timestamp())
            bar["end_time"] = int(datetime.combine(day + timedelta(days=1), wall_time(), ET).timestamp())
        else:
            bar["end_time"] = bar["time"] + 15 * 60
    rejected = len(rows) - len(bars)
    kept = {datetime.fromtimestamp(b["time"], ET).date().isoformat() for b in bars}
    missing = sorted({str(r.get("date")) for r in rows if r.get("date") and str(r.get("date")) not in kept}) if daily else []
    detail = f" Dates: {', '.join(missing[:10])}." if missing else ""
    issues = [f"{rejected} invalid, conflicting or duplicate index row(s) omitted; no missing prices were filled.{detail}"] if rejected else []
    return bars, issues


def index_bars(bars: list[dict], interval: str) -> list[dict]:
    """4h clock buckets anchored at New York midnight, retaining provider hours.

    No NYSE pre/RTH/post clipping: VIX and TNX have different observation hours.
    Missing source intervals stay missing. Daily OHLC comes from daily history.
    """
    if interval == "1D":
        return indicators([{**b, "extended": False, "vwap": None, "vwap_sd": None} for b in bars])
    groups = {}
    for b in bars:
        dt = datetime.fromtimestamp(b["time"], ET)
        start = dt.replace(hour=(dt.hour // 4) * 4, minute=0, second=0, microsecond=0)
        stamp = int(start.timestamp())
        if stamp not in groups:
            groups[stamp] = {**b, "time": stamp, "end_time": int((start + timedelta(hours=4)).timestamp()),
                             "extended": False, "vwap": None, "vwap_sd": None, "observed_at": b["time"]}
        else:
            groups[stamp].update(high=max(groups[stamp]["high"], b["high"]), low=min(groups[stamp]["low"], b["low"]), close=b["close"], observed_at=b["time"])
    return indicators(list(groups.values()))


class ChartIndices:
    def __init__(self, feed):
        self.feed = feed

    def series(self, symbol: str, interval: str) -> tuple[list[dict], dict, list[str]]:
        from app.engine.chart_feed import ChartFeedError, _rows

        if interval not in INTERVALS:
            raise ChartFeedError("VIX and US10Y support 4h and 1D charts.", "invalid_request")
        today = datetime.now(ET).date()
        ticker = provider_symbol(symbol)
        issues, fetched = [], {}

        def read(name, path, params, ttl):
            payload, at, issue = self.feed.read(path, params, ttl)
            fetched[name] = at
            if issue:
                issues.append(issue)
            return payload

        if interval == "1D":
            completed = read("daily_history", "/v1/markets/history", {
                "symbol": ticker, "interval": "daily", "start": "1970-01-01", "end": (today - timedelta(days=1)).isoformat(),
            }, 86400)
            tail = read("daily", "/v1/markets/history", {
                "symbol": ticker, "interval": "daily", "start": (today - timedelta(days=10)).isoformat(), "end": today.isoformat(),
            }, 60)
            # Tail wins by date, including a malformed replacement: it must not
            # silently resurrect a superseded historical value.
            rows = {row.get("date"): row for row in history_rows(completed)}
            tail_rows = history_rows(tail)
            for row in tail_rows:
                rows[row.get("date")] = row
            raw = list(rows.values())
            # Retain conflicting duplicate dates from either provider response.
            tail_dates = set()
            for row in tail_rows:
                try:
                    tail_dates.add(date.fromisoformat(row.get("date", "")))
                except (ValueError, TypeError):
                    pass
            conflicts = (conflicting_days([{**r, "volume": 0} for r in history_rows(completed)]) - tail_dates) | conflicting_days([{**r, "volume": 0} for r in tail_rows])
            raw = [r for r in raw if str(r.get("date")) not in {d.isoformat() for d in conflicts}]
            if conflicts:
                issues.append(f"Conflicting index dates omitted: {', '.join(sorted(d.isoformat() for d in conflicts))}.")
        else:
            payload = read("intraday", "/v1/markets/timesales", {
                "symbol": ticker, "interval": "15min", "session_filter": "all",
                "start": (today - timedelta(days=INTRADAY_DAYS)).strftime("%Y-%m-%d 00:00"),
                "end": today.strftime("%Y-%m-%d 23:59"),
            }, 60)
            raw = _rows(payload, "series", "data")
        bars, rejected = normalize_index(raw, symbol, interval == "1D")
        if not bars:
            issues.append(f"No {interval} index observations available from Tradier.")
        return index_bars(bars, interval), fetched, list(dict.fromkeys(issues + rejected))

    @staticmethod
    def adjustment() -> dict:
        return {"basis": "index_native", "status": "ok", "source": "Tradier index values", "as_of": None,
                "splits": [], "daily": {}, "dividends": "unsupported", "dividends_note": "Not applicable to an index.", "warnings": []}

    def workspace(self, symbol: str, intervals: list[str], watchlist: list[str], session: str, quotes: bool) -> dict:
        from app.engine import tradier
        from app.engine.chart_feed import ChartFeedError
        import time

        panels, fetched, issues = {}, {}, []
        for interval in intervals:
            if interval not in INTERVALS:
                panels[interval] = {"bars": [], "markers": []}
                issues.append("VIX and US10Y support 4h and 1D charts.")
                continue
            try:
                bars, stamps, notes = self.series(symbol, interval)
                panels[interval] = {"bars": bars[-1200:], "markers": []}
                fetched.update(stamps)
                issues.extend(notes)
            except ChartFeedError as exc:
                panels[interval] = {"bars": [], "markers": []}
                issues.append(str(exc))
        try:
            rows, quote_stamp, quote_issue = self.feed.quote_rows([symbol, *watchlist]) if quotes else ([], None, None)
        except ChartFeedError as exc:
            rows, quote_stamp, quote_issue = [], None, str(exc)
        if quote_stamp:
            fetched["quotes"] = quote_stamp
        if quote_issue:
            issues.append(quote_issue)
        last = max((b["observed_at"] for p in panels.values() for b in p["bars"] if "observed_at" in b), default=None)
        return {"symbol": symbol, "provider": "Tradier", "session": session, "delayed": "sandbox" in tradier.TRADIER_BASE_URL,
                "refresh_seconds": 60, "checked_at": int(time.time()), "fetched_at": fetched, "panels": panels, "quotes": rows,
                "issues": list(dict.fromkeys(issues)), "intraday_as_of": last, "instrument": {"kind": "index", **INSTRUMENTS[symbol]},
                "market": {"date": datetime.now(ET).date().isoformat(), "status": "unknown", "source": "index", "description": None, "sessions": [], "note": None},
                "adjustment": self.adjustment(), "auto_levels": None, "rvol": None,
                "history_note": "Tradier index observations; no traded volume or split adjustment. 4h candles use 15-minute observations in clock buckets starting at New York midnight, including provider hours. Recent intraday history is limited by the provider; no missing intervals are filled. EMA/RSI use available valid bars. US10Y is Cboe TNX divided by 10, in yield percent."}

    def page(self, symbol: str, interval: str, before: int, limit: int, session: str) -> dict:
        bars, _, issues = self.series(symbol, interval)
        page, older, exhausted = daily_page(bars, before, limit)
        return {"symbol": symbol, "interval": interval, "session": session, "before": before, "limit": limit, "bars": page,
                "older_cursor": older, "exhausted": exhausted, "continuation": None, "warmup": "ready", "source": "tradier",
                "price_basis": "index_native", "issue": None, "history_start": datetime.fromtimestamp(bars[0]["time"], ET).date().isoformat() if bars else None,
                "adjustment": {**self.adjustment(), "warnings": issues}, "calendar_note": "Index observations; 4h buckets start at New York midnight. Available history only."}
