"""His weekly goals (docs/copilot-lab.md § Weekly goals): one or two goals he sets for the week, with progress computed
from data the desk already keeps, never typed.

- **The goals.** At most ``MAX_GOALS``, each one of ``KINDS`` with its number, about his real trades (the default) or
  his paper book. Only kinds the data can measure: rules followed (the #827 checklists), the largest loss on one trade,
  and the most trades opened in one day. Each save is a ``trading_rule_record`` row (``kind`` ``goals``; the rules
  table, no new table); the newest is the list, so goals carry over week to week until he changes them. An empty save
  clears them.
- **The week.** Monday to Friday, New York. A week's goals are the newest saved before that week ended, so a change
  made mid-week applies to the whole week. On a weekend the desk's line names next week's goals with no progress yet;
  the week just ended is the Friday review's row.
- **Real.** The journal's ``trade`` rows (Webull left out): a loss counts in the week its trade closed, a trade in the
  day it opened. Rules followed counts real trades opened that week whose copied Ticket checklist is linked to them
  through the saved plan (``trading_rules.matched``); trades without one are counted and named as such, never guessed.
  When the Gmail fill feed is down (``gmail_health``) the real progress is marked stale with the last import's time, so
  the desk shows it grey and never as on track.
- **Paper.** Every live paper run's positions (``paper_book.fold``): opened that week for trades a day and rules, closed
  that week for the largest loss. Each paper entry's checklist rides in its fill.

Counts and dollars only, never a ticker. Database reads and local state files; no quote, no provider, never Robinhood,
never a ping.
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, date, datetime, time as wall_time, timedelta

from sqlmodel import Session, col, select

from app.engine import trading_rules
from app.engine.chart_math import ET
from app.models import TradingRuleRecord

MAX_GOALS = 2
BOOKS = ("real", "paper")
KINDS: dict[str, dict] = {
    "rules_pct": {"words": "Follow all my rules on {n}% of trades", "unit": "%", "min": 1, "max": 100},
    "max_loss": {"words": "Max loss per trade ${n}", "unit": "$", "min": 1, "max": 1_000_000},
    "max_trades_day": {"words": "No more than {n} trades a day", "unit": "trades", "min": 1, "max": 100},
}


class GoalsError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _naive(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _dollars(value: float) -> str:
    cents = round(value, 2)
    return f"${cents:,.0f}" if cents == int(cents) else f"${cents:,.2f}"


def words(goal: dict) -> str:
    n = goal["n"]
    shown = f"{n:,}" if goal["kind"] == "max_loss" else str(n)
    out = KINDS[goal["kind"]]["words"].format(n=shown)
    return f"{out} (paper)" if goal["book"] == "paper" else out


# --- the list ---------------------------------------------------------------------------------------------------------

def _row(db: Session, before: datetime | None = None) -> TradingRuleRecord | None:
    query = select(TradingRuleRecord).where(TradingRuleRecord.kind == "goals")
    if before is not None:
        query = query.where(TradingRuleRecord.recorded_at < before)
    return db.exec(query.order_by(col(TradingRuleRecord.recorded_at).desc(), col(TradingRuleRecord.id).desc())).first()


def current(db: Session, before: datetime | None = None) -> list[dict]:
    """His goals now (or the newest saved before ``before``, naive UTC); none when never set or cleared."""
    row = _row(db, before)
    return json.loads(row.data_json)["goals"] if row else []


def clean(db: Session, raw) -> list[dict]:
    if not isinstance(raw, list):
        raise GoalsError("Send the goals as a list.")
    if len(raw) > MAX_GOALS:
        raise GoalsError(f"Keep it to {MAX_GOALS} goals a week.")
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            raise GoalsError(f"A goal is one of: {', '.join(KINDS)}.")
        kind, book, n = item["kind"], item.get("book") or "real", item.get("n")
        spec = KINDS[kind]
        if book not in BOOKS:
            raise GoalsError("A goal is about your real trades or your paper book.")
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n != int(n) or not spec["min"] <= n <= spec["max"]:
            raise GoalsError(f"\"{spec['words'].format(n='N')}\" needs a whole N from {spec['min']:,} to {spec['max']:,}.")
        if (kind, book) in seen:
            raise GoalsError("The same goal twice: keep one.")
        if kind == "rules_pct" and not trading_rules.current(db):
            raise GoalsError("Write your rules first (Paper › Rules): this goal counts trades that followed them.")
        seen.add((kind, book))
        out.append({"kind": kind, "n": int(n), "book": book})
    return out


def save(db: Session, raw, now: float) -> list[dict]:
    goals = clean(db, raw)
    db.add(TradingRuleRecord(kind="goals", record_key=f"goals:{uuid.uuid4().hex}", recorded_at=_naive(now),
                             data_json=json.dumps({"goals": goals}, sort_keys=True)))
    db.commit()
    return goals


def kinds(db: Session) -> list[dict]:
    """The kinds he can pick, each with why not when the data cannot measure it yet."""
    has_rules = bool(trading_rules.current(db))
    return [{"kind": k, "words": v["words"], "unit": v["unit"], "min": v["min"], "max": v["max"],
             "why_not": None if k != "rules_pct" or has_rules else "Write your rules first (Paper › Rules)."}
            for k, v in KINDS.items()]


# --- the week ---------------------------------------------------------------------------------------------------------

def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def bounds(monday: date) -> tuple[datetime, datetime]:
    """Monday 00:00 to Saturday 00:00 New York, as New York wall clocks (the journal's trade times)."""
    return datetime.combine(monday, wall_time(0)), datetime.combine(monday + timedelta(days=5), wall_time(0))


def _end_utc(monday: date) -> datetime:
    return datetime.combine(monday + timedelta(days=5), wall_time(0), ET).astimezone(UTC).replace(tzinfo=None)


def _clock(stamp: float, now: float) -> str:
    moment = datetime.fromtimestamp(stamp, ET)
    if moment.date() == datetime.fromtimestamp(now, ET).date():
        return moment.strftime("%-I:%M %p ET")
    return moment.strftime("%b %-d, %-I:%M %p ET")


def real_freshness(db: Session, now: float) -> str | None:
    """Why the journal's real trades may be behind (with the last import's time), or None when the fill feed is live."""
    try:
        from app.engine.gmail_health import gmail_health
        health = gmail_health(db)
    except Exception:  # noqa: BLE001 -- unreadable: say so, never "on track"
        return "The fill feed's state could not be read, so real trades may be behind."
    if health.get("status") != "down":
        return None
    last = health.get("last_import_at")
    when = None
    if isinstance(last, str):
        try:
            when = _clock(datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp(), now)
        except ValueError:
            when = None
    return f"Real trades as of {when}: new fills are not arriving." if when else "Real trades may be behind: new fills are not arriving."


def _real_rows(db: Session, monday: date):
    from app.models import Account, Trade
    start, end = bounds(monday)
    webull = select(Account.id).where(Account.broker == "webull")
    opened = db.exec(select(Trade).where(col(Trade.account_id).not_in(webull))
                     .where(col(Trade.opened_at) >= start).where(col(Trade.opened_at) < end)).all()
    closed = db.exec(select(Trade.realized_pnl).where(col(Trade.account_id).not_in(webull))
                     .where(col(Trade.status).in_(("closed", "expired"))).where(Trade.realized_pnl.is_not(None))
                     .where(col(Trade.closed_at) >= start).where(col(Trade.closed_at) < end)).all()
    return opened, [float(p) for p in closed]


def _paper_positions(db: Session) -> list[dict]:
    from app.engine import paper_book
    from app.models import PaperRun
    runs = db.exec(select(PaperRun).where(PaperRun.kind == "live")).all()
    return [p for run in runs for p in paper_book.fold(paper_book._events(db, run))]


def _in_week(stamp: float | None, monday: date) -> bool:
    if stamp is None:
        return False
    day = datetime.fromtimestamp(stamp, ET).date()
    return monday <= day < monday + timedelta(days=5)


def _rules_line(outcomes: list[str | None], n: int, prefix: str, unlinked_words: str) -> dict:
    followed = outcomes.count("followed")
    checked = followed + outcomes.count("broken")
    unclear = outcomes.count("unclear")
    missing = outcomes.count(None)
    extra = "".join([f" · {unclear} unclear" if unclear else "",
                     f" · {missing} {unlinked_words}" if missing else ""])
    if not checked:
        return {"text": f"{prefix}rules: no checked trades yet (goal {n}%){extra}", "ok": None}
    pct = round(followed / checked * 100)
    return {"text": f"{prefix}rules followed {followed}/{checked} ({pct}%, goal {n}%){extra}",
            "ok": followed * 100 >= n * checked}


def _loss_line(pnls: list[float], n: int, prefix: str) -> dict:
    if not pnls:
        return {"text": f"{prefix}max loss: no closed trades yet (goal {_dollars(n)})", "ok": None}
    worst = -min(pnls)
    if worst <= 0:
        return {"text": f"{prefix}no losing trade (goal {_dollars(n)})", "ok": True}
    return {"text": f"{prefix}max loss {_dollars(worst)} (goal {_dollars(n)})", "ok": worst <= n + 0.005}


def _day_line(days: list[date], n: int, prefix: str) -> dict:
    if not days:
        return {"text": f"{prefix}no trades yet (goal at most {n} a day)", "ok": None}
    counts: dict[date, int] = {}
    for d in days:
        counts[d] = counts.get(d, 0) + 1
    busiest = max(counts.values())
    when = min(d for d, c in counts.items() if c == busiest)
    return {"text": f"{prefix}most trades in a day {busiest} ({when:%a}; goal {n})", "ok": busiest <= n}


def progress(db: Session, goals: list[dict], monday: date, now: float) -> list[dict]:
    """Each goal's progress over the week of ``monday``: ``text``, ``ok`` (True met so far, False missed, None nothing to
    judge yet) and ``stale`` (why the real side may be behind, with its time; the desk shows it grey, never as met)."""
    if not goals:
        return []
    real = paper = None
    stale = None
    out = []
    for goal in goals:
        kind, n, book = goal["kind"], goal["n"], goal["book"]
        item = {**goal, "goal": words(goal), "stale": None}
        try:
            if book == "real":
                if real is None:
                    stale = real_freshness(db, now)
                    real = _real_rows(db, monday)
                opened, closed = real
                if kind == "max_loss":
                    found = _loss_line(closed, n, "")
                elif kind == "max_trades_day":
                    found = _day_line([t.opened_at.date() for t in opened], n, "")
                else:
                    by_trade = {}
                    links = trading_rules.matched(db)
                    if links is not None:
                        checklists, trades = links
                        for plan, trade in trades.items():
                            by_trade[trade.id] = checklists[plan]
                    outcomes = [trading_rules.outcome(by_trade[t.id]) if t.id in by_trade else None for t in opened]
                    found = _rules_line(outcomes, n, "", "without a checklist")
                item["stale"] = stale
            else:
                if paper is None:
                    paper = _paper_positions(db)
                if kind == "max_loss":
                    found = _loss_line([p["realized"] for p in paper if p["status"] != "open" and _in_week(p["closed_at"], monday)],
                                       n, "paper ")
                elif kind == "max_trades_day":
                    found = _day_line([datetime.fromtimestamp(p["opened_at"], ET).date() for p in paper
                                       if _in_week(p["opened_at"], monday)], n, "paper ")
                else:
                    found = _rules_line([trading_rules.outcome(p.get("rules")) for p in paper if _in_week(p["opened_at"], monday)],
                                        n, "paper ", "entered before your rules")
        except Exception:  # noqa: BLE001 -- unreadable: grey with why, never a zero
            db.rollback()  # a failed read must not leave the session aborted for the paper read that follows
            found = {"text": f"{words(goal)}: could not be read just now", "ok": None}
            item["stale"] = "Could not be read just now."
        if item["stale"]:
            found["ok"] = None  # behind: never shown as on track or missed
        out.append({**item, **found})
    return out


def desk(db: Session, now: float) -> dict:
    """The Paper section's line: his goals and this week's progress; on a weekend, next week's goals, nothing measured."""
    today = datetime.fromtimestamp(now, ET).date()
    goals = current(db)
    weekend = today.weekday() >= 5
    monday = monday_of(today) + (timedelta(days=7) if weekend else timedelta(0))
    return {"goals": goals, "kinds": kinds(db), "max": MAX_GOALS, "monday": monday.isoformat(),
            "label": "Next week" if weekend else "This week",
            "progress": [] if weekend else progress(db, goals, monday, now)}


def for_review(db: Session, monday_iso: str, now: float) -> list[dict]:
    """The Friday review's row: the goals in force when that week ended, measured over it."""
    try:
        monday = date.fromisoformat(monday_iso)
    except (TypeError, ValueError):
        return []
    return progress(db, current(db, _end_utc(monday)), monday, now)
