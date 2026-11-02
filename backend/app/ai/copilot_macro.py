"""The copilot's macro series and history base rates (docs/copilot-lab.md § Macro and base rates).

``get_macro`` reads public FRED series (no key: the fredgraph CSV download) for what the regime read lacks: the 2-year
and 10-year, the curve, real yields and breakevens, the funds rate, high-yield and investment-grade credit spreads, the
dollar, oil and the Chicago Fed's financial conditions index, each with its change over a week, a month and three
months and where it sits in its one-year range. ``get_base_rates`` counts what followed past drawdowns like the current
one in a symbol's own daily history (the chart feed's split-adjusted closes): forward returns at fixed horizons beside
the unconditional baseline, further drops, recoveries and the recent episodes. Counts of the past, never a forecast.
Replay cuts both at the frozen day; the fixture serves fixed numbers. Nothing here writes, except the FRED file cache.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from app.engine import market_http
from app.engine.chart_math import ET

log = logging.getLogger(__name__)

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fred"
FRED_TTL_S = 6 * 3600
# (id, label, kind): a rate or spread changes in basis points, a level in percent, an index by its difference.
SERIES = (
    ("DGS2", "2-year Treasury yield, %", "rate"),
    ("DGS10", "10-year Treasury yield, %", "rate"),
    ("T10Y2Y", "10-year minus 2-year, percentage points", "rate"),
    ("DFII10", "10-year real yield (TIPS), %", "rate"),
    ("T10YIE", "10-year breakeven inflation, %", "rate"),
    ("DFF", "Effective fed funds rate, %", "rate"),
    ("BAMLH0A0HYM2", "High-yield credit spread (ICE BofA OAS), %", "rate"),
    ("BAMLC0A0CM", "Investment-grade credit spread (ICE BofA OAS), %", "rate"),
    ("DTWEXBGS", "Broad trade-weighted US dollar index", "level"),
    ("DCOILWTICO", "WTI crude oil, $ a barrel", "level"),
    ("NFCI", "Chicago Fed financial conditions (above 0 = tighter than average; weekly)", "index"),
)
LOOKBACKS = (("1w", 7), ("1m", 30), ("3m", 91))
MACRO_NOTE = ("FRED publishes a day's value the next business day (credit spreads and the dollar can lag a day or two "
              "more); each series carries its own date. Changes: rates and spreads in basis points, the dollar and oil in "
              "percent, the conditions index as a plain difference. "
              "range_pct_1y is where the latest value sits between its one-year low (0) and high (100).")

HIGH_WINDOW = 252  # trading days: the trailing one-year high a drawdown is measured from
HORIZONS = (5, 21, 63, 126)
MIN_BARS = HIGH_WINDOW + 63
MAX_EPISODES_SHOWN = 10
BASE_RATE_NOTE = ("An episode starts the first close at least threshold_pct below the trailing 252-day closing high and "
                  "ends once the drawdown has recovered to half the threshold (the last one is marked ongoing until then). "
                  "Forward returns are close to close on split-adjusted closes, dividends left out. baseline is every day's forward return over the same history, so "
                  "an episode's figure means something only beside it. Overlapping market regimes and fewer than 10 "
                  "episodes make these anecdotes, not odds.")


# --------------------------------------------------------------------------- FRED

def _fetch(series_id: str, start: date) -> str:
    response = market_http.get(FRED_URL, params={"id": series_id, "cosd": start.isoformat()}, timeout=8)
    response.raise_for_status()
    text = response.text
    if not text.startswith("observation_date"):
        raise ValueError("not a FRED CSV")
    return text


def _cached(series_id: str, start: date, now: float) -> tuple[str | None, float | None]:
    """The series' CSV and when it was fetched: fresh from disk, else fetched, else the stale file, else (None, None)."""
    path = FRED_DIR / f"{series_id}.csv"
    stamp = path.stat().st_mtime if path.exists() else None
    if stamp is not None and now - stamp < FRED_TTL_S:
        return path.read_text(), stamp
    try:
        text = _fetch(series_id, start)
    except Exception as exc:  # noqa: BLE001 - a stale file or a missing series beats failing the whole read
        log.warning("FRED %s unavailable: %s", series_id, type(exc).__name__)
        return (path.read_text(), stamp) if stamp is not None else (None, None)
    FRED_DIR.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.part")
    part.write_text(text)
    os.replace(part, path)  # a reader never sees half a file
    return text, now


def observations(text: str, until: date | None = None) -> list[tuple[date, float]]:
    """A FRED CSV's dated values, missing ones ('.') left out, cut before ``until`` when given."""
    rows = []
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        if len(row) < 2:
            continue
        try:
            day, value = date.fromisoformat(row[0]), float(row[1])
        except ValueError:
            continue
        if math.isfinite(value) and (until is None or day < until):
            rows.append((day, value))
    return rows


def summarize(series_id: str, label: str, kind: str, rows: list[tuple[date, float]]) -> dict:
    if not rows:
        return {"id": series_id, "label": label, "state": "unavailable"}
    day, value = rows[-1]
    out = {"id": series_id, "label": label, "date": day.isoformat(), "value": round(value, 3)}
    for name, days in LOOKBACKS:
        before = [v for d, v in rows if d <= day - timedelta(days=days)]
        if before:
            then = before[-1]
            out[f"chg_{name}"] = (round((value - then) * 100, 1) if kind == "rate" else round(value - then, 3) if kind == "index"
                                  else round((value / then - 1) * 100, 2) if then else None)
    year = [v for d, v in rows if d > day - timedelta(days=365)]
    low, high = min(year), max(year)
    out.update(low_1y=round(low, 3), high_1y=round(high, 3),
               range_pct_1y=round((value - low) / (high - low) * 100) if high > low else None)
    return out


def macro(now: float, until: date | None = None, fetch=_cached) -> dict:
    """Every series, fetched in parallel; one that fails is unavailable and the rest stand."""
    start = (until or date.fromtimestamp(now)) - timedelta(days=400)

    def one(spec):
        series_id, label, kind = spec
        text, stamp = fetch(series_id, start, now)
        row = summarize(series_id, label, kind, observations(text, until) if text else [])
        if stamp is not None and now - stamp >= FRED_TTL_S:
            row["stale"] = True
        return row, stamp

    with ThreadPoolExecutor(max_workers=6) as pool:
        got = list(pool.map(one, SERIES))
    rows = [r for r, _ in got]
    stamps = [s for _, s in got if s is not None]
    ok = [r for r in rows if r.get("state") != "unavailable"]
    return {"state": "ok" if len(ok) == len(rows) else "partial" if ok else "unavailable",
            "fetched_at": datetime.fromtimestamp(min(stamps), ET).isoformat(timespec="minutes") if stamps else None,
            "latest_date": max((r["date"] for r in ok), default=None), "series": rows, "note": MACRO_NOTE}


def live_macro(now: datetime) -> dict:
    return macro(now.timestamp())


def _uncached(series_id: str, start: date, now: float) -> tuple[str | None, float | None]:
    """A replay's own read from its start: the shared cache starts about 400 days before today, not the frozen day."""
    try:
        return _fetch(series_id, start), now
    except Exception as exc:  # noqa: BLE001 - that series reads unavailable
        log.warning("FRED %s unavailable: %s", series_id, type(exc).__name__)
        return None, None


def replay_macro(at: datetime) -> dict:
    """Cut before the replay's day: FRED publishes a day's value the next business day."""
    day = at.astimezone(ET).date()
    return {**macro(time.time(), until=day, fetch=_uncached), "cut": f"values dated before {day}"}


def fixture_macro() -> dict:
    rows = [{"id": "DGS2", "label": SERIES[0][1], "date": "2026-10-22", "value": 4.31, "chg_1w": 6.0, "chg_1m": 18.0, "chg_3m": 22.0,
             "low_1y": 3.62, "high_1y": 4.52, "range_pct_1y": 77},
            {"id": "DGS10", "label": SERIES[1][1], "date": "2026-10-22", "value": 4.96, "chg_1w": -4.0, "chg_1m": 21.0, "chg_3m": 35.0,
             "low_1y": 4.02, "high_1y": 5.13, "range_pct_1y": 85},
            {"id": "BAMLH0A0HYM2", "label": SERIES[6][1], "date": "2026-10-21", "value": 3.31, "chg_1w": 22.0, "chg_1m": 41.0,
             "chg_3m": 38.0, "low_1y": 2.71, "high_1y": 4.12, "range_pct_1y": 43},
            {"id": "NFCI", "label": SERIES[10][1], "date": "2026-10-16", "value": -0.48, "chg_1w": 0.02, "chg_1m": 0.05,
             "chg_3m": 0.06, "low_1y": -0.6, "high_1y": -0.31, "range_pct_1y": 41}]
    return {"state": "ok", "fetched_at": "2026-10-23T09:00-04:00", "latest_date": "2026-10-22", "series": rows, "note": MACRO_NOTE}


# --------------------------------------------------------------------------- base rates

def _drawdowns(closes: list[float]) -> tuple[list[float], list[int]]:
    """Each close's distance below its trailing HIGH_WINDOW closing high (0 at a high), and that high's index."""
    dd, at = [], []
    for i, close in enumerate(closes):
        lo = max(0, i - HIGH_WINDOW + 1)
        j = max(range(lo, i + 1), key=lambda k: closes[k])
        dd.append(round(close / closes[j] - 1, 9))  # 88 / 110 is exactly 20% down, not a hair less
        at.append(j)
    return dd, at


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "median_pct": _pct(statistics.median(values)), "up_share": round(sum(v > 0 for v in values) / len(values), 2),
            "worst_pct": _pct(min(values)), "best_pct": _pct(max(values))}


def base_rates(symbol: str, bars: list[dict], drawdown_pct: float | None = None) -> dict:
    """What followed past drawdowns at least as deep as ``drawdown_pct`` (default: today's, whole percent) in ``bars``."""
    bars = sorted((b for b in bars if b.get("close")), key=lambda b: b["time"])
    if len(bars) < MIN_BARS:
        return {"symbol": symbol, "state": "unavailable",
                "reason": f"{len(bars)} daily bars; at least {MIN_BARS} are needed to measure a one-year high and what followed."}
    closes = [float(b["close"]) for b in bars]
    days = [datetime.fromtimestamp(b["time"], ET).date() for b in bars]
    dd, high_at = _drawdowns(closes)
    last = len(closes) - 1
    now_pct = -dd[last] * 100
    threshold = float(drawdown_pct) if drawdown_pct is not None else math.floor(round(now_pct, 6))  # 0.29 * 100 < 29
    current = {"close": closes[last], "date": days[last].isoformat(), "drawdown_pct": round(-now_pct, 2),
               "high": closes[high_at[last]], "high_date": days[high_at[last]].isoformat()}
    if threshold < 3:
        return {"symbol": symbol, "state": "not_in_drawdown", "current": current,
                "reason": "Less than 3% below its one-year closing high; pass drawdown_pct to ask about a deeper drop."}
    cut = -threshold / 100
    episodes, armed = [], False
    for i in range(HIGH_WINDOW - 1, last + 1):
        if dd[i] > cut / 2:
            armed = True
        elif armed and dd[i] <= cut:
            armed = False
            high = closes[high_at[i]]
            back = next((j for j in range(i + 1, last + 1) if closes[j] >= high), None)
            episodes.append({"i": i, "date": days[i].isoformat(), "drawdown_pct": _pct(dd[i]),
                             **{f"fwd_{h}d_pct": _pct(closes[i + h] / closes[i] - 1) for h in HORIZONS if i + h <= last},
                             # Only once 63 later closes exist: a shorter window's low is not the same measure.
                             "further_drop_63d_pct": _pct(min(closes[i + 1:i + 64]) / closes[i] - 1) if i + 63 <= last else None,
                             "recovered_high_in_days": back - i if back is not None else None})
    if episodes and not armed:
        episodes[-1]["ongoing"] = True  # the drawdown has not recovered to half the threshold since it began
    horizons = {f"{h}d": {"episodes": _stats([closes[e["i"] + h] / closes[e["i"]] - 1 for e in episodes if e["i"] + h <= last]),
                          "baseline": _stats([closes[i + h] / closes[i] - 1 for i in range(HIGH_WINDOW - 1, last + 1 - h)])}
                for h in HORIZONS}
    done = [e for e in episodes if e["i"] + 63 <= last]
    recovered = [e["recovered_high_in_days"] for e in done if e["recovered_high_in_days"] is not None]
    return {"symbol": symbol, "state": "ok", "latest_close": days[last].isoformat(), "since": days[HIGH_WINDOW - 1].isoformat(),
            "threshold_pct": threshold, "current": current, "episodes": len(episodes), "horizons": horizons,
            "further_drop_63d": _stats([e["further_drop_63d_pct"] / 100 for e in done if e["further_drop_63d_pct"] is not None]),
            "recovered_high": {"of": len(done), "recovered": len(recovered),
                               "median_days": statistics.median(recovered) if recovered else None},
            "recent": [{k: v for k, v in e.items() if k != "i"} for e in episodes[-MAX_EPISODES_SHOWN:]],
            "note": BASE_RATE_NOTE}


def history_bars(symbol: str, today: date, live: bool = True) -> list[dict]:
    """The chart feed's whole daily history (Tradier, split-adjusted, completed days, read once per New York date) and,
    when ``live``, today's bar from the workspace's tail."""
    from app.engine.chart_feed import chart_feed
    from app.engine.chart_splits import UNAVAILABLE
    info = chart_feed.splits.get(symbol) if chart_feed.splits else UNAVAILABLE
    bars = list(chart_feed.daily.entry(symbol, today, info).bars)
    if live and bars:
        from app.engine.desk_context import daily_bars
        bars += [b for b in daily_bars(symbol) if b["time"] > bars[-1]["time"]]
    return bars


SOURCE_NOTE = "Tradier daily history through the chart feed, split-adjusted, dividends left out"


def live_base_rates(symbol: str, drawdown_pct: float | None) -> dict:
    now = datetime.now(ET)
    return {**base_rates(symbol, history_bars(symbol, now.date()), drawdown_pct), "source_note": SOURCE_NOTE,
            "as_of": now.isoformat(timespec="minutes")}


def replay_base_rates(symbol: str, drawdown_pct: float | None, at: datetime) -> dict:
    day = at.astimezone(ET).date()
    bars = [b for b in history_bars(symbol, datetime.now(ET).date(), live=False) if datetime.fromtimestamp(b["time"], ET).date() < day]
    return {**base_rates(symbol, bars, drawdown_pct), "source_note": SOURCE_NOTE, "cut": f"daily closes before {day}",
            "as_of": at.isoformat(timespec="minutes")}


def fixture_bars(end: date = date(2026, 10, 22), n: int = 1925) -> list[dict]:
    """A deterministic rising series with periodic drawdowns, ending about 20% below its high on ``end``, as daily
    bars on weekdays."""
    closes, price = [], 40.0
    for i in range(n):
        price *= 1 + 0.0008 + 0.012 * math.sin(i / 37) * (1 if (i // 300) % 2 else 0.6)
        closes.append(round(price, 2))
    days, day = [], end
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return [{"time": int(datetime(d.year, d.month, d.day, 16, tzinfo=ET).timestamp()), "close": c}
            for d, c in zip(reversed(days), closes)]


def fixture_base_rates(symbol: str, drawdown_pct: float | None) -> dict:
    return {**base_rates(symbol, fixture_bars(), drawdown_pct),
            "source_note": "SIMULATED daily bars", "as_of": "2026-10-23T11:12-04:00"}
