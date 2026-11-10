"""Radar gap reversals, rule ``radar-reversal-v0`` (registered candidate C05 "reverse", ``research/radar-v2``).

A discovery rule, separate from the ``radar_rules`` trial and from ``radar_dip``: in the first two hours it flags a
tracked stock that gapped one way against SPY and has since reversed the other way from the open, still moving that
way over the last five minutes. It is advice only: it flags a name and never places an order. No model call; the
only inputs are the session's recorded passes.

For each non-benchmark stock and direction d (+1 up, -1 down), every figure signed by d and relative to SPY over the
same interval (stock return minus SPY return, in percentage points), all of these hold at one pass:

- **Window:** t, the minutes since the regular open, at most ``window_minutes``.
- **Gap against:** G, previous close to today's open, at most ``-gap_relative_pct``.
- **Reversed from the open:** O, today's open to now, at least ``open_relative_pct``.
- **Still going:** M5, the exact trailing five minutes, at least ``five_minute_relative_pct``.

The study read minute bars; the recorder stands in for them as ``radar_rules``' opening drive does: the opening price
is the ``open`` field of the quote row on the 09:31 pass, the five-minute start is the pass in the exact minute slot
five minutes back, both from the current pass's universe version, and every quote read must be ``usable``. A missing
operand means no reading; nothing is filled in. The first pass that can read all three is 09:36 (t = 6).

One event per stock and direction a session (kind ``gap_reversal``, ids ``rg0-…``), the first qualifying pass only.
No revisions, no persistence, no cap. The numbers in ``V0`` are the registered ones and are not tuned; changing one
means a new version. ``RADAR_REVERSAL_RULES`` is ``off`` (default), ``record`` or ``alert``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
import logging
import os

from app.engine.chart_math import ET, REGULAR_OPEN
from app.engine.radar_rules import _epoch, _evidence, _pct, _ret, _slug, usable
from app.engine.radar_store import RadarEvent

log = logging.getLogger(__name__)

PREFIX = "radar-reversal-"
KIND = "gap_reversal"
MODES = ("off", "record", "alert")
FIRST_MINUTE = 6  # the opening (09:31) and five-minute-back slots only both exist from 09:36


@dataclass(frozen=True)
class ReversalThresholds:
    window_minutes: int  # t <= this, minutes since the regular open
    gap_relative_pct: float  # signed G <= -this
    open_relative_pct: float  # signed O >= this
    five_minute_relative_pct: float  # signed M5 >= this
    version: str


V0 = ReversalThresholds(window_minutes=120, gap_relative_pct=2.0, open_relative_pct=1.75, five_minute_relative_pct=0.5,
                        version="radar-reversal-v0")
VERSIONS = {V0.version: V0}


def is_reversal(event: dict) -> bool:
    """A reversal-rule event: never part of the ``radar_rules`` trial's proof, census or scoring."""
    return str(event.get("rule_version", "")).startswith(PREFIX)


def mode_from_env() -> str:
    """``RADAR_REVERSAL_RULES``: off (default), record or alert; anything else stays off and logs."""
    mode = os.environ.get("RADAR_REVERSAL_RULES", "").strip().lower() or "off"
    if mode not in MODES:
        log.error("Unknown RADAR_REVERSAL_RULES %r; the reversal rule stays off", mode)
        return "off"
    return mode


def event_id(session_date: str, symbol: str, direction: str, version: str = V0.version) -> str:
    return f"rg{version.rsplit('-v', 1)[1]}-{session_date}-reversal-{_slug(symbol)}-{direction}-1"


# ------------------------------------------------------------------ the rule


def _indexes(passes: list[dict], end: int, t: ReversalThresholds) -> list[int]:
    """[opening, five minutes back, now] pass indexes for ``passes[end]``, or [] outside the window or on a gap."""
    p = passes[end]
    at = datetime.fromtimestamp(_epoch(p["started_at"]), ET)
    minute = at.hour * 60 + at.minute - REGULAR_OPEN
    if not FIRST_MINUTE <= minute <= t.window_minutes:
        return []
    current_slot = int(at.timestamp() // 60)
    wanted = (current_slot - minute + 1, current_slot - 5)
    found = {}
    for i in range(end):
        q = passes[i]
        slot = int(_epoch(q["started_at"]) // 60)
        if slot in wanted and q["universe_version"] == p["universe_version"]:
            found[slot] = i
    if any(slot not in found for slot in wanted):
        return []
    return [found[wanted[0]], found[wanted[1]], end]


def needed_pass_ids(passes: list[dict], end: int, t: ReversalThresholds = V0) -> set[int]:
    """Every pass ``detect`` reads for ``passes[end]``: the session so far (for the extreme), none once outside the
    window or when the opening or five-minute pass is missing."""
    return {p["id"] for p in passes[:end + 1]} if _indexes(passes, end, t) else set()


def _moves(rows: tuple[dict, dict, dict], symbol: str):
    """(gap, from open, last five minutes) percent returns for one symbol, or None when any operand is missing."""
    first, prior, now = (r.get(symbol) for r in rows)
    if not all(usable(q) for q in (first, prior, now)):
        return None
    prices = (first["prev_close"], first.get("open"), prior["last"], now["last"])
    if not all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in prices):
        return None
    prev, opened, back, last = prices
    return _ret(prev, opened), _ret(opened, last), _ret(back, last)


def _extreme(passes, end: int, quotes, symbol: str, opening: int, open_price: float, sign: int) -> tuple[float, int]:
    """The lowest (up) or highest (down) of the open and every usable recorded last so far, with its pass index (the
    opening pass for the open; the latest pass for a repeated last)."""
    best, at = open_price, opening
    for i in range(end + 1):
        q = quotes.get(passes[i]["id"], {}).get(symbol)
        if usable(q) and sign * q["last"] <= sign * best:
            best, at = q["last"], i
    return best, at


def _build(sym: str, sign: int, own, spy, indexes, passes, quotes, t: ReversalThresholds) -> RadarEvent:
    opening, trailing, end = indexes
    p = passes[end]
    session = p["session_date"]
    direction = "up" if sign > 0 else "down"
    first, now, spy_now = quotes[passes[opening]["id"]][sym], quotes[p["id"]][sym], quotes[p["id"]]["SPY"]
    gap, since_open, five = (own[k] - spy[k] for k in range(3))
    extreme, extreme_at = _extreme(passes, end, quotes, sym, opening, first["open"], sign)
    summary = (f"{sym} reversing {direction} after a gap {'down' if sign > 0 else 'up'}: gapped {_pct(gap)} vs SPY, "
               f"{_pct(since_open)} vs SPY from the open, {_pct(five)} in the last 5 minutes")
    measures = {"gap_relative_pct": round(gap, 3), "open_relative_pct": round(since_open, 3),
                "five_minute_relative_pct": round(five, 3), "relative_pct": round(since_open, 3),
                "change_pct": round(own[1], 3), "benchmark_change_pct": round(spy[1], 3),
                "day_change_pct": round(_ret(now["prev_close"], now["last"]), 3),
                "open_price": first["open"], "last_price": now["last"], "extreme_price": extreme,
                "extreme_minutes_ago": round((_epoch(p["started_at"]) - _epoch(passes[extreme_at]["started_at"])) / 60),
                "spy_day_change_pct": round(_ret(spy_now["prev_close"], spy_now["last"]), 3)}
    started = datetime.fromtimestamp(_epoch(p["started_at"]), ET)
    return {"event_id": event_id(session, sym, direction, t.version), "session_date": session, "rule_version": t.version,
            "universe_version": p["universe_version"], "kind": KIND, "direction": direction, "symbols": [sym],
            "benchmark": "SPY", "group": None, "first_seen_at": p["finished_at"], "summary": summary,
            "measures": measures,
            "evidence": [q for i in dict.fromkeys((opening, extreme_at, trailing, end))
                         for q in _evidence(passes, quotes, i, [sym, "SPY"])],
            "coverage": {"passes_expected": max(1, started.hour * 60 + started.minute - REGULAR_OPEN + 1),
                         "passes_recorded": end + 1, "symbols_missing": []},
            "chart": {"symbol": sym, "from": passes[0]["started_at"], "to": p["finished_at"]}}


def detect(universe: dict, passes: list[dict], end: int, quotes: dict[int, dict[str, dict]], saved: list[dict],
           thresholds: ReversalThresholds = V0) -> list[RadarEvent]:
    """New reversal events for ``passes[end]``.

    ``passes`` is ``radar_rules.session_passes`` for one session, ``quotes`` covers ``needed_pass_ids`` and ``saved``
    is the session's saved events of this version.
    """
    t = thresholds
    indexes = _indexes(passes, end, t)
    if not indexes:
        return []
    rows = tuple(quotes.get(passes[i]["id"], {}) for i in indexes)
    spy = _moves(rows, "SPY")
    if spy is None:
        return []
    seen = {(e["symbols"][0], e["direction"]) for e in saved}
    stocks = sorted(r["symbol"] for r in universe["symbols"] if r["kind"] == "stock" and not r["benchmark"])
    events = []
    for sym in stocks:
        own = _moves(rows, sym)
        if own is None:
            continue
        g, o, m5 = (own[k] - spy[k] for k in range(3))
        for sign, direction in ((1, "up"), (-1, "down")):
            if (sym, direction) in seen:
                continue
            if sign * g <= -t.gap_relative_pct and sign * o >= t.open_relative_pct and sign * m5 >= t.five_minute_relative_pct:
                events.append(_build(sym, sign, own, spy, indexes, passes, quotes, t))
    return events


def replay(universe: dict, passes: list[dict], quotes: dict[int, dict[str, dict]],
           thresholds: ReversalThresholds = V0) -> list[RadarEvent]:
    """Every reversal event the rule writes over one session's passes, in order."""
    saved: list[RadarEvent] = []
    for end in range(len(passes)):
        saved += detect(universe, passes, end, quotes, saved, thresholds)
    return saved
