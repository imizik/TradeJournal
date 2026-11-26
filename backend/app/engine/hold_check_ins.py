"""Keep holding check-ins: the ping card's **Keep holding** asks for +15m or +30m; when that time comes and the position
is still open, one ping opens the same card again (docs/copilot-lab.md § Where a ping opens).

The check-in is saved with the hold itself: the ``decision`` day-journal entry the card writes ("Holding. …") carries
``context_json`` ``{"check_in": {"at": <epoch>, "minutes": 15|30, "alert": <id>|null, "interrupt": <id>|null}}``
(``routers/day_journal.EntryCreate.check_in``). No table of its own.

A check-in is due from its ``at`` for ``LATE_SECONDS`` (a server down past that sends nothing late) and only in the
regular session. It is dropped when a newer hold on the same ping replaces it, when an ``Exiting`` decision on the
symbol came after it, or when the pinged position is no longer open in the journal (the alert's position by
``alert_scorecard.position_trade``, an interrupt's by the desk's own ``_interrupt_trade``). Each is claimed once
through the notification policy (``decide(new_only=True)``, sender ``hold_check_in``, source the entry's id, anchored
to the position so the quiet window applies) and sent at most once: a failed send is logged, never retried.

Off unless ``HOLD_CHECK_IN_PINGS=true`` (the owner's switch). While off the card still logs the hold and its time, as
before, and says nothing will ping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
import os
import time
from typing import Callable
import uuid

from sqlmodel import Session, select

from app.engine import notification_policy, phone
from app.engine.chart_math import ET, session_windows
from app.models import DayJournalEntry, FillInterrupt, PositionAlert

log = logging.getLogger(__name__)

SENDER = KIND = "hold_check_in"
MINUTES = (15, 30)
RUN_SECONDS = 30
LATE_SECONDS = 10 * 60
LOOKBACK = timedelta(hours=2)  # holds older than this cannot be due (the longest is 30 minutes)


def enabled() -> bool:
    return os.environ.get("HOLD_CHECK_IN_PINGS", "").strip().lower() == "true"


def context(minutes: int, alert: uuid.UUID | None, interrupt: uuid.UUID | None, now: float) -> dict:
    """What a hold's journal entry carries so this pass can find it."""
    return {"check_in": {"at": int(now) + minutes * 60, "minutes": minutes,
                         "alert": str(alert) if alert else None, "interrupt": str(interrupt) if interrupt else None}}


def _check_in(row: DayJournalEntry) -> dict | None:
    try:
        found = json.loads(row.context_json or "{}").get("check_in")
    except (TypeError, ValueError, AttributeError):
        return None
    if not isinstance(found, dict) or not isinstance(found.get("at"), (int, float)) or not (found.get("alert") or found.get("interrupt")):
        return None
    return found


def due(db: Session, now: float) -> list[tuple[DayJournalEntry, dict]]:
    """The check-ins due now: each ping's newest hold, at or past its time by under ``LATE_SECONDS``, with no
    ``Exiting`` decision on the symbol after it."""
    since = datetime.fromtimestamp(now, UTC).replace(tzinfo=None) - LOOKBACK
    rows = db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "decision", DayJournalEntry.created_at >= since)
                   .order_by(DayJournalEntry.created_at, DayJournalEntry.id)).all()
    newest: dict[str, tuple[DayJournalEntry, dict]] = {}
    exited: dict[str, datetime] = {}
    for row in rows:
        if row.text.strip().lower().startswith("exiting") and row.symbol:
            exited[row.symbol] = row.created_at
        found = _check_in(row)
        if found is not None:
            newest[f"alert:{found['alert']}" if found.get("alert") else f"interrupt:{found['interrupt']}"] = (row, found)
    return [(row, found) for row, found in newest.values()
            if found["at"] <= now < found["at"] + LATE_SECONDS and not (row.symbol in exited and exited[row.symbol] > row.created_at)]


def _target(db: Session, found: dict):
    """(open, contract, what fired, anchor, trade id, desk path, Close/Trim links) for the pinged position; ``open``
    False when it is closed or cannot be found."""
    from app.engine import alert_scorecard, fill_interrupts, position_alerts, telegram_replies
    if found.get("alert"):
        alert = db.get(PositionAlert, uuid.UUID(found["alert"]))
        if alert is None:
            return None
        symbol = (alert.contract or "").split(" ")[0]
        trade = alert_scorecard.position_trade(db, alert.account_id, symbol, alert.source_key, alert.trade_id)
        if trade is None or trade.status != "open":
            return None
        path, more = position_alerts._links(db, alert)
        if not path.startswith("/copilot-lab"):
            more = ()  # with the desk off the links are the alert's answers, which belong to the first ping
        # With the desk on, the check-in carries the alert's Cut it / Holding reply buttons (since 2026-11-26).
        buttons = telegram_replies.cut_buttons(alert.id) if path.startswith("/copilot-lab") else None
        return (alert.contract, f"{alert_scorecard.KIND.get(alert.kind, 'position')} ping".lower(),
                notification_policy.anchor(alert.account_id, alert.source_key), trade.id, path, more, symbol, buttons)
    row = db.get(FillInterrupt, uuid.UUID(found["interrupt"]))
    if row is None:
        return None
    from app.routers.copilot_desk import _interrupt_trade  # the trade the card itself acts on
    trade = _interrupt_trade(db, row)
    if trade is None or trade.status != "open":
        return None
    path = phone.desk_link(fill_interrupts.path(row), symbol=row.ticker, card=f"interrupt:{row.id}")
    return (row.contract, "fill-pattern ping", notification_policy.anchor(row.account_id, row.position_key), trade.id, path, (), row.ticker, None)


def message(contract: str, fired: str, row: DayJournalEntry, found: dict) -> tuple[str, str]:
    held_at = row.created_at.replace(tzinfo=UTC).astimezone(ET)
    clock = f"{held_at.hour % 12 or 12}:{held_at.minute:02d} {'AM' if held_at.hour < 12 else 'PM'}"
    minutes = found.get("minutes") or round((found["at"] - held_at.timestamp()) / 60)
    return (f"Check-in: {contract} still open",
            f"At {clock} you chose to keep holding after the {fired} and asked to be checked in {minutes} minutes. "
            "It is still open: close, trim, or hold again.")


class HoldCheckIns:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self._last_run = 0.0
        self._done: set[str] = set()  # entry ids already claimed by this process

    def run(self) -> None:
        try:
            self._run()
        except Exception:  # noqa: BLE001 - one bad pass never stops the monitor's other stages
            log.exception("Hold check-in pass failed")

    def _run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        minute = moment.hour * 60 + moment.minute
        hours = self.calendar.hours(moment.date()) if self.calendar is not None else None
        regular = next((w for w in session_windows(moment.date(), hours) if w[0] == "regular"), None)
        if regular is None or not regular[1] <= minute < regular[2] or not phone.configured():
            return
        with Session(self.engine) as db:
            for row, found in due(db, now):
                if str(row.id) in self._done:
                    continue
                self._done.add(str(row.id))
                target = _target(db, found)
                if target is None:
                    continue
                self._ping(db, row, found, target, now)

    def _ping(self, db: Session, row: DayJournalEntry, found: dict, target: tuple, now: float) -> None:
        contract, fired, anchor, trade_id, path, more, symbol, buttons = target
        title, body = message(contract, fired, row, found)
        ticket = notification_policy.decide(db, sender=SENDER, source_id=str(row.id), kind=KIND, title=title, body=body, now=now,
                                            anchor=anchor, symbol=symbol, trade_id=trade_id, new_only=True)
        if ticket.held:
            log.info("Hold check-in held: %s", ticket.reason)
            return
        try:
            phone.send(title, body + ticket.append, kind=KIND, path=path, priority=4, tags=("hourglass",), direct_click=True,
                       more=more, keep_links=bool(more), **({"buttons": buttons} if buttons else {}))
        except phone.SendError as exc:
            log.warning("Hold check-in not sent: %s", exc)
            return
        notification_policy.delivered(db, ticket, now)
        db.commit()
