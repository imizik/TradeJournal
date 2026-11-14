"""One-line notes on a trade from the desk ("why I'm in", "why I left"): ``TradeCaptureNote`` rows of kind ``note``.

A note is anchored as a capture link is (``capture_links``): in the source identity of the trade's first entry fill
(account plus ``raw_email_id``), resolved to the trade through its fills on every read, so a rebuild keeps it with its
trade. When the trade has a plan linked (the oldest, as ``plan_positions`` reads it) the note is that plan's too, so
the plan sheets, the day journal and the plan's thesis show it as they show any later note. A trade with no plan gets
no capture: a note is not a plan, never counts as one and never stands in the way of linking one.

A note never changes a fill, a trade or its P&L. A ticker set to Not following keeps its notes; nothing here reaches
the Feed. Database reads and one insert only: no broker, no provider.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlmodel import Session, select

from app.engine import capture_links
from app.engine.captures import CaptureError, epoch
from app.engine.chart_journal import contract_label
from app.models import CaptureLink, Fill, Trade, TradeCaptureNote, TradeFill

MAX = 300  # one line
RECENT_TRADES = 50  # a fill's contract is looked for among the ticker's newest trades


def clean(text: str) -> str:
    """The note as one line: whitespace and line breaks folded to single spaces. Raises CaptureError."""
    words = " ".join(str(text or "").split())
    if not words or len(words) > MAX:
        raise CaptureError(f"Write a note of 1 to {MAX} characters.")
    return words


def _row(note: TradeCaptureNote) -> dict:
    return {"id": str(note.id), "text": note.text, "at": epoch(note.created_at)}


def add(db: Session, trade_id: uuid.UUID, text: str) -> dict:
    """Save one note on a trade, anchored in its first entry fill, and on its linked plan when it has one."""
    words = clean(text)
    rows = capture_links._trades(db, Trade.id == trade_id)
    if not rows or rows[0]["raw_email_id"] is None:
        raise CaptureError("That trade is no longer in the journal. Refresh and try again.")
    trade = rows[0]
    linked = capture_links.for_trade(db, trade_id)
    plan = min(linked, key=lambda c: c.received_at) if linked else None
    note = TradeCaptureNote(capture_id=plan.id if plan else None, account_id=trade["account_id"],
                            source_key=trade["raw_email_id"], kind="note", text=words)
    db.add(note)
    db.commit()
    db.refresh(note)
    return _row(note)


def for_trades(db: Session, trade_ids: list[uuid.UUID], *, with_ids: bool = False) -> dict[str, list[dict]]:
    """Each trade's notes, oldest first: those anchored in any of its fills, and the ``note`` kind written on its linked
    plans (in the Journal or on the Charts plan sheet). Four queries for any number of trades."""
    if not trade_ids:
        return {}
    keys = db.exec(select(TradeFill.trade_id, Fill.raw_email_id, Fill.account_id)
                   .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(trade_ids))).all()
    trade_of = {(raw, account): trade_id for trade_id, raw, account in keys if raw}
    raws = {raw for raw, _ in trade_of}
    if not raws:
        return {}
    found: dict[uuid.UUID, tuple[uuid.UUID, TradeCaptureNote]] = {}
    for note in db.exec(select(TradeCaptureNote).where(TradeCaptureNote.source_key.in_(raws))).all():
        trade_id = trade_of.get((note.source_key, note.account_id))
        if trade_id is not None:
            found[note.id] = (trade_id, note)
    plans = {}
    for link in db.exec(select(CaptureLink).where(CaptureLink.unlinked_at.is_(None), CaptureLink.source_key.in_(raws))).all():
        trade_id = trade_of.get((link.source_key, link.account_id))
        if trade_id is not None:
            plans[link.capture_id] = trade_id
    if plans:
        for note in db.exec(select(TradeCaptureNote).where(TradeCaptureNote.capture_id.in_(list(plans)),
                                                            TradeCaptureNote.kind == "note")).all():
            found.setdefault(note.id, (plans[note.capture_id], note))
    out: dict[str, list[dict]] = defaultdict(list)
    for trade_id, note in sorted(found.values(), key=lambda pair: (pair[1].created_at, str(pair[1].id))):
        out[str(trade_id)].append({**_row(note), "capture_id": str(note.capture_id) if note.capture_id else None} if with_ids else _row(note))
    return dict(out)


def trade_for_fill(db: Session, symbol: str, contract: str) -> uuid.UUID | None:
    """The journal trade a Robinhood fill line belongs to (the book's Orders group: a fill that closed a position, or one
    with no row to sit on), by its ticker and contract label (``chart_journal.contract_label``, as the line has it): the
    newest such trade, an open one first. None when the journal does not have it yet (a fill whose email is not in)."""
    symbol = (symbol or "").strip().upper()
    if not symbol or not contract:
        return None
    trades = db.exec(select(Trade).where(Trade.ticker == symbol).order_by(Trade.opened_at.desc()).limit(RECENT_TRADES)).all()
    same = [t for t in trades if contract_label(t.ticker, t.instrument_type, t.option_type, t.strike, t.expiration) == contract]
    same.sort(key=lambda t: (t.status == "open", t.opened_at), reverse=True)
    return same[0].id if same else None


def anchored_only(db: Session, trade_ids: list[uuid.UUID]) -> dict[str, list[dict]]:
    """The desk notes on trades with no plan when written (``capture_id`` empty): the plans' own notes already show
    under their plans."""
    notes = for_trades(db, trade_ids, with_ids=True)
    return {trade_id: [{k: v for k, v in n.items() if k != "capture_id"} for n in rows if n["capture_id"] is None]
            for trade_id, rows in notes.items() if any(n["capture_id"] is None for n in rows)}
