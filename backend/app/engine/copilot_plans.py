"""The Copilot Lab's Plans board: each confirmed copilot plan that is still armed, nearest to a trigger first.

A plan is what a plan card's Confirm left behind for one investigation: its
entry and invalidation level alerts (``plan_role``, ``source_kind="copilot"``,
``source_id`` = the investigation), its time stop and its pre-trade plan
capture. Several plans in one investigation show as its latest: the parts made
within ``PLAN_WINDOW`` before the newest one. The capture is the time stop's
(they share the card's ``client_id``), else the newest "Copilot plan" capture
for the symbol in that window.

A plan is on the board while an alert is armed, its time stop is pending or
the fill linked to its capture is an open position. Once its alerts have fired
or been deleted and nothing is open it drops off, and still shows in its
investigation (``LinkedActivity``). Read-only; the only id out is the
investigation's. Last prices come from one batched quote read.

A position the companion adopted (``engine/position_companion.py``) has no plan
capture: once Confirm arms its invalidation, its plan is read from the adopted
row instead: the position (open or closed) from the trade at its anchor, the
direction from the option (a call is long), the thesis from the draft, and an
``entry`` level already hit at the underlying's price when it was adopted, so
the plan ladder has both ends.
"""

from datetime import UTC, datetime, timedelta
import uuid

from sqlmodel import Session, select

from app.engine import capture_links
from app.engine.chart_journal import contract_label
from app.engine.chart_math import ET
from app.engine.position_alerts import _epoch
from app.models import CopilotInvestigation, LevelAlert, PlanTimeStop, TradeCapture

PLAN_WINDOW = timedelta(minutes=10)
ENTRY_DAYS = 14  # with no capture link, a trade in the symbol opened this long after the plan is still its trade
PLAN_LABEL = "Copilot plan"  # the setup label the plan card saves its capture with
LONG_SIDES = {"buy_stock", "buy_calls", "sell_puts"}
THESIS_CHARS = 160


def _thesis(note: str | None) -> str | None:
    """The thesis from the note the plan card writes: ``Thesis: … [Contract: ….] From a Copilot Lab plan card.``"""
    text = (note or "").strip()
    if not text.startswith("Thesis: "):
        return None
    text = text[len("Thesis: "):]
    for tail in (" Contract: ", " From a Copilot Lab plan card."):
        if (cut := text.rfind(tail)) >= 0:
            text = text[:cut]
    return text.strip()[:THESIS_CHARS] or None


def _instrument(capture: TradeCapture | None) -> str | None:
    """What the plan's capture means to trade: ``stock``, the option contract without its symbol, or ``calls``/``puts``."""
    if capture is None:
        return None
    if capture.instrument != "option":
        return "stock"
    kind = "put" if capture.side.endswith("puts") else "call"
    if capture.strike is None or capture.expiration is None:
        return f"{kind}s"
    return contract_label(capture.underlying, "option", kind, capture.strike, capture.expiration).removeprefix(capture.underlying).strip()


def _level(alert: LevelAlert | None, last: float | None) -> dict | None:
    if alert is None:
        return None
    out = {"price": alert.price, "condition": alert.condition, "interval": alert.interval,
           "state": "armed" if alert.state == "active" else "hit"}
    if alert.state == "active":
        if last:
            out.update(distance_usd=round(alert.price - last, 2), distance_pct=round((alert.price - last) / last * 100, 2))
    else:
        out["hit_at"] = int(_epoch(alert.fired_at)) if alert.fired_at else None
    return out


def _position(capture: TradeCapture | None, links: dict, suggested: dict) -> str:
    """in_position | closed | fill_to_link (an open trade the capture is suggested for) | waiting (no fill yet)."""
    if capture is None:
        return "waiting"
    link = links.get(capture.id, {}).get("link")
    if link and link.get("trade_id"):
        return "in_position" if link.get("status") == "open" else "closed"
    if any(trade.get("status") == "open" for trade in suggested.get(capture.id, [])):
        return "fill_to_link"
    return "waiting"


def _quotes(symbols: list[str]) -> tuple[dict[str, float], float | None, str | None]:
    from app.engine.chart_feed import ChartFeedError, chart_feed
    if not symbols:
        return {}, None, None
    try:
        rows, fetched_at, issue = chart_feed.quote_rows(symbols)
    except ChartFeedError as exc:
        return {}, None, str(exc)
    last = {r["symbol"]: r["last"] for r in rows if isinstance(r.get("last"), (int, float)) and r["last"] > 0}
    return last, fetched_at, issue


def _plans(db: Session) -> tuple[list[dict], dict]:
    """Every confirmed plan, each investigation's latest (its parts within ``PLAN_WINDOW`` of the newest), with its
    capture and its position from the capture's link alone; and the capture links."""
    alerts = db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", LevelAlert.plan_role.is_not(None),
                                              LevelAlert.source_id.is_not(None))).all()
    stops = db.exec(select(PlanTimeStop)).all()
    parts: dict[str, dict] = {}
    for alert in alerts:
        parts.setdefault(alert.source_id, {"alerts": [], "stops": []})["alerts"].append(alert)
    for stop in stops:
        parts.setdefault(stop.investigation_id, {"alerts": [], "stops": []})["stops"].append(stop)

    plans = []
    for investigation_id, found in parts.items():
        newest = max([a.created_at for a in found["alerts"]] + [s.created_at for s in found["stops"]])
        since = newest - PLAN_WINDOW
        recent = sorted((a for a in found["alerts"] if a.created_at >= since), key=lambda a: a.created_at)
        entry = next((a for a in reversed(recent) if a.plan_role == "entry"), None)
        invalidation = next((a for a in reversed(recent) if a.plan_role == "invalidation"), None)
        stop = max((s for s in found["stops"] if s.created_at >= since), key=lambda s: s.created_at, default=None)
        symbol = (entry or invalidation or stop).symbol
        plans.append({"investigation_id": investigation_id, "symbol": symbol, "entry": entry, "invalidation": invalidation,
                      "stop": stop, "since": since, "newest": newest})

    # The pre-trade plan each one saved, in two reads.
    by_client = {c.client_id: c for c in db.exec(select(TradeCapture).where(
        TradeCapture.client_id.in_([p["stop"].client_id for p in plans if p["stop"]]))).all()} if plans else {}
    labelled = db.exec(select(TradeCapture).where(TradeCapture.setup_label == PLAN_LABEL, TradeCapture.mode == "discretionary",
                                                  TradeCapture.underlying.in_({p["symbol"] for p in plans}))).all() if plans else []
    for plan in plans:
        capture = by_client.get(plan["stop"].client_id) if plan["stop"] else None
        if capture is None:
            capture = max((c for c in labelled if c.underlying == plan["symbol"] and plan["since"] <= c.received_at <= plan["newest"]),
                          key=lambda c: c.received_at, default=None)
        plan["capture"] = capture
    captures = [p["capture"] for p in plans if p["capture"] is not None]
    links = capture_links.link_rows(db, captures)
    from app.engine import position_companion
    adopted = position_companion.for_investigations(db, [p["investigation_id"] for p in plans if p["capture"] is None])
    for plan in plans:
        plan["position"] = _position(plan["capture"], links, {})
        if (row := adopted.get(plan["investigation_id"])) is not None:
            trade = position_companion.trade_of(db, row)
            plan["adopted"], plan["trade"] = row, trade
            if trade is not None:
                plan["position"] = "in_position" if trade.status == "open" else "closed"
    return plans, links


def _adopted_entry(row) -> dict | None:
    """An adopted position's entry on the underlying: its price when adopted, already hit at the first fill."""
    from app.engine import position_companion
    price = position_companion.plan_of(row).get("entry_underlying")
    if not price:
        return None
    return {"price": price, "condition": "touches", "interval": None, "state": "hit",
            "hit_at": int(row.opened_at.replace(tzinfo=ET).timestamp())}


def board(db: Session, quotes=None) -> dict:
    """``quotes`` replaces the one batched quote read (the Today screen shares one read across readers)."""
    plans, links = _plans(db)
    live = []
    for plan in plans:
        armed = any(a is not None and a.state == "active" for a in (plan["entry"], plan["invalidation"]))
        pending = plan["stop"] is not None and plan["stop"].delivery == "scheduled"
        if armed or pending or plan["position"] == "in_position":
            live.append(plan)
    # Only a plan still on the board asks whether an unlinked open trade looks like its fill.
    waiting = [p["capture"] for p in live if p["capture"] is not None and p["position"] == "waiting"]
    suggested = capture_links.suggestions(db, waiting)
    for plan in live:
        if plan.get("adopted") is None:  # an adopted plan's position is its trade's
            plan["position"] = _position(plan["capture"], links, suggested)

    last, fetched_at, issue = (quotes or _quotes)(sorted({p["symbol"] for p in live}))
    titles = {str(i.id): i.title for i in db.exec(select(CopilotInvestigation).where(
        CopilotInvestigation.id.in_([_uuid(p["investigation_id"]) for p in live if _uuid(p["investigation_id"])]))).all()} if live else {}
    rows = []
    for plan in live:
        price, capture, stop = last.get(plan["symbol"]), plan["capture"], plan["stop"]
        adopted = plan.get("adopted")
        if adopted is not None:
            from app.engine import position_companion
            draft = position_companion.plan_of(adopted)
            rows.append({
                "investigation_id": plan["investigation_id"], "symbol": plan["symbol"], "direction": draft.get("direction"),
                "instrument": adopted.contract.removeprefix(adopted.ticker).strip(),
                "thesis": draft.get("thesis") or titles.get(plan["investigation_id"]), "last": price,
                "entry": _adopted_entry(adopted), "invalidation": _level(plan["invalidation"], price), "time_stop": None,
                "position": plan["position"], "confirmed_at": int(_epoch(plan["newest"])),
            })
            continue
        if capture is not None:
            direction = "long" if capture.side in LONG_SIDES else "short"
        elif plan["entry"] and plan["invalidation"]:
            direction = "long" if plan["entry"].price > plan["invalidation"].price else "short"
        else:
            direction = None
        rows.append({
            "investigation_id": plan["investigation_id"], "symbol": plan["symbol"], "direction": direction,
            "instrument": _instrument(capture), "thesis": _thesis(capture.note if capture else None) or titles.get(plan["investigation_id"]),
            "last": price, "entry": _level(plan["entry"], price), "invalidation": _level(plan["invalidation"], price),
            "time_stop": {"text": stop.text, "due_at": int(_epoch(stop.due_at)),
                          "state": "pending" if stop.delivery == "scheduled" else stop.delivery} if stop else None,
            "position": plan["position"], "confirmed_at": int(_epoch(plan["newest"])),
        })
    rows.sort(key=_nearest)
    return {"plans": rows, "quotes_at": fetched_at, "quote_issue": issue}


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _nearest(row: dict) -> tuple:
    """Nearest armed trigger first (by %), then plans waiting on a time stop by its time, then the rest."""
    gaps = [abs(level["distance_pct"]) for level in (row["entry"], row["invalidation"]) if level and "distance_pct" in level]
    stop = row["time_stop"]["due_at"] if row["time_stop"] and row["time_stop"]["state"] == "pending" else None
    return (min(gaps) if gaps else float("inf"), stop if stop is not None else float("inf"), row["symbol"], row["investigation_id"])


def exits(db: Session, since: datetime) -> list[dict]:
    """Plans whose position is over, the last of it closed at or after ``since`` (naive UTC), newest exit first: the
    trade linked to the plan's capture, else every trade in the symbol opened within ``ENTRY_DAYS`` after the plan (none
    still open). A plan with no trade either way has not exited. Webull stays out. Read-only; no quote read. Each row also
    carries its ``trades``, ``invalidation`` alert and time ``stop`` (ORM rows) for the week review."""
    from sqlalchemy import or_
    from app.engine.chart_math import ET
    from app.models import Account, Trade
    plans, links = _plans(db)
    wall = lambda moment: moment.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)  # noqa: E731 -- trades keep New York wall time
    utc = lambda moment: moment.replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None)  # noqa: E731
    out = []
    for plan in plans:
        link = links.get(plan["capture"].id, {}).get("link") if plan["capture"] is not None else None
        if plan.get("adopted") is not None:
            trades = [plan["trade"]] if plan["trade"] is not None else []
        elif link and link.get("trade_id"):
            trades = [t for t in [db.get(Trade, uuid.UUID(link["trade_id"]))] if t is not None]
        elif plan["position"] == "waiting":
            trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                             .where(Trade.ticker == plan["symbol"], Trade.opened_at >= wall(plan["since"]),
                                    Trade.opened_at <= wall(plan["newest"] + timedelta(days=ENTRY_DAYS)))
                             .where(or_(Account.broker.is_(None), Account.broker != "webull"))).all()
        else:
            continue
        if not trades or any(t.status == "open" or t.closed_at is None for t in trades):
            continue
        exited = utc(max(t.closed_at for t in trades))
        if exited < since:
            continue
        out.append({"investigation_id": plan["investigation_id"], "symbol": plan["symbol"], "newest": plan["newest"],
                    "exited_at": exited, "thesis": _thesis(plan["capture"].note if plan["capture"] else None),
                    "instrument": _instrument(plan["capture"]),
                    # For the week review's measured facts; never sent out as they are.
                    "trades": trades, "invalidation": plan["invalidation"], "stop": plan["stop"]})
    out.sort(key=lambda row: row["exited_at"], reverse=True)
    return out


def done(db: Session, since: datetime) -> list[dict]:
    """Plans made done at or after ``since`` (naive UTC), newest first: each plan is done by the first ``plan_done``
    day-journal entry for its symbol at or after its newest part. A plan whose alerts and time stop were all deleted
    cannot be found any more; its entry stands alone, with no investigation. Read-only; no quote read."""
    from app.models import DayJournalEntry
    marks: dict[str, list] = {}
    for entry in db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "plan_done", DayJournalEntry.symbol.is_not(None))
                         .order_by(DayJournalEntry.created_at, DayJournalEntry.id)).all():
        marks.setdefault(entry.symbol, []).append(entry)
    plans, _links = _plans(db)
    out, used = [], set()
    for plan in plans:
        entry = next((e for e in marks.get(plan["symbol"], []) if e.created_at >= plan["newest"]), None)
        if entry is None or entry.created_at < since:
            continue
        used.add(entry.id)
        out.append({"investigation_id": plan["investigation_id"], "symbol": plan["symbol"], "done_at": entry.created_at,
                    "text": entry.text, "thesis": _thesis(plan["capture"].note if plan["capture"] else None),
                    "instrument": _instrument(plan["capture"])})
    out += [{"investigation_id": None, "symbol": e.symbol, "done_at": e.created_at, "text": e.text, "thesis": None, "instrument": None}
            for found in marks.values() for e in found if e.created_at >= since and e.id not in used]
    out.sort(key=lambda row: row["done_at"], reverse=True)
    return out


def last_exit_lessons(db: Session, symbols: set[str]) -> dict[str, dict]:
    """Each symbol's newest answered exit review, for the plan card and Arm today's plans: of the plans exited
    (``exits``, newest first), the first whose review was answered, read as Review my week reads it
    (``copilot_review.exit_reviews``: the ``reflection`` saved with the first "Exit reviewed" ``plan_done`` at or after
    the plan's newest part). ``exited``: the New York date of its last exit; ``followed``: what the answer opens with;
    ``lesson``: the owner's own words. A symbol with none is absent. Read-only; no quote read, no model call."""
    from app.ai.copilot_review import LESSON_TEXT, REVIEW_PAIR, _followed, _trim
    from app.engine.chart_math import ET
    from app.models import DayJournalEntry
    exited = [r for r in exits(db, datetime.min) if r["symbol"] in symbols] if symbols else []
    if not exited:
        return {}
    entries = db.exec(select(DayJournalEntry).where(DayJournalEntry.kind.in_(("plan_done", "reflection")),
                                                    DayJournalEntry.symbol.in_({r["symbol"] for r in exited}))
                      .order_by(DayJournalEntry.created_at, DayJournalEntry.id)).all()
    out: dict[str, dict] = {}
    for r in exited:
        if r["symbol"] in out:
            continue
        mine = [e for e in entries if e.symbol == r["symbol"]]
        done = next((e for e in mine if e.kind == "plan_done" and e.created_at >= r["newest"]), None)
        if done is None or done.text != "Exit reviewed":
            continue
        said = [e for e in mine if e.kind == "reflection" and done.created_at - REVIEW_PAIR <= e.created_at <= done.created_at]
        if said:
            out[r["symbol"]] = {"exited": r["exited_at"].replace(tzinfo=UTC).astimezone(ET).date().isoformat(),
                                "followed": _followed(said[-1].text), "lesson": _trim(said[-1].text, LESSON_TEXT)}
    return out
