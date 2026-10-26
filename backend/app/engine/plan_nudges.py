"""Plan pings for a new position: the unplanned-entry nudge and the one-tap link ping.

The owner often enters without a plan, and rarely links the plans they do save.
When a new position's first entry fill is ``GRACE_MINUTES`` old (default 3, so
a plan captured just before it, or a fill email's delay, does not false-fire)
and no plan is linked to the trade (``capture_links.for_trade``), one ntfy
notification goes out:

- a link ping when unlinked plans are suggested for it (``candidates``, from
  ``capture_links.suggestions``). It opens ``/plans/link?trade=…``, where the
  owner's tap on Link calls the existing link route: nothing is linked here;
- otherwise the nudge, which opens the copilot (``/copilot-lab?symbol=…&context=…``)
  to plan the position.

Nothing here places, changes or suggests an order.

Off unless ``PLAN_NUDGE_ENABLED=true``. It runs on the level alert monitor's
loop beside position alerts, at most every ``RUN_SECONDS``, in the regular
session only. Only entries since this process started count, so switching it
on (or a restart) never nudges positions already open. Webull is dormant and
left out. One ping (of either kind) per position, anchored in the first entry fill's source
identity as position alerts are, so a trade rebuild never re-sends. At most
``PLAN_NUDGE_DAILY_CAP`` (default 5), of both kinds, are sent a day; a position past the cap
is recorded ``skipped`` and not nudged later. Delivery is at-most-once, as
position alerts': a send that may have reached ntfy is ``unknown`` and never
resent, and a ping not sent within ``EXPIRE_SECONDS`` or before the close is
dropped. A link ping whose plans were all linked or set aside before it went out
is skipped. Right before the send, ``notification_policy.decide`` may hold it
(``held``, with the reason): the shared daily cap, or a ping for the same
position moments earlier.
"""

from datetime import UTC, date, datetime, timedelta
import json
import logging
import os
import time
from typing import Callable
from urllib.parse import quote, urlencode
import uuid

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import capture_links, notification_policy, ntfy, ping_images
from app.engine.captures import epoch
from app.engine.chart_journal import contract_label, stamp
from app.engine.chart_math import ET, session_windows
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc, anchor
from app.models import Account, Fill, PlanNudge, Trade, TradeCapture, TradeFill

log = logging.getLogger(__name__)

RUN_SECONDS = 30
EXPIRE_SECONDS = 15 * 60
CONTEXT_MAX = 300  # the copilot deep link's limit (frontend/lib/copilot.ts)
LINK_PATH = "/plans/link"  # the confirm page (frontend/app/plans/link)


def enabled() -> bool:
    return os.environ.get("PLAN_NUDGE_ENABLED", "").lower() == "true"


def _setting(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "").strip()))
    except ValueError:
        return default


def grace_seconds() -> int:
    return _setting("PLAN_NUDGE_GRACE_MINUTES", 3) * 60


def daily_cap() -> int:
    return _setting("PLAN_NUDGE_DAILY_CAP", 5)


def _short_label(nudge: PlanNudge, expiration: date | None, option_type: str | None, strike) -> str:
    if expiration is None:
        return f"{nudge.ticker} stock"
    return f"{nudge.ticker} {expiration.month}/{expiration.day} {float(strike):g}{'C' if option_type == 'call' else 'P'}"


def _size(nudge: PlanNudge) -> str:
    """'2 at $3.10' for options (premium per share), '10 shares at $120.00' for stock."""
    if nudge.contract.endswith(" stock"):
        return f"{nudge.contracts:g} share{'' if nudge.contracts == 1 else 's'} at ${nudge.price:,.2f}"
    return f"{nudge.contracts:g} at ${nudge.price / 100:,.2f}"


def message(nudge: PlanNudge, title_label: str) -> tuple[str, str, str]:
    """Title, body and the app path the notification opens."""
    verb = "sold to open" if nudge.side == "sell_to_open" else "opened"
    context = (f"Plan this position: I just {verb} {nudge.contract} ({_size(nudge)}) without a plan. "
               "Help me set an invalidation and a time stop.")[:CONTEXT_MAX]
    path = "/copilot-lab?" + urlencode({"symbol": nudge.ticker, "context": context}, quote_via=quote)
    return f"{title_label}: no plan yet", f"{verb.capitalize()} {_size(nudge)}. Tap for a 20-second plan.", path


def plan_name(capture: TradeCapture) -> str:
    return capture.setup_label or ("Voice plan" if capture.mode == "voice" else "Discretionary plan")


def _clock(received_at: datetime) -> str:
    """'9:58', New York time."""
    moment = received_at.replace(tzinfo=UTC).astimezone(ET)
    return f"{moment.hour % 12 or 12}:{moment.minute:02d}"


def link_message(title_label: str, plans: list[TradeCapture], trade_id: uuid.UUID) -> tuple[str, str, str]:
    """The link ping: title, body and the confirm page it opens."""
    if len(plans) == 1:
        body = f'Link it to your plan "{plan_name(plans[0])}" (captured {_clock(plans[0].received_at)})? Tap to confirm.'
    else:
        body = f"{len(plans)} of your saved plans match it. Tap to choose the one to link."
    return f"{title_label} filled", body, f"{LINK_PATH}?" + urlencode({"trade": str(trade_id)})


def candidates(db: Session, trade: Trade) -> list[TradeCapture]:
    """Unlinked plans, not marked not taken, that capture linking suggests for this trade, oldest first."""
    if not capture_links.reliable(trade.opened_at):
        return []
    start = capture_links.entry_utc(trade.opened_at)
    # Suggestions need receipt within the window before the entry's minute ends; only those plans are read.
    near = list(db.exec(select(TradeCapture).where(TradeCapture.received_at >= start - capture_links.WINDOW,
                                                   TradeCapture.received_at < start + timedelta(minutes=1),
                                                   TradeCapture.not_taken_at.is_(None)).order_by(TradeCapture.received_at)).all())
    links = capture_links.link_rows(db, near)
    unlinked = [c for c in near if links[c.id]["link"] is None]
    suggested = capture_links.suggestions(db, unlinked)
    return [c for c in unlinked if any(row["trade_id"] == str(trade.id) for row in suggested[c.id])]


def _regular(calendar, day: date):
    hours = calendar.hours(day) if calendar is not None else None
    return next((w for w in session_windows(day, hours) if w[0] == "regular"), None)


class PlanNudges:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.started_at = clock()  # entries before this are never nudged
        self._last_run = 0.0

    def run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        regular = _regular(self.calendar, moment.date())
        if regular is None or not regular[1] <= moment.hour * 60 + moment.minute < regular[2]:
            return
        with Session(self.engine) as db:
            for nudge in self._due(db, now, moment.date()):
                if capture_links.for_trade(db, nudge.trade_id):
                    continue
                trade = db.get(Trade, nudge.trade_id)
                if trade is not None and candidates(db, trade):
                    nudge.kind = "link"
                self._record(db, nudge, moment.date())

    def _due(self, db: Session, now: float, today: date) -> list[PlanNudge]:
        """Open trades whose first entry is new since start, past the grace period, today, and not nudged yet."""
        trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                         .where(Trade.status == "open", or_(Account.broker.is_(None), Account.broker != "webull"))).all()
        if not trades:
            return []
        rows = db.exec(select(TradeFill.trade_id, Fill.id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at, Fill.raw_email_id)
                       .join(Fill, Fill.id == TradeFill.fill_id)
                       .where(TradeFill.trade_id.in_([t.id for t in trades]), TradeFill.role == "entry")).all()
        entries: dict = {}
        for row in rows:
            entries.setdefault(row.trade_id, []).append(row)
        out = []
        for trade in trades:
            fills = entries.get(trade.id)
            if not fills:
                continue
            first = min(fills, key=lambda f: (f.executed_at, f.raw_email_id or "", str(f.id)))
            if not capture_links.reliable(first.executed_at) or first.executed_at.date() != today:
                continue
            opened = stamp(first.executed_at)
            # A whole-minute fill time: the fill may have come any time in that minute.
            if opened + 60 <= self.started_at or now < opened + grace_seconds():
                continue
            key = anchor(fills)
            if db.exec(select(PlanNudge.id).where(PlanNudge.account_id == trade.account_id, PlanNudge.source_key == key)).first():
                continue
            out.append(_draft(trade, fills, key, now))
        return out

    def _record(self, db: Session, nudge: PlanNudge, today: date) -> None:
        start = datetime(today.year, today.month, today.day, tzinfo=ET)
        counted = db.exec(select(func.count()).select_from(PlanNudge).where(
            PlanNudge.detected_at >= _utc(start.timestamp()), PlanNudge.detected_at < _utc((start + timedelta(days=1)).timestamp()),
            PlanNudge.delivery != "skipped")).one()
        if counted >= daily_cap():
            nudge.delivery = "skipped"
            nudge.last_error = f"Today's limit of {daily_cap()} plan pings was reached, so it was not sent."
        db.add(nudge)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # another process recorded this position a moment earlier
            return
        log.info("Plan %s %s for %s", "link ping" if nudge.kind == "link" else "nudge", nudge.delivery, nudge.contract)

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(PlanNudge).where(PlanNudge.delivery == "sending", PlanNudge.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(PlanNudge.id).where(PlanNudge.delivery == "pending")
                          .where((PlanNudge.next_attempt_at.is_(None)) | (PlanNudge.next_attempt_at <= _utc(now)))
                          .order_by(PlanNudge.detected_at).limit(20)).all()
        for nudge_id in due:
            self._send(nudge_id)

    def _send(self, nudge_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(PlanNudge).where(PlanNudge.id == nudge_id, PlanNudge.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            nudge = db.get(PlanNudge, nudge_id)
            moment = datetime.fromtimestamp(now, ET)
            regular = _regular(self.calendar, moment.date())
            if now - _epoch(nudge.detected_at) > EXPIRE_SECONDS or regular is None or moment.hour * 60 + moment.minute >= regular[2]:
                nudge.delivery, nudge.last_error = "expired", "Not sent within 15 minutes or before the close, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                nudge.delivery, nudge.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                nudge.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            trade = db.get(Trade, nudge.trade_id)
            label = _short_label(nudge, trade.expiration, trade.option_type, trade.strike) if trade else nudge.contract
            if nudge.kind == "link":
                plans = candidates(db, trade) if trade else []
                if not plans:
                    nudge.delivery = "skipped"
                    nudge.last_error = "Its plan was linked or set aside before the ping went out, so it was not sent."
                    db.commit()
                    return
                title, body, path = link_message(label, plans, trade.id)
            else:
                title, body, path = message(nudge, label)
            ticket = notification_policy.decide(
                db, sender="plan_nudges", source_id=str(nudge.id), kind="link" if nudge.kind == "link" else "nudge", title=title, body=body,
                now=now, anchor=notification_policy.anchor(nudge.account_id, nudge.source_key), symbol=nudge.ticker, trade_id=nudge.trade_id)
            if ticket.held:
                nudge.delivery, nudge.last_error = "held", ticket.reason
                db.commit()
                return
            image = ping_images.picture(ping_images.prepare(db, _picture, nudge, label, now))
            nudge.attempts += 1
            try:
                _, image_state = ping_images.publish(title, body + ticket.append, image, priority=4,
                                                     tags=("link" if nudge.kind == "link" else "memo",), path=path, direct_click=True)
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    nudge.delivery, nudge.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    nudge.delivery, nudge.last_error = "pending", str(exc)
                    nudge.next_attempt_at = _utc(now + BACKOFF[min(nudge.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Plan nudge delivery failed (attempt %d): %s", nudge.attempts, exc)
                return
            nudge.delivery, nudge.delivered_at, nudge.last_error = "sent", _utc(self.clock()), None
            notification_policy.delivered(db, ticket, now)
            ping_images.record(db, ticket, image_state)
            db.commit()


def _picture(db: Session, nudge: PlanNudge, label: str, now: float):
    """The ping's chart: the last 90 minutes with the fill."""
    return ping_images.fill_window(f"{label} · {'filled' if nudge.kind == 'link' else 'no plan'}", nudge.ticker,
                                   ping_images.entry_fills(db, nudge.trade_id), now)


def _draft(trade: Trade, fills, key: str, now: float) -> PlanNudge:
    """This position as an unsaved ping row: its first entry, size so far and share-weighted price."""
    first = min(fills, key=lambda f: (f.executed_at, f.raw_email_id or "", str(f.id)))
    held = float(sum(f.contracts for f in fills))  # Decimal from the database
    return PlanNudge(
        account_id=trade.account_id, source_key=key, trade_id=trade.id, ticker=trade.ticker,
        contract=contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
        side=first.side, contracts=held, price=round(float(sum(f.contracts * f.price for f in fills)) / held, 2),
        opened_at=first.executed_at, detected_at=_utc(now))


def _investigation(capture: TradeCapture) -> str | None:
    """The Copilot Lab investigation a plan card saved this plan from, when it says so."""
    try:
        value = json.loads(capture.context_json or "{}").get("investigation_id")
        return str(uuid.UUID(str(value))) if value else None
    except (ValueError, AttributeError):
        return None


def _plan_row(capture: TradeCapture, opened_at: datetime) -> dict:
    return {"capture_id": str(capture.id), "setup": plan_name(capture), "mode": capture.mode,
            "wording": capture.wording or capture.transcript_text, "note": capture.note, "received_at": epoch(capture.received_at),
            "timing": capture_links.timing(capture.received_at, opened_at), "investigation_id": _investigation(capture)}


def link_page(db: Session, trade: Trade, now: float) -> dict | None:
    """The confirm page's data: the position, the plans suggested for it, and any plan already linked. Only the
    trade, plan and investigation ids it links with; no account or fill ids."""
    fills = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                    .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    if not fills:
        return None
    row = _draft(trade, fills, anchor(fills), now)
    linked = capture_links.for_trade(db, trade.id)
    return {
        "trade": {"id": str(trade.id), "ticker": trade.ticker, "contract": row.contract, "status": trade.status,
                  "opened": "sold to open" if row.side == "sell_to_open" else "opened", "fill": _size(row),
                  "opened_at": stamp(row.opened_at), "opened_at_reliable": capture_links.reliable(row.opened_at)},
        "candidates": [] if linked else [_plan_row(c, row.opened_at) for c in candidates(db, trade)],
        "linked": [_plan_row(c, row.opened_at) for c in linked],
        "plan_path": message(row, row.contract)[2],
    }


def for_trade(db: Session, trade: Trade) -> list[dict]:
    """This position's nudge, shaped as a trade-page phone alert row."""
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                      .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    if not entries:
        return []
    rows = db.exec(select(PlanNudge).where(PlanNudge.account_id == trade.account_id, PlanNudge.source_key == anchor(entries))).all()
    return [{
        "id": str(n.id), "contract": n.contract, "kind": "plan_link" if n.kind == "link" else "plan_nudge", "detected_at": int(_epoch(n.detected_at)),
        "contracts": n.contracts, "entry": _size(n), "mark": None, "bid": None, "quoted_at": None, "gain": None, "gain_pct": None,
        "peak_gain": None, "peak_gain_pct": None, "delivery": n.delivery, "error": n.last_error,
        "delivered_at": int(_epoch(n.delivered_at)) if n.delivered_at else None,
    } for n in rows]
