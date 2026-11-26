"""The day card and the morning glance: the two summaries the phone gets without asking (November 26, 2026 UI pass).

``card`` is the after-close headline, read by the 4:30 evening ping (``engine/evening_review.py``) and the desk's day
report (``GET /copilot/desk/day-report``): today's realized P&L over the trades closed today, whether the cut pings were
followed today (``leak_bill.PING_KINDS`` through ``alert_scorecard.week_by_kind``, the scorecard the Sunday leak bill
reads, so "acted" means the same thing in both: a sale within its minutes or an Exiting decision after it), and what
expires the next trading day. ``holdings`` is what the 9:25 morning glance lists (``MorningGlance``): each open long
option with its expiry and, where the owner's cut-line rule applies (``fill_interrupts.cut_line``: a short-dated first
buy), the line itself.

Read-only: nothing here writes a trade, fill or stored money value, and nothing changes when a ping fires.

``MorningGlance`` is off unless ``MORNING_GLANCE_PINGS=true`` (the owner's switch). On a trading day at ``AT`` (09:25 New
York) and for ``WINDOW_MINUTES`` after, when at least one long option is open, one silent ping goes through the
notification policy (kind ``morning_glance``, once a day by ``new_only`` on the day's date, never held by the quiet
window or a budget). Nothing open, no ping. A failed send is never retried (it may have arrived).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, date, datetime, timedelta
from typing import Callable

from sqlmodel import Session

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

KIND = "morning_glance"
AT = 9 * 60 + 25
WINDOW_MINUTES = 30
LOOP_SECONDS = 60


def _calendar():
    try:
        from app.engine.chart_calendar import chart_calendar
        return chart_calendar
    except Exception:  # noqa: BLE001 - weekdays stand in for the calendar
        return None


def _money(value: float) -> str:
    return f"{'-' if value < -0.005 else '+' if value > 0.005 else ''}${abs(value):,.0f}"


def _premium(per_contract: float) -> str:
    """As the broker quotes it: fills (and so the cut line) store dollars per contract."""
    return f"${per_contract / 100:,.2f}"


def _short(expiration: date, today: date) -> str:
    days = (expiration - today).days
    if days == 0:
        return "expires today"
    if days == 1:
        return "expires tomorrow"
    if 1 < days < 7:
        return f"expires {expiration.strftime('%a')}"
    return f"expires {expiration.strftime('%b %-d')}"


def holdings(db: Session) -> list[dict]:
    """Each open long option (``position_alerts.open_positions``), soonest expiry first: ``contract``, ``contracts``,
    ``expiration`` and ``cut`` (the cut-line price in dollars per contract, as fills store it; None where the rule does not apply)."""
    from app.engine.fill_interrupts import cut_line
    from app.engine.position_alerts import open_positions
    out = []
    for p in open_positions(db):
        first = p.get("first_entry")
        cut = cut_line({**first, "instrument_type": "option", "expiration": p["expiration"]}, []) if first else None
        out.append({"contract": p["contract"], "contracts": p["contracts"], "expiration": p["expiration"], "cut": cut,
                    "trade_id": p["trade"].id})
    return sorted(out, key=lambda h: (h["expiration"], h["contract"]))


def card(db: Session, now: float, calendar=None) -> dict:
    """Today's card (New York day of ``now``): ``pnl`` and ``closed`` (realized over the trades closed today, Webull left
    out as on the desk), ``cut`` ({pings, acted} today; zero pings when none fired) and ``expiring`` (the holdings that
    expire the next trading day: contract, contracts, cut)."""
    from app.engine import alert_scorecard
    from app.engine.leak_bill import PING_KINDS
    from app.engine.position_alerts import trading_days_after
    from app.routers.copilot_desk import _realized_today
    day = datetime.fromtimestamp(now, ET).date()
    closed = _closed_today(db, day)
    realized = _realized_today(db, day)["usd"]
    start = datetime.combine(day, datetime.min.time(), ET).astimezone(UTC).replace(tzinfo=None)
    rows = [r for r in alert_scorecard.week_by_kind(db, start, start + timedelta(days=1)) if r["kind"] in PING_KINDS]
    nxt = trading_days_after(calendar if calendar is not None else _calendar(), day, 1)
    expiring = [{"contract": h["contract"], "contracts": h["contracts"], "cut": h["cut"]}
                for h in holdings(db) if nxt and h["expiration"] == nxt[0]]
    return {"day": day.isoformat(), "pnl": realized, "closed": closed,
            "cut": {"pings": sum(r["pings"] for r in rows), "acted": sum(r["acted"] for r in rows)},
            "expiring": expiring, "next_day": nxt[0].isoformat() if nxt else None}


def _closed_today(db: Session, day: date) -> int:
    from sqlmodel import func, select
    from app.ai.copilot_book import _not_webull
    from app.models import Account, Trade
    start = datetime(day.year, day.month, day.day)
    return int(db.exec(select(func.count()).select_from(Trade).join(Account, Account.id == Trade.account_id).where(_not_webull())
                       .where(Trade.closed_at >= start, Trade.closed_at < start + timedelta(days=1))).one())


def _count(n: float) -> str:
    return f"×{n:g}"


def card_lines(c: dict) -> tuple[str, str] | None:
    """The evening ping's (title, body) for a card; None when the day has nothing to say (no close, no cut ping, nothing
    expiring next session)."""
    if not c["closed"] and not c["cut"]["pings"] and not c["expiring"]:
        return None
    title = f"Today {_money(c['pnl'])}" if c["closed"] else "Today: nothing closed"
    lines = []
    if c["closed"]:
        lines.append(f"{c['closed']} trade{'' if c['closed'] == 1 else 's'} closed, {_money(c['pnl'])} realized.")
    if c["cut"]["pings"]:
        lines.append(f"Cut pings: acted on {c['cut']['acted']} of {c['cut']['pings']}.")
    if c["expiring"]:
        lines.append("Expires tomorrow: " + "; ".join(
            f"{e['contract']} {_count(e['contracts'])}" + (f", cut {_premium(e['cut'])}" if e["cut"] is not None else "")
            for e in c["expiring"]) + ".")
    return title, "\n".join(lines)


def glance_lines(held: list[dict], today: date) -> tuple[str, str] | None:
    """The morning glance's (title, body); None with nothing held."""
    if not held:
        return None
    title = f"You hold {len(held)}"
    lines = [f"{h['contract']} {_count(h['contracts'])} · {_short(h['expiration'], today)}"
             + (f" · cut {_premium(h['cut'])}" if h["cut"] is not None else "") for h in held]
    return title, "\n".join(lines)


def glance_enabled() -> bool:
    return os.environ.get("MORNING_GLANCE_PINGS", "false").strip().lower() == "true"


class MorningGlance:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time, send=None):
        self.engine, self.calendar, self.clock, self._send = engine, calendar, clock, send
        self._claimed: str | None = None  # the day handled here, so the policy is not asked every pass

    def due(self, now: float) -> bool:
        from app.engine.premarket_prep import _trading_day
        local = datetime.fromtimestamp(now, ET)
        minute = local.hour * 60 + local.minute
        return (AT <= minute < AT + WINDOW_MINUTES and self._claimed != local.date().isoformat()
                and _trading_day(self.calendar, local.date()))

    def run(self) -> str:
        """Send today's glance once; what happened, for the log and tests."""
        from app.engine import notification_policy, phone
        now = self.clock()
        today = datetime.fromtimestamp(now, ET).date()
        self._claimed = today.isoformat()
        if self._send is None and not phone.configured():
            return "off: phone pings are not set up"
        try:
            with Session(self.engine) as db:
                built = glance_lines(holdings(db), today)
                if built is None:
                    return "nothing: no option held"
                title, body = built
                ticket = notification_policy.decide(db, sender=KIND, source_id=today.isoformat(), kind=KIND, title=title, body=body,
                                                    now=now, new_only=True)
                if ticket.held:
                    return f"held: {ticket.reason}"
                path = "/copilot-lab"
                if self._send is not None:
                    self._send(title, body, path=path)
                else:
                    phone.send(title, body, kind=KIND, path=path, priority=2, direct_click=True)
                notification_policy.delivered(db, ticket, now)
                db.commit()
            return "sent"
        except Exception as exc:  # noqa: BLE001 - recorded, never retried (a failed send may still have arrived)
            log.exception("Morning glance failed")
            return f"failed: {type(exc).__name__}"

    async def loop(self) -> None:
        while True:
            try:
                if self.due(self.clock()):
                    log.info("Morning glance: %s", await asyncio.to_thread(self.run))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Morning glance pass failed")
            await asyncio.sleep(LOOP_SECONDS)
