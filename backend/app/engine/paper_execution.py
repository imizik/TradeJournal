"""Paper execution for Practice plans (A2): a pure event reducer.

A saved and armed long-share plan (A1) moves through two kinds of completed bars:
regular-session 15-minute bars decide the trigger, and one-minute bars decide the
fill and every exit. Nothing here reads a clock, a database or the network. The
worker hands in the bars and the moment it saw them, and stores the events these
functions return. ``fold`` rebuilds a position from stored events alone, so a
restart, or a later change to the decision rules here, cannot alter a past outcome.

The rules are ``docs/agent/practice-policy.md``'s, which names ``p0-cost-v1``:

- A 15-minute close strictly above the trigger, judged on a bar that closed after
  arming and no later than the plan's expiry, is the trigger. The order is
  eligible for the first full one-minute bar *starting* after the moment the
  trigger was detected, and fills at that bar's open plus adverse slippage.
- The fill is refused when that open is at or through the stop, at or beyond the
  target, or outside the frozen entry guard. A trigger seen later than
  ``MAX_DETECTION_DELAY`` after its bar closed is a missed trigger, never a
  backdated entry.
- Stop and target rest from entry, the entry minute included. A bar that opens
  through the stop exits at that open; a bar that touches both exits at the stop
  and is flagged ambiguous; a target never fills better than the target. The
  second session's last regular minute closes what is left (the entry session
  is session one).
- A one-minute bar missing from the supplied sequence is never filled forward:
  the position becomes ``unresolved``.

``advance`` is stateless over bars: it is handed every bar from the entry (or
detection) minute onward, skips what an earlier event already settled, and
returns only new events, so judging the same bars twice, or in chunks across a
restart, yields the same events.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

EXEC_VERSION = "p0-exec-v1"
# Seconds a trigger may be detected after its 15-minute bar closed and still be acted on.
# The practice policy asks for an "allowable delay" without a number; this is the proposal.
MAX_DETECTION_DELAY = 300
TERMINAL = frozenset({"closed", "expired", "missed", "rejected", "unresolved"})
MINUTE = 60


@dataclass(frozen=True)
class Terms:
    """The numbers of one frozen A1 TAKE plan, as epoch seconds and shares-prices."""

    trigger: float
    stop: float
    target: float
    guard_min: float
    guard_max: float
    expiry: float
    hold_sessions: int
    slippage_bps: float
    slippage_per_share: float
    risk_per_share: float
    cost_version: str


@dataclass(frozen=True)
class Session:
    """One regular session: ``open_at`` and ``close_at`` are UTC epoch seconds (an early close ends earlier)."""

    day: str
    open_at: int
    close_at: int


@dataclass(frozen=True)
class Paper:
    """A position projected from its events; ``status`` is one of the strings in the policy."""

    status: str = "unarmed"
    armed_at: float | None = None
    trigger: dict | None = None
    order_intent: dict | None = None
    entry: dict | None = None
    exit: dict | None = None
    ended: dict | None = None  # the event that ended a plan with no exit: expired, missed, rejected or unresolved


def terms_from_plan(plan: dict) -> Terms:
    """Read a validated A1 plan; a plan A1 would have refused raises ``ValueError``."""
    try:
        guard, costs = plan["entry_guard"], plan["cost_model"]
        expiry = datetime.fromisoformat(str(plan["expiry"]).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("plan.expiry must include a timezone")
        terms = Terms(
            trigger=float(plan["trigger_level"]), stop=float(plan["stop"]), target=float(plan["target"]),
            guard_min=float(guard["min"]), guard_max=float(guard["max"]), expiry=expiry.timestamp(),
            hold_sessions=int(plan["max_holding_sessions"]), slippage_bps=float(costs["slippage_bps"]),
            slippage_per_share=float(costs["slippage_per_share"]), risk_per_share=float(plan["initial_risk_per_share"]),
            cost_version=str(costs["version"]),
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"plan is missing a paper-execution field: {exc}") from exc
    numbers = (terms.trigger, terms.stop, terms.target, terms.guard_min, terms.guard_max, terms.slippage_bps,
               terms.slippage_per_share, terms.risk_per_share)
    if not all(math.isfinite(n) for n in numbers) or terms.hold_sessions < 1:
        raise ValueError("plan prices, costs and hold must be finite")
    if not 0 < terms.stop < terms.trigger < terms.target or terms.slippage_bps < 0 or terms.slippage_per_share < 0:
        raise ValueError("plan must satisfy 0 < stop < trigger < target with nonnegative costs")
    return terms


# ------------------------------------------------------------------ prices


def slip(price: float, terms: Terms, factor: float = 1.0) -> float:
    """Adverse slippage per share: basis points of the side's reference price plus a fixed amount."""
    return factor * (price * terms.slippage_bps / 10_000 + terms.slippage_per_share)


def outcome(state: Paper, terms: Terms, factor: float = 1.0) -> dict | None:
    """A closed position's result at ``factor`` times the cost parameters; None until it is closed.

    Fills are recomputed from the stored reference prices, so ``factor=1`` equals the stored fills and
    ``factor=3`` is the triple-cost view without touching the base outcome. R is net per share over the
    frozen trigger-minus-stop unit; the entry-to-stop exposure is shown separately.
    """
    if state.status != "closed" or state.entry is None or state.exit is None:
        return None
    entry = state.entry["reference"] + slip(state.entry["reference"], terms, factor)
    leave = state.exit["reference"] - slip(state.exit["reference"], terms, factor)
    net = leave - entry
    return {"cost_version": terms.cost_version if factor == 1 else f"{terms.cost_version}-x{factor:g}",
            "entry_fill": entry, "exit_fill": leave, "net_per_share": net,
            "planned_r": net / terms.risk_per_share, "entry_to_stop_exposure": entry - terms.stop,
            "exit_kind": state.exit["kind"], "ambiguous": state.exit["ambiguous"], "gap": state.exit["gap"]}


# ------------------------------------------------------------------ events


def arm_event(armed_at: float) -> dict:
    return {"type": "armed", "key": "armed", "at": armed_at, "exec_version": EXEC_VERSION}


def apply(state: Paper, event: dict) -> Paper:
    """Move one event into the projection. Decides nothing: a stored event is the whole truth."""
    kind = event["type"]
    if kind == "armed":
        return replace(state, status="armed", armed_at=event["at"])
    if kind == "trigger":
        return replace(state, status="triggered", trigger=event)
    if kind == "order_intent":
        return replace(state, order_intent=event)
    if kind == "entry":
        return replace(state, status="open", entry=event)
    if kind == "exit":
        return replace(state, status="closed", exit=event)
    ending = {"expired": "expired", "missed_trigger": "missed", "entry_rejected": "rejected", "unresolved": "unresolved"}
    if kind in ending:
        return replace(state, status=ending[kind], ended=event)
    raise ValueError(f"unknown paper event type: {kind}")


def fold(events: list[dict]) -> Paper:
    state = Paper()
    for event in events:
        state = apply(state, event)
    return state


class _Run:
    """Collects the events one call produces and keeps the projection current while it decides."""

    def __init__(self, state: Paper, reconstructed: bool):
        self.state, self.events, self.reconstructed = state, [], reconstructed

    def emit(self, event_type: str, at: float, **fields) -> None:
        event = {"type": event_type, "key": event_type, "at": at, **fields}
        if self.reconstructed:
            event["reconstructed"] = True
        self.events.append(event)
        self.state = apply(self.state, event)


# ------------------------------------------------------------------ the trigger


def watch(state: Paper, terms: Terms, bars15: list[dict], detected_at: float) -> list[dict]:
    """Judge completed regular-session 15-minute bars ``{start, end, close}`` seen at ``detected_at``.

    Only a bar that closed after arming, at or before the plan's expiry and no later than ``detected_at``
    can trigger. The first qualifying close decides: it is a trigger, or a missed trigger when it was
    detected more than ``MAX_DETECTION_DELAY`` after it closed.
    """
    run = _Run(state, False)
    if state.status != "armed":
        return []
    for bar in sorted(bars15, key=lambda b: b["end"]):
        _finite(bar["end"], bar["close"])
        if bar["end"] <= state.armed_at or bar["end"] > terms.expiry or bar["end"] > detected_at:
            continue
        if not bar["close"] > terms.trigger:
            continue
        delay = detected_at - bar["end"]
        facts = {"bar_start": bar["start"], "bar_end": bar["end"], "close": bar["close"], "level": terms.trigger,
                 "detected_at": detected_at, "delay_seconds": delay}
        if delay > MAX_DETECTION_DELAY:
            run.emit("missed_trigger", bar["end"], reason="detected_late", **facts)
        else:
            run.emit("trigger", bar["end"], **facts)
        break
    return run.events


def end_unresolved(state: Paper, at: float, reason: str) -> list[dict]:
    """End a triggered or open position whose outcome cannot be judged exactly, for example across a split."""
    if state.status not in ("triggered", "open"):
        return []
    run = _Run(state, False)
    run.emit("unresolved", at, stage="entry" if state.status == "triggered" else "hold", reason=reason)
    return run.events


def check_expiry(state: Paper, terms: Terms, now: float) -> list[dict]:
    """An untriggered plan ends once no still-acceptable close at or before its expiry can arrive."""
    if state.status == "armed" and now > terms.expiry + MAX_DETECTION_DELAY:
        run = _Run(state, False)
        run.emit("expired", terms.expiry, expiry=terms.expiry, checked_at=now)
        return run.events
    return []


# ------------------------------------------------------------------ the fill and the exits


def advance(state: Paper, terms: Terms, bars: list[dict], sessions: list[Session], *,
            reconstructed: bool = False, durable_at: float | None = None) -> list[dict]:
    """Judge completed one-minute bars ``{start, o, h, l, c}`` and return the new events.

    ``bars`` must hold every regular minute from the first the position needs (the eligible entry minute,
    or the entry minute when already open) onward; earlier ones are skipped. ``sessions`` are the regular
    sessions from the entry day on, as far as the calendar knows them. Minutes outside a session are ignored; a minute
    missing between two supplied ones makes the position ``unresolved``. ``durable_at`` is when the
    trigger was stored: the entry minute must start after both detection and that moment.
    """
    if state.status not in ("triggered", "open"):
        return []
    run = _Run(state, reconstructed)
    if state.status == "triggered":
        expected = _next_minute(max(state.trigger["detected_at"], durable_at or 0,
                                    state.order_intent["at"] if state.order_intent else 0))
    else:
        expected = state.entry["bar_start"]
    hold_end = None
    for bar in _regular(bars, sessions):
        if bar["start"] < expected:
            continue
        stage = "entry" if run.state.status == "triggered" else "hold"
        if bar["start"] > expected:
            run.emit("unresolved", expected, stage=stage, reason="missing one-minute bars",
                     from_start=expected, to_start=bar["start"])
            break
        session = _session_of(bar["start"], sessions)
        if run.state.status == "triggered" and not _enter(run, terms, bar):
            break
        if hold_end is None:
            hold_end = _hold_end(run.state, terms, sessions)  # None until the calendar covers it
        if _leave(run, terms, bar, session, hold_end):
            break
        expected = _after(bar["start"], session, sessions)
    return run.events


def _enter(run: _Run, terms: Terms, bar: dict) -> bool:
    ref = bar["o"]
    refusal = ("at_or_below_stop" if ref <= terms.stop else "at_or_above_target" if ref >= terms.target
               else "above_guard" if ref > terms.guard_max else "below_guard" if ref < terms.guard_min else None)
    if refusal is None:
        fill = ref + slip(ref, terms)
        exposure = fill - terms.stop
        if exposure <= 0:
            refusal = "nonpositive_exposure"
    if refusal is not None:
        run.emit("entry_rejected", bar["start"], bar_start=bar["start"], reference=ref, reason=refusal)
        return False
    run.emit("entry", bar["start"], bar_start=bar["start"], reference=ref, fill=fill, slippage=fill - ref,
             entry_to_stop_exposure=exposure, cost_version=terms.cost_version)
    return True


def _leave(run: _Run, terms: Terms, bar: dict, session: Session, hold_end: Session) -> bool:
    """Stop, target, then the time exit, on one minute. True when the position closed."""
    first = bar["start"] == run.state.entry["bar_start"]  # its open is the fill, so it cannot gap
    if not first and bar["o"] <= terms.stop:
        return _close(run, terms, bar, "stop", bar["o"], gap=True)
    if not first and bar["o"] >= terms.target:
        return _close(run, terms, bar, "target", terms.target, gap=True)  # no better than the target
    hit_stop, hit_target = bar["l"] <= terms.stop, bar["h"] >= terms.target
    if hit_stop:
        return _close(run, terms, bar, "stop", terms.stop, ambiguous=hit_target)
    if hit_target:
        return _close(run, terms, bar, "target", terms.target)
    if session == hold_end and bar["start"] == session.close_at - MINUTE:
        return _close(run, terms, bar, "time", bar["c"], at=session.close_at)
    return False


def _close(run: _Run, terms: Terms, bar: dict, kind: str, reference: float, *, gap: bool = False,
           ambiguous: bool = False, at: float | None = None) -> bool:
    run.emit("exit", bar["start"] if at is None else at, kind=kind, bar_start=bar["start"], reference=reference,
             fill=reference - slip(reference, terms), gap=gap, ambiguous=ambiguous, cost_version=terms.cost_version)
    return True


# ------------------------------------------------------------------ sessions and bars


def _finite(*values: float) -> None:
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError("bars must carry finite numbers")


def _next_minute(moment: float) -> int:
    return (int(moment) // MINUTE + 1) * MINUTE


def _session_of(start: int, sessions: list[Session]) -> Session:
    for session in sessions:
        if session.open_at <= start < session.close_at:
            return session
    raise ValueError("bar is outside the supplied sessions")


def _after(start: int, session: Session, sessions: list[Session]) -> int:
    """The minute that must follow ``start``: the next one, or the next session's open."""
    if start + MINUTE < session.close_at:
        return start + MINUTE
    later = [s for s in sessions if s.open_at >= session.close_at]
    return min(s.open_at for s in later) if later else session.close_at


def _hold_end(state: Paper, terms: Terms, sessions: list[Session]) -> Session | None:
    """The hold's last session; None when ``sessions`` stop short of it (the calendar has not published it).

    Stop and target are still judged meanwhile: minutes of an uncovered session are outside ``sessions``
    and are ignored, so nothing is judged past what the calendar can place.
    """
    ordered = sorted(sessions, key=lambda s: s.open_at)
    entry = _session_of(state.entry["bar_start"], ordered)
    last = ordered.index(entry) + terms.hold_sessions - 1
    return ordered[last] if last < len(ordered) else None


def _regular(bars: list[dict], sessions: list[Session]) -> list[dict]:
    """Validated regular-session minutes in order; a repeated minute is a caller error."""
    seen, kept = set(), []
    for bar in bars:
        _finite(bar["start"], bar["o"], bar["h"], bar["l"], bar["c"])
        if min(bar["o"], bar["h"], bar["l"], bar["c"]) <= 0 or bar["l"] > min(bar["o"], bar["c"]) or bar["h"] < max(bar["o"], bar["c"]):
            raise ValueError("bar prices must be positive with low <= open, close <= high")
        if bar["start"] in seen:
            raise ValueError("a one-minute bar was supplied twice")
        seen.add(bar["start"])
        if any(s.open_at <= bar["start"] < s.close_at for s in sessions):
            kept.append(bar)
    return sorted(kept, key=lambda b: b["start"])
