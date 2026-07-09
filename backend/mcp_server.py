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


def _get(path: str, params: dict | None = None, timeout: float = 120.0,
         allow_404: bool = False):
    started = time.monotonic()
    error = None
    response_bytes = None
    try:
        resp = httpx.get(f"{API_BASE}{path}", params=params, timeout=timeout)
        if allow_404 and resp.status_code == 404:
            return None
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


@mcp.tool()
def analyze_ticker(symbol: str) -> dict:
    """Live, on-demand analysis of ANY ticker (traded or not) as of the latest
    data — independent of the user's journal.

    Returns:
    - `current`: latest price, % change vs prev close, today's O/H/L/volume.
    - `short_term`: intraday read — VWAP and distance from it, opening range
      (5m/15m), premarket levels, day high/low and where price sits in the range.
      Falls back to the last completed session when the market is closed.
    - `long_term`: daily/investment read — SMA 20/50/200 and % distance from
      each, EMA 9/20, RSI-14, ATR-14, MACD, 52-week high/low and distance, and
      1/3/6-month returns.
    - `recent_daily_bars` / `recent_minute_bars`: the last ~30 of each for your
      own checks.

    Use this for "analyze APLD / any ticker right now" — size it up as a short-to-
    mid-term trade AND as a longer-term investment. This returns data only; you
    form the verdict. Note: the free Alpaca feed is IEX (thinner than full SIP),
    so treat pre/post-market and illiquid names as approximate.
    """
    return _get("/packets/analyze", {"symbol": symbol}, timeout=60.0)


@mcp.tool()
def analyze_scalp(symbol: str, direction: str | None = None,
                  instrument: str | None = None, option_type: str | None = None,
                  expiration: str | None = None, strike: float | None = None,
                  style: str | None = None) -> dict:
    """Read-only scalp decision support: "should I scalp X right now?",
    "should I buy intraday calls at the open?", "is this VWAP reclaim real?".

    Returns `assessment` (deterministic verdict + scores + plan) and `data`
    (the raw packet the scores were computed from). Never places trades.

    Args:
    - direction: "long"/"up" or "short"/"down"; omit to evaluate both sides.
    - instrument: "stock" or "option". Passing option_type/expiration/strike
      implies "option"; with no expiration/strike the nearest-expiry contract
      closest to the money is auto-selected.
    - option_type: "call" or "put" (derived from direction if omitted).
    - expiration: YYYY-MM-DD. strike: contract strike.
    - style: "open" | "midday" | "power_hour" (derived from clock if omitted).

    assessment.verdict is "no_trade" / "wait" / "long_scalp" / "short_scalp"
    with confidence, bias (bullish/bearish/mixed/chop), setup_score,
    liquidity_score, risk_score (higher = riskier), a level-based trigger /
    invalidation / targets plan, reasons_for/against, and missing-data
    caveats. Hard rules baked in: closed market or stale data => wait/no_trade;
    option spread over 10% of mid => reject; inside VWAP/opening-range band on
    weak RVOL => chop; extra strict in the first 5-15 minutes.

    You write the narrative: relay the verdict WITH its reasons and caveats,
    triage the raw `data.news` headlines yourself (the scorer only counts
    them), and never present this as guaranteed advice or an order to place.
    Uses the free IEX feed — treat thin names and pre/post-market as
    approximate. Takes a few seconds (live Alpaca calls).
    """
    params: dict = {k: v for k, v in {
        "symbol": symbol, "direction": direction, "instrument": instrument,
        "option_type": option_type, "expiration": expiration,
        "strike": strike, "style": style,
    }.items() if v is not None}
    return _get("/packets/scalp", params, timeout=90.0)


@mcp.tool()
def get_trade_detail(trade_id: str) -> dict:
    """Full end-to-end bundle for a single trade (read-only).

    Combines the trade record, its fills (each with the Alpaca market context
    inlined as `market_context`), and path metrics (MFE/MAE, exit efficiency,
    giveback, post-exit continuation). Use this to analyze one trade in depth.
    `path_metrics` is null if the Path Metrics job has not run for this trade.

    trade_id: a trade UUID (from get_trades / get_trade_path_metrics).
    """
    trade = _get(f"/trades/{trade_id}")
    fills = _get(f"/trades/{trade_id}/fills") or []
    fill_ids = [f["id"] for f in fills]
    ctx_map = _get("/market-context/fills/bulk", {"ids": ",".join(fill_ids)}) if fill_ids else {}
    for f in fills:
        f["market_context"] = ctx_map.get(f["id"])
    path = _get(f"/market-context/trade/{trade_id}", allow_404=True)
    return {"trade": trade, "fills": fills, "path_metrics": path}


@mcp.tool()
def get_coverage() -> dict:
    """Enrichment coverage counts (read-only): how many fills have Polygon vs
    Alpaca context, and how many closed/expired trades have path metrics.
    Use this first to know whether data is complete before drawing conclusions.
    """
    return _get("/market-context/coverage")


@mcp.tool()
def get_trade_audit(trade_id: str) -> dict:
    """Re-derive a trade's computed values from cached bar data and compare them
    against what's stored — for sanity-checking whether the data looks correct
    (read-only).

    Returns per-fill audit records (the recorded underlying price vs the actual
    minute bar at fill time, with nearby bars), a path-metrics audit, and an
    indicator lookback. Use this when a number looks off or to confirm that the
    underlying price / VWAP / indicators are consistent with surrounding bars.

    trade_id: a trade UUID.
    """
    return _get(f"/market-context/audit/{trade_id}")


@mcp.tool()
def get_trade_path_metrics(start_date: str | None = None, end_date: str | None = None,
                           status: str | None = "closed", ticker: str | None = None) -> list:
    """Path metrics across many trades for aggregate analysis (read-only).

    Each row joins a trade's id/ticker/status/open-close/P-L/instrument with its
    full path metrics: MFE, MAE, time-to-MFE/MAE, exit efficiency, giveback,
    post-exit continuation (15/30/60m), and hold/exit buckets. `path` is null for
    trades without computed metrics.

    Use this to compare MFE / exit efficiency / giveback across a day, a ticker,
    or the whole journal. Dates are YYYY-MM-DD and filter by trade open date;
    status is open|closed|expired (defaults to closed). Omit all args for every
    closed trade — scope by date (e.g. yesterday) to keep the payload small.
    """
    params = {k: v for k, v in {
        "start_date": start_date, "end_date": end_date,
        "status": status, "ticker": ticker,
    }.items() if v}
    trades = _get("/trades", params) or []
    by_id = {t["id"]: t for t in trades}
    if not by_id:
        return []
    paths = _get("/market-context/trade-path/bulk", {"ids": ",".join(by_id)})
    return [
        {
            "trade_id": tid,
            "ticker": t.get("ticker"),
            "status": t.get("status"),
            "instrument_type": t.get("instrument_type"),
            "opened_at": t.get("opened_at"),
            "closed_at": t.get("closed_at"),
            "realized_pnl": t.get("realized_pnl"),
            "path": paths.get(tid),
        }
        for tid, t in by_id.items()
    ]


@mcp.tool()
def get_fill_contexts(start_date: str | None = None, end_date: str | None = None,
                      status: str | None = None, ticker: str | None = None) -> list:
    """Entry/exit market context across many fills for aggregate analysis (read-only).

    Anchored to trades matching the filters. Each row carries the fill's side,
    time, and price; both the Polygon (`underlying_price_at_fill`) and Alpaca
    (`entry_underlying_price`) underlying prices side by side for cross-checking;
    VWAP and distance-from-VWAP; RSI/EMA; relative volume; and behavioral flags
    (above VWAP, chase, late move, trend aligned).

    Use this to study VWAP/entry quality across trades or a day, and to spot when
    the two underlying-price sources disagree. Dates YYYY-MM-DD (filter by trade
    open date); status open|closed|expired.
    """
    params = {k: v for k, v in {
        "start_date": start_date, "end_date": end_date,
        "status": status, "ticker": ticker,
    }.items() if v}
    trades = _get("/trades", params) or []
    trade_ids = [t["id"] for t in trades]
    if not trade_ids:
        return []
    fills_by_trade = _get("/trades/fills/bulk", {"ids": ",".join(trade_ids)}) or {}

    rows: list = []
    fill_to_trade: dict = {}
    all_fills: list = []
    for tid, flist in fills_by_trade.items():
        for f in flist:
            fill_to_trade[f["id"]] = tid
            all_fills.append(f)
    fill_ids = [f["id"] for f in all_fills]
    ctx_map = _get("/market-context/fills/bulk", {"ids": ",".join(fill_ids)}) if fill_ids else {}

    for f in all_fills:
        c = ctx_map.get(f["id"]) or {}
        rows.append({
            "fill_id": f["id"],
            "trade_id": fill_to_trade[f["id"]],
            "ticker": f.get("ticker"),
            "side": f.get("side"),
            "executed_at": f.get("executed_at"),
            "price": f.get("price"),
            "underlying_price_at_fill": f.get("underlying_price_at_fill"),
            "entry_underlying_price": c.get("entry_underlying_price"),
            "entry_vwap": c.get("entry_vwap"),
            "entry_vs_vwap_pct": c.get("entry_vs_vwap_pct"),
            "entry_rsi_14": c.get("entry_rsi_14"),
            "entry_ema_9": c.get("entry_ema_9"),
            "entry_ema_20": c.get("entry_ema_20"),
            "rvol_time_adjusted": c.get("rvol_time_adjusted"),
            "is_above_vwap": c.get("is_above_vwap"),
            "is_chase_entry": c.get("is_chase_entry"),
            "is_late_move": c.get("is_late_move"),
            "is_trend_aligned": c.get("is_trend_aligned"),
        })
    return rows


if __name__ == "__main__":
    mcp.run()
