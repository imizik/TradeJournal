"""
Deterministic market report ("packet") builder.

Produces the data layer for premarket/postmarket reports consumed by Claude
via MCP. This module computes tables and metrics only — regime classification,
sentiment, and narrative synthesis happen on the Claude side.

Symbol universe lives in backend/data/universe.json (hand-editable buckets).

Data tiers:
  - Detail tier (SPY/QQQ/IWM/DIA/SMH): live minute bars -> VWAP, range
    structure, opening range, premarket / after-hours detail.
  - Breadth tier (everything else): one snapshots call -> change, gap, RVOL.
  - ^VIX / ^TNX: yfinance (not available on Alpaca).
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from app.engine.alpaca import (
    ET,
    alpaca_configured,
    fetch_daily_bars,
    fetch_minute_bars_live,
    fetch_snapshots,
)
from app.engine.news import fetch_news

log = logging.getLogger(__name__)

UNIVERSE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "universe.json"

DETAIL_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "SMH"]
YF_GAUGES = ["^VIX", "^TNX"]

# Buckets ranked for leaders/laggards (execution universe, not indexes/gauges)
EXECUTION_BUCKETS = [
    "semis_ai", "memory", "megacap", "software",
    "high_beta", "spec_hardtech", "large_movers",
]


def build_market_report(report_type: str) -> dict:
    """Build a premarket or postmarket market report. Pure data, no LLM."""
    if report_type not in ("premarket", "postmarket"):
        raise ValueError(f"Unknown report_type: {report_type}")

    missing: list[str] = []
    sources: list[str] = []

    if not alpaca_configured():
        raise RuntimeError("Alpaca API keys are not configured")

    universe = _load_universe()
    all_symbols = sorted({s for bucket in universe.values() for s in bucket})

    now_et = datetime.now(ET)
    session_date, prior_date = _resolve_session_dates(report_type, now_et)
    market_state = _market_state(now_et)

    # --- breadth tier: snapshots + daily history -------------------------
    sources.append("alpaca_snapshots")
    snapshots = fetch_snapshots(all_symbols)
    for symbol in all_symbols:
        if symbol not in snapshots:
            missing.append(f"{symbol}: no Alpaca snapshot (bad/unsupported symbol?)")

    sources.append("alpaca_daily_bars")
    daily = fetch_daily_bars(all_symbols, session_date - timedelta(days=90), session_date)

    metrics: dict[str, dict] = {}
    for symbol in all_symbols:
        metrics[symbol] = _symbol_metrics(
            symbol, snapshots.get(symbol), daily.get(symbol, []), session_date
        )

    spy_pct = metrics.get("SPY", {}).get("pct_change")

    # --- detail tier: minute bars for indexes + SMH ----------------------
    sources.append("alpaca_minute_bars")
    minute_day = session_date
    minute = fetch_minute_bars_live(DETAIL_TICKERS, minute_day)
    detail = {
        t: _detail_metrics(minute.get(t, []), metrics.get(t, {}))
        for t in DETAIL_TICKERS
    }
    for t in DETAIL_TICKERS:
        if not minute.get(t):
            missing.append(f"{t}: no minute bars for {minute_day.isoformat()}")

    # --- yfinance gauges (VIX, 10Y) ---------------------------------------
    sources.append("yfinance (^VIX, ^TNX)")
    yf_gauges = {}
    for symbol in YF_GAUGES:
        gauge = _yf_gauge(symbol)
        if gauge is None:
            missing.append(f"{symbol}: yfinance fetch failed")
        else:
            yf_gauges[symbol] = gauge

    # --- buckets, sectors, leaders/laggards -------------------------------
    buckets = {
        name: _bucket_aggregate([metrics[s] for s in syms if s in metrics], spy_pct)
        for name, syms in universe.items()
        if name != "sectors"
    }

    sector_rows = sorted(
        (
            {"symbol": s, **_breadth_row(metrics[s])}
            for s in universe.get("sectors", [])
            if metrics.get(s, {}).get("pct_change") is not None
        ),
        key=lambda r: r["pct_change"],
        reverse=True,
    )

    execution_rows = sorted(
        (
            {"symbol": s, "bucket": bucket, **_breadth_row(metrics[s])}
            for bucket in EXECUTION_BUCKETS
            for s in universe.get(bucket, [])
            if metrics.get(s, {}).get("pct_change") is not None
        ),
        key=lambda r: r["pct_change"],
        reverse=True,
    )

    # --- news --------------------------------------------------------------
    sources.append("alpaca_news (Benzinga)")
    if report_type == "postmarket":
        news_start = datetime(session_date.year, session_date.month, session_date.day, 4, 0, tzinfo=ET)
    else:
        news_start = datetime(prior_date.year, prior_date.month, prior_date.day, 16, 0, tzinfo=ET)
    try:
        symbol_news = fetch_news(symbols=all_symbols, start=news_start, limit=50)
        broad_news = fetch_news(symbols=None, start=news_start, limit=25)
    except Exception as exc:
        log.warning("News fetch failed", exc_info=True)
        symbol_news, broad_news = [], []
        missing.append(f"news: fetch failed ({exc})")

    # --- standing caveats ---------------------------------------------------
    missing.append("premarket/after-hours volume understated (IEX feed, not SIP)")
    missing.append("economic calendar & scheduled earnings: no source — supplement via web search")
    if report_type == "postmarket" and market_state == "rth":
        missing.append("market still open — session metrics are intraday-so-far, not final")

    confidence = "high" if len(missing) <= 4 else ("medium" if len(missing) <= 8 else "low")

    report = {
        "report_type": report_type,
        "generated_at": now_et.isoformat(),
        "market_state": market_state,
        "session_date": session_date.isoformat(),
        "prior_session_date": prior_date.isoformat(),
        "sources": sources,
        "missing": missing,
        "confidence": confidence,
        "data": {
            "indexes_detail": detail,
            "sectors": sector_rows,
            "macro_gauges": {
                "etf": {
                    s: _breadth_row(metrics[s])
                    for s in universe.get("macro_gauges", [])
                    if s in metrics
                },
                "indexes": yf_gauges,
            },
            "universe_buckets": buckets,
            "leaders": execution_rows[:10],
            "laggards": execution_rows[-10:][::-1],
            "all_execution_symbols": execution_rows,
            "news": {
                "window_start": news_start.isoformat(),
                "symbol_tagged": symbol_news,
                "broad_tape": broad_news,
            },
        },
    }
    _archive_report(report)
    return report


# ---------------------------------------------------------------------------
# session/date helpers
# ---------------------------------------------------------------------------

def _previous_weekday(day: date) -> date:
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _resolve_session_dates(report_type: str, now_et: datetime) -> tuple[date, date]:
    """Return (session_date, prior_session_date) for the report."""
    today = now_et.date()
    if report_type == "premarket":
        # The upcoming/current session. On weekends, the next session's
        # "premarket" doesn't exist yet — use today and let data come up empty.
        session = today
        if session.weekday() >= 5:
            session = _previous_weekday(today)  # fall back to last session
    else:
        # Most recent session with meaningful data.
        session = today
        if session.weekday() >= 5 or now_et.hour < 9 or (now_et.hour == 9 and now_et.minute < 30):
            session = _previous_weekday(today)
    return session, _previous_weekday(session)


def _market_state(now_et: datetime) -> str:
    if now_et.weekday() >= 5:
        return "closed"
    minutes = now_et.hour * 60 + now_et.minute
    if minutes < 4 * 60:
        return "closed"
    if minutes < 9 * 60 + 30:
        return "premarket"
    if minutes < 16 * 60:
        return "rth"
    if minutes < 20 * 60:
        return "afterhours"
    return "closed"


# ---------------------------------------------------------------------------
# per-symbol breadth metrics (snapshot + daily history)
# ---------------------------------------------------------------------------

def _bar_et_dt(bar: dict) -> Optional[datetime]:
    ts = bar.get("t")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(ET)
    except ValueError:
        return None


def _symbol_metrics(symbol: str, snap: Optional[dict], daily_bars: list, session_date: date) -> dict:
    out: dict = {
        "symbol": symbol,
        "last_price": None,
        "last_trade_at": None,
        "prev_close": None,
        "pct_change": None,
        "gap_pct": None,
        "day_volume": None,
        "avg_volume_20": None,
        "rvol": None,
        "ah_move_pct": None,
        "session_high": None,
        "session_low": None,
    }
    if not snap:
        return out

    latest_trade = snap.get("latestTrade") or {}
    daily_bar = snap.get("dailyBar") or {}
    prev_daily = snap.get("prevDailyBar") or {}

    out["last_price"] = latest_trade.get("p")
    out["last_trade_at"] = latest_trade.get("t")

    # Figure out which bar is "this session" vs "prior session". During
    # premarket, the snapshot's dailyBar can still be the prior session.
    daily_dt = _bar_et_dt(daily_bar)
    session_bar: Optional[dict] = None
    if daily_dt and daily_dt.date() == session_date:
        session_bar = daily_bar
        out["prev_close"] = prev_daily.get("c")
    elif daily_dt and daily_dt.date() < session_date:
        out["prev_close"] = daily_bar.get("c")
    else:
        out["prev_close"] = prev_daily.get("c")

    if out["last_price"] is not None and out["prev_close"]:
        out["pct_change"] = round((out["last_price"] - out["prev_close"]) / out["prev_close"] * 100, 2)

    if session_bar:
        out["session_high"] = session_bar.get("h")
        out["session_low"] = session_bar.get("l")
        out["day_volume"] = session_bar.get("v")
        if session_bar.get("o") and out["prev_close"]:
            out["gap_pct"] = round((session_bar["o"] - out["prev_close"]) / out["prev_close"] * 100, 2)
        if out["last_price"] is not None and session_bar.get("c"):
            ah = (out["last_price"] - session_bar["c"]) / session_bar["c"] * 100
            # Only meaningful when the last trade is after the daily bar close;
            # tiny diffs during RTH are noise.
            out["ah_move_pct"] = round(ah, 2)

    # 20-day average volume from daily history, excluding the session itself
    volumes = [
        b.get("v") for b in daily_bars
        if b.get("v") is not None
        and (d := _bar_et_dt(b)) is not None
        and d.date() < session_date
    ][-20:]
    if volumes:
        out["avg_volume_20"] = round(sum(volumes) / len(volumes))
        if out["day_volume"]:
            out["rvol"] = round(out["day_volume"] / out["avg_volume_20"], 2)

    return out


def _breadth_row(m: dict) -> dict:
    """Compact row for tables — drop internals, keep what Claude reads."""
    return {
        "pct_change": m.get("pct_change"),
        "gap_pct": m.get("gap_pct"),
        "rvol": m.get("rvol"),
        "last_price": m.get("last_price"),
        "ah_move_pct": m.get("ah_move_pct"),
    }


def _bucket_aggregate(rows: list[dict], spy_pct: Optional[float]) -> dict:
    changes = [r["pct_change"] for r in rows if r.get("pct_change") is not None]
    rvols = [r["rvol"] for r in rows if r.get("rvol") is not None]
    if not changes:
        return {"symbols_with_data": 0}
    median_pct = round(statistics.median(changes), 2)
    return {
        "symbols_with_data": len(changes),
        "median_pct_change": median_pct,
        "pct_green": round(sum(1 for c in changes if c > 0) / len(changes) * 100, 1),
        "median_rvol": round(statistics.median(rvols), 2) if rvols else None,
        "rs_vs_spy": round(median_pct - spy_pct, 2) if spy_pct is not None else None,
        "best": max(changes),
        "worst": min(changes),
    }


# ---------------------------------------------------------------------------
# detail tier (minute bars)
# ---------------------------------------------------------------------------

def _detail_metrics(bars: list, breadth: dict) -> dict:
    pre, rth, ah = [], [], []
    for bar in bars:
        dt = _bar_et_dt(bar)
        if dt is None:
            continue
        minutes = dt.hour * 60 + dt.minute
        if minutes < 9 * 60 + 30:
            pre.append(bar)
        elif minutes < 16 * 60:
            rth.append(bar)
        else:
            ah.append(bar)

    out: dict = {
        "pct_change": breadth.get("pct_change"),
        "gap_pct": breadth.get("gap_pct"),
        "rvol": breadth.get("rvol"),
        "prev_close": breadth.get("prev_close"),
        "last_price": breadth.get("last_price"),
    }

    if pre:
        out["premarket_high"] = max(b["h"] for b in pre)
        out["premarket_low"] = min(b["l"] for b in pre)
        out["premarket_volume"] = sum(b.get("v", 0) for b in pre)

    if rth:
        rth_open = rth[0]["o"]
        rth_close = rth[-1]["c"]
        rth_high = max(b["h"] for b in rth)
        rth_low = min(b["l"] for b in rth)
        out["rth_open"] = rth_open
        out["rth_high"] = rth_high
        out["rth_low"] = rth_low
        out["rth_close"] = rth_close
        out["rth_volume"] = sum(b.get("v", 0) for b in rth)

        vol_sum = sum(b.get("v", 0) for b in rth)
        vw_sum = sum(b.get("v", 0) * b.get("vw", b.get("c", 0)) for b in rth)
        if vol_sum > 0:
            vwap = vw_sum / vol_sum
            out["rth_vwap"] = round(vwap, 4)
            out["close_vs_vwap_pct"] = round((rth_close - vwap) / vwap * 100, 2)
        if rth_high > rth_low:
            out["close_location_in_range"] = round((rth_close - rth_low) / (rth_high - rth_low), 2)

        or5 = [b for b in rth if (d := _bar_et_dt(b)) and (d.hour * 60 + d.minute) < 9 * 60 + 35]
        if or5:
            out["or5_high"] = max(b["h"] for b in or5)
            out["or5_low"] = min(b["l"] for b in or5)

    if ah and rth:
        ah_last = ah[-1]["c"]
        out["ah_last_price"] = ah_last
        out["ah_volume"] = sum(b.get("v", 0) for b in ah)
        out["ah_move_pct"] = round((ah_last - rth[-1]["c"]) / rth[-1]["c"] * 100, 2)

    return out


# ---------------------------------------------------------------------------
# yfinance gauges
# ---------------------------------------------------------------------------

def _yf_gauge(symbol: str) -> Optional[dict]:
    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)
        closes = hist["Close"].dropna()
        if closes.empty:
            return None
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else None
        return {
            "last": round(last, 2),
            "prev_close": round(prev, 2) if prev is not None else None,
            "change_pct": round((last - prev) / prev * 100, 2) if prev else None,
        }
    except Exception:
        log.warning("yfinance gauge fetch failed for %s", symbol, exc_info=True)
        return None


def _load_universe() -> dict[str, list[str]]:
    with open(UNIVERSE_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# archive — every generated packet is saved for validation / later diffing
# ---------------------------------------------------------------------------

ARCHIVE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "packet_archive"


def _archive_report(report: dict) -> None:
    """Write the exact JSON handed to Claude plus a skimmable markdown digest.

    Keyed by (session_date, report_type) — regenerating the same report
    overwrites, so the archive holds the latest version per session. The full
    JSON also feeds the future premarket-vs-postmarket diff.
    """
    try:
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stem = f"{report['session_date']}_{report['report_type']}"
        (ARCHIVE_DIR / f"{stem}.json").write_text(
            json.dumps(report, indent=1, default=str), encoding="utf-8"
        )
        (ARCHIVE_DIR / f"{stem}.md").write_text(_digest_md(report), encoding="utf-8")
    except OSError:
        log.warning("Failed to archive market report", exc_info=True)


def _digest_md(report: dict) -> str:
    d = report["data"]
    lines = [
        f"# {report['report_type']} packet — {report['session_date']}",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- market_state: {report['market_state']} | confidence: {report['confidence']}",
        "- missing:",
        *[f"  - {m}" for m in report["missing"]],
        "",
        "## Indexes",
    ]
    for symbol, m in d["indexes_detail"].items():
        lines.append(
            f"- {symbol}: {m.get('pct_change')}% | gap {m.get('gap_pct')}% | rvol {m.get('rvol')}"
            f" | close_vs_vwap {m.get('close_vs_vwap_pct')}% | range_loc {m.get('close_location_in_range')}"
            f" | AH {m.get('ah_move_pct')}%"
        )

    lines += ["", "## Sectors (sorted)"]
    for row in d["sectors"]:
        lines.append(f"- {row['symbol']}: {row['pct_change']}% (rvol {row['rvol']})")

    lines += ["", "## Buckets"]
    for name, b in d["universe_buckets"].items():
        if b.get("symbols_with_data"):
            lines.append(
                f"- {name}: median {b['median_pct_change']}% | rs_vs_spy {b['rs_vs_spy']}"
                f" | green {b['pct_green']}% | n={b['symbols_with_data']}"
            )
        else:
            lines.append(f"- {name}: NO DATA")

    gauges = d["macro_gauges"]["indexes"]
    lines += ["", "## VIX / 10Y"]
    for symbol, g in gauges.items():
        lines.append(f"- {symbol}: {g.get('last')} ({g.get('change_pct')}%)")

    lines += ["", "## Leaders"]
    for row in d["leaders"]:
        lines.append(f"- {row['symbol']} ({row['bucket']}): {row['pct_change']}%")
    lines += ["", "## Laggards"]
    for row in d["laggards"]:
        lines.append(f"- {row['symbol']} ({row['bucket']}): {row['pct_change']}%")

    news = d["news"]
    lines += ["", f"## Headlines (symbol-tagged, {len(news['symbol_tagged'])})"]
    for a in news["symbol_tagged"]:
        lines.append(f"- [{a.get('created_at')}] {a.get('headline')} ({', '.join(a.get('symbols') or [])})")
    lines += ["", f"## Headlines (broad tape, {len(news['broad_tape'])})"]
    for a in news["broad_tape"]:
        lines.append(f"- [{a.get('created_at')}] {a.get('headline')}")

    lines.append("")
    return "\n".join(lines)
