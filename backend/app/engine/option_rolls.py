"""Turn a Robinhood two-leg order into the two fills the journal needs.

The email gives the quantity and the net debit, never the contracts or a price for
each leg. The contracts come from the book: the open contract rolled out of, and a
later sale of a contract that was never opened. The split between legs cannot be
known and does not change the total, so the old leg closes at its FIFO cost ($0)
and the new leg opens at that cost plus the debit. ``roll:`` fills are therefore
derived, not broker prices. Anything short of exactly one match stays unresolved.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlmodel import Session, select

from app.models import FILL_LIGHT, Fill, OptionRollOrder

_OPENS = {"buy_to_open", "sell_to_open"}
_PRICE = Decimal("0.000001")


def _derived_id(roll: OptionRollOrder, leg: str) -> str:
    return f"roll:{roll.raw_email_id}:{leg}"


@dataclass(frozen=True)
class _Match:
    account_id: object
    option_type: str
    old: tuple
    new: tuple
    cost: Decimal


def _key(fill: Fill) -> tuple:
    return fill.account_id, fill.option_type, Decimal(str(fill.strike)), fill.expiration


def _order(fill: Fill) -> tuple:
    return fill.executed_at, 0 if fill.side in _OPENS else 1, str(fill.id)


def _open_lots(fills: list[Fill]) -> dict[tuple, deque]:
    """Long lots still open after ``fills``, oldest first: [contracts, price]."""
    lots: dict[tuple, deque] = defaultdict(deque)
    for fill in fills:
        key, remaining = _key(fill), Decimal(str(fill.contracts))
        if fill.side == "buy_to_open":
            lots[key].append([remaining, Decimal(str(fill.price))])
        elif fill.side == "sell_to_close":
            while remaining > 0 and lots[key]:
                used = min(lots[key][0][0], remaining)
                lots[key][0][0] -= used
                remaining -= used
                if not lots[key][0][0]:
                    lots[key].popleft()
    return lots


def _match(roll: OptionRollOrder, fills: list[Fill]) -> _Match | None:
    quantity = Decimal(str(roll.contracts))
    before = [f for f in fills if f.executed_at <= roll.executed_at]
    lots = _open_lots(before)
    shorted = {_key(f) for f in fills if f.side == "sell_to_open"}
    old = [k for k, rows in lots.items() if sum(r[0] for r in rows) >= quantity
           and k not in shorted and k[3] >= roll.executed_at.date()]
    first_after: dict[tuple, Fill] = {}
    for fill in fills:
        if fill.executed_at >= roll.executed_at:
            first_after.setdefault(_key(fill), fill)
    new = [k for k, fill in first_after.items() if fill.side == "sell_to_close" and not lots.get(k)
           and Decimal(str(fill.contracts)) <= quantity]
    pairs = [(o, n) for o in old for n in new if o != n and o[:2] == n[:2]]
    if len(pairs) != 1:
        return None
    from_key, to_key = pairs[0]
    remaining, cost = quantity, Decimal(0)
    for contracts, price in lots[from_key]:
        used = min(contracts, remaining)
        cost += used * price
        remaining -= used
        if not remaining:
            break
    return _Match(from_key[0], from_key[1], from_key, to_key, cost / quantity)


def _is_resolved(roll: OptionRollOrder, known: set[str]) -> bool:
    return _derived_id(roll, "open") in known


def resolve_rolls(session: Session) -> int:
    """Add the derived fills for each roll that now has exactly one match, oldest first. Never edits a fill."""
    rolls = session.exec(select(OptionRollOrder).order_by(OptionRollOrder.executed_at)).all()
    known = set(session.exec(select(Fill.raw_email_id).where(Fill.raw_email_id.like("roll:%"))).all())
    added = 0
    for roll in rolls:
        if roll.credit_mentioned or _is_resolved(roll, known):
            continue
        fills = sorted(session.exec(select(Fill).options(*FILL_LIGHT).where(
            Fill.ticker == roll.ticker, Fill.instrument_type == "option", Fill.option_type.is_not(None),
            Fill.strike.is_not(None), Fill.expiration.is_not(None))).all(), key=_order)
        found = _match(roll, fills)
        if found is None:
            continue
        net = Decimal(str(roll.net_per_contract))
        legs = (("close", "sell_to_close", found.old, found.cost),
                ("open", "buy_to_open", found.new, found.cost + net))
        for leg, side, key, price in legs:
            session.add(Fill(account_id=found.account_id, ticker=roll.ticker, instrument_type="option", side=side,
                             contracts=roll.contracts, price=price.quantize(_PRICE, rounding=ROUND_HALF_UP),
                             executed_at=roll.executed_at, raw_email_id=_derived_id(roll, leg),
                             option_type=found.option_type, strike=key[2], expiration=key[3],
                             email_subject="Derived from a two-leg roll email"))
        session.flush()
        known.add(_derived_id(roll, "open"))
        added += 1
    return added


def unresolved_rolls(session: Session) -> list[OptionRollOrder]:
    known = set(session.exec(select(Fill.raw_email_id).where(Fill.raw_email_id.like("roll:%"))).all())
    return [r for r in session.exec(select(OptionRollOrder).order_by(OptionRollOrder.executed_at)).all()
            if not _is_resolved(r, known)]
