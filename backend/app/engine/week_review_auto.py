"""The automatic week review: Review my week runs by itself once a week, and one phone ping opens it.

At ``WEEK_REVIEW_AUTO_AT`` (default 16:45 New York) on the week's last trading day (Friday; on a Friday holiday the
day before it, per the market calendar) the week is claimed once (``WeekReviewAuto.week_start`` is unique, so a
restart or a second process never reviews it twice). A week with no closed trade (``copilot_review.week_review`` reads
``none``) is recorded ``skipped`` and nothing runs or pings.

Otherwise one Copilot Lab turn (``run_turn`` through ``premarket_prep._turn``: the lab's backend, evidence, system
prompt and turn budget cap as configured) is sent the owner's own "Review my week" context for that week, so the
model calls ``get_week_review``, opens with the active practice goal's score, and proposes one practice
(``propose_plan`` kind ``practice``) when the counts support it. The answer is saved as an open copilot investigation
titled ``Week review <Mon>–<Fri>`` (it shows in Open threads), and the proposed practice is kept on this row, so the
card shows when the owner opens that investigation (``GET /copilot/practice?investigation=<id>``); nothing is saved
as a goal until they confirm it.

The ping's title is ``Your week: +$412 · 3 of 5 planned`` (the week review's totals and plans captured before the
entry), its body the answer's first two lines, then the practice score while a goal is active, then "Open to confirm
next week's practice" when a practice was proposed. A tap opens the investigation. If the turn fails (an error event,
the budget stop included, or no text), the ping and the saved record carry the week's facts instead, labelled as
such. Nothing here places, changes or suggests an order.

Off unless ``WEEK_REVIEW_AUTO_ENABLED=true``, and nothing runs while the lab is off (``COPILOT_ENABLED``). It runs on
the level alert monitor's loop beside the pre-market prep, the review on its own thread. A review not started by
midnight New York on its day waits for the next week. Delivery is at-most-once, as the prep's: a send that may have
reached ntfy is ``unknown`` and never resent, and a ping not sent within ``EXPIRE_SECONDS`` of its claim is
``expired``. The gate is ``notification_policy.decide`` (kind ``week_review``, ranked with the prep).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import logging
import os
import re
import threading
import time
from typing import Callable
import uuid

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import notification_policy, ntfy
from app.engine.chart_math import ET
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc
from app.engine.premarket_prep import _trading_day, _turn
from app.models import PracticeGoal, WeekReviewAuto

log = logging.getLogger(__name__)

RUN_SECONDS = 30
DEFAULT_AT = 16 * 60 + 45
PREPARE_SECONDS = 15 * 60  # a claimed review that never finished (a crash mid-turn) is given up, not redone
EXPIRE_SECONDS = 2 * 60 * 60
BODY_LINES = 2
LINE_MAX = 160
TITLE = "Week review"
CONFIRM = "Open to confirm next week's practice"
FALLBACK_LABEL = "The week's facts (the copilot turn failed):"


def enabled() -> bool:
    return os.environ.get("WEEK_REVIEW_AUTO_ENABLED", "").lower() == "true"


def review_minute() -> int:
    """``WEEK_REVIEW_AUTO_AT`` (``HH:MM`` New York) as a minute of the day; 16:45 when unset or unreadable."""
    raw = os.environ.get("WEEK_REVIEW_AUTO_AT", "").strip()
    if not raw:
        return DEFAULT_AT
    try:
        hour, minute = (int(part) for part in raw.split(":"))
    except ValueError:
        hour = minute = -1
    if 0 <= hour < 24 and 0 <= minute < 60:
        return hour * 60 + minute
    log.warning("WEEK_REVIEW_AUTO_AT=%r is not HH:MM; using 16:45", raw)
    return DEFAULT_AT


def _lab_on() -> bool:
    from app.ai import copilot
    return copilot.settings().enabled


def last_trading_day(calendar, day: date) -> bool:
    """``day`` is a trading day and no later weekday of its week is one: Friday, or the day before a Friday holiday."""
    if day.weekday() >= 5 or not _trading_day(calendar, day):
        return False
    return not any(_trading_day(calendar, day + timedelta(days=k)) for k in range(1, 5 - day.weekday()))


# --------------------------------------------------------------------------- the review

def week_title(monday: date) -> str:
    friday = monday + timedelta(days=4)
    return f"{TITLE} {monday:%b} {monday.day}–{friday:%b} {friday.day}"


def prompt(monday: date) -> str:
    """The owner's own Review my week context for that week, as a Friday's Daily Review link sends it."""
    return f"Context: Review my week of {monday.isoformat()}"


def _money(value: float) -> str:
    dollars = round(value)
    return f"{'-' if dollars < 0 else '+'}${abs(dollars):,}"


def ping_title(review: dict) -> str:
    totals, planned = review["totals"], review["planned"]
    return f"Your week: {_money(totals['pnl_usd'])} · {planned['pre_entry']['trades']} of {totals['trades']} planned"


def score_line(review: dict) -> str | None:
    """The active practice goal's score for the week, from the review's own ``practice`` section; None without one."""
    practice = review.get("practice") or {}
    if practice.get("state") != "ok" or not practice.get("practicing"):
        return None
    week, last = practice.get("this_week") or {}, practice.get("last_week") or {}
    return (f"Practice ({practice['goal']['label']}): {week.get('text', '?')} this week"
            + (f", {last['text']} last week" if last.get("of") else ""))


def fallback_lines(review: dict) -> list[str]:
    """The week's facts when the turn fails, nothing interpreted."""
    totals, planned = review["totals"], review["planned"]
    out = [FALLBACK_LABEL,
           f"{totals['trades']} closed trades, {_money(totals['pnl_usd'])}; plan before entry {planned['pre_entry']['trades']}, "
           f"late {planned['late_or_unverified']['trades']}, none {planned['none']['trades']}"]
    follow = review.get("follow_through") or {}
    if follow.get("invalidation_hit_while_held"):
        out.append(f"Invalidation hit while held {follow['invalidation_hit_while_held']}: out within 15 min "
                   f"{follow.get('out_within_15m', 0)}, held past {follow.get('held_past_15m', 0)}")
    return out


def _plain(line: str) -> str:
    """One answer line for the lock screen: no markdown heading, bullet, emphasis or code marks."""
    line = re.sub(r"^\s*(#+|>|[-*•]|\d+[.)])\s+", "", line)
    line = re.sub(r"^\**verdict\**:\**\s*", "", line, flags=re.I)  # the answer format's label; the saved answer keeps it
    line = re.sub(r"\*\*|__|`", "", line).strip()
    if len(line) > 2 and line[0] == line[-1] and line[0] in "_*":
        line = line[1:-1].strip()
    return line if len(line) <= LINE_MAX else line[: LINE_MAX - 1] + "…"


def answer_lines(text: str) -> list[str]:
    return [p for p in (_plain(line) for line in (text or "").splitlines()) if p]


def practice_proposal(events: list[dict]) -> dict | None:
    """The practice card the turn proposed (``run_turn`` allows one per answer), without the event type."""
    found = [e for e in events if e.get("type") == "proposal" and e.get("kind") == "practice"]
    return {k: v for k, v in found[-1].items() if k != "type"} if found else None


def _evidence(events: list[dict]) -> list[dict]:
    """Which tools the answer used and how old their data was (never the data); a proposal is not evidence."""
    refs = []
    for e in events:
        prov = e.get("provenance") or {}
        if e.get("type") == "tool" and e.get("status") == "ok" and prov and e.get("name") != "propose_plan":
            refs.append({"tool": e["name"], "as_of": prov.get("as_of"), "kind": prov.get("kind"), "message": 1})
    return refs


def body(row: WeekReviewAuto) -> str:
    return row.body or row.title or TITLE


def message(row: WeekReviewAuto) -> tuple[str, str, str]:
    """Title, body and the app path the notification opens."""
    path = f"/copilot-lab?investigation={row.investigation_id}" if row.investigation_id else "/copilot-lab"
    return row.title or TITLE, body(row), path


def _save(db: Session, title: str, question: str, written: str, conclusion: str | None, evidence: list[dict]) -> str:
    from app.engine import copilot_investigations as investigations
    fields = investigations.InvestigationFields(
        title=title, conclusion=conclusion[:280] if conclusion else None, evidence=evidence[:400],
        transcript=[{"role": "user", "content": question}, {"role": "assistant", "content": written[:20_000]}])
    return investigations.create(fields, session=db)["id"]


def proposed(db: Session, investigation_id: str) -> dict | None:
    """The practice card an automatic review proposed, while it is the latest review and its card is not confirmed."""
    row = db.exec(select(WeekReviewAuto).where(WeekReviewAuto.investigation_id == investigation_id)).first()
    if row is None or not row.proposal_json:
        return None
    newer = db.exec(select(WeekReviewAuto.id).where(WeekReviewAuto.week_start > row.week_start,
                                                    WeekReviewAuto.investigation_id.is_not(None))).first()
    confirmed = db.exec(select(PracticeGoal.id).where(PracticeGoal.investigation_id == investigation_id)).first()
    return None if newer or confirmed else json.loads(row.proposal_json)


class WeekReviews:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None, turn=None):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.turn = turn or self._lab_turn
        self._spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True, name="week-review").start())
        self._last_run = 0.0

    @staticmethod
    def _lab_turn(question: str, now: float) -> tuple[str, str | None, list[dict]]:
        events: list[dict] = []
        answer, error = _turn(question, now, events)
        return answer, error, events

    def run(self) -> None:
        """Claim this week's review once it is due, then run it off the alert loop."""
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        if not enabled() or not _lab_on():
            return
        moment = datetime.fromtimestamp(now, ET)
        if moment.hour * 60 + moment.minute < review_minute() or not last_trading_day(self.calendar, moment.date()):
            return
        monday = moment.date() - timedelta(days=moment.weekday())
        with Session(self.engine) as db:
            if db.exec(select(WeekReviewAuto.id).where(WeekReviewAuto.week_start == monday)).first():
                return
            row = WeekReviewAuto(week_start=monday, detected_at=_utc(now))
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # another process claimed this week a moment earlier
                return
            row_id = row.id
        log.info("Week review claimed for the week of %s", monday)
        self._spawn(lambda: self._prepare_and_send(row_id))

    def _prepare_and_send(self, row_id: uuid.UUID) -> None:
        try:
            self.prepare(row_id)
        except Exception:
            log.exception("Week review failed")
            with Session(self.engine) as db:
                db.exec(update(WeekReviewAuto).where(WeekReviewAuto.id == row_id, WeekReviewAuto.delivery == "preparing")
                        .values(delivery="expired", last_error="The review could not be assembled, so nothing was sent."))
                db.commit()
            return
        self.deliver()

    def prepare(self, row_id: uuid.UUID) -> None:
        """Read the week, run the turn, save the investigation and queue the ping (or skip a week with no trade)."""
        from app.ai import copilot_review
        now = self.clock()
        with Session(self.engine) as db:
            row = db.get(WeekReviewAuto, row_id)
            if row is None or row.delivery != "preparing":
                return
            monday = row.week_start
            review = copilot_review.week_review(monday.isoformat(), session=db)
            if review.get("state") != "ok":
                row.delivery, row.last_error = "skipped", "No closed trades this week, so no review was run."
                db.add(row)
                db.commit()
                log.info("Week review skipped for the week of %s: no closed trades", monday)
                return
        question = prompt(monday)
        answer, error, events = self.turn(question, now)
        written = answer_lines(answer) if error is None else []
        if not written:
            error = error or "The copilot wrote nothing."
        proposal = practice_proposal(events) if error is None else None
        score = score_line(review)
        if error is None:
            shown = written[:BODY_LINES] + ([score] if score else []) + ([CONFIRM] if proposal else [])
            saved_text, conclusion = answer.strip(), written[0]
        else:
            facts = fallback_lines(review) + ([score] if score else [])
            shown, saved_text, conclusion = facts, "\n".join(facts), None
        with Session(self.engine) as db:
            row = db.get(WeekReviewAuto, row_id)
            if row is None or row.delivery != "preparing":
                return  # given up meanwhile: never sent late
            investigation_id = _save(db, week_title(monday), question, saved_text, conclusion,
                                     _evidence(events) if error is None else [])
            queued = db.exec(update(WeekReviewAuto).where(WeekReviewAuto.id == row_id, WeekReviewAuto.delivery == "preparing").values(
                delivery="pending", investigation_id=investigation_id, title=ping_title(review), body="\n".join(shown),
                proposal_json=json.dumps(proposal) if proposal else None, fallback=error is not None,
                last_error=None if error is None else f"Copilot turn failed: {error}"[:500]))
            db.commit()
            if queued.rowcount != 1:
                return
        log.info("Week review ready (%s)", "facts" if error else "copilot")

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            db.exec(update(WeekReviewAuto).where(WeekReviewAuto.delivery == "preparing", WeekReviewAuto.detected_at < _utc(now - PREPARE_SECONDS))
                    .values(delivery="expired", last_error="The review did not finish in time, so nothing was sent."))
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(WeekReviewAuto).where(WeekReviewAuto.delivery == "sending", WeekReviewAuto.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(WeekReviewAuto.id).where(WeekReviewAuto.delivery == "pending")
                          .where((WeekReviewAuto.next_attempt_at.is_(None)) | (WeekReviewAuto.next_attempt_at <= _utc(now)))
                          .order_by(WeekReviewAuto.detected_at).limit(5)).all()
        for row_id in due:
            self._send(row_id)

    def _send(self, row_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(WeekReviewAuto).where(WeekReviewAuto.id == row_id, WeekReviewAuto.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            row = db.get(WeekReviewAuto, row_id)
            if now - _epoch(row.detected_at) > EXPIRE_SECONDS:
                row.delivery, row.last_error = "expired", "Not sent within 2 hours of its time, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                row.delivery, row.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                row.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            title, text, path = message(row)
            ticket = notification_policy.decide(db, sender="week_review_auto", source_id=str(row.id), kind="week_review",
                                                title=title, body=text, now=now)
            if ticket.held:
                row.delivery, row.last_error = "held", ticket.reason
                db.commit()
                return
            row.attempts += 1
            try:
                ntfy.publish(title, text + ticket.append, priority=3, tags=("bar_chart",), path=path, direct_click=True)
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    row.delivery, row.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    row.delivery, row.last_error = "pending", str(exc)
                    row.next_attempt_at = _utc(now + BACKOFF[min(row.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Week review delivery failed (attempt %d): %s", row.attempts, exc)
                return
            row.delivery, row.delivered_at = "sent", _utc(self.clock())
            notification_policy.delivered(db, ticket, now)
            db.commit()
