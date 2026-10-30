"""Fill-time pattern interrupts: when a new entry fill repeats one of the owner's own costly habits, one phone message
with the owner's own numbers for that habit. No advice, no model call; nothing here places, changes or suggests an order.

The October 21, 2026 behavior audit (``backend/reports/behavior_audit_2026-10-21.md``) found the money leaking at
exits and in a few repeated entry habits. Four pure rules judge each new **entry** fill, newest-first order:

- ``add_to_loser``: a second or later ``buy_to_open`` into a long option position still open, below the open lots'
  average cost (first in, first out, as ``chart_journal.open_lots`` replays it);
- ``put_entry``: a ``buy_to_open`` of a put;
- ``opened_green``: the account's realized P&L for the New York day is already above zero at the fill (trades
  closed earlier that day, as ``behavior.SequenceState`` sums them; the rule ``exit_habits.opened_green`` reads);
- ``late_short_dated``: a ``buy_to_open`` of an option with 0 to 2 trading days to expiry (weekdays; a market
  holiday counts as one) at or after 14:00 New York.

A stock entry can fire only ``opened_green``; a short (``sell_to_open``) only ``opened_green``. The put, green-day
and late-buy rules describe the position, so each fires once per position (``ONCE_PER_POSITION``); adding to a
loser fires on every such add. A fill whose email arrives after a later entry's keeps the position's recorded
anchor. Known limit, as for position alerts: a message sent before an earlier entry fill arrived links the trade
id of that moment, which the rebuild replaces, so its link no longer opens. Each rule's line
carries the owner's record for that habit from closed trades in every account but Webull, never counting the
trade being judged (matched by its first entry fill's source identity, so a rebuild cannot slip it in):

- ``add_to_loser``: past long option positions with such an add, how many ended green, their P&L;
- ``put_entry``: lifetime long-put P&L and count against long-call P&L and count;
- ``opened_green``: trades whose first entry came with the day already green, their count and P&L;
- ``late_short_dated``: long options first bought that way, their count, expired-worthless share and P&L.

A record under ``MIN_SAMPLE`` (5) says "too few to read" instead of its share. The records are built once from
the journal and kept in memory for the New York day, rebuilt only when the closed trades change (their count or
realized total, which a rebuild or a new close moves), so a fill never waits on a heavy query.

Off unless ``FILL_INTERRUPTS_ENABLED=true`` (the owner's switch). It runs on the level alert monitor's loop, at
most every ``RUN_SECONDS``, in the regular session only. Only fills since this process started, and in the last
``STALE_SECONDS``, count, so switching it on (or a restart, or a late backfill) never interrupts old fills. Webull
is dormant and left out. Each entry fill is judged once, anchored in its own source identity (``FillInterrupt``,
unique per account and fill key); a fill that fired nothing is recorded ``none``. A fill that fires several rules
sends one message listing each. Delivery is at-most-once, as plan nudges': a send that may have reached the phone
is ``unknown`` and never resent, and a message not sent within ``EXPIRE_SECONDS`` or before the close is dropped.
Right before the send ``notification_policy.decide`` may hold it (kind ``interrupt``, ranked just below
``hold_hour``, its own daily budget ``PING_BUDGET_INTERRUPT``, default 4; the quiet window is per position).

The message opens the trade page on the interrupt; its Noted button opens the same page with ``noted=1``, where
the page records the acknowledgement once (``POST /trades/{trade_id}/fill-interrupts/{id}/noted``).
"""

from collections import defaultdict
from datetime import date, datetime, time as clock_time, timedelta
import logging
import os
import time
from typing import Callable
from urllib.parse import urlencode
import uuid

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import notification_policy, phone, ping_images
from app.engine.analytics import wall_time
from app.engine.chart_journal import OPEN_SIDES, contract_label, open_lots, stamp
from app.engine.chart_math import ET, session_windows
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc, anchor
from app.models import Account, Fill, FillInterrupt, Trade, TradeFill

log = logging.getLogger(__name__)

RUN_SECONDS = 30
EXPIRE_SECONDS = 3 * 60
STALE_SECONDS = 15 * 60  # a fill first seen later than this after it happened is too late to interrupt
MIN_SAMPLE = 5
LATE_AT = clock_time(14, 0)
SHORT_DATED_DAYS = 2
EPS = 1e-9
KINDS = ("add_to_loser", "put_entry", "opened_green", "late_short_dated")
ONCE_PER_POSITION = ("put_entry", "opened_green", "late_short_dated")
FOOTER = "Your record, not advice."


def enabled() -> bool:
    return os.environ.get("FILL_INTERRUPTS_ENABLED", "").lower() == "true"


# ------------------------------------------------------------------ the rules (pure)

def _order(f: dict) -> tuple:
    """The reconstructor's order: time, opens before closes, then the source identity (stable across a re-import)."""
    return (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, f.get("key") or str(f["id"]))


def trading_days(day: date, expiration: date) -> int:
    """Weekdays after ``day`` through ``expiration``: 0 when it expires that day, negative once past."""
    if expiration <= day:
        return (expiration - day).days
    return sum(1 for i in range(1, (expiration - day).days + 1) if (day + timedelta(days=i)).weekday() < 5)


def adds_to_loser(fill: dict, prior: list[dict]) -> bool:
    """A ``buy_to_open`` of an option into a long position still open after ``prior`` (the position's fills before
    it), below the open lots' average cost."""
    if fill["side"] != "buy_to_open" or fill.get("instrument_type") != "option" or not prior:
        return False
    lots = open_lots(prior)
    return lots["open"] > EPS and lots["direction"] == "long" and lots["avg_cost"] is not None and fill["price"] < lots["avg_cost"] - EPS


def is_put_entry(fill: dict) -> bool:
    return fill["side"] == "buy_to_open" and fill.get("instrument_type") == "option" and fill.get("option_type") == "put"


def opened_green(day_pnl_before: float | None) -> bool:
    return day_pnl_before is not None and day_pnl_before > 0


def late_short_dated(fill: dict) -> bool:
    """A ``buy_to_open`` of an option at or after 14:00 New York with 0 to 2 trading days to expiry."""
    expiration = fill.get("expiration")
    if fill["side"] != "buy_to_open" or fill.get("instrument_type") != "option" or expiration is None:
        return False
    at = fill["executed_at"]
    return at.time() >= LATE_AT and 0 <= trading_days(at.date(), expiration) <= SHORT_DATED_DAYS


def fired(fill: dict, prior: list[dict], day_pnl_before: float | None) -> list[str]:
    """The rules this entry fill fires, in ``KINDS`` order."""
    out = []
    if adds_to_loser(fill, prior):
        out.append("add_to_loser")
    if is_put_entry(fill):
        out.append("put_entry")
    if opened_green(day_pnl_before):
        out.append("opened_green")
    if late_short_dated(fill):
        out.append("late_short_dated")
    return out


def day_pnl_before(closes: list[tuple[datetime, float]], at: datetime) -> float:
    """The realized P&L of the ``(closed_at, pnl)`` closes on ``at``'s New York day, before ``at``."""
    return sum(pnl for closed, pnl in closes if closed.date() == at.date() and closed < at)


# ------------------------------------------------------------------ the record (pure)

def history_rows(trades: list[dict], fills_of: dict) -> list[dict]:
    """One row per closed trade with what each record counts. ``trades`` hold id, account_id, status,
    instrument_type, option_type, expiration, realized_pnl, expired_worthless and closed_at (naive New York);
    ``fills_of`` maps a trade id to its fills (id, key, role, side, contracts, price, executed_at)."""
    closed = [t for t in trades if t["status"] in ("closed", "expired") and t["closed_at"] is not None]
    closes: dict = defaultdict(list)
    for t in closed:
        closes[t["account_id"]].append((t["closed_at"], t["realized_pnl"] or 0.0))
    rows = []
    for t in closed:
        fills = sorted(fills_of.get(t["id"], ()), key=_order)
        entries = [f for f in fills if f["role"] == "entry"]
        if not entries:
            continue
        first = entries[0]
        long_option = t["instrument_type"] == "option" and all(f["side"] == "buy_to_open" for f in entries)
        option = {"instrument_type": "option", "expiration": t["expiration"]}
        rows.append({
            "key": first.get("key") or str(first["id"]), "pnl": t["realized_pnl"] or 0.0,
            "long_option": long_option, "option_type": t["option_type"] if long_option else None,
            "expired_worthless": bool(t["expired_worthless"]),
            "added_to_loser": long_option and any(adds_to_loser({**f, **option}, fills[:i]) for i, f in enumerate(fills)
                                                  if f["role"] == "entry" and f is not first),
            "opened_green": opened_green(day_pnl_before(closes[t["account_id"]], first["executed_at"])),
            "late_short_dated": long_option and late_short_dated({**first, **option}),
        })
    return rows


def record(rows: list[dict], kind: str, exclude: str | None = None) -> dict:
    """One rule's record over ``rows``, leaving out the position whose first entry fill is ``exclude``."""
    rows = [r for r in rows if r["key"] != exclude]
    if kind == "put_entry":
        puts = [r for r in rows if r["long_option"] and r["option_type"] == "put"]
        calls = [r for r in rows if r["long_option"] and r["option_type"] == "call"]
        return {"n": len(puts), "pnl": round(sum(r["pnl"] for r in puts), 2),
                "calls": len(calls), "calls_pnl": round(sum(r["pnl"] for r in calls), 2)}
    flag = {"add_to_loser": "added_to_loser", "opened_green": "opened_green", "late_short_dated": "late_short_dated"}[kind]
    hit = [r for r in rows if r[flag]]
    return {"n": len(hit), "pnl": round(sum(r["pnl"] for r in hit), 2), "green": sum(1 for r in hit if r["pnl"] > 0),
            "expired": sum(1 for r in hit if r["expired_worthless"])}


# ------------------------------------------------------------------ the message (pure)

def money(value: float) -> str:
    """'+$8,710' or '−$2,140' (a minus sign, not a hyphen)."""
    return f"{'+' if value >= 0 else '−'}${abs(value):,.0f}"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def line(kind: str, rec: dict, day_pnl: float | None = None) -> str:
    """One rule's line with the owner's numbers and the sample."""
    n = rec["n"]
    if kind == "add_to_loser":
        head = f"Adding to a loser: {_plural(n, 'past add')}"
        return f"{head}, too few to read" if n < MIN_SAMPLE else f"{head}, {rec['green']:,} ended green, {money(rec['pnl'])}"
    if kind == "put_entry":
        if n < MIN_SAMPLE:
            return f"Put entry: {_plural(n, 'past put')}, too few to read"
        calls = (f"calls {rec['calls']:,}, too few to read" if rec["calls"] < MIN_SAMPLE
                 else f"calls {money(rec['calls_pnl'])} over {rec['calls']:,}")
        return f"Put entry: puts {money(rec['pnl'])} over {_plural(n, 'trade')}; {calls}"
    if kind == "opened_green":
        head = f"Day already green ({money(day_pnl or 0)} today): {_plural(n, 'past trade')} opened green"
        return f"{head}, too few to read" if n < MIN_SAMPLE else f"{head}, {money(rec['pnl'])}"
    head = f"Late short-dated buy: {_plural(n, 'past buy')} after 2 PM with 0–2 days left"
    if n < MIN_SAMPLE:
        return f"{head}, too few to read"
    return f"{head}, {round(100 * rec['expired'] / n)}% expired worthless, {money(rec['pnl'])}"


def short_label(ticker: str, instrument_type: str, option_type: str | None, strike) -> str:
    """'NBIS 160C', or the ticker for a stock."""
    if instrument_type != "option" or strike is None:
        return ticker
    return f"{ticker} {float(strike):g}{'P' if option_type == 'put' else 'C'}"


def message(label: str, lines: list[str]) -> tuple[str, str]:
    return f"Pattern: {label}", "\n".join(lines + [FOOTER])


# ------------------------------------------------------------------ the pass

def _regular(calendar, day: date):
    hours = calendar.hours(day) if calendar is not None else None
    return next((w for w in session_windows(day, hours) if w[0] == "regular"), None)


def _naive_ny(at: float) -> datetime:
    return datetime.fromtimestamp(at, ET).replace(tzinfo=None)


def _num(value) -> float | None:
    return None if value is None else float(value)


class FillInterrupts:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.started_at = clock()  # fills before this are never judged
        self._last_run = 0.0
        self._history: tuple | None = None  # (signature, rows)

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
            fresh = self._new_fills(db, now)
            if not fresh:
                return
            rows = self.history(db, moment.date())
            drafts = [self._judge(db, fill, rows, now) for fill in fresh]
        for draft in drafts:
            self._record(draft)

    def _new_fills(self, db: Session, now: float) -> list[dict]:
        """Entry fills since start and in the last ``STALE_SECONDS``, outside Webull, not judged yet."""
        since = _naive_ny(max(self.started_at - 60, now - STALE_SECONDS))  # a whole-minute fill time
        rows = db.exec(select(TradeFill.trade_id, Fill.id, Fill.account_id, Fill.raw_email_id, Fill.side, Fill.contracts, Fill.price,
                              Fill.executed_at, Fill.instrument_type, Fill.option_type, Fill.expiration)
                       .join(TradeFill, TradeFill.fill_id == Fill.id).join(Account, Account.id == Fill.account_id)
                       .where(TradeFill.role == "entry", Fill.executed_at > since,
                              or_(Account.broker.is_(None), Account.broker != "webull"))).all()
        if not rows:
            return []
        keys = [r.raw_email_id or str(r.id) for r in rows]
        seen = {(a, k) for a, k in db.exec(select(FillInterrupt.account_id, FillInterrupt.fill_key).where(FillInterrupt.fill_key.in_(keys)))}
        return [{"trade_id": r.trade_id, "id": r.id, "key": r.raw_email_id or str(r.id), "account_id": r.account_id, "side": r.side,
                 "contracts": float(r.contracts), "price": float(r.price), "executed_at": wall_time(r.executed_at),
                 "instrument_type": r.instrument_type, "option_type": r.option_type, "expiration": r.expiration}
                for r in sorted(rows, key=lambda r: (r.executed_at, r.raw_email_id or ""))
                if (r.account_id, r.raw_email_id or str(r.id)) not in seen]

    def history(self, db: Session, today: date) -> list[dict]:
        """The record rows, rebuilt only on a new day or when the closed trades' count or realized total moved."""
        count, total = db.exec(select(func.count(Trade.id), func.sum(Trade.realized_pnl))
                               .where(Trade.status.in_(("closed", "expired")))).one()
        signature = (today, count, round(float(total or 0), 2))
        if self._history is None or self._history[0] != signature:
            self._history = (signature, load_history(db))
        return self._history[1]

    def _judge(self, db: Session, fill: dict, rows: list[dict], now: float) -> FillInterrupt:
        trade = db.get(Trade, fill["trade_id"])
        links = db.exec(select(TradeFill.role, Fill.id, Fill.raw_email_id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at)
                        .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id == trade.id)).all()
        fills = sorted(({"id": f.id, "key": f.raw_email_id or str(f.id), "role": f.role, "side": f.side, "contracts": float(f.contracts),
                         "price": float(f.price), "executed_at": wall_time(f.executed_at)} for f in links), key=_order)
        entries = [f for f in links if f.role == "entry"]
        # A fill whose email came before an earlier entry's keeps the anchor already recorded for the position, so the
        # quiet window still sees one position and its first message stays on the trade page.
        position = db.exec(select(FillInterrupt.position_key).where(
            FillInterrupt.account_id == fill["account_id"], FillInterrupt.fill_key.in_([f.raw_email_id or str(f.id) for f in entries]))
            .order_by(FillInterrupt.detected_at)).first() or anchor(entries)
        prior = [f for f in fills if _order(f) < _order(fill)]
        start = datetime.combine(fill["executed_at"].date(), clock_time())
        closes = db.exec(select(Trade.closed_at, Trade.realized_pnl).where(
            Trade.account_id == fill["account_id"], Trade.id != trade.id, Trade.status.in_(("closed", "expired")),
            Trade.closed_at >= start, Trade.closed_at < fill["executed_at"])).all()
        day = day_pnl_before([(wall_time(c), _num(p) or 0.0) for c, p in closes], fill["executed_at"])
        # The put, green-day and late-buy rules describe the position: once each, so scaling in does not repeat them.
        said = {k for kinds in db.exec(select(FillInterrupt.kinds).where(
            FillInterrupt.account_id == fill["account_id"], FillInterrupt.position_key == position)) for k in kinds.split(",")}
        kinds = [k for k in fired(fill, prior, day) if k not in said or k not in ONCE_PER_POSITION]
        label = short_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike)
        title, body = message(label, [line(k, record(rows, k, anchor(entries)), day) for k in kinds])
        return FillInterrupt(
            account_id=fill["account_id"], fill_key=fill["key"], position_key=position, trade_id=trade.id, ticker=trade.ticker,
            contract=contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
            kinds=",".join(kinds), title=title, body=body, executed_at=fill["executed_at"], detected_at=_utc(now),
            delivery="pending" if kinds else "none")

    def _record(self, row: FillInterrupt) -> None:
        with Session(self.engine) as db:
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # another process judged this fill a moment earlier
                return
            if row.kinds:
                log.info("Fill interrupt %s for %s", row.kinds, row.contract)

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            # A claim this old may have reached the phone before the pass died: never resent.
            db.exec(update(FillInterrupt).where(FillInterrupt.delivery == "sending", FillInterrupt.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(FillInterrupt.id).where(FillInterrupt.delivery == "pending")
                          .where((FillInterrupt.next_attempt_at.is_(None)) | (FillInterrupt.next_attempt_at <= _utc(now)))
                          .order_by(FillInterrupt.detected_at).limit(20)).all()
        for row_id in due:
            self._send(row_id)

    def _send(self, row_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(FillInterrupt).where(FillInterrupt.id == row_id, FillInterrupt.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            row = db.get(FillInterrupt, row_id)
            moment = datetime.fromtimestamp(now, ET)
            regular = _regular(self.calendar, moment.date())
            if now - _epoch(row.detected_at) > EXPIRE_SECONDS or regular is None or moment.hour * 60 + moment.minute >= regular[2]:
                row.delivery = "expired"
                row.last_error = f"Not sent within {EXPIRE_SECONDS // 60} minutes of the fill or before the close, so it was not sent late."
                db.commit()
                return
            if not phone.configured():
                row.delivery, row.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                row.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            ticket = notification_policy.decide(
                db, sender="fill_interrupts", source_id=str(row.id), kind="interrupt", title=row.title, body=row.body, now=now,
                anchor=notification_policy.anchor(row.account_id, row.position_key), symbol=row.ticker, trade_id=row.trade_id)
            if ticket.held:
                row.delivery, row.last_error = "held", ticket.reason
                db.commit()
                return
            image = ping_images.picture(ping_images.prepare(db, _picture, row, now)) if row.attempts == 0 else None  # a retry goes as text
            row.attempts += 1
            try:
                _, image_state = phone.send(row.title, row.body + ticket.append, kind="interrupt", image=image, priority=4, tags=("mirror",),
                                            path=path(row), direct_click=True, more=(("Noted", path(row, noted=True)),))
            except phone.SendError as exc:
                if not _surely_unsent(exc):
                    row.delivery, row.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    row.delivery, row.last_error = "pending", str(exc)
                    row.next_attempt_at = _utc(now + BACKOFF[min(row.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Fill interrupt delivery failed (attempt %d): %s", row.attempts, exc)
                return
            row.delivery, row.delivered_at, row.last_error = "sent", _utc(self.clock()), None
            notification_policy.delivered(db, ticket, now)
            ping_images.record(db, ticket, image_state)
            db.commit()


def path(row: FillInterrupt, *, noted: bool = False) -> str:
    """The trade page on this interrupt; with ``noted`` the page records the acknowledgement once on open."""
    return f"/trades/{row.trade_id}?" + urlencode({"interrupt": row.id, **({"noted": 1} if noted else {})})


def _picture(db: Session, row: FillInterrupt, now: float):
    """The message's chart: the last 90 minutes with the position's entries."""
    return ping_images.fill_window(row.title, row.ticker, ping_images.entry_fills(db, row.trade_id), now)


def load_history(db: Session) -> list[dict]:
    """``history_rows`` over every closed trade outside Webull."""
    trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                     .where(Trade.status.in_(("closed", "expired")), or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    if not trades:
        return []
    ids = [t.id for t in trades]
    links = db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.raw_email_id, Fill.side, Fill.contracts, Fill.price,
                           Fill.executed_at).join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(ids))).all()
    fills_of: dict = defaultdict(list)
    for f in links:
        fills_of[f.trade_id].append({"id": f.id, "key": f.raw_email_id or str(f.id), "role": f.role, "side": f.side,
                                     "contracts": float(f.contracts), "price": float(f.price), "executed_at": wall_time(f.executed_at)})
    return history_rows([{"id": t.id, "account_id": t.account_id, "status": t.status, "instrument_type": t.instrument_type,
                          "option_type": t.option_type, "expiration": t.expiration, "realized_pnl": _num(t.realized_pnl),
                          "expired_worthless": t.expired_worthless, "closed_at": wall_time(t.closed_at) if t.closed_at else None}
                         for t in trades], fills_of)


# ------------------------------------------------------------------ the trade page

def for_trade(db: Session, trade: Trade) -> list[dict]:
    """This position's interrupts that fired, oldest first, for the trade page."""
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                      .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    if not entries:
        return []
    keys = [f.raw_email_id or str(f.id) for f in entries]
    rows = db.exec(select(FillInterrupt).where(FillInterrupt.account_id == trade.account_id, FillInterrupt.fill_key.in_(keys),
                                               FillInterrupt.delivery != "none").order_by(FillInterrupt.detected_at)).all()
    return [shape(r) for r in rows]


def shape(row: FillInterrupt) -> dict:
    return {"id": str(row.id), "contract": row.contract, "kinds": [k for k in row.kinds.split(",") if k], "title": row.title,
            "lines": row.body.split("\n"), "executed_at": stamp(row.executed_at), "detected_at": int(_epoch(row.detected_at)),
            "delivery": row.delivery, "error": row.last_error, "noted_at": int(_epoch(row.noted_at)) if row.noted_at else None}


def note(db: Session, trade: Trade, interrupt_id: uuid.UUID, now: float) -> dict | None:
    """Record the owner's Noted once; a repeated tap keeps the first time. None when it is not this position's."""
    if not any(r["id"] == str(interrupt_id) for r in for_trade(db, trade)):
        return None
    row = db.get(FillInterrupt, interrupt_id)
    if row.noted_at is None:
        row.noted_at = _utc(now)
        db.add(row)
        db.commit()
        db.refresh(row)
    return shape(row)
