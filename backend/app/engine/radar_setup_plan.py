"""Plan it: one tap on a Radar setup ping saves the setup card as a real plan in the journal.

The ping's ``rp:<RadarSetup id>`` button (``telegram_replies.plan_button``) runs ``plan`` with no model call. With a
fresh quote for the stock on the idea's side of the setup's invalidation, it claims the card (``plan_state``
``none`` to ``planned``, so a double tap or a retry never saves two plans), opens the plan's desk thread
(``Radar setup: NBIS dip turning up``), saves the pre-trade plan capture as the plan card's Confirm saves one (a
discretionary ``Copilot plan`` on the default, or only, account, long calls for ``up`` and long puts for ``down``, the
candidate contract when the card has one, origin ``radar_event`` with the event id, so ``radar_proof`` counts the
event as planned) and arms its invalidation alert (``plan_role="invalidation"``, ``source_kind="copilot"`` on the
thread, so the plan ladder, the Plans board and the invalidation ping read it), then, best effort, a 60-minute time stop
(``plan_time_stops.create``, text ``60m``: it counts from the tap, never runs past the close, and pings only if a
position in the symbol was entered after the plan); a time stop refused or failed never fails the plan. There is no
entry alert: the setup's entry is now, so a card from an earlier session (its ``session_date`` is not today's New York
date by ``now``) is refused with nothing written. A failure after the claim and before the plan is saved releases the
claim, so a later tap can plan it: a desk thread opened before the capture was saved is deleted, and a capture already
saved is reused with its thread, so a retry ends with one thread, one capture and one alert. An alert the caps refuse
or the database fails to save leaves the plan standing, and the reply says it is not armed. A stock already at or through the invalidation is refused once, with the reason kept on the card; a
missing or stale quote leaves the card untouched for a later tap. Advice only: nothing places, sizes or suggests an
order.
"""

from datetime import UTC, date, datetime
import json
import logging
import time
from typing import Callable
import uuid

from sqlalchemy import delete, update
from sqlmodel import Session

from app.engine.chart_math import ET
from app.models import CopilotInvestigation, RadarSetup

log = logging.getLogger(__name__)

WORDS = {("dip_turn", "up"): "dip turning up", ("dip_turn", "down"): "pop turning down",
         ("gap_reversal", "up"): "gap down turning up", ("gap_reversal", "down"): "gap up turning down"}
PLANNED = "Planned"
NOT_PLANNED = "Not planned"


def _live_price(symbol: str) -> float | None:
    """The copilot's fresh quote, as the plan card's Confirm reads it; None when it is stale or missing."""
    from app.engine.telegram_replies import _fresh_quote
    last, fresh = _fresh_quote(symbol)
    return last if fresh and last else None


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def setup_words(row: RadarSetup) -> str:
    return WORDS.get((row.kind, row.direction), f"{row.kind.replace('_', ' ')} {row.direction}")


def plan(engine, setup_id: str, *, now: float | None = None, quote: Callable[[str], float | None] | None = None) -> tuple[str, str | None]:
    """The Plan it tap: ``(reply, chosen label)``, the label None when a later tap may still plan it."""
    from app.engine import captures, copilot_investigations as investigations, copilot_plans, plan_time_stops
    from app.engine.chart_journal import contract_label
    from app.engine.level_alert_monitor import create_alert
    from app.engine.telegram_replies import _calendar, _plan_account
    now = time.time() if now is None else now
    key = _uuid(setup_id)
    with Session(engine) as db:
        row = db.get(RadarSetup, key) if key else None
        if row is None:
            return "That setup is no longer available.", None
        if row.plan_state == "planned":
            return "Already planned.", PLANNED
        if row.plan_state == "refused":
            return f"Not planned: {row.plan_note or 'this setup was refused.'}", NOT_PLANNED
        today = datetime.fromtimestamp(now, ET).date()
        if row.session_date != today.isoformat():
            try:
                day = date.fromisoformat(row.session_date)
                when = f"{day:%b} {day.day}"
            except ValueError:
                when = "an earlier session"
            return f"This setup is from {when}; its level no longer applies. No plan saved.", NOT_PLANNED
        symbol, level, long, event_id = row.symbol, row.invalidation, row.direction == "up", row.event_id
        side = "below" if long else "above"
        account = _plan_account(db)
        if account is None:
            return "Set a default account for plans on the desk first; nothing was saved.", None
        last = (quote or _live_price)(symbol)
        if not last:
            return f"The latest {symbol} quote is stale or missing, so nothing was saved. Tap again in a moment.", None
        if (last <= level) if long else (last >= level):
            note = f"{symbol} is already {side} {level:,.2f}, the level this setup was built on. No plan saved."
            refused = db.exec(update(RadarSetup).where(RadarSetup.id == row.id, RadarSetup.plan_state == "none")
                              .values(plan_state="refused", plan_note=note))
            db.commit()
            return (note, NOT_PLANNED) if refused.rowcount == 1 else ("Already planned.", PLANNED)

        contract = json.loads(row.contract_json) if row.contract_json else None
        option_type = "call" if long else "put"
        if contract and contract.get("option_type") not in (None, option_type):
            contract = None  # a candidate on the wrong side is not this idea's
        strike = contract.get("strike") if contract else None
        expiration = contract.get("expiration") if contract else None
        words = setup_words(row)
        thesis = f"{symbol} {words} on Radar ({row.event_id}); the idea is wrong {side} {level:,.2f}."
        contract_text = (contract_label(symbol, "option", option_type, strike, datetime.fromisoformat(expiration).date())
                         if strike is not None and expiration else None)

        def body(thread_id: str | None) -> dict:  # the plan card's savePlanCapture body
            return {
                "client_id": row.id.hex, "underlying": symbol, "account_id": account, "side": "buy_calls" if long else "buy_puts",
                "strike": strike, "expiration": expiration,
                "wording": f"Entry: now, near {last:,.2f}. Invalidation: crosses {level:,.2f}."[:captures.WORDING_MAX],
                "note": " ".join(filter(None, [f"Thesis: {thesis}", contract_text and f"Contract: {contract_text}."]))[:captures.NOTE_MAX],
                "client_captured_at": now * 1000, "mode": "discretionary", "setup_label": copilot_plans.PLAN_LABEL, "image": False,
                "origin": {"kind": "radar_event", "ref": row.event_id, "text": f"Radar setup: {symbol} {words}"},
                "context": {"state": "unavailable", "reason": "Saved by Plan it on a Radar setup ping.", "investigation_id": thread_id}}
        try:
            captures.build(db, body(None))  # every check before anything is written
        except captures.CaptureError as exc:
            return f"Not planned: {exc}", None

        setup_key, client_id = row.id, row.id.hex
        claimed = db.exec(update(RadarSetup).where(RadarSetup.id == setup_key, RadarSetup.plan_state == "none")
                          .values(plan_state="planned", planned_at=datetime.fromtimestamp(now, UTC).replace(tzinfo=None)))
        db.commit()
        if claimed.rowcount != 1:
            return "Already planned.", PLANNED
        saved = captures.by_client_id(db, client_id)  # an earlier tap's plan whose last step failed: reuse it
        thread_id = json.loads(saved.context_json or "{}").get("investigation_id") if saved else None
        created = None
        try:
            if thread_id is None:
                thread_id = created = investigations.create(investigations.InvestigationFields(
                    title=f"Radar setup: {symbol} {words}", symbol=symbol), session=db)["id"]
                captures.save(db, captures.build(db, body(thread_id)))
            db.exec(update(RadarSetup).where(RadarSetup.id == setup_key).values(investigation_id=thread_id))
            db.commit()
        except Exception:
            log.exception("Radar setup %s: the plan failed after the claim; the claim is released", event_id)
            db.rollback()
            if created is not None and captures.by_client_id(db, client_id) is None:
                try:  # the thread committed on its own and no plan points at it, so it goes
                    db.exec(delete(CopilotInvestigation).where(CopilotInvestigation.id == uuid.UUID(created)))
                    db.commit()
                except Exception:
                    log.exception("Radar setup %s: the unused desk thread %s was not removed", event_id, created)
                    db.rollback()
            db.exec(update(RadarSetup).where(RadarSetup.id == setup_key, RadarSetup.plan_state == "planned")
                    .values(plan_state="none", planned_at=None))
            db.commit()
            return "The plan could not be saved, so nothing is planned. Tap again in a moment.", None
        try:
            create_alert(db, symbol=symbol, price=level, reference=last, condition="crosses", interval=None, session="regular",
                         source_kind="copilot", source_id=thread_id, label=f"{symbol} invalidation: crosses {level:,.2f}",
                         now=now, plan_role="invalidation")
            armed = "Alert armed."
        except ValueError as exc:
            db.rollback()
            armed = f"Alert not armed: {exc}"
        except Exception:  # a database error: the plan stands, said plainly
            log.exception("Radar setup %s: the invalidation alert could not be saved", event_id)
            db.rollback()
            armed = "Alert not armed: it could not be saved."
        try:
            plan_time_stops.create(db, client_id=client_id, investigation_id=thread_id, symbol=symbol, text="60m", now=now,
                                   calendar=_calendar())
            armed += " 60-minute check armed."
        except Exception as exc:  # refused (after the close) or failed: the plan stands without it
            db.rollback()
            log.info("Radar setup %s: no 60-minute check (%s)", event_id, exc)
    log.info("Radar setup %s planned for %s: %s", event_id, symbol, armed)
    return f"Planned {symbol}: out {side} {level:,.2f}. {armed}", PLANNED


# ------------------------------------------------------------------ the desk's reads


def for_event(db: Session, event_id: str) -> RadarSetup | None:
    from sqlmodel import select
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
        "record": row.record_text, "paper_record": radar_setup.paper_record(db, row.kind, row.direction),
        "paper": paper, "plan_state": row.plan_state, "plan_note": row.plan_note,
        "investigation_id": row.investigation_id, "last": last, "distance_pct": distance,
    }


def thread_ids(db: Session, ids: list[str]) -> set[str]:
    """The desk threads among ``ids`` that came from Radar: a setup's Plan it thread, or a plan whose origin is a Radar
    event (the capture's ``context.investigation_id``)."""
    from sqlmodel import select
    from app.models import TradeCapture
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
    from sqlmodel import select
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
