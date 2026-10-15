"""One calendar month's review: where the P&L came from and leaked, the habits
that repeat, how the daily rules held up, and one commitment for next month.

The coach gets statistics, not fills: trades that closed in the month (New
York calendar, the dashboard's rule), broken down by ticker, time of day, hold
time, side, days to expiry, entry flags, size, weekday, with or without a
captured plan, and SPY's day; the month's daily reviews (grades, rules kept and
broken, patterns); last month's numbers and its commitment. Like the daily
review it asks Claude on the owner's plan (app.ai.plan_runner), never API
credits unless ``AI_REVIEW_BACKEND=api`` is set for the button.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import json
import logging
from statistics import median
from typing import Callable

from sqlmodel import Session, select

from app.models import CaptureLink, DailyReviewRecord, Fill, FillMarketContext, MonthlyReviewRecord, Trade, TradeFill, TradePathMetrics

log = logging.getLogger(__name__)
PROMPT_VERSION = 1
MIN_GROUP = 2  # a breakdown row needs at least this many trades
ENTRY_SIDES = {"buy_to_open", "sell_to_open", "buy"}
FIELDS = ("summary", "month_grade", "edge", "leaks", "recurring_patterns", "rules_scorecard", "last_commitment_check",
          "one_commitment", "vs_last_month", "data_gaps")


def month_bounds(month: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(month, "%Y-%m")
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end


def previous_month(month: str) -> str:
    start, _ = month_bounds(month)
    return (start - timedelta(days=1)).strftime("%Y-%m")


def closed_trades(session: Session, month: str) -> list[Trade]:
    start, end = month_bounds(month)
    return list(session.exec(select(Trade).where(Trade.status.in_(("closed", "expired")), Trade.realized_pnl.is_not(None),
                                                 Trade.closed_at >= start, Trade.closed_at < end).order_by(Trade.closed_at)).all())


def _row(trades: list[Trade]) -> dict:
    pnls = [float(trade.realized_pnl) for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    return {"trades": len(pnls), "pnl": round(sum(pnls), 2), "win_rate": round(len(wins) / len(pnls), 3) if pnls else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None, "avg_loss": round(sum(losses) / len(losses), 2) if losses else None}


def _breakdown(trades: list[Trade], key: Callable[[Trade], str | None]) -> list[dict]:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        value = key(trade)
        if value is not None:
            groups[value].append(trade)
    rows = [{"group": name, **_row(members)} for name, members in groups.items() if len(members) >= MIN_GROUP]
    return sorted(rows, key=lambda row: row["pnl"])


def _hold_bucket(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    return "under 5 min" if minutes < 5 else "5-30 min" if minutes < 30 else "30-120 min" if minutes < 120 else "same day, 2h+" if minutes < 390 else "multi-day"


def _time_bucket(opened: datetime) -> str:
    clock = opened.time()
    if clock < time(9, 30):
        return "premarket"
    if clock < time(10, 0):
        return "09:30-10:00"
    if clock < time(11, 0):
        return "10:00-11:00"
    if clock < time(14, 0):
        return "11:00-14:00"
    if clock < time(15, 0):
        return "14:00-15:00"
    return "15:00 and later" if clock < time(16, 0) else "after hours"


def month_stats(session: Session, month: str, gaps: list[str]) -> dict | None:
    trades = closed_trades(session, month)
    if not trades:
        return None
    ids = [trade.id for trade in trades]
    # First entry fill of each trade: its market context (flags, days to expiry) and its source identity (plans).
    entries: dict = {}
    for trade_id, fill in session.exec(select(TradeFill.trade_id, Fill).join(Fill, Fill.id == TradeFill.fill_id)
                                       .where(TradeFill.trade_id.in_(ids), Fill.side.in_(ENTRY_SIDES)).order_by(Fill.executed_at)).all():
        entries.setdefault(trade_id, fill)
    contexts = {row.fill_id: row for row in session.exec(select(FillMarketContext).where(
        FillMarketContext.fill_id.in_([fill.id for fill in entries.values()]))).all()} if entries else {}
    paths = {row.trade_id: row for row in session.exec(select(TradePathMetrics).where(TradePathMetrics.trade_id.in_(ids))).all()}
    planned_keys = set(session.exec(select(CaptureLink.source_key).where(
        CaptureLink.unlinked_at.is_(None), CaptureLink.source_key.in_([fill.raw_email_id for fill in entries.values()]))).all()) if entries else set()

    def context(trade: Trade) -> FillMarketContext | None:
        fill = entries.get(trade.id)
        return contexts.get(fill.id) if fill else None

    def flag(name: str) -> Callable[[Trade], str | None]:
        def read(trade: Trade) -> str | None:
            value = getattr(context(trade), name, None) if context(trade) else None
            return None if value is None else ("yes" if value == 1 else "no")
        return read

    # Thirds by rank, so each holds a third of the sized trades whatever their premiums.
    sized = sorted((trade for trade in trades if trade.total_premium_paid), key=lambda trade: float(trade.total_premium_paid))
    thirds = {trade.id: ("smallest third", "middle third", "largest third")[index * 3 // len(sized)]
              for index, trade in enumerate(sized)} if len(sized) >= 6 else {}

    def size(trade: Trade) -> str | None:
        return thirds.get(trade.id)

    spy = _spy_days(month, gaps)
    by_day: dict[date, float] = defaultdict(float)
    for trade in trades:
        by_day[trade.closed_at.date()] += float(trade.realized_pnl)
    with_context = sum(1 for trade in trades if context(trade))
    exits = [paths[trade.id] for trade in trades if trade.id in paths and paths[trade.id].option_exit_efficiency is not None]
    if with_context < len(trades):
        gaps.append(f"Entry market context for {with_context} of {len(trades)} trades, so flag and days-to-expiry breakdowns cover only those")
    pnls = [float(trade.realized_pnl) for trade in trades]
    gross_win, gross_loss = sum(p for p in pnls if p > 0), -sum(p for p in pnls if p < 0)
    return {
        "month": month,
        "overall": {**_row(trades), "trading_days": len(by_day),
                    "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
                    "best_day": _day(max(by_day.items(), key=lambda item: item[1])),
                    "worst_day": _day(min(by_day.items(), key=lambda item: item[1])),
                    "largest_win": round(max(pnls), 2), "largest_loss": round(min(pnls), 2),
                    "losing_days": sum(1 for value in by_day.values() if value < 0),
                    "median_exit_efficiency": round(median(float(p.option_exit_efficiency) for p in exits), 2) if exits else None,
                    "median_giveback_from_peak": round(median(float(p.option_giveback_from_peak) for p in exits
                                                              if p.option_giveback_from_peak is not None), 2)
                    if any(p.option_giveback_from_peak is not None for p in exits) else None},
        "by": {
            "ticker": _breakdown(trades, lambda t: t.ticker),
            "side": _breakdown(trades, lambda t: f"{t.instrument_type} {t.option_type or ''}".strip()),
            "entry_time": _breakdown(trades, lambda t: _time_bucket(t.opened_at)),
            "hold_time": _breakdown(trades, lambda t: _hold_bucket(t.hold_duration_mins)),
            "weekday": _breakdown(trades, lambda t: t.opened_at.strftime("%A")),
            "size": _breakdown(trades, size),
            "days_to_expiry": _breakdown(trades, lambda t: getattr(context(t), "dte_bucket", None)),
            "had_captured_plan": _breakdown(trades, lambda t: ("yes" if entries.get(t.id) and entries[t.id].raw_email_id in planned_keys else "no")),
            "spy_that_day": _breakdown(trades, lambda t: spy.get(t.opened_at.date())),
            "chase_entry": _breakdown(trades, flag("is_chase_entry")),
            "late_move_entry": _breakdown(trades, flag("is_late_move")),
            "trend_aligned": _breakdown(trades, flag("is_trend_aligned")),
            "call_near_resistance": _breakdown(trades, flag("is_near_resistance_on_call_entry")),
            "put_near_support": _breakdown(trades, flag("is_near_support_on_put_entry")),
            "expired_worthless": _breakdown(trades, lambda t: "yes" if t.expired_worthless else "no"),
        },
    }


def _day(item: tuple[date, float]) -> dict:
    return {"day": item[0].isoformat(), "pnl": round(item[1], 2)}


def _spy_days(month: str, gaps: list[str]) -> dict[date, str]:
    """SPY up or down (with how big) for each day of the month, from daily bars."""
    try:
        from app.engine import alpaca

        start, end = month_bounds(month)
        bars = alpaca.fetch_daily_bars(["SPY"], start.date() - timedelta(days=7), end.date() - timedelta(days=1)).get("SPY") or []
    except Exception as exc:
        gaps.append(f"SPY daily bars unavailable, so the SPY-day breakdown is empty ({type(exc).__name__})")
        return {}
    from app.engine import alpaca

    dated = [(alpaca._bar_et_date(bar), bar) for bar in bars]
    dated = [(day, bar) for day, bar in dated if day]
    out = {}
    for (_, before), (day, bar) in zip(dated, dated[1:]):
        change = (bar["c"] / before["c"] - 1) * 100
        out[day] = "SPY up >0.5%" if change > 0.5 else "SPY down >0.5%" if change < -0.5 else "SPY flat (within 0.5%)"
    return out


def daily_reviews_summary(session: Session, month: str) -> dict:
    start, end = month_bounds(month)
    records = session.exec(select(DailyReviewRecord).where(DailyReviewRecord.day >= start.date(), DailyReviewRecord.day < end.date())
                           .order_by(DailyReviewRecord.day)).all()
    grades, patterns, rules = [], [], defaultdict(Counter)
    for record in records:
        try:
            review = json.loads(record.review_json)
        except ValueError:
            continue
        grades.append({"day": record.day.isoformat(), "grade": str(review.get("day_grade") or "")[:1]})
        patterns.extend(review.get("patterns") or [])
        for check in review.get("rules_check") or []:
            rules[check.get("rule", "")][check.get("result", "not_tested")] += 1
    return {"reviewed_days": len(grades), "grades": grades, "patterns": patterns[:40],
            "rules_checked": [{"rule": rule, **counts} for rule, counts in rules.items()][:20]}


def last_commitment(session: Session, month: str) -> dict | None:
    record = session.exec(select(MonthlyReviewRecord).where(MonthlyReviewRecord.month == previous_month(month))).first()
    if record is None:
        return None
    try:
        review = json.loads(record.review_json)
    except ValueError:
        return None
    return {"month": record.month, "commitment": review.get("one_commitment"), "grade": review.get("month_grade")}


def build_context(session: Session, month: str) -> dict:
    gaps: list[str] = []
    stats = month_stats(session, month, gaps)
    if stats is None:
        raise LookupError(f"No closed trades in {month}")
    before = month_stats(session, previous_month(month), [])
    commitment = last_commitment(session, month)
    if commitment is None:
        gaps.append("No monthly review for last month, so there is no commitment to check")
    daily = daily_reviews_summary(session, month)
    if not daily["reviewed_days"]:
        gaps.append("No daily reviews this month, so rule keeping comes from the numbers alone")
    return {"this_month": stats, "last_month": before["overall"] if before else None, "last_commitment": commitment,
            "daily_reviews": daily, "gaps": gaps}


def review_month(session: Session, month: str, backend: str | None = None) -> tuple[dict, int]:
    """The month's review and how many closed trades it covered. Raises LookupError when there are none."""
    import os

    context = build_context(session, month)
    message = f"Review this trading month:\n\n{json.dumps(context, indent=2, default=str)}"
    chosen = backend or os.environ.get("AI_REVIEW_BACKEND", "plan").strip().lower()
    if chosen == "api":
        from app.ai.daily_reviewer import _parse_json_response
        from anthropic import Anthropic

        response = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY")).messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"), max_tokens=4000, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"{message}\n\nAnswer with one JSON object matching this schema:\n{json.dumps(SCHEMA)}"}])
        review = _parse_json_response(response.content[0].text)
        review["generated_by"] = f"{os.environ.get('ANTHROPIC_MODEL', 'claude-opus-4-7')} through the Anthropic API"
    else:
        from app.ai import plan_runner

        answer = plan_runner.ask(SYSTEM_PROMPT, message, SCHEMA)
        review = answer.data
        review["generated_by"] = answer.author
        review["usage"] = {"input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens,
                           "api_equivalent_usd": answer.api_equivalent_usd, "seconds": answer.seconds}
    missing = [field for field in FIELDS if field not in review]
    if missing:
        raise ValueError(f"AI response missing required fields: {', '.join(missing)}")
    review["prompt_version"] = PROMPT_VERSION
    return review, context["this_month"]["overall"]["trades"]


def generate(session: Session, month: str, backend: str | None = None) -> tuple[MonthlyReviewRecord, dict]:
    review, count = review_month(session, month, backend)
    record = session.exec(select(MonthlyReviewRecord).where(MonthlyReviewRecord.month == month)).first()
    now = datetime.utcnow()
    if record:
        record.review_json, record.trade_count, record.updated_at = json.dumps(review), count, now
    else:
        record = MonthlyReviewRecord(month=month, review_json=json.dumps(review), trade_count=count, created_at=now, updated_at=now)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record, review


_ITEM = {"type": "object", "additionalProperties": False, "required": ["finding", "evidence"],
         "properties": {"finding": {"type": "string"}, "evidence": {"type": "string"}}}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(FIELDS),
    "properties": {
        "summary": {"type": "string"},
        "month_grade": {"type": "string"},
        "edge": {"type": "array", "items": _ITEM, "maxItems": 3},
        "leaks": {"type": "array", "items": _ITEM, "maxItems": 3},
        "recurring_patterns": {"type": "array", "items": _ITEM, "maxItems": 4},
        "rules_scorecard": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["rule", "kept", "broken", "verdict"],
            "properties": {"rule": {"type": "string"}, "kept": {"type": "integer"}, "broken": {"type": "integer"},
                           "verdict": {"enum": ["keep", "tighten", "drop", "now_a_habit"]}}}, "maxItems": 6},
        "last_commitment_check": {"type": ["object", "null"], "additionalProperties": False, "required": ["commitment", "result", "evidence"],
                                  "properties": {"commitment": {"type": "string"}, "result": {"enum": ["kept", "broken", "partly", "unclear"]},
                                                 "evidence": {"type": "string"}}},
        "one_commitment": {"type": "string"},
        "vs_last_month": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "data_gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
}

SYSTEM_PROMPT = """You are the trading coach for one retail trader who mostly day-trades and scalps US equity options,
reviewing one calendar month from their own journal. The daily reviews coached each day; your job is the view a single
day cannot give: where this trader's money actually comes from, where it leaks, which habits repeat, and the ONE thing
to change next month.

You receive JSON:
- this_month.overall: closed trades (P&L counted on the close day), win rate, average win and loss, profit factor,
  best and worst day, largest win and loss, losing days, and the median exit efficiency and giveback from peak where
  path data exists.
- this_month.by: breakdowns (each row: group, trades, pnl, win_rate, avg_win, avg_loss; rows with fewer than two
  trades are left out) by ticker, side, entry_time, hold_time, weekday, size (premium thirds), days_to_expiry,
  had_captured_plan, spy_that_day, entry flags (chase_entry, late_move_entry, trend_aligned, call_near_resistance,
  put_near_support) and expired_worthless.
- daily_reviews: the month's daily grades, their patterns, and each daily rule with how often it was kept / broken /
  partly / not_tested.
- last_month: last month's overall numbers (null if none). last_commitment: last month's one commitment (null if none).
- gaps: what is missing.

## How to judge

- edge: up to three places the P&L comes from, each with the numbers (group, trades, P&L, win rate). Only groups with
  enough trades to mean something (say 5+); say when a sample is small.
- leaks: up to three biggest drains in dollars, each with the numbers, most expensive first. A leak is a group of trades
  the trader could stop taking or do differently (a time of day, a flag, a size, a ticker, holding too long), not bad luck.
- recurring_patterns: habits that repeat across days (from the breakdowns and the daily reviews' patterns), each with
  evidence.
- rules_scorecard: the daily rules that came up most, with kept and broken counts, and a verdict: keep (working, still
  needed), tighten (often broken or too loose), drop (never tested or not useful), now_a_habit (kept nearly always).
- last_commitment_check: was last month's commitment kept, by the numbers (null when there was none).
- one_commitment: ONE specific, measurable commitment for next month, aimed at the biggest leak, checkable from the
  journal (e.g. "No entries before 10:00 — that window lost $1,240 on 18 trades"). Not a list, not a slogan.
- month_grade: "<A-F>: <one line about process and consistency>". Grade the trading, not only the P&L.
- vs_last_month: the few changes that matter, both numbers each. Empty when there is no last month.
- data_gaps: missing data that limits a judgement.

Every claim cites numbers from the JSON. Each evidence line is plain words with the numbers ("24 trades, +$1,073, 75%
won"), never a quoted field or group name ("entry_time group", "win_rate 0.75"). Never invent data. No buy or sell
recommendations. Plain, direct trading words, second person.

Answer in the given JSON schema only."""
