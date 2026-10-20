"""What the journal recorded after a saved Jo check (Dots step 5).

The check lives in the Check service's ledger; this module never reads or
copies it. The owner's page passes the facts it shows (ID, ticker, receipt
time and any contract the check named) and gets back two lists:

- **Linked**: activity the owner linked by hand, in the CaptureLink style:
  anchored in a fill's source identity and resolved to its current trade on
  every read, so rebuilds never move a link. Unlinking stamps the row.
- **Later activity — review needed**: trades in the approved account scope
  (Webull excluded, as for Jo's history), on the same underlying, entered after
  the check within ``WINDOW``, matching every contract field the check named.
  This is a possible match only. Nothing here says the advice was followed or
  overridden, marks it outdated, or links anything by itself.

P&L is the engine's ``trade.realized_pnl``; nothing is recomputed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine.capture_links import reliable, timing
from app.engine.captures import epoch
from app.engine.chart_journal import contract_label, number, stamp
from app.engine.pretrade_check import EXCLUDED_BROKERS
from app.models import Account, CheckLink, Fill, Trade, TradeFill

NY = ZoneInfo("America/New_York")
# Possible matches are entries within five calendar days after the check.
WINDOW = timedelta(days=5)
CHECK_ID = re.compile(r"^chk_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TICKER = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


class LinkError(ValueError):
    """A refusal the owner can act on."""


@dataclass(frozen=True)
class CheckFacts:
    check_id: str
    ticker: str
    received_at: datetime  # aware
    instrument: str | None = None  # option | stock
    option_type: str | None = None  # call | put
    strike: float | None = None
    expiration: date | None = None

    @classmethod
    def build(cls, check_id: str, ticker: str | None, received_at: datetime | None, instrument: str | None = None,
              option_type: str | None = None, strike: float | None = None, expiration: date | None = None) -> CheckFacts:
        if not CHECK_ID.fullmatch(check_id or ""):
            raise LinkError("Unknown check.")
        ticker = (ticker or "").strip().upper()
        if not TICKER.fullmatch(ticker) or received_at is None or received_at.tzinfo is None:
            # A redacted or incomplete check: nothing to match on, so nothing is suggested.
            raise LinkError("This saved check has no ticker or time to match on, so no later activity is shown.")
        if instrument not in (None, "option", "stock") or option_type not in (None, "call", "put"):
            raise LinkError("Unknown instrument or option type.")
        return cls(check_id, ticker, received_at, instrument, option_type, strike, expiration)

    @property
    def received_utc(self) -> datetime:
        """Naive UTC, comparable with ``capture_links.timing``."""
        return self.received_at.astimezone(UTC).replace(tzinfo=None)

    @property
    def received_ny(self) -> datetime:
        """Naive New York wall clock, comparable with journal times."""
        return self.received_at.astimezone(NY).replace(tzinfo=None)


def _scope(db: Session) -> dict[uuid.UUID, Account]:
    return {a.id: a for a in db.exec(select(Account)).all() if (a.broker or "").lower() not in EXCLUDED_BROKERS}


def _contract_matches(facts: CheckFacts, trade: Trade) -> bool:
    """Every contract field the check named must agree; a field it left out is not a guess."""
    if facts.instrument is not None and trade.instrument_type != facts.instrument:
        return False
    if facts.option_type is not None and trade.option_type != facts.option_type:
        return False
    if facts.strike is not None and (trade.strike is None or abs(float(trade.strike) - facts.strike) > 1e-6):
        return False
    return facts.expiration is None or trade.expiration == facts.expiration


def _after(facts: CheckFacts, trade: Trade) -> str | None:
    """after | same_minute | same_day when the entry follows the check inside the window, else None."""
    wall = trade.opened_at
    if wall is None or wall > facts.received_ny + WINDOW:
        return None
    if not reliable(wall):
        # A date without a time: a later day is after the check; the check's own day leaves the order unclear.
        day = facts.received_ny.date()
        return "after" if wall.date() > day else "same_day" if wall.date() == day else None
    when = timing(facts.received_utc, wall)
    return {"pre_entry": "after", "unverified": "same_minute"}.get(when)


def _fills(db: Session, trade_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    if not trade_ids:
        return {}
    rows = db.exec(select(TradeFill.trade_id, TradeFill.role, Fill).join(Fill, Fill.id == TradeFill.fill_id)
                   .where(TradeFill.trade_id.in_(trade_ids)).order_by(Fill.executed_at, Fill.raw_email_id)).all()
    out: dict[uuid.UUID, list[dict]] = {trade_id: [] for trade_id in trade_ids}
    for trade_id, role, fill in rows:
        out[trade_id].append({"fill_id": str(fill.id), "role": role, "side": fill.side, "contracts": number(fill.contracts),
                              "price": number(fill.price), "executed_at": stamp(fill.executed_at),
                              "source_key": fill.raw_email_id, "account_id": fill.account_id})
    return out


def _trade_row(trade: Trade, account: Account | None, fills: list[dict], after: str | None) -> dict:
    return {
        "trade_id": str(trade.id), "account": account.name if account else None, "account_type": account.type if account else None,
        "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
        "status": trade.status, "contracts": number(trade.contracts), "opened_at": stamp(trade.opened_at),
        "closed_at": stamp(trade.closed_at), "realized_pnl": None if trade.realized_pnl is None else number(trade.realized_pnl),
        "timing": after,
        "fills": [{k: v for k, v in f.items() if k not in ("source_key", "account_id")} for f in fills],
    }


def _resolve(db: Session, links: list[CheckLink]) -> dict[uuid.UUID, tuple[uuid.UUID, str] | None]:
    """Each link's (current trade, anchor fill ID), or None when its fill is gone or in no trade."""
    keys = {link.source_key for link in links}
    if not keys:
        return {}
    found = db.exec(select(Fill.raw_email_id, Fill.account_id, Fill.id, TradeFill.trade_id)
                    .join(TradeFill, TradeFill.fill_id == Fill.id).where(Fill.raw_email_id.in_(keys))).all()
    where = {(row.raw_email_id, row.account_id): (row.trade_id, str(row.id)) for row in found}
    return {link.id: where.get((link.source_key, link.account_id)) for link in links}


def possible(db: Session, facts: CheckFacts, exclude: set[uuid.UUID] = frozenset()) -> list[tuple[Trade, str]]:
    """Trades that may be later activity for this check, oldest entry first. Never linked here."""
    scope = _scope(db)
    if not scope:
        return []
    start = facts.received_ny - timedelta(days=1)  # Date-only entries sit at midnight; each is checked exactly below.
    pool = db.exec(select(Trade).where(Trade.account_id.in_(list(scope)), Trade.ticker == facts.ticker,
                                       Trade.opened_at >= start, Trade.opened_at <= facts.received_ny + WINDOW)
                   .order_by(Trade.opened_at, Trade.id)).all()
    return [(trade, after) for trade in pool if trade.id not in exclude and _contract_matches(facts, trade)
            and (after := _after(facts, trade)) is not None]


def activity(db: Session, facts: CheckFacts) -> dict:
    links = list(db.exec(select(CheckLink).where(CheckLink.check_id == facts.check_id).order_by(CheckLink.linked_at)).all())
    active = [link for link in links if link.unlinked_at is None]
    resolved = _resolve(db, active)
    linked_trades = {value[0] for value in resolved.values() if value}
    candidates = possible(db, facts, exclude=linked_trades)
    trade_ids = list(linked_trades | {trade.id for trade, _ in candidates})
    trades = {t.id: t for t in db.exec(select(Trade).where(Trade.id.in_(trade_ids))).all()} if trade_ids else {}
    fills = _fills(db, trade_ids)
    accounts = {a.id: a for a in db.exec(select(Account)).all()}

    linked = []
    for link in active:
        entry = {"link_id": str(link.id), "target": link.target, "method": link.method, "linked_at": epoch(link.linked_at)}
        where = resolved.get(link.id)
        trade = trades.get(where[0]) if where else None
        if trade is None:
            entry.update(trade=None, fill_id=None, note="The fill this was linked to is no longer in a trade. Rebuild trades, or link again.")
        else:
            entry.update(trade=_trade_row(trade, accounts.get(trade.account_id), fills[trade.id], _after(facts, trade)),
                         fill_id=where[1] if link.target == "fill" else None)
        linked.append(entry)
    return {
        "check_id": facts.check_id,
        "window": {"from": int(facts.received_at.timestamp()), "to": int((facts.received_ny + WINDOW).replace(tzinfo=NY).timestamp()),
                   "days": WINDOW.days},
        "linked": linked,
        "possible": [_trade_row(trade, accounts.get(trade.account_id), fills[trade.id], after) for trade, after in candidates],
        "history": [{"link_id": str(link.id), "target": link.target, "linked_at": epoch(link.linked_at),
                     "unlinked_at": epoch(link.unlinked_at)} for link in links],
    }


def link(db: Session, facts: CheckFacts, trade_id: uuid.UUID | None = None, fill_id: uuid.UUID | None = None) -> CheckLink:
    """The owner links this check to a trade (anchored on its first entry) or to one fill. The check never changes."""
    if (trade_id is None) == (fill_id is None):
        raise LinkError("Choose one trade or one fill.")
    if fill_id is not None:
        fill = db.get(Fill, fill_id)
        trade_row = db.exec(select(TradeFill.trade_id).where(TradeFill.fill_id == fill_id)).first() if fill else None
        trade = db.get(Trade, trade_row) if trade_row else None
    else:
        trade = db.get(Trade, trade_id)
        # A trade's ID is its first entry fill's ID.
        fill = db.get(Fill, trade_id) if trade else None
    if trade is None or fill is None:
        raise LinkError("That activity is no longer in the journal. Refresh and choose again.")
    if trade.account_id not in _scope(db):
        raise LinkError("That account is outside the approved scope for saved advice.")
    if trade.ticker != facts.ticker:
        raise LinkError("That trade is on a different symbol from this check.")
    row = CheckLink(check_id=facts.check_id, account_id=fill.account_id, source_key=fill.raw_email_id,
                    target="fill" if fill_id is not None else "trade",
                    method="possible_match" if trade.id in {t.id for t, _ in possible(db, facts)} else "manual")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise LinkError("This check is already linked to that activity.") from None
    db.refresh(row)
    return row


def unlink(db: Session, check_id: str, link_id: uuid.UUID) -> None:
    row = db.get(CheckLink, link_id)
    if row is None or row.check_id != check_id:
        raise LinkError("Unknown link.")
    if row.unlinked_at is None:
        row.unlinked_at = datetime.utcnow()
        db.add(row)
        db.commit()


def for_trade(db: Session, trade_id: uuid.UUID) -> list[dict]:
    """Checks the owner linked to this trade or one of its fills, oldest link first."""
    fills = _fills(db, [trade_id])[trade_id]
    keys = {(f["source_key"], f["account_id"]): f["fill_id"] for f in fills}
    if not keys:
        return []
    rows = db.exec(select(CheckLink).where(CheckLink.unlinked_at.is_(None), CheckLink.source_key.in_({k for k, _ in keys}))
                   .order_by(CheckLink.linked_at)).all()
    return [{"link_id": str(row.id), "check_id": row.check_id, "target": row.target, "method": row.method,
             "linked_at": epoch(row.linked_at), "fill_id": keys[(row.source_key, row.account_id)] if row.target == "fill" else None}
            for row in rows if (row.source_key, row.account_id) in keys]
