"""A paper result for every Radar setup card (``RadarSetup.paper_*``): no model, no orders.

The owner does not rate alerts, so each card with a candidate contract is paper traded on the shadow book's and the
setup scanner's pricing rules: buy one contract at the ask of the first quote whose bid and ask both updated after the
card (``shadow_book.entry_fill``, ``setup_scanner._fresh``), sell at the bid of the first such quote after the exit
condition (``shadow_book.exit_fill``), $0.65 a side (``scanner_rules.result``).

pending -> open: the first fresh option quote after ``created_at``; none within ``ENTRY_WINDOW_SECONDS`` ->
unresolved. open -> closed at the first of: invalidation (after the entry, a recorded Radar pass whose ``last`` is at
or through the card's invalidation, or whose day low (up) / high (down) is a new extreme made after the card that is
at or through it), the time stop ``HOLD_MINUTES`` after the entry, or ``FLAT_MINUTES`` before the regular close. Anything
still pending or open after its session is unresolved; nothing is carried overnight.

Everything is derived from the row and the Radar store's own recorded passes, so a restart neither loses nor repeats
anything. ``step`` reads nothing from the provider when no row is pending or open, makes at most one batched quote
request, and never raises into the recorder.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

from sqlmodel import Session, col, select

from app.engine import scanner_rules as rules
from app.engine import tradier
from app.engine.shadow_book import entry_fill, exit_fill
from app.models import RadarSetup

log = logging.getLogger(__name__)

HOLD_MINUTES = 60  # the owner's audit: his best holds are 15-60 minutes
ENTRY_WINDOW_SECONDS = 120  # no fresh quote within this after the card -> unresolved
# The session-close exit's flat time, before the regular close. ``step`` runs once a minute after the Radar pass and
# the exit needs a quote fresh after the condition, so a flat time on the last minute would leave no later step to
# fill it; five minutes leaves several passes for a fresh quote.
FLAT_MINUTES = 5
LIVE = ("pending", "open")
_PLAN = {"instrument": "calls", "direction": "long"}  # buy to open, sell to close: ask in, bid out


def _epoch(value: datetime) -> float:
    """A naive-UTC model timestamp as epoch seconds."""
    return value.replace(tzinfo=UTC).timestamp() if value.tzinfo is None else value.timestamp()


def _utc(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC).replace(tzinfo=None)


def _retrieved(row: dict) -> float | None:
    try:
        return datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def invalidation_at(direction: str, invalidation: float, card_at: float, entry_at: float,
                    rows: list[dict]) -> float | None:
    """When the stock first went at or through the invalidation after the entry, from the store's recorded rows of
    one symbol (``retrieved_at``, ``last``, ``low``, ``high``), or None.

    The day low (up) / high (down) only counts when it is a new extreme made after the card: the baseline is the
    extreme of the last recorded row at or before the card (or, without one, the first row after it), because the
    invalidation is the lowest recorded last, sampled once a minute, so the day extreme can already be through it."""
    up = direction == "up"
    side = "low" if up else "high"
    timed = sorted((t, r) for r in rows if (t := _retrieved(r)) is not None)
    baseline = None
    for t, r in timed:
        if t <= card_at and r.get(side) is not None:
            baseline = r[side]
    for t, r in timed:
        if t <= card_at:
            continue
        extreme = r.get(side)
        if baseline is None:
            baseline = extreme  # no row before the card: the first after it sets what already existed
            new_extreme = False
        else:
            new_extreme = extreme is not None and (extreme < baseline if up else extreme > baseline)
        if t <= entry_at:
            continue
        last = r.get("last")
        through_last = last is not None and (last <= invalidation if up else last >= invalidation)
        through_extreme = new_extreme and (extreme <= invalidation if up else extreme >= invalidation)
        if through_last or through_extreme:
            return t
    return None


def exit_condition(row: RadarSetup, rows: list[dict], close_at: float | None, now: float) -> dict | None:
    """The first exit condition that has happened by ``now``: {"reason", "condition_at"}, or None."""
    entry_at = _epoch(row.paper_entry_at)
    found = []
    hit = invalidation_at(row.direction, row.invalidation, _epoch(row.created_at), entry_at, rows)
    if hit is not None:
        found.append({"reason": "invalidation", "condition_at": hit})
    for reason, moment in (("time_stop", entry_at + HOLD_MINUTES * 60),
                           ("session_close", None if close_at is None else close_at - FLAT_MINUTES * 60)):
        if moment is not None and now >= moment:
            found.append({"reason": reason, "condition_at": moment})
    return min(found, key=lambda f: f["condition_at"]) if found else None


class SetupPaper:
    """Fills the ``paper_*`` columns of Radar setup cards, one step a minute after the Radar pass."""

    def __init__(self, engine, store, *, quotes=tradier.get_quotes_once, clock=time.time):
        self.engine, self.store, self.quotes, self.clock = engine, store, quotes, clock

    def step(self, session_date: str, close_at: float | None) -> None:
        try:
            self._step(session_date, close_at)
        except Exception:  # the paper book is extra; it never stops the recorder
            log.exception("Radar setup paper step failed; the next minute tries again")

    def _step(self, session_date: str, close_at: float | None) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            live = list(db.exec(select(RadarSetup).where(col(RadarSetup.paper_state).in_(LIVE))))
        if not live:
            return
        wanted: list[tuple[RadarSetup, dict, dict | None]] = []  # (row, contract, exit condition or None for entry)
        history: dict[str, list[dict]] = {}
        for row in live:
            try:
                if row.session_date != session_date:
                    self._resolve(row, "unresolved", note=f"session {row.session_date} ended with the card still "
                                                          f"{row.paper_state}; nothing is carried overnight")
                    continue
                contract = json.loads(row.contract_json) if row.contract_json else None
                if not contract or not contract.get("symbol"):
                    self._resolve(row, "unresolved", note="no candidate contract to paper trade")
                    continue
                if row.paper_state == "pending":
                    if now - _epoch(row.created_at) > ENTRY_WINDOW_SECONDS:
                        self._resolve(row, "unresolved", note="no fresh option quote within 2 minutes of the card")
                    else:
                        wanted.append((row, contract, None))
                    continue
                if row.symbol not in history:  # one store read per open symbol: its recorded rows this session
                    history[row.symbol] = self.store.quotes(session_date=session_date, symbol=row.symbol)
                found = exit_condition(row, history[row.symbol], close_at, now)
                if found is not None:
                    wanted.append((row, contract, found))
            except Exception:
                log.exception("Radar setup paper: card %s skipped this minute", row.id)
        if not wanted:
            return
        try:
            quotes = self.quotes(sorted({c["symbol"] for _, c, _ in wanted}))
        except Exception as exc:  # a failed request just waits for the next minute
            log.warning("Radar setup paper: option quotes failed (%s); the next minute tries again", exc)
            return
        for row, contract, found in wanted:
            try:
                quote = quotes.get(contract["symbol"])
                if found is None:
                    fill = entry_fill(_PLAN, quote, _epoch(row.created_at))
                    if fill is not None:
                        self._update(row, "pending", paper_state="open", paper_entry_price=fill["price"],
                                     paper_entry_at=_utc(now))
                    continue
                entry = {"bid": row.paper_entry_price, "ask": row.paper_entry_price}
                fill = exit_fill(_PLAN, entry, quote, found["condition_at"], found["reason"])
                if fill is not None:
                    pnl = rules.result(entry, fill, int(contract.get("multiplier") or 100))["pnl"]
                    self._update(row, "open", paper_state="closed", paper_exit_price=fill["price"],
                                 paper_exit_at=_utc(now), paper_exit_reason=found["reason"], paper_pnl=pnl)
            except Exception:
                log.exception("Radar setup paper: card %s skipped this minute", row.id)

    def _resolve(self, row: RadarSetup, state: str, *, note: str) -> None:
        self._update(row, row.paper_state, paper_state=state, paper_note=note)

    def _update(self, row: RadarSetup, expected: str, **values) -> None:
        """Write only if the row is still in the state it was read in (a second process never double-writes)."""
        with Session(self.engine) as db:
            current = db.get(RadarSetup, row.id)
            if current is None or current.paper_state != expected:
                return
            for key, value in values.items():
                setattr(current, key, value)
            db.add(current)
            db.commit()


def scorecard(db: Session) -> list[dict]:
    """One row per (kind, direction) present: cards, contracts, plans and the paper results. A read only."""
    out: dict[tuple[str, str], dict] = {}
    for kind, direction, contract, plan, state, pnl in db.exec(
            select(RadarSetup.kind, RadarSetup.direction, RadarSetup.contract_json, RadarSetup.plan_state,
                   RadarSetup.paper_state, RadarSetup.paper_pnl)):
        card = out.setdefault((kind, direction), {"kind": kind, "direction": direction, "cards": 0, "with_contract": 0,
                                                  "planned": 0, "paper_closed": 0, "paper_green": 0,
                                                  "paper_pnl": 0.0, "unresolved": 0})
        card["cards"] += 1
        card["with_contract"] += contract is not None
        card["planned"] += plan == "planned"
        card["unresolved"] += state == "unresolved"
        if state == "closed":
            card["paper_closed"] += 1
            card["paper_green"] += (pnl or 0) > 0
            card["paper_pnl"] = round(card["paper_pnl"] + (pnl or 0), 2)
    return [out[key] for key in sorted(out)]
