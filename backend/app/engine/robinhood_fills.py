"""Fills from Robinhood's order history (docs/robinhood-order-fills.md): the journal learns of an execution within a
minute of the trade, and no fill is ever counted twice.

The design, in one paragraph. The fill email stays the journal's record. Every execution the order history shows is
recorded once (``robinhood_execution``, keyed by Robinhood's execution id) and paired, order by order, with the
journal's fills (``robinhood_reconciliation``): matched, pending (its email not due yet), order-history only, email
only, or mismatch. An execution is a **provisional** fact: it never becomes a fill and never reaches FIFO, trades or
P&L, except where no email will ever come: a recurring stock buy (``placed_agent: "recurring"``), which Robinhood never
emails. Only that order, once filled and paired with no fill already in the journal (an email, a manual fill, a
``csvfix`` backfill), is written as one fill (``raw_email_id`` ``robinhood:<order id>``, a fixed id from the order id)
and the trades are rebuilt in the same transaction. If an email does later arrive for a written order,
``email_already_written`` keeps it out (no second fill) and records it on the order's row; a disagreement is a
mismatch listed with both versions, never resolved by itself.

Modes: ``ROBINHOOD_FILLS_ENABLED`` off (default; nothing runs), ``shadow`` (reads, records and reconciles, writes no
fill: the row says ``would_write_fill``) or ``true`` (also writes the fills no email will bring). Either needs the read
feed on (``ROBINHOOD_READ_ENABLED`` and a usable sign-in); the reads go through the feed's sign-in and the read-only
client. Only an account's last four digits are kept or shown; no account number reaches a row, a log line, the screen
or the copilot.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from sqlalchemy import text
from sqlmodel import Session, col, select

from app.engine import robinhood_book as rb
from app.engine import robinhood_read as rh
from app.engine.chart_math import ET
from app.models import FILL_LIGHT, Account, Fill, RobinhoodExecution, RobinhoodReconciliation

log = logging.getLogger(__name__)

MAX_CALLS = 40
MAX_PAGES = 5
LOOKBACK = timedelta(days=4)  # each read asks for orders created this far back; an execution is stored once, forever
REVIEW = timedelta(days=7)  # orders and fills this recent are paired again on every pass
EMAIL_GRACE = timedelta(minutes=30)  # how long an order waits for its email before it is listed as order-history only
WINDOW = timedelta(minutes=5)  # an email's minute must fall this close to the order's executions
SHARE_TOLERANCE = Decimal("0.006")  # emails show an average to the cent: half a cent a share, plus rounding
QTY_TOLERANCE = Decimal("0.000001")
FINAL_STATES = frozenset({"filled", "cancelled", "canceled", "rejected", "failed", "voided", "expired"})
WRITE_PREFIX = "robinhood:"
ADVISORY_LOCK = 61834207
DUPLICATE = "possible duplicate"
WRITTEN_NOTE = "recurring buy: Robinhood sends no email, so the journal took it from the order history"
TICKER = re.compile(r"[A-Z][A-Z0-9.]{0,9}")
OPTION_SIDES = {("buy", "open"): "buy_to_open", ("sell", "close"): "sell_to_close",
                ("sell", "open"): "sell_to_open", ("buy", "close"): "buy_to_close"}
ACCOUNT_TYPES = {"ira_roth": "roth_ira", "ira_traditional": "traditional_ira", "individual": "individual"}


def mode() -> str:
    """``off``, ``shadow`` or ``on``, from ``ROBINHOOD_FILLS_ENABLED`` alone; the poller also needs the read feed on."""
    value = (os.environ.get("ROBINHOOD_FILLS_ENABLED") or "").strip().lower()
    return {"true": "on", "shadow": "shadow"}.get(value, "off")


# --------------------------------------------------------------------------- parsing (defensive: odd = skipped)

def _dec(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _et(value) -> datetime | None:
    """A Robinhood UTC timestamp as the journal's New York wall clock (naive)."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw)  # nanoseconds: keep microseconds
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None  # a time with no zone is not trusted as UTC
    return moment.astimezone(ET).replace(tzinfo=None)


def _date(value) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Execution:
    execution_id: str
    order_id: str
    last4: str
    instrument_type: str
    ticker: str
    side: str
    option_type: str | None
    strike: Decimal | None
    expiration: date | None
    contracts: Decimal
    price: Decimal
    executed_at: datetime
    order_state: str
    placed_agent: str | None
    legs: int


def _common(order: dict) -> tuple[str, str, str | None] | None:
    order_id = order.get("id")
    state = order.get("state")
    if not isinstance(order_id, str) or not order_id or not isinstance(state, str):
        return None
    agent = order.get("placed_agent") if isinstance(order.get("placed_agent"), str) else None
    return order_id[:64], state[:24], (agent[:24] if agent else None)


def _executions(raw, make) -> list[Execution]:
    out = []
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict):
            continue
        exec_id, qty, price, at = e.get("id"), _dec(e.get("quantity")), _dec(e.get("price")), _et(e.get("timestamp"))
        if not isinstance(exec_id, str) or not exec_id or qty is None or qty <= 0 or price is None or price < 0 or at is None:
            continue  # without its id, quantity, price and time an execution cannot be recorded once and only once
        out.append(make(exec_id[:64], qty, price, at))
    return out


def option_executions(data: dict, last4: str) -> list[Execution]:
    out = []
    for order in rb._list(data, "orders", "results"):
        common = _common(order)
        ticker = order.get("chain_symbol").strip().upper() if isinstance(order.get("chain_symbol"), str) else ""
        multiplier = _dec(order.get("trade_value_multiplier"))
        legs = [leg for leg in order.get("legs") or [] if isinstance(leg, dict)] if isinstance(order.get("legs"), list) else []
        if common is None or not TICKER.fullmatch(ticker) or not multiplier or multiplier <= 0 or not legs:
            continue
        order_id, state, agent = common
        for leg in legs:
            side = OPTION_SIDES.get((leg.get("side"), leg.get("position_effect")))
            kind = leg.get("option_type") if leg.get("option_type") in ("call", "put") else None
            strike, expiry = _dec(leg.get("strike_price")), _date(leg.get("expiration_date"))
            if side is None or kind is None or strike is None or expiry is None:
                continue
            out += _executions(leg.get("executions"), lambda i, q, p, at, side=side, kind=kind, strike=strike, expiry=expiry: Execution(
                i, order_id, last4, "option", ticker, side, kind, strike, expiry, q, p * multiplier, at, state, agent, len(legs)))
    return out


def equity_executions(data: dict, last4: str) -> list[Execution]:
    out = []
    for order in rb._list(data, "orders", "results"):
        common = _common(order)
        ticker = order.get("symbol").strip().upper() if isinstance(order.get("symbol"), str) else ""
        side = order.get("side") if order.get("side") in ("buy", "sell") else None
        if common is None or not TICKER.fullmatch(ticker) or side is None:
            continue
        order_id, state, agent = common
        out += _executions(order.get("executions"), lambda i, q, p, at: Execution(
            i, order_id, last4, "stock", ticker, side, None, None, None, q, p, at, state, agent, 1))
    return out


# --------------------------------------------------------------------------- the read

@dataclass
class Read:
    since: datetime  # UTC, aware
    executions: list[Execution]
    complete: set[tuple[str, str]]  # (last4, instrument) whose whole window was read
    account_types: dict[str, str]  # last4 -> the journal's account type
    calls: int


def read_orders(reader: rh.Reader, now: float) -> Read:
    """Every account's orders created in the last ``LOOKBACK``, both kinds, newest first and at most ``MAX_PAGES``
    pages each. A kind whose read failed or ran out of pages is incomplete: no email fill there is judged email-only."""
    since = datetime.fromtimestamp(now, UTC) - LOOKBACK
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    accounts = rb._accounts(reader.get_accounts())
    executions, complete, types = [], set(), {}
    for account in accounts:
        last4 = account["last4"]
        types[last4] = ACCOUNT_TYPES.get(account["type"], account["type"] or "individual")
        for kind, call, parse in (("option", reader.get_option_orders, option_executions),
                                  ("stock", reader.get_equity_orders, equity_executions)):
            cursor, seen, whole = None, set(), False
            try:
                for _ in range(MAX_PAGES):
                    data = call(account["number"], stamp, cursor)
                    if not any(isinstance(data.get(k), list) for k in ("orders", "results")):
                        raise rh.ReadError("shape", "orders reply")
                    executions += parse(data, last4)
                    cursor = rb._next(data)
                    if not cursor or cursor in seen:
                        whole = True
                        break
                    seen.add(cursor)
            except rh.ReadError as exc:
                if exc.kind == "expired":
                    raise
                log.warning("Robinhood %s orders read failed for an account (%s)", kind, exc.kind)
            if whole:
                complete.add((last4, kind))
    return Read(since=since, executions=executions, complete=complete, account_types=types, calls=reader.calls)


# --------------------------------------------------------------------------- recording (idempotent by execution id)

def record(session: Session, executions: list[Execution]) -> int:
    """Insert each execution not seen before; refresh the order state of those seen. Returns how many were new."""
    if not executions:
        return 0
    ids = list({e.execution_id for e in executions})
    known = {r.execution_id: r for r in session.exec(select(RobinhoodExecution).where(col(RobinhoodExecution.execution_id).in_(ids))).all()}
    new = 0
    for e in executions:
        row = known.get(e.execution_id)
        if row is not None:
            if row.order_state != e.order_state:
                row.order_state = e.order_state
                session.add(row)
            continue
        row = RobinhoodExecution(execution_id=e.execution_id, order_id=e.order_id, account_last4=e.last4,
                                 instrument_type=e.instrument_type, ticker=e.ticker, side=e.side, option_type=e.option_type,
                                 strike=e.strike, expiration=e.expiration, contracts=e.contracts, price=e.price,
                                 executed_at=e.executed_at, order_state=e.order_state, placed_agent=e.placed_agent, legs=e.legs)
        session.add(row)
        known[e.execution_id] = row
        new += 1
    session.flush()
    return new


# --------------------------------------------------------------------------- pairing

def direction(side: str) -> str:
    return "buy" if side.startswith("buy") else "sell"


def _strike(value) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.001"))


def _q6(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


def source(raw_email_id: str) -> str:
    for prefix, name in (("manual:", "manual"), ("roll:", "roll"), (WRITE_PREFIX, "robinhood"), ("webull:", "webull")):
        if raw_email_id.startswith(prefix):
            return name
    return "email"


@dataclass
class Order:
    order_id: str
    last4: str
    instrument_type: str
    ticker: str
    side: str  # buy | sell
    option_type: str | None
    strike: Decimal | None
    expiration: date | None
    contracts: Decimal
    price: Decimal  # the executions' volume-weighted average, journal convention
    first_at: datetime
    last_at: datetime
    state: str
    placed_agent: str | None
    legs: int

    @property
    def key(self) -> tuple:
        return (self.last4, self.instrument_type, self.ticker, self.side, self.option_type, _strike(self.strike), self.expiration)

    @property
    def final(self) -> bool:
        return self.state in FINAL_STATES

    @property
    def no_email(self) -> bool:
        """Robinhood never emails a recurring buy: the order history is the only source, so it may be written."""
        return self.instrument_type == "stock" and self.side == "buy" and self.placed_agent == "recurring" and self.state == "filled"

    @property
    def tolerance(self) -> Decimal:
        return SHARE_TOLERANCE * (100 if self.instrument_type == "option" else 1)


def orders_from(rows: list[RobinhoodExecution]) -> list[Order]:
    by_order: dict[str, list[RobinhoodExecution]] = defaultdict(list)
    for r in rows:
        by_order[r.order_id].append(r)
    out = []
    for order_id, execs in by_order.items():
        first = execs[0]
        qty = sum((Decimal(str(e.contracts)) for e in execs), Decimal(0))
        if qty <= 0:
            continue
        price = _q6(sum((Decimal(str(e.price)) * Decimal(str(e.contracts)) for e in execs), Decimal(0)) / qty)
        legs_sides = {direction(e.side) for e in execs}
        out.append(Order(order_id, first.account_last4, first.instrument_type, first.ticker, direction(first.side),
                         first.option_type, Decimal(str(first.strike)) if first.strike is not None else None, first.expiration,
                         _q6(qty), price, min(e.executed_at for e in execs), max(e.executed_at for e in execs),
                         first.order_state, first.placed_agent, max(max(e.legs for e in execs), len(legs_sides))))
    out.sort(key=lambda o: (o.first_at, o.order_id))
    return out


@dataclass
class JournalFill:
    fill: Fill
    last4: str
    source: str

    @property
    def key(self) -> tuple:
        f = self.fill
        return (self.last4, f.instrument_type, f.ticker.upper(), direction(f.side), f.option_type, _strike(f.strike), f.expiration)

    @property
    def contracts(self) -> Decimal:
        return Decimal(str(self.fill.contracts))

    @property
    def price(self) -> Decimal:
        return Decimal(str(self.fill.price))


def _minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def in_window(order: Order, at: datetime, journal_source: str) -> bool:
    """An email shows its time to the minute: it must sit within ``WINDOW`` of the order's executions. A manual fill
    (a ``csvfix`` backfill, a hand entry) carries a rough time: the same New York day is enough."""
    if journal_source == "manual":
        return at.date() == order.last_at.date()
    return _minute(order.first_at) - WINDOW <= at <= order.last_at + WINDOW


def exact(order: Order, j: JournalFill) -> bool:
    return abs(j.contracts - order.contracts) <= QTY_TOLERANCE and abs(j.price - order.price) <= order.tolerance


def _closest(order: Order, pool: list[JournalFill]) -> JournalFill:
    return min(pool, key=lambda j: (abs((j.fill.executed_at - order.last_at).total_seconds()), j.fill.executed_at, j.fill.raw_email_id))


# --------------------------------------------------------------------------- the reconciliation pass

def _order_values(order: Order) -> dict:
    return {"order_id": order.order_id, "account_last4": order.last4, "instrument_type": order.instrument_type,
            "ticker": order.ticker, "side": order.side, "option_type": order.option_type, "strike": order.strike,
            "expiration": order.expiration, "placed_agent": order.placed_agent, "rh_contracts": order.contracts,
            "rh_price": order.price, "rh_first_at": order.first_at, "rh_last_at": order.last_at}


def _journal_values(j: JournalFill | None) -> dict:
    if j is None:
        return {"fill_id": None, "journal_source": None, "journal_contracts": None, "journal_price": None, "journal_at": None}
    return {"fill_id": j.fill.id, "journal_source": j.source, "journal_contracts": j.contracts, "journal_price": j.price,
            "journal_at": j.fill.executed_at}


def _same(a, b) -> bool:
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            return a is not None and b is not None and Decimal(str(a)) == Decimal(str(b))
        except InvalidOperation:
            return False
    return a == b


def _put(session: Session, rows: dict[str, RobinhoodReconciliation], key: str, values: dict) -> RobinhoodReconciliation:
    """Upsert one outcome row; ``updated_at`` moves only when something changed, so a quiet pass rewrites nothing."""
    row = rows.get(key)
    if row is None:
        row = RobinhoodReconciliation(key=key, **values)
        session.add(row)
        rows[key] = row
        return row
    changed = False
    for name, value in values.items():
        if not _same(getattr(row, name), value):
            setattr(row, name, value)
            changed = True
    if changed:
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(row)
    return row


def _write_fill(session: Session, order: Order, account_types: dict[str, str]) -> Fill:
    """The one fill written from the order history: a recurring buy. A fixed id and ``raw_email_id`` from the order id,
    so a second attempt finds it instead of adding another."""
    from app.routers.fills import _get_or_create_account
    raw = f"{WRITE_PREFIX}{order.order_id}"
    found = session.exec(select(Fill).options(*FILL_LIGHT).where(Fill.raw_email_id == raw)).first()
    if found is not None:
        return found
    account = session.exec(select(Account).where(Account.last4 == order.last4)).first() \
        or _get_or_create_account(session, order.last4, account_types.get(order.last4, "individual"))
    fill = Fill(id=uuid.uuid5(uuid.NAMESPACE_URL, f"robinhood-order:{order.order_id}"), account_id=account.id,
                ticker=order.ticker, instrument_type="stock", side="buy", contracts=order.contracts, price=order.price,
                executed_at=order.last_at, raw_email_id=raw)
    session.add(fill)
    session.flush()
    return fill


@dataclass
class PassResult:
    outcomes: dict[str, int]
    written: int


def reconcile(session: Session, *, now_et: datetime, current: str, read: Read | None = None) -> PassResult:
    """Pair every recent order with the journal's fills and record each outcome (see the module docstring). ``current``
    is ``shadow`` or ``on``; only ``on`` writes, and only an order no email will bring. Nothing here deletes or
    changes a fill. The caller commits once, so the executions, the outcomes, any fill written and the trades rebuilt
    from it land together."""
    horizon = now_et - REVIEW
    executions = session.exec(select(RobinhoodExecution).where(RobinhoodExecution.executed_at >= horizon)
                              .order_by(RobinhoodExecution.executed_at, RobinhoodExecution.execution_id)).all()
    orders = orders_from(list(executions))
    pool_rows = session.exec(select(Fill, Account.last4).options(*FILL_LIGHT).join(Account, Account.id == Fill.account_id)
                             .where(Fill.executed_at >= horizon - timedelta(days=1))).all()
    journal = [JournalFill(f, (last4 or "").strip(), source(f.raw_email_id)) for f, last4 in pool_rows]
    journal = [j for j in journal if j.source != "webull"]
    by_id = {j.fill.id: j for j in journal}
    order_keys = [f"order:{o.order_id}" for o in orders]
    fill_keys = [f"fill:{j.fill.id}" for j in journal]
    rows = {r.key: r for r in session.exec(select(RobinhoodReconciliation).where(
        col(RobinhoodReconciliation.key).in_(order_keys + fill_keys))).all()} if order_keys or fill_keys else {}
    # Fills an earlier pass already paired with an order outside this window stay paired.
    claimed: set[uuid.UUID] = {r.fill_id for r in session.exec(select(RobinhoodReconciliation).where(
        col(RobinhoodReconciliation.fill_id).in_(list(by_id)), col(RobinhoodReconciliation.key).startswith("order:"),
        col(RobinhoodReconciliation.order_id).not_in([o.order_id for o in orders]))).all()} if by_id else set()
    written = 0

    # A matched pair or a written fill is settled: a later order cannot take its fill. A mismatch is not: it is paired
    # again each pass, so an exact match that turns up later (a late email) replaces it.
    open_orders = []
    for o in orders:
        row = rows.get(f"order:{o.order_id}")
        if row is not None and row.fill_id is not None and (
                row.outcome == "matched" and row.fill_id in by_id
                or row.action == "wrote_fill" and (row.fill_id in by_id or _fill_exists(session, row.fill_id))):
            claimed.add(row.fill_id)
            continue
        key = f"order:{o.order_id}"
        base = {**_order_values(o), "mode": current}
        if o.legs > 1:
            _put(session, rows, key, {**base, **_journal_values(None), "outcome": "order_only", "action": "none",
                                      "note": "two-leg order (a roll): the journal takes it from its email; not paired here"})
        elif not o.final:
            _put(session, rows, key, {**base, **_journal_values(None), "outcome": "pending", "action": "none",
                                      "note": f"order still {o.state}: paired once it is done"})
        else:
            open_orders.append(o)

    def candidates(o: Order) -> list[JournalFill]:
        return [j for j in journal if j.fill.id not in claimed and j.source != "robinhood" and j.key == o.key
                and in_window(o, j.fill.executed_at, j.source)]

    # Every exact pair first, across all orders, so an order never takes as a near miss the fill another order matches.
    unmatched = []
    for o in open_orders:
        match = [j for j in candidates(o) if exact(o, j)]
        if not match:
            unmatched.append(o)
            continue
        j = _closest(o, match)
        claimed.add(j.fill.id)
        _put(session, rows, f"order:{o.order_id}", {**_order_values(o), "mode": current, **_journal_values(j),
                                                    "outcome": "matched", "action": "none", "note": f"paired with the {j.source} fill"})

    for o in unmatched:
        key = f"order:{o.order_id}"
        base = {**_order_values(o), "mode": current}
        near = candidates(o)
        if o.no_email:
            # Only the same quantity can be this recurring buy (at another price); another quantity is another trade.
            near = [j for j in near if abs(j.contracts - o.contracts) <= QTY_TOLERANCE]
        elif now_et - o.last_at < EMAIL_GRACE:
            _put(session, rows, key, {**base, **_journal_values(None), "outcome": "pending", "action": "none",
                                      "note": "seen on Robinhood; its email is not in yet"})
            continue
        if near:
            j = _closest(o, near)
            claimed.add(j.fill.id)
            _put(session, rows, key, {**base, **_journal_values(j), "outcome": "mismatch", "action": "none",
                                      "note": f"the {j.source} fill differs in quantity or price; the journal keeps it as it is"})
            continue
        if o.no_email:
            if current == "on":
                fill = _write_fill(session, o, read.account_types if read else {})
                claimed.add(fill.id)
                written += 1
                _put(session, rows, key, {**base, "fill_id": fill.id, "journal_source": "robinhood",
                                          "journal_contracts": o.contracts, "journal_price": o.price, "journal_at": o.last_at,
                                          "outcome": "order_only", "action": "wrote_fill",
                                          "note": WRITTEN_NOTE})
            else:
                _put(session, rows, key, {**base, **_journal_values(None), "outcome": "order_only", "action": "would_write_fill",
                                          "note": "recurring buy: Robinhood sends no email; switched on, this fill would be written"})
            continue
        _put(session, rows, key, {**base, **_journal_values(None), "outcome": "order_only", "action": "none",
                                  "note": "no email arrived for this order; the journal does not have it"})

    _check_duplicates(session, rows, claimed, current)

    if read is not None:
        _email_only(session, rows, journal, claimed, read, now_et, current)
    else:
        for j in journal:  # an email-only row whose fill an order has since taken is matched now
            row = rows.get(f"fill:{j.fill.id}")
            if row is not None and row.outcome == "email_only" and j.fill.id in claimed:
                _put(session, rows, row.key, {"outcome": "matched", "note": "an order now explains this fill", "mode": current})
    session.flush()
    counts: dict[str, int] = defaultdict(int)
    for row in rows.values():
        counts[row.outcome] += 1
    return PassResult(outcomes=dict(counts), written=written)


def _fill_exists(session: Session, fill_id: uuid.UUID) -> bool:
    return session.exec(select(Fill.id).where(Fill.id == fill_id)).first() is not None


def _check_duplicates(session: Session, rows: dict, claimed: set, current: str) -> None:
    """Every fill written from the order history, whatever its age, that the journal also has from another source (an
    email that slipped past the guard, a manual entry or a CSV backfill made later) is listed as a mismatch with both
    versions: same account, stock, New York day and quantity, a fill no order has taken. A flag whose other fill an
    order has since matched (another trade of the same quantity) is cleared. Nothing is removed."""
    written = [r for r in session.exec(select(RobinhoodReconciliation).where(RobinhoodReconciliation.action == "wrote_fill")).all()
               if r.outcome != "mismatch" or (r.note or "").startswith(DUPLICATE)]
    if not written:
        return
    taken = claimed | {r for r in session.exec(select(RobinhoodReconciliation.fill_id).where(
        col(RobinhoodReconciliation.key).startswith("order:"), col(RobinhoodReconciliation.fill_id).is_not(None),
        col(RobinhoodReconciliation.outcome).in_(["matched", "mismatch"]))).all()}
    for row in written:
        rows.setdefault(row.key, row)
        day = row.rh_last_at.replace(hour=0, minute=0, second=0, microsecond=0)
        found = session.exec(select(Fill, Account.last4).options(*FILL_LIGHT).join(Account, Account.id == Fill.account_id).where(
            Account.last4 == row.account_last4, Fill.ticker == row.ticker, Fill.instrument_type == row.instrument_type,
            Fill.executed_at >= day, Fill.executed_at < day + timedelta(days=1))).all()
        other = [JournalFill(f, last4, source(f.raw_email_id)) for f, last4 in found]
        other = [j for j in other if j.source not in ("robinhood", "webull") and j.fill.id not in taken
                 and direction(j.fill.side) == row.side and abs(j.contracts - Decimal(str(row.rh_contracts))) <= QTY_TOLERANCE]
        if not other:
            if row.outcome == "mismatch":  # the flagged fill turned out to be another order's
                _put(session, rows, row.key, {"outcome": "order_only", "mode": current, "journal_source": "robinhood",
                                              "journal_contracts": row.rh_contracts, "journal_price": row.rh_price,
                                              "journal_at": row.rh_last_at, "note": WRITTEN_NOTE})
            continue
        j = min(other, key=lambda j: (abs((j.fill.executed_at - row.rh_last_at).total_seconds()), j.fill.raw_email_id))
        taken.add(j.fill.id)
        claimed.add(j.fill.id)
        _put(session, rows, row.key, {"outcome": "mismatch", "mode": current, "journal_source": j.source,
                                      "journal_contracts": j.contracts, "journal_price": j.price, "journal_at": j.fill.executed_at,
                                      "note": f"{DUPLICATE}: written from Robinhood, and the journal also has a {j.source} "
                                              f"fill for it (fill {j.fill.id}); check and remove one by hand"})


def _email_only(session, rows, journal: list[JournalFill], claimed: set, read: Read, now_et: datetime, current: str) -> None:
    """An email fill no order explains, judged only where this pass read the whole window: from a day after the read's
    start (so an order created before the window is rare) until ``EMAIL_GRACE`` ago."""
    start = read.since.astimezone(ET).replace(tzinfo=None) + timedelta(days=1)
    for j in journal:
        key = f"fill:{j.fill.id}"
        row = rows.get(key)
        if j.fill.id in claimed:
            if row is not None and row.outcome == "email_only":
                _put(session, rows, key, {"outcome": "matched", "mode": current, "note": "an order now explains this fill"})
            continue
        if j.source != "email" or (j.last4, j.fill.instrument_type) not in read.complete:
            continue
        if not start <= j.fill.executed_at <= now_et - EMAIL_GRACE:
            continue
        f = j.fill
        _put(session, rows, key, {"order_id": None, "fill_id": f.id, "outcome": "email_only", "action": "none", "mode": current,
                                  "account_last4": j.last4, "instrument_type": f.instrument_type, "ticker": f.ticker,
                                  "side": direction(f.side), "option_type": f.option_type, "strike": f.strike,
                                  "expiration": f.expiration, "placed_agent": None, "rh_contracts": None, "rh_price": None,
                                  "rh_first_at": None, "rh_last_at": None, "journal_source": "email",
                                  "journal_contracts": j.contracts, "journal_price": j.price, "journal_at": f.executed_at,
                                  "note": "no Robinhood order explains this email fill (an order placed before the read "
                                          "window, such as a good-till-cancelled one, also shows here)"})


# --------------------------------------------------------------------------- the email side

def written_email_ids(session: Session) -> set[str]:
    """Emails already accounted for by a fill written from the order history: the import treats them as known."""
    return {r for r in session.exec(select(RobinhoodReconciliation.journal_email_id)
                                    .where(col(RobinhoodReconciliation.journal_email_id).is_not(None))).all() if r}


def email_already_written(session: Session, parsed, last4: str) -> bool:
    """True when ``parsed`` (an email ``ParsedFill``) is for an order already written from the order history: the
    import then adds no second fill. Only an email with the order's exact quantity counts as that order's; it is
    recorded on the order's row (price within rounding: confirmed; otherwise a mismatch with both versions, for the
    owner). An email of another quantity is another trade and is imported as usual (False, nothing recorded)."""
    candidates = session.exec(select(RobinhoodReconciliation).where(
        RobinhoodReconciliation.action == "wrote_fill", col(RobinhoodReconciliation.journal_email_id).is_(None),
        RobinhoodReconciliation.account_last4 == last4, RobinhoodReconciliation.ticker == parsed.ticker.upper(),
        RobinhoodReconciliation.instrument_type == parsed.instrument_type)).all()
    if not candidates:
        return False
    executed_at = parsed.executed_at.astimezone(ET).replace(tzinfo=None) if parsed.executed_at.tzinfo else parsed.executed_at
    for row in sorted(candidates, key=lambda r: abs((r.rh_last_at - executed_at).total_seconds())):
        if row.fill_id is None or not _fill_exists(session, row.fill_id):
            continue
        order = Order(row.order_id or "", row.account_last4, row.instrument_type, row.ticker, row.side, row.option_type,
                      row.strike, row.expiration, Decimal(str(row.rh_contracts)), Decimal(str(row.rh_price)),
                      row.rh_first_at, row.rh_last_at, "filled", row.placed_agent, 1)
        if (direction(parsed.side), parsed.option_type, _strike(parsed.strike), parsed.expiration) != \
                (order.side, order.option_type, _strike(order.strike), order.expiration):
            continue
        if not in_window(order, executed_at, "email"):
            continue
        qty, price = Decimal(str(parsed.contracts)), Decimal(str(parsed.price))
        if abs(qty - order.contracts) > QTY_TOLERANCE:
            continue  # a different quantity is a different trade: the email is the record for it
        agrees = abs(price - order.price) <= order.tolerance
        row.journal_email_id = parsed.raw_email_id
        row.journal_contracts, row.journal_price, row.journal_at = qty, price, executed_at
        if agrees:
            row.journal_source = "email"
            row.note = "written from the order history; its email arrived later and agrees (no second fill)"
        else:
            row.outcome = "mismatch"
            row.journal_source = "email"
            row.note = ("written from the order history; its email arrived later with the same quantity at another "
                        "price. The journal keeps the written fill and adds no second one: check both versions and "
                        "correct it by hand")
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(row)
        log.info("An email arrived for an order already written from Robinhood's order history (%s)",
                 "agrees" if agrees else "differs")
        return True
    return False


# --------------------------------------------------------------------------- the desk and the owner's read

def provisional(session: Session, now_et: datetime) -> set[tuple]:
    """(last4, contract key) of orders seen on Robinhood today whose fill is not in the journal yet (pending, or no
    email arrived): the desk says "fill seen on Robinhood" instead of "not in the journal yet"."""
    rows = session.exec(select(RobinhoodReconciliation).where(
        col(RobinhoodReconciliation.outcome).in_(["pending", "order_only"]), RobinhoodReconciliation.action != "wrote_fill",
        col(RobinhoodReconciliation.key).startswith("order:"),
        RobinhoodReconciliation.rh_last_at >= now_et - timedelta(days=1))).all()
    out = set()
    for r in rows:
        if r.side != "buy":
            continue
        key = rb.contract_key(r.ticker, r.instrument_type, r.option_type, r.strike, r.expiration.isoformat() if r.expiration else None)
        if key is not None:
            out.add((r.account_last4, key))
    return out


def _f(value) -> float | None:
    return None if value is None else float(value)


def _at(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def view(session: Session, days: int = 7) -> dict:
    """The owner's read of the reconciliation: the mode, the last pass, counts by outcome and the rows, problems first.
    A row belongs to the window by its trade's time (Robinhood's, else the journal's), New York; a mismatch stays
    listed whatever its age until someone corrects it. Accounts appear as the journal's label and ``••last4``;
    Robinhood's ids appear only as their last six characters."""
    days = max(1, min(int(days), 30))
    since = datetime.now(ET).replace(tzinfo=None) - timedelta(days=days)
    rows = [r for r in session.exec(select(RobinhoodReconciliation)).all()
            if r.outcome == "mismatch" or (r.rh_last_at or r.journal_at or r.updated_at) >= since]
    names = {a.last4: a.name for a in session.exec(select(Account)).all()}
    rank = {"mismatch": 0, "order_only": 1, "email_only": 2, "pending": 3, "matched": 4}
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r.outcome] += 1
    items = []
    def order(r: RobinhoodReconciliation) -> tuple:
        moment = r.rh_last_at or r.journal_at
        return (rank.get(r.outcome, 9), -(moment.replace(tzinfo=UTC).timestamp() if moment else 0), r.key)

    for r in sorted(rows, key=order):
        items.append({
            "outcome": r.outcome, "action": r.action, "mode": r.mode, "note": r.note,
            "account": {"label": names.get(r.account_last4) or "Robinhood account", "masked": rb.mask(r.account_last4)},
            "ticker": r.ticker, "instrument": r.instrument_type, "side": r.side, "option_type": r.option_type,
            "strike": _f(r.strike), "expiration": r.expiration.isoformat() if r.expiration else None,
            "recurring": r.placed_agent == "recurring",
            "order": None if r.order_id is None else {"ref": r.order_id[-6:], "contracts": _f(r.rh_contracts), "price": _f(r.rh_price),
                                                      "first_at": _at(r.rh_first_at), "last_at": _at(r.rh_last_at)},
            "journal": None if r.journal_source is None else {"source": r.journal_source, "contracts": _f(r.journal_contracts),
                                                              "price": _f(r.journal_price), "at": _at(r.journal_at),
                                                              "fill_id": str(r.fill_id) if r.fill_id else None},
            "updated_at": _at(r.updated_at),
        })
    return {"mode": mode(), "feed": "on" if rb.settings().enabled else "off", "last_pass": poller.status(),
            "days": days, "counts": dict(counts), "rows": items}


# --------------------------------------------------------------------------- the poller

class Poller:
    """Reads the order history on the feed's schedule (a minute in market hours, fifteen otherwise), one pass at a
    time, at most ``MAX_CALLS`` calls each, and commits each pass in one transaction."""

    def __init__(self, engine=None, feed: rb.Feed | None = None, now=time.time, mode_fn=mode):
        self._engine = engine
        self._feed = feed
        self._now = now
        self._mode = mode_fn
        self._lock = threading.Lock()
        self._status: dict = {"at": None, "state": "not run", "new_executions": 0, "written": 0, "calls": 0}

    def status(self) -> dict:
        return dict(self._status)

    def _engine_(self):
        if self._engine is None:
            from app.database import engine
            self._engine = engine
        return self._engine

    def run_once(self) -> dict:
        current = self._mode()
        feed = self._feed or rb.feed
        if current == "off":
            self._status |= {"state": "off"}
            return self.status()
        sign = feed.signer()
        if sign is None:
            self._status |= {"state": "feed off or signed out", "at": int(self._now())}
            return self.status()
        if not self._lock.acquire(blocking=False):
            return self.status()
        try:
            now = self._now()
            try:
                got = read_orders(rh.Reader(sign, max_calls=MAX_CALLS), now)
            except rh.ReadError as exc:
                self._status |= {"state": f"read failed ({exc.kind})", "at": int(now)}
                log.warning("Robinhood order history read failed (%s)", exc.kind)
                return self.status()
            now_et = datetime.fromtimestamp(now, ET).replace(tzinfo=None)
            with Session(self._engine_()) as session:
                try:
                    result, new = self.apply(session, got, now_et, current)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            self._status = {"at": int(now), "state": "ok", "mode": current, "new_executions": new, "written": result.written,
                            "calls": got.calls, "outcomes": result.outcomes,
                            "complete": len(got.complete) == 2 * len(got.account_types)}
            if new or result.written:
                log.info("Robinhood order history: %d new execution(s), %d fill(s) written (%s)", new, result.written, current)
            return self.status()
        finally:
            self._lock.release()

    @staticmethod
    def apply(session: Session, got: Read, now_et: datetime, current: str) -> tuple[PassResult, int]:
        """Record, pair and (on) write, then rebuild the trades when a fill was written, all in the caller's one
        transaction: the journal is never seen half-applied."""
        if session.get_bind().dialect.name == "postgresql":
            session.exec(text(f"SELECT pg_advisory_xact_lock({ADVISORY_LOCK})"))
        new = record(session, got.executions)
        result = reconcile(session, now_et=now_et, current=current, read=got)
        if result.written:
            from app.routers.fills import _rebuild_trades
            _rebuild_trades(session, anomalies_label="robinhood order fills")
        return result, new

    async def loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except Exception as error:  # the type only: a message could carry a row's values
                log.warning("Robinhood order history pass failed (%s)", type(error).__name__)
            await asyncio.sleep(rb.ttl(self._now()))


poller = Poller()
