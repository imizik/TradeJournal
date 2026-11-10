"""Plan it: one tap on a Radar setup ping saves the setup card as a real plan in the journal.

The ping's ``rp:<RadarSetup id>`` button (``telegram_replies.plan_button``) runs ``plan`` with no model call. With a
fresh quote for the stock on the idea's side of the setup's invalidation, it claims the card (``plan_state``
``none`` to ``planned``, so a double tap or a retry never saves two plans), opens the plan's desk thread
(``Radar setup: NBIS dip turning up``), saves the pre-trade plan capture as the plan card's Confirm saves one (a
discretionary ``Copilot plan`` on the default, or only, account, long calls for ``up`` and long puts for ``down``, the
candidate contract when the card has one, origin ``radar_event`` with the event id, so ``radar_proof`` counts the
event as planned) and arms its invalidation alert (``plan_role="invalidation"``, ``source_kind="copilot"`` on the
thread, so the plan ladder, the Plans board and the invalidation ping read it). There is no entry alert: the setup's
entry is now. A stock already at or through the invalidation is refused once, with the reason kept on the card; a
missing or stale quote leaves the card untouched for a later tap. Advice only: nothing places, sizes or suggests an
order.
"""

from datetime import UTC, datetime
import json
import logging
import time
from typing import Callable
import uuid

from sqlalchemy import update
from sqlmodel import Session

from app.models import RadarSetup

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
    from app.engine import captures, copilot_investigations as investigations, copilot_plans
    from app.engine.chart_journal import contract_label
    from app.engine.level_alert_monitor import create_alert
    from app.engine.telegram_replies import _plan_account
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

        claimed = db.exec(update(RadarSetup).where(RadarSetup.id == row.id, RadarSetup.plan_state == "none")
                          .values(plan_state="planned", planned_at=datetime.fromtimestamp(now, UTC).replace(tzinfo=None)))
        db.commit()
        if claimed.rowcount != 1:
            return "Already planned.", PLANNED
        thread_id = investigations.create(investigations.InvestigationFields(
            title=f"Radar setup: {symbol} {words}", symbol=symbol), session=db)["id"]
        captures.save(db, captures.build(db, body(thread_id)))
        db.exec(update(RadarSetup).where(RadarSetup.id == row.id).values(investigation_id=thread_id))
        db.commit()
        try:
            create_alert(db, symbol=symbol, price=level, reference=last, condition="crosses", interval=None, session="regular",
                         source_kind="copilot", source_id=thread_id, label=f"{symbol} invalidation: crosses {level:,.2f}",
                         now=now, plan_role="invalidation")
            armed = "Alert armed."
        except ValueError as exc:
            db.rollback()
            armed = f"Alert not armed: {exc}"
    log.info("Radar setup %s planned for %s: %s", event_id, symbol, armed)
    return f"Planned {symbol}: out {side} {level:,.2f}. {armed}", PLANNED
