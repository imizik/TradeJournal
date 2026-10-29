"""The plan streak: how many of the latest entries had a plan saved before them.

An entry is a reconstructed trade's first entry in a Robinhood account (Webull
is out), the tracked ones while capture tracking is on. It counts as planned
only through a plan the owner linked whose timing is pre-entry; a late plan
(unverified or retrospective) or no plan breaks the streak. A recent entry
with a suggested but unlinked plan is pending for 30 minutes: it neither
extends nor breaks the streak until it is linked or that time passes. An entry
with a date but no time of day is left out, as in capture adherence. This
week's entries are also listed one by one, in time order, with the trade and
the linked plan's capture. Reads ``capture_links`` and never changes a link.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.engine import capture_links
from app.engine.capture_links import entry_utc, reliable
from app.engine.captures import epoch, profile
from app.engine.chart_journal import ET, contract_label, number, stamp
from app.models import Account, CaptureLink, Trade, TradeCapture

# A suggested plan this long after the entry stops holding the streak open.
PENDING = timedelta(minutes=30)
# Without tracking, entries this recent are counted.
DEFAULT_DAYS = 30


def _accounts(db: Session, tracked: list[str] | None) -> list[uuid.UUID]:
    rows = db.exec(select(Account)).all()
    return [a.id for a in rows if (a.broker or "robinhood") == "robinhood" and (tracked is None or str(a.id) in tracked)]


def _short(trade: Trade) -> str:
    """The chip's contract: ``NBIS 100C`` or ``NBIS stock``."""
    if trade.instrument_type != "option":
        return f"{trade.ticker} stock"
    kind = {"call": "C", "put": "P"}.get(trade.option_type or "", "")
    return f"{trade.ticker} {number(trade.strike):g}{kind}" if trade.strike is not None else trade.ticker


def _week(now: datetime) -> tuple[datetime, datetime]:
    """Monday 00:00 to Saturday 00:00 of this New York week, as naive wall clocks (the journal's own)."""
    today = now.replace(tzinfo=UTC).astimezone(ET).date()
    monday = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    return monday, monday + timedelta(days=5)


def streak(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    row = profile(db)
    tracked = json.loads(row.tracking_accounts) if row.tracking_since is not None and row.tracking_accounts else None
    since = row.tracking_since if tracked is not None else now - timedelta(days=DEFAULT_DAYS)
    show = tracked is not None or db.exec(select(TradeCapture.id).limit(1)).first() is not None
    accounts = _accounts(db, tracked)
    trades = [t for t in db.exec(select(Trade).where(Trade.account_id.in_(accounts), Trade.opened_at >= since - timedelta(days=1))).all()
              if reliable(t.opened_at) and entry_utc(t.opened_at) >= since] if accounts else []
    trades.sort(key=lambda t: (t.opened_at, str(t.id)))

    # Each linked trade's timing, through the links as they resolve now.
    active = db.exec(select(CaptureLink.capture_id).where(CaptureLink.unlinked_at.is_(None))).all()
    linked = list(db.exec(select(TradeCapture).where(TradeCapture.id.in_(active))).all()) if active else []
    linked_ids = set(active)
    links = [(capture_id, r["link"]) for capture_id, r in capture_links.link_rows(db, linked).items() if r["link"] and r["link"].get("trade_id")]
    timing = {link["trade_id"]: link["timing"] for _, link in links}
    plan_of = {link["trade_id"]: str(capture_id) for capture_id, link in links}
    # Plans suggested for an entry in the last 30 minutes; only a capture this recent can be one.
    recent = [c for c in db.exec(select(TradeCapture).where(TradeCapture.received_at >= now - PENDING - timedelta(minutes=15))).all()
              if c.id not in linked_ids and c.not_taken_at is None]
    suggested = {s["trade_id"] for rows in capture_links.suggestions(db, recent).values() for s in rows}

    def state(trade: Trade) -> str:
        when = timing.get(str(trade.id))
        if when == "pre_entry":
            return "planned"
        if when is None and str(trade.id) in suggested and entry_utc(trade.opened_at) > now - PENDING:
            return "pending"
        return "late" if when else "unplanned"

    states = [(trade, state(trade)) for trade in trades]
    best = run = 0
    for _, value in states:
        if value == "planned":
            run += 1
            best = max(best, run)
        elif value != "pending":
            run = 0
    current = 0
    last_break = None
    for trade, value in reversed(states):
        if value == "planned":
            current += 1
        elif value != "pending":
            last_break = {"contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
                          "short": _short(trade), "entry_time": stamp(trade.opened_at), "reason": "late" if value == "late" else "no_plan"}
            break
    monday, saturday = _week(now)
    week = [(trade, value) for trade, value in states if monday <= trade.opened_at < saturday]
    entries = [{"trade_id": str(trade.id), "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
                "short": _short(trade), "entry_time": stamp(trade.opened_at), "state": value,
                **({"capture_id": plan_of[str(trade.id)]} if str(trade.id) in plan_of else {})} for trade, value in week]
    counts = [value for _, value in week]
    return {
        "show": show, "since": epoch(since), "tracking": tracked is not None,
        "current": current, "best": best, "pending": sum(value == "pending" for _, value in states),
        "this_week": {"planned": counts.count("planned"), "total": len(counts), "pending": counts.count("pending"), "start": stamp(monday),
                      "entries": entries},
        "last_break": last_break,
    }
