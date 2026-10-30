"""The practice goal (docs/copilot-lab.md § Review my week): one concrete thing the owner chose to practice, proposed by
the week review, confirmed on its card, and scored by the next week's review from data the journal already holds.

Measures (each "hit of of" for one Monday-to-Friday week, New York):

- ``plan_before_entry``: the week's closed trades with a plan captured before the entry (``capture_links.timing``);
- ``exit_at_invalidation``: invalidation pings the fills could judge, acted on (closed or trimmed within 15 minutes,
  ``notification_policy``); a week with none judged falls back to the plans' follow-through (invalidation hit while
  held, out within 15 minutes);
- ``respond_to_giveback_15m``: give-back alerts on the week's trades followed by a close or trim within 15 minutes
  (``exit_habits.follow_up``);
- ``no_trade_after_hour_red``: closed long options not held an hour and closed red the same day (habit flags);
- ``no_opening_while_green``: closed long options not opened while the day was already green (habit flags);
- ``max_trades_per_day``: trading days with at most ``target`` trades opened.

``target`` is a share (0-1) the hit rate should reach, or the daily cap for ``max_trades_per_day`` (required there).
Nothing here writes a trade, fill or alert; ``save`` writes only ``practice_goal`` rows.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.models import PracticeGoal

MEASURES = {
    "plan_before_entry": ("plan before entry", "trades with a plan captured before the entry"),
    "exit_at_invalidation": ("exit at my invalidation", "invalidation pings followed by an exit within 15 min"),
    "respond_to_giveback_15m": ("act on give-back alerts within 15 min", "give-back alerts followed by a close or trim within 15 min"),
    "no_trade_after_hour_red": ("no trade held an hour into a red close", "long options not held an hour and closed red"),
    "no_opening_while_green": ("no new trade while the day is green", "long options not opened while the day was green"),
    "max_trades_per_day": ("at most {cap} trades a day", "trading days at or under {cap} trades"),
}
TEXT_MAX, WHY_MAX = 200, 300
MAX_DAILY_CAP = 20
HABIT = {"no_trade_after_hour_red": "held_hour_lost", "no_opening_while_green": "opened_green"}
OUT = ("closed_15m", "trimmed_15m")


class PracticeError(ValueError):
    pass


def check_target(measure: str, target) -> float | None:
    """A share in (0, 1], or a whole daily cap (1-20, required) for ``max_trades_per_day``."""
    if measure not in MEASURES:
        raise PracticeError(f"measure must be one of {', '.join(MEASURES)}")
    if measure == "max_trades_per_day":
        if isinstance(target, bool) or not isinstance(target, (int, float)) or target != int(target) or not 1 <= target <= MAX_DAILY_CAP:
            raise PracticeError(f"max_trades_per_day needs target, a whole number of trades from 1 to {MAX_DAILY_CAP}")
        return float(int(target))
    if target is None:
        return None
    if isinstance(target, bool) or not isinstance(target, (int, float)) or not 0 < target <= 1:
        raise PracticeError("target must be a share above 0 and at most 1")
    return round(float(target), 2)


def label(measure: str, target: float | None) -> str:
    return MEASURES[measure][0].format(cap=int(target or 0))


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def first_week(today: date) -> date:
    """The Monday a goal confirmed ``today`` starts counting: this week's on a weekday, the next one on a weekend."""
    return _monday(today) + (timedelta(days=7) if today.weekday() >= 5 else timedelta())


def active(db: Session) -> PracticeGoal | None:
    return db.exec(select(PracticeGoal).where(PracticeGoal.status == "active").order_by(PracticeGoal.created_at.desc())).first()


def save(db: Session, *, text: str, measure: str, target, investigation_id: str | None, today: date) -> PracticeGoal:
    """The new active goal; the previous one ends (scored once its first week is over, dropped before)."""
    target = check_target(measure, target)
    text = " ".join((text or "").split())
    if not text or len(text) > TEXT_MAX:
        raise PracticeError(f"text must be 1-{TEXT_MAX} characters")
    now = datetime.utcnow()
    week = first_week(today)
    for old in db.exec(select(PracticeGoal).where(PracticeGoal.status == "active")).all():
        old.status = "scored" if old.week_start + timedelta(days=5) <= today else "dropped"
        old.ended_at = now
        db.add(old)
    goal = PracticeGoal(text=text, measure=measure, target=target, week_start=week, investigation_id=investigation_id)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def public(goal: PracticeGoal) -> dict:
    """What a page or the copilot sees of a goal: no ids."""
    return {"text": goal.text, "measure": goal.measure, "label": label(goal.measure, goal.target), "target": goal.target,
            "week_start": goal.week_start.isoformat(), "since": goal.created_at.isoformat(timespec="seconds") + "Z"}


# --------------------------------------------------------------------------- scoring

def _week(monday: date) -> tuple[datetime, datetime]:
    start = datetime.combine(monday, datetime.min.time())
    return start, start + timedelta(days=5)


def _webull_ids(db: Session):
    from app.models import Account
    return list(db.exec(select(Account.id).where(Account.broker == "webull")).all())


def week_rows(db: Session, monday: date) -> list[dict]:
    """The week review's per-trade pieces (``copilot_review._week_trade``) for the week starting ``monday``."""
    from app.ai import copilot_review
    from app.models import Account, Trade
    start, end = _week(monday)
    webull = set(_webull_ids(db))
    trades = db.exec(select(Trade).where(Trade.status.in_(("closed", "expired")), Trade.closed_at >= start,
                                         Trade.closed_at < end).order_by(Trade.closed_at)).all()
    accounts = {a.id: a for a in db.exec(select(Account)).all()}
    return [copilot_review._week_trade(db, t, accounts.get(t.account_id)) for t in trades if t.account_id not in webull]


def _invalidation_pings(db: Session, start: datetime, end: datetime) -> tuple[int, int]:
    from app.engine import capture_links, notification_policy
    from app.models import PhonePing
    pings = db.exec(select(PhonePing.then, PhonePing.anchor).where(PhonePing.kind == "invalidation", PhonePing.decision == "sent",
                                                 PhonePing.decided_at >= capture_links.entry_utc(start),
                                                 PhonePing.decided_at < capture_links.entry_utc(end))).all()
    webull = tuple(f"{account}:" for account in _webull_ids(db))  # a ping's anchor is "<account id>:<source key>"
    judged = [then for then, anchor in pings if then is not None and then != "unmatched" and not (anchor or "").startswith(webull or ("\0",))]
    return sum(then in notification_policy.ACTED for then in judged), len(judged)


def _trades_per_day(db: Session, start: datetime, end: datetime) -> Counter:
    from app.engine.analytics import wall_time
    from app.models import Trade
    webull = set(_webull_ids(db))
    opened = db.exec(select(Trade.opened_at, Trade.account_id).where(Trade.opened_at >= start, Trade.opened_at < end)).all()
    return Counter(wall_time(at).date() for at, account in opened if account not in webull)


def score(db: Session, measure: str, target: float | None, monday: date, rows: list[dict] | None = None) -> dict:
    """One measure for the week starting ``monday``: ``hit`` of ``of``, the share, and whether it met ``target``."""
    rows = week_rows(db, monday) if rows is None else rows
    start, end = _week(monday)
    source = None
    if measure == "plan_before_entry":
        hit, of = sum(r["plan"] == "pre_entry" for r in rows), len(rows)
    elif measure == "exit_at_invalidation":
        hit, of = _invalidation_pings(db, start, end)
        source = "invalidation pings"
        if not of:
            hits = [r["follow"] for r in rows if isinstance(r["follow"], dict) and r["follow"].get("invalidation") == "hit_while_held"]
            hit, of, source = sum(f["then"] == "out_15m" for f in hits), len(hits), "plan follow-through"
    elif measure == "respond_to_giveback_15m":
        # A roll is neither taking the gain nor ignoring the alert, so it does not count either way.
        alerts = [a for r in rows for a in ((r["alerts"] or {}).get("alerts") or []) if a.get("kind") == "giveback" and a.get("then") != "rolled"]
        hit, of = sum(a.get("then") in OUT for a in alerts), len(alerts)
    elif measure in HABIT:
        flags = [r["flags"][HABIT[measure]] for r in rows if r["flags"] and r["flags"].get(HABIT[measure]) is not None]
        hit, of = sum(not f for f in flags), len(flags)
    else:
        days = _trades_per_day(db, start, end)
        hit, of = sum(n <= (target or 0) for n in days.values()), len(days)
    noun = MEASURES[measure][1].format(cap=int(target or 0))
    out = {"week_start": monday.isoformat(), "hit": hit, "of": of, "text": f"{hit} of {of}", "of_what": noun,
           "share": round(hit / of, 2) if of else None,
           "met": None if not of or (target is None and measure != "max_trades_per_day")
           else (hit == of if measure == "max_trades_per_day" else hit / of >= target)}
    if source:
        out["source"] = source
    return out


def week_section(db: Session, monday: date, rows: list[dict]) -> dict:
    """The week review's ``practice`` section: the active goal scored for the reviewed week and the week before."""
    goal = active(db)
    if goal is None:
        return {"state": "none"}
    return {"state": "ok", "goal": public(goal), "practicing": monday >= goal.week_start,
            "this_week": score(db, goal.measure, goal.target, monday, rows),
            "last_week": score(db, goal.measure, goal.target, monday - timedelta(days=7)),
            "note": "Lead the review with this score in one sentence (this week against the target and last week). "
                    "practicing false means the reviewed week came before the goal started. Never characterize the owner."}


def current(db: Session, today: date) -> dict:
    """``GET /copilot/practice``: the active goal and its score for the week holding ``today`` (the week just ended, on
    a weekend), or null when the goal starts later."""
    goal = active(db)
    if goal is None:
        return {"goal": None, "this_week": None}
    monday = _monday(today)
    return {"goal": public(goal),
            "this_week": score(db, goal.measure, goal.target, monday) if monday >= goal.week_start else None}
