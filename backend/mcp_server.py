"""
MCP server for the Trade Journal — stdio transport, for Claude Desktop.

Thin adapter: every tool is an HTTP call to the local FastAPI backend, which
holds all API keys and business logic. This process needs no secrets.

Run (Claude Desktop launches it via claude_desktop_config.json):
    python mcp_server.py

Config entry (claude_desktop_config.json -> "mcpServers"):
    "trade-journal": {
      "command": "C:\\Users\\Owner\\TradeJournal\\backend\\venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\Owner\\TradeJournal\\backend\\mcp_server.py"]
    }

Requires the backend running on localhost:8000 (override: TRADE_JOURNAL_API).
"""

import json
import logging
import os
import time
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("TRADE_JOURNAL_API", "http://localhost:8000")
LOG_DIR = Path(__file__).resolve().parent / "data" / "mcp_log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("trade-journal-mcp")

mcp = FastMCP("trade-journal")


def _get(path: str, params: dict | None = None, timeout: float = 120.0) -> dict | list:
    started = time.monotonic()
    error = None
    response_bytes = None
    try:
        resp = httpx.get(f"{API_BASE}{path}", params=params, timeout=timeout)
        resp.raise_for_status()
        response_bytes = len(resp.content)
        result = resp.json()
        return result
    except httpx.ConnectError as exc:
        error = str(exc)
        raise RuntimeError(
            f"Cannot reach the trade journal backend at {API_BASE}. "
            "Is uvicorn running? (cd backend && uvicorn app.main:app --port 8000)"
        ) from exc
    except httpx.HTTPStatusError as exc:
        error = f"{exc.response.status_code}: {exc.response.text[:300]}"
        raise RuntimeError(f"Backend error on {path} — {error}") from exc
    finally:
        _log_call(path, params, error, time.monotonic() - started, response_bytes)


def _log_call(path: str, params: dict | None, error: str | None,
              duration_s: float, response_bytes: int | None = None) -> None:
    """Append one JSONL line per tool-backed request for auditability."""
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "path": path,
            "params": params,
            "duration_s": round(duration_s, 2),
            "response_bytes": response_bytes,
            "error": error,
        }
        logfile = LOG_DIR / f"{time.strftime('%Y-%m-%d')}.jsonl"
        with open(logfile, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        log.warning("Failed to write MCP log entry", exc_info=True)


@mcp.tool()
def get_market_report(report_type: str) -> dict:
    """Build a fresh, objective market report (pure data — you do the analysis).

    report_type: "premarket" or "postmarket".

    Returns indexes detail (VWAP, range structure, opening range, premarket and
    after-hours moves), sector rotation table, macro/risk gauges (incl. VIX and
    10Y), the user's high-beta execution universe bucketed with relative
    strength vs SPY, leaders/laggards, and raw news headlines. Check the
    `missing` and `confidence` fields before drawing conclusions; supplement
    macro/geopolitical context and the economic calendar via web search.
    Takes ~10-30 seconds to build.
    """
    return _get("/packets/report", {"type": report_type})


@mcp.tool()
def get_news(symbols: str | None = None, hours: int = 24, limit: int = 30,
             include_content: bool = False) -> dict:
    """Fetch raw financial headlines (Benzinga via Alpaca) for drill-down.

    symbols: comma-separated tickers (e.g. "NVDA,MU"); omit for the broad tape.
    hours: lookback window from now (1-168).
    include_content: True returns full article text (HTML-stripped, capped,
    max 10 articles) — use for targeted drill-down when a headline doesn't
    explain a big move, not for bulk scanning.
    """
    params: dict = {"hours": hours, "limit": limit, "include_content": include_content}
    if symbols:
        params["symbols"] = symbols
    return _get("/packets/news", params)


@mcp.tool()
def get_trades(start_date: str | None = None, end_date: str | None = None,
               status: str | None = None, ticker: str | None = None) -> list:
    """Fetch the user's trades from the journal (read-only).

    Dates are YYYY-MM-DD. status: "open", "closed", or "expired".
    """
    params = {k: v for k, v in {
        "start_date": start_date, "end_date": end_date,
        "status": status, "ticker": ticker,
    }.items() if v}
    return _get("/trades", params)


@mcp.tool()
def get_stats() -> dict:
    """Fetch aggregate journal stats: P/L, win rate, today's P/L, breakdowns
    by ticker / tag / time bucket, and behavioral flag counts (read-only)."""
    return _get("/stats")


if __name__ == "__main__":
    mcp.run()
