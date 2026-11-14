"""The Copilot desk's thread list (``GET /copilot/desk/threads``, docs/copilot-lab.md § The desk): one grouped list of
what is live, in the desk's group order (``frontend/lib/desk.ts`` ``DESK_GROUPS``), composed in-process from readers
that already exist:

- ``pinned``: the Briefing ("What matters right now?", with today's pre-market prep when there is one) and Review my
  week, with this week's plan numbers;
- ``act``: open positions the Today screen's Act now rule flags (``today._act_now``). A ``decision`` day-journal entry
  for the symbol logged today moves the row to Watching: the owner has already decided, unless the invalidation was
  hit after it;
- ``near``: armed plans not yet in a position within ``today.NEAR_PCT`` of their entry or invalidation (the Today
  screen's rule, on the same board read);
- ``draft``: the owner's open conversations with plan or alert cards still waiting on Confirm or Dismiss (no
  ``outcome`` in the saved transcript), newest first. A conversation already shown as an armed plan or a position stays
  there; a waiting one leaves Watching;
- ``new``: Radar events since the last Radar visit (``today._radar``) and thesis-watch triggers fired today
  (``today._thesis``), newest first;
- a position the position companion adopted (``engine/position_companion.py``) opens its adopted thread and reads
  "Adopted · draft plan" (or its armed invalidation) with ``adopted`` set, until it closes or is ignored;
- ``watch``: every other open position, armed plan and open investigation, and each plan whose position closed in the
  last ``EXIT_DAYS`` days (``copilot_plans.exits``): Exited, asking its one exit review at any hour.

A plan is Done once a ``plan_done`` day-journal entry for its symbol is at or after its newest part (its exit review
answered or skipped, or Mark done): it leaves every group, and so does a conversation of the owner's about the symbol not
touched since.

``plans`` is the thread list's Plans view: every plan by stage (``armed``, ``in_position``, ``exited`` and ``done``
in the last ``EXIT_DAYS`` days, ``copilot_plans.done``), each with its instrument, horizon, levels, time stop and, in
a position, where the underlying sits in units of the plan's risk (``r``); an armed plan, its symbol's newest answered
exit review (``last_exit``).

Each row with a position or a plan carries its symbol's ``horizon`` (``day``, ``swing`` or ``long``): its newest
``horizon`` day-journal entry (a plan card's Confirm or the thread header), else ``swing``. After 16:00 New York on a
weekday (the decision bar's rule, ``frontend/lib/desk.ts`` ``afterClose``) the horizon sets which rows carry ``close``,
the close-of-day question: a day trade every trading day; a swing only on a day something happened to it (a phone ping
or a level alert fired, a fill, or the decision bar asked or was answered); a long hold never (Review my week looks at
it). A position with no plan asks "Want a plan for this?" instead, once: a ``plan_ask`` entry since it opened answers
it. ``close`` carries the first words of the ``reflection`` (or the ``plan_ask`` answer) saved for the symbol today once
there is one, and the row's status line says the same.

Each source is read on its own (``today._section``): one failure reads ``unavailable`` in ``sections`` and the rest
stand. The board reads first, so one batched underlying quote read serves the plans and the positions. Read-only: no
store, no pings, no Radar visit. Owner-only like every ``/copilot`` route; refuses while the lab is off. The only ids
out are investigation, trade and Radar event ids, each the row's own link, and ``fill_to_link``: the open trade whose fill
waits to be linked to a plan (an unplanned position the link ping would offer plans for, or the armed plan the linker
suggests that fill for, matched by symbol). The desk links it inline through the capture link routes; a position row
with one opens on the desk (``/copilot-lab?symbol=``), not on the confirm page.

An option position's value is its own unrealized P&L (the option's mark), never the underlying's price; its plan
levels and meter are on the underlying, and the status line says so by naming it.

``GET /copilot/desk/scorecard`` is the alert scorecard (``app/engine/alert_scorecard.py``), with the Radar scorecard
(``app/engine/radar_scorecard.py``) under ``radar``. ``GET /copilot/desk/to-rate`` is what the retired Rate yesterday card read
(nothing on the desk calls it since 2026-11-10): everything since the previous trading session still waiting on the
owner's rating.
``GET /copilot/desk/pings`` is the day report's "How the pings did": each alert and alerted Radar hit since the previous
trading session (``day_only``: today's) and what followed it; a ticker he does not follow is left out.
``GET /copilot/desk/day-report`` is the after-close day report's other parts (``app/engine/day_report.py``): today's
entries with how many had a plan before the fill, and the calls he checked scored from the price when he checked.
``POST /copilot/desk/read`` is the desk's read of a selected ticker (``app/engine/desk_read.py``); ``POST
/copilot/desk/day-read`` is the read of the owner's day after the close (``app/engine/day_read.py``); ``GET
/copilot/desk/timings`` carries today's counts and cost under ``desk_reads`` and ``day_reads``.
``GET /copilot/desk/session`` (at the end) is the Briefing's session timeline: today's regular session and what
happened in it, from the same kind of existing readers, and the alerts and Radar hits still waiting on an answer.
"""

from datetime import UTC, date, datetime, timedelta
import json
import logging
import uuid
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field as PydField
from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.ai import copilot
from app.database import get_session
from app.engine.radar_evidence import rule_side
from app.engine.chart_math import ET, session_windows
from app.routers import today

log = logging.getLogger(__name__)

router = APIRouter()

MAX_INVESTIGATIONS = 20
DRAFT_KINDS = ("watch", "trade_plan")  # alerts and plans (a plan card carries its time stop); not memories or revisits
CONDITION = {"touches": "touches", "crosses": "crosses", "closes_beyond": "closes beyond"}  # ProposalCard's words
RADAR_KIND = {"relative_to_spy": "vs SPY", "relative_to_sector": "vs sector", "group_move": "Group move", "dip_turn": "Dip turning up",
              "gap_reversal": "Gap reversal"}  # RadarFeedView's words


def _hours(day):
    """The market calendar's day (cached a day at a time); None reads the clock hours, which cannot see holidays."""
    from app.engine.chart_calendar import chart_calendar
    return chart_calendar.hours(day)


def _say(text: str, tone: str) -> dict:
    return {"text": text, "tone": tone}


def _usd(value: float) -> str:
    return f"{'+' if value > 0 else '−' if value < 0 else ''}${abs(value):,.2f}"


def _epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _row(key: str, group: str, title: str, status: dict, *, symbol: str | None = None, instrument: str | None = None,
         value: dict | None = None, meter: dict | None = None, investigation_id: str | None = None,
         trade_id: str | None = None, radar_event_id: str | None = None, path: str | None = None,
         changed_at: int | None = None, fill_to_link: str | None = None) -> dict:
    return {"key": key, "group": group, "symbol": symbol, "title": title, "instrument": instrument, "value": value,
            "status": status, "meter": meter, "investigation_id": investigation_id, "trade_id": trade_id,
            "radar_event_id": radar_event_id, "path": path, "changed_at": changed_at, "horizon": None, "close": None,
            "fill_to_link": fill_to_link, "adopted": False, "hidden": False}


def meter(entry: float | None, invalidation: float | None, last: float | None, tone: str) -> dict | None:
    """The live price on the plan's track: 0 is the invalidation, ``entry`` (0-100) the entry, with a quarter of the
    risk's room beyond it; past the invalidation pins to 0. Either direction: the risk's sign carries it."""
    if entry is None or invalidation is None or last is None or entry == invalidation:
        return None
    progress = (last - invalidation) / (entry - invalidation)  # 0 at the invalidation, 1 at the entry
    span = max(1.25, progress)
    return {"last": round(min(100.0, max(0.0, progress / span * 100)), 1), "entry": round(100 / span, 1), "tone": tone}


# --------------------------------------------------------------------------- sources

def _board(db: Session, quotes: today.SharedQuotes) -> dict:
    from app.engine import copilot_plans
    return {"state": "ok", "plans": copilot_plans.board(db, quotes=quotes)["plans"]}


def _positions(db: Session, quotes: today.SharedQuotes, now: float, day) -> dict:
    from app.engine import plan_positions
    book = plan_positions.positions(db, quotes=quotes)
    act = today._act_now(db, quotes, now, day, book=book)
    return {"state": "ok", "positions": book["positions"], "count": book["count"],
            "flagged": {row["trade_id"]: row for row in act["rows"]}}


def _position_investigations(db: Session, book: dict) -> dict[str, str]:
    """Each planned position's Copilot Lab investigation, as ``plan_positions`` finds its plan: the oldest linked
    capture's ``context.investigation_id``, else its time stop's (the card's ``client_id``)."""
    from app.engine import capture_links, plan_nudges
    from app.models import PlanTimeStop
    out = {}
    for row in book["positions"]:
        if row["plan"] is None:
            continue
        linked = capture_links.for_trade(db, uuid.UUID(row["trade_id"]))
        if not linked:
            continue
        capture = min(linked, key=lambda c: c.received_at)
        found = plan_nudges._investigation(capture)
        if found is None:
            stop = db.exec(select(PlanTimeStop).where(PlanTimeStop.client_id == capture.client_id)
                           .order_by(PlanTimeStop.created_at.desc())).first()
            found = stop.investigation_id if stop else None
        if found:
            out[row["trade_id"]] = found
    return out


def _adopted(db: Session) -> dict[str, dict]:
    """Each adopted, still open position's thread, by trade id: its investigation and plan state."""
    from app.engine import position_companion
    return {trade_id: {"investigation_id": str(row.investigation_id), "state": row.state}
            for trade_id, row in position_companion.adopted_trades(db).items() if row.investigation_id}


def _investigations(db: Session) -> dict:
    """Open investigations, newest first. A research job's conclusion was written by a model that read untrusted web
    pages, so only the owner's own conversations bring theirs (``copilot_context._investigations``' rule)."""
    from app.engine import copilot_investigations
    from app.models import CopilotInvestigation
    found = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.status == "open", col(CopilotInvestigation.main_day).is_(None))
                    .order_by(col(CopilotInvestigation.updated_at).desc()).limit(MAX_INVESTIGATIONS)).all()
    rows = []
    for r in map(copilot_investigations.summary, found):
        rows.append({"id": r["id"], "source": r["source"], "symbol": r["symbol"], "title": r["title"],
                     "conclusion": r["conclusion"] if r["source"] == "copilot" else None, "updated_at": r["updated_at"]})
    return {"state": "ok", "rows": rows}


def _card_text(card: dict) -> str:
    """A waiting card in a few words: "Alert · APLD crosses 31.20", "Plan · APLD long calls · entry crosses 31.20"."""
    level = card if card["kind"] == "watch" else card["entry_trigger"]
    words = f"{level['interval']} close beyond" if level["condition"] == "closes_beyond" else CONDITION.get(level["condition"], level["condition"])
    if card["kind"] == "watch":
        return f"Alert · {card['symbol']} {words} {level['price']:.2f}"
    return f"Plan · {card['symbol']} {card['direction']} {card['instrument']} · entry {words} {level['price']:.2f}"


def _drafts(db: Session) -> dict:
    """Open conversations whose plan or alert cards still wait on the owner (no ``outcome``), newest first, each with
    its waiting cards in transcript order. Only the owner's own conversations: a research job's cards are not read."""
    from app.models import CopilotInvestigation
    found = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.status == "open", CopilotInvestigation.source == "copilot")
                    .order_by(col(CopilotInvestigation.updated_at).desc()).limit(MAX_INVESTIGATIONS)).all()
    rows = []
    for row in found:
        waiting = [card for message in json.loads(row.transcript_json) if message.get("role") == "assistant"
                   for card in message.get("proposals") or () if card.get("kind") in DRAFT_KINDS and not card.get("outcome")
                   and not (row.main_day and card.get("kind") == "trade_plan")]
        if waiting:
            rows.append({"id": str(row.id), "symbol": row.symbol or waiting[0].get("symbol"), "title": row.title,
                         "cards": [_card_text(card) for card in waiting], "updated_at": row.updated_at.isoformat() + "Z"})
    return {"state": "ok", "rows": rows}


def _draft_rows(drafts: dict, covered: set[str]) -> list[dict]:
    return [_row(f"draft:{r['id']}", "draft", r["title"], _say(r["cards"][0], "muted"), symbol=r["symbol"],
                 value=_say(f"{len(r['cards'])} to confirm", "attention"), investigation_id=r["id"],
                 changed_at=_epoch(r["updated_at"]))
            for r in drafts.get("rows", []) if r["id"] not in covered]


def _decisions(db: Session, day) -> dict:
    """Symbols with a ``decision`` day-journal entry today (the decision bar's log), newest time each, and the first
    ``reflection`` entry's text each (the close-of-day review). Read by the kinds' names, so a journal without them yet
    reads as none."""
    from app.engine import day_journal
    found, reflections = {}, {}
    for entry in day_journal.entries(db, day):
        if entry.kind == "decision" and entry.symbol:
            found[entry.symbol] = entry.created_at
        elif entry.kind == "reflection" and entry.symbol:
            reflections.setdefault(entry.symbol, entry.text)
    return {"state": "ok", "symbols": found, "reflections": reflections}


def _check_ins(db: Session) -> dict:
    from app.engine import day_journal
    horizons, asked = day_journal.check_ins(db)
    return {"state": "ok", "horizons": horizons, "asked": {symbol: (e.day, e.text) for symbol, e in asked.items()},
            "hidden": day_journal.not_following(db),
            "done": {symbol: at.replace(tzinfo=UTC).timestamp() for symbol, at in day_journal.done(db).items()}}


def _exits(db: Session, now: float) -> dict:
    from app.engine import copilot_plans
    since = datetime.fromtimestamp(now - EXIT_DAYS * 86400, UTC).replace(tzinfo=None)
    return {"state": "ok", "rows": [{**r, "newest": r["newest"].replace(tzinfo=UTC).timestamp()} for r in copilot_plans.exits(db, since)]}


def _done(db: Session, now: float) -> dict:
    from app.engine import copilot_plans
    since = datetime.fromtimestamp(now - EXIT_DAYS * 86400, UTC).replace(tzinfo=None)
    return {"state": "ok", "rows": copilot_plans.done(db, since)}


def _touched(db: Session, now: float, day) -> dict:
    """Symbols something happened to today: a phone ping judged (sent or held), a level alert fired, a fill."""
    from app.engine import day_replay, notification_policy as policy
    from app.models import LevelAlert, PhonePing
    start, end = policy.day_bounds(now)
    found = set(db.exec(select(PhonePing.symbol).where(PhonePing.decided_at >= start, PhonePing.decided_at < end)).all())
    found |= set(db.exec(select(LevelAlert.symbol).where(LevelAlert.fired_at >= start, LevelAlert.fired_at < end)).all())
    found |= set(day_replay.traded(db, day))
    found.discard(None)
    return {"state": "ok", "symbols": found}


def _opened(db: Session, trade_ids: list[str]) -> dict:
    """Each trade's New York opening day (the journal keeps ``opened_at`` in New York wall time)."""
    from app.models import Trade
    if not trade_ids:
        return {}
    return {str(t.id): t.opened_at.date() for t in db.exec(select(Trade).where(col(Trade.id).in_([uuid.UUID(i) for i in trade_ids]))).all()}


def _phase(now: float) -> dict:
    local = datetime.fromtimestamp(now, ET)
    minute = local.hour * 60 + local.minute
    phase = next((name for name, start, end in session_windows(local.date(), _hours(local.date())) if start <= minute < end), None)
    return {"state": "ok", "phase": phase or "closed"}


# --------------------------------------------------------------------------- rows

CLOSE_QUESTION = {"position": "Review: did you follow the plan?", "plan": "Added or not, and why?",
                  "plan_ask": "Want a plan for this?", "exit": "Did you follow the plan? One lesson?"}  # DecisionBar's
EXIT_DAYS = 7  # an exited plan asks its review for a week after the exit
REVIEW_WORDS = 6
DEFAULT_HORIZON = "swing"


def _after_close(now: float) -> bool:
    """After 16:00 New York on a weekday; holidays and early closes are not known here, as in the decision bar."""
    local = datetime.fromtimestamp(now, ET)
    return local.weekday() < 5 and local.hour >= 16


def _horizons(rows: list[dict], horizons: dict[str, str]) -> None:
    for row in rows:
        if row["symbol"] and (row["trade_id"] or row["key"].startswith("plan:")):
            row["horizon"] = horizons.get(row["symbol"], DEFAULT_HORIZON)


def _closing(rows: list[dict], reflections: dict[str, str], touched: set[str] | None, unplanned: dict[str, object],
             asked: dict[str, tuple], day) -> None:
    """The rows whose horizon asks today ask their close-of-day question, or say it was answered (in place).
    ``touched``: the symbols something happened to today (None when unknown: every swing asks); ``unplanned``: each
    position with no plan and the day it opened; ``asked``: each symbol's newest "Want a plan" answer (day, text)."""
    for row in rows:
        symbol, horizon = row["symbol"], row["horizon"]
        if horizon is None or horizon == "long" or row["close"] or row["hidden"]:  # an exited plan already asks its exit review
            continue
        if row["trade_id"] in unplanned:
            answer = asked.get(symbol)
            if answer and answer[0] >= unplanned[row["trade_id"]] and answer[0] != day:
                continue  # answered on an earlier day: it stays quiet
            text = answer[1] if answer and answer[0] == day else None
            kind = "plan_ask"
        else:
            text = reflections.get(symbol)
            if not text and horizon == "swing" and touched is not None and symbol not in touched:
                continue
            kind = "position" if row["trade_id"] or row["value"] == PLAN_STATE["in_position"] else "plan"
        words = text.split() if text else []
        reviewed = " ".join(words[:REVIEW_WORDS]) + ("…" if len(words) > REVIEW_WORDS else "") if text else None
        row["close"] = {"kind": kind, "question": CLOSE_QUESTION[kind], "reviewed": reviewed}
        row["status"] = _say(f"Reviewed · {reviewed}", "muted") if text else _say(CLOSE_QUESTION[kind], "attention")


def _instrument(contract: str, symbol: str, instrument: str) -> str:
    return "stock" if instrument == "stock" else contract.removeprefix(symbol).strip() or instrument


def _position_status(row: dict) -> dict:
    """A position not flagged for Act now: its plan's nearest line, or that it has none."""
    plan = row["plan"]
    if plan is None:
        return _say("Fill to link", "attention") if row["link_path"] else _say("No plan yet", "muted")
    where = f" ({row['symbol']})" if row["instrument"] == "option" else ""  # an option's levels are on the underlying
    level = plan.get("invalidation")
    if level and level["state"] == "armed" and "distance_pct" in level:
        return _say(f"Invalidation {level['price']:.2f}{where} · {abs(level['distance_pct']):.1f}% away", "muted")
    stop = plan.get("time_stop")
    if stop and stop["state"] == "pending":
        return _say(f"Time stop {stop['clock']}", "muted")
    if level:
        return _say(f"Invalidation {level['price']:.2f}{where}", "muted")
    return _say("On plan", "muted")


def _decided(row: dict, decided: dict) -> datetime | None:
    """When the symbol's decision was logged today, unless the plan's invalidation was hit after it (that needs a new one)."""
    at = decided.get(row["symbol"])
    level = (row["plan"] or {}).get("invalidation") or {}
    if at is not None and level.get("state") == "hit" and (level.get("hit_at") or 0) > at.replace(tzinfo=UTC).timestamp():
        return None
    return at


def _adopted_status(row: dict, adopted: dict, plan: dict | None) -> dict:
    """An adopted position not flagged for Act now: its draft, or its armed invalidation."""
    level = (plan or {}).get("invalidation")
    if adopted["state"] == "armed" and level:
        away = f" · {abs(level['distance_pct']):.1f}% away" if level.get("state") == "armed" and "distance_pct" in level else ""
        return _say(f"Adopted · invalidation {level['price']:.2f} ({row['symbol']}){away}", "muted")
    return _say("Adopted · draft plan to confirm", "info")


def _position_rows(found: dict, links: dict[str, str], board: dict, decided: dict,
                   adopted: dict[str, dict] | None = None) -> tuple[list[dict], list[dict], set[str]]:
    """(act rows, watch rows, investigation ids the rows cover). ``links``: each planned position's investigation;
    ``adopted``: each adopted position's thread (``_adopted``)."""
    plans = {p["investigation_id"]: p for p in board.get("plans", [])}
    act, watch, covered = [], [], set()
    for row in found["positions"]:
        trade_id, symbol = row["trade_id"], row["symbol"]
        companion = (adopted or {}).get(trade_id) if row["plan"] is None else None
        investigation = links.get(trade_id) or (companion["investigation_id"] if companion else None)
        if investigation:
            covered.add(investigation)
        plan = plans.get(investigation) if investigation else None
        pnl = row["unrealized_usd"]
        value = None if pnl is None else _say(_usd(pnl), "gain" if pnl > 0 else "loss" if pnl < 0 else "muted")
        common = {"symbol": symbol, "instrument": _instrument(row["contract"], symbol, row["instrument"]), "value": value,
                  "investigation_id": investigation, "trade_id": trade_id, "fill_to_link": trade_id if row["link_path"] else None,
                  "path": None if investigation else f"/copilot-lab?{urlencode({'symbol': symbol})}" if row["link_path"]
                  else row["plan_path"] or f"/trades/{trade_id}"}
        flagged = found["flagged"].get(trade_id)
        reasons = " · ".join(r["text"] for r in flagged["reasons"]) if flagged else None
        at = _decided(row, decided) if flagged else None
        if flagged and at is None:
            hit = any(r["kind"] == "invalidation_hit" for r in flagged["reasons"])
            tone = "loss" if hit else "attention"
            level = (row["plan"] or {}).get("invalidation") or (plan or {}).get("invalidation")
            track = meter(plan["entry"]["price"] if plan and plan["entry"] else None, level["price"] if level else None,
                          plan["last"] if plan else None, tone)
            act.append(_row(f"trade:{trade_id}", "act", row["contract"], _say(reasons, tone), meter=track, **common))
        elif flagged:
            clock = at.replace(tzinfo=UTC).astimezone(ET).strftime("%H:%M")
            watch.append(_row(f"trade:{trade_id}", "watch", row["contract"], _say(f"Decided {clock} · {reasons}", "muted"), **common))
        else:
            status = _adopted_status(row, companion, plan) if companion else _position_status(row)
            watch.append(_row(f"trade:{trade_id}", "watch", row["contract"], status, **common))
        (act if flagged and at is None else watch)[-1]["book"] = _book(row, plan, flagged)
        if companion:
            (act if flagged and at is None else watch)[-1]["adopted"] = True
    return act, watch, covered


BOOK_STATES = ("past_stop", "near_stop", "giving_back", "on_plan", "no_plan")  # the cockpit's one tag per row


def _book_state(kinds: set[str], planned: bool, gave_back: bool, usd: float | None) -> str:
    """The book row's one tag, true now (docs/copilot-lab.md § The book's tag), first match wins: ``past_stop`` (the
    plan's invalidation was hit), ``near_stop`` (within Act now's 1% of it), ``giving_back`` (still in profit now, and
    the give-back alert fired with no new high since), ``on_plan`` (an invalidation or time stop stands) or
    ``no_plan``. A position under its entry is never Giving back: it says how it stands against its plan, or No plan."""
    if "invalidation_hit" in kinds:
        return "past_stop"
    if "invalidation_near" in kinds:
        return "near_stop"
    if gave_back and usd is not None and usd > 0:
        return "giving_back"
    return "on_plan" if planned else "no_plan"


def _book(row: dict, plan: dict | None, flagged: dict | None) -> dict:
    """What the desk's book row shows beside the status line (docs/copilot-lab.md § The desk): the position's unrealized
    P&L in dollars and percent, its expiry and days held, where the underlying sits between the plan's invalidation and
    entry (``meter``; null without both lines), the distance to the invalidation, and one state (``_book_state``);
    ``planned`` says whether an invalidation or time stop stands (an adopted draft is not yet a plan), whatever the
    state. Facts only; nothing here is advice."""
    level = (row["plan"] or {}).get("invalidation") or (plan or {}).get("invalidation")
    entry = (plan or {}).get("entry")
    track = meter(entry["price"] if entry else None, level["price"] if level else None, (plan or {}).get("last"), "muted")
    kinds = {r["kind"] for r in (flagged or {}).get("reasons", [])}
    planned = bool(row["plan"]) and bool(level or (row["plan"] or {}).get("time_stop"))
    gave_back = bool(row.get("giveback_since_peak", row.get("giveback") == "fired"))
    return {"usd": row.get("unrealized_usd"), "pct": row.get("unrealized_pct"), "expiry": (row.get("option") or {}).get("expiry"),
            "days_held": row.get("days_held"), "track": track,
            "state": _book_state(kinds, planned, gave_back, row.get("unrealized_usd")), "planned": planned,
            "stop_pct": level.get("distance_pct") if level and level.get("state") == "armed" else None,
            # The plan's two exits on the underlying, for the closing ticket (``frontend/lib/closingTicket.ts``): the
            # invalidation (armed or hit) and the saved target; None without them.
            "plan_levels": {"stop": level.get("price") if level else None, "target": (plan or {}).get("target")},
            "tick": _tick(row), "option": _option_terms(row)}


def _option_terms(row: dict) -> dict | None:
    """What the desk's option standing (``frontend/lib/optionStanding.ts``) needs for a held option: the contract, side,
    quantity, the cost a contract (premium x 100) and the Greeks a share with where and when they came from. The
    journal's Greeks are the app's own option quote's (Tradier's hourly ORATS figures, read from the quote cache the
    positions' marks just filled; never a provider call); a Robinhood-matched row takes Robinhood's (``_live_terms``).
    None for a stock. A missing figure stays None, never zero."""
    option = row.get("option") or {}
    if row.get("instrument") != "option" or not option:
        return None
    from app.engine.quotes import OptionQuoteRequest, cached_option_quote
    greeks = None
    try:
        quote = cached_option_quote(OptionQuoteRequest(ticker=row["symbol"], expiration=option["expiry"],
                                                       strike=float(option["strike"]), option_type=option.get("side") or ""))
    except (KeyError, TypeError, ValueError):
        quote = None
    if quote is not None and any(v is not None for v in (quote.delta, quote.theta, quote.iv)):
        greeks = {"delta": quote.delta, "theta": quote.theta, "iv": quote.iv, "as_of": quote.iv_updated_at, "source": "tradier"}
    return {"side": option.get("side"), "strike": option.get("strike"), "expiry": option.get("expiry"),
            "direction": row.get("direction"), "quantity": row.get("quantity"), "multiplier": 100,
            "cost": row.get("avg_entry"), "greeks": greeks}


def _live_terms(live: dict, as_of: float | None) -> dict | None:
    """A Robinhood option's standing terms (``_option_terms``' shape) from the snapshot: its own cost, quantity and
    multiplier, and the Greeks its last read kept (``as_of`` is that read's epoch). None for a stock."""
    if live.get("instrument") != "option":
        return None
    raw = live.get("greeks") if isinstance(live.get("greeks"), dict) else {}
    greeks = {"delta": raw.get("delta"), "theta": raw.get("theta"), "iv": raw.get("iv"), "as_of": as_of, "source": "robinhood"}
    return {"side": live.get("side"), "strike": live.get("strike"), "expiry": live.get("expiry"), "direction": live.get("direction"),
            "quantity": live.get("quantity"), "multiplier": live.get("multiplier"), "cost": live.get("avg_cost"),
            "greeks": greeks if any(greeks[k] is not None for k in ("delta", "theta", "iv")) else None}


def _tick(row: dict) -> dict | None:
    """What the desk's live prices need to move this row's P&L in place, by the positions' own formula
    (``copilot_book.position_rows``): the symbol to quote (an option's OCC symbol), the units the cost is in (100 a
    contract), the cost, the quantity and the side. None when the P&L is not derived from a price the desk can quote."""
    from app.engine.occ import occ_symbol
    cost, quantity = row.get("avg_entry"), row.get("quantity")
    if not cost or not quantity:
        return None
    if row.get("instrument") == "option":
        option = row.get("option") or {}
        try:
            quote = occ_symbol(row["symbol"], datetime.fromisoformat(option["expiry"]).date(), option.get("side") or "", float(option["strike"]))
        except (KeyError, TypeError, ValueError):
            return None
        scale = 100
    elif row.get("instrument") == "stock":
        quote, scale = row["symbol"], 1
    else:
        return None
    if not quote:
        return None
    sign = -1 if row.get("direction") == "short" else 1
    # The journal's avg_entry is rounded to the cent; the cost that gives the row's own P&L at its own mark is not, so
    # the first tick at an unchanged price shows the same number.
    usd, mark = row.get("unrealized_usd"), row.get("mark")
    exact = round(mark - usd / (sign * quantity), 6) if usd is not None and mark else None
    return {"quote": quote, "scale": scale, "cost": exact if exact and exact > 0 else cost, "quantity": quantity, "sign": sign}


def _exit_rows(exits: list[dict]) -> list[dict]:
    """Exited plans, each asking its one exit review (whatever the hour)."""
    rows = []
    for r in exits:
        clock = datetime.fromtimestamp(_utc_epoch(r["exited_at"]), ET).strftime("%b %-d")
        row = _row(f"plan:{r['investigation_id']}", "watch", r["thesis"] or f"{r['symbol']} plan",
                   _say(CLOSE_QUESTION["exit"], "attention"), symbol=r["symbol"], value=_say(f"Exited {clock}", "muted"),
                   investigation_id=r["investigation_id"], changed_at=_utc_epoch(r["exited_at"]))
        row["close"] = {"kind": "exit", "question": CLOSE_QUESTION["exit"], "reviewed": None}
        rows.append(row)
    return rows


PLAN_STATE = {"waiting": _say("Armed", "muted"), "fill_to_link": _say("Fill to link", "attention"),
              "closed": _say("Closed", "muted"), "in_position": _say("In position", "info")}


def _near(plan: dict) -> tuple[str, dict] | None:
    """The Today screen's rule: the nearest armed entry or invalidation within ``NEAR_PCT``."""
    near = [(role, level) for role, level in (("entry", plan["entry"]), ("invalidation", plan["invalidation"]))
            if level and level["state"] == "armed" and "distance_pct" in level and abs(level["distance_pct"]) <= today.NEAR_PCT]
    return min(near, key=lambda pair: abs(pair[1]["distance_pct"])) if near else None


def _plan_rows(board: dict, covered: set[str], waiting: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(near rows, watch rows) for the armed plans no position row covers. ``waiting``: by symbol, an open trade with a fill
    to link (the first such position row)."""
    near_rows, watch = [], []
    for plan in board["plans"]:
        inv = plan["investigation_id"]
        if inv in covered:
            continue
        common = {"symbol": plan["symbol"], "instrument": plan["direction"], "value": PLAN_STATE.get(plan["position"]),
                  "investigation_id": inv,
                  "fill_to_link": waiting.get(plan["symbol"]) if plan["position"] == "fill_to_link" else None}
        title = plan["thesis"] or f"{plan['symbol']} plan"
        close = _near(plan)
        entry, invalidation = plan["entry"], plan["invalidation"]
        if close and plan["position"] != "in_position":
            role, level = close
            track = meter(entry["price"] if entry else None, invalidation["price"] if invalidation else None, plan["last"], "attention")
            near_rows.append(_row(f"plan:{inv}", "near", title,
                                  _say(f"{abs(level['distance_pct']):.1f}% to {role} {level['price']:.2f}", "attention"),
                                  meter=track, **common))
            continue
        armed = [(role, level) for role, level in (("Entry", entry), ("Invalidation", invalidation))
                 if level and level["state"] == "armed"]
        if armed:
            role, level = min(armed, key=lambda pair: abs(pair[1].get("distance_pct", 1e9)))
            away = f" · {abs(level['distance_pct']):.1f}% away" if "distance_pct" in level else ""
            status = _say(f"{role} {level['price']:.2f}{away}", "muted")
        elif plan["time_stop"] and plan["time_stop"]["state"] == "pending":
            due = datetime.fromtimestamp(plan["time_stop"]["due_at"], ET).strftime("%H:%M")
            status = _say(f"Time stop {due}", "muted")
        else:
            status = _say("Plan armed", "muted")
        watch.append(_row(f"plan:{inv}", "watch", title, status, **common))
    return near_rows, watch


def _r(plan: dict) -> float | None:
    """Where the underlying is in units of the plan's risk: 0 at the entry, -1 at the invalidation."""
    entry, invalidation, last = plan["entry"], plan["invalidation"], plan["last"]
    if not entry or not invalidation or last is None or entry["price"] == invalidation["price"]:
        return None
    return round((last - entry["price"]) / (entry["price"] - invalidation["price"]), 2)


def _plan_list(board: dict, exited: list[dict], done: list[dict], horizons: dict[str, str], lessons: dict[str, dict]) -> list[dict]:
    """The thread list's Plans view: every plan by stage (armed, in_position, exited, done), each with what its line
    needs. ``board`` holds the plans not yet exited or done; a plan whose fill waits to be linked is in position. An
    armed plan carries ``last_exit``, its symbol's newest answered exit review (``copilot_plans.last_exit_lessons``),
    for Arm today's plans."""
    def row(stage, symbol, investigation_id, instrument, thesis, **more):
        base = {"stage": stage, "symbol": symbol, "investigation_id": investigation_id, "instrument": instrument,
                "thesis": thesis, "horizon": horizons.get(symbol, DEFAULT_HORIZON), "last": None, "entry": None,
                "invalidation": None, "time_stop": None, "r": None, "at": None, "note": None, "last_exit": None}
        return {**base, **more}
    rows = []
    for p in board.get("plans", []):
        held = p["position"] in ("in_position", "fill_to_link")
        rows.append(row("in_position" if held else "armed", p["symbol"], p["investigation_id"], p["instrument"] or p["direction"],
                        p["thesis"], last=p["last"], entry=p["entry"], invalidation=p["invalidation"], time_stop=p["time_stop"],
                        r=_r(p) if held else None, note="Fill to link" if p["position"] == "fill_to_link" else None,
                        last_exit=None if held else lessons.get(p["symbol"])))
    rows += [row("exited", r["symbol"], r["investigation_id"], r["instrument"], r["thesis"], at=_utc_epoch(r["exited_at"]))
             for r in exited]
    rows += [row("done", r["symbol"], r["investigation_id"], r["instrument"], r["thesis"], at=_utc_epoch(r["done_at"]), note=r["text"])
             for r in done]
    return rows


def _exit_lessons(db: Session, plans: list[dict]) -> dict[str, dict]:
    from app.engine import copilot_plans
    armed = {p["symbol"] for p in plans if p["position"] not in ("in_position", "fill_to_link")}
    return copilot_plans.last_exit_lessons(db, armed) if armed else {}


def _investigation_of(path: str | None) -> str | None:
    found = parse_qs(urlparse(path or "").query).get("investigation")
    return found[0] if found else None


TRIGGER = {"news": "News", "move": "Move", "earnings": "Earnings"}


def _new_rows(radar: dict, thesis: dict, titles: dict[str, str]) -> list[dict]:
    rows = []
    for event in radar.get("rows", []):
        kind = RADAR_KIND.get(event["kind"], (event["kind"] or "event").replace("_", " "))
        # A stock hit opens on the desk, on its decision (watching, passing or planning); a group event stays on Radar.
        path = (f"/copilot-lab?{urlencode({'symbol': event['symbol'], 'radar': event['event_id']})}"
                if event["symbol"] and event["kind"] in ("relative_to_spy", "relative_to_sector", "dip_turn", "gap_reversal")
                else event["path"])
        rows.append(_row(f"radar:{event['event_id']}", "new", event["summary"] or kind, _say(f"Radar · {kind}", "info"),
                         symbol=event["symbol"] or None, radar_event_id=event["event_id"], path=path,
                         changed_at=_epoch(event["first_seen_at"])))
    seen = set()
    for trigger in thesis.get("rows", []):  # newest first: one row per investigation (or link), its newest trigger
        inv = _investigation_of(trigger["path"])
        key = f"thesis:{inv or trigger['path']}"
        if key in seen:
            continue
        seen.add(key)
        title = titles.get(inv) if inv else None
        rows.append(_row(key, "new", title or f"{trigger['symbol']} thesis", _say(f"{TRIGGER.get(trigger['kind'], 'Watch')} · {trigger['text']}", "info"),
                         symbol=trigger["symbol"], investigation_id=inv, path=None if inv else trigger["path"],
                         changed_at=_epoch(trigger["fired_at"])))
    rows.sort(key=lambda r: r["changed_at"] or 0, reverse=True)
    return rows


def _pinned(prep: dict, week: dict) -> list[dict]:
    lines = (prep.get("prep") or {}).get("lines") or []
    briefing = _say(f"Prep: {lines[0]}", "info") if lines else _say("What matters right now? One turn across everything", "muted")
    if week.get("state") == "ok" and week.get("show") and week.get("total"):
        review = _say(f"{week['planned']} of {week['total']} entries planned this week", "muted")
    else:
        review = _say("Planned vs unplanned, follow-through, exits", "muted")
    return [_row("briefing", "pinned", "Briefing", briefing),
            _row("week", "pinned", "Review my week", review)]


@router.get("/desk/threads")
def desk_threads(db: Session = Depends(get_session)):
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return threads(db, today._now())


def threads(db: Session, now: float) -> dict:
    """The thread list as ``GET /copilot/desk/threads`` returns it, read at ``now``."""
    day = datetime.fromtimestamp(now, ET).date()
    quotes = today.SharedQuotes()
    # The positions' marks and the Radar file wait on a provider or a file: they start first, beside the board's quote
    # read and the journal's sections. The positions read waits for its marks, then reads them from the quotes' cache.
    marks = _marks_ahead(db)
    radar_ahead = today._ahead("desk radar", lambda: today._radar(now))
    # The board first: its read covers every armed plan, so the positions' invalidations need no second read.
    board = today._section(db, "desk board", lambda: _board(db, quotes))
    if marks is not None:
        marks.get()
    found = today._section(db, "desk positions", lambda: _positions(db, quotes, now, day))
    investigations = today._section(db, "desk investigations", lambda: _investigations(db))
    drafts = today._section(db, "desk drafts", lambda: _drafts(db))
    decisions = today._section(db, "desk decisions", lambda: _decisions(db, day))
    checks = today._section(db, "desk check-ins", lambda: _check_ins(db))
    ended = today._section(db, "desk exits", lambda: _exits(db, now))
    finals = today._section(db, "desk done plans", lambda: _done(db, now))
    radar = radar_ahead.get()
    thesis = today._section(db, "desk thesis", lambda: today._thesis(db, day))
    prep = today._section(db, "desk prep", lambda: today._prep(db, day))
    week = today._section(db, "desk week", lambda: today._week(db, now))
    phase = today._section(db, "desk phase", lambda: _phase(now))

    # Done plans leave the list; exited ones not yet done ask their exit review instead of their plan row.
    done = checks.get("done", {})
    over = lambda symbol, at: symbol in done and done[symbol] >= at  # noqa: E731
    exited = [r for r in ended.get("rows", []) if not over(r["symbol"], r["newest"])]
    finished = {r["investigation_id"] for r in ended.get("rows", [])} | {
        p["investigation_id"] for p in board.get("plans", []) if over(p["symbol"], p["confirmed_at"])}
    if board["state"] == "ok":
        board = {**board, "plans": [p for p in board["plans"] if p["investigation_id"] not in finished]}
    # The armed plans' last exit lessons, on their own: a failure here leaves the Plans view without them.
    lessons = today._section(db, "desk exit lessons", lambda: {"state": "ok", "map": _exit_lessons(db, board.get("plans", []))})
    act, watch, covered = ([], [], set())
    if found["state"] == "ok":
        # Which investigation each planned position opens; on its own, so a failure here still lists the positions.
        links = today._section(db, "desk position plans", lambda: {"state": "ok", "map": _position_investigations(db, found)})
        adopted = today._section(db, "desk adopted", lambda: {"state": "ok", "map": _adopted(db)})
        act, watch, covered = _position_rows(found, links.get("map", {}), board if board["state"] == "ok" else {},
                                             decisions.get("symbols", {}), adopted.get("map", {}))
    near = []
    if board["state"] == "ok":
        waiting = {}
        for r in act + watch:
            if r["fill_to_link"]:
                waiting.setdefault(r["symbol"], r["fill_to_link"])
        near, plan_watch = _plan_rows(board, covered, waiting)
        watch += plan_watch
        covered |= {p["investigation_id"] for p in board["plans"]}
    watch = _exit_rows(exited) + watch  # first in Watching, ahead of the "+N more" cut
    covered |= finished
    draft = _draft_rows(drafts, covered)
    titles = {r["id"]: r["title"] for r in investigations.get("rows", [])}
    new = _new_rows(radar, thesis, titles)
    covered |= {r["investigation_id"] for r in draft + new if r["investigation_id"]}
    for r in investigations.get("rows", []):
        if r["id"] in covered or r["source"] == "copilot" and over(r["symbol"], _epoch(r["updated_at"]) or 0):
            continue
        status = _say(r["conclusion"], "muted") if r["conclusion"] else _say("Research" if r["source"] == "research_job" else "Open question", "muted")
        watch.append(_row(f"investigation:{r['id']}", "watch", r["title"], status, symbol=r["symbol"],
                          instrument="research" if r["source"] == "research_job" else None, investigation_id=r["id"],
                          changed_at=_epoch(r["updated_at"])))

    # The live book from Robinhood (docs/robinhood-read-feed.md): off, signed out or stale, the rows stay the journal's.
    live = today._section(db, "desk robinhood", lambda: _robinhood())
    if live.get("snapshot") is not None and found["state"] == "ok":
        joined = today._section(db, "desk robinhood join", lambda: {"state": "ok", "rows": _live_book(db, found, act + watch, live["snapshot"])})
        watch += joined.get("rows", [])
        live["view"]["joined"] = joined["state"] == "ok"
    _horizons(act + near + watch, checks.get("horizons", {}))
    hidden = checks.get("hidden", set())
    for row in act + near + draft + new + watch:
        row["hidden"] = bool(row["symbol"]) and row["symbol"] in hidden
    # Robinhood's working orders and today's fills, on their book rows; display only (no call, no write).
    if live.get("view", {}).get("joined"):
        lines = today._section(db, "desk robinhood orders", lambda: {"state": "ok", "rows": _order_lines(found, act + watch, now, hidden)})
        if lines.get("rows"):
            live["view"]["orders"] = lines["rows"]
    if _after_close(now):
        touched = today._section(db, "desk touched", lambda: _touched(db, now, day))
        happened = None
        if touched["state"] == "ok" and found["state"] == "ok":  # the decision bar asked (Act now) or was answered
            happened = touched["symbols"] | set(decisions.get("symbols", {})) | {
                p["symbol"] for p in found["positions"] if p["trade_id"] in found["flagged"]}
        unplanned = _opened(db, [p["trade_id"] for p in found.get("positions", []) if p["plan"] is None])
        _closing(act + near + watch, decisions.get("reflections", {}), happened, unplanned, checks.get("asked", {}), day)
    streak = {"current": week["current"], "best": week["best"]} if week["state"] == "ok" and week["show"] else None
    return {
        "as_of": today._iso(now), "quotes_at": quotes.at, "quote_issue": quotes.issue,
        "day": {"phase": phase.get("phase"), "need_you": sum(not r["hidden"] for r in act), "streak": streak},
        "threads": _pinned(prep, week) + act + near + draft + new + watch,
        "plans": _plan_list(board if board["state"] == "ok" else {}, exited, finals.get("rows", []), checks.get("horizons", {}),
                            lessons.get("map", {})),
        "robinhood": live.get("view") or {"state": "unavailable"},
        "sections": {name: part["state"] for name, part in (
            ("positions", found), ("plans", board), ("investigations", investigations), ("drafts", drafts),
            ("decisions", decisions), ("check_ins", checks), ("exits", ended), ("done", finals), ("radar", radar), ("thesis", thesis), ("prep", prep), ("week", week), ("phase", phase))},
    }


def warm_at_start() -> None:
    """At startup, in the background: the one read nearly every desk read needs that a fresh process lacks, the market
    calendar (its current month lives in memory only, so each start reads it again; the feed's news window also needs
    the previous session's close). At most the calls the first desk read would make; nothing while the lab is off. Never
    delays startup or ``/health``: it runs on its own thread, and a failure leaves the reads their usual fallback."""
    import threading
    if not copilot.settings().enabled:
        return

    def run():
        from app.engine import premarket_prep
        from app.engine.chart_calendar import chart_calendar
        try:
            day = datetime.now(ET).date()
            chart_calendar.hours(day)
            premarket_prep._previous_close(chart_calendar, day)
        except Exception as exc:  # noqa: BLE001 - a cold calendar is read again by the first desk read
            log.warning("desk warm-up skipped: %s", type(exc).__name__)
    threading.Thread(target=run, name="desk-warm", daemon=True).start()


def _marks_ahead(db: Session):
    """The open positions' quote reads (``copilot_book.mark_reads``) started on a worker; None when they could not be
    listed (the positions read then makes them itself, as before)."""
    from app.ai import copilot_book
    try:
        stocks, options = copilot_book.mark_reads(db)
    except Exception as exc:  # noqa: BLE001 - the positions section reads and reports the journal itself
        log.warning("desk marks ahead unavailable: %s", type(exc).__name__)
        db.rollback()
        return None
    return today._ahead("desk position marks", lambda: copilot_book.warm_marks(stocks, options)) if stocks or options else None


# --------------------------------------------------------------------------- the live book from Robinhood

def _robinhood() -> dict:
    from app.engine import robinhood_fills
    from app.engine.robinhood_book import feed, unsure_today
    view, snapshot = feed.snapshot()
    if snapshot is not None and view.get("accounts"):
        unsure_today(view["accounts"], snapshot, robinhood_fills.poller.filled())  # today's change unknown, never wrong
    return {"state": "ok", "view": view, "snapshot": snapshot}


def _live_book(db: Session, found: dict, rows: list[dict], snapshot: dict) -> list[dict]:
    """Joins the Robinhood snapshot onto the journal's position rows (in place) and returns a row for each position
    Robinhood shows that the journal does not have yet. A matched row keeps its plan, meter, state and thread; its P&L,
    quantity and mark come from Robinhood. Display only: nothing is written."""
    from app.engine import robinhood_book as rb
    from app.models import Account, Trade
    ids = [uuid.UUID(p["trade_id"]) for p in found["positions"]]
    last4 = {str(t): a for t, a in db.exec(select(Trade.id, Account.last4).join(Account, Account.id == Trade.account_id)
                                          .where(col(Trade.id).in_(ids))).all()} if ids else {}
    journal = [{"trade_id": p["trade_id"], "last4": last4.get(p["trade_id"]),
                "key": rb.contract_key(p["symbol"], p["instrument"], (p.get("option") or {}).get("side"),
                                       (p.get("option") or {}).get("strike"), (p.get("option") or {}).get("expiry"))}
               for p in found["positions"]]
    matched, missing, extra = rb.match(journal, snapshot)
    # The desk lists at most plan_positions.MAX_ROWS positions: one past that cut is still in the journal, not new.
    if found.get("count", 0) > len(found["positions"]):
        from app.ai.copilot_book import _not_webull
        held = {rb.contract_key(t.ticker, t.instrument_type, t.option_type, t.strike, t.expiration.isoformat() if t.expiration else None)
                for t in db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                                 .where(Trade.status == "open").where(_not_webull())).all()}
        extra = [p for p in extra if rb.contract_key(p["symbol"], p["instrument"], p["side"], p["strike"], p["expiry"]) not in held]
    by_key = {r["key"]: r for r in rows if r.get("book") is not None}

    as_of = snapshot.get("at")

    def facts(live: dict) -> dict:
        return {"usd": live["usd"], "pct": live["pct"], "quantity": live["quantity"], "mark": live["mark"],
                "account": rb.account_tag(live)}

    positions = {p["trade_id"]: p for p in found["positions"]}
    for trade_id, live in matched.items():
        row = by_key.get(f"trade:{trade_id}")
        if row is not None:
            terms = _live_terms(live, as_of)
            if terms is not None and terms["greeks"] is None:  # Robinhood gave no Greeks: the app's own quote's stand
                terms["greeks"] = (row["book"].get("option") or {}).get("greeks")
            row["book"] |= {**facts(live), "live": "matched", "option": terms or row["book"].get("option")}
            row["book"]["tick"] = _live_tick(row["book"].get("tick"), live)
            # Robinhood's P&L decides whether it is still in profit: the tag follows the live numbers too.
            if row["book"]["state"] not in ("past_stop", "near_stop"):
                held = positions.get(trade_id, {})
                gave_back = bool(held.get("giveback_since_peak", held.get("giveback") == "fired"))
                row["book"]["state"] = _book_state(set(), row["book"]["planned"], gave_back, live["usd"])
            row["value"] = None if live["usd"] is None else _say(_usd(live["usd"]), "gain" if live["usd"] > 0 else "loss" if live["usd"] < 0 else "muted")
    for trade_id in missing:
        row = by_key.get(f"trade:{trade_id}")
        if row is not None:
            row["book"]["live"] = "not_on_robinhood"
    new = []
    seen = _seen_on_robinhood(db) if extra else set()
    for live in extra:
        contract = rb.label(live)
        value = None if live["usd"] is None else _say(_usd(live["usd"]), "gain" if live["usd"] > 0 else "loss" if live["usd"] < 0 else "muted")
        pending = (live["last4"], rb.contract_key(live["symbol"], live["instrument"], live["side"], live["strike"], live["expiry"])) in seen
        note = "New · fill seen on Robinhood, email not in yet" if pending else "New · not in the journal yet"
        row = _row(f"robinhood:{rb.mask(live['last4'])}:{contract}", "watch", contract, _say(note, "info"),
                   symbol=live["symbol"], instrument=_instrument(contract, live["symbol"], live["instrument"]), value=value,
                   path=f"/copilot-lab?{urlencode({'symbol': live['symbol']})}")
        row["book"] = {"usd": live["usd"], "pct": live["pct"], "expiry": live["expiry"], "days_held": None, "track": None,
                       "state": "no_plan", "planned": False, "stop_pct": None, **facts(live), "live": "new",
                       "option": _live_terms(live, as_of)}
        new.append(row)
    return new


def day_accounts(hidden: set[str]) -> dict:
    """The day read's open P&L by account (``engine/day_read.py``): the Robinhood account line as the desk holds it (no call: the feed's snapshot without a refresh). An account
    holding a ticker he does not follow shows its open P&L from its followed positions only, and no change today."""
    from app.engine import robinhood_book as rb
    try:
        summary, snap = rb.feed.snapshot(kick=False)
    except Exception:  # noqa: BLE001 - the read stands without the account line
        log.warning("day read: the account line could not be read", exc_info=True)
        return {"state": "unavailable", "rows": []}
    if snap is None:
        return {"state": summary.get("state") or "unavailable", "rows": []}
    rows = []
    for a in snap["accounts"]:
        mine = [p for p in snap["positions"] if p.get("last4") == a["last4"]]
        if any(p.get("symbol") in hidden for p in mine):
            followed = [p.get("usd") for p in mine if p.get("symbol") not in hidden]
            rows.append({"account": a["label"], "open_pnl": round(sum(followed), 2) if None not in followed else None,
                         "day_change": None, "followed_only": True})
        else:
            rows.append({"account": a["label"], "open_pnl": a.get("open_pnl"), "day_change": a.get("day_change"), "followed_only": False})
    return {"state": "ok", "as_of": snap["at"], "rows": rows}


def day_provisional(now: float, hidden: set[str]) -> list[dict]:
    """The day read's provisional fills: today's Robinhood fills the journal does not have yet (the order-history pass's lines in memory, no call)."""
    from app.engine import robinhood_book as rb
    from app.engine import robinhood_fills
    try:
        lines = robinhood_fills.poller.desk(now) or []
    except Exception:  # noqa: BLE001
        log.warning("day read: Robinhood order lines unreadable", exc_info=True)
        return []
    out = []
    for o in lines:
        if o["filled"] <= 0 or o["filled_at"] is None or o["symbol"] in hidden or o.get("pairing") not in (None, "provisional"):
            continue
        contract = rb.label({"symbol": o["symbol"], "instrument": o["instrument"], "side": o["option_type"], "strike": o["strike"],
                             "expiry": o["expiry"]})
        out.append({"contract": contract, "action": robinhood_fills.OPTION_ACTIONS.get(o["action"], o["action"]),
                    "filled": o["filled"], "avg": o["avg"], "at": o["filled_at"], "account": o["account"]})
    return out


def _order_lines(found: dict, rows: list[dict], now: float, hidden: set[str] = frozenset()) -> list[dict]:
    """Robinhood's orders on the book (``robinhood_fills.Poller.desk``: the order-history pass's last good read, held in
    memory): each working order, and each order with a fill today, goes on its contract's followed book row
    (``book.orders``), in its own account first, else on a row no account is known for. The rest are returned for the
    book's small "Orders" group (a contract with no position yet, or one the fill closed). A ticker set to Not following
    stays hidden here too. Nothing when that pass is off or its read is stale. Display only: no Robinhood call, no write, and no Robinhood id leaves the server."""
    from app.engine import robinhood_book as rb
    from app.engine import robinhood_fills
    orders = [o for o in robinhood_fills.poller.desk(now) or [] if o["symbol"] not in hidden]
    if not orders:
        return []
    keys = {}
    for p in found["positions"]:
        option = p.get("option") or {}
        keys[f"trade:{p['trade_id']}"] = rb.contract_key(p["symbol"], p["instrument"], option.get("side"), option.get("strike"), option.get("expiry"))
    book = [r for r in rows if r.get("book") is not None]
    spare = []
    orders.sort(key=lambda o: (not o["working"], -(o["filled_at"] or o["placed_at"] or 0)))
    for o in orders:
        live = {"symbol": o["symbol"], "instrument": o["instrument"], "side": o["option_type"], "strike": o["strike"], "expiry": o["expiry"]}
        key = rb.contract_key(o["symbol"], o["instrument"], o["option_type"], o["strike"], o["expiry"])
        masked, contract = rb.mask(o["last4"]), rb.label(live)
        same = [r for r in book if key is not None and keys.get(r["key"]) == key or r["key"] == f"robinhood:{masked}:{contract}"]
        pick = next((r for r in same if (r["book"].get("account") or {}).get("masked") == masked), None) \
            or next((r for r in same if not r["book"].get("account")), None)
        line = {"contract": contract, "symbol": o["symbol"], "instrument": o["instrument"],
                "action": robinhood_fills.OPTION_ACTIONS.get(o["action"], o["action"]), "working": o["working"],
                "quantity": o["quantity"], "filled": o["filled"], "price_kind": o["price_kind"], "limit": o["limit"],
                "avg": o["avg"], "placed_at": o["placed_at"], "filled_at": o["filled_at"],
                "account": {"label": o["account"], "masked": masked}, "pairing": o.get("pairing") if o["filled"] else None}
        if pick is not None:
            pick["book"].setdefault("orders", []).append(line)
        else:
            spare.append(line)
    return spare


def _live_tick(tick: dict | None, live: dict) -> dict | None:
    """A Robinhood-matched row ticks from Robinhood's own numbers: its quantity, and the cost that gives its P&L at its
    mark (so the first tick does not jump to the journal's cost). None when Robinhood's numbers cannot give one."""
    usd, mark, quantity = live.get("usd"), live.get("mark"), live.get("quantity")
    if tick is None or usd is None or not mark or not quantity:
        return None
    return {**tick, "cost": round(mark - usd / (tick["sign"] * quantity), 4), "quantity": quantity}


def _seen_on_robinhood(db: Session) -> set[tuple]:
    """Buys Robinhood's order history recorded today whose fill is not in the journal yet (docs/robinhood-order-fills.md);
    empty while that switch is off."""
    from app.engine import robinhood_fills
    try:
        return robinhood_fills.provisional(db, datetime.now(ET).replace(tzinfo=None))
    except Exception as exc:  # noqa: BLE001 - the marker falls back to its plain wording
        log.warning("order-history marker unavailable: %s", type(exc).__name__)
        db.rollback()
        return set()


# --------------------------------------------------------------------------- the Briefing's session timeline

INDICES = ("SPY", "QQQ", "VIX")  # VIX through the chart feed's index mapping (chart_indices)
MAX_EVENTS = 80
TO_ANSWER_ROWS = 20  # each answer list: today's, then the newest still waiting


def _utc_epoch(moment: datetime) -> int:
    return int(moment.replace(tzinfo=UTC).timestamp())


def _clock(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, ET).strftime("%H:%M")


def _regular(day) -> dict:
    """Today's regular session as epoch seconds (an early close is the calendar's); none on a closed day."""
    window = next(((start, end) for name, start, end in session_windows(day, _hours(day)) if name == "regular"), None)
    if window is None:
        return {"state": "ok", "open": None, "close": None}
    at = [int(datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET).timestamp()) for minute in window]
    return {"state": "ok", "open": at[0], "close": at[1]}


def _fill_events(db: Session, day) -> dict:
    from app.engine import day_replay
    rows = [{"kind": "fill", "at": f.time, "symbol": symbol, "text": f"{'Bought' if f.buy else 'Sold'} {symbol}"}
            for symbol, fills in day_replay.traded(db, day).items() for f in fills]
    return {"state": "ok", "rows": rows}


def _ping_events(db: Session, now: float) -> dict:
    """Phone pings the notification policy sent today, and its day count (held ones count apart)."""
    from app.engine import notification_policy as policy
    from app.models import PhonePing
    start, end = policy.day_bounds(now)
    found = db.exec(select(PhonePing).where(PhonePing.decided_at >= start, PhonePing.decided_at < end)).all()
    sent = [p for p in found if p.decision == "sent"]
    rows = [{"kind": "ping", "at": _utc_epoch(p.decided_at), "symbol": p.symbol,
             "text": f"{policy._label(p.kind).capitalize()} ping{f' · {p.symbol}' if p.symbol else ''}"} for p in sent]
    return {"state": "ok", "rows": rows, "sent": len(sent), "held": sum(p.decision in policy.HELD for p in found), "cap": None}


def _radar_events(day) -> dict:
    from app.routers import radar
    store, _reason = radar._store(read_only=True)
    if store is None:
        return {"state": "off", "rows": []}
    rows = []
    for event in store.events(day.isoformat()):
        at = _epoch(event.get("first_seen_at"))
        symbol = (event.get("symbols") or [None])[0]
        if at is not None:
            rows.append({"kind": "radar", "at": at, "symbol": symbol, "text": f"Radar · {symbol or 'event'} {RADAR_KIND.get(event.get('kind'), '')}".strip()})
    return {"state": "ok", "rows": rows}


def _decision_events(db: Session, day) -> dict:
    from app.engine import day_journal
    rows = [{"kind": "decision", "at": _utc_epoch(e.created_at), "symbol": e.symbol, "text": f"{e.symbol} · {e.text.split('.', 1)[0][:40]}"}
            for e in day_journal.entries(db, day) if e.kind == "decision" and e.symbol]
    return {"state": "ok", "rows": rows}


def _time_stops(db: Session, now: float) -> dict:
    """Plan time stops still scheduled for today, soonest first."""
    from app.engine import notification_policy as policy
    from app.models import PlanTimeStop
    start, end = policy.day_bounds(now)
    found = db.exec(select(PlanTimeStop).where(PlanTimeStop.delivery == "scheduled", PlanTimeStop.due_at >= start,
                                               PlanTimeStop.due_at < end).order_by(PlanTimeStop.due_at)).all()
    return {"state": "ok", "rows": [{"symbol": r.symbol, "at": _utc_epoch(r.due_at), "clock": _clock(_utc_epoch(r.due_at))} for r in found]}


def _alert_trades(db: Session, alerts: list) -> dict:
    """Each alert's current trade, by its position's identity (``position_alerts.anchor``: the first entry fill's source
    key), the one the feedback route binds it to; the stored ``trade_id`` may predate a rebuild."""
    from app.models import Fill, TradeFill
    keys = {a.source_key for a in alerts}
    if not keys:
        return {}
    ids = []
    for key in keys:
        try:
            ids.append(uuid.UUID(key))
        except ValueError:
            pass  # a source id, not a fill id
    found = db.exec(select(TradeFill.trade_id, Fill.account_id, Fill.raw_email_id, Fill.id).join(Fill, Fill.id == TradeFill.fill_id)
                    .where(TradeFill.role == "entry", or_(col(Fill.raw_email_id).in_(keys), col(Fill.id).in_(ids)))).all()
    return {(account, key): str(trade_id) for trade_id, account, email, fill in found for key in (email, str(fill)) if key in keys}


def _alerts_to_answer(db: Session, now: float) -> dict:
    """Position alerts for the owner's feedback, in /proof's scope (``exit_habits.build``): ``count`` is every sent or
    delivery-unconfirmed alert with no feedback yet. ``rows`` are today's (answered or not), then the newest still
    unanswered, each with the trade its feedback is saved against; one whose position is no longer in the journal is left out."""
    from app.engine import alert_feedback, notification_policy as policy
    from app.models import PositionAlert
    alerts = db.exec(select(PositionAlert).where(col(PositionAlert.delivery).in_(alert_feedback.ELIGIBLE_DELIVERIES))
                     .order_by(col(PositionAlert.detected_at).desc())).all()
    feedback = alert_feedback.for_alerts(db, [a.id for a in alerts])
    start, _end = policy.day_bounds(now)
    shown = [a for a in alerts if a.detected_at >= start or a.id not in feedback][:TO_ANSWER_ROWS]
    trades = _alert_trades(db, shown)
    rows = [{"id": str(a.id), "trade_id": trades[(a.account_id, a.source_key)], "symbol": (a.contract or "").split(" ")[0],
             "contract": a.contract, "kind": a.kind, "at": _utc_epoch(a.detected_at), "today": a.detected_at >= start,
             "feedback": feedback.get(a.id)} for a in shown if (a.account_id, a.source_key) in trades]
    return {"state": "ok", "count": len(alerts) - len(feedback), "rows": rows}


def _hits_to_rate(day) -> dict:
    """Radar events for the owner's rating, in /proof's scope (``radar_proof.build``): ``count`` is the events of the newest
    rule version not rated yet. ``rows`` are today's (rated or not), then the newest still unrated."""
    from app.routers import radar
    store, _reason = radar._store(read_only=True)
    if store is None:
        return {"state": "off"}
    events = sorted((e for e in store.events() if rule_side(e) is None), key=lambda e: _epoch(e.get("first_seen_at")) or 0, reverse=True)
    version = events[0]["rule_version"] if events else None
    events = [e for e in events if e["rule_version"] == version]
    rated = store.latest_ratings()
    session = day.isoformat()
    shown = [e for e in events if e["session_date"] == session or e["event_id"] not in rated][:TO_ANSWER_ROWS]
    rows = [{"event_id": e["event_id"], "symbol": (e.get("symbols") or [None])[0], "kind": RADAR_KIND.get(e.get("kind"), ""),
             "at": _epoch(e.get("first_seen_at")), "today": e["session_date"] == session, "rating": rated.get(e["event_id"])} for e in shown]
    return {"state": "ok", "count": sum(e["event_id"] not in rated for e in events), "rows": rows}


def _indices(now: float) -> dict:
    from app.ai import copilot_extended
    from app.engine.chart_feed import chart_feed
    rows, _at, issue = chart_feed.quote_rows(list(INDICES))
    found = {r["symbol"]: r for r in rows}
    moment = datetime.fromtimestamp(now, ET)
    premarket = copilot_extended.phase(moment) == "pre-market"

    def change(symbol: str) -> float | None:
        row = found[symbol]
        if not premarket or symbol == "VIX":
            return row.get("change_percentage")
        # Tradier's quote carries no premarket trade, so its change reads 0.00% until the open. The Charts tab's own
        # minutes give the last premarket trade against the previous close; none yet, or no read, is a dash, not a zero.
        return _premarket_change(symbol, row.get("previous_close"), moment)

    return {"state": "ok", "issue": issue, "rows": [
        {"symbol": s, "last": found[s].get("last"), "change_pct": change(s)} for s in INDICES if s in found]}


def _premarket_change(symbol: str, reference: float | None, moment: datetime) -> float | None:
    from app.ai import copilot_extended
    from app.engine.chart_feed import ChartFeedError
    day = moment.date()
    try:
        bars = copilot_extended._part(copilot_extended._bars(symbol, day, moment), day, "pre")
    except ChartFeedError:
        return None
    return copilot_extended.summary(bars, reference, range_=False).get("change_pct")


@router.get("/desk/minute")
async def desk_minute(request: Request):
    """The desk's once-a-minute re-reads in one request (``app/engine/desk_minute.py``): ``read`` names each one (a path
    with its query, at most ``MAX_READS``, only the desk's own minute reads), each answered as its own route would
    answer this browser, in order. Read-only, owner-only, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_minute as minute
    targets = request.query_params.getlist("read")
    if not targets or len(targets) > minute.MAX_READS:
        raise HTTPException(400, f"Name 1 to {minute.MAX_READS} reads.")
    return {"reads": await minute.read_all(request.app, request.scope, targets)}


@router.get("/desk/timings")
def desk_timings(limit: int = 10):
    """Where the desk's server time goes (``app/engine/request_timing.py``, docs/copilot-lab.md § Where the wait goes):
    per route, p50/p90/max of the last timings kept since the backend started, p50/p90 of each section, and the newest
    ``limit`` timings (``first``: the route's first request since the start, the cold one). Section names and
    milliseconds only. Owner-only; answers while the lab is off, so a slow start can still be read."""
    from app.engine import day_read, desk_read, request_timing
    return {**request_timing.summary(max(0, min(limit, request_timing.KEEP))), "desk_reads": desk_read.today(),
            "day_reads": day_read.today()}


class ReadAsk(BaseModel):
    symbol: str = PydField(min_length=1, max_length=12)
    refresh: bool = False
    kept_only: bool = False  # confirm a read the panel already shows; never starts a turn


@router.post("/desk/read")
async def desk_read_route(body: ReadAsk):
    """The desk's few-line read of a selected ticker (``app/engine/desk_read.py``): kept per ticker for 30 minutes in the
    regular session (longer outside it), refused when the day's copilot budget has no room for one, never for a ticker
    he does not follow. Each read is a ``copilot_turn`` row on the shared daily budget; ``today`` is the day's count and
    cost. Owner-only; refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_read
    return await desk_read.read(body.symbol, refresh=body.refresh, kept_only=body.kept_only)


class DayReadAsk(BaseModel):
    refresh: bool = False  # his tap: the only way a second read runs on one day


@router.post("/desk/day-read")
async def desk_day_read_route(body: DayReadAsk):
    """The copilot's read of the owner's day after the close (``app/engine/day_read.py``): four to six lines written once
    a day from the day report's facts, kept for the day; one line and no call on a day with no fills and no plans;
    refused when the day's copilot budget has no room. A ``copilot_turn`` row (``kind="day_read"``) on the shared daily
    budget; ``today`` is the day's count and cost. Owner-only; refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import day_read
    return await day_read.read(refresh=body.refresh)


@router.post("/desk/robinhood/refresh")
def desk_robinhood_refresh():
    """Reads Robinhood now (docs/robinhood-read-feed.md): parameterless, at most once every 15 seconds, one read at a
    time; returns the feed's state and account line. Owner-only, refused while the lab is off; nothing is written."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine.robinhood_book import feed
    return feed.refresh(force=True)


@router.get("/desk/session")
def desk_session(db: Session = Depends(get_session)):
    """The Briefing's day at a glance (docs/copilot-lab.md § The desk): today's regular session, what happened in it
    (fills, phone pings sent, Radar events, logged decisions), the time stops still ahead, the pings against the daily
    cap, the pre-market prep and SPY/QQQ/VIX, and under ``to_answer`` the position alerts and Radar hits still waiting
    on the owner's answer for /proof. Composed from readers that already exist; each source fails on its own.
    Read-only, owner-only, refused while the lab is off. The only ids out are the ``to_answer`` rows' alert, trade and
    Radar event ids, each the target of its own answer."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    now = today._now()
    day = datetime.fromtimestamp(now, ET).date()
    # The index quotes and the Radar file's reads wait on a provider or a file, not the journal: they start first and
    # run beside the journal's sections, so the slowest holds none of the rest.
    indices_ahead = today._ahead("session indices", lambda: _indices(now))
    radar_ahead = today._ahead("session radar", lambda: _radar_events(day))
    hits_ahead = today._ahead("session radar to rate", lambda: _hits_to_rate(day))
    regular = today._section(db, "session hours", lambda: _regular(day))
    phase = today._section(db, "session phase", lambda: _phase(now))
    fills = today._section(db, "session fills", lambda: _fill_events(db, day))
    pings = today._section(db, "session pings", lambda: _ping_events(db, now))
    decisions = today._section(db, "session decisions", lambda: _decision_events(db, day))
    stops = today._section(db, "session time stops", lambda: _time_stops(db, now))
    prep = today._section(db, "session prep", lambda: today._prep(db, day))
    alerts_due = today._section(db, "session alerts to answer", lambda: _alerts_to_answer(db, now))
    realized = today._section(db, "session realized", lambda: _realized_today(db, day))
    indices, radar, hits_due = indices_ahead.get(), radar_ahead.get(), hits_ahead.get()
    from app.engine import day_journal
    try:
        hidden = day_journal.not_following(db)  # a ticker he does not follow is in no event (Since you looked counts these)
    except Exception:  # noqa: BLE001 - the events are counts; an unread setting leaves them as they are
        hidden = set()
    events = sorted((row for part in (fills, pings, radar, decisions) for row in part.get("rows", [])
                     if row.get("symbol") not in hidden), key=lambda r: r["at"])
    written = (prep.get("prep") or {})
    return {
        "as_of": today._iso(now), "now": int(now), "day": day.isoformat(), "phase": phase.get("phase"),
        "open": regular.get("open"), "close": regular.get("close"),
        "events": events[-MAX_EVENTS:], "time_stops": stops.get("rows", []),
        "pings": {k: pings[k] for k in ("sent", "held", "cap")} if pings["state"] == "ok" else None,
        # The whole brief (its saved lines) and its thread, so Main chat can open the day on it.
        "prep": {"at": _epoch(written.get("at")), "line": (written.get("lines") or [None])[0], "lines": written.get("lines") or [],
                 "fallback": bool(written.get("fallback")), "path": written.get("path")} if written else None,
        "indices": indices.get("rows", []), "quote_issue": indices.get("issue"),
        "realized_today": realized.get("usd") if realized["state"] == "ok" else None,
        "to_answer": {name: {"count": part["count"], "rows": part["rows"]} if part["state"] == "ok" else None
                      for name, part in (("alerts", alerts_due), ("radar", hits_due))},
        "sections": {name: part["state"] for name, part in (
            ("hours", regular), ("phase", phase), ("fills", fills), ("pings", pings), ("radar", radar),
            ("decisions", decisions), ("time_stops", stops), ("prep", prep), ("indices", indices),
            ("alerts_to_answer", alerts_due), ("radar_to_rate", hits_due), ("realized", realized))},
    }


def _realized_today(db: Session, day) -> dict:
    """Realized P&L of the trades closed on ``day`` (New York; ``closed_at`` is a New York wall clock, as the dashboard's
    today_pnl reads it), Webull left out like the rest of the desk."""
    from app.ai.copilot_book import _not_webull
    from app.models import Account, Trade
    start = datetime(day.year, day.month, day.day)
    found = db.exec(select(Trade.realized_pnl).join(Account, Account.id == Trade.account_id).where(_not_webull())
                    .where(Trade.closed_at >= start, Trade.closed_at < start + timedelta(days=1))
                    .where(col(Trade.realized_pnl).is_not(None))).all()
    return {"state": "ok", "usd": round(sum(float(v) for v in found), 2)}


@router.get("/desk/sparks")
def desk_sparks(symbols: str = "", watch: str = ""):
    """Each named symbol's day so far for the desk's book rows: today's minute closes (the regular session once it has
    bars, before that the pre-market), thinned to 48, and its change today against the previous close with SPY's beside
    it. Built from what the app already has before it asks a provider (``app/engine/desk_sparks.py``: Radar's recorder,
    the chart feed's cache, one batched read, then low-priority reads); a symbol whose read fails or runs past the 6 s
    budget is left out. ``watch``: the Watching list's symbols, each with its last price and change from the same quote
    read and a line only from the sources that make no call of its own (the recorder, a chart's cache, the batched read).
    Read-only, owner-only, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_sparks as sparks
    return sparks.read(symbols, today._now(), watch=watch)


@router.get("/desk/moving")
def desk_moving(db: Session = Depends(get_session)):
    """The desk's "what's moving" strip (``app/engine/desk_moving.py``): SPY/QQQ/IWM, the sector ETFs and his own groups
    (the Watching list, the Research tab's groups) as day changes, then the biggest movers among his names and Radar's
    recorded ones, each with a reason only when the app already has one. Radar's recorder first, then one batched quote
    read; kept 45 seconds. Outside the session it is the last session's close (``mode: close``); with nothing to show,
    ``state: unavailable``, never zeros. A ticker set to Not following is never in it. Read-only, owner-only, refused
    while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_moving
    return desk_moving.build(db, today._now())


@router.get("/desk/ticks")
def desk_ticks(symbols: str = ""):
    """Live prices for the desk (``app/engine/desk_ticks.py``): each named underlying's last price and change today and a
    held contract's mark (OCC symbols), from one batched quote read kept a few seconds and shared by every open desk.
    Regular session only: outside it no provider is asked and the answer is ``closed`` with the next open today. Read-only,
    owner-only, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_ticks
    return desk_ticks.read(symbols, today._now())


@router.get("/desk/contract")
def desk_contract(symbol: str = "", occ: str = "", db: Session = Depends(get_session)):
    """A held option's own price for the desk chart's Contract view (``app/engine/desk_contract.py``): the contract's
    latest session of trades as 2-minute candles (one cached chart-feed read), today's recorded marks, the stock's price
    per slot and the owner's journal fills on it. A ticker set to Not following is never read. Read-only, owner-only,
    no Robinhood call, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import day_journal, desk_contract
    hidden = today._section(db, "desk contract hidden", lambda: {"rows": sorted(day_journal.not_following(db))})
    if hidden.get("state") == "unavailable" or symbol.strip().upper() in set(hidden.get("rows", [])):
        return {"state": "none", "symbol": symbol.strip().upper(), "reason": None}  # silent: never a hidden ticker's contract
    return desk_contract.read(db, symbol, occ, today._now())


@router.get("/desk/walls")
def desk_walls(symbol: str = "", expiration: date | None = None, db: Session = Depends(get_session)):
    """The Charts strike ladder's dealer-positioning read for the desk (``app/engine/desk_walls.py``): put wall, call
    wall, gamma flip, max pain and the expected move for the nearest expiry (or ``expiration``), from the same
    ``options_feed.ladder`` call and chain cache as Charts. The dealer side is assumed and said so. A ticker set to Not
    following is never read. Read-only, owner-only, no Robinhood call, refused while the lab is off."""
    found = copilot.settings()
    if not found.enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import day_journal, desk_walls as walls
    hidden = today._section(db, "desk walls hidden", lambda: {"rows": sorted(day_journal.not_following(db))})
    if hidden.get("state") == "unavailable" or symbol.strip().upper() in set(hidden.get("rows", [])):
        return {"state": "none", "symbol": symbol.strip().upper(), "levels": [], "expected_move": None,
                "message": None, "refresh_seconds": walls.REFRESH_SECONDS}  # silent: never a hidden ticker's walls
    return walls.read(symbol, expiration, mode=getattr(found, "evidence", "live"), now=today._now())


@router.get("/desk/events")
def desk_events(symbols: str = "", held: str = "", db: Session = Depends(get_session)):
    """Earnings tags for the book's and the Watching list's rows (``app/engine/desk_events.py``): each named symbol's next
    report from the earnings cache (12 hours; stale ones refresh in one batched background read, so ``loading`` says to
    read again), tagged grey within 7 trading days and amber when a held option (``held``: ``SYMBOL:YYYY-MM-DD`` pairs)
    expires on or after it. A symbol with no known date, a fund and a ticker set to Not following get no row. Read-only,
    owner-only, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import day_journal, desk_events as events
    day = datetime.fromtimestamp(today._now(), ET).date()
    hidden = today._section(db, "desk events hidden", lambda: {"rows": sorted(day_journal.not_following(db))})
    if hidden.get("state") == "unavailable":
        return {"state": "unavailable", "today": day.isoformat(), "rows": {}, "loading": False}  # never a hidden ticker's tag
    return events.tags(symbols.split(","), events.parse_held(held), day, set(hidden.get("rows", [])))


@router.get("/desk/grid")
def desk_grid(symbols: str = "", timeframe: str = "1m", db: Session = Depends(get_session)):
    """The centre's Grid (``app/engine/desk_grid.py``): up to nine small intraday charts in one read: each named
    symbol's session on 1-minute or 5-minute candles after the previous session's last half hour, with today's VWAP and
    its armed plan and alert levels. Cached minutes first (the grid's own, then any chart's), then one batched Alpaca
    read, then the chart feed's low-priority reads within its budget. A ticker set to Not following is never read.
    Read-only, owner-only, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import day_journal, desk_grid
    hidden = today._section(db, "desk grid hidden", lambda: {"rows": sorted(day_journal.not_following(db))})
    if hidden.get("state") == "unavailable":
        return {"state": "unavailable", "rows": {}}  # never a hidden ticker's tile
    names = desk_grid.names(symbols, set(hidden.get("rows", [])))
    levels = today._section(db, "desk grid levels", lambda: {"rows": desk_grid.plan_levels(db, names)})
    return {"state": "ok", **desk_grid.read(names, timeframe, today._now(), levels.get("rows") or {})}


# --------------------------------------------------------------------------- the Watching list (app/engine/desk_watch.py)

class WatchAdd(BaseModel):
    symbol: str = PydField(max_length=16)


class WatchImport(BaseModel):
    lists: list[str] = PydField(default_factory=list, max_length=50)


def _watching(db: Session, now: float) -> dict:
    from app.engine import desk_watch
    try:
        return desk_watch.view(db, datetime.fromtimestamp(now, ET).date())
    except Exception as exc:  # noqa: BLE001 - never a list that might show a hidden ticker
        log.warning("desk watching unavailable: %s", type(exc).__name__)
        db.rollback()
        return {"state": "unavailable", "symbols": [], "levels": {}, "setups": {}}


@router.get("/desk/watching")
def desk_watching(db: Session = Depends(get_session)):
    """The Watching list under the book: the watched symbols he follows, their armed levels and today's Radar setup
    cards, and the Robinhood connection's state for the import. Database reads only; prices come from the sparks read."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return _watching(db, today._now())


@router.post("/desk/watching")
def desk_watch_add(body: WatchAdd, db: Session = Depends(get_session)):
    """Watch a symbol by hand: it must be a ticker the app knows (Radar's universe, his traded tickers, else one quote
    read that returns a price). Written to the app's watchlist (the Charts one), never to Robinhood."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_watch
    symbol = body.symbol.strip().upper().lstrip("$")
    if not desk_watch.SYMBOL.fullmatch(symbol):
        raise HTTPException(422, f"{symbol[:16] or 'That'} is not a ticker.")
    found = desk_watch.known(db, symbol)
    if found is None:
        raise HTTPException(503, f"Could not check {symbol} just now. Try again in a minute.")
    if not found:
        raise HTTPException(422, f"{symbol} is not a symbol the app knows.")
    try:
        desk_watch.add(db, symbol)
    except desk_watch.Full as exc:
        raise HTTPException(409, str(exc)) from None
    return _watching(db, today._now())


@router.delete("/desk/watching/{symbol}")
def desk_watch_remove(symbol: str, db: Session = Depends(get_session)):
    """Stop watching: out of the app's watchlist and remembered, so a later Robinhood sync does not bring it back."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_watch
    symbol = symbol.strip().upper()
    if not desk_watch.SYMBOL.fullmatch(symbol):
        raise HTTPException(422, "Not a ticker.")
    desk_watch.remove(db, symbol)
    return _watching(db, today._now())


@router.get("/desk/watching/robinhood")
def desk_watch_lists(db: Session = Depends(get_session)):
    """His own Robinhood watchlists by name and size, for the import to offer (one read, on his tap). Off, signed out or
    expired: the state, no call."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_watch
    return desk_watch.robinhood_lists(db)


@router.post("/desk/watching/robinhood")
def desk_watch_import(body: WatchImport, db: Session = Depends(get_session)):
    """Bring in the stocks and ETFs of the lists he chose (his own lists only; the rest are refused by a fresh read of his
    lists). Only reads Robinhood; never writes to his lists. One import at a time."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_watch
    try:
        result = desk_watch.import_lists(db, body.lists)
    except desk_watch.Busy as exc:
        raise HTTPException(409, str(exc)) from None
    except desk_watch.Full as exc:
        raise HTTPException(413, str(exc)) from None
    return {**result, "watching": _watching(db, today._now())}


def waiting(db: Session, now: float) -> dict:
    """What Close the day walks at ``now``, for the evening review ping (``app/engine/evening_review.py``): ``review``,
    the symbols still asking their close question (``toReview``, one per symbol); ``fills``, the fills waiting to link
    (``fillsToLink``, one per trade). Ratings of alerts and Radar hits are optional and never counted as waiting; a
    ticker the owner does not follow is left out. A Skip or "No plan" kept only in a browser is not seen here. Raises
    when the positions or plans could not be read."""
    listed = threads(db, now)
    rows = [r for r in listed["threads"] if not r["hidden"]]
    # A source that could not be read is not "nothing waiting": the caller records the failure instead.
    failed = [name for name in ("positions", "plans") if listed["sections"][name] == "unavailable"]
    if failed:
        raise RuntimeError(f"Desk sections unavailable: {', '.join(failed)}")
    return {"review": len({r["symbol"] for r in rows if r["close"] and not r["close"]["reviewed"] and r["symbol"]}),
            "fills": len({r["fill_to_link"] for r in rows if r["fill_to_link"]})}


@router.get("/desk/scorecard")
def desk_scorecard(db: Session = Depends(get_session)):
    """The alert scorecard (``app/engine/alert_scorecard.py``): each position alert of the last 30 days, the decision
    logged after it and what happened next against selling at the alert; under ``radar``, the same for Radar's stock hits
    (``app/engine/radar_scorecard.py``), ``off`` or ``unavailable`` with a reason when the Radar file is. Read-only,
    owner-only, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import alert_scorecard, radar_scorecard
    from app.routers import radar
    from app.engine.request_timing import timed
    now = today._now()
    with timed("scorecard alerts"):
        alerts = alert_scorecard.scorecard(db, now)  # first: a failed Radar query below can leave the transaction aborted
    store, reason = radar._store(read_only=True)
    if store is None:
        hits = {"state": "off", "reason": reason}
    else:
        try:
            with timed("scorecard radar"):
                hits = radar_scorecard.scorecard(store, db, now)
        except Exception as exc:  # noqa: BLE001 -- a busy or damaged Radar file or odd event must not take the alert card down
            db.rollback()  # Postgres refuses every later statement in an aborted transaction; this route wrote nothing
            log.warning("radar scorecard unreadable: %s", exc)
            hits = {"state": "unavailable", "reason": "The Radar file could not be read right now."}
    return {**alerts, "radar": hits}


# --------------------------------------------------------------------------- the retired Rate yesterday card's read

TO_RATE_ROWS = 30  # the card's list, newest first; ``count`` is every item waiting
AUTOMATIC_KINDS = ("prep", "week_review")  # the morning brief and the week review, written unasked: not asked about here
ANSWER_RATINGS = ("helped", "didnt")
QUESTION_CHARS = 60


def _rate_since(now: float) -> tuple:
    """The previous trading session's New York date (the market calendar's, else the clock's weekdays) and its midnight
    as naive UTC: the card covers that session and everything after it."""
    from app.engine import chart_levels
    day = datetime.fromtimestamp(now, ET).date()
    known = {d: _hours(d) for d in (day - timedelta(days=n) for n in range(1, 15))}
    first = chart_levels.previous_session(day, known) or day - timedelta(days=1)
    return first, datetime(first.year, first.month, first.day, tzinfo=ET).astimezone(UTC).replace(tzinfo=None)


def _first_words(text: str | None) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= QUESTION_CHARS else line[:QUESTION_CHARS].rsplit(" ", 1)[0] + "…"


def _alerts_to_rate(db: Session, start: datetime) -> dict:
    """Position alerts since ``start`` in /proof's scope (sent, or maybe sent) with no feedback, each with the trade its
    feedback is saved against; one whose position left the journal is left out, as in the Briefing."""
    from app.engine import alert_feedback
    from app.engine.alert_scorecard import KIND
    from app.models import PositionAlert
    alerts = db.exec(select(PositionAlert).where(col(PositionAlert.delivery).in_(alert_feedback.ELIGIBLE_DELIVERIES),
                                                 PositionAlert.detected_at >= start)).all()
    answered = alert_feedback.for_alerts(db, [a.id for a in alerts])
    waiting = [a for a in alerts if a.id not in answered]
    trades = _alert_trades(db, waiting)
    return {"state": "ok", "rows": [
        {"key": f"alert:{a.id}", "type": "alert", "id": str(a.id), "trade_id": trades[(a.account_id, a.source_key)],
         "label": a.contract, "detail": KIND.get(a.kind, "Position alert"), "at": _utc_epoch(a.detected_at),
         "answers": list(alert_feedback.RATINGS)}
        for a in waiting if (a.account_id, a.source_key) in trades]}


def _hits_to_rate_since(db: Session, first, day) -> dict:
    """Radar events of the sessions from ``first`` to ``day`` that a phone ping reached (``radar_proof.alerted_events``,
    /proof's read) and the owner has not rated (``latest_ratings``). The dip rule is scored on its own and stays out, as
    on /proof."""
    from app.engine import radar_proof
    from app.engine.radar_store import RATINGS
    from app.routers import radar
    store, _reason = radar._store(read_only=True)
    if store is None:
        return {"state": "off", "rows": []}
    sessions = [(first + timedelta(days=n)).isoformat() for n in range((day - first).days + 1)]
    events = [e for session in sessions for e in store.events(session) if rule_side(e) is None]
    rated = store.latest_ratings()
    alerted = radar_proof.alerted_events(db, [e["event_id"] for e in events if e["event_id"] not in rated])
    return {"state": "ok", "rows": [
        {"key": f"radar:{e['event_id']}", "type": "radar", "event_id": e["event_id"],
         "label": (e.get("symbols") or [None])[0] if e.get("kind") != "group_move" else e.get("group") or "Group",
         "detail": e.get("summary") or RADAR_KIND.get(e.get("kind"), "Radar"), "at": _epoch(e.get("first_seen_at")),
         "answers": list(RATINGS)}
        for e in events if e["event_id"] in alerted]}


def _answers_to_rate(db: Session, start: datetime) -> dict:
    """The copilot's answers since ``start`` with no Helped / Didn't, read as the answer scorecard reads them (the owner's
    saved conversations; simulated turns left out). The automatic morning brief and week review are not asked about. The
    row's time names the day, so a Main chat segment's detail is just "Main chat"."""
    from app.engine import copilot_scorecard
    from app.models import CopilotTurn
    turns = {str(t.id): t for t in db.exec(select(CopilotTurn).where(col(CopilotTurn.started_at) >= start)).all() if t.backend != "fake"}
    return {"state": "ok", "rows": [
        {"key": f"answer:{a['investigation_id']}:{a['index']}", "type": "answer", "investigation_id": a["investigation_id"],
         "index": a["index"], "label": _first_words(a["question"]) or a["title"],
         "detail": ("Main chat" if a["title"].startswith("Main chat · ") else a["title"]) if a["question"] else None,
         "at": _utc_epoch(a["at"]), "answers": list(ANSWER_RATINGS)}
        for a in copilot_scorecard._answers(db, start, turns) if a["rating"] not in ANSWER_RATINGS and a["kind"] not in AUTOMATIC_KINDS]}


@router.get("/desk/to-rate")
def desk_to_rate(db: Session = Depends(get_session)):
    """The retired Rate yesterday card's read (docs/copilot-lab.md § The desk; kept, unused by the desk): what still waits on the owner's rating from the
    previous trading session (``since``) through now, newest first, at most ``TO_RATE_ROWS`` (``count`` is all of them).
    Each item names its ``type`` and the ids its rating route takes: a position alert (``id``, ``trade_id``:
    ``PUT /trades/{trade_id}/phone-alerts/{id}/feedback``), an alerted Radar event (``event_id``:
    ``POST /radar/events/{event_id}/feedback``) or a copilot answer (``investigation_id``, ``index``:
    ``PUT /copilot/investigations/{id}/messages/{index}/rating``), with ``label``, ``detail``, ``at`` (epoch seconds) and
    the ``answers`` that route accepts. Each source fails on its own (``sections``). Read-only, owner-only, refused while
    the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    now = today._now()
    day = datetime.fromtimestamp(now, ET).date()
    first, start = _rate_since(now)
    alerts = today._section(db, "alerts to rate", lambda: _alerts_to_rate(db, start))
    answers = today._section(db, "answers to rate", lambda: _answers_to_rate(db, start))
    hits = today._section(db, "radar to rate", lambda: _hits_to_rate_since(db, first, day))
    items = sorted((row for part in (alerts, hits, answers) for row in part.get("rows", [])), key=lambda r: r["at"] or 0, reverse=True)
    return {"day": day.isoformat(), "since": first.isoformat(), "count": len(items), "items": items[:TO_RATE_ROWS],
            "sections": {"alerts": alerts["state"], "radar": hits["state"], "answers": answers["state"]}}


# --------------------------------------------------------------------------- Now's "How the pings did" card

SETUP_KINDS = ("dip_turn", "gap_reversal")


def _alert_outcomes(db: Session, now: float, first, start: datetime) -> dict:
    """The alert scorecard's rows (``alert_scorecard.scorecard``) for the alerts sent since ``start`` (naive UTC)."""
    from app.engine import alert_scorecard
    day = datetime.fromtimestamp(now, ET).date()
    card = alert_scorecard.scorecard(db, now, days=(day - first).days + 1)
    since = _utc_epoch(start)
    return {"state": "ok", "rows": [r for r in card["rows"] if r["at"] >= since]}


def _radar_outcomes(db: Session, now: float, first, start: datetime) -> dict:
    """Radar's stock hits and setup cards first seen since ``start`` that a phone ping reached
    (``radar_proof.alerted_events``), each with the radar scorecard's move after it and, for a setup card, its paper
    result (``radar_setup_paper``) when one exists."""
    from app.engine import radar_proof, radar_scorecard
    from app.models import RadarSetup
    from app.routers import radar
    store, reason = radar._store(read_only=True)
    if store is None:
        return {"state": "off", "reason": reason, "rows": []}
    day = datetime.fromtimestamp(now, ET).date()
    try:
        # Only the events a ping reached are scored, so the scorecard's row cap never drops one of them.
        sessions = [(first + timedelta(days=n)).isoformat() for n in range((day - first).days + 1)]
        alerted = radar_proof.alerted_events(db, [e["event_id"] for s in sessions for e in store.events(s)])
        card = radar_scorecard.scorecard(store, db, now, days=(day - first).days, kinds=(*radar_scorecard.STOCK_KINDS, *SETUP_KINDS),
                                         only=alerted)
    except Exception as exc:  # noqa: BLE001 -- a busy or damaged Radar file must not take the alert rows down
        log.warning("radar outcomes unreadable: %s", exc)
        return {"state": "unavailable", "reason": "The Radar file could not be read right now.", "rows": []}
    since = _utc_epoch(start)
    rows = [r for r in card["rows"] if r["at"] >= since]
    setups = {s.event_id: s for s in db.exec(select(RadarSetup).where(col(RadarSetup.event_id).in_([r["event_id"] for r in rows])))} if rows else {}
    out = []
    for r in rows:
        setup = setups.get(r["event_id"])
        paper = None
        if setup is not None:
            paper = {"state": setup.paper_state, "pnl": setup.paper_pnl, "exit_reason": setup.paper_exit_reason,
                     "note": setup.paper_note}
        out.append({"event_id": r["event_id"], "at": r["at"], "symbol": r["symbol"], "kind": r["kind"],
                    "kind_label": RADAR_KIND.get(r["kind"], r["kind_label"]), "direction": r["direction"],
                    "summary": r["summary"], "after": r["after"], "setup": setup is not None, "paper": paper})
    return {"state": "ok", "rows": out}


@router.get("/desk/pings")
def desk_pings(day_only: bool = False, db: Session = Depends(get_session)):
    """Now's "How the pings did" card (docs/copilot-lab.md § The desk): what followed each phone ping since the previous
    trading session (``since``), with nothing to answer. ``alerts``: each position alert sent, with the alert
    scorecard's ``outcome`` (sold or expired for how much against selling at the alert, still open, or not measured).
    ``radar``: each alerted Radar stock hit and setup card, with the stock's move against SPY the way Radar flagged it an
    hour on and at the close (``after``), and a setup card's ``paper`` result. Counts, not advice. Each source fails on
    its own; Radar ``off`` while it does not record. Read-only, owner-only, refused while the lab is off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    now = today._now()
    first, start = _rate_since(now)
    if day_only:  # the day report: just today's pings
        first = datetime.fromtimestamp(now, ET).date()
        start = datetime(first.year, first.month, first.day, tzinfo=ET).astimezone(UTC).replace(tzinfo=None)
    alerts = today._section(db, "pings alert outcomes", lambda: _alert_outcomes(db, now, first, start))
    hits = today._section(db, "pings radar outcomes", lambda: _radar_outcomes(db, now, first, start))
    from app.engine import day_journal
    hidden = day_journal.not_following(db)  # a ticker he does not follow stays out of the card
    return {"day": datetime.fromtimestamp(now, ET).date().isoformat(), "since": first.isoformat(),
            "alerts": {"state": alerts["state"], "rows": [r for r in alerts.get("rows", []) if r["symbol"] not in hidden]},
            "radar": {"state": hits["state"], "reason": hits.get("reason"), "rows": [r for r in hits.get("rows", []) if r["symbol"] not in hidden]}}


@router.get("/desk/day-report")
def desk_day_report(db: Session = Depends(get_session)):
    """The cockpit's after-close day report, the parts the other reads do not hold (docs/copilot-lab.md § The desk;
    ``app/engine/day_report.py``): ``entries``, today's trades opened and how many had a plan saved before the fill;
    ``checks``, the calls he checked scored from the price when he checked to the close (today's, with the last 30 days'
    tally). Facts and counts: "not measured" when a stored price is missing, never a provider fetch, nothing to answer.
    Tickers he does not follow are left out. Each part fails on its own. Read-only, owner-only, refused while the lab is
    off."""
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import day_report
    now = today._now()
    day = datetime.fromtimestamp(now, ET).date()
    hidden = day_report.not_followed(db)
    entries = today._section(db, "day report entries", lambda: day_report.entries_today(db, day, hidden))
    checks = today._section(db, "day report checks", lambda: day_report.checks_report(db, day, now, hidden))
    return {"day": day.isoformat(), "as_of": today._iso(now),
            "entries": entries if entries["state"] == "ok" else None, "checks": checks if checks["state"] == "ok" else None,
            "sections": {"entries": entries["state"], "checks": checks["state"]}}


def _now() -> float:
    import time
    return time.time()


@router.get("/desk/feed")
def desk_feed(db: Session = Depends(get_session)):
    """The desk's Feed (``app/engine/desk_feed.py``): today's pings, plan events, his TradingView alerts, Radar events and setup cards, headlines
    on the owner's symbols and a few market-wide ones, this week's calendar and the morning brief's lines, one small row
    each, ranked and bounded. Each source fails on its own and ``unavailable`` names it. Read-only, owner-only, refused
    while the lab is off."""
    found = copilot.settings()
    if not found.enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    from app.engine import desk_feed
    return desk_feed.build(db, today._now(), mode=getattr(found, "evidence", "live"))


@router.get("/desk/radar-setup")
def radar_setup(event: str, db: Session = Depends(get_session)):
    """A Radar event's setup card as the desk's Radar card shows it (``desk_radar_setups.view``), or ``setup: null``
    for an event without one. The distance from the level uses the latest recorded Radar quote, today's session only;
    a Radar file that is off or unreadable just leaves it out. Read-only."""
    import sqlite3
    from app.engine import desk_radar_setups
    from app.routers import radar
    row = desk_radar_setups.for_event(db, event)
    if row is None:
        return {"setup": None}
    last = None
    store, _ = radar._store(read_only=True)
    if store is not None:
        try:
            today = datetime.fromtimestamp(_now(), ET).date().isoformat()
            last = desk_radar_setups.last_recorded(store, row.session_date, row.symbol, today)
        except (sqlite3.Error, ValueError, KeyError, OSError) as exc:
            log.warning("radar setup last quote unreadable: %s", exc)
    return {"setup": desk_radar_setups.view(db, row, last=last)}


@router.post("/desk/radar-setup/{setup_id}/plan")
def plan_radar_setup(setup_id: str, request: Request, db: Session = Depends(get_session)):
    """Plan it on the desk's Radar card: the setup ping's own ``radar_setup_plan.plan``, unchanged (the same claim, plan,
    alert, 60-minute check and refusals). ``planned`` once a plan stands (now or earlier); ``refused`` when it never can."""
    from app.engine import desk_radar_setups, radar_setup_plan
    from app.models import RadarSetup
    reply, label = radar_setup_plan.plan(db.get_bind(), setup_id)
    monitor = getattr(request.app.state, "level_alerts", None)
    if label == radar_setup_plan.PLANNED and monitor is not None:
        monitor.changed()  # the new invalidation alert is watched at once, as the ping's tap does
    try:
        key = uuid.UUID(setup_id)
    except ValueError:
        key = None
    db.expire_all()
    row = db.get(RadarSetup, key) if key else None
    if row is None:
        raise HTTPException(404, reply)
    return {"reply": reply, "planned": label == radar_setup_plan.PLANNED, "refused": label == radar_setup_plan.NOT_PLANNED,
            "setup": desk_radar_setups.view(db, row)}
