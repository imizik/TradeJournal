"""Radar setup cards on the copilot desk (docs/copilot-lab.md § The desk, docs/radar.md § Setup cards): read-only views.

The card as the desk's Radar card shows it (``view``), which desk threads came from Radar (``thread_ids``) and the
compact rows ``get_radar_today`` carries (``copilot_rows``). Planning reuses ``radar_setup_plan.plan`` unchanged.
Reads ``RadarSetup`` rows and captures only; no provider call, no write.
"""
from datetime import UTC, datetime
import json

from sqlmodel import Session, select

from app.engine import paper_book
from app.engine.radar_setup_plan import setup_words
from app.models import RadarSetup, TradeCapture



def for_event(db: Session, event_id: str) -> RadarSetup | None:
    return db.exec(select(RadarSetup).where(RadarSetup.event_id == event_id)).first()


def _contract(row: RadarSetup) -> dict | None:
    try:
        return json.loads(row.contract_json) if row.contract_json else None
    except ValueError:
        return None


def _contract_text(symbol: str, contract: dict | None) -> str | None:
    """The ping's candidate line; a saved contract missing a quote field still names itself."""
    from app.engine import radar_setup
    if not contract:
        return None
    try:
        return radar_setup._contract_line(symbol, contract)
    except (KeyError, TypeError, ValueError):
        letter = "C" if contract.get("option_type") == "call" else "P"
        return f"Candidate: {symbol} {contract.get('expiration', '')} {contract.get('strike', '')}{letter}".replace("  ", " ")


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if value else None


def view(db: Session, row: RadarSetup, *, last: dict | None = None) -> dict:
    """The setup card as the desk's Radar card shows it, worded as the phone ping words it (``radar_setup.card_text``).

    ``last``: the stock's latest recorded Radar quote this session (``{"price", "at"}``) when the caller has one, for how
    far price is from the invalidation. Read-only; no account, trade or capture ids."""
    from app.engine import radar_setup
    contract = _contract(row)
    move = (row.invalidation - row.entry) / row.entry * 100
    side = "below" if row.direction == "up" else "above"
    distance = None
    if last and last.get("price"):
        distance = round((last["price"] - row.invalidation) / last["price"] * 100, 2)
    paper = {"state": row.paper_state}
    if row.paper_state == "closed":
        paper.update(pnl=row.paper_pnl, exit_reason=row.paper_exit_reason, entry_price=row.paper_entry_price,
                     exit_price=row.paper_exit_price)
    elif row.paper_state == "unresolved":
        paper["note"] = row.paper_note
    return {
        "id": str(row.id), "event_id": row.event_id, "session_date": row.session_date, "kind": row.kind,
        "direction": row.direction, "symbol": row.symbol, "words": setup_words(row), "entry": row.entry,
        "invalidation": row.invalidation, "side": side,
        "levels_line": f"In near {row.entry:.2f} · out {side} {row.invalidation:.2f} ({radar_setup._signed(move)}%)",
        "contract_line": _contract_text(row.symbol, contract),
        # The candidate contract as the desk's Paper it names it (type, expiration, strike), or None.
        "contract": paper_book.idea_contract(contract),
        "record": row.record_text, "paper_record": radar_setup.paper_record(db, row.kind, row.direction),
        "paper": paper, "plan_state": row.plan_state, "plan_note": row.plan_note,
        "investigation_id": row.investigation_id, "last": last, "distance_pct": distance,
    }


def thread_ids(db: Session, ids: list[str]) -> set[str]:
    """The desk threads among ``ids`` that came from Radar: a setup's Plan it thread, or a plan whose origin is a Radar
    event (the capture's ``context.investigation_id``)."""
    wanted = {str(i) for i in ids}
    if not wanted:
        return set()
    found = {t for t in db.exec(select(RadarSetup.investigation_id).where(RadarSetup.investigation_id.in_(wanted))).all() if t}
    for context in db.exec(select(TradeCapture.context_json).where(TradeCapture.origin_kind == "radar_event")).all():
        try:
            thread = json.loads(context or "{}").get("investigation_id")
        except ValueError:
            continue
        if thread in wanted:
            found.add(thread)
    return found


MAX_COPILOT_ROWS = 8
_EXIT = {"invalidation": "invalidation", "time_stop": "60-minute stop", "session_close": "the close"}


def copilot_rows(db: Session, session: str, before: float | None = None, most: int = MAX_COPILOT_ROWS) -> list[dict]:
    """The session's setup cards for ``get_radar_today``, newest first, compact. ``before`` (replay's frozen moment, an
    epoch) drops a card made later, a plan saved later and a paper result closed later."""
    from app.engine import radar_setup
    cut = None if before is None else datetime.fromtimestamp(before, UTC).replace(tzinfo=None)
    rows = db.exec(select(RadarSetup).where(RadarSetup.session_date == session).order_by(RadarSetup.created_at.desc())).all()
    out = []
    for row in rows:
        if cut is not None and row.created_at > cut:
            continue
        contract = _contract(row)
        planned = row.plan_state == "planned" and (cut is None or (row.planned_at is not None and row.planned_at <= cut))
        refused = row.plan_state == "refused" and cut is None
        item = {"symbol": row.symbol, "event_id": row.event_id, "setup": setup_words(row), "entry": row.entry,
                "invalidation": row.invalidation,
                "contract": (_contract_text(row.symbol, contract) or "").removeprefix("Candidate: ") or None,
                "record": row.record_text, "plan": "planned" if planned else "refused" if refused else "not planned",
                "first_seen": _iso(row.created_at)}
        if row.paper_state == "closed" and row.paper_pnl is not None and (cut is None or (row.paper_exit_at and row.paper_exit_at <= cut)):
            item["paper"] = f"{radar_setup._dollars(row.paper_pnl)} per contract, out at {_EXIT.get(row.paper_exit_reason, row.paper_exit_reason)}"
        out.append(item)
        if len(out) >= most:
            break
    return out


def last_recorded(store, session: str, symbol: str, today: str) -> dict | None:
    """The symbol's latest recorded Radar quote in ``session`` when that session is ``today``; None otherwise."""
    if session != today:
        return None
    rows = [r for r in store.quotes(session_date=session, symbol=symbol) if r.get("last")]
    if not rows:
        return None
    row = max(rows, key=lambda r: r.get("retrieved_at") or "")
    return {"price": row["last"], "at": row.get("retrieved_at")}
