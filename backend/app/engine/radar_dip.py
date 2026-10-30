"""Radar dip-buy candidates, rule ``radar-dip-v0`` (``docs/radar.md`` § Dip-buy candidates).

A discovery rule, separate from the ``radar_rules`` trial: in the first hour it flags a tracked stock that came
into the day weak (gapped down, or closed yesterday below its 20-day average), dropped further, and now shows the
first sign of turning up on the recorded passes. It is advice only: it flags a name and never places an order. No
model call; the only inputs are the session's recorded passes and each stock's completed daily closes before the
session.

All of these hold on ``persist_passes`` consecutive passes (no gap over 150 seconds), each read as of that pass:

- **Window:** the pass started before 10:30 ET, and the session's first usable pass started before 09:33 ET with a
  usable quote for the stock (otherwise the morning low and the sampled VWAP are not seen).
- **Liquid:** last at least ``min_price`` and the day's dollar volume so far (last × cumulative volume) at least
  ``min_dollar_volume``. The tracked list is a curated list of optionable names; optionability is not re-checked.
- **Weak coming in:** the open at least ``gap_down_pct`` below the previous close, or the latest completed daily
  close below the mean of the last ``trend_days`` completed closes.
- **Dropped:** the lowest recorded last so far at least ``dip_pct`` below the previous close.
- **Turning up:** no new or equal low for ``low_age_minutes``; the last at least ``bounce_pct`` above that low;
  the low was under its sampled VWAP and the last is now above it. The sampled VWAP weights each recorded last by
  the cumulative volume added since the stock's previous usable quote.

One event per stock a session (kind ``dip_turn``, direction ``up``, ids ``rd0-…``), at most ``max_events`` a
session, the earliest first (ties by symbol). No revisions. The numbers in ``V0`` were fixed before any trial and
are not tuned on trades; changing one means a new version. ``RADAR_DIP_RULES`` is ``off`` (default), ``record``
(events go to the feed and are scored by ``scripts/radar_outcomes.py``) or ``alert`` (also phone pings, which
still need ``RADAR_ALERTS_ENABLED``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
import os

from app.engine.chart_math import ET, REGULAR_OPEN
from app.engine.radar_rules import MAX_PASS_GAP_SECONDS, _epoch, _evidence, _pct, _ret, _slug, usable
from app.engine.radar_store import RadarEvent

log = logging.getLogger(__name__)

PREFIX = "radar-dip-"
KIND = "dip_turn"
MODES = ("off", "record", "alert")


@dataclass(frozen=True)
class DipThresholds:
    window_end_minute: int  # ET minute of day; passes started at or after it never trigger
    first_pass_by_minutes: int  # the session's first usable pass must start within this many minutes of the open
    min_price: float
    min_dollar_volume: float
    gap_down_pct: float
    trend_days: int
    dip_pct: float
    low_age_minutes: int
    bounce_pct: float
    persist_passes: int
    max_events: int
    version: str


V0 = DipThresholds(window_end_minute=10 * 60 + 30, first_pass_by_minutes=3, min_price=5.0, min_dollar_volume=10_000_000,
                   gap_down_pct=1.0, trend_days=20, dip_pct=1.5, low_age_minutes=5, bounce_pct=0.5, persist_passes=2,
                   max_events=10, version="radar-dip-v0")
VERSIONS = {V0.version: V0}


def is_dip(event: dict) -> bool:
    """A dip-rule event: never part of the ``radar_rules`` trial's proof, census or scoring."""
    return str(event.get("rule_version", "")).startswith(PREFIX)


def mode_from_env() -> str:
    """``RADAR_DIP_RULES``: off (default), record or alert; anything else stays off and logs."""
    mode = os.environ.get("RADAR_DIP_RULES", "").strip().lower() or "off"
    if mode not in MODES:
        log.error("Unknown RADAR_DIP_RULES %r; the dip rule stays off", mode)
        return "off"
    return mode


# ------------------------------------------------------------------ daily context


def daily_context(bars: dict[str, list[dict]], session_date: str, days: int = V0.trend_days) -> dict[str, dict]:
    """Per symbol, the latest completed daily close before ``session_date`` and the mean of the last ``days`` closes.

    Bars on or after the session date are ignored, so nothing from the session itself (or later) is read. A symbol
    with fewer than ``days`` closes, or whose newest close is more than 5 calendar days old, has no entry.
    """
    session = date.fromisoformat(session_date)
    out = {}
    for symbol, rows in bars.items():
        dated = []
        for bar in rows or []:
            try:
                day = datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00")).astimezone(ET).date()
                close = float(bar["c"])
            except (KeyError, TypeError, ValueError):
                continue
            if day < session and close > 0:
                dated.append((day, close))
        dated.sort()
        if len(dated) < days or (session - dated[-1][0]).days > 5:
            continue
        closes = [c for _, c in dated[-days:]]
        out[symbol] = {"close": dated[-1][1], "sma": sum(closes) / days, "bar_date": dated[-1][0].isoformat()}
    return out


def fetch_daily(symbols: list[str], session_date: str) -> dict[str, dict]:
    """``daily_context`` from Alpaca daily bars, through the no-retry fast read (2.5 s a request, no sleep), so a rate
    limit or outage raises at once instead of holding up the recorder's pass; raises when Alpaca is not configured."""
    from app.engine import alpaca
    if not alpaca.alpaca_configured():
        raise RuntimeError("the dip rule's 20-day test needs Alpaca daily bars (ALPACA_API_KEY)")
    session = date.fromisoformat(session_date)
    bars: dict[str, list] = {}
    for i in range(0, len(symbols), 100):
        params = {"symbols": ",".join(symbols[i:i + 100]), "timeframe": "1Day", "adjustment": "all", "limit": 10000,
                  "start": (session - timedelta(days=45)).isoformat(), "end": (session - timedelta(days=1)).isoformat(),
                  "feed": alpaca.ALPACA_DATA_FEED}
        while True:
            page = alpaca._alpaca_get_fast("/v2/stocks/bars", params)
            for symbol, rows in (page.get("bars") or {}).items():
                bars.setdefault(symbol, []).extend(rows)
            if not page.get("next_page_token"):
                break
            params = {**params, "page_token": page["next_page_token"]}
    return daily_context(bars, session_date)


# ------------------------------------------------------------------ the rule


def _minute(record: dict) -> int:
    at = datetime.fromtimestamp(_epoch(record["started_at"]), ET)
    return at.hour * 60 + at.minute


def needed_pass_ids(passes: list[dict], end: int, t: DipThresholds = V0) -> set[int]:
    """Every pass the rule reads for ``passes[end]``: the session so far inside the window, none after it."""
    return {p["id"] for p in passes[:end + 1]} if _minute(passes[end]) < t.window_end_minute else set()


@dataclass
class _Reading:
    symbol: str
    end: int
    low_index: int
    last: float
    prev_close: float
    low: float
    vwap: float
    gap_pct: float | None
    below_trend: bool
    dollar_volume: float


def _readings(universe: dict, passes: list[dict], end: int, quotes: dict, daily: dict, t: DipThresholds) -> dict[str, _Reading]:
    """Stocks meeting every condition at ``passes[end]``, from ``passes[0..end]`` only."""
    if _minute(passes[end]) >= t.window_end_minute or _minute(passes[0]) >= REGULAR_OPEN + t.first_pass_by_minutes:
        return {}
    out = {}
    for row in universe["symbols"]:
        sym = row["symbol"]
        if row["kind"] != "stock" or row["benchmark"]:
            continue
        if not usable(quotes.get(passes[0]["id"], {}).get(sym)):
            continue
        num = den = 0.0
        volume = 0
        low = low_index = low_vwap = None
        for i in range(end + 1):
            q = quotes.get(passes[i]["id"], {}).get(sym)
            if not usable(q):
                continue
            v = q.get("volume")
            if isinstance(v, (int, float)) and v > volume:
                num += q["last"] * (v - volume)
                den += v - volume
                volume = v
            vwap = num / den if den else None
            if low is None or q["last"] <= low:
                low, low_index, low_vwap = q["last"], i, vwap
        q = quotes.get(passes[end]["id"], {}).get(sym)
        if not usable(q) or not den or low_vwap is None:
            continue
        last, prev, vwap = q["last"], q["prev_close"], num / den
        opened = q.get("open")
        gap = _ret(prev, opened) if isinstance(opened, (int, float)) and opened > 0 else None
        trend = daily.get(sym)
        below = bool(trend and trend["close"] < trend["sma"])
        dollars = last * volume
        low_age = (_epoch(passes[end]["started_at"]) - _epoch(passes[low_index]["started_at"])) / 60
        if (last >= t.min_price and dollars >= t.min_dollar_volume
                and ((gap is not None and gap <= -t.gap_down_pct) or below)
                and _ret(prev, low) <= -t.dip_pct
                and low_age >= t.low_age_minutes and _ret(low, last) >= t.bounce_pct
                and low < low_vwap and last > vwap):
            out[sym] = _Reading(sym, end, low_index, last, prev, low, vwap, gap, below, dollars)
    return out


def _persisting(universe, passes, end, quotes, daily, t: DipThresholds) -> dict[str, _Reading]:
    first = end - t.persist_passes + 1
    if first < 0:
        return {}
    for a in range(first, end):
        if _epoch(passes[a + 1]["started_at"]) - _epoch(passes[a]["started_at"]) > MAX_PASS_GAP_SECONDS:
            return {}
    held = None
    for i in range(first, end + 1):
        now = _readings(universe, passes, i, quotes, daily, t)
        held = now if held is None else {s: now[s] for s in held if s in now}
    return held or {}


def event_id(session_date: str, symbol: str, version: str = V0.version) -> str:
    return f"rd{version.rsplit('-v', 1)[1]}-{session_date}-dip-{_slug(symbol)}-up-1"


def _clock(record: dict) -> str:
    at = datetime.fromtimestamp(_epoch(record["started_at"]), ET)
    return f"{(at.hour - 1) % 12 + 1}:{at.minute:02d}"


def _build(r: _Reading, passes, quotes, daily: dict, universe_version: str, t: DipThresholds) -> RadarEvent:
    p = passes[r.end]
    session = p["session_date"]
    spy = quotes.get(p["id"], {}).get("SPY")
    why = []
    if r.gap_pct is not None and r.gap_pct <= -t.gap_down_pct:
        why.append(f"gapped {_pct(r.gap_pct)}")
    if r.below_trend:
        why.append(f"closed below its {t.trend_days}-day average")
    summary = (f"{r.symbol} turning up after a morning dip: low {_pct(_ret(r.prev_close, r.low))} at "
               f"{_clock(passes[r.low_index])}, now {_pct(_ret(r.prev_close, r.last))}, back above its sampled VWAP "
               f"({' and '.join(why)})")
    measures = {"day_change_pct": round(_ret(r.prev_close, r.last), 3), "low_change_pct": round(_ret(r.prev_close, r.low), 3),
                "from_low_pct": round(_ret(r.low, r.last), 3), "vwap_distance_pct": round(_ret(r.vwap, r.last), 3),
                "vwap": round(r.vwap, 4), "dollar_volume": round(r.dollar_volume),
                "low_minutes_ago": round((_epoch(p["started_at"]) - _epoch(passes[r.low_index]["started_at"])) / 60)}
    if r.gap_pct is not None:
        measures["gap_pct"] = round(r.gap_pct, 3)
    trend = daily.get(r.symbol)
    if trend:
        measures["prior_close_vs_average_pct"] = round(_ret(trend["sma"], trend["close"]), 3)
    if usable(spy):
        measures["spy_day_change_pct"] = round(_ret(spy["prev_close"], spy["last"]), 3)
    started = datetime.fromtimestamp(_epoch(p["started_at"]), ET)
    return {"event_id": event_id(session, r.symbol, t.version), "session_date": session, "rule_version": t.version,
            "universe_version": universe_version, "kind": KIND, "direction": "up", "symbols": [r.symbol],
            "benchmark": "SPY", "group": None, "first_seen_at": p["finished_at"], "summary": summary,
            "measures": measures,
            "evidence": _evidence(passes, quotes, r.low_index, [r.symbol, "SPY"]) + _evidence(passes, quotes, r.end, [r.symbol, "SPY"]),
            "coverage": {"passes_expected": max(1, started.hour * 60 + started.minute - REGULAR_OPEN + 1),
                         "passes_recorded": r.end + 1, "symbols_missing": []},
            "chart": {"symbol": r.symbol, "from": passes[0]["started_at"], "to": p["finished_at"]}}


def detect(universe: dict, passes: list[dict], end: int, quotes: dict[int, dict[str, dict]], saved: list[dict],
           daily: dict[str, dict], thresholds: DipThresholds = V0) -> list[RadarEvent]:
    """New dip events for ``passes[end]``.

    ``passes`` is ``radar_rules.session_passes`` for one session, ``quotes`` covers ``needed_pass_ids``, ``saved``
    is the session's saved events of this version and ``daily`` is ``daily_context`` for the session.
    """
    t = thresholds
    room = t.max_events - len(saved)
    if room <= 0:
        return []
    seen = {e["symbols"][0] for e in saved}
    found = _persisting(universe, passes, end, quotes, daily, t)
    return [_build(found[s], passes, quotes, daily, passes[end]["universe_version"], t)
            for s in sorted(found) if s not in seen][:room]


def replay(universe: dict, passes: list[dict], quotes: dict[int, dict[str, dict]], daily: dict[str, dict],
           thresholds: DipThresholds = V0) -> list[RadarEvent]:
    """Every dip event the rule writes over one session's passes, in order."""
    saved: list[RadarEvent] = []
    for end in range(len(passes)):
        saved += detect(universe, passes, end, quotes, saved, daily, thresholds)
    return saved
