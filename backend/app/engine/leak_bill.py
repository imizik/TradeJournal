"""The Sunday leak bill: one ping with one dollar number, what breaking the leak rules cost that week.

The November 24, 2026 edge audit found the money leaking in three habits on long options, not in size or late buys.
For each long option trade (every entry a ``buy_to_open``, Webull left out) that closed in the New York week (Monday to
Sunday, by close date), this replays the trade's own fills first in, first out against the contract's minute bars and
prices what each rule would have done instead:

- ``add``: a buy below the open lots' average cost (``fill_interrupts.adds_to_loser``) with at most ``BUILT_DAYS``
  calendar days to expiry. The rule: do not buy it. Its cost is what those contracts lost (their price minus what they
  later sold for, nothing for any that expired). Needs no bars.
- ``deep_red``: the first regular-session minute, ``HOLD_MINUTES`` or more after the first entry and with at most
  ``SHORT_DATED_DAYS`` calendar days to expiry, where the open contracts are worth ``DEEP_RED_PCT`` or less against
  their cost. The rule: sell there.
- ``past_1pm``: an option that expires the day it was first bought, bought before noon and still open at 13:00 (the
  1 PM alert's own test, ``position_alerts.same_day_due``). The rule: sell there.

A trade is cut once, at whichever of the last two comes first (a minute that meets both reads ``deep_red``). The cut's
cost is that minute's price times the contracts open then, minus what those contracts later sold for. Contracts from an
``add`` are billed as the add only, so no dollar is counted twice, and a buy after the cut is left as it happened.
A positive bill means the rules would have kept that much more; a week where the breaks paid says so.

The price is the minute bar's last trade (``alpaca.fetch_option_bars``, the window the path metrics cache), not a
quote that could surely have been sold at. A minute holding one of the trade's own fills is not judged, as the path
metrics read it. A short-dated trade held past the hour with no bars cannot be priced: it is counted apart
(``unpriced``) and named in the message, never billed as zero.

Off unless ``LEAK_BILL_ENABLED=true`` (the owner's switch). Sunday at or after ``note_digest.AT`` (18:00 New York), at
most once a week through the notification policy (``new_only``, kind ``leak_bill``, its own budget of one a day), a
failed send never retried. A week with no closed long option trade sends nothing. Read-only: nothing here writes a
trade, fill or stored money value.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from typing import Callable

from sqlalchemy import or_
from sqlmodel import Session, select

from app.engine import note_digest
from app.engine.analytics import wall_time
from app.engine.chart_math import ET
from app.engine.fill_interrupts import BUILT_DAYS, _order
from app.engine.position_alerts import AFTERNOON_MINUTE, DEEP_RED_PCT, HOLD_MINUTES, MORNING_END, SHORT_DATED_DAYS

log = logging.getLogger(__name__)

KIND = "leak_bill"
LOOP_SECONDS = 300
OPEN_MINUTE, CLOSE_MINUTE = 9 * 60 + 30, 16 * 60
EPS = 1e-9
RULES = (("deep_red", f"Held short-dated down {-DEEP_RED_PCT:.0%}+ past an hour"), ("add", "Added below cost"),
         ("past_1pm", "Same-day option held past 1 PM"))


def enabled() -> bool:
    return os.environ.get("LEAK_BILL_ENABLED", "false").strip().lower() == "true"


def _minute(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def marks(bars: list[dict] | None) -> list[tuple[datetime, float]]:
    """Regular-session minute bars as (naive New York minute, last trade in dollars per contract), oldest first."""
    out = []
    for bar in bars or ():
        try:
            at = datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00"))
            close = float(bar["c"]) * 100
        except (KeyError, TypeError, ValueError):
            continue
        at = (at if at.tzinfo else at.replace(tzinfo=UTC)).astimezone(ET).replace(tzinfo=None, second=0, microsecond=0)
        if OPEN_MINUTE <= _minute(at) < CLOSE_MINUTE and close > 0:
            out.append((at, close))
    return sorted(out)


def bill_trade(expiration: date, expired: bool, fills: list[dict], bars: list[dict] | None) -> dict:
    """One long option trade against the rules: ``saved`` per rule (dollars the rule would have kept; negative when
    breaking it paid) and ``cut``, the rule and minute a hold rule fired at, if any. ``fills`` hold role, side,
    contracts, price (dollars per contract), executed_at (naive New York) and key or id."""
    ordered = sorted(fills, key=_order)
    entries = [f for f in ordered if f["role"] == "entry"]
    saved: dict[str, float] = defaultdict(float)
    out = {"saved": saved, "cut": None}
    if not entries:
        return out
    first = entries[0]["executed_at"]
    busy = {f["executed_at"].replace(second=0, microsecond=0) for f in ordered}
    lots: deque[list] = deque()  # [contracts, price, an add below cost, open at the cut]
    cut_price = None

    def settle(lot: list, used: float, price: float) -> None:
        if lot[2]:
            saved["add"] += (lot[1] - price) * used
        elif lot[3]:
            saved[out["cut"]["rule"]] += (cut_price - price) * used

    def apply(fill: dict) -> None:
        qty, price = float(fill["contracts"]), float(fill["price"])
        if fill["role"] == "entry":
            held = sum(lot[0] for lot in lots)
            below = held > EPS and price < sum(lot[0] * lot[1] for lot in lots) / held - EPS
            lots.append([qty, price, below and 0 <= (expiration - fill["executed_at"].date()).days <= BUILT_DAYS, False])
            return
        while qty > EPS and lots:
            used = min(qty, lots[0][0])
            settle(lots[0], used, price)
            lots[0][0] -= used
            qty -= used
            if lots[0][0] <= EPS:
                lots.popleft()

    pointer = 0
    for at, price in marks(bars):
        while pointer < len(ordered) and ordered[pointer]["executed_at"] <= at:
            apply(ordered[pointer])
            pointer += 1
        if out["cut"] is not None or not lots or at in busy:
            continue
        days = (expiration - at.date()).days
        held = sum(lot[0] for lot in lots)
        cost = sum(lot[0] * lot[1] for lot in lots)
        rule = None
        if 0 <= days <= SHORT_DATED_DAYS and at >= first + timedelta(minutes=HOLD_MINUTES) and cost > EPS \
                and price * held <= cost * (1 + DEEP_RED_PCT) + EPS:
            rule = "deep_red"
        elif days == 0 and first.date() == at.date() and _minute(first) < MORNING_END and _minute(at) >= AFTERNOON_MINUTE:
            rule = "past_1pm"
        if rule is not None:
            out["cut"], cut_price = {"rule": rule, "at": at, "price": price}, price
            for lot in lots:
                lot[3] = True
    for fill in ordered[pointer:]:
        apply(fill)
    if expired:
        for lot in lots:
            settle(lot, lot[0], 0.0)
    return out


def _bars(trade) -> list[dict] | None:
    """The contract's minute bars over the trade (the window the path metrics fetch, so their cache serves it); None
    when it has no contract symbol, runs too long, or the read fails."""
    from app.engine.alpaca import fetch_option_bars
    from app.engine.occ import occ_symbol
    from app.engine.trade_path import MAX_PATH_WINDOW_DAYS
    if trade.strike is None or not trade.option_type:
        return None
    symbol = occ_symbol(trade.ticker, trade.expiration, trade.option_type, float(trade.strike))
    opened, closed = wall_time(trade.opened_at), wall_time(trade.closed_at)
    if not symbol or (closed.date() - opened.date()).days + 1 > MAX_PATH_WINDOW_DAYS:
        return None
    try:
        return fetch_option_bars([symbol], "1Min", opened.replace(tzinfo=ET), closed.replace(tzinfo=ET)).get(symbol) or None
    except Exception:  # noqa: BLE001 - no bars: the trade is counted as not priced
        log.warning("Leak bill: no minute bars for %s", symbol, exc_info=True)
        return None


def week_bill(db: Session, monday: date, sunday: date, bars_for: Callable = _bars) -> dict:
    """The week's bill over the long option trades closed ``monday`` to ``sunday`` (New York dates, Webull left out):
    ``trades`` judged, ``broke`` (at least one rule), their realized ``broke_pnl``, ``saved`` (the number), per-rule
    trades and dollars in ``by_rule``, and ``unpriced`` short-dated trades held past the hour with no bars."""
    from app.models import Account, Fill, Trade, TradeFill
    trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id).where(
        Trade.instrument_type == "option", Trade.status.in_(("closed", "expired")), Trade.closed_at.is_not(None),
        Trade.expiration.is_not(None), or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    trades = [t for t in trades if monday <= wall_time(t.closed_at).date() <= sunday]
    fills_of: dict = defaultdict(list)
    if trades:
        for f in db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.raw_email_id, Fill.side, Fill.contracts, Fill.price,
                                Fill.executed_at).join(Fill, Fill.id == TradeFill.fill_id)
                         .where(TradeFill.trade_id.in_([t.id for t in trades]))).all():
            fills_of[f.trade_id].append({"id": f.id, "key": f.raw_email_id or str(f.id), "role": f.role, "side": f.side,
                                         "contracts": float(f.contracts), "price": float(f.price), "executed_at": wall_time(f.executed_at)})
    out = {"trades": 0, "broke": 0, "broke_pnl": 0.0, "saved": 0.0, "unpriced": 0,
           "by_rule": {rule: {"trades": 0, "saved": 0.0} for rule, _ in RULES}}
    for trade in trades:
        fills = fills_of[trade.id]
        entries = [f for f in fills if f["role"] == "entry"]
        if not entries or any(f["side"] != "buy_to_open" for f in entries):
            continue
        out["trades"] += 1
        first, closed = min(f["executed_at"] for f in entries), wall_time(trade.closed_at)
        bars = None
        if 0 <= (trade.expiration - closed.date()).days <= SHORT_DATED_DAYS and closed >= first + timedelta(minutes=HOLD_MINUTES):
            bars = bars_for(trade)
            out["unpriced"] += not marks(bars)
        found = bill_trade(trade.expiration, trade.status == "expired", fills, bars)
        if not found["saved"]:
            continue
        out["broke"] += 1
        out["broke_pnl"] += float(trade.realized_pnl or 0)
        for rule, dollars in found["saved"].items():
            out["by_rule"][rule]["trades"] += 1
            out["by_rule"][rule]["saved"] += dollars
            out["saved"] += dollars
    for row in (out, *out["by_rule"].values()):
        row["saved"] = round(row["saved"], 2)
    out["broke_pnl"] = round(out["broke_pnl"], 2)
    return out


def _signed(value: float) -> str:
    return f"{'-' if value < -0.5 else '+' if value > 0.5 else ''}${abs(value):,.0f}"


def _trades(n: int) -> str:
    return f"{n} trade{'' if n == 1 else 's'}"


def render(bill: dict, week_of: str) -> tuple[str, str]:
    """The ping's title (the number) and body."""
    saved, n = bill["saved"], bill["trades"]
    title = f"LEAK BILL · ${max(saved, 0):,.0f}"
    if not bill["broke"]:
        lines = [f"Week of {week_of}: none of your {n} option trade{'' if n == 1 else 's'} broke a leak rule."]
    else:
        if saved > 0.5:
            lines = [f"Week of {week_of}: breaking your leak rules cost ${saved:,.0f}."]
        elif saved < -0.5:
            lines = [f"Week of {week_of}: the trades that broke a leak rule came out ${-saved:,.0f} ahead of following it."]
        else:
            lines = [f"Week of {week_of}: breaking your leak rules came out even."]
        lines.append(f"{bill['broke']} of {n} option trades broke one and ended {_signed(bill['broke_pnl'])}; "
                     f"by the rules, {_signed(bill['broke_pnl'] + saved)}.")
        for rule, label in RULES:
            row = bill["by_rule"][rule]
            if row["trades"]:
                what = "came out even" if abs(row["saved"]) <= 0.5 else f"{'cost' if row['saved'] > 0 else 'paid'} ${abs(row['saved']):,.0f}"
                lines.append(f"{label}: {_trades(row['trades'])}, {what}.")
        if any(bill["by_rule"][rule]["trades"] for rule in ("deep_red", "past_1pm")):
            lines.append("Priced at that minute's last trade, not a quote.")
    if bill["unpriced"]:
        lines.append(f"{_trades(bill['unpriced'])} held short-dated past an hour had no minute prices: not in the number.")
    return title, "\n".join(lines)


def build(db: Session, now: float, bars_for: Callable = _bars) -> tuple[str, str, str] | None:
    """(week key, title, body) for the New York week ending at the latest Sunday send time at or before ``now``; None
    when no long option trade closed in it."""
    sunday = note_digest.window(now)[0]
    monday = sunday - timedelta(days=6)
    bill = week_bill(db, monday, sunday, bars_for)
    if not bill["trades"]:
        return None
    return sunday.isoformat(), *render(bill, monday.strftime("%b %-d"))


class LeakBill:
    def __init__(self, engine, *, clock: Callable[[], float] = time.time, send=None, bars_for: Callable = _bars):
        self.engine, self.clock, self._send, self.bars_for = engine, clock, send, bars_for
        self._claimed: str | None = None  # the Sunday handled here, so the policy is not asked every pass

    def due(self, now: float) -> bool:
        local = datetime.fromtimestamp(now, ET)
        return local.weekday() == 6 and _minute(local) >= note_digest.AT and self._claimed != local.date().isoformat()

    def run(self) -> str:
        """Build and send this Sunday's bill once; what happened, for the log and tests."""
        from app.engine import notification_policy, phone
        now = self.clock()
        self._claimed = datetime.fromtimestamp(now, ET).date().isoformat()
        if self._send is None and not phone.configured():
            return "off: phone pings are not set up"
        try:
            with Session(self.engine) as db:
                built = build(db, now, self.bars_for)
                if built is None:
                    return "nothing: no long option trade closed this week"
                week, title, body = built
                ticket = notification_policy.decide(db, sender=KIND, source_id=week, kind=KIND, title=title, body=body,
                                                    now=now, new_only=True)
                if ticket.held:
                    return f"held: {ticket.reason}"
                path = "/proof"  # the weekly leak trend
                if self._send is not None:
                    self._send(title, body, path=path)
                else:
                    phone.send(title, body, kind=KIND, path=path, priority=2)
                notification_policy.delivered(db, ticket, now)
                db.commit()
            return "sent"
        except Exception as exc:  # noqa: BLE001 - recorded, never retried (a failed send may still have arrived)
            log.exception("Leak bill failed")
            return f"failed: {type(exc).__name__}"

    async def loop(self) -> None:
        while True:
            try:
                if self.due(self.clock()):
                    log.info("Leak bill: %s", await asyncio.to_thread(self.run))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Leak bill pass failed")
            await asyncio.sleep(LOOP_SECONDS)
