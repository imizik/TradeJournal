"""Fill-time pattern interrupts: when a new entry fill repeats one of the owner's own costly habits, one phone message
with the owner's own numbers for that habit. No advice, no model call; nothing here places, changes or suggests an order.

The October 21, 2026 behavior audit (``backend/reports/behavior_audit_2026-10-21.md``) found the money leaking at
exits and in a few repeated entry habits, and that since July the same mistakes cost more per trade because sizes
are larger. Eight pure rules judge each new **entry** fill, newest-first order:

- ``add_to_loser``: a second or later ``buy_to_open`` into a long option position still open, below the open lots'
  average cost (first in, first out, as ``chart_journal.open_lots`` replays it);
- ``put_entry``: a ``buy_to_open`` of a put;
- ``opened_green``: the account's realized P&L for the New York day is already above zero at the fill (trades
  closed earlier that day, as ``behavior.SequenceState`` sums them; the rule ``exit_habits.opened_green`` reads);
- ``late_short_dated``: a ``buy_to_open`` of an option with 0 to 2 trading days to expiry (weekdays; a market
  holiday counts as one) at or after 14:00 New York;
- ``ticker_record``: the owner has at least ``MIN_SAMPLE`` closed trades in the fill's ticker and their realized
  total is below zero (a positive or too-small record stays quiet, so familiar names do not spend the budget);
- ``large_size``: a ``buy_to_open`` of an option whose premium paid (contracts × price, fills storing option prices
  as dollars per contract) is at least ``LARGE_MULTIPLE`` times the median of the owner's closed long
  option positions entered in the last ``LARGE_LOOKBACK_DAYS`` (each position's largest entry fill), needing
  ``LARGE_MIN_ENTRIES`` of them, else it never fires;
- ``size_by_adding``: an add below cost (``add_to_loser``) to a long option with at most ``BUILT_DAYS`` calendar days to
  expiry that takes the premium paid into the position (every entry fill so far) to ``LARGE_MULTIPLE`` times that same
  median or more;
- ``quick_reentry``: a position's first ``buy_to_open`` of an option within ``REENTRY_MINUTES`` of the account's latest
  close that New York day, when that minute's closes lost money together (an add to an open position is not a
  re-entry).

The November 25, 2026 edge audit replayed these rules over every closed long option trade. A large first entry and a
late short-dated buy both flagged trades that, taken together, made money, while short-dated positions that became
large by adding below cost, and entries inside five minutes of a losing close, lost it. So the phone message leaves out ``large_size`` and ``late_short_dated`` (``NOT_SENT``); both
still judge an order on the desk's play check (``play_check.habits``), which shows the record either way.

A stock entry, and a short (``sell_to_open``), can fire only ``opened_green`` and ``ticker_record``: a stock's dollars
are not an option premium, and a short receives premium rather than paying it. The put, green-day, late-buy, ticker, size and
re-entry rules describe the position,
so each fires once per position (``ONCE_PER_POSITION``); adding to a loser fires on every such add. A fill whose
email arrives after a later entry's keeps the position's recorded anchor. Known limit, as for position alerts: a
message sent before an earlier entry fill arrived links the trade id of that moment, which the rebuild replaces, so
its link no longer opens. Each rule's line
carries the owner's record for that habit from closed trades in every account but Webull, never counting the
trade being judged (matched by its first entry fill's source identity, so a rebuild cannot slip it in):

- ``add_to_loser``: past long option positions with such an add, how many ended green, their P&L;
- ``put_entry``: lifetime long-put P&L and count against long-call P&L and count;
- ``opened_green``: trades whose first entry came with the day already green, their count and P&L;
- ``late_short_dated``: long options first bought that way, their count, expired-worthless share and P&L;
- ``ticker_record``: closed trades in the ticker, their count, share won and P&L;
- ``large_size``: the size against the median, and the window's past positions at or above the multiple, their
  count, share won and P&L;
- ``size_by_adding``: the position's premium against the median, and the window's past positions with at most
  ``BUILT_DAYS`` days to expiry at an add below cost that took the premium paid in to the multiple (the same test,
  at each past add), their count, share won and P&L;
- ``quick_reentry``: long options first bought within ``REENTRY_MINUTES`` of a losing close, their count, share won
  and P&L.

A record under ``MIN_SAMPLE`` (5) says "too few to read" instead of its share. The records are built once from
the journal and kept in memory for the New York day, rebuilt only when the closed trades change (their count or
realized total, which a rebuild or a new close moves), so a fill never waits on a heavy query.

**Cut line (the owner's own rule, not a record).** The November 25, 2026 edge audit found the money lost holding options
with ``BUILT_DAYS`` (3) calendar days or less to expiry once they were deep red. So a long option position's first
``buy_to_open`` with that little time left also says, once per position and only while ``CUT_LINE_PINGS=true`` (a second
switch, off by default), the contract price ``CUT_PCT`` (30%) under that entry and what it costs there; bought on its
expiration day before ``FLAT_BY`` (13:00 New York), also to be flat by then. The line is fixed at the first entry: an add
never moves it. It leads the message and titles it (``Cut line $2.17: NBIS 160P``), makes a sound, and goes to the policy
as its own kind (``cut_line``, just below ``interrupt``, no daily budget), so it never waits on the pattern lines' budget
and a later pattern, no-exit or one-hour ping for the position is not held by it. It is not judged on the desk's play
check.

Off unless ``FILL_INTERRUPTS_ENABLED=true`` (the owner's switch). It runs on the level alert monitor's loop, at
most every ``RUN_SECONDS``, in the regular session only. Only fills since this process started, and in the last
``STALE_SECONDS``, count, so switching it on (or a restart, or a late backfill) never interrupts old fills. Webull
is dormant and left out. Each entry fill is judged once, anchored in its own source identity (``FillInterrupt``,
unique per account and fill key); a fill that fired nothing is recorded ``none``. A fill that fires several rules
sends one message listing each. Delivery is at-most-once, as plan nudges': a send that may have reached the phone
is ``unknown`` and never resent, and a message not sent within ``EXPIRE_SECONDS`` or before the close is dropped.
Right before the send ``notification_policy.decide`` may hold it (kind ``interrupt``, ranked just below
``hold_hour``, its own daily budget ``PING_BUDGET_INTERRUPT``, default 4; the quiet window is per position). A message
with a loud line (``size_by_adding``) goes as kind ``interrupt_size``, ranked with ``hold_hour``: a silent pattern line
sent for the same position minutes earlier does not hold it, and it does not spend the silent lines' budget or wait on
it. A once-per-position line counts as said only when its message reached the phone or is on its way (``SAID``), or the policy merged it into another ping still being sent: one the policy
otherwise held, or that expired, is judged again at the position's next fill.

While Copilot Lab is on the message opens the desk's ping card on the interrupt (``card=interrupt:<id>``: Close,
Trim and Set stop first; any of them records the acknowledgement), else the trade page on it. Its Noted button opens
the trade page with ``noted=1``, where the page records the acknowledgement once
(``POST /trades/{trade_id}/fill-interrupts/{id}/noted``).
"""

from collections import defaultdict
from datetime import date, datetime, time as clock_time, timedelta
import logging
import os
from statistics import median
import time
from typing import Callable
from urllib.parse import urlencode
import uuid

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import notification_policy, phone, ping_images, practice_goal
from app.engine.analytics import wall_time
from app.engine.chart_journal import OPEN_SIDES, contract_label, open_lots, stamp
from app.engine.chart_math import ET, session_windows
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc, anchor
from app.models import Account, Fill, FillInterrupt, PhonePing, Trade, TradeFill

log = logging.getLogger(__name__)

RUN_SECONDS = 30
EXPIRE_SECONDS = 3 * 60
STALE_SECONDS = 15 * 60  # a fill first seen later than this after it happened is too late to interrupt
MIN_SAMPLE = 5
LATE_AT = clock_time(14, 0)
SHORT_DATED_DAYS = 2
LARGE_MULTIPLE = 2.0
LARGE_LOOKBACK_DAYS = 365
LARGE_MIN_ENTRIES = 20
BUILT_DAYS = 3  # calendar days to expiry: the audit's short-dated group, where averaging down into size lost the money
REENTRY_MINUTES = 5
EPS = 1e-9
CUT_PCT = 0.30  # the cut line: this far under a short-dated option's first entry price
FLAT_BY = clock_time(13, 0)  # a same-day option bought before this is told to be flat by it
LOUD_KINDS = frozenset({"size_by_adding", "cut_line"})  # position risk: these make a sound (phone.LOUD); the rest arrive silently
KINDS = ("add_to_loser", "put_entry", "opened_green", "late_short_dated", "ticker_record", "large_size", "size_by_adding",
         "quick_reentry")
ONCE_PER_POSITION = ("put_entry", "opened_green", "late_short_dated", "ticker_record", "large_size", "size_by_adding", "quick_reentry")
# Judged for the desk's play check, never a phone message. The last three since the November 25, 2026 ping review: the
# audit found ticker carries little, the October audit's put gap was not reliable, and the green-day walk-away ping
# (``day_lock``) says the green-day record once, before the entry, instead of after each one.
NOT_SENT = frozenset({"large_size", "late_short_dated", "ticker_record", "put_entry", "opened_green"})
SAID = ("pending", "sending", "sent", "unknown")  # a line held by the policy or expired never reached the phone: not said
LOUD_POLICY_KIND = "interrupt_size"  # the policy's kind for a message with the size-by-adding line
CUT_POLICY_KIND = "cut_line"  # ...and for one with the cut line; the rest go as "interrupt"
FOOTER = "Your record, not advice."


def enabled() -> bool:
    return os.environ.get("FILL_INTERRUPTS_ENABLED", "").lower() == "true"


def cut_line_enabled() -> bool:
    return enabled() and os.environ.get("CUT_LINE_PINGS", "").lower() == "true"


def policy_kind(kinds: set[str]) -> str:
    """The notification policy's kind for a message with these lines."""
    return LOUD_POLICY_KIND if "size_by_adding" in kinds else CUT_POLICY_KIND if "cut_line" in kinds else "interrupt"


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


def premium(fill: dict) -> float:
    """Dollars paid: contracts × price (option prices are stored per contract, multiplier included)."""
    return fill["contracts"] * fill["price"]


def ticker_record(rec: dict | None) -> bool:
    """The ticker's record (``record(rows, "ticker_record", ...)``) has enough trades and lost money."""
    return rec is not None and rec["n"] >= MIN_SAMPLE and rec["pnl"] < 0


def large_size(fill: dict, usual: float | None) -> bool:
    """An option bought to open paying at least ``LARGE_MULTIPLE`` times ``usual`` (None when the history is too short
    to say). A stock buy never fires: its dollars are not an option premium, so the median says nothing about it."""
    return (fill["side"] == "buy_to_open" and fill.get("instrument_type") == "option" and usual is not None
            and premium(fill) >= LARGE_MULTIPLE * usual - EPS)


def position_premium(fill: dict, prior: list[dict]) -> float:
    """Dollars paid into the position by every entry so far, this fill included (sales do not reduce it)."""
    return premium(fill) + sum(premium(f) for f in prior if f["side"] == "buy_to_open")


def size_by_adding(fill: dict, prior: list[dict], usual: float | None) -> bool:
    """An add below cost to a long option with at most ``BUILT_DAYS`` calendar days to expiry that takes the premium
    paid into the position to ``LARGE_MULTIPLE`` times ``usual`` or more (None: the history is too short to say)."""
    expiration = fill.get("expiration")
    if usual is None or expiration is None or not adds_to_loser(fill, prior):
        return False
    return (0 <= (expiration - fill["executed_at"].date()).days <= BUILT_DAYS
            and position_premium(fill, prior) >= LARGE_MULTIPLE * usual - EPS)


def cut_line(fill: dict, prior: list[dict]) -> float | None:
    """The cut-line price (per contract, as fills store it) for a long option position's first ``buy_to_open`` with at
    most ``BUILT_DAYS`` calendar days to expiry: ``CUT_PCT`` under that fill's price. None for any other fill."""
    expiration = fill.get("expiration")
    if (fill["side"] != "buy_to_open" or fill.get("instrument_type") != "option" or expiration is None
            or any(f["side"] == "buy_to_open" for f in prior)):
        return None
    if not 0 <= (expiration - fill["executed_at"].date()).days <= BUILT_DAYS:
        return None
    return fill["price"] * (1 - CUT_PCT)


def last_close(closes: list[tuple[datetime, float]], at: datetime) -> tuple[datetime, float] | None:
    """The latest minute with a close among the ``(closed_at, pnl)`` closes on ``at``'s New York day at or before
    ``at``, and that minute's total P&L (fill times carry minutes only, so a close and an entry in the same minute
    count as close then entry, and several closes in one minute are read together, whatever order they come in)."""
    def minute(moment: datetime) -> datetime:
        return moment.replace(second=0, microsecond=0)  # a manual fill can carry seconds
    same_day = [(minute(c[0]), c[1]) for c in closes if c[0].date() == at.date() and minute(c[0]) <= minute(at)]
    if not same_day:
        return None
    latest = max(c[0] for c in same_day)
    return latest, round(sum(c[1] for c in same_day if c[0] == latest), 2)  # to the cent: a flat minute is not a loss


def quick_reentry(fill: dict, last: tuple[datetime, float] | None) -> bool:
    """A ``buy_to_open`` of an option within ``REENTRY_MINUTES`` of ``last``, the account's latest close that day
    (``last_close``, a whole minute), when that close lost money."""
    if fill["side"] != "buy_to_open" or fill.get("instrument_type") != "option" or last is None:
        return False
    return last[1] < 0 and fill["executed_at"].replace(second=0, microsecond=0) - last[0] < timedelta(minutes=REENTRY_MINUTES)


def fired(fill: dict, prior: list[dict], day_pnl_before: float | None, ticker_rec: dict | None = None,
          size_rec: dict | None = None, built_rec: dict | None = None, last: tuple[datetime, float] | None = None) -> list[str]:
    """The rules this entry fill fires, in ``KINDS`` order. ``ticker_rec``, ``size_rec`` and ``built_rec`` are the
    fill's ticker, size and size-by-adding records (``record``), ``last`` the account's latest close that day
    (``last_close``); without them those rules do not fire."""
    out = []
    if adds_to_loser(fill, prior):
        out.append("add_to_loser")
    if is_put_entry(fill):
        out.append("put_entry")
    if opened_green(day_pnl_before):
        out.append("opened_green")
    if late_short_dated(fill):
        out.append("late_short_dated")
    if ticker_record(ticker_rec):
        out.append("ticker_record")
    if large_size(fill, (size_rec or {}).get("median")):
        out.append("large_size")
    if size_by_adding(fill, prior, (built_rec or {}).get("median")):
        out.append("size_by_adding")
    if quick_reentry(fill, last) and not any(f["side"] == "buy_to_open" for f in prior):  # a position's first entry, as its record counts
        out.append("quick_reentry")
    return out


def day_pnl_before(closes: list[tuple[datetime, float]], at: datetime) -> float:
    """The realized P&L of the ``(closed_at, pnl)`` closes on ``at``'s New York day, before ``at``."""
    return sum(pnl for closed, pnl in closes if closed.date() == at.date() and closed < at)


# ------------------------------------------------------------------ the record (pure)

def history_rows(trades: list[dict], fills_of: dict) -> list[dict]:
    """One row per closed trade with what each record counts. ``trades`` hold id, account_id, ticker, status,
    instrument_type, option_type, expiration, realized_pnl, expired_worthless and closed_at (naive New York);
    ``fills_of`` maps a trade id to its fills (id, key, role, side, contracts, price, executed_at)."""
    closed = [t for t in trades if t["status"] in ("closed", "expired") and t["closed_at"] is not None]
    closes: dict = defaultdict(list)
    for t in closed:
        closes[t["account_id"]].append((t["closed_at"], t["realized_pnl"] or 0.0))
    day_closes: dict = defaultdict(list)  # the re-entry rule never counts a trade's own close
    for t in closed:
        day_closes[t["account_id"], t["closed_at"].date()].append((t["closed_at"], t["realized_pnl"] or 0.0, t["id"]))
    rows = []
    for t in closed:
        fills = sorted(fills_of.get(t["id"], ()), key=_order)
        entries = [f for f in fills if f["role"] == "entry"]
        if not entries:
            continue
        first = entries[0]
        long_option = t["instrument_type"] == "option" and all(f["side"] == "buy_to_open" for f in entries)
        option = {"instrument_type": "option", "expiration": t["expiration"]}
        before = [c[:2] for c in day_closes[t["account_id"], first["executed_at"].date()] if c[2] != t["id"]]
        rows.append({
            "key": first.get("key") or str(first["id"]), "pnl": t["realized_pnl"] or 0.0, "ticker": t["ticker"],
            "entered": first["executed_at"].date(), "premium": max(premium(f) for f in entries),
            "long_option": long_option, "option_type": t["option_type"] if long_option else None,
            "expired_worthless": bool(t["expired_worthless"]),
            "added_to_loser": long_option and any(adds_to_loser({**f, **option}, fills[:i]) for i, f in enumerate(fills)
                                                  if f["role"] == "entry" and f is not first),
            "opened_green": opened_green(day_pnl_before(closes[t["account_id"]], first["executed_at"])),
            "late_short_dated": long_option and late_short_dated({**first, **option}),
            # The most paid into the position at an add the size-by-adding rule could fire on (below cost, short-dated).
            "built": max((position_premium(f, fills[:i]) for i, f in enumerate(fills)
                          if long_option and f["role"] == "entry" and f is not first and t["expiration"] is not None
                          and 0 <= (t["expiration"] - f["executed_at"].date()).days <= BUILT_DAYS
                          and adds_to_loser({**f, **option}, fills[:i])), default=0.0),
            "quick_reentry": long_option and quick_reentry({**first, **option}, last_close(before, first["executed_at"])),
        })
    return rows


def record(rows: list[dict], kind: str, exclude: str | None = None, *, ticker: str | None = None, day: date | None = None) -> dict:
    """One rule's record over ``rows``, leaving out the position whose first entry fill is ``exclude``. The ticker
    record needs ``ticker``; the size record needs the fill's ``day`` (its window ends there)."""
    rows = [r for r in rows if r["key"] != exclude]
    if kind == "ticker_record":
        hit = [r for r in rows if r["ticker"] == ticker]
        return {"ticker": ticker, "n": len(hit), "pnl": round(sum(r["pnl"] for r in hit), 2), "green": sum(1 for r in hit if r["pnl"] > 0)}
    if kind == "large_size":
        since = day - timedelta(days=LARGE_LOOKBACK_DAYS)
        window = [r for r in rows if r["long_option"] and since <= r["entered"] <= day]
        usual = median(r["premium"] for r in window) if len(window) >= LARGE_MIN_ENTRIES else None
        hit = [r for r in window if usual is not None and r["premium"] >= LARGE_MULTIPLE * usual - EPS]
        return {"n": len(hit), "pnl": round(sum(r["pnl"] for r in hit), 2), "green": sum(1 for r in hit if r["pnl"] > 0),
                "median": usual, "entries": len(window)}
    if kind == "size_by_adding":
        usual = record(rows, "large_size", day=day)["median"]
        hit = [r for r in rows if usual is not None and r["built"] > 0
               and day - timedelta(days=LARGE_LOOKBACK_DAYS) <= r["entered"] <= day and r["built"] >= LARGE_MULTIPLE * usual - EPS]
        return {"n": len(hit), "pnl": round(sum(r["pnl"] for r in hit), 2), "green": sum(1 for r in hit if r["pnl"] > 0), "median": usual}
    if kind == "put_entry":
        puts = [r for r in rows if r["long_option"] and r["option_type"] == "put"]
        calls = [r for r in rows if r["long_option"] and r["option_type"] == "call"]
        return {"n": len(puts), "pnl": round(sum(r["pnl"] for r in puts), 2),
                "calls": len(calls), "calls_pnl": round(sum(r["pnl"] for r in calls), 2)}
    flag = {"add_to_loser": "added_to_loser", "opened_green": "opened_green", "late_short_dated": "late_short_dated",
            "quick_reentry": "quick_reentry"}[kind]
    hit = [r for r in rows if r[flag]]
    return {"n": len(hit), "pnl": round(sum(r["pnl"] for r in hit), 2), "green": sum(1 for r in hit if r["pnl"] > 0),
            "expired": sum(1 for r in hit if r["expired_worthless"])}


# ------------------------------------------------------------------ the message (pure)

def money(value: float) -> str:
    """'+$8,710' or '−$2,140' (a minus sign, not a hyphen)."""
    return f"{'+' if value >= 0 else '−'}${abs(value):,.0f}"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def line(kind: str, rec: dict, day_pnl: float | None = None, paid: float | None = None, last: tuple[datetime, float] | None = None,
         at: datetime | None = None) -> str:
    """One rule's line with the owner's numbers and the sample; ``paid`` is the fill's premium for the size line and the
    position's for the size-by-adding line; ``last`` and ``at`` are the losing close and the fill's time for the
    re-entry line."""
    n = rec["n"]
    if kind == "size_by_adding":
        paid, usual = paid or 0.0, rec["median"]
        head = f"Size by adding: ${paid:,.0f} in this position is {paid / usual:.1f}× your median (${usual:,.0f}) after an add below cost"
        tail = f"your {_plural(n, 'past short-dated position')} built this way"
        return f"{head}; {tail}, too few to read" if n < MIN_SAMPLE else f"{head}; {tail}: {round(100 * rec['green'] / n)}% won, {money(rec['pnl'])}"
    if kind == "quick_reentry":
        gap = "" if last is None or at is None else f" {int((at - last[0]).total_seconds() // 60)} min after a {money(last[1])} close"
        head = f"Back in{gap}: {n:,} past {'entry' if n == 1 else 'entries'} within {REENTRY_MINUTES} min of a losing close"
        return f"{head}, too few to read" if n < MIN_SAMPLE else f"{head}, {round(100 * rec['green'] / n)}% won, {money(rec['pnl'])}"
    if kind == "ticker_record":
        head = f"Your record in {rec['ticker']}: {_plural(n, 'trade')}"
        return f"{head}, too few to read" if n < MIN_SAMPLE else f"{head}, {round(100 * rec['green'] / n)}% won, {money(rec['pnl'])}"
    if kind == "large_size":
        paid, usual = paid or 0.0, rec["median"]
        return f"Size: ${paid:,.0f} is {paid / usual:.1f}× your median (${usual:,.0f}); {size_tail(rec)}"
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


def quoted(per_contract: float) -> str:
    """'$1.05': an option price as the broker quotes it (fills store dollars per contract)."""
    return f"${per_contract / 100:,.2f}"


def cut_lines(fill: dict, cut: float) -> list[str]:
    """The cut line's own lines: the price and what the fill loses there; for a same-day option bought before
    ``FLAT_BY``, the time to be flat by."""
    count = fill["contracts"]
    out = [f"Cut line {quoted(cut)}: {CUT_PCT:.0%} under your {quoted(fill['price'])} entry, "
           f"{money((cut - fill['price']) * count)} on {count:g} contract{'' if count == 1 else 's'}"]
    if fill["expiration"] == fill["executed_at"].date() and fill["executed_at"].time() < FLAT_BY:
        out.append("Expires today: flat by 1 PM New York")
    return out


def size_tail(rec: dict) -> str:
    """The size line's record half (after the paid-versus-median half), which does not depend on the size paid."""
    n = rec["n"]
    tail = f"your {n:,} past {'entry' if n == 1 else 'entries'} above {LARGE_MULTIPLE:g}×"
    return f"{tail}, too few to read" if n < MIN_SAMPLE else f"{tail}: {round(100 * rec['green'] / n)}% won, {money(rec['pnl'])}"


def short_label(ticker: str, instrument_type: str, option_type: str | None, strike) -> str:
    """'NBIS 160C', or the ticker for a stock."""
    if instrument_type != "option" or strike is None:
        return ticker
    return f"{ticker} {float(strike):g}{'P' if option_type == 'put' else 'C'}"


def message(label: str, lines: list[str], practice: str | None = None) -> tuple[str, str]:
    """``practice`` is the week's practice-goal sentence (``practice_goal.ping_line``), kept above the footer."""
    return f"Pattern: {label}", "\n".join(lines + ([practice] if practice else []) + [FOOTER])


def practice_line(db: Session, kinds: list[str], day: date) -> str | None:
    """The practice goal's sentence when the green-day rule fired and the goal is not opening while green; None, never
    an error, otherwise."""
    if "opened_green" not in kinds:
        return None
    try:
        return practice_goal.ping_line(db, "no_opening_while_green", day)
    except Exception:  # noqa: BLE001 - the interrupt matters more than its extras
        log.warning("Practice line skipped", exc_info=True)
        return None


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
        for fill in fresh:  # one at a time: a fill judged after another in this pass sees what that one already said
            with Session(self.engine) as db:
                draft = self._judge(db, fill, rows, now)
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
        signature = history_signature(db, today)
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
        minute = fill["executed_at"].replace(second=0, microsecond=0)
        same_minute = db.exec(select(Trade.closed_at, Trade.realized_pnl).where(
            Trade.account_id == fill["account_id"], Trade.id != trade.id, Trade.status.in_(("closed", "expired")),
            Trade.closed_at >= fill["executed_at"], Trade.closed_at < minute + timedelta(minutes=1))).all()
        last = last_close([(wall_time(c), _num(p) or 0.0) for c, p in [*closes, *same_minute]], fill["executed_at"])
        # The put, green-day and late-buy rules describe the position: once each, so scaling in does not repeat them.
        earlier = db.exec(select(FillInterrupt.id, FillInterrupt.kinds, FillInterrupt.delivery).where(
            FillInterrupt.account_id == fill["account_id"], FillInterrupt.position_key == position)).all()
        # A held row the policy merged into another ping still being sent was said there.
        merged = set(db.exec(select(PhonePing.source_id).where(
            PhonePing.sender == "fill_interrupts", PhonePing.decision == "merged",
            PhonePing.source_id.in_([str(r.id) for r in earlier if r.delivery == "held"]))).all())
        said = {k for r in earlier if r.delivery in SAID or str(r.id) in merged for k in r.kinds.split(",")}
        key = anchor(entries)
        recs = {"ticker_record": record(rows, "ticker_record", key, ticker=trade.ticker),
                "large_size": record(rows, "large_size", key, day=fill["executed_at"].date()),
                "size_by_adding": record(rows, "size_by_adding", key, day=fill["executed_at"].date())}
        kinds = [k for k in fired(fill, prior, day, recs["ticker_record"], recs["large_size"], recs["size_by_adding"], last)
                 if k not in NOT_SENT and (k not in said or k not in ONCE_PER_POSITION)]
        label = short_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike)
        paid = {"size_by_adding": position_premium(fill, prior)}
        title, body = message(label, [line(k, recs.get(k) or record(rows, k, key), day, paid.get(k, premium(fill)), last, fill["executed_at"])
                                      for k in kinds],
                              practice_line(db, kinds, fill["executed_at"].date()))
        cut = cut_line(fill, prior) if cut_line_enabled() and "cut_line" not in said else None
        if cut is not None:  # the owner's rule leads and titles the message; the footer follows record lines only
            title, body = f"Cut line {quoted(cut)}: {label}", "\n".join(cut_lines(fill, cut) + ([body] if kinds else []))
            kinds = ["cut_line", *kinds]
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
                db, sender="fill_interrupts", source_id=str(row.id), title=row.title, body=row.body, now=now,
                kind=policy_kind(set(row.kinds.split(","))),
                anchor=notification_policy.anchor(row.account_id, row.position_key), symbol=row.ticker, trade_id=row.trade_id)
            if ticket.held:
                row.delivery, row.last_error = "held", ticket.reason
                db.commit()
                return
            image = ping_images.picture(ping_images.prepare(db, _picture, row, now)) if row.attempts == 0 else None  # a retry goes as text
            row.attempts += 1
            try:
                _, image_state = phone.send(row.title, row.body + ticket.append, kind="interrupt", image=image, priority=4, tags=("mirror",),
                                            sound=bool(LOUD_KINDS & set(row.kinds.split(","))),
                                            path=phone.desk_link(path(row), symbol=row.ticker, card=f"interrupt:{row.id}"), direct_click=True,
                                            more=(("Noted", path(row, noted=True)),))
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


def history_signature(db: Session, today: date) -> tuple:
    """What the cached record rows depend on: the New York day, and the closed trades' count and realized total."""
    count, total = db.exec(select(func.count(Trade.id), func.sum(Trade.realized_pnl))
                           .where(Trade.status.in_(("closed", "expired")))).one()
    return today, count, round(float(total or 0), 2)


_USUAL: tuple | None = None


def usual_size(db: Session, today: date) -> float | None:
    """The median premium paid for a long option position over ``LARGE_LOOKBACK_DAYS`` (the large-size rule's usual,
    from the same cached record rows), or None while fewer than ``LARGE_MIN_ENTRIES`` are in the window. Cached per
    ``history_signature``, so the desk's read pays for it once a day or when a trade closes."""
    global _USUAL
    signature = history_signature(db, today)
    if _USUAL is None or _USUAL[0] != signature:
        since = today - timedelta(days=LARGE_LOOKBACK_DAYS)
        window = [r["premium"] for r in load_history(db) if r["long_option"] and since <= r["entered"] <= today]
        _USUAL = (signature, median(window) if len(window) >= LARGE_MIN_ENTRIES else None)
    return _USUAL[1]


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
    return history_rows([{"id": t.id, "account_id": t.account_id, "ticker": t.ticker, "status": t.status,
                          "instrument_type": t.instrument_type,
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
