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
- ``draft``: unarmed plan drafts. No store keeps them yet, so the group stays empty;
- ``new``: Radar events since the last Radar visit (``today._radar``) and thesis-watch triggers fired today
  (``today._thesis``), newest first;
- ``watch``: every other open position, armed plan and open investigation.

Each source is read on its own (``today._section``): one failure reads ``unavailable`` in ``sections`` and the rest
stand. The board reads first, so one batched underlying quote read serves the plans and the positions. Read-only: no
store, no pings, no Radar visit. Owner-only like every ``/copilot`` route; refuses while the lab is off. The only ids
out are investigation, trade and Radar event ids, each the row's own link.

An option position's value is its own unrealized P&L (the option's mark), never the underlying's price; its plan
levels and meter are on the underlying, and the status line says so by naming it.
"""

from datetime import UTC, datetime
import uuid
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from app.ai import copilot
from app.database import get_session
from app.engine.chart_math import ET, session_windows
from app.routers import today

router = APIRouter()

MAX_INVESTIGATIONS = 20
RADAR_KIND = {"relative_to_spy": "vs SPY", "relative_to_sector": "vs sector", "group_move": "Group move"}  # RadarFeedView's words


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
         changed_at: int | None = None) -> dict:
    return {"key": key, "group": group, "symbol": symbol, "title": title, "instrument": instrument, "value": value,
            "status": status, "meter": meter, "investigation_id": investigation_id, "trade_id": trade_id,
            "radar_event_id": radar_event_id, "path": path, "changed_at": changed_at}


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


def _investigations(db: Session) -> dict:
    """Open investigations, newest first. A research job's conclusion was written by a model that read untrusted web
    pages, so only the owner's own conversations bring theirs (``copilot_context._investigations``' rule)."""
    from app.engine import copilot_investigations
    from app.models import CopilotInvestigation
    found = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.status == "open")
                    .order_by(col(CopilotInvestigation.updated_at).desc()).limit(MAX_INVESTIGATIONS)).all()
    rows = []
    for r in map(copilot_investigations.summary, found):
        rows.append({"id": r["id"], "source": r["source"], "symbol": r["symbol"], "title": r["title"],
                     "conclusion": r["conclusion"] if r["source"] == "copilot" else None, "updated_at": r["updated_at"]})
    return {"state": "ok", "rows": rows}


def _decisions(db: Session, day) -> dict:
    """Symbols with a ``decision`` day-journal entry today (the decision bar's log), newest time each. Read by the
    kind's name, so a journal without that kind yet reads as none."""
    from app.engine import day_journal
    found = {}
    for entry in day_journal.entries(db, day):
        if entry.kind == "decision" and entry.symbol:
            found[entry.symbol] = entry.created_at
    return {"state": "ok", "symbols": found}


def _phase(now: float) -> dict:
    local = datetime.fromtimestamp(now, ET)
    minute = local.hour * 60 + local.minute
    phase = next((name for name, start, end in session_windows(local.date(), _hours(local.date())) if start <= minute < end), None)
    return {"state": "ok", "phase": phase or "closed"}


# --------------------------------------------------------------------------- rows

def _instrument(contract: str, symbol: str, instrument: str) -> str:
    return "stock" if instrument == "stock" else contract.removeprefix(symbol).strip() or instrument


def _position_status(row: dict) -> dict:
    """A position not flagged for Act now: its plan's nearest line, or that it has none."""
    plan = row["plan"]
    if plan is None:
        return _say("No plan yet", "muted")
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


def _position_rows(found: dict, links: dict[str, str], board: dict, decided: dict) -> tuple[list[dict], list[dict], set[str]]:
    """(act rows, watch rows, investigation ids the rows cover). ``links``: each planned position's investigation."""
    plans = {p["investigation_id"]: p for p in board.get("plans", [])}
    act, watch, covered = [], [], set()
    for row in found["positions"]:
        trade_id, symbol = row["trade_id"], row["symbol"]
        investigation = links.get(trade_id)
        if investigation:
            covered.add(investigation)
        plan = plans.get(investigation) if investigation else None
        pnl = row["unrealized_usd"]
        value = None if pnl is None else _say(_usd(pnl), "gain" if pnl > 0 else "loss" if pnl < 0 else "muted")
        common = {"symbol": symbol, "instrument": _instrument(row["contract"], symbol, row["instrument"]), "value": value,
                  "investigation_id": investigation, "trade_id": trade_id,
                  "path": None if investigation else row["plan_path"] or row["link_path"] or f"/trades/{trade_id}"}
        flagged = found["flagged"].get(trade_id)
        reasons = " · ".join(r["text"] for r in flagged["reasons"]) if flagged else None
        at = _decided(row, decided) if flagged else None
        if flagged and at is None:
            hit = any(r["kind"] == "invalidation_hit" for r in flagged["reasons"])
            tone = "loss" if hit else "attention"
            level = (row["plan"] or {}).get("invalidation")
            track = meter(plan["entry"]["price"] if plan and plan["entry"] else None, level["price"] if level else None,
                          plan["last"] if plan else None, tone)
            act.append(_row(f"trade:{trade_id}", "act", row["contract"], _say(reasons, tone), meter=track, **common))
        elif flagged:
            clock = at.replace(tzinfo=UTC).astimezone(ET).strftime("%H:%M")
            watch.append(_row(f"trade:{trade_id}", "watch", row["contract"], _say(f"Decided {clock} · {reasons}", "muted"), **common))
        else:
            watch.append(_row(f"trade:{trade_id}", "watch", row["contract"], _position_status(row), **common))
    return act, watch, covered


PLAN_STATE = {"waiting": _say("Armed", "muted"), "fill_to_link": _say("Fill to link", "attention"),
              "closed": _say("Closed", "muted"), "in_position": _say("In position", "info")}


def _near(plan: dict) -> tuple[str, dict] | None:
    """The Today screen's rule: the nearest armed entry or invalidation within ``NEAR_PCT``."""
    near = [(role, level) for role, level in (("entry", plan["entry"]), ("invalidation", plan["invalidation"]))
            if level and level["state"] == "armed" and "distance_pct" in level and abs(level["distance_pct"]) <= today.NEAR_PCT]
    return min(near, key=lambda pair: abs(pair[1]["distance_pct"])) if near else None


def _plan_rows(board: dict, covered: set[str]) -> tuple[list[dict], list[dict]]:
    """(near rows, watch rows) for the armed plans no position row covers."""
    near_rows, watch = [], []
    for plan in board["plans"]:
        inv = plan["investigation_id"]
        if inv in covered:
            continue
        common = {"symbol": plan["symbol"], "instrument": plan["direction"], "value": PLAN_STATE.get(plan["position"]),
                  "investigation_id": inv}
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


def _investigation_of(path: str | None) -> str | None:
    found = parse_qs(urlparse(path or "").query).get("investigation")
    return found[0] if found else None


TRIGGER = {"news": "News", "move": "Move", "earnings": "Earnings"}


def _new_rows(radar: dict, thesis: dict, titles: dict[str, str]) -> list[dict]:
    rows = []
    for event in radar.get("rows", []):
        kind = RADAR_KIND.get(event["kind"], (event["kind"] or "event").replace("_", " "))
        rows.append(_row(f"radar:{event['event_id']}", "new", event["summary"] or kind, _say(f"Radar · {kind}", "info"),
                         symbol=event["symbol"] or None, radar_event_id=event["event_id"], path=event["path"],
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
    now = today._now()
    day = datetime.fromtimestamp(now, ET).date()
    quotes = today.SharedQuotes()
    # The board first: its read covers every armed plan, so the positions' invalidations need no second read.
    board = today._section(db, "desk board", lambda: _board(db, quotes))
    found = today._section(db, "desk positions", lambda: _positions(db, quotes, now, day))
    investigations = today._section(db, "desk investigations", lambda: _investigations(db))
    decisions = today._section(db, "desk decisions", lambda: _decisions(db, day))
    radar = today._section(db, "desk radar", lambda: today._radar(now))
    thesis = today._section(db, "desk thesis", lambda: today._thesis(db, day))
    prep = today._section(db, "desk prep", lambda: today._prep(db, day))
    week = today._section(db, "desk week", lambda: today._week(db, now))
    phase = today._section(db, "desk phase", lambda: _phase(now))

    act, watch, covered = ([], [], set())
    if found["state"] == "ok":
        # Which investigation each planned position opens; on its own, so a failure here still lists the positions.
        links = today._section(db, "desk position plans", lambda: {"state": "ok", "map": _position_investigations(db, found)})
        act, watch, covered = _position_rows(found, links.get("map", {}), board if board["state"] == "ok" else {},
                                             decisions.get("symbols", {}))
    near = []
    if board["state"] == "ok":
        near, plan_watch = _plan_rows(board, covered)
        watch += plan_watch
        covered |= {p["investigation_id"] for p in board["plans"]}
    titles = {r["id"]: r["title"] for r in investigations.get("rows", [])}
    new = _new_rows(radar, thesis, titles)
    covered |= {r["investigation_id"] for r in new if r["investigation_id"]}
    for r in investigations.get("rows", []):
        if r["id"] in covered:
            continue
        status = _say(r["conclusion"], "muted") if r["conclusion"] else _say("Research" if r["source"] == "research_job" else "Open investigation", "muted")
        watch.append(_row(f"investigation:{r['id']}", "watch", r["title"], status, symbol=r["symbol"],
                          instrument="research" if r["source"] == "research_job" else None, investigation_id=r["id"],
                          changed_at=_epoch(r["updated_at"])))

    streak = {"current": week["current"], "best": week["best"]} if week["state"] == "ok" and week["show"] else None
    return {
        "as_of": today._iso(now), "quotes_at": quotes.at, "quote_issue": quotes.issue,
        "day": {"phase": phase.get("phase"), "need_you": len(act), "streak": streak},
        "threads": _pinned(prep, week) + act + near + new + watch,
        "sections": {name: part["state"] for name, part in (
            ("positions", found), ("plans", board), ("investigations", investigations), ("decisions", decisions),
            ("radar", radar), ("thesis", thesis), ("prep", prep), ("week", week), ("phase", phase))},
    }
