"""Radar step 2: the provisional alert rules ``radar-rules-v0`` (see ``docs/radar.md``).

Pure functions over recorded passes. ``detect`` looks at one pass (the latest the
caller has) and the passes its windows need, plus the session's saved events and
revisions, and returns the new events and revisions to append. Replaying the same
passes in order gives the same event ids and revisions, so the live runner, a
restart and ``scripts/radar_replay.py`` all agree.

Three kinds, all over a window W ending at the pass and starting at the recorded
pass about W minutes earlier (never the open, so an opening gap alone never
qualifies):

- ``relative_to_spy``: a stock's W return minus SPY's.
- ``relative_to_sector``: the same against the stock's ``sector`` ETF, skipped
  while the stock has a same-direction SPY event (that would be a duplicate).
- ``group_move``: a curated group whose members mostly move the same way versus
  SPY, by the median member.

Each must hold on ``persist_passes`` consecutive passes. One event per (session,
kind, symbol or group, direction) is active at a time; later passes write
``extended``, ``faded`` or ``reversed`` revisions measured from the event's own
window start, and a faded or reversed event can only come back as a new event
after the cooldown. A quote without a positive last and prev close, or whose
trade is over two minutes older than its retrieval, does not exist here: no
event is built from it and nothing is filled in.

The numbers in ``V0`` are provisional, set on the sessions listed in
``docs/radar.md``; changing them means a new ``RULE_VERSION``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from statistics import median
from typing import Iterable

from app.engine.chart_math import ET, REGULAR_OPEN
from app.engine.radar_store import RadarEvent, RadarEventRevision, RadarEvidence

RULE_VERSION = "radar-rules-v0"

WINDOW_TOLERANCE_SECONDS = 90  # the window's start pass is the one nearest W minutes back, within this
MAX_PASS_GAP_SECONDS = 150  # passes further apart than this break persistence
TRADE_AGE_SECONDS = 120
DOMINANT_SHARE = 0.5  # one member is "dominant" above this share of the group's same-direction move
USABLE = ("ok", "partial")


@dataclass(frozen=True)
class Thresholds:
    windows: tuple[int, ...]  # minutes
    spy_relative_pct: float
    sector_relative_pct: float
    own_move_floor_pct: float  # the stock's own |W move|
    group_relative_pct: float  # |median member vs SPY|
    group_min_members: int
    group_agreement: float  # share of members with data on the median's side
    persist_passes: int
    extend_step_pct: float  # stock events
    group_extend_step_pct: float
    cooldown_minutes: int


V0 = Thresholds(windows=(30,), spy_relative_pct=4.5, sector_relative_pct=4.5, own_move_floor_pct=2.0,
                group_relative_pct=2.0, group_min_members=4, group_agreement=0.6, persist_passes=3,
                extend_step_pct=1.5, group_extend_step_pct=1.0, cooldown_minutes=30)

_KIND_TAG = {"relative_to_spy": "spy", "relative_to_sector": "sector", "group_move": "group"}


def _epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pct(value: float) -> str:
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{abs(value):.1f}%"


def _ret(start: float, end: float) -> float:
    return (end / start - 1) * 100


def usable(quote: dict | None) -> bool:
    """A positive last and prev close and a trade at most two minutes older than its retrieval."""
    if not quote:
        return False
    last, prev, trade = quote.get("last"), quote.get("prev_close"), quote.get("trade_time_ms")
    if not all(isinstance(v, (int, float)) and v > 0 for v in (last, prev)) or not isinstance(trade, (int, float)):
        return False
    return 0 <= _epoch(quote["retrieved_at"]) - trade / 1000 <= TRADE_AGE_SECONDS


def session_passes(passes: Iterable[dict], session_date: str) -> list[dict]:
    """The session's ok/partial passes in time order: the only passes rules read."""
    rows = [p for p in passes if p["session_date"] == session_date and p["status"] in USABLE]
    return sorted(rows, key=lambda p: (p["started_at"], p["id"]))


def window_start(passes: list[dict], end: int, minutes: int) -> int | None:
    """Index of the pass nearest ``minutes`` before ``passes[end]``, same universe version, else None."""
    target = _epoch(passes[end]["started_at"]) - minutes * 60
    best = None
    for j in range(end - 1, -1, -1):
        gap = _epoch(passes[j]["started_at"]) - target
        if gap < -WINDOW_TOLERANCE_SECONDS:
            break
        if abs(gap) <= WINDOW_TOLERANCE_SECONDS and passes[j]["universe_version"] == passes[end]["universe_version"]:
            if best is None or abs(gap) < abs(_epoch(passes[best]["started_at"]) - target):
                best = j
    return best


def _persist_indexes(passes: list[dict], end: int, k: int) -> list[int] | None:
    """The last ``k`` passes ending at ``end`` when they are consecutive minutes, else None."""
    if end - k + 1 < 0:
        return None
    idx = list(range(end - k + 1, end + 1))
    for a, b in zip(idx, idx[1:]):
        if _epoch(passes[b]["started_at"]) - _epoch(passes[a]["started_at"]) > MAX_PASS_GAP_SECONDS:
            return None
    return idx


def needed_pass_ids(passes: list[dict], end: int, thresholds: Thresholds = V0) -> set[int]:
    """Every pass id whose quotes ``detect`` reads for ``passes[end]``."""
    ids = set()
    for i in _persist_indexes(passes, end, thresholds.persist_passes) or [end]:
        ids.add(passes[i]["id"])
        for w in thresholds.windows:
            s = window_start(passes, i, w)
            if s is not None:
                ids.add(passes[s]["id"])
    return ids


@dataclass
class _Reading:
    kind: str
    subject: str  # symbol or group name
    direction: str
    window: int
    relative: float  # signed
    start: int  # pass index
    end: int
    detail: dict


def _readings(universe: dict, passes: list[dict], end: int, minutes: int, quotes: dict, t: Thresholds) -> list[_Reading]:
    start = window_start(passes, end, minutes)
    if start is None:
        return []
    a, b = quotes.get(passes[start]["id"], {}), quotes.get(passes[end]["id"], {})

    def move(symbol):
        qa, qb = a.get(symbol), b.get(symbol)
        return _ret(qa["last"], qb["last"]) if usable(qa) and usable(qb) else None

    spy = move("SPY")
    if spy is None:
        return []
    out: list[_Reading] = []
    rel_spy: dict[str, float] = {}
    for row in universe["symbols"]:
        sym = row["symbol"]
        if row["kind"] != "stock" or row["benchmark"]:
            continue
        own = move(sym)
        if own is None:
            continue
        rel = own - spy
        rel_spy[sym] = rel
        floor = abs(own) >= t.own_move_floor_pct
        if floor and abs(rel) >= t.spy_relative_pct:
            out.append(_Reading("relative_to_spy", sym, "up" if rel > 0 else "down", minutes, rel, start, end,
                                {"own": own, "bench": spy, "benchmark": "SPY"}))
        sector = row.get("sector")
        sector_move = move(sector) if sector else None
        if sector_move is not None and floor and abs(own - sector_move) >= t.sector_relative_pct:
            rel_s = own - sector_move
            out.append(_Reading("relative_to_sector", sym, "up" if rel_s > 0 else "down", minutes, rel_s, start, end,
                                {"own": own, "bench": sector_move, "benchmark": sector, "spy_relative": rel}))
    for group in universe["groups"]:
        members = {m: rel_spy[m] for m in group["members"] if m in rel_spy}
        if len(members) < t.group_min_members:
            continue
        mid = median(members.values())
        if abs(mid) < t.group_relative_pct:
            continue
        sign = 1 if mid > 0 else -1
        same = {m: r for m, r in members.items() if r * sign > 0}
        if len(same) / len(members) < t.group_agreement:
            continue
        out.append(_Reading("group_move", group["name"], "up" if sign > 0 else "down", minutes, mid, start, end,
                            {"members": members, "same": same, "total": len(group["members"]), "spy": spy,
                             "missing": [m for m in group["members"] if m not in members]}))
    return out


def _key(r: _Reading) -> tuple[str, str, str]:
    return (r.kind, r.subject, r.direction)


def _qualifying(universe, passes, end, quotes, t: Thresholds) -> dict[tuple, _Reading]:
    """Keys that qualify on the last ``persist_passes`` consecutive passes on one window; the larger reading wins."""
    idx = _persist_indexes(passes, end, t.persist_passes)
    if idx is None:
        return {}
    found: dict[tuple, _Reading] = {}
    for w in t.windows:
        held: dict[tuple, _Reading] | None = None
        for i in idx:
            now = {(_key(r)): r for r in _readings(universe, passes, i, w, quotes, t)}
            held = now if held is None else {k: now[k] for k in held if k in now}
        for k, r in (held or {}).items():
            if k not in found or abs(r.relative) > abs(found[k].relative):
                found[k] = r
    return found


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def event_id(session_date: str, kind: str, subject: str, direction: str, n: int) -> str:
    return f"rv0-{session_date}-{_KIND_TAG[kind]}-{_slug(subject)}-{direction}-{n}"


def _evidence(passes, quotes, index: int, symbols: list[str]) -> list[RadarEvidence]:
    p = passes[index]
    rows = []
    for sym in symbols:
        q = quotes.get(p["id"], {}).get(sym)
        if usable(q):
            rows.append({"symbol": sym, "pass_id": p["id"], "retrieved_at": q["retrieved_at"], "last": q["last"],
                         "change_pct": round(_ret(q["prev_close"], q["last"]), 3)})
    return rows


def _day_change(quotes, pass_id, symbol) -> float:
    q = quotes[pass_id][symbol]
    return round(_ret(q["prev_close"], q["last"]), 3)


def _coverage(passes, end: int, missing: list[str]) -> dict:
    started = datetime.fromtimestamp(_epoch(passes[end]["started_at"]), ET)
    minute = started.hour * 60 + started.minute
    return {"passes_expected": max(1, minute - REGULAR_OPEN + 1), "passes_recorded": end + 1, "symbols_missing": missing}


def _build_event(r: _Reading, n: int, universe_version: str, passes, quotes, own_events: set[str]) -> RadarEvent:
    session = passes[r.end]["session_date"]
    end_id = passes[r.end]["id"]
    ahead = "ahead of" if r.direction == "up" else "behind"
    if r.kind == "group_move":
        d = r.detail
        ordered = sorted(d["same"], key=lambda m: (-abs(d["same"][m]), m))
        top = ordered[0]
        share = abs(d["same"][top]) / sum(abs(v) for v in d["same"].values())
        listed = [m for m in ordered if m in own_events]
        summary = (f"{r.subject} {ahead} SPY: {len(d['same'])} of {len(d['members'])} members "
                   f"{'up' if r.direction == 'up' else 'down'} vs SPY over {r.window} min, median {_pct(r.relative)} "
                   f"(biggest {top} {_pct(d['same'][top])}; SPY {_pct(d['spy'])})")
        if share > DOMINANT_SHARE:
            summary += f"; mostly {top}"
        if listed:
            summary += f". Own alerts: {', '.join(listed)}"
        members = sorted(d["members"])
        evidence = _evidence(passes, quotes, r.start, members + ["SPY"]) + _evidence(passes, quotes, r.end, members + ["SPY"])
        measures = {"median_relative_pct": round(r.relative, 3), "members_same_direction": len(d["same"]),
                    "members_with_data": len(d["members"]), "members_total": d["total"],
                    "top_member_relative_pct": round(d["same"][top], 3), "top_member_share_pct": round(share * 100, 1),
                    "spy_change_pct": round(d["spy"], 3), "window_minutes": r.window}
        symbols, benchmark, group, chart_symbol, missing = ordered, "SPY", r.subject, top, d["missing"]
    else:
        d = r.detail
        sym, bench = r.subject, d["benchmark"]
        against = "SPY" if r.kind == "relative_to_spy" else f"its sector {bench}"
        summary = (f"{sym} {ahead} {against} by {abs(r.relative):.1f}% over {r.window} min "
                   f"({sym} {_pct(d['own'])}, {bench} {_pct(d['bench'])})")
        evidence = _evidence(passes, quotes, r.start, [sym, bench]) + _evidence(passes, quotes, r.end, [sym, bench])
        measures = {"relative_pct": round(r.relative, 3), "change_pct": round(d["own"], 3),
                    "benchmark_change_pct": round(d["bench"], 3), "day_change_pct": _day_change(quotes, end_id, sym),
                    "window_minutes": r.window}
        if r.kind == "relative_to_sector":
            measures["spy_relative_pct"] = round(d["spy_relative"], 3)
        symbols, benchmark, group, chart_symbol, missing = [sym], bench, None, sym, []
    return {"event_id": event_id(session, r.kind, r.subject, r.direction, n), "session_date": session,
            "rule_version": RULE_VERSION, "universe_version": universe_version, "kind": r.kind,
            "direction": r.direction, "symbols": symbols, "benchmark": benchmark, "group": group,
            "first_seen_at": passes[r.end]["finished_at"], "summary": summary, "measures": measures,
            "evidence": evidence, "coverage": _coverage(passes, r.end, missing),
            "chart": {"symbol": chart_symbol, "from": passes[r.start]["started_at"], "to": passes[r.end]["finished_at"]}}


@dataclass
class _State:
    event: dict
    revisions: list[dict]

    @property
    def active(self) -> bool:
        return not any(r["status"] in ("faded", "reversed") for r in self.revisions)

    @property
    def closed_at(self) -> float | None:
        ends = [r["recorded_at"] for r in self.revisions if r["status"] in ("faded", "reversed")]
        return _epoch(ends[-1]) if ends else None

    @property
    def level(self) -> float:
        """The highest reported reading in the event's direction: the original, then each extension."""
        key = "median_relative_pct" if self.event["kind"] == "group_move" else "relative_pct"
        sign = 1 if self.event["direction"] == "up" else -1
        values = [self.event["measures"][key]] + [r["measures"][key] for r in self.revisions if r["status"] == "extended"]
        return max(v * sign for v in values)

    @property
    def last_pass_id(self) -> int:
        rows = self.event["evidence"] + [e for r in self.revisions for e in r["evidence"]]
        return max(e["pass_id"] for e in rows)


def _anchor(event: dict) -> dict[str, float]:
    first = min(e["pass_id"] for e in event["evidence"])
    return {e["symbol"]: e["last"] for e in event["evidence"] if e["pass_id"] == first}


def _track(state: _State, passes, end: int, quotes, t: Thresholds) -> RadarEventRevision | None:
    event, p = state.event, passes[end]
    if p["id"] <= state.last_pass_id:
        return None
    now = quotes.get(p["id"], {})
    anchor = _anchor(event)
    sign = 1 if event["direction"] == "up" else -1

    def since(sym):
        return _ret(anchor[sym], now[sym]["last"]) if sym in anchor and usable(now.get(sym)) else None

    minutes = round((_epoch(p["started_at"]) - _epoch(event["chart"]["from"])) / 60)
    if event["kind"] == "group_move":
        spy = since("SPY")
        moves = {m: since(m) for m in sorted(set(anchor) - {"SPY"})}
        rels = {m: v - spy for m, v in moves.items() if v is not None and spy is not None}
        if len(rels) < t.group_min_members:
            return None
        relative, threshold, step = median(rels.values()), t.group_relative_pct, t.group_extend_step_pct
        measures = {"median_relative_pct": round(relative, 3), "members_with_data": len(rels),
                    "spy_change_pct": round(spy, 3), "minutes_since_start": minutes}
        evidence = _evidence(passes, quotes, end, sorted(rels) + ["SPY"])
        what = "median member"
    else:
        sym, bench = event["symbols"][0], event["benchmark"]
        own, ref = since(sym), since(bench)
        if own is None or ref is None:
            return None
        relative = own - ref
        threshold = t.spy_relative_pct if event["kind"] == "relative_to_spy" else t.sector_relative_pct
        step = t.extend_step_pct
        measures = {"relative_pct": round(relative, 3), "change_pct": round(own, 3), "benchmark_change_pct": round(ref, 3),
                    "minutes_since_start": minutes}
        evidence = _evidence(passes, quotes, end, [sym, bench])
        what = f"{sym} vs {bench}"
    r, level = relative * sign, state.level
    if r <= -threshold:
        status, note = "reversed", f"Reversed: {what} now {_pct(relative)} since the move began ({minutes} min ago)."
    elif r < level / 2:
        status, note = "faded", f"Faded: {what} back to {_pct(relative)} from a peak of {_pct(level * sign)}."
    elif r >= level + step:
        status, note = "extended", f"Extended: {what} now {_pct(relative)} since the move began (was {_pct(level * sign)})."
    else:
        return None
    return {"event_id": event["event_id"], "revision": len(state.revisions) + 1, "recorded_at": p["finished_at"],
            "status": status, "measures": measures, "evidence": evidence, "note": note}


def _event_key(event: dict) -> tuple[str, str, str]:
    return (event["kind"], event["group"] if event["kind"] == "group_move" else event["symbols"][0], event["direction"])


def detect(universe: dict, passes: list[dict], end: int, quotes: dict[int, dict[str, dict]],
           saved: list[tuple[dict, list[dict]]], thresholds: Thresholds = V0) -> tuple[list[RadarEvent], list[RadarEventRevision]]:
    """New events and revisions for ``passes[end]``.

    ``passes`` is ``session_passes`` for one session, ``quotes`` maps pass id to {symbol: quote row} for at least
    ``needed_pass_ids``, and ``saved`` is the session's events (in saved order) with their revisions.
    """
    t = thresholds
    states: dict[tuple, list[_State]] = {}
    for event, revisions in saved:
        states.setdefault(_event_key(event), []).append(_State(event, list(revisions)))
    now = _epoch(passes[end]["started_at"])

    revisions: list[RadarEventRevision] = []
    for chain in states.values():
        state = chain[-1]
        if state.active:
            revision = _track(state, passes, end, quotes, t)
            if revision:
                state.revisions.append(revision)
                revisions.append(revision)

    def active(key) -> bool:
        return bool(states.get(key)) and states[key][-1].active

    found = _qualifying(universe, passes, end, quotes, t)
    order = sorted(found, key=lambda k: (("relative_to_spy", "relative_to_sector", "group_move").index(k[0]), k[1], k[2]))
    events: list[RadarEvent] = []
    for key in order:
        kind, subject, direction = key
        if active(key):
            continue
        chain = states.get(key, [])
        closed = chain[-1].closed_at if chain else None
        if closed is not None and now - closed < t.cooldown_minutes * 60:
            continue
        if kind == "relative_to_sector" and (active(("relative_to_spy", subject, direction))
                                             or found[key].detail["spy_relative"] * found[key].relative > 0
                                             and abs(found[key].detail["spy_relative"]) >= t.spy_relative_pct):
            continue  # the stock is moving against SPY just as much: an SPY event says this, not a sector one
        own = {k[1] for k in states if k[0] == "relative_to_spy"}  # members with their own SPY event this session
        event = _build_event(found[key], len(chain) + 1, passes[end]["universe_version"], passes, quotes, own)
        states.setdefault(key, []).append(_State(event, []))
        events.append(event)
    return events, revisions


def replay(universe: dict, passes: list[dict], quotes: dict[int, dict[str, dict]],
           thresholds: Thresholds = V0) -> list[tuple[dict, list[dict]]]:
    """Every event (with its revisions) the rules write over one session's passes, in order."""
    saved: list[tuple[dict, list[dict]]] = []
    by_id: dict[str, list[dict]] = {}
    for end in range(len(passes)):
        events, revisions = detect(universe, passes, end, quotes, saved, thresholds)
        for revision in revisions:
            by_id[revision["event_id"]].append(revision)
        for event in events:
            by_id[event["event_id"]] = []
            saved.append((event, by_id[event["event_id"]]))
    return saved
