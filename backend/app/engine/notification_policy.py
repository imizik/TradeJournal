"""One notification policy for the app's own phone pings, and what the owner did after each.

Every copilot-side sender (open-trade alerts, plan nudges and link pings, plan
time stops, a confirmed plan's entry and invalidation alerts, pre-market prep,
research results) keeps its own outbox, its own at-most-once delivery and its
own expiry. Right before it hands a message to ``ntfy`` it asks this module one
question, ``decide``: **send now, merge, or hold**. ``ntfy.py`` stays a
transport. Jo's senders (Codex) are not gated here.

The policy, in the order it is applied:

- **Retry.** A ping already judged (the same ``sender`` and ``source_id``) gets
  its first answer again: a send that failed and comes back is still a send,
  with any text merged into it meanwhile appended (``Ticket.append``); a held
  ping stays held. Nothing is counted twice.
- **Quiet window.** A second ping anchored to the same position within
  ``PING_QUIET_MINUTES`` (default 10) of one that was sent is not sent on its
  own: when it is a different kind and the first has not been delivered yet
  (its send failed and is retrying), it is ``merged`` and its text rides with
  the first's resend; otherwise it is ``suppressed``. A ping more important
  than the one before it (the priority order below) is never held by the
  window, and a last-day final or an invalidation is held only by its own
  duplicate: a last-day final after a one-hour alert still goes out, and an
  invalidation after a last-day final does too.
- **Daily cap.** At most ``PING_DAILY_CAP`` (default 12) pings a New York day
  across every kind. The priority order keeps the cap from dropping what
  matters: last-day final, invalidation and give-back are never over cap; the
  last ``RESERVED`` slots under the cap are kept for position and plan pings,
  so nudges, prep and research are held first.

  ``expiry_final`` > ``invalidation`` > ``giveback`` > ``time_stop`` (and the
  90-minute last-day alert) > ``entry`` > ``hold_hour`` > ``nudge`` / ``link`` >
  ``prep`` > ``research``.

Every decision is one ``PhonePing`` row (``sent``, ``merged``, ``suppressed``,
``over_cap``), so the owner can see what was held back (the Dashboard Plans
card's "held back today" line; each held sender row reads ``held`` with the
reason). A database problem in the gate never holds a ping: the sender is told
to send. Known limit: a ``sent`` record whose send kept failing until the sender
expired it stays ``sent`` without ``delivered_at``; it still counts toward the
cap and the window (fewer pings, never more), and any text merged into it is
recorded ``merged`` but never reaches the phone.

``ALERT_POLICY_ENABLED`` defaults to **true**: the policy only ever reduces
pings, each sender's own switch still decides whether it runs at all, and a
held ping is recorded, never lost silently. ``false`` passes everything
through (still recorded, so the follow-up below keeps working).

**Acted on.** ``FollowUps`` runs on the level alert monitor's loop and writes,
from the fills and the plan links as they arrive and never by guessing, what
followed each delivered ping (``then``): an entry trigger, did an entry fill in
the symbol follow within ``ENTRY_MINUTES``; an invalidation, time stop or
open-trade alert, was the position closed (or trimmed) within
``EXIT_MINUTES``; a nudge or link ping, was a plan linked within
``LINK_MINUTES``. The trade page's phone-alert list shows it per ping
("then: closed in 6 min") and the copilot's week review counts it by kind.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import os
import time
from typing import Callable
import uuid

from sqlmodel import Session, select

from app.engine.chart_math import ET
from app.models import CaptureLink, Fill, PhonePing, Trade, TradeFill

log = logging.getLogger(__name__)

PRIORITY = ("expiry_final", "invalidation", "giveback", "time_stop", "entry", "hold_hour", "nudge", "prep", "research")
ALIASES = {"expiry_first": "time_stop", "link": "nudge", "no_plan": "nudge"}
NEVER_CAPPED = 3  # ranks 0-2 (last-day final, invalidation, give-back) are never over cap
NEVER_QUIET = 2  # ranks 0-1 (last-day final, invalidation) are held by the quiet window only for their own duplicate
LOW_PRIORITY = 6  # ranks from here (nudge/link, prep, research) are held first
RESERVED = 3  # slots under the cap kept for ranks below LOW_PRIORITY
HELD = ("merged", "suppressed", "over_cap")
RUN_SECONDS = 30
ENTRY_MINUTES = 30
EXIT_MINUTES = 15
LINK_MINUTES = 30
LOOKBACK_DAYS = 2  # pings older than this are no longer judged
ACTED = ("entered", "closed", "trimmed", "linked")
EPS = 1e-9
# What answers each kind: an entry fill in the symbol, an exit of the position, or a plan link.
TRACKED = {"entry": "entry", "invalidation": "exit", "time_stop": "exit", "giveback": "exit", "hold_hour": "exit",
           "expiry_first": "exit", "expiry_final": "exit", "nudge": "link", "link": "link", "no_plan": "link"}
WINDOW = {"entry": ENTRY_MINUTES, "exit": EXIT_MINUTES, "link": LINK_MINUTES}


def enabled() -> bool:
    return os.environ.get("ALERT_POLICY_ENABLED", "true").strip().lower() != "false"


def _setting(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "").strip()))
    except ValueError:
        return default


def daily_cap() -> int:
    return _setting("PING_DAILY_CAP", 12)


def quiet_seconds() -> int:
    return _setting("PING_QUIET_MINUTES", 10) * 60


def rank(kind: str) -> int:
    """The kind's place in the priority order; a kind the policy does not know goes last."""
    canonical = ALIASES.get(kind, kind)
    return PRIORITY.index(canonical) if canonical in PRIORITY else len(PRIORITY)


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _et(moment_utc: datetime) -> datetime:
    """A naive UTC moment as the naive New York wall clock the journal's fills use."""
    return moment_utc.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)


def day_bounds(now: float) -> tuple[datetime, datetime]:
    """The New York day holding ``now``, as naive UTC bounds."""
    moment = datetime.fromtimestamp(now, ET)
    start = datetime(moment.year, moment.month, moment.day, tzinfo=ET)
    return _utc(start.timestamp()), _utc((start + timedelta(days=1)).timestamp())


def anchor(account_id: uuid.UUID, source_key: str) -> str:
    """A position's identity as every sender anchors it: the account and its first entry fill's source key."""
    return f"{account_id}:{source_key}"


def position_anchor(db: Session, trade_id: uuid.UUID | None) -> str | None:
    """The anchor of the position ``trade_id`` holds, or None when it has no entry fill."""
    if trade_id is None:
        return None
    trade = db.get(Trade, trade_id)
    if trade is None:
        return None
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                      .where(TradeFill.trade_id == trade_id, TradeFill.role == "entry")).all()
    if not entries:
        return None
    first = min(entries, key=lambda f: (f.executed_at, f.raw_email_id or "", str(f.id)))
    return anchor(trade.account_id, first.raw_email_id or str(first.id))


def symbol_anchor(db: Session, symbol: str) -> tuple[str, uuid.UUID | None]:
    """A symbol-level ping's anchor: the newest open position in the symbol when there is one, else the symbol."""
    trades = db.exec(select(Trade).where(Trade.status == "open", Trade.ticker == symbol)).all()
    for trade in sorted(trades, key=lambda t: (t.opened_at or datetime.min, str(t.id)), reverse=True):
        found = position_anchor(db, trade.id)
        if found:
            return found, trade.id
    return f"symbol:{symbol}", None


@dataclass
class Ticket:
    """The gate's answer: ``send`` (with ``append`` to add to the body), or ``merge`` / ``hold`` with the reason."""
    action: str
    reason: str = ""
    append: str = ""
    id: uuid.UUID | None = None

    @property
    def held(self) -> bool:
        return self.action != "send"


def decide(db: Session, *, sender: str, source_id: str, kind: str, title: str, body: str, now: float,
           anchor: str | None = None, symbol: str | None = None, trade_id: uuid.UUID | None = None) -> Ticket:
    """Send now, merge, or hold this ping; the decision is recorded once per (sender, source_id).
    Never raises: when the policy cannot be read or written the answer is to send."""
    try:
        return _decide(db, sender=sender, source_id=source_id, kind=kind, title=title, body=body, now=now,
                       anchor=anchor, symbol=symbol, trade_id=trade_id)
    except Exception:  # noqa: BLE001 - the ping matters more than its bookkeeping
        log.warning("Notification policy unavailable; sending %s from %s unjudged", kind, sender, exc_info=True)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return Ticket("send", "The notification policy could not be read, so the ping was sent unjudged.")


def _decide(db: Session, *, sender: str, source_id: str, kind: str, title: str, body: str, now: float,
            anchor: str | None, symbol: str | None, trade_id: uuid.UUID | None) -> Ticket:
    held = db.exec(select(PhonePing).where(PhonePing.sender == sender, PhonePing.source_id == source_id)).first()
    if held is not None:
        if held.decision == "sent":
            return Ticket("send", held.reason or "", _appended(db, held), held.id)
        return Ticket("merge" if held.decision == "merged" else "hold", held.reason or "", "", held.id)
    row = PhonePing(sender=sender, source_id=source_id, kind=kind, rank=rank(kind), symbol=symbol, anchor=anchor, trade_id=trade_id,
                    title=title, body=body, decided_at=_utc(now), decision="sent")
    if not enabled():
        row.reason = "ALERT_POLICY_ENABLED is false, so the ping was passed through."
    else:
        _judge(db, row, now)
    db.add(row)
    db.commit()
    db.refresh(row)
    if row.decision == "sent":
        return Ticket("send", row.reason or "", "", row.id)
    log.info("Notification policy %s %s from %s: %s", row.decision, kind, sender, row.reason)
    return Ticket("merge" if row.decision == "merged" else "hold", row.reason or "", "", row.id)


def _judge(db: Session, row: PhonePing, now: float) -> None:
    if row.anchor:
        recent = db.exec(select(PhonePing).where(PhonePing.anchor == row.anchor, PhonePing.decision == "sent",
                                                 PhonePing.decided_at >= _utc(now - quiet_seconds()))
                         .order_by(PhonePing.decided_at.desc())).all()
        # A duplicate of a kind sent inside the window is never sent again. The two most important kinds are held by
        # nothing else; anything else yields to an equal or more important ping sent moments earlier for the same position.
        same = next((p for p in recent if p.kind == row.kind), None)
        prev = same if same is not None else recent[0] if recent else None
        if prev is not None and (same is not None or (row.rank >= prev.rank and row.rank >= NEVER_QUIET)):
            minutes = max(1, round((now - _epoch(prev.decided_at)) / 60))
            if same is None and prev.delivered_at is None:
                row.decision, row.merged_into = "merged", prev.id
                row.reason = f"Merged into the {_label(prev.kind)} ping {minutes} min earlier for the same position, which is still being sent."
            else:
                row.decision = "suppressed"
                row.reason = f"Not sent: a {_label(prev.kind)} ping went out {minutes} min earlier for the same position (quiet window {quiet_seconds() // 60} min)."
            return
    if row.rank < NEVER_CAPPED:
        return
    start, end = day_bounds(now)
    sent_today = len(db.exec(select(PhonePing.id).where(PhonePing.decision == "sent", PhonePing.decided_at >= start,
                                                        PhonePing.decided_at < end)).all())
    cap = daily_cap()
    limit = cap - RESERVED if row.rank >= LOW_PRIORITY else cap
    if sent_today >= max(0, limit):
        row.decision = "over_cap"
        kept = (f" The last {RESERVED} of {cap} are kept for position and plan pings." if row.rank >= LOW_PRIORITY and limit > 0 else "")
        row.reason = f"Not sent: {sent_today} ping{'' if sent_today == 1 else 's'} already went out today (cap {cap}).{kept}"


def _appended(db: Session, into: PhonePing) -> str:
    merged = db.exec(select(PhonePing).where(PhonePing.merged_into == into.id).order_by(PhonePing.decided_at)).all()
    return "".join(f"\n\nAlso: {m.title}. {m.body}" for m in merged)


def _label(kind: str) -> str:
    return {"expiry_final": "last-day final", "expiry_first": "expires-today", "giveback": "give-back", "hold_hour": "one-hour",
            "time_stop": "time stop", "entry": "entry trigger", "invalidation": "invalidation", "nudge": "plan nudge",
            "no_plan": "plan nudge", "link": "plan link", "prep": "pre-market prep", "research": "research"}.get(kind, kind)


def delivered(db: Session, ticket: Ticket, now: float) -> None:
    """ntfy accepted the ping (or the send may have reached the phone): the record stops taking merges."""
    if ticket.id is None:
        return
    try:
        row = db.get(PhonePing, ticket.id)
        if row is not None and row.delivered_at is None:
            row.delivered_at = _utc(now)
            db.add(row)
    except Exception:  # noqa: BLE001 - never fail a delivered ping over its bookkeeping
        log.warning("Notification policy could not record a delivery", exc_info=True)


# ------------------------------------------------------------------ acted on

def _trade_of(db: Session, ping_anchor: str | None) -> Trade | None:
    """The trade holding the anchored position's first entry fill, in its account."""
    if not ping_anchor or ":" not in ping_anchor or ping_anchor.startswith("symbol:"):
        return None
    account, key = ping_anchor.split(":", 1)
    try:
        account_id = uuid.UUID(account)
    except ValueError:
        return None
    fill = db.exec(select(Fill).where(Fill.account_id == account_id, Fill.raw_email_id == key)).first()
    if fill is None:
        try:
            fill = db.get(Fill, uuid.UUID(key))
        except ValueError:
            fill = None
    if fill is None or fill.account_id != account_id:
        return None
    link = db.exec(select(TradeFill).where(TradeFill.fill_id == fill.id, TradeFill.role == "entry")).first()
    return db.get(Trade, link.trade_id) if link is not None else None


def _fills(db: Session, trade: Trade) -> list[dict]:
    rows = db.exec(select(TradeFill.role, Fill.id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at)
                   .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id == trade.id)).all()
    return sorted(({"id": r.id, "role": r.role, "side": r.side, "contracts": float(r.contracts), "price": float(r.price),
                    "executed_at": r.executed_at} for r in rows), key=lambda f: (f["executed_at"], str(f["id"])))


def _minutes(at: datetime, moment: datetime) -> int:
    return max(0, round((moment - at).total_seconds() / 60))


def judge_entry(db: Session, row: PhonePing, at: datetime, now: float) -> tuple[str | None, int | None]:
    """An entry fill in the symbol in the ``ENTRY_MINUTES`` after the ping; fills carry the broker's minute, so one in
    the ping's own minute counts."""
    if not row.symbol:
        return "unmatched", None
    minute = at.replace(second=0, microsecond=0)
    fills = db.exec(select(Fill.executed_at).join(TradeFill, TradeFill.fill_id == Fill.id)
                    .where(TradeFill.role == "entry", Fill.ticker == row.symbol, Fill.executed_at >= minute,
                           Fill.executed_at <= at + timedelta(minutes=ENTRY_MINUTES)).order_by(Fill.executed_at)).all()
    if fills:
        return "entered", _minutes(at, fills[0])
    if now >= _epoch(row.delivered_at) + ENTRY_MINUTES * 60:
        return "no_entry", None
    return None, None


def judge_exit(db: Session, row: PhonePing, at: datetime, now: float) -> tuple[str | None, int | None]:
    """The contracts open at the ping, under first in, first out, sold within ``EXIT_MINUTES``: all of them, some, or none."""
    from app.engine.chart_journal import OPEN_SIDES
    from app.engine.exit_habits import _open_before
    trade = _trade_of(db, row.anchor)
    if trade is None:
        return "unmatched", None
    fills = _fills(db, trade)
    minute = at.replace(second=0, microsecond=0)
    held = _open_before(fills, at, True)
    cut = at
    if held <= EPS:
        held, cut = _open_before(fills, minute, False), minute
    if held <= EPS:
        return "unmatched", None
    left, last = held, None
    for f in fills:
        if f["executed_at"] < cut or f["side"] in OPEN_SIDES or left <= EPS:
            continue
        if f["executed_at"] > at + timedelta(minutes=EXIT_MINUTES):
            break
        left -= min(left, f["contracts"])
        last = f["executed_at"]
    if left <= EPS:
        return "closed", _minutes(at, last)
    if now < _epoch(row.delivered_at) + EXIT_MINUTES * 60:
        return None, None
    return ("trimmed", _minutes(at, last)) if last is not None else ("held", None)


def judge_link(db: Session, row: PhonePing, at: datetime, now: float) -> tuple[str | None, int | None]:
    """A plan linked to the anchored position within ``LINK_MINUTES`` of the ping (``CaptureLink.linked_at`` is UTC)."""
    if not row.anchor or row.anchor.startswith("symbol:") or ":" not in row.anchor:
        return "unmatched", None
    account, key = row.anchor.split(":", 1)
    try:
        account_id = uuid.UUID(account)
    except ValueError:
        return "unmatched", None
    since = row.delivered_at
    links = db.exec(select(CaptureLink.linked_at).where(CaptureLink.account_id == account_id, CaptureLink.source_key == key,
                                                        CaptureLink.linked_at >= since - timedelta(minutes=1),
                                                        CaptureLink.linked_at <= since + timedelta(minutes=LINK_MINUTES))
                    .order_by(CaptureLink.linked_at)).all()
    if links:
        return "linked", _minutes(since, links[0])
    if now >= _epoch(since) + LINK_MINUTES * 60:
        return "not_linked", None
    return None, None


JUDGES = {"entry": judge_entry, "exit": judge_exit, "link": judge_link}


class FollowUps:
    """The acted-on pass: judges each delivered, tracked ping once the fills (or the window's end) can answer it."""

    def __init__(self, engine, *, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.clock = clock
        self._last_run = 0.0
        self._warned = False

    def run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        try:
            with Session(self.engine) as db:
                self.judge(db, now)
        except Exception:  # noqa: BLE001 - a missing table or a read error must not stop the alert loop
            if not self._warned:
                log.warning("Phone ping follow-up pass failed", exc_info=True)
                self._warned = True

    def judge(self, db: Session, now: float) -> int:
        """Judge what can be judged; returns how many pings were answered this pass."""
        due = db.exec(select(PhonePing).where(PhonePing.decision == "sent", PhonePing.then.is_(None),
                                              PhonePing.delivered_at.is_not(None),
                                              PhonePing.decided_at >= _utc(now - LOOKBACK_DAYS * 86400))).all()
        answered = 0
        for row in due:
            what = TRACKED.get(row.kind)
            if what is None:
                continue
            then, minutes = JUDGES[what](db, row, _et(row.delivered_at), now)
            if then is None:
                continue
            row.then, row.then_minutes, row.judged_at = then, minutes, _utc(now)
            db.add(row)
            answered += 1
        if answered:
            db.commit()
        return answered


# ------------------------------------------------------------------ views

def then_text(then: str | None, minutes: int | None) -> str | None:
    """'closed in 6 min', for the trade page's phone-alert list."""
    if then is None or then == "unmatched":
        return None
    soon = f" in {minutes} min" if minutes is not None else ""
    return {"entered": f"entered{soon}", "no_entry": f"no entry within {ENTRY_MINUTES} min",
            "closed": f"closed{soon}", "trimmed": f"trimmed{soon}", "held": f"still held {EXIT_MINUTES} min later",
            "linked": f"plan linked{soon}", "not_linked": f"no plan linked within {LINK_MINUTES} min"}.get(then)


SENDER_OF_KIND = {"giveback": "position_alerts", "expiry_first": "position_alerts", "expiry_final": "position_alerts",
                  "hold_hour": "position_alerts", "plan_nudge": "plan_nudges", "plan_link": "plan_nudges"}


def annotate(db: Session, rows: list[dict]) -> list[dict]:
    """The trade page's phone-alert rows with the policy's decision and what followed each (``then``)."""
    ids = [r["id"] for r in rows if r.get("id")]
    if not ids:
        return rows
    try:
        found = {(p.sender, p.source_id): p for p in db.exec(select(PhonePing).where(PhonePing.source_id.in_(ids))).all()}
    except Exception:  # noqa: BLE001 - the list stands without the policy's view
        log.warning("Phone ping records could not be read for the trade page", exc_info=True)
        return rows
    for row in rows:
        ping = found.get((SENDER_OF_KIND.get(row.get("kind"), ""), row.get("id")))
        row["policy"] = None if ping is None else ping.decision
        row["then"] = None if ping is None else then_text(ping.then, ping.then_minutes)
    return rows


def held_back_today(db: Session, now: float) -> dict:
    """How many pings the policy held today (New York) and of which kinds, for the Dashboard Plans card."""
    start, end = day_bounds(now)
    try:
        rows = db.exec(select(PhonePing.kind).where(PhonePing.decision.in_(HELD), PhonePing.decided_at >= start,
                                                    PhonePing.decided_at < end)).all()
    except Exception:  # noqa: BLE001
        log.warning("Held-back pings could not be counted", exc_info=True)
        return {"count": 0, "by_kind": {}}
    return {"count": len(rows), "by_kind": dict(Counter(_label(k) for k in rows))}


def week_summary(db: Session, start_utc: datetime, end_utc: datetime) -> dict:
    """The week's pings by kind: sent, held, judged and acted on, for the copilot's week review."""
    rows = db.exec(select(PhonePing).where(PhonePing.decided_at >= start_utc, PhonePing.decided_at < end_utc)).all()
    by_kind: dict[str, Counter] = {}
    for p in rows:
        tally = by_kind.setdefault(p.kind, Counter())
        if p.decision == "sent":
            tally["sent"] += 1
            if p.then is not None and p.then != "unmatched":
                tally["judged"] += 1
                if p.then in ACTED:
                    tally["acted_on"] += 1
        else:
            tally["held"] += 1
    judged = sum(t["judged"] for t in by_kind.values())
    acted = sum(t["acted_on"] for t in by_kind.values())
    return {"state": "ok", "sent": sum(t["sent"] for t in by_kind.values()), "held": sum(t["held"] for t in by_kind.values()),
            "judged": judged, "acted_on": acted, "acted_on_pct": round(100 * acted / judged, 1) if judged else None,
            "by_kind": {k: dict(t) for k, t in sorted(by_kind.items(), key=lambda kv: rank(kv[0]))},
            "then": (f"acted_on: an entry trigger followed by an entry fill in the symbol within {ENTRY_MINUTES} min; an "
                     f"invalidation, time stop or open-trade alert followed by the position closed or trimmed within {EXIT_MINUTES} "
                     f"min; a nudge or link ping followed by a plan link within {LINK_MINUTES} min. judged counts pings the fills "
                     "could answer. held: merged, suppressed by the quiet window, or over the daily cap.")}
