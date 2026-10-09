"""Isolated sample-data entry point; never imported by production app.main.

Run only on the separately copied runtime and seeded SQLite installation.
Authentication stays outside the fixture middleware. External networking is
also blocked by the trial's systemd units.
"""
from datetime import datetime, timedelta
import math
import os
from pathlib import Path
import sqlite3

from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

ROOT = Path("/var/lib/tradejournal-dot-trial")
SOURCE = "Sample fixture (not live)"
NOTICE = "Simulated prices for the UI trial; never use these for trading."
BASES = {"SPY": 500, "QQQ": 430, "IWM": 210, "NVDA": 130, "AAPL": 220,
         "TSLA": 250, "RNXT": 1, "RCAT": 10, "MU": 110, "NBIS": 60}
OFF_FLAGS = ("GMAIL_WATCH_AUTOSTART", "GMAIL_LISTENER_ENABLED", "WEBULL_LISTENER_AUTOSTART",
             "LEVEL_ALERTS_AUTOSTART", "PRACTICE_AGENT_ENABLED", "PRACTICE_SCHEDULE_ENABLED")
SECRET_FLAGS = ("TRADIER_API_KEY", "ALPACA_API_KEY", "ALPACA_API_SECRET", "POLYGON_API_KEY",
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "WEBULL_USERNAME", "WEBULL_PASSWORD", "NTFY_URL")


def validate_environment(env, root=ROOT):
    expected = root / "data/trial.db"
    if (env.get("TJ_DOT_TRIAL_ENABLED") != "true" or env.get("TJ_ACCESS_ENABLED") != "true"
            or env.get("TJ_ACCESS_SAMPLE_DATA") != "true"
            or env.get("DATABASE_URL") != f"sqlite:///{expected}"
            or env.get("MIGRATION_DATABASE_URL") != f"sqlite:///{expected}"
            or env.get("JOB_EXECUTION_MODE") != "external"
            or any(env.get(name) != "false" for name in OFF_FLAGS)
            or any(env.get(name) for name in SECRET_FLAGS)
            or expected.is_symlink() or expected.resolve() != expected
            or not (root / ".sample-installation").is_file()):
        raise RuntimeError("Dot trial refuses a non-isolated or integration-enabled installation")
    with sqlite3.connect(f"file:{expected}?mode=ro", uri=True) as db:
        count, foreign = db.execute("SELECT COUNT(*), SUM(CASE WHEN raw_email_id IS NULL OR raw_email_id NOT LIKE 'seed:%' THEN 1 ELSE 0 END) FROM fill").fetchone()
    if not count or foreign:
        raise RuntimeError("Dot trial requires exclusively seeded sample fills")


def candles(symbol, interval, before=None, limit=120):
    from app.engine.chart_math import ET
    step = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1D": 86400, "1W": 604800}[interval]
    anchor = datetime.now(ET).replace(hour=16, minute=0, second=0, microsecond=0)
    while anchor.weekday() >= 5:
        anchor -= timedelta(days=1)
    finish = min(int(anchor.timestamp()), before - step) if before else int(anchor.timestamp())
    base = BASES.get(symbol, 100)
    rows = []
    for i in range(min(limit, 120)):
        stamp = finish - (min(limit, 120) - i) * step
        opening = round(base * (1 + 0.0002 * i + 0.002 * math.sin(i / 5)), 4)
        close = round(opening + base * 0.0005 * math.sin(i / 3), 4)
        rows.append({"time": stamp, "end_time": stamp + step, "open": opening,
                     "high": round(max(opening, close) + base * 0.001, 4),
                     "low": round(min(opening, close) - base * 0.001, 4), "close": close,
                     "volume": 1000 + i * 20, "extended": False, "source": SOURCE})
    return rows


def workspace(query):
    symbol = query.get("symbol", "SPY").upper()
    frames = query.get("intervals", "5m,15m,1h,1D,1m").split(",")
    stamp = int(datetime.now().timestamp())
    watchlist = query.get("watchlist", symbol).split(",")
    def panels(name, intervals):
        return {frame: {"bars": candles(name, frame), "markers": []} for frame in intervals}
    extras = {}
    for value in filter(None, query.get("extras", "").split(",")):
        name, _, intervals = value.partition(":")
        extras[name] = {"panels": panels(name, intervals.split(".")), "fetched_at": {"intraday": stamp},
                        "intraday_as_of": stamp, "issues": [NOTICE], "positions": [], "fills_truncated": False}
    return {"symbol": symbol, "session": query.get("session", "extended"), "provider": SOURCE,
            "delayed": True, "refresh_seconds": 60, "checked_at": stamp,
            "fetched_at": {"intraday": stamp, "quotes": stamp}, "intraday_as_of": stamp,
            "issues": [NOTICE], "history_note": NOTICE,
            "quotes": [{"symbol": name, "name": f"{name} · sample", "instrument_type": "stock",
                        "last": BASES.get(name, 100), "previous_close": BASES.get(name, 100),
                        "change": 0, "change_percentage": 0, "volume": 100000, "trade_time": stamp}
                       for name in watchlist],
            "panels": panels(symbol, frames), "extras": extras, "fills": [],
            "fills_truncated": False, "positions": [], "alerts": {"alerts": []},
            "auto_levels": None, "rvol": None, "adjustment": None}


def market_response(request):
    path, query = request.url.path, request.query_params
    if path == "/charts/workspace":
        return workspace(query)
    if path == "/charts/history":
        return {"symbol": query["symbol"], "interval": query["interval"], "session": query["session"],
                "provider": SOURCE, "bars": candles(query["symbol"], query["interval"], int(query["before"]), int(query.get("limit", 120))),
                "markers": [], "fills_truncated": False, "next_before": None, "has_more": False, "issues": [NOTICE]}
    if path == "/charts/stream":
        return JSONResponse({"detail": "Sample trial has static fixture prices, no live stream"}, 503)
    if path == "/quotes":
        return {name: BASES.get(name, 100) for name in query.get("tickers", "").split(",") if name}
    if path == "/quotes/positions":
        return []
    if path.startswith("/charts/symbol/") and not path.endswith("/you"):
        symbol, section = path[len("/charts/symbol/"):].rsplit("/", 1)
        common = {"symbol": symbol, "state": "unavailable", "source": SOURCE, "fetched_at": None, "message": NOTICE}
        if section == "overview":
            return {**common, "datasets": {key: {**common, "name": None} for key in ("company", "ratios", "statistics")}}
        if section == "news":
            return {"symbol": symbol, "as_of": None, "time_zone": "America/New_York", "days": 7,
                    "sentiment_note": NOTICE, "articles": [], "sources": []}
        if section == "events":
            return {**common, "next": None, "reports": [], "dividends": [], "splits": []}
        if section == "peers":
            return {**common, "as_of": None, "quotes": common, "peers": []}
        if section == "reactions":
            return {**common, "rows": [], "usable_count": 0, "average_abs_pct": None, "report_range": None}
        return JSONResponse({"detail": NOTICE}, 503)
    if path.startswith("/charts/options/") or path.startswith("/market-context/") or path.endswith("/mark"):
        return JSONResponse({"detail": NOTICE}, 503)
    if path == "/packets/analyze":
        return {"symbol": query.get("symbol"), "data_source": SOURCE, "missing": [NOTICE],
                "recent_minute_bars": [], "recent_daily_bars": [], "generated_at": None}
    if path == "/packets/news":
        return {"window_start": None, "articles": [], "notice": NOTICE}
    return None


class FixtureMarket:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope)
            if request.method == "GET" or (request.method == "POST" and request.url.path == "/quotes/positions"):
                try:
                    data = market_response(request)
                except (ValueError, KeyError):
                    data = JSONResponse({"detail": "Invalid sample-data request"}, 422)
                if data is not None:
                    response = data if isinstance(data, JSONResponse) else JSONResponse(data)
                    return await response(scope, receive, send)
        await self.app(scope, receive, send)


def build_app():
    validate_environment(os.environ)
    from app.main import app
    from app.access_middleware import AccessMiddleware
    # Fixture replies must never sit outside the real authentication boundary.
    if not app.user_middleware or app.user_middleware[0].cls is not AccessMiddleware:
        raise RuntimeError("Dot trial authentication middleware order changed")
    app.user_middleware.insert(1, Middleware(FixtureMarket))
    return app
