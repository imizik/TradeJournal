"""The day call (docs/copilot-lab.md § The day call): Claude's risk-on or risk-off read of the session, kept as a thread
it follows through the day, on paper until it earns a place.

- **The opening call.** At ``FIRST_CALL`` (09:45 New York, once the opening range and VWAP exist) Claude is asked once
  through the Anthropic API (``api_runner.ask``, on API credits and the monthly cap): from the session's facts (SPY's
  minutes against its VWAP and opening range, the indices' day from Radar, VIX, the 10-year, today's macro calendar) it
  says ``risk_on``, ``risk_off`` or ``mixed``, why, and one to three things that would flip it, each written as a check
  the code can run (``FLIP_METRICS`` above or below a number).
- **Following its thread.** Every ``RUN_SECONDS`` in the regular session the code (no model) checks those conditions
  against the live facts. A condition that holds for ``CONFIRM_CHECKS`` checks in a row, or SPY moving ``SHARP_PCT`` or
  more from the price at the last call, asks Claude again with the whole day's thread: its earlier calls, what each said
  would flip it and what just tripped. It holds or flips, and writes new conditions. At most ``MAX_CALLS`` calls a day,
  at least ``MIN_GAP_MINUTES`` apart.
- **Paper score.** After the close each call is scored on SPY from that call to the next one (or the close): a
  ``risk_on`` call is right when SPY rose, ``risk_off`` when it fell; ``mixed`` is not scored. ``record`` sums every
  saved day, so the desk can show whether the calls are worth listening to.
- **Where it shows.** The desk's copilot column (``GET /copilot/desk/day-call``). A call that changes sends one silent
  ping only with ``DAY_CALL_PINGS=true`` (kind ``day_call``, through the notification policy).

Nothing here places, sizes or arms an order. Off unless ``DAY_CALL_ENABLED=true`` (the owner's switch: new paid
background work is his to start); it runs on the level-alert monitor's loop and never raises into it. Its reads, checks
and asks run on a thread of its own so a slow feed or answer never holds the monitor; no call is made without SPY's
minutes or on a day the market calendar cannot confirm, none starts after ``LAST_OPENING``, and ``MAX_FAILURES`` failed
asks stop the day. Each day is ``data/day_call/<day>.json``; no table.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from app.engine.chart_math import ET, session_windows

log = logging.getLogger(__name__)

KIND = "day_call"
SENDER = "day_call"
ROOT = Path(__file__).resolve().parents[2] / "data" / "day_call"
RUN_SECONDS = 60
FIRST_CALL = 9 * 60 + 45
LAST_OPENING = 10 * 60 + 30  # a process that starts later makes no call that day (it would not be an opening call)
MAX_FAILURES = 3  # failed asks in a day before the day stops (a failed ask can still be billed)
CONFIRM_CHECKS = 2  # a flip condition must hold this many checks in a row (about two minutes)
SHARP_PCT = 0.5  # SPY's move from the last call's price that asks again without a condition tripping
MAX_CALLS = 5
MIN_GAP_MINUTES = 20
RETRY_SECONDS = 600  # after a failed ask
SCORE_UNTIL = 17 * 60  # the close is scored on the first pass after it, until this minute
CALLS = ("risk_on", "risk_off", "mixed")
FLIP_METRICS = {
    "spy_price": "SPY's last price",
    "spy_vs_vwap_pct": "SPY's percent above (+) or below (-) its session VWAP",
    "spy_from_open_pct": "SPY's percent change from today's 09:30 open",
    "spy_day_pct": "SPY's percent change from the previous close (Radar)",
    "qqq_day_pct": "QQQ's percent change from the previous close (Radar)",
    "iwm_day_pct": "IWM's percent change from the previous close (Radar)",
    "rsp_minus_spy_pct": "RSP's day percent minus SPY's: breadth, equal weight against cap weight (Radar)",
    "vix": "VIX in index points",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "call": {"type": "string", "enum": list(CALLS)},
        "confidence": {"type": "number", "description": "0 to 1"},
        "read": {"type": "string", "description": "One or two plain sentences: why, from the facts given."},
        "changed": {"type": ["string", "null"], "description": "On a re-read: what changed since the last call, else null."},
        "flips": {
            "type": "array",
            "description": "One to three checks that would change this call.",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "enum": list(FLIP_METRICS)},
                    "op": {"type": "string", "enum": ["above", "below"]},
                    "value": {"type": "number"},
                    "why": {"type": "string", "description": "A few words: what it would mean."},
                },
                "required": ["metric", "op", "value", "why"],
            },
        },
    },
    "required": ["call", "confidence", "read", "changed", "flips"],
}

SYSTEM = """You make the day call for a retail options trader who trades 0-3 day SPY-complex and single-stock options.
The call is whether today's session is risk on (buyers in control: dips get bought, calls work), risk off (sellers in
control: rips get sold, puts work) or mixed (no side in control: chop, smaller and fewer trades).

Rules:
- Use only the facts in the message. Never invent a level, a headline or a number. A fact marked unavailable is unknown.
- "mixed" is a real answer: say it when the facts do not lean. A confident call on thin evidence is worse than mixed.
- Write one to three flip checks: things that, if they happen, would mean your call is wrong. Each is a metric from the
  list given, above or below a number, set from the current values so it is not already true and would take a real move
  to trip (not noise). A risk-on call flips on weakness, a risk-off call on strength, a mixed call on either side.
- On a re-read you get your earlier calls today and what just tripped. Change the call only when the session has truly
  changed sides, not because one check tripped; say what changed in "changed". Holding is fine.
- Plain words, no hedging boilerplate, no trade instructions."""


def enabled() -> bool:
    return os.environ.get("DAY_CALL_ENABLED", "").strip().lower() == "true"


def pings_enabled() -> bool:
    return os.environ.get("DAY_CALL_PINGS", "").strip().lower() == "true"


# ------------------------------------------------------------------ facts

def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def spy_facts(bars: list[dict], day: date, minute: int) -> dict:
    """SPY's regular session so far from its minute bars (``time`` epoch seconds, open/high/low/close/volume)."""
    lo = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET).timestamp()
    hi = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET).timestamp()
    rows = [b for b in bars if lo <= b["time"] < hi]
    if not rows:
        return {"state": "unavailable", "reason": "No SPY minutes for today's session yet."}
    volume = sum(b["volume"] for b in rows)
    vwap = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in rows) / volume if volume > 0 else None
    price, open_ = rows[-1]["close"], rows[0]["open"]
    first = rows[:15]
    back = next((b for b in reversed(rows) if b["time"] <= rows[-1]["time"] - 30 * 60), None)
    return {"state": "ok", "price": round(price, 2), "open": round(open_, 2), "vwap": round(vwap, 2) if vwap else None,
            "vs_vwap_pct": round((price / vwap - 1) * 100, 2) if vwap else None,
            "from_open_pct": round((price / open_ - 1) * 100, 2),
            "high": round(max(b["high"] for b in rows), 2), "low": round(min(b["low"] for b in rows), 2),
            "or15_high": round(max(b["high"] for b in first), 2) if len(first) == 15 else None,
            "or15_low": round(min(b["low"] for b in first), 2) if len(first) == 15 else None,
            "last_30m_pct": round((price / back["close"] - 1) * 100, 2) if back else None,
            "minutes": len(rows)}


def metrics(facts: dict) -> dict:
    """The flip checks' inputs from the facts; None where unknown (a check on an unknown metric never trips)."""
    spy = facts.get("spy") or {}
    radar = (facts.get("regime") or {}).get("radar") or {}
    indices = radar.get("indices") or {} if radar.get("state") == "ok" else {}

    def day(symbol):
        return _num((indices.get(symbol) or {}).get("day_pct"))
    spy_day, rsp_day = day("SPY"), day("RSP")
    vix = (facts.get("regime") or {}).get("vix") or {}
    return {"spy_price": _num(spy.get("price")), "spy_vs_vwap_pct": _num(spy.get("vs_vwap_pct")),
            "spy_from_open_pct": _num(spy.get("from_open_pct")), "spy_day_pct": spy_day, "qqq_day_pct": day("QQQ"),
            "iwm_day_pct": day("IWM"), "rsp_minus_spy_pct": round(rsp_day - spy_day, 3) if None not in (rsp_day, spy_day) else None,
            "vix": _num(vix.get("last")) if vix.get("state") == "ok" else None}


def live_facts(feed, now: float) -> dict:
    """Today's facts from the chart feed's SPY minutes and the copilot's regime read (Radar, VIX, 10-year, macro)."""
    from app.ai import copilot_regime
    moment = datetime.fromtimestamp(now, ET)
    try:
        bars = feed.today_minutes("SPY", now) if feed is not None else []
        spy = spy_facts(bars, moment.date(), moment.hour * 60 + moment.minute)
    except Exception as exc:  # noqa: BLE001 - a call on what is known, with the gap said
        spy = {"state": "unavailable", "reason": str(exc)[:200]}
    try:
        regime = copilot_regime.live_regime(None, datetime.fromtimestamp(now, ET))
    except Exception as exc:  # noqa: BLE001
        log.warning("day call regime unreadable", exc_info=True)
        regime = {"state": "unavailable", "reason": str(exc)[:200]}
    return {"time_et": moment.strftime("%H:%M"), "spy": spy, "regime": regime}


# ------------------------------------------------------------------ the thread

def _flip_text(flip: dict) -> str:
    return f"{flip['metric']} {flip['op']} {flip['value']:g} ({flip['why']})"


def tripped(call: dict, values: dict) -> list[dict]:
    """The call's flip checks that hold on these values."""
    out = []
    for flip in call.get("flips") or []:
        value = values.get(flip.get("metric"))
        if value is None or not isinstance(flip.get("value"), (int, float)):
            continue
        if (flip["op"] == "above" and value > flip["value"]) or (flip["op"] == "below" and value < flip["value"]):
            out.append(flip)
    return out


def prompt(facts: dict, calls: list[dict], trigger: str | None) -> str:
    lines = [f"Time now: {facts['time_et']} New York.", "",
             "Flip check metrics you may use: " + "; ".join(f"{k} = {v}" for k, v in FLIP_METRICS.items()), "",
             "Current values of those metrics: " + json.dumps(metrics(facts)), "",
             "Facts:", json.dumps({"spy": facts["spy"], "regime": facts["regime"]}, default=str)]
    if calls:
        lines += ["", "Your calls so far today, oldest first:"]
        for c in calls:
            lines.append(f"- {c['time_et']}: {c['call']} ({c['confidence']:.1f}), SPY {c.get('spy_price')}. {c['read']}"
                         + (f" Changed: {c['changed']}" if c.get("changed") else "")
                         + " Would flip if: " + "; ".join(_flip_text(f) for f in c.get("flips") or []) + ".")
        lines += ["", f"Asked again because: {trigger}", "Hold or change the call, and write fresh flip checks."]
    else:
        lines += ["", "Make the opening call for today."]
    return "\n".join(lines)


def clean(answer: dict) -> dict:
    """The model's answer, checked: a known call, a confidence in 0..1, at most three flip checks on known metrics."""
    call = answer.get("call") if answer.get("call") in CALLS else "mixed"
    try:
        confidence = min(1.0, max(0.0, float(answer.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    flips = [{"metric": f["metric"], "op": f["op"], "value": float(f["value"]), "why": str(f.get("why") or "")[:120]}
             for f in answer.get("flips") or []
             if isinstance(f, dict) and f.get("metric") in FLIP_METRICS and f.get("op") in ("above", "below")
             and isinstance(f.get("value"), (int, float))][:3]
    changed = answer.get("changed")
    return {"call": call, "confidence": round(confidence, 2), "read": str(answer.get("read") or "")[:600],
            "changed": str(changed)[:300] if changed else None, "flips": flips}


# ------------------------------------------------------------------ paper score

def score(calls: list[dict], close: float | None) -> dict:
    """Each call on SPY from its price to the next call's (or the close): right when a risk-on call saw SPY rise or a
    risk-off call saw it fall. ``mixed`` and calls with no price either side are not scored."""
    rows = []
    for i, c in enumerate(calls):
        start = c.get("spy_price")
        end = calls[i + 1].get("spy_price") if i + 1 < len(calls) else close
        move = round((end / start - 1) * 100, 3) if start and end else None
        right = None if move is None or c["call"] == "mixed" or move == 0 else (move > 0) == (c["call"] == "risk_on")
        rows.append({"time_et": c["time_et"], "call": c["call"], "spy_move_pct": move, "right": right})
    scored = [r for r in rows if r["right"] is not None]
    return {"close": close, "calls": rows, "scored": len(scored), "right": sum(1 for r in scored if r["right"]),
            "opening_right": rows[0]["right"] if rows else None}


def _file(day: str) -> Path:
    return ROOT / f"{day}.json"


def load(day: str) -> dict:
    try:
        found = json.loads(_file(day).read_text())
        return found if isinstance(found, dict) else {"day": day, "calls": []}
    except FileNotFoundError:
        return {"day": day, "calls": []}
    except (OSError, ValueError):
        log.warning("day call file unreadable for %s", day, exc_info=True)
        return {"day": day, "calls": []}


def save(state: dict) -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        tmp = _file(state["day"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(_file(state["day"]))
    except OSError:
        log.warning("day call could not be saved for %s", state.get("day"), exc_info=True)


def record() -> dict:
    """The paper record over every saved day: calls scored and right, and the opening calls alone."""
    days = scored = right = opening = opening_right = 0
    for path in sorted(ROOT.glob("*.json")) if ROOT.exists() else []:
        try:
            s = (json.loads(path.read_text()) or {}).get("score")
        except (OSError, ValueError):
            continue
        if not isinstance(s, dict):
            continue
        days += 1
        scored += int(s.get("scored") or 0)
        right += int(s.get("right") or 0)
        if s.get("opening_right") is not None:
            opening += 1
            opening_right += int(s["opening_right"])
    return {"days": days, "scored": scored, "right": right, "hit_rate": round(right / scored, 3) if scored else None,
            "opening_calls": opening, "opening_right": opening_right}


def view(now: float | None = None) -> dict:
    """What the desk shows: today's calls (newest last), the day's score once the close is in, and the paper record."""
    asked = time.time() if now is None else now
    day = datetime.fromtimestamp(asked, ET).date().isoformat()
    state = load(day)
    return {"enabled": enabled(), "day": day, "calls": state.get("calls") or [], "score": state.get("score"),
            "stopped": state.get("stopped"), "record": record()}


# ------------------------------------------------------------------ the pass

def _ask(system: str, message: str) -> tuple[dict, float, str]:
    from app.ai import api_runner
    answer = api_runner.ask(system, message, SCHEMA, kind=KIND)
    return answer.data, answer.usd, answer.model


class DayCalls:
    """The monitor-loop stage: the opening call, the code-run flip checks, the re-asks and the close's score."""

    def __init__(self, calendar=None, feed=None, *, clock: Callable[[], float] = time.time,
                 ask: Callable[[str, str], tuple[dict, float, str]] = _ask, facts: Callable | None = None,
                 background: bool = True):
        self.calendar = calendar
        self.feed = feed
        self.clock = clock
        self.ask = ask
        self.facts = facts or (lambda now: live_facts(self.feed, now))
        self.background = background  # tests run the ask inline
        self._last_run = 0.0
        self._streak: dict[str, int] = {}  # flip check text -> checks in a row it has held
        self._asking: threading.Thread | None = None
        self._retry_at = 0.0

    def run(self) -> None:
        try:
            self._run()
        except Exception:  # noqa: BLE001 - one bad pass never stops the monitor's other stages
            log.exception("Day call pass failed")

    def _regular(self, today: date) -> tuple[int, int] | None:
        """Today's regular session in minutes, from the market calendar only: a paid call is never made on the clock's
        guess, which cannot see holidays or early closes."""
        hours = self.calendar.hours(today) if self.calendar is not None else None
        if hours is None:
            return None
        regular = next((w for w in session_windows(today, hours) if w[0] == "regular"), None)
        return (regular[1], regular[2]) if regular else None

    def _run(self) -> None:
        """Cheap timing on the monitor's pass; the reads, the checks and any ask run on a thread of their own."""
        now = self.clock()
        if now - self._last_run < RUN_SECONDS or (self._asking is not None and self._asking.is_alive()):
            return
        self._last_run = now
        if self.background:
            self._asking = threading.Thread(target=self._guarded, args=(now,), name="day-call", daemon=True)
            self._asking.start()
        else:
            self._check(now)

    def _guarded(self, now: float) -> None:
        try:
            self._check(now)
        except Exception:  # noqa: BLE001
            log.exception("Day call check failed")

    def _check(self, now: float) -> None:
        moment = datetime.fromtimestamp(now, ET)
        today, minute = moment.date(), moment.hour * 60 + moment.minute
        session = self._regular(today)
        if session is None:
            return
        opens, closes = session
        state = load(today.isoformat())
        calls = state.get("calls") or []
        if minute >= closes:
            if calls and not state.get("score") and minute < SCORE_UNTIL:
                self._score(state, now, closes)
            return
        if state.get("stopped") or minute < max(FIRST_CALL, opens + 15) or len(calls) >= MAX_CALLS or now < self._retry_at:
            return
        if not calls and minute > LAST_OPENING:
            return
        facts = self.facts(now)
        if metrics(facts).get("spy_price") is None:  # no call without SPY's own minutes: retried next check
            return
        if not calls:
            self._call(state, facts, None, now)
            return
        last = calls[-1]
        values = metrics(facts)
        held = {_flip_text(f) for f in tripped(last, values)}
        self._streak = {k: self._streak.get(k, 0) + 1 for k in held}
        confirmed = [k for k, n in self._streak.items() if n >= CONFIRM_CHECKS]
        price, base = values.get("spy_price"), last.get("spy_price")
        sharp = price is not None and base and abs(price / base - 1) * 100 >= SHARP_PCT
        if not confirmed and not sharp:
            return
        if now - last["at"] < MIN_GAP_MINUTES * 60:
            return
        trigger = (f"flip check held for {CONFIRM_CHECKS} checks: {confirmed[0]}" if confirmed
                   else f"SPY moved {(price / base - 1) * 100:+.2f}% since the last call ({base} to {price})")
        self._call(state, facts, trigger, now)

    def _call(self, state: dict, facts: dict, trigger: str | None, now: float) -> None:
        from app.ai import api_runner
        calls = state.setdefault("calls", [])
        try:
            data, usd, model = self.ask(SYSTEM, prompt(facts, calls, trigger))
        except api_runner.ApiUnavailable as exc:  # no key, or the month's cap is spent: done for the day
            state["stopped"] = str(exc)[:300]
            save(state)
            log.warning("Day call stopped for the day: %s", exc)
            return
        except Exception:  # noqa: BLE001 - ApiCallFailed or worse: try again later, a few times a day at most
            self._retry_at = now + RETRY_SECONDS
            state["failures"] = int(state.get("failures") or 0) + 1
            if state["failures"] >= MAX_FAILURES:
                state["stopped"] = f"{state['failures']} asks failed today."
            save(state)
            log.warning("Day call ask failed", exc_info=True)
            return
        entry = {**clean(data), "at": now, "time_et": facts["time_et"], "trigger": trigger,
                 "spy_price": metrics(facts).get("spy_price"), "cost_usd": round(usd, 4), "model": model}
        previous = calls[-1]["call"] if calls else None
        calls.append(entry)
        self._streak = {}
        save(state)
        if previous is not None and previous != entry["call"] and pings_enabled():
            self._ping(state["day"], len(calls), previous, entry, now)

    def _score(self, state: dict, now: float, closes: int) -> None:
        day = date.fromisoformat(state["day"])
        try:
            bars = self.feed.today_minutes("SPY", now) if self.feed is not None else []
        except Exception:  # noqa: BLE001 - scored on a later pass
            log.warning("Day call close unreadable", exc_info=True)
            return
        spy = spy_facts(bars, day, closes)
        if spy.get("state") != "ok":
            return
        state["score"] = score(state["calls"], spy["price"])
        save(state)

    def _ping(self, day: str, number: int, previous: str, entry: dict, now: float) -> None:
        from sqlmodel import Session
        from app.database import engine
        from app.engine import notification_policy, phone
        if not phone.configured():
            return
        names = {"risk_on": "risk on", "risk_off": "risk off", "mixed": "mixed"}
        title = f"Day call: {names[entry['call']]} (was {names[previous]})"
        body = (entry.get("changed") or entry["read"]) + (
            " Flips if " + "; ".join(_flip_text(f) for f in entry["flips"]) + "." if entry["flips"] else "") + " Paper call, not a trade."
        with Session(engine) as db:
            ticket = notification_policy.decide(db, sender=SENDER, source_id=f"{KIND}:{day}:{number}", kind=KIND,
                                                title=title, body=body, now=now, new_only=True)
            if ticket.held:
                log.info("Day call ping held: %s", ticket.reason)
                return
            try:
                phone.send(title, body + ticket.append, kind=KIND, path=phone.desk_link("/"), priority=2)
            except phone.SendError as exc:
                log.warning("Day call ping not sent: %s", exc)
                return
            notification_policy.delivered(db, ticket, now)
            db.commit()
