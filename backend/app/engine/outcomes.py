"""Outcome attribution (docs/analytics.md § Outcomes): for every output the app makes, what the underlying did 1 hour,
1 trading day and 5 trading days later, what the owner did in the fills, and the dollars against the obvious
alternative. One ``Outcome`` row per output, filled in by the morning sync pipeline (``compute_outcomes``, after
fills and enrichment). Python only: no model call, and prices come from stored bars, never a price provider request
(the market calendar is its usual cached read: at most one Tradier calendar request a New York day per month).

**Subjects**, anchored at the output's moment (naive UTC), since ``OUTCOMES_SINCE`` (default 2026-10-21, the alerts'
go-live):

- ``ping``: every ``PhonePing``, anchored when it was delivered (else decided). Those the policy held (merged,
  suppressed, over cap) are rows too, ``held`` true, so they can serve as a control.
- ``plan``: every pre-trade plan (``TradeCapture``, the copilot's plan card included), anchored when it was saved.
- ``radar_event``: every Radar event (the store, read-only), anchored at its first sighting; a stock event on its
  stock, a group event on its top member (the evidence that moved most in the event's direction).
- ``research``: each saved Jo research record (``CopilotInvestigation.source == "jo"``) on its symbol; d1 and d5.
- ``shadow_decision``: each Shadow book plan or skip on its symbol; d1 and d5 (its own paper fills give its result).
- ``companion_update``: reserved for the position companion's updates once that table exists.

**Windows** (``h1``, ``d1``, ``d5``), from the stored minute sessions the charts keep on disk
(``chart_history.stored``: extended hours, 04:00-20:00 New York): ``h1`` ends 60 minutes after the anchor, ``dN``
at the regular close of the Nth trading day after the anchor's New York date (the market calendar, else weekdays).
Each is ``{price, pct, high, low, complete}``: the last minute's close before the end, its change from the reference
in percent, and the highest and lowest minute inside the window. A window still open, or one whose sessions are not
stored yet, is incomplete and recomputed next run; one still missing sessions ``STALE_DAYS`` after it ended is closed
with what there is (``missing`` says so). The reference price is the source's own price when it recorded the
underlying (Radar's evidence), else the close of the stored minute at or before the anchor.

**Action**, from the fills (naive New York): ``closed``, ``trimmed``, ``added`` or ``held`` when a position in the
symbol was open at the anchor, else ``entered`` or ``none``; ``unknown`` when it cannot be told (a ping with no symbol
or a position that can no longer be found). Windows: 15 minutes for an exit-kind ping (on its position's own fills),
30 for an entry trigger, every other ping and a Radar event, the d1 window for research; a plan is ``entered`` once
it is linked to a trade (else ``none``), a Shadow decision reads its paper book (``entered``, ``closed`` or ``none``).

**Alternative** (``alt_usd``): an open-trade alert's proceeds against closing its contracts at the alert's midpoint
mark (``exit_habits.follow_up``'s ``vs_alert``); a Radar event, one share taken at first sight in Radar's direction,
the scorecard's move against SPY to the session's last pass (``radar_scorecard``) times the price at first sight.
Nothing for the other kinds. Counts and price paths, not causation.
"""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time as wall_clock, timedelta
import json
import logging
import os
from statistics import median
from typing import Callable
import uuid

from sqlmodel import Session, select

from app.engine import capture_links, exit_habits, notification_policy
from app.engine.analytics import wall_time
from app.engine.chart_journal import OPEN_SIDES
from app.engine.chart_math import ET
from app.engine.copilot_plans import ENTRY_DAYS
from app.models import (CopilotInvestigation, Fill, Outcome, PhonePing, PositionAlert, ShadowBookDecision, ShadowBookEvent,
                        Trade, TradeCapture)

log = logging.getLogger(__name__)

VERSION = 1
SINCE = date(2026, 10, 21)  # POSITION_ALERTS_ENABLED=true on the VPS; OUTCOMES_SINCE overrides
RUN_CAP = 400  # subjects computed per run, oldest first; the rest wait for the next run
STALE_DAYS = 10  # a window still missing stored sessions this long after it ended is closed with what there is
KINDS = ("ping", "plan", "radar_event", "research", "shadow_decision", "companion_update")
ACTIONS = ("closed", "trimmed", "added", "held", "entered", "none", "unknown")
EXIT_MINUTES = notification_policy.EXIT_MINUTES  # 15
ENTRY_MINUTES = notification_policy.ENTRY_MINUTES  # 30
WINDOWS = ("h1", "d1", "d5")
DAYS = {"d1": 1, "d5": 5}
REGULAR_CLOSE = 16 * 60
EPS = 1e-9
ROWS_SHOWN = 200
SENT_POSITION_SENDER = "position_alerts"

Bars = Callable[[str, date], list[dict] | None]  # a stored session's minutes ({time, open, high, low, close}), or None
Hours = Callable[[date], dict | None]  # the market calendar's day ({status, close}), or None when unknown


def since() -> date:
    try:
        return date.fromisoformat(os.environ.get("OUTCOMES_SINCE", "").strip())
    except ValueError:
        return SINCE


# ------------------------------------------------------------------ time and calendar

def _epoch_utc(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _day_start(day: date) -> datetime:
    """Midnight New York on ``day``, as naive UTC."""
    return datetime.combine(day, wall_clock(), ET).astimezone(UTC).replace(tzinfo=None)


def _ny(moment: datetime) -> datetime:
    """A naive UTC moment as naive New York wall clock (fill times)."""
    return moment.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)


def _open(hours: Hours, day: date) -> bool:
    found = hours(day)
    return found["status"] == "open" if found else day.weekday() < 5


def _close(hours: Hours, day: date) -> float:
    found = hours(day)
    minutes = found.get("close") if found and found.get("close") is not None else REGULAR_CLOSE
    return datetime.combine(day, wall_clock(minutes // 60, minutes % 60), ET).timestamp()


def trading_days_after(hours: Hours, day: date, n: int) -> list[date]:
    """The first ``n`` trading days after ``day``."""
    out, cursor = [], day
    while len(out) < n:
        cursor += timedelta(days=1)
        if _open(hours, cursor):
            out.append(cursor)
    return out


# ------------------------------------------------------------------ price paths

def reference(bars: Bars, symbol: str, anchor: float) -> float | None:
    """The close of the stored minute at or before ``anchor`` on its New York day."""
    minutes = bars(symbol, datetime.fromtimestamp(anchor, ET).date()) or []
    before = [b for b in minutes if b["time"] <= anchor]
    return float(before[-1]["close"]) if before else None


def path(minutes: list[dict], ref: float | None, start: float, end: float, *, final: bool) -> dict:
    """One window from the stored minutes starting in [start, end): the last close, its change from ``ref`` in percent,
    the high and low inside, and whether it is final."""
    inside = [b for b in minutes if start <= b["time"] < end]
    price = float(inside[-1]["close"]) if inside else None
    return {"price": price,
            "pct": round((price / ref - 1) * 100, 2) + 0.0 if price is not None and ref else None,
            "high": max(float(b["high"]) for b in inside) if inside else None,
            "low": min(float(b["low"]) for b in inside) if inside else None,
            "complete": final}


def windows(bars: Bars, hours: Hours, symbol: str | None, anchored_at: datetime, ref: float | None, now: float,
            which: tuple[str, ...] = WINDOWS) -> dict[str, dict | None]:
    """``h1``, ``d1`` and ``d5`` for ``symbol`` from ``anchored_at`` (naive UTC); a kind left out of ``which`` is None."""
    out: dict[str, dict | None] = {w: None for w in WINDOWS}
    if not symbol:
        return {w: {"price": None, "pct": None, "high": None, "low": None, "complete": True, "missing": "no symbol"}
                if w in which else None for w in WINDOWS}
    anchor = _epoch_utc(anchored_at)
    day = datetime.fromtimestamp(anchor, ET).date()
    later = trading_days_after(hours, day, max(DAYS[w] for w in which if w in DAYS)) if any(w in DAYS for w in which) else []
    for w in which:
        if w == "h1":
            days, end = [day], anchor + 3600
        else:
            days = [day, *later[:DAYS[w]]]
            end = _close(hours, days[-1])
        sessions = {d: bars(symbol, d) for d in days}
        missing = [d for d, m in sessions.items() if m is None and _open(hours, d)]
        ended = now >= end
        final = ended and (not missing or now >= end + STALE_DAYS * 86400)
        minutes = [b for d in days for b in (sessions[d] or [])]
        out[w] = path(minutes, ref, anchor, end, final=final)
        if missing and final:
            out[w]["missing"] = "sessions not stored: " + ", ".join(d.isoformat() for d in missing)
    return out


# ------------------------------------------------------------------ action

def _key(f: dict):
    return f.get("key", "position")


def action(fills: list[dict], start: datetime, end: datetime, now_ny: datetime) -> str | None:
    """What the fills (naive New York; ``side``, ``contracts``, ``executed_at``, optional ``key`` per contract) show
    from ``start`` to ``end``: a position open at the start was ``closed``, ``trimmed``, ``added`` to or ``held``;
    with none open, ``entered`` or ``none``. None while the window is still open. Fills carry the broker's minute, so
    one in the start's own minute counts as after it."""
    if now_ny < end:
        return None
    minute = start.replace(second=0, microsecond=0)
    held: dict = defaultdict(float)
    for f in fills:
        if f["executed_at"] < minute:
            held[_key(f)] += f["contracts"] if f["side"] in OPEN_SIDES else -f["contracts"]
    open_before = {k for k, v in held.items() if abs(v) > EPS}
    inside = [f for f in fills if minute <= f["executed_at"] <= end]
    opens = any(f["side"] in OPEN_SIDES for f in inside)
    if not open_before:
        return "entered" if opens else "none"
    closes = [f for f in inside if f["side"] not in OPEN_SIDES and _key(f) in open_before]
    after = dict(held)
    for f in inside:
        after[_key(f)] = after.get(_key(f), 0.0) + (f["contracts"] if f["side"] in OPEN_SIDES else -f["contracts"])
    if closes and all(abs(after[k]) <= EPS for k in open_before):
        return "closed"
    if closes:
        return "trimmed"
    return "added" if opens else "held"


def _symbol_fills(db: Session, symbol: str) -> list[dict]:
    rows = db.exec(select(Fill).where(Fill.ticker == symbol)).all()
    return sorted(({"id": f.id, "side": f.side, "contracts": float(f.contracts), "price": float(f.price),
                    "executed_at": wall_time(f.executed_at),
                    "key": (f.account_id, f.instrument_type, f.option_type, None if f.strike is None else float(f.strike), f.expiration)}
                   for f in rows), key=lambda f: (f["executed_at"], str(f["id"])))


# ------------------------------------------------------------------ rows

def _done(row: dict) -> bool:
    return row["action"] is not None and all(row[w] is None or row[w]["complete"] for w in WINDOWS)


def _row(kind: str, subject_id: str, *, symbol: str | None, anchored_at: datetime, bars: Bars, hours: Hours, now: float,
         ref: float | None = None, which: tuple[str, ...] = WINDOWS, **fields) -> dict:
    if ref is None and symbol:
        ref = reference(bars, symbol, _epoch_utc(anchored_at))
    row = {"subject_kind": kind, "subject_id": subject_id, "symbol": symbol, "anchored_at": anchored_at, "reference_price": ref,
           "source_kind": None, "held": False, "trade_id": None, "action": None, "alt_usd": None,
           **windows(bars, hours, symbol, anchored_at, ref, now, which), **fields}
    row["complete"] = _done(row)
    return row


def ping_row(db: Session, ping: PhonePing, bars: Bars, hours: Hours, now: float) -> dict:
    """A phone ping: the position's own fills for 15 minutes after an exit-kind ping (and, for an open-trade alert, its
    proceeds against closing at the alert's mark), else the symbol's fills for 30."""
    at = ping.delivered_at or ping.decided_at
    start, now_ny = _ny(at), _ny(datetime.fromtimestamp(now, UTC).replace(tzinfo=None))
    trade, alt, did = None, None, None
    if notification_policy.TRACKED.get(ping.kind) == "exit":
        trade = notification_policy._trade_of(db, ping.anchor)
        if trade is None:
            did = "unknown"
        else:
            fills = notification_policy._fills(db, trade)
            did = action(fills, start, start + timedelta(minutes=EXIT_MINUTES), now_ny)
            if (alert := _alert(db, ping)) is not None:
                alt = exit_habits.follow_up({"detected_at": alert.detected_at, "contracts": float(alert.contracts),
                                             "mark": None if alert.mark is None else float(alert.mark)},
                                            fills, trade.status)["vs_alert"]
    elif ping.symbol:
        did = action(_symbol_fills(db, ping.symbol), start, start + timedelta(minutes=ENTRY_MINUTES), now_ny)
    else:
        did = "unknown"
    row = _row("ping", str(ping.id), symbol=ping.symbol, anchored_at=at, bars=bars, hours=hours, now=now,
               source_kind=ping.kind, held=ping.decision != "sent", trade_id=trade.id if trade else ping.trade_id,
               action=did, alt_usd=alt)
    # An open position's alert has no result until it closes: keep recomputing until it does.
    if trade is not None and trade.status == "open" and ping.sender == SENT_POSITION_SENDER:
        row["complete"] = False
    return row


def _alert(db: Session, ping: PhonePing) -> PositionAlert | None:
    if ping.sender != SENT_POSITION_SENDER:
        return None
    try:
        return db.get(PositionAlert, uuid.UUID(ping.source_id))
    except ValueError:
        return None


def plan_row(db: Session, capture: TradeCapture, link: dict | None, bars: Bars, hours: Hours, now: float) -> dict:
    """A plan from its saving to its trade's close: ``entered`` once linked to a trade, ``none`` while it is not."""
    trade_id = link.get("trade_id") if link else None
    trade = db.get(Trade, uuid.UUID(trade_id)) if trade_id else None
    row = _row("plan", str(capture.id), symbol=capture.underlying, anchored_at=capture.received_at, bars=bars, hours=hours,
               now=now, source_kind=capture.setup_label or capture.mode, trade_id=trade.id if trade else None,
               action="entered" if trade else "none")
    if trade is None and capture.not_taken_at is None:
        # Still open to a link for the copilot plans' entry window.
        row["complete"] = row["complete"] and now >= _epoch_utc(capture.received_at) + ENTRY_DAYS * 86400
    elif trade is not None and trade.status == "open":
        row["complete"] = False
    return row


def top_member(event: dict) -> str | None:
    """A stock event's stock; a group event's member that moved most in the event's direction."""
    if event.get("kind") in ("relative_to_spy", "relative_to_sector") or not event.get("evidence"):
        return (event.get("symbols") or [None])[0]
    sign = 1 if event.get("direction") == "up" else -1
    members = [e for e in event["evidence"] if e.get("symbol") in (event.get("symbols") or [])] or event["evidence"]
    return max(members, key=lambda e: (sign * e["change_pct"], e["symbol"]))["symbol"]


def radar_alt(store, event: dict, symbol: str, price: float | None, passes: list[dict], session_over: bool, prices: dict) -> float | None:
    """One share at first sight in Radar's direction: the scorecard's move against SPY to the session's last pass
    (``radar_scorecard._after``'s ``close_pct``) times the price at first sight."""
    from app.engine import radar_scorecard
    if price is None:
        return None
    moved = radar_scorecard._after(store, {**event, "symbols": [symbol]}, passes, session_over, prices)["close_pct"]
    return None if moved is None else round(moved / 100 * price, 2) + 0.0


def radar_row(db: Session, store, event: dict, passes: list[dict], bars: Bars, hours: Hours, now: float, prices: dict) -> dict:
    symbol = top_member(event)
    seen = datetime.fromtimestamp(_iso_epoch(event["first_seen_at"]), UTC).replace(tzinfo=None)
    evidence = next((e for e in event.get("evidence") or [] if e.get("symbol") == symbol), None)
    ref = float(evidence["last"]) if evidence and evidence.get("last") else None
    today = datetime.fromtimestamp(now, ET).date().isoformat()
    start, now_ny = _ny(seen), _ny(datetime.fromtimestamp(now, UTC).replace(tzinfo=None))
    did = action(_symbol_fills(db, symbol), start, start + timedelta(minutes=ENTRY_MINUTES), now_ny) if symbol else "unknown"
    alt = radar_alt(store, event, symbol, ref, passes, event["session_date"] < today, prices) if symbol else None
    row = _row("radar_event", event["event_id"], symbol=symbol, anchored_at=seen, bars=bars, hours=hours, now=now, ref=ref,
               source_kind=event.get("kind"), action=did, alt_usd=alt)
    if event["session_date"] >= today:
        row["complete"] = False
    return row


def _iso_epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def research_row(db: Session, record: CopilotInvestigation, bars: Bars, hours: Hours, now: float) -> dict:
    """A saved Jo research record on its symbol: d1 and d5, and whether the owner traded it by the d1 close."""
    symbol = record.symbol
    if not symbol:
        return _row("research", f"{record.id}:", symbol=None, anchored_at=record.created_at, bars=bars, hours=hours, now=now,
                    which=("d1", "d5"), source_kind=record.source, action="unknown")
    start = _ny(record.created_at)
    end_day = trading_days_after(hours, start.date(), 1)[0]
    end = datetime.fromtimestamp(_close(hours, end_day), ET).replace(tzinfo=None)
    did = action(_symbol_fills(db, symbol), start, end, _ny(datetime.fromtimestamp(now, UTC).replace(tzinfo=None)))
    return _row("research", f"{record.id}:{symbol}", symbol=symbol, anchored_at=record.created_at, bars=bars, hours=hours,
                now=now, which=("d1", "d5"), source_kind=record.source, action=did)


def shadow_row(db: Session, decision: ShadowBookDecision, bars: Bars, hours: Hours, now: float) -> dict:
    """A Shadow book decision on its symbol: d1 and d5 of the underlying; the action is its own paper book's."""
    kinds = set(db.exec(select(ShadowBookEvent.event_type).where(ShadowBookEvent.decision_id == decision.id)).all())
    did = "closed" if "exit" in kinds else "entered" if "entry" in kinds else "none"
    row = _row("shadow_decision", str(decision.id), symbol=decision.symbol, anchored_at=decision.decided_at or decision.claimed_at,
               bars=bars, hours=hours, now=now, which=("d1", "d5"), source_kind=decision.status, action=did)
    if decision.status == "plan" and did == "entered":
        row["complete"] = False  # the paper position is still open
    return row


# ------------------------------------------------------------------ the run

def _stored_bars() -> Bars:
    from app.engine.chart_history import chart_history
    return chart_history.stored


def _calendar() -> Hours:
    from app.engine.chart_calendar import chart_calendar
    return chart_calendar.hours


def _radar_store():
    from app.routers import radar
    return radar._store(read_only=True)[0]


def _save(db: Session, existing: Outcome | None, row: dict, now: float) -> Outcome:
    out = existing or Outcome(subject_kind=row["subject_kind"], subject_id=row["subject_id"], anchored_at=row["anchored_at"])
    for name in ("source_kind", "held", "symbol", "trade_id", "anchored_at", "reference_price", "action", "alt_usd", "complete"):
        setattr(out, name, row[name])
    for w in WINDOWS:
        setattr(out, w, None if row[w] is None else json.dumps(row[w], separators=(",", ":")))
    out.computed_at = datetime.fromtimestamp(now, UTC).replace(tzinfo=None)
    out.version = VERSION
    db.add(out)
    return out


def compute(db: Session, now: float, *, bars: Bars | None = None, hours: Hours | None = None, store=None,
            start: date | None = None, cap: int = RUN_CAP) -> dict:
    """Build or refresh the rows of every new or incomplete subject since ``start``, oldest first, at most ``cap`` of
    them. ``store`` is the Radar store (None: the configured one, read-only; False: none). A subject that fails is
    logged and left for the next run."""
    bars = bars or _stored_bars()
    hours = hours or _calendar()
    begin = _day_start(start or since())
    have = {(o.subject_kind, o.subject_id): o for o in db.exec(select(Outcome).where(Outcome.anchored_at >= begin - timedelta(days=1))).all()}

    def due(kind: str, subject_id: str) -> bool:
        found = have.get((kind, subject_id))
        return found is None or not found.complete or found.version < VERSION

    work: list[tuple[datetime, str, Callable[[], dict]]] = []
    for ping in db.exec(select(PhonePing).where(PhonePing.decided_at >= begin)).all():
        if due("ping", str(ping.id)):
            work.append((ping.delivered_at or ping.decided_at, "ping", lambda p=ping: ping_row(db, p, bars, hours, now)))
    captures = [c for c in db.exec(select(TradeCapture).where(TradeCapture.received_at >= begin)).all() if due("plan", str(c.id))]
    links = capture_links.link_rows(db, captures)
    for c in captures:
        work.append((c.received_at, "plan", lambda c=c: plan_row(db, c, links.get(c.id, {}).get("link"), bars, hours, now)))
    for record in db.exec(select(CopilotInvestigation).where(CopilotInvestigation.source == "jo",
                                                              CopilotInvestigation.created_at >= begin)).all():
        if due("research", f"{record.id}:{record.symbol or ''}"):
            work.append((record.created_at, "research", lambda r=record: research_row(db, r, bars, hours, now)))
    for decision in db.exec(select(ShadowBookDecision).where(ShadowBookDecision.status.in_(("plan", "skip")),
                                                             ShadowBookDecision.claimed_at >= begin)).all():
        if due("shadow_decision", str(decision.id)):
            work.append((decision.decided_at or decision.claimed_at, "shadow_decision",
                         lambda d=decision: shadow_row(db, d, bars, hours, now)))
    radar_note = None
    radar = _radar_store() if store is None else store or None
    if radar is not None:
        try:
            passes: dict[str, list[dict]] = {}
            prices: dict = {}
            first = (start or since()).isoformat()
            for session in sorted(s for s in radar.sessions() if s >= first):
                for event in radar.events(session):
                    if not due("radar_event", event["event_id"]):
                        continue

                    def build(e=event, s=session):
                        if s not in passes:
                            passes[s] = sorted((p for p in radar.passes(s) if p["status"] in ("ok", "partial")),
                                               key=lambda p: (p["started_at"], p["id"]))
                        return radar_row(db, radar, e, passes[s], bars, hours, now, prices)
                    work.append((datetime.fromtimestamp(_iso_epoch(event["first_seen_at"]), UTC).replace(tzinfo=None),
                                 "radar_event", build))
        except Exception:  # noqa: BLE001 - a busy or damaged Radar file must not stop the other kinds
            log.warning("Outcomes: the Radar file could not be read", exc_info=True)
            radar_note = "Radar file unreadable; its events wait for the next run."
    work.sort(key=lambda w: w[0])
    done = Counter()
    failed = 0
    for _, kind, build in work[:cap]:
        # One commit per subject: a failed read rolls back only its own subject (Postgres refuses every later
        # statement in an aborted transaction).
        try:
            row = build()
            _save(db, have.get((row["subject_kind"], row["subject_id"])), row, now)
            db.commit()
        except Exception:  # noqa: BLE001 - one odd source row must not stop the run
            db.rollback()
            log.warning("Outcomes: a %s could not be computed", kind, exc_info=True)
            failed += 1
            continue
        done[kind] += 1
    return {"computed": sum(done.values()), "by_kind": dict(done), "failed": failed, "waiting": max(0, len(work) - cap),
            "note": radar_note}


def run(db: Session) -> tuple[int, str]:
    """The pipeline step: (rows computed, a one-line summary)."""
    import time
    result = compute(db, time.time())
    parts = ", ".join(f"{n} {k}" for k, n in sorted(result["by_kind"].items())) or "nothing new"
    extra = "".join(f" {text}" for text in (
        f"{result['failed']} failed." if result["failed"] else "",
        f"{result['waiting']} wait for the next run." if result["waiting"] else "",
        result["note"] or "") if text)
    return result["computed"], f"Outcomes computed: {parts}.{extra}"


# ------------------------------------------------------------------ reads

def as_dict(o: Outcome) -> dict:
    return {"subject_kind": o.subject_kind, "subject_id": o.subject_id, "source_kind": o.source_kind, "held": o.held,
            "symbol": o.symbol, "trade_id": str(o.trade_id) if o.trade_id else None,
            "anchored_at": int(_epoch_utc(o.anchored_at)), "reference_price": o.reference_price,
            **{w: json.loads(getattr(o, w)) if getattr(o, w) else None for w in WINDOWS},
            "action": o.action, "alt_usd": o.alt_usd, "complete": o.complete, "computed_at": int(_epoch_utc(o.computed_at)),
            "version": o.version}


def summarize(rows: list[dict]) -> dict:
    """Per subject kind: rows, complete, held (pings), median d1 change, the action mix and the alternative's total."""
    out = {}
    for kind in KINDS:
        mine = [r for r in rows if r["subject_kind"] == kind]
        if not mine:
            continue
        d1 = [r["d1"]["pct"] for r in mine if r["d1"] and r["d1"]["complete"] and r["d1"]["pct"] is not None]
        alts = [r["alt_usd"] for r in mine if r["alt_usd"] is not None]
        out[kind] = {"count": len(mine), "complete": sum(r["complete"] for r in mine), "held": sum(r["held"] for r in mine),
                     "median_d1_pct": round(median(d1), 2) if d1 else None, "d1_measured": len(d1),
                     "actions": dict(Counter(r["action"] or "pending" for r in mine)),
                     "alt_usd_total": round(sum(alts), 2) if alts else None, "alt_usd_n": len(alts)}
    return out


def build(db: Session, kind: str | None = None, start: date | None = None, symbol: str | None = None) -> dict:
    """``GET /analytics/outcomes``: the newest rows (at most ``ROWS_SHOWN``) and the summary per kind over all matches."""
    begin = _day_start(start or since())
    query = select(Outcome).where(Outcome.anchored_at >= begin)
    if kind:
        query = query.where(Outcome.subject_kind == kind)
    if symbol:
        query = query.where(Outcome.symbol == symbol.upper())
    rows = [as_dict(o) for o in db.exec(query.order_by(Outcome.anchored_at.desc())).all()]
    return {"since": (start or since()).isoformat(), "summary": summarize(rows), "rows": rows[:ROWS_SHOWN],
            "truncated": len(rows) > ROWS_SHOWN, "note": "Counts and price paths, not causation."}


def week(db: Session, start_utc: datetime, end_utc: datetime) -> dict:
    """The week review's section: the summary per kind for outputs anchored in the week, without the rows."""
    rows = [as_dict(o) for o in db.exec(select(Outcome).where(Outcome.anchored_at >= start_utc, Outcome.anchored_at < end_utc)).all()]
    if not rows:
        return {"state": "not_applicable", "reason": "No outcomes recorded for the week's outputs."}
    return {"state": "ok", "by_kind": {k: {f: v for f, v in s.items() if f not in ("d1_measured", "alt_usd_n")}
                                       for k, s in summarize(rows).items()},
            "note": "d1 is the underlying's change to the next session's close, in percent; alt_usd is $ against "
                    "closing at the alert's mark (pings) or one share at Radar's first sighting. Counts and price paths, not causation."}


def _signed(pct: float) -> str:
    return f"{'+' if pct >= 0 else '−'}{abs(round(pct)):.0f}%"


def after_text(row: dict | None) -> str | None:
    """'+1h −4% · +1d −12%' for the trade page's phone-alert list; None while neither is known."""
    if row is None:
        return None
    parts = [f"+{label} {_signed(row[w]['pct'])}" for w, label in (("h1", "1h"), ("d1", "1d"))
             if row[w] and row[w]["pct"] is not None]
    return " · ".join(parts) or None


def annotate(db: Session, rows: list[dict]) -> list[dict]:
    """The trade page's phone-alert rows with what the underlying did after each ping (``after``)."""
    ids = [r["id"] for r in rows if r.get("id")]
    if not ids:
        return rows
    try:
        pings = {(p.sender, p.source_id): str(p.id) for p in db.exec(select(PhonePing).where(PhonePing.source_id.in_(ids))).all()}
        found = {o.subject_id: as_dict(o) for o in db.exec(select(Outcome).where(
            Outcome.subject_kind == "ping", Outcome.subject_id.in_(list(pings.values())))).all()} if pings else {}
    except Exception:  # noqa: BLE001 - the list stands without the outcomes
        log.warning("Outcomes could not be read for the trade page", exc_info=True)
        return rows
    for row in rows:
        ping = pings.get((notification_policy.SENDER_OF_KIND.get(row.get("kind"), ""), row.get("id")))
        row["after"] = after_text(found.get(ping)) if ping else None
    return rows

