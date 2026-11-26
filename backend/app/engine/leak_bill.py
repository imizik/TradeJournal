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
``add`` are billed as the add only, so no dollar is counted twice, and a buy after the cut is left as it happened
(by the rules nothing is held then, so it is no add).
A positive bill means the rules would have kept that much more; a week where the breaks paid says so.

Did the cut pings get followed (``follow``). The bill above prices the rules whether or not a ping fired; this part asks
whether he acted when one did. Each week's trade whose first buy sent a cut-line ping (``FillInterrupt`` with kind
``cut_line``, reached the phone or may have) is replayed on the same minute bars: the first regular-session minute the
contract traded at or under the line (``fill_interrupts.CUT_PCT`` under that first buy, the line the ping named) is the
cross. Sold within ``alert_scorecard.ACT_MINUTES`` of it is ``acted``; otherwise ``ignored``, and what the contracts held
at the cross fetched (first in, first out, nothing for any that expired) against selling them at that minute's price is
the cost of ignoring it. A line never traded through is ``not_hit``; no bars, ``unpriced``. The held-an-hour (the
short-dated, deep-red case is the only one sent) and 1 PM same-day pings come from ``alert_scorecard.week_by_kind``:
acted is a sale within the same minutes or an Exiting decision logged after it. Together they read how often the cut
pings change an exit, the evidence for or against an automatic exit.

The price is the minute bar's last trade (``alpaca.fetch_option_bars``, the window the path metrics cache), not a
quote that could surely have been sold at. A minute holding one of the trade's own fills is not judged, as the path
metrics read it. A short-dated trade held past the hour that no rule cut, with no bar where one could have (none
past the hour, or none from 13:00 for a same-day option still open then), cannot be priced: it is counted apart
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
from app.engine.chart_journal import OPEN_SIDES
from app.engine.alert_scorecard import ACT_MINUTES
from app.engine.fill_interrupts import BUILT_DAYS, CUT_PCT
from app.engine.position_alerts import AFTERNOON_MINUTE, DEEP_RED_PCT, HOLD_MINUTES, MORNING_END, SHORT_DATED_DAYS

log = logging.getLogger(__name__)

KIND = "leak_bill"
LOOP_SECONDS = 300
OPEN_MINUTE, CLOSE_MINUTE = 9 * 60 + 30, 16 * 60
EPS = 1e-9
RULES = (("deep_red", f"Held short-dated down {-DEEP_RED_PCT:.0%}+ past an hour"), ("add", "Added below cost"),
         ("past_1pm", "Same-day option held past 1 PM"))

PING_KINDS = ("hold_hour", "same_day_1pm")  # the position alerts that ask for the cut (the hour one is sent only deep red)


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
    contracts, price (dollars per contract), executed_at (naive New York) and id."""
    # The reconstructor's own order (time, opens before closes, fill id), so the lots here are the journal's lots.
    ordered = sorted(fills, key=lambda f: (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, str(f["id"])))
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
            # After the cut the rules hold nothing, so a later buy averages nothing down: it is left as it happened.
            below = out["cut"] is None and held > EPS and price < sum(lot[0] * lot[1] for lot in lots) / held - EPS
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


def unpriced(expiration: date, fills: list[dict], closed: datetime, bars: list[dict] | None) -> bool:
    """Whether a trade no hold rule cut had no price where one could have: no judged minute (regular session, not one
    of its own fills) while it was short-dated and past the hour, or, for a same-day option bought before noon and
    still open after 13:00 (which broke that rule whatever the price), none from 13:00 on."""
    first = min(f["executed_at"] for f in fills if f["role"] == "entry")
    busy = {f["executed_at"].replace(second=0, microsecond=0) for f in fills}
    usable = [at for at, _ in marks(bars) if first + timedelta(minutes=HOLD_MINUTES) <= at < closed and at not in busy
              and 0 <= (expiration - at.date()).days <= SHORT_DATED_DAYS]
    past_one = expiration == first.date() == closed.date() and _minute(first) < MORNING_END and _minute(closed) > AFTERNOON_MINUTE
    return not usable or (past_one and not any(_minute(at) >= AFTERNOON_MINUTE for at in usable))


def follow(expired: bool, fills: list[dict], bars: list[dict] | None) -> dict:
    """What he did once the contract traded at or under the cut line his first buy was pinged: ``state`` (``acted``,
    ``ignored``, ``not_hit`` or ``unpriced``), and for a cross the minute (``at``), the contracts open then (``held``) and
    ``cost``, selling them at that minute's price minus what they fetched (positive: holding past the line cost that much)."""
    ordered = sorted(fills, key=lambda f: (f["executed_at"], 0 if f["side"] in OPEN_SIDES else 1, str(f["id"])))
    entries = [f for f in ordered if f["role"] == "entry"]
    found = marks(bars)
    if not entries or not found:
        return {"state": "unpriced"}
    # The pinged buy: the first entry as the ping chose it (time, then source identity, never the fill UUID).
    first = min(entries, key=lambda f: (f["executed_at"], f.get("key") or str(f["id"])))
    line = first["price"] * (1 - CUT_PCT)
    for at, price in found:
        # Fills carry minutes only: one in the cross's own minute is counted after it, so a sale then is acting on it.
        before = [f for f in ordered if f["executed_at"].replace(second=0, microsecond=0) < at]
        held = sum(f["contracts"] * (1 if f["role"] == "entry" else -1) for f in before)
        if at < first["executed_at"] or held <= EPS or price > line + EPS:
            continue
        exits = [f for f in ordered if f["role"] == "exit" and f not in before]
        taken = proceeds = 0.0
        rolled = False
        for fill in exits:  # first in, first out: the contracts open at the cross close first
            used = min(float(fill["contracts"]), held - taken)
            if used <= EPS:
                break
            rolled |= str(fill.get("key") or "").startswith("roll:")  # a derived roll close is not a sale price
            proceeds += used * float(fill["price"])
            taken += used
        acted = any(f["executed_at"] < at + timedelta(minutes=ACT_MINUTES + 1) for f in exits)
        cost = price * held - proceeds if not rolled and (taken >= held - EPS or expired) else None
        return {"state": "acted" if acted else "ignored", "at": at, "held": held,
                "cost": None if cost is None else round(cost, 2)}
    return {"state": "not_hit"}


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
    trades and dollars in ``by_rule``, and ``unpriced`` short-dated trades held past the hour with no usable bar."""
    from app.engine import alert_scorecard
    from app.models import Account, Fill, FillInterrupt, Trade, TradeFill
    trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id).where(
        Trade.instrument_type == "option", Trade.status.in_(("closed", "expired")), Trade.closed_at.is_not(None),
        Trade.expiration.is_not(None), or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    trades = [t for t in trades if monday <= wall_time(t.closed_at).date() <= sunday]
    fills_of: dict = defaultdict(list)
    if trades:
        for f in db.exec(select(TradeFill.trade_id, TradeFill.role, Fill.id, Fill.side, Fill.contracts, Fill.price,
                                Fill.executed_at, Fill.raw_email_id).join(Fill, Fill.id == TradeFill.fill_id)
                         .where(TradeFill.trade_id.in_([t.id for t in trades]))).all():
            fills_of[f.trade_id].append({"id": f.id, "role": f.role, "side": f.side,
                                         "contracts": float(f.contracts), "price": float(f.price), "executed_at": wall_time(f.executed_at),
                                         "key": f.raw_email_id or str(f.id)})
    pinged = {(r.account_id, r.fill_key) for r in db.exec(select(FillInterrupt).where(
        FillInterrupt.kinds.contains("cut_line"), FillInterrupt.delivery.in_(alert_scorecard.SENT))).all()
        if "cut_line" in r.kinds.split(",")} if trades else set()
    out = {"trades": 0, "broke": 0, "broke_pnl": 0.0, "saved": 0.0, "unpriced": 0,
           "by_rule": {rule: {"trades": 0, "saved": 0.0} for rule, _ in RULES},
           "cut_line": {"pings": 0, "acted": 0, "ignored": 0, "not_hit": 0, "unpriced": 0, "ignored_cost": 0.0, "ignored_priced": 0}}
    for trade in trades:
        fills = fills_of[trade.id]
        entries = [f for f in fills if f["role"] == "entry"]
        if not entries or any(f["side"] != "buy_to_open" for f in entries):
            continue
        out["trades"] += 1
        first, closed = min(f["executed_at"] for f in entries), wall_time(trade.closed_at)
        held = 0 <= (trade.expiration - closed.date()).days <= SHORT_DATED_DAYS and closed >= first + timedelta(minutes=HOLD_MINUTES)
        ordered = sorted(entries, key=lambda f: (f["executed_at"], f["key"]))
        cut_pinged = (trade.account_id, ordered[0]["key"]) in pinged
        bars = bars_for(trade) if held or cut_pinged else None
        if cut_pinged:
            row = out["cut_line"]
            seen = follow(trade.status == "expired", fills, bars)
            row["pings"] += 1
            row[seen["state"]] += 1
            if seen["state"] == "ignored" and seen["cost"] is not None:
                row["ignored_priced"] += 1
                row["ignored_cost"] += seen["cost"]
        found = bill_trade(trade.expiration, trade.status == "expired", fills, bars)
        out["unpriced"] += held and found["cut"] is None and unpriced(trade.expiration, fills, closed, bars)
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
    out["cut_line"]["ignored_cost"] = round(out["cut_line"]["ignored_cost"], 2)
    start = datetime.combine(monday, datetime.min.time(), ET).astimezone(UTC).replace(tzinfo=None)
    end = datetime.combine(sunday + timedelta(days=1), datetime.min.time(), ET).astimezone(UTC).replace(tzinfo=None)
    out["pings"] = [r for r in alert_scorecard.week_by_kind(db, start, end) if r["kind"] in PING_KINDS]
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
    lines += follow_lines(bill)
    return title, "\n".join(lines)


def follow_lines(bill: dict) -> list[str]:
    """The bill's "did you follow the cut pings" lines: the cut line, then the deep-red hour and 1 PM pings."""
    out = []
    cut = bill.get("cut_line") or {}
    if cut.get("pings"):
        crossed = cut["acted"] + cut["ignored"]
        line = f"Cut line: {cut['pings']} pinged, {crossed} traded through it"
        if crossed:
            line += f", you sold within {ACT_MINUTES} min on {cut['acted']}"
        line += "."
        if cut["ignored_priced"]:
            total = cut["ignored_cost"]
            what = f"cost ${total:,.0f}" if total > 0.5 else f"paid ${-total:,.0f}" if total < -0.5 else "came out even"
            line += f" Holding past it {what}."
        if cut["unpriced"]:
            line += f" {cut['unpriced']} had no minute prices."
        out.append(line)
    for r in bill.get("pings") or ():
        line = f"{r['kind_label']} ping: acted on {r['acted']} of {r['pings']}."
        if r["ignored_closed"]:
            total = -r["ignored_vs_alert_usd"]
            what = f"cost ${total:,.0f}" if total > 0.5 else f"paid ${-total:,.0f}" if total < -0.5 else "came out even"
            line += f" Ignoring {r['ignored_closed']} {what}."
        out.append(line)
    if out:
        out.insert(0, "Did you follow the cut pings?")
    return out


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
