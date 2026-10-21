"""The weekly review: three exit leaks, one rule to practise, and next week's check.

The October 21, 2026 behavior audit (D0) found the money leaks at the exit:
winners ridden back below entry, losers held past an hour, and options left to
die on their last day. The entry flags the AI reviews coach on did not predict
outcomes, so this review counts only those three exits. It is deterministic:
saving or checking a rule never needs a model call.

A week is Monday 00:00 to the next Monday, New York (journal times are naive
New York wall clocks). Leak rows use trades that **closed** in the week, the
analytics rule. The rule check uses trades **entered** after the rule was
chosen, up to the end of the week it was chosen for. Option trades only;
Webull is excluded, as for Jo's history.

Every trade is judged per rule as ``untested`` (the situation never arose),
``kept``, ``broke`` or ``unmeasured`` (no price path or time of day). Only a
losing trade can break a rule, so only losing trades are ever ``unmeasured``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.engine.capture_links import reliable
from app.engine.chart_journal import contract_label, number, stamp
from app.engine.pretrade_check import EXCLUDED_BROKERS
from app.models import Account, Fill, Trade, TradeFill, TradePathMetrics, WeeklyReviewRecord, utc_now_naive

NY = ZoneInfo("America/New_York")
RULES = {
    "winner_to_red": {"label": "Winner ridden to red", "params": {"peak_pct": 10},
                      "text": "Once an option is up 10%, don't let it close below entry."},
    "held_hour_red": {"label": "Held an hour, closed red", "params": {"hold_minutes": 60},
                      "text": "Re-decide at one hour: don't let a trade held past an hour close red."},
    "expiry_day": {"label": "Died on its last day", "params": {"loss_pct": 90},
                   "text": "Be out before the last day: don't let an option expire or lose 90% on its expiry day."},
}
RESULTS = ("kept", "partly", "broken", "not_enough")
MIN_TESTED = 3  # fewer trades than this that tested the rule, with none broken, is "not enough trades"
HISTORY = 12


class ReviewError(ValueError):
    """A refusal the owner can act on."""


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def this_monday() -> date:
    return monday(datetime.now(NY).date())


def check_week(week_start: date) -> date:
    if week_start.weekday() != 0:
        raise ReviewError("A week starts on a Monday.")
    if week_start > this_monday():
        raise ReviewError("That week hasn't started yet.")
    return week_start


def _bounds(week_start: date) -> tuple[datetime, datetime]:
    start = datetime.combine(week_start, datetime.min.time())
    return start, start + timedelta(days=7)


def _ny(utc: datetime) -> datetime:
    """A stored UTC time as a naive New York wall clock, comparable with journal times."""
    return utc.replace(tzinfo=UTC).astimezone(NY).replace(tzinfo=None)


def _scope(db: Session) -> dict[uuid.UUID, Account]:
    return {a.id: a for a in db.exec(select(Account)).all() if (a.broker or "").lower() not in EXCLUDED_BROKERS}


def _hold_minutes(trade: Trade) -> float | None:
    if trade.opened_at is None or trade.closed_at is None:
        return None
    if trade.closed_at.date() > trade.opened_at.date():
        return (trade.closed_at - trade.opened_at).total_seconds() / 60 if reliable(trade.opened_at) else 24 * 60.0
    if not (reliable(trade.opened_at) and reliable(trade.closed_at)):
        return None
    return (trade.closed_at - trade.opened_at).total_seconds() / 60


def judge(rule_key: str, params: dict, trade: Trade, path: TradePathMetrics | None) -> str:
    """untested | kept | broke | unmeasured, for one closed or expired trade."""
    pnl = float(trade.realized_pnl)
    if rule_key == "winner_to_red":
        premium = float(trade.total_premium_paid or 0)
        if premium > 0 and pnl >= premium * params["peak_pct"] / 100:
            return "kept"  # it closed at least that far up, so it got there
        peak = path.option_mfe_pct if path is not None else None
        if peak is None:
            return "unmeasured" if pnl < 0 else "untested"
        return "untested" if peak < params["peak_pct"] else "broke" if pnl < 0 else "kept"
    if rule_key == "held_hour_red":
        minutes = _hold_minutes(trade)
        if minutes is None:
            return "unmeasured" if pnl < 0 else "untested"
        return "untested" if minutes < params["hold_minutes"] else "broke" if pnl < 0 else "kept"
    if rule_key == "expiry_day":
        last_day = trade.expiration
        if last_day is None or trade.closed_at is None:
            return "untested"
        if trade.status != "expired" and trade.closed_at.date() < last_day:
            return "untested"
        premium = float(trade.total_premium_paid or 0)
        died = trade.status == "expired" and pnl < 0 or premium > 0 and pnl <= -premium * params["loss_pct"] / 100
        return "broke" if died else "kept"
    raise ReviewError("Unknown rule.")


def _paths(db: Session, trades: list[Trade]) -> dict[uuid.UUID, TradePathMetrics]:
    ids = [t.id for t in trades]
    return {p.trade_id: p for p in db.exec(select(TradePathMetrics).where(TradePathMetrics.trade_id.in_(ids))).all()} if ids else {}


def _anchors(db: Session, trades: list[Trade]) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    """Each trade's first entry fill as (account, raw_email_id): a trade's ID is that fill's ID."""
    ids = [t.id for t in trades]
    rows = db.exec(select(Fill.id, Fill.account_id, Fill.raw_email_id).where(Fill.id.in_(ids))).all() if ids else []
    return {row.id: (row.account_id, row.raw_email_id) for row in rows}


def _resolve(db: Session, anchors: list[tuple[str, str]]) -> dict[tuple[str, str], uuid.UUID]:
    """(account, raw_email_id) → the trade that fill is in now; a fill that is gone resolves to nothing."""
    keys = {key for _, key in anchors}
    if not keys:
        return {}
    rows = db.exec(select(Fill.account_id, Fill.raw_email_id, TradeFill.trade_id).join(TradeFill, TradeFill.fill_id == Fill.id)
                   .where(Fill.raw_email_id.in_(keys))).all()
    return {(str(row.account_id), row.raw_email_id): row.trade_id for row in rows}


def _row(trade: Trade, state: str | None = None) -> dict:
    return {"trade_id": str(trade.id), "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration),
            "opened_at": stamp(trade.opened_at), "closed_at": stamp(trade.closed_at), "status": trade.status,
            "realized_pnl": number(trade.realized_pnl), "state": state}


def _options(db: Session, scope: dict):
    return select(Trade).where(Trade.account_id.in_(list(scope)), Trade.instrument_type == "option")


def week_trades(db: Session, week_start: date) -> list[Trade]:
    scope = _scope(db)
    if not scope:
        return []
    start, end = _bounds(week_start)
    return list(db.exec(_options(db, scope).where(Trade.status.in_(("closed", "expired")), Trade.realized_pnl.is_not(None),
                                                  Trade.closed_at >= start, Trade.closed_at < end)
                        .order_by(Trade.closed_at, Trade.id)).all())


def leaks(db: Session, trades: list[Trade]) -> list[dict]:
    paths = _paths(db, trades)
    out = []
    for key, rule in RULES.items():
        states = [(trade, judge(key, rule["params"], trade, paths.get(trade.id))) for trade in trades]
        broke = [trade for trade, state in states if state == "broke"]
        out.append({"key": key, "label": rule["label"], "rule_text": rule["text"], "count": len(broke),
                    "pnl": round(sum(float(t.realized_pnl) for t in broke), 2),
                    "unmeasured": sum(state == "unmeasured" for _, state in states),
                    "trades": [_row(trade, "broke") for trade in broke]})
    return out


def suggest(tested: int, broke: int) -> str:
    if broke == 0:
        return "kept" if tested >= MIN_TESTED else "not_enough"
    return "broken" if broke == tested else "partly"


def check(db: Session, record: WeeklyReviewRecord) -> dict:
    """How the rule chosen in ``record`` went: trades entered after it was chosen, up to the end of the following week."""
    params = json.loads(record.rule_params_json or "{}")
    scope = _scope(db)
    start = _ny(record.chosen_at)
    _, end = _bounds(record.week_start + timedelta(days=7))
    pool = list(db.exec(_options(db, scope).where(Trade.opened_at >= datetime.combine(start.date(), datetime.min.time()),
                                                  Trade.opened_at < end).order_by(Trade.opened_at, Trade.id)).all()) if scope else []
    order_unclear = [t for t in pool if not reliable(t.opened_at) and t.opened_at.date() == start.date()]
    entered = [t for t in pool if t not in order_unclear and (t.opened_at >= start or not reliable(t.opened_at))]
    done = [t for t in entered if t.status in ("closed", "expired") and t.realized_pnl is not None]
    still_open = [t for t in entered if t not in done]
    paths = _paths(db, done)
    judged = [(trade, judge(record.rule_key, params, trade, paths.get(trade.id))) for trade in done]
    shown = [(trade, state) for trade, state in judged if state != "untested"]
    tested = sum(state in ("kept", "broke") for _, state in shown)
    broke = sum(state == "broke" for _, state in shown)
    anchors = _anchors(db, [trade for trade, _ in shown])
    return {
        "entered": len(entered), "closed": len(done), "tested": tested, "broke": broke,
        "kept": tested - broke, "unmeasured": sum(state == "unmeasured" for _, state in shown),
        "order_unclear": len(order_unclear), "suggested": suggest(tested, broke),
        "trades": [_row(trade, state) for trade, state in shown],
        "still_open": [_row(trade) for trade in still_open],
        "anchors": [[str(anchors[t.id][0]), anchors[t.id][1]] if t.id in anchors else None for t, _ in shown],
    }


def _rule(record: WeeklyReviewRecord) -> dict:
    rule = RULES.get(record.rule_key or "")
    return {"week_start": record.week_start.isoformat(), "rule_key": record.rule_key, "rule_text": rule["text"] if rule else None,
            "label": rule["label"] if rule else None, "params": json.loads(record.rule_params_json or "{}"),
            "note": record.note, "chosen_at": stamp(_ny(record.chosen_at)), "result": record.result,
            "result_source": record.result_source}


def _frozen(db: Session, record: WeeklyReviewRecord) -> dict:
    """The evidence as it was confirmed, each trade re-resolved through its source fill."""
    evidence = json.loads(record.evidence_json)
    current = _resolve(db, [tuple(row["anchor"]) for row in evidence["trades"] if row.get("anchor")])
    trades = []
    for row in evidence["trades"]:
        trade_id = current.get(tuple(row["anchor"])) if row.get("anchor") else None
        trades.append({**{k: v for k, v in row.items() if k != "anchor"}, "trade_id": str(trade_id) if trade_id else None})
    return {**{k: v for k, v in evidence.items() if k != "trades"}, "trades": trades, "frozen": True,
            "checked_at": stamp(_ny(record.checked_at)) if record.checked_at else None}


def view(db: Session, week_start: date) -> dict:
    trades = week_trades(db, week_start)
    records = {r.week_start: r for r in db.exec(select(WeeklyReviewRecord).where(WeeklyReviewRecord.week_start <= week_start)).all()}
    current, previous = records.get(week_start), records.get(week_start - timedelta(days=7))
    prior = None
    if previous is not None:
        prior = _rule(previous)
        if previous.rule_key:
            prior["check"] = _frozen(db, previous) if previous.evidence_json else {**check(db, previous), "frozen": False}
            prior["check"].pop("anchors", None)
    paths = _paths(db, trades)
    wins = sum(float(t.realized_pnl) > 0 for t in trades)
    history = sorted((r for d, r in records.items() if d < week_start), key=lambda r: r.week_start, reverse=True)[:HISTORY]
    return {
        "week_start": week_start.isoformat(), "week_end": (week_start + timedelta(days=4)).isoformat(),
        "in_progress": week_start == this_monday(),
        "summary": {"trades": len(trades), "pnl": round(sum(float(t.realized_pnl) for t in trades), 2),
                    "wins": wins, "losses": sum(float(t.realized_pnl) < 0 for t in trades)},
        "coverage": {"trades": len(trades), "with_path": sum(1 for t in trades if paths.get(t.id) and paths[t.id].option_mfe_pct is not None),
                     "accounts": sorted({a.name for a in _scope(db).values()})},
        "leaks": leaks(db, trades),
        "previous": prior,
        "chosen": _rule(current) if current else None,
        "history": [_rule(r) for r in history],
        "rules": [{"key": key, "label": rule["label"], "rule_text": rule["text"]} for key, rule in RULES.items()],
    }


def choose(db: Session, week_start: date, rule_key: str | None, note: str | None) -> WeeklyReviewRecord:
    """Save (or change) the rule to practise after this week; None skips the week."""
    if rule_key is not None and rule_key not in RULES:
        raise ReviewError("Unknown rule.")
    note = (note or "").strip()[:280] or None
    now = utc_now_naive()
    record = db.exec(select(WeeklyReviewRecord).where(WeeklyReviewRecord.week_start == week_start)).first()
    new = record is None
    if new:
        record = WeeklyReviewRecord(week_start=week_start, created_at=now)
    elif record.rule_key != rule_key and record.result is not None:
        raise ReviewError("This rule has already been checked, so it can't be changed.")
    if new or record.rule_key != rule_key:
        # A new or changed rule starts its practice window now, with today's thresholds frozen.
        record.chosen_at = now
        record.rule_params_json = json.dumps(RULES[rule_key]["params"]) if rule_key else None
    record.rule_key, record.note, record.updated_at = rule_key, note, now
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def confirm(db: Session, week_start: date, result: str) -> WeeklyReviewRecord:
    """Record how last week's rule went, reviewed in ``week_start``'s review; the evidence freezes the first time."""
    if result not in RESULTS:
        raise ReviewError("Unknown result.")
    record = db.exec(select(WeeklyReviewRecord).where(WeeklyReviewRecord.week_start == week_start - timedelta(days=7))).first()
    if record is None or not record.rule_key:
        raise ReviewError("No rule was chosen last week, so there is nothing to check.")
    now = utc_now_naive()
    if record.evidence_json is None:
        found = check(db, record)
        anchors = found.pop("anchors")
        found["trades"] = [{**row, "anchor": anchor} for row, anchor in zip(found["trades"], anchors)]
        found["still_open"] = [{**row, "trade_id": None} for row in found["still_open"]]
        record.evidence_json = json.dumps(found)
        record.checked_at = now
    suggested = json.loads(record.evidence_json)["suggested"]
    record.result, record.result_source, record.updated_at = result, "suggested" if result == suggested else "changed", now
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
