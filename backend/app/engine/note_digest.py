"""The Sunday notes digest: once a week, the owner's own Telegram notes sent back to him in one ping.

A note is a message or voice note to the bot that starts with note or idea (``telegram_replies``), saved to that day's
journal with its context (``DayJournalEntry.context_json``). On Sunday at or after ``AT`` (18:00 New York) this sends one
ping, ``NOTES · week of <Monday>``, under its own budget (``note_digest``: one a day in ``notification_policy``):

- how many notes the week holds (Sunday ``AT`` to Sunday ``AT``, so no note is counted twice);
- their recurring themes: the tickers named most, then the words used in two or more notes (at most ``THEMES``);
- how many of the week's sent position-alert and Radar pings (``sent`` or ``unknown``) he rated, of how many;
- what holding past the week's position alerts did (``alert_scorecard.week_cost``): each pinged position measured once
  from its first alert, the dollars selling at that ping would have made against what he did, when one has closed;
- one "worth testing?" note, quoted: the newest that began with idea, else the newest naming a theme ticker, else the
  newest.

It is written here from the rows, with no model call, and is under a dozen lines. A week with no notes still sends the
digest (zero notes, the ratings line, and how to save one). Off unless ``NOTE_DIGEST_ENABLED=true``: switching it on is
the owner's call. At most once a week: the week is claimed through the notification policy (``new_only``), so a restart
never sends it twice, and a send that fails is not retried.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlmodel import Session, select

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

KIND = "note_digest"
AT = 18 * 60  # Sunday, New York
LOOP_SECONDS = 300
THEMES = 5
QUOTE = 160
WORD = re.compile(r"[a-z][a-z']{3,}")
STOP = frozenset("""about after again also always back been before being could didn does doing done down each even every
from going gonna good have here into just keep know like look looks looking made make maybe more most much need next only
other over really right same should since some still take than that their them then there these they thing think this
those through today tomorrow very want week well were what when where which while will with without would your yeah
note idea""".split())


def enabled() -> bool:
    return os.environ.get("NOTE_DIGEST_ENABLED", "false").strip().lower() == "true"


def _context(row) -> dict:
    try:
        found = json.loads(row.context_json or "{}")
    except (TypeError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def notes(db: Session, start_utc: datetime, end_utc: datetime) -> list[tuple]:
    """The Telegram notes saved in the window, oldest first, each with its context."""
    from app.models import DayJournalEntry
    rows = db.exec(select(DayJournalEntry).where(DayJournalEntry.context_json.is_not(None), DayJournalEntry.created_at >= start_utc,
                                                 DayJournalEntry.created_at < end_utc).order_by(DayJournalEntry.created_at)).all()
    return [(row, ctx) for row in rows if (ctx := _context(row)).get("source") == "telegram"]


def themes(found: list[tuple]) -> list[tuple[str, int]]:
    """The tickers named most (each note counts a ticker once), then words in two or more notes."""
    tickers = Counter(t for _, ctx in found for t in dict.fromkeys(ctx.get("tickers") or ()))
    named = {t.lower() for t in tickers}
    words = Counter(w for row, _ in found for w in set(WORD.findall(row.text.lower())) if w not in STOP and w not in named)
    out = tickers.most_common(3)
    out += [(w, n) for w, n in words.most_common() if n >= 2][:THEMES - len(out)]
    return out


def ratings(db: Session, start_utc: datetime, end_utc: datetime) -> tuple[int, int]:
    """(rated, got): the window's sent position-alert and Radar pings, and how many of them he rated."""
    from app.models import PositionAlert, PositionAlertFeedback, RadarAlert
    alerts = db.exec(select(PositionAlert.id).where(PositionAlert.delivery.in_(("sent", "unknown")), PositionAlert.detected_at >= start_utc,
                                                    PositionAlert.detected_at < end_utc)).all()
    rated = len(db.exec(select(PositionAlertFeedback.alert_id).where(PositionAlertFeedback.alert_id.in_(alerts))).all()) if alerts else 0
    radar = db.exec(select(RadarAlert.event_id).where(RadarAlert.delivery.in_(("sent", "unknown")), RadarAlert.detected_at >= start_utc,
                                                      RadarAlert.detected_at < end_utc)).all()
    if radar:
        try:
            from app.routers.radar import _require_store
            latest = _require_store().latest_ratings()
            rated += sum(1 for event_id in radar if event_id in latest)
        except Exception:  # noqa: BLE001 - the Radar file unreadable: its pings count as unrated
            log.warning("Radar ratings not read for the notes digest", exc_info=True)
    return rated, len(alerts) + len(radar)


def worth_testing(found: list[tuple], top: list[tuple[str, int]]) -> tuple | None:
    if not found:
        return None
    newest = list(reversed(found))
    top_tickers = {name for name, _ in top}
    return (next((n for n in newest if n[1].get("word") == "idea"), None)
            or next((n for n in newest if top_tickers & set(n[1].get("tickers") or ())), None) or newest[0])


def render(found: list[tuple], rated: int, got: int, week_of: str, cost: str | None = None) -> tuple[str, str]:
    """The ping's title and body."""
    title = f"NOTES · week of {week_of}"
    count = len(found)
    lines = [f"{count} note{'' if count == 1 else 's'} this week." if count else
             "No notes this week. Start a message or voice note with note or idea to save one."]
    top = themes(found)
    if top:
        lines.append("Themes: " + ", ".join(f"{name} ×{n}" if n > 1 else name for name, n in top))
    lines.append(f"Rated {rated} of {got} alert and Radar ping{'' if got == 1 else 's'}." if got else
                 "No alert or Radar pings this week.")
    if cost:
        lines.append(cost)
    if (pick := worth_testing(found, top)) is not None:
        row = pick[0]
        text = row.text if len(row.text) <= QUOTE else row.text[:QUOTE - 1].rstrip() + "…"
        day = row.created_at.replace(tzinfo=UTC).astimezone(ET).strftime("%a")
        lines.append(f"Worth testing? “{text}” ({day})")
    return title, "\n".join(lines)


def build(db: Session, now: float) -> tuple[str, str, str]:
    """(week key, title, body) for the week ending at this Sunday's ``AT`` (the latest one at or before ``now``), so two
    digests never count the same note and a late send counts the same week."""
    local = datetime.fromtimestamp(now, ET).date()
    sunday = local - timedelta(days=(local.weekday() + 1) % 7)
    cut = datetime.combine(sunday, datetime.min.time(), ET) + timedelta(minutes=AT)
    if cut.timestamp() > now:
        sunday, cut = sunday - timedelta(days=7), cut - timedelta(days=7)
    end = cut.astimezone(UTC).replace(tzinfo=None)
    start = end - timedelta(days=7)
    local = sunday
    monday = local - timedelta(days=local.weekday())
    found = notes(db, start, end)
    from app.engine import alert_scorecard
    cost = alert_scorecard.cost_line(alert_scorecard.week_cost(db, start, end))
    title, body = render(found, *ratings(db, start, end), monday.strftime("%b %-d"), cost)
    return local.isoformat(), title, body


class NoteDigest:
    def __init__(self, engine, *, clock: Callable[[], float] = time.time, send=None):
        self.engine, self.clock, self._send = engine, clock, send
        self._claimed: str | None = None  # the Sunday handled here, so the policy is not asked every pass

    def due(self, now: float) -> bool:
        local = datetime.fromtimestamp(now, ET)
        return local.weekday() == 6 and local.hour * 60 + local.minute >= AT and self._claimed != local.date().isoformat()

    def run(self) -> str:
        """Build and send this Sunday's digest once; what happened, for the log and tests."""
        from app.engine import notification_policy, phone
        now = self.clock()
        self._claimed = datetime.fromtimestamp(now, ET).date().isoformat()
        if self._send is None and not phone.configured():
            return "off: phone pings are not set up"
        try:
            with Session(self.engine) as db:
                week, title, body = build(db, now)
                ticket = notification_policy.decide(db, sender=KIND, source_id=week, kind=KIND, title=title, body=body,
                                                    now=now, new_only=True)
                if ticket.held:
                    return f"held: {ticket.reason}"
                path = "/daily"  # the day journal, where the notes are
                if self._send is not None:
                    self._send(title, body, path=path)
                else:
                    phone.send(title, body, kind=KIND, path=path, priority=2)
                notification_policy.delivered(db, ticket, now)
                db.commit()
            return "sent"
        except Exception as exc:  # noqa: BLE001 - recorded, never retried (a failed send may still have arrived)
            log.exception("Notes digest failed")
            return f"failed: {type(exc).__name__}"

    async def loop(self) -> None:
        while True:
            try:
                if self.due(self.clock()):
                    log.info("Notes digest: %s", await asyncio.to_thread(self.run))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Notes digest pass failed")
            await asyncio.sleep(LOOP_SECONDS)
