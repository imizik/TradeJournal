"""Open-trade phone alerts: a long option that was up gives its gain back, one
has been held an hour, or one is still open on its expiration day.

From the October 21, 2026 behavior audit (``backend/reports/behavior_audit_2026-10-21.md``):
trades that were green and were ridden back into losses, trades held from an
hour to the close, and options left to expire, are where the journal's money
goes. These alerts only tell the phone;
nothing here places, changes or suggests an order.

Off unless ``POSITION_ALERTS_ENABLED=true``. It runs on the level alert
monitor's loop (``level_alert_monitor.py``), at most every ``RUN_SECONDS``:

- **Give-back.** One Tradier quote request for every open long option. A
  position arms once its gain at the bid/ask midpoint reaches ``ARM_PCT`` of
  cost and ``ARM_DOLLARS``; the explicitly configured account gets a
  SPY/QQQ-only exception to the dollar floor. Once armed, a gain at or under
  ``FIRE_PCT`` sends one alert. A new cost basis (buying more, or a
  first-in-first-out sale that leaves differently priced lots) starts a new
  arming with a fresh peak; a sale
  that leaves the basis unchanged keeps it armed. Regular hours only. Tradier is read directly,
  never the dashboard's yfinance fallback, whose option prices are delayed;
  a quote whose bid or ask is older than ``MAX_QUOTE_AGE``, or wider than
  ``MAX_SPREAD`` of its midpoint, is not judged. The peak is what this loop saw, not the trade's
  whole path: a position opened before the switch-on starts at its first mark.
- **Last day.** An option still open on its expiration date gets one alert
  ``FIRST_MINUTES`` before the close and a last one ``FINAL_MINUTES`` before,
  from the market calendar (half days included). A first alert more than
  ``FIRST_GRACE_MINUTES`` late is skipped, and none is sent after the close;
  the last one states the minutes actually left. A contract too thin to price
  shows its bid rather than "no quote".
- **Held an hour.** Also off unless ``POSITION_HOLD_ALERTS=true``. Trades the
  audit found held from an hour to the same-day close lost $17,558, and 53 of
  those losers had been up 10% within their first hour; its suggestion was to
  re-decide any position still open after an hour. One alert when a position
  opened today reaches ``HOLD_MINUTES`` of the regular session, counted from
  its first entry fill (an entry before the open counts from the open). None
  when that lands at or after the close, when an expiry alert is due within
  ``FIRST_GRACE_MINUTES`` of it (expiry wins), or when it is more than
  ``FIRST_GRACE_MINUTES`` late. The clock is the first entry's, so it is one
  alert per position: it is recorded with the give-back generation current
  when it fired, and adding to the position (a new generation) neither restarts
  the clock nor sends another. A quote that cannot be judged still sends, saying so;
  the peak shown is what this loop saw.

An already-qualified alert also freezes optional same-session Radar entry context.
This does not participate in judging or delivery eligibility. Missing/stale context
never suppresses an alert; retries reuse the saved observations, not newer data.

Positions are anchored in their first entry fill's source identity (account
plus ``raw_email_id``), as saved-advice links are, so a trade rebuild does not
re-send anything. Delivery is at-most-once: a send that may have reached ntfy
is recorded ``unknown`` and never resent, and an alert not sent within
``EXPIRE_SECONDS`` is dropped, since a late give-back alert is wrong advice.
Right before the send, ``notification_policy.decide`` may hold it (``held``, with
the reason): the daily cap or a ping for the same position moments earlier.
Last-day final and give-back alerts are never over the cap.
"""

from datetime import UTC, date, datetime
import logging
import os
import time
from typing import Callable
from urllib.parse import urlencode
import uuid

import httpx
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import notification_policy, ntfy, position_alert_context
from app.engine.chart_journal import OPEN_SIDES, contract_label, open_lots
from app.engine.chart_math import ET, session_windows
from app.engine.occ import occ_symbol
from app.engine.tradier import TradierError, get_quotes_once
from app.models import Fill, PositionAlert, PositionWatch, Trade, TradeFill

log = logging.getLogger(__name__)

ARM_PCT = 0.10
ARM_DOLLARS = 50.0
FIRE_PCT = 0.03
MAX_SPREAD = 0.30  # of the midpoint
MAX_QUOTE_AGE = 120  # seconds since Tradier's bid time
FIRST_MINUTES = 90
FIRST_GRACE_MINUTES = 15
FINAL_MINUTES = 30
RUN_SECONDS = 30
CLAIM_SECONDS = 120
EXPIRE_SECONDS = 15 * 60
BACKOFF = (30, 60, 120, 300)
HOLD_MINUTES = 60
KINDS = ("giveback", "expiry_first", "expiry_final", "hold_hour")


def enabled() -> bool:
    return os.environ.get("POSITION_ALERTS_ENABLED", "").lower() == "true"


def floorless_giveback(position: dict) -> bool:
    """Whether this position has the explicitly scoped SPY/QQQ arming exception.

    The account UUID must be configured explicitly. Account names/labels are
    intentionally not used because they are mutable and can be duplicated.
    """
    configured = os.environ.get("POSITION_ALERTS_FLOORLESS_ACCOUNT_ID", "").strip()
    if not configured:
        return False
    try:
        account_id = uuid.UUID(configured)
    except (ValueError, AttributeError):
        return False
    trade = position.get("trade")
    return (position.get("account_id") == account_id
            and trade is not None
            and trade.instrument_type == "option"
            and trade.ticker in {"SPY", "QQQ"})


def hold_enabled() -> bool:
    return enabled() and os.environ.get("POSITION_HOLD_ALERTS", "").lower() == "true"


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _fresh(stamp_ms: int | None, now: float) -> bool:
    return stamp_ms is not None and now - stamp_ms / 1000 <= MAX_QUOTE_AGE


def judged_quote(quote, now: float) -> dict | None:
    """A Tradier option quote per contract: ``mark`` is the midpoint, or None when the quote is
    unfit to judge (wide, crossed, no bid); ``bid`` stays when it is fresh. None when nothing fresh."""
    if quote is None or quote.bid is None or not _fresh(quote.bid_date, now):
        return None
    out = {"mark": None, "bid": round(quote.bid * 100, 2), "quoted_at": quote.bid_date / 1000}
    if quote.ask is None or quote.bid <= 0 or quote.ask < quote.bid or not _fresh(quote.ask_date, now):
        return out
    mid = (quote.bid + quote.ask) / 2
    if (quote.ask - quote.bid) / mid <= MAX_SPREAD:
        out["mark"] = round(mid * 100, 2)
    return out


def anchor(entries) -> str:
    """A position's identity: its first entry fill's source ID. Ties at the same minute break on the
    source ID, never the fill UUID, which a re-import replaces."""
    first = min(entries, key=lambda f: (f.executed_at, f.raw_email_id or "", str(f.id)))
    return first.raw_email_id or str(first.id)


def hold_due(opened_at: datetime, today: date, regular, expires_today: bool) -> int | None:
    """The minute (ET) a position opened today has been held ``HOLD_MINUTES`` regular-session minutes, or None:
    opened another day, due at or after the close, or an expiry alert is due within ``FIRST_GRACE_MINUTES`` of it."""
    if opened_at.date() != today:
        return None
    due = max(opened_at.hour * 60 + opened_at.minute, regular[1]) + HOLD_MINUTES
    if due >= regular[2]:
        return None
    if expires_today:
        close = regular[2]
        if due >= close - FINAL_MINUTES or any(abs(due - at) < FIRST_GRACE_MINUTES for at in (close - FIRST_MINUTES, close - FINAL_MINUTES)):
            return None
    return due


def open_positions(db: Session) -> list[dict]:
    """Every open long option with what is still held, anchored in its first entry fill."""
    trades = db.exec(select(Trade).where(Trade.status == "open", Trade.instrument_type == "option",
                                         Trade.expiration.is_not(None))).all()
    if not trades:
        return []
    rows = db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at,
                          Fill.raw_email_id)
                   .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_([t.id for t in trades]))).all()
    by_trade: dict = {}
    for row in rows:
        by_trade.setdefault(row.trade_id, []).append(row)
    out = []
    for trade in trades:
        fills = sorted(by_trade.get(trade.id, []), key=lambda f: (f.executed_at, 0 if f.side in OPEN_SIDES else 1, str(f.id)))
        entries = [f for f in fills if f.role == "entry"]
        lots = open_lots([{"id": f.id, "side": f.side, "contracts": f.contracts, "price": f.price, "executed_at": f.executed_at}
                          for f in fills])
        if not entries or not lots["open"] or lots["avg_cost"] is None or lots["direction"] != "long":
            continue  # nothing held, or a short: these alerts judge long premium only
        out.append({
            "trade": trade, "account_id": trade.account_id, "source_key": anchor(entries), "opened_at": entries[0].executed_at,
            "contract": contract_label(trade.ticker, "option", trade.option_type, trade.strike, trade.expiration),
            "occ": occ_symbol(trade.ticker, trade.expiration, trade.option_type or "", float(trade.strike)),
            "contracts": lots["open"], "avg_cost": lots["avg_cost"], "expiration": trade.expiration,
        })
    return out


def _money(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{'+' if value >= 0 else '-'}${abs(value):,.0f}"


def _pct(value: float | None) -> str:
    return "?" if value is None else f"{value * 100:+.0f}%"


def _premium(per_contract: float | None) -> str:
    return "?" if per_contract is None else f"${per_contract / 100:,.2f}"


def _count(contracts: float) -> str:
    n = f"{contracts:g}"
    return f"{n} contract{'' if contracts == 1 else 's'}"


def _base_message(alert: PositionAlert, close_label: str | None = None, minutes_left: int | None = None) -> tuple[str, str, int]:
    """Title, body and ntfy priority for one alert."""
    if alert.mark is not None:
        now_part = f"now {_money(alert.gain)} ({_pct(alert.gain_pct)}) at a {_premium(alert.mark)} mid, bid {_premium(alert.bid)}"
    elif alert.bid is not None:
        now_part = f"bid {_premium(alert.bid)}, too thin to price at a midpoint"
    else:
        now_part = "no live quote right now"
    if alert.kind == "hold_hour":
        if alert.mark is None:
            now_part = "no reliable quote" + (f", bid {_premium(alert.bid)}" if alert.bid is not None else "")
        peak = "" if alert.peak_gain is None else f", best seen by the alert watch {_money(alert.peak_gain)} ({_pct(alert.peak_gain_pct)})"
        return (f"{alert.contract}: open an hour, re-decide",
                f"Open {HOLD_MINUTES} min, {now_part}{peak}. {_count(alert.contracts)} open. "
                f"Re-decide: close, trim, or set your exit.", 4)
    if alert.kind == "giveback":
        return (f"{alert.contract}: give-back triggered",
                f"Peak {_money(alert.peak_gain)} ({_pct(alert.peak_gain_pct)}), {now_part}. "
                f"Gain reached the +3% give-back threshold or below. {_count(alert.contracts)} open. Review your exit plan.", 4)
    when = f" The market closes at {close_label}." if close_label else ""
    if alert.kind == "expiry_first":
        return (f"{alert.contract} expires today and is still open",
                f"{_count(alert.contracts)} open, {now_part}.{when}", 4)
    left = f"{minutes_left} minute{'' if minutes_left == 1 else 's'}" if minutes_left is not None else "Under 30 minutes"
    return (f"{alert.contract}: {left} left, expires today",
            f"Still open: {_count(alert.contracts)}, {now_part}.{when}", 5)


def message(alert: PositionAlert, close_label: str | None = None, minutes_left: int | None = None) -> tuple[str, str, int]:
    title, body, priority = _base_message(alert, close_label, minutes_left)
    context = position_alert_context.phone_text(alert.context_snapshot_json)
    return title, body + ("\n\n" + context if context else ""), priority


ASK_KIND = {"giveback": "Give-back alert", "hold_hour": "One-hour alert", "expiry_first": "Expires-today alert",
            "expiry_final": "30-minutes-left alert"}


def ask_copilot_path(alert: PositionAlert) -> str:
    """The lab, prefilled to review this position with what the alert saw (docs/copilot-lab.md § Review a trade or position)."""
    was = f"was {_money(alert.peak_gain)}, " if alert.kind == "giveback" and alert.peak_gain is not None else ""
    now = f"now {_money(alert.gain)}" if alert.mark is not None else "no live quote"
    context = (f"Review this position: {alert.trade_id}. {ASK_KIND.get(alert.kind, 'Position alert')} at "
               f"{_clock_label(_minute_of(_epoch(alert.detected_at)))}: {was}{now}.")
    return "/copilot-lab?" + urlencode({"symbol": (alert.contract or "").split(" ")[0], "context": context[:300]})


def _ask_copilot(alert: PositionAlert) -> tuple[tuple[str, str], ...]:
    """The extra push action, only while Copilot Lab is on (its own switch, read here without loading the lab).
    Optional, so it can never stop the alert itself from going out."""
    if os.environ.get("COPILOT_ENABLED") != "true":
        return ()
    try:
        return (("Ask copilot", ask_copilot_path(alert)),)
    except Exception:  # noqa: BLE001 - the alert matters more than its extra button
        log.warning("Ask copilot action skipped for a position alert", exc_info=True)
        return ()


def _minute_of(stamp: float) -> int:
    moment = datetime.fromtimestamp(stamp, ET)
    return moment.hour * 60 + moment.minute


def _clock_label(minute: int) -> str:
    hour, rest = divmod(minute, 60)
    return f"{(hour - 1) % 12 + 1}:{rest:02d} {'AM' if hour < 12 else 'PM'}"


def _surely_unsent(exc: ntfy.NtfyError) -> bool:
    """True when the push certainly never reached ntfy: not configured, refused with a status, or no connection."""
    cause = exc.__cause__
    return cause is None or isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout))


class PositionAlerts:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time, quotes=get_quotes_once):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.quotes = quotes
        self._last_run = 0.0

    def run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        today, minute = moment.date(), moment.hour * 60 + moment.minute
        hours = self.calendar.hours(today) if self.calendar is not None else None
        regular = next((w for w in session_windows(today, hours) if w[0] == "regular"), None)
        if regular is None or not regular[1] <= minute < regular[2]:
            return
        with Session(self.engine) as db:
            positions = open_positions(db)
        if not positions:
            return
        marks = self._marks(positions, now)
        found = []
        with Session(self.engine) as db:
            for position in positions:
                mark = marks.get(position["occ"])
                found.extend(self._judge(db, position, mark, today, minute, regular, now))
            db.commit()
        for alert in found:
            self._record(alert, regular=regular)

    def _marks(self, positions: list[dict], now: float) -> dict:
        try:
            quotes = self.quotes(sorted({p["occ"] for p in positions if p["occ"]}))
        except TradierError as exc:
            log.info("Open-trade alerts: no option quotes this pass: %s", exc)
            return {}
        return {symbol: judged for symbol, quote in quotes.items() if (judged := judged_quote(quote, now))}

    def _judge(self, db: Session, position: dict, mark: dict | None, today: date, minute: int, regular, now: float) -> list[PositionAlert]:
        found = []
        held, cost = position["contracts"], position["avg_cost"]
        price = mark["mark"] if mark else None
        gain = gain_pct = None
        if price is not None:
            gain, gain_pct = round((price - cost) * held, 2), (price - cost) / cost
        watch = db.exec(select(PositionWatch).where(PositionWatch.account_id == position["account_id"],
                                                    PositionWatch.source_key == position["source_key"])).first()
        if watch is None:
            watch = PositionWatch(account_id=position["account_id"], source_key=position["source_key"], contracts=held, avg_cost=cost)
            db.add(watch)
        elif held > watch.contracts + 1e-9 or abs(cost - watch.avg_cost) > 0.01:
            # A new cost basis (bought more, or a sale left differently priced lots): a new arming.
            watch.generation += 1
            watch.peak_mark = watch.peak_at = watch.armed_at = None
        watch.contracts, watch.avg_cost, watch.updated_at = held, cost, _utc(now)
        if price is not None:
            if watch.peak_mark is None or price > watch.peak_mark:
                watch.peak_mark, watch.peak_at = price, _utc(now)
            if watch.armed_at is None:
                if gain_pct >= ARM_PCT and (floorless_giveback(position) or gain >= ARM_DOLLARS):
                    watch.armed_at = _utc(now)
            elif gain_pct <= FIRE_PCT:
                found.append(self._alert(position, "giveback", watch.generation, mark, gain, gain_pct, watch, now))
        if position["expiration"] == today:
            close = regular[2]
            first = close - FIRST_MINUTES
            kind = ("expiry_final" if minute >= close - FINAL_MINUTES
                    else "expiry_first" if first <= minute < first + FIRST_GRACE_MINUTES else None)
            if kind is not None:
                found.append(self._alert(position, kind, 0, mark, gain, gain_pct, None, now))
        if hold_enabled():
            due = hold_due(position["opened_at"], today, regular, position["expiration"] == today)
            if due is not None and due <= minute < due + FIRST_GRACE_MINUTES:
                found.append(self._alert(position, "hold_hour", watch.generation, mark, gain, gain_pct, watch, now))
        return found

    def _alert(self, position: dict, kind: str, generation: int, mark: dict | None, gain, gain_pct, watch, now: float) -> PositionAlert:
        cost, held = position["avg_cost"], position["contracts"]
        peak = watch.peak_mark if watch else None
        return PositionAlert(
            account_id=position["account_id"], source_key=position["source_key"], kind=kind, generation=generation,
            trade_id=position["trade"].id, contract=position["contract"], contracts=position["contracts"],
            avg_cost=round(cost, 2), mark=mark["mark"] if mark else None, bid=mark["bid"] if mark else None,
            gain=gain, gain_pct=gain_pct, peak_gain=None if peak is None else round((peak - cost) * held, 2),
            peak_gain_pct=None if peak is None else (peak - cost) / cost,
            quoted_at=_utc(mark["quoted_at"]) if mark else None, detected_at=_utc(now))

    def _record(self, alert: PositionAlert, *, regular=None) -> None:
        """Write one firing; a firing already written (this pass's retry, another process) is skipped."""
        with Session(self.engine) as db:
            exists = db.exec(select(PositionAlert.id).where(
                PositionAlert.account_id == alert.account_id, PositionAlert.source_key == alert.source_key,
                PositionAlert.kind == alert.kind, PositionAlert.generation == alert.generation)).first()
            if exists is not None:
                return
            if alert.kind in ("expiry_first", "hold_hour"):
                # A last-day alert already sent makes the first one moot; a held-an-hour alert is once per position.
                later = "expiry_final" if alert.kind == "expiry_first" else "hold_hour"
                other = db.exec(select(PositionAlert.id).where(
                    PositionAlert.account_id == alert.account_id, PositionAlert.source_key == alert.source_key,
                    PositionAlert.kind == later)).first()
                if other is not None:
                    return
            alert.context_snapshot_json = position_alert_context.capture(self.engine, alert, _epoch(alert.detected_at), regular)
            db.add(alert)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return
            log.info("Open-trade alert %s for %s", alert.kind, alert.contract)

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(PositionAlert).where(PositionAlert.delivery == "sending", PositionAlert.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(PositionAlert.id).where(PositionAlert.delivery == "pending")
                          .where((PositionAlert.next_attempt_at.is_(None)) | (PositionAlert.next_attempt_at <= _utc(now)))
                          .order_by(PositionAlert.detected_at).limit(20)).all()
        for alert_id in due:
            self._send(alert_id)

    def _send(self, alert_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(PositionAlert).where(PositionAlert.id == alert_id, PositionAlert.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            alert = db.get(PositionAlert, alert_id)
            if now - _epoch(alert.detected_at) > EXPIRE_SECONDS:
                alert.delivery, alert.last_error = "expired", "Not sent within 15 minutes, so it was not sent late."
                db.commit()
                return
            close = self._close(now) if alert.kind != "giveback" else None
            if alert.kind != "giveback" and (close is None or now >= close):
                alert.delivery, alert.last_error = "expired", "The market had closed, so it was not sent."
                db.commit()
                return
            if not ntfy.configured():
                alert.delivery, alert.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                alert.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            title, body, priority = message(alert, _clock_label(_minute_of(close)) if close else None,
                                            max(1, int((close - now) // 60)) if close else None)
            more = _ask_copilot(alert)
            ticket = notification_policy.decide(
                db, sender="position_alerts", source_id=str(alert.id), kind=alert.kind, title=title, body=body, now=now,
                anchor=notification_policy.anchor(alert.account_id, alert.source_key), symbol=(alert.contract or "").split(" ")[0],
                trade_id=alert.trade_id)
            if ticket.held:
                alert.delivery, alert.last_error = "held", ticket.reason
                db.commit()
                return
            alert.attempts += 1
            try:
                ntfy.publish(title, body + ticket.append, priority=priority, tags=("warning",),
                             path=f"/trades/{alert.trade_id}?alert={alert.id}", direct_click=True, more=more)
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    alert.delivery, alert.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    alert.delivery, alert.last_error = "pending", str(exc)
                    alert.next_attempt_at = _utc(now + BACKOFF[min(alert.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Open-trade alert delivery failed (attempt %d): %s", alert.attempts, exc)
                return
            alert.delivery, alert.delivered_at, alert.last_error = "sent", _utc(self.clock()), None
            notification_policy.delivered(db, ticket, now)
            db.commit()

    def _close(self, now: float) -> float | None:
        """Today's regular close as epoch seconds, or None on a closed day."""
        today = datetime.fromtimestamp(now, ET).date()
        hours = self.calendar.hours(today) if self.calendar is not None else None
        regular = next((w for w in session_windows(today, hours) if w[0] == "regular"), None)
        if regular is None:
            return None
        return datetime(today.year, today.month, today.day, regular[2] // 60, regular[2] % 60, tzinfo=ET).timestamp()


def for_trade(db: Session, trade: Trade) -> dict:
    """The trade page's view: alerts sent for this position and, while it is open, what is being watched."""
    floor_applies = not floorless_giveback({"account_id": trade.account_id, "trade": trade})
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                      .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    if not entries or trade.instrument_type != "option":
        return {"enabled": enabled(), "giveback_dollar_floor_applies": floor_applies, "alerts": [], "watch": None}
    key = anchor(entries)
    alerts = db.exec(select(PositionAlert).where(PositionAlert.account_id == trade.account_id, PositionAlert.source_key == key)
                     .order_by(PositionAlert.detected_at)).all()
    watch = db.exec(select(PositionWatch).where(PositionWatch.account_id == trade.account_id, PositionWatch.source_key == key)).first()
    return {
        "enabled": enabled(),
        "giveback_dollar_floor_applies": floor_applies,
        "alerts": [{
            "id": str(a.id), "contract": a.contract,
            "quoted_at": int(_epoch(a.quoted_at)) if a.quoted_at else None,
            "kind": a.kind, "detected_at": int(_epoch(a.detected_at)), "contracts": a.contracts, "mark": a.mark, "bid": a.bid,
            "gain": a.gain, "gain_pct": a.gain_pct, "peak_gain": a.peak_gain, "peak_gain_pct": a.peak_gain_pct,
            "delivery": a.delivery, "error": a.last_error,
            "delivered_at": int(_epoch(a.delivered_at)) if a.delivered_at else None,
        } for a in alerts],
        "watch": None if watch is None or trade.status != "open" else {
            "peak_gain": None if watch.peak_mark is None else round((watch.peak_mark - watch.avg_cost) * watch.contracts, 2),
            "peak_gain_pct": None if watch.peak_mark is None else (watch.peak_mark - watch.avg_cost) / watch.avg_cost,
            "armed": watch.armed_at is not None,
            "fired": any(a.kind == "giveback" and a.generation == watch.generation for a in alerts),
            "peak_at": int(_epoch(watch.peak_at)) if watch.peak_at else None,
        },
    }
