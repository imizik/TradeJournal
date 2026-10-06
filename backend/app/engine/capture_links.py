"""Capture links and capture adherence (Charts C3.6).

A capture is linked to one reconstructed trade, by the user: matches are only
suggested. The link is anchored in the source identity of the trade's first
entry fill (account plus ``raw_email_id``, the dedupe key) and resolved to the
current trade through that fill's ``tradefill`` row on every read, so rebuilds
and resyncs never move a link to a different trade; a vanished fill leaves it
unresolved, and timing is recomputed from the trade as it is now.

Timing compares the server's receipt of the complete intent (UTC) with the
first entry's execution time, a New York wall clock that broker emails give to
the minute. Only intent received before that minute began is confirmed
pre-entry; inside it, timing-unverified; after it, retrospective. An entry with
a date but no time is excluded from the count. Adherence measures capture,
never trading discipline or profitability.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.engine.captures import CaptureError, epoch, profile
from app.engine.chart_journal import contract_label, stamp
from app.models import Account, CaptureLink, Fill, Trade, TradeCapture, TradeFill

# The initial candidate window after the qualifying capture time.
WINDOW = timedelta(minutes=10)
# Unlinked plans this recent (or since tracking began) are listed for linking.
REVIEW_DAYS = 30

# What each captured side opens: instrument, option type and the journal's opening side.
OPENING: dict[str, tuple[str, str | None, str]] = {
    "buy_calls": ("option", "call", "buy_to_open"), "buy_puts": ("option", "put", "buy_to_open"),
    "sell_calls": ("option", "call", "sell_to_open"), "sell_puts": ("option", "put", "sell_to_open"),
    "buy_stock": ("stock", None, "buy"),
    # The journal reconstructs no short stock, so nothing matches it.
    "short_stock": ("stock", None, "sell_short"),
}


def entry_utc(wall: datetime) -> datetime:
    """A journal time (naive New York wall clock) as a naive UTC datetime, comparable with ``received_at``."""
    return datetime.fromtimestamp(stamp(wall), UTC).replace(tzinfo=None)


def reliable(wall: datetime | None) -> bool:
    """False for an entry recorded with a date but no time of day."""
    return wall is not None and (wall.hour, wall.minute, wall.second, wall.microsecond) != (0, 0, 0, 0)


def timing(received_at: datetime, entry_wall: datetime | None) -> str:
    """pre_entry | unverified | retrospective, for intent received at ``received_at`` (UTC)."""
    if not reliable(entry_wall):
        return "unverified"
    start = entry_utc(entry_wall)
    # A whole-minute time means the fill happened somewhere in that minute.
    end = start + (timedelta(minutes=1) if entry_wall.second == 0 and entry_wall.microsecond == 0 else timedelta(0))
    if received_at < start:
        return "pre_entry"
    return "unverified" if received_at < end else "retrospective"


def _trades(db: Session, *filters) -> list[dict]:
    """Trades with their first entry fill (a trade's id is that fill's id), as plain rows."""
    rows = db.exec(select(Trade.id, Trade.account_id, Trade.ticker, Trade.instrument_type, Trade.option_type, Trade.strike,
                          Trade.expiration, Trade.opened_at, Trade.status, Fill.side, Fill.raw_email_id)
                   .join(Fill, Fill.id == Trade.id, isouter=True).where(*filters)).all()
    return [dict(row._mapping) for row in rows]


def _compatible(capture: TradeCapture, trade: dict) -> bool:
    instrument, option_type, side = OPENING.get(capture.side, (None, None, None))
    if trade["account_id"] != capture.account_id or trade["ticker"] != capture.underlying:
        return False
    if trade["instrument_type"] != instrument or trade["side"] != side:
        return False
    if instrument == "option":
        if trade["option_type"] != option_type:
            return False
        # Contract fields the user gave must agree; their absence is not permission to pick one.
        if capture.strike is not None and (trade["strike"] is None or abs(float(trade["strike"]) - capture.strike) > 1e-6):
            return False
        if capture.expiration is not None and trade["expiration"] != capture.expiration:
            return False
    return True


def _in_window(capture: TradeCapture, trade: dict) -> bool:
    wall = trade["opened_at"]
    if not reliable(wall):
        return False
    start = entry_utc(wall)
    # An entry whose minute ends after the capture, up to ten minutes after it.
    return start + timedelta(minutes=1) > capture.received_at and start <= capture.received_at + WINDOW


def _trade_row(trade: dict, received_at: datetime | None = None) -> dict:
    return {
        "trade_id": str(trade["id"]), "contract": contract_label(trade["ticker"], trade["instrument_type"], trade["option_type"], trade["strike"], trade["expiration"]),
        "entry_time": stamp(trade["opened_at"]), "entry_time_reliable": reliable(trade["opened_at"]), "status": trade["status"],
        "timing": timing(received_at, trade["opened_at"]) if received_at is not None else None,
    }


def _key(trade: dict) -> tuple[str, uuid.UUID]:
    return trade["raw_email_id"], trade["account_id"]


def _resolve(db: Session, links: list[CaptureLink]) -> dict[uuid.UUID, dict | None]:
    """Each link's current trade through its anchored fill, or None when that fill is gone or in no trade."""
    keys = {link.source_key for link in links}
    if not keys:
        return {}
    found = db.exec(select(Fill.raw_email_id, Fill.account_id, TradeFill.trade_id)
                    .join(TradeFill, TradeFill.fill_id == Fill.id).where(Fill.raw_email_id.in_(keys))).all()
    trade_of = {(row.raw_email_id, row.account_id): row.trade_id for row in found}
    trade_ids = set(trade_of.values())
    trades = {row["id"]: row for row in _trades(db, Trade.id.in_(trade_ids))} if trade_ids else {}
    return {link.id: trades.get(trade_of.get((link.source_key, link.account_id))) for link in links}


def link_rows(db: Session, captures: list[TradeCapture]) -> dict[uuid.UUID, dict]:
    """For each capture: its active link (resolved, with timing) and its link history, in a few queries."""
    ids = [capture.id for capture in captures]
    if not ids:
        return {}
    links = list(db.exec(select(CaptureLink).where(CaptureLink.capture_id.in_(ids)).order_by(CaptureLink.linked_at)).all())
    resolved = _resolve(db, [link for link in links if link.unlinked_at is None])
    received = {capture.id: capture.received_at for capture in captures}
    out: dict[uuid.UUID, dict] = {capture_id: {"link": None, "history": []} for capture_id in ids}
    for row in links:
        entry = {"id": str(row.id), "method": row.method, "linked_at": epoch(row.linked_at), "unlinked_at": epoch(row.unlinked_at)}
        if row.unlinked_at is None:
            trade = resolved.get(row.id)
            entry.update(_trade_row(trade, received[row.capture_id]) if trade else
                         {"trade_id": None, "unresolved": True, "contract": None, "timing": None,
                          "note": "The fill this plan was linked to is no longer in a trade. Rebuild trades, or link it again."})
            out[row.capture_id]["link"] = entry
        out[row.capture_id]["history"].append(entry)
    return out


def _active_keys(db: Session) -> set[tuple[str, uuid.UUID]]:
    return {(row.source_key, row.account_id) for row in db.exec(select(CaptureLink).where(CaptureLink.unlinked_at.is_(None))).all()}


def suggestions(db: Session, captures: list[TradeCapture]) -> dict[uuid.UUID, list[dict]]:
    """Unlinked trades each capture plausibly planned: same account, underlying and opening side,
    the exact contract where given, first entry within ten minutes of receipt. Never confirmed here."""
    if not captures:
        return {}
    taken = _active_keys(db)
    # Wall clocks are New York, receipt is UTC: a day of slack, then each candidate is compared exactly.
    earliest = min(capture.received_at for capture in captures) - timedelta(days=1)
    latest = max(capture.received_at for capture in captures) + timedelta(days=1)
    pool = _trades(db, Trade.account_id.in_({c.account_id for c in captures}), Trade.ticker.in_({c.underlying for c in captures}),
                   Trade.opened_at >= earliest, Trade.opened_at <= latest)
    pool.sort(key=lambda t: t["opened_at"])
    return {capture.id: [_trade_row(trade, capture.received_at) for trade in pool
                         if _key(trade) not in taken and _compatible(capture, trade) and _in_window(capture, trade)]
            for capture in captures}


def others(db: Session, capture: TradeCapture, limit: int = 10) -> list[dict]:
    """Compatible unlinked trades outside the window within a week, nearest first, for a manual link."""
    taken = _active_keys(db)
    pool = _trades(db, Trade.account_id == capture.account_id, Trade.ticker == capture.underlying,
                   Trade.opened_at >= capture.received_at - timedelta(days=8), Trade.opened_at <= capture.received_at + timedelta(days=8))
    rows = [trade for trade in pool if reliable(trade["opened_at"]) and _key(trade) not in taken
            and _compatible(capture, trade) and not _in_window(capture, trade)]
    rows.sort(key=lambda t: abs((entry_utc(t["opened_at"]) - capture.received_at).total_seconds()))
    return [_trade_row(trade, capture.received_at) for trade in rows[:limit]]


def link(db: Session, capture: TradeCapture, trade_id: uuid.UUID) -> CaptureLink:
    """Link a capture to a trade. One active link per capture and per trade; changing one means unlinking first."""
    if db.exec(select(CaptureLink).where(CaptureLink.capture_id == capture.id, CaptureLink.unlinked_at.is_(None))).first():
        raise CaptureError("This plan is already linked. Unlink it first.")
    rows = _trades(db, Trade.id == trade_id)
    if not rows or rows[0]["raw_email_id"] is None:
        raise CaptureError("That trade is no longer in the journal. Refresh and choose again.")
    trade = rows[0]
    if not _compatible(capture, trade):
        raise CaptureError("That trade is a different account, symbol, side or contract from this plan.")
    if _key(trade) in _active_keys(db):
        raise CaptureError("That trade already has a plan linked. A re-entry is a new trade and needs its own plan.")
    row = CaptureLink(capture_id=capture.id, account_id=trade["account_id"], source_key=trade["raw_email_id"],
                      method="suggested" if _in_window(capture, trade) else "manual")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def unlink(db: Session, capture: TradeCapture) -> None:
    row = db.exec(select(CaptureLink).where(CaptureLink.capture_id == capture.id, CaptureLink.unlinked_at.is_(None))).first()
    if row is not None:
        row.unlinked_at = datetime.utcnow()
        db.add(row)
        db.commit()


def for_trade(db: Session, trade_id: uuid.UUID) -> list[TradeCapture]:
    """Captures actively linked to this trade, through its fills' source identities."""
    keys = {(row.raw_email_id, row.account_id) for row in db.exec(
        select(Fill.raw_email_id, Fill.account_id).join(TradeFill, TradeFill.fill_id == Fill.id).where(TradeFill.trade_id == trade_id)).all()}
    if not keys:
        return []
    links = db.exec(select(CaptureLink).where(CaptureLink.unlinked_at.is_(None), CaptureLink.source_key.in_({key for key, _ in keys}))).all()
    ids = [row.capture_id for row in links if (row.source_key, row.account_id) in keys]
    return list(db.exec(select(TradeCapture).where(TradeCapture.id.in_(ids))).all()) if ids else []


# ---------------------------------------------------------------- tracking

def tracking(db: Session) -> dict:
    row = profile(db)
    return {"since": epoch(row.tracking_since), "accounts": json.loads(row.tracking_accounts) if row.tracking_accounts else []}


def set_tracking(db: Session, on: bool, accounts: list[str]) -> dict:
    row = profile(db)
    if on:
        ids = []
        for value in accounts:
            try:
                account = db.get(Account, uuid.UUID(str(value)))
            except ValueError:
                account = None
            if account is None:
                raise CaptureError("Choose the accounts to track from your journal accounts.")
            ids.append(str(account.id))
        if not ids:
            raise CaptureError("Choose at least one account to track.")
        # Turning tracking on starts the count now; changing accounts keeps the start.
        row.tracking_since = row.tracking_since or datetime.utcnow()
        row.tracking_accounts = json.dumps(sorted(set(ids)))
    else:
        row.tracking_since = None
        row.tracking_accounts = None
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return tracking(db)


def summary(db: Session, pending: set[tuple[str, uuid.UUID]]) -> dict | None:
    """Capture coverage of recorded trades entered since tracking began, in the tracked accounts.
    ``pending``: trades suggested for an unlinked plan, counted as needing linking rather than missed."""
    row = profile(db)
    if row.tracking_since is None or not row.tracking_accounts:
        return None
    accounts = [uuid.UUID(value) for value in json.loads(row.tracking_accounts)]
    since = row.tracking_since
    pool = [t for t in _trades(db, Trade.account_id.in_(accounts), Trade.opened_at >= since - timedelta(days=1))
            if not reliable(t["opened_at"]) or entry_utc(t["opened_at"]) >= since]
    active = list(db.exec(select(CaptureLink).where(CaptureLink.unlinked_at.is_(None))).all())
    by_key = {(row.source_key, row.account_id): row for row in active}
    captures = {c.id: c for c in db.exec(select(TradeCapture).where(TradeCapture.id.in_([row.capture_id for row in active])))} if active else {}
    counts = {"confirmed": 0, "confirmed_discretionary": 0, "unverified": 0, "retrospective": 0, "needs_linking": 0, "no_capture": 0, "excluded": 0}
    for trade in pool:
        if not reliable(trade["opened_at"]):
            counts["excluded"] += 1
            continue
        linked = by_key.get(_key(trade))
        capture = captures.get(linked.capture_id) if linked else None
        if capture is not None:
            when = timing(capture.received_at, trade["opened_at"])
            if when == "pre_entry":
                counts["confirmed"] += 1
                counts["confirmed_discretionary"] += capture.mode == "discretionary"
            else:
                counts[when] += 1
        elif _key(trade) in pending:
            counts["needs_linking"] += 1
        else:
            counts["no_capture"] += 1
    return {"since": epoch(since), "accounts": [str(a) for a in accounts], "eligible": len(pool) - counts["excluded"], **counts}


def review(db: Session, now: datetime | None = None) -> dict:
    """The Needs linking view: unlinked plans with suggestions and other candidates, unresolved links, and the count."""
    now = now or datetime.utcnow()
    since = now - timedelta(days=REVIEW_DAYS)
    tracked = profile(db).tracking_since
    if tracked is not None and tracked < since:
        since = tracked
    recent = list(db.exec(select(TradeCapture).where(TradeCapture.received_at >= since).order_by(TradeCapture.received_at.desc())).all())
    links = link_rows(db, recent)
    unlinked = [c for c in recent if links[c.id]["link"] is None and c.not_taken_at is None]
    unresolved = [c for c in recent if (links[c.id]["link"] or {}).get("unresolved")]
    suggested = suggestions(db, unlinked)
    ids = {uuid.UUID(s["trade_id"]) for rows in suggested.values() for s in rows}
    pending = {_key(row) for row in _trades(db, Trade.id.in_(ids))} if ids else set()
    return {
        "needs_linking": [{"capture_id": str(c.id), "suggestions": suggested[c.id], "others": others(db, c)} for c in unlinked],
        "unresolved": [str(c.id) for c in unresolved],
        # The persistent count: plans with a match waiting for a choice, and links that lost their trade.
        "count": sum(1 for c in unlinked if suggested[c.id]) + len(unresolved),
        "summary": summary(db, pending),
        "tracking": tracking(db),
    }


def needs_linking_count(db: Session) -> int:
    return review(db)["count"]
