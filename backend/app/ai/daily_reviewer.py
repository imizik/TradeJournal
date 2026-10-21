import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

from dotenv import load_dotenv
from sqlmodel import Session, select

from app.models import Account, DailyReviewRecord, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")


REVIEW_FIELDS = ("summary", "day_grade", "key_takeaways", "best_trade", "worst_trade", "patterns", "next_session_rules")
PROMPT_VERSION = 3
BASELINE_DAYS = 20
PRIOR_REVIEWS = 3


def review_trading_day(
    day: str,
    trades: list[Trade],
    fills_by_trade_id: dict[str, list[Fill]],
    session: Session,
    backend: str | None = None,
) -> dict:
    """One day's review, from Claude on the owner's plan (app.ai.plan_runner).

    The Anthropic API is used only when ``AI_REVIEW_BACKEND=api`` is set
    explicitly and the caller does not pin ``backend="plan"`` (the nightly run
    always does); nothing falls back to it.
    """
    context = _assemble_daily_context(day, trades, fills_by_trade_id, session)
    context["history"] = _history_context(date.fromisoformat(day), session)
    from app.ai import review_context

    context["day_context"] = review_context.build(session, date.fromisoformat(day), trades)
    message = f"Review this trading day:\n\n{json.dumps(context, indent=2, default=str)}"
    chosen = backend or os.environ.get("AI_REVIEW_BACKEND", "plan").strip().lower()
    if chosen == "api":
        review = _review_with_api(message)
        review["generated_by"] = f"{os.environ.get('ANTHROPIC_MODEL', 'claude-opus-4-7')} through the Anthropic API"
    else:
        from app.ai import plan_runner

        answer = plan_runner.ask(_SYSTEM_PROMPT, message, REVIEW_SCHEMA)
        review = answer.data
        review["generated_by"] = answer.author
        review["usage"] = {"input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens,
                           "api_equivalent_usd": answer.api_equivalent_usd, "seconds": answer.seconds}
    missing = [field for field in REVIEW_FIELDS if field not in review]
    if missing:
        raise ValueError(f"AI response missing required fields: {', '.join(missing)}")
    valid_thought_ids = {row["id"] for row in context["day_context"].get("owner_timeline", [])}
    checks = review.get("expectation_checks")
    if isinstance(checks, list):
        accepted = [item for item in checks if isinstance(item, dict) and item.get("entry_id") in valid_thought_ids]
        if len(accepted) != len(checks):
            review["data_gaps"] = list(review.get("data_gaps") or [])
            review["data_gaps"].append("An expectation check referenced a thought that was not in this day's saved timeline; that check was omitted")
        review["expectation_checks"] = accepted
    for field in ("owner_timeline_truncated_count", "owner_timeline_text_truncated_count"):
        count = context["day_context"].get(field, 0)
        if count:
            review[field] = count
    review["prompt_version"] = PROMPT_VERSION
    return review


def _review_with_api(message: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
        max_tokens=4000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"{message}\n\nAnswer with one JSON object matching this schema:\n{json.dumps(REVIEW_SCHEMA)}"}],
    )
    response_text = ""
    try:
        response_text = response.content[0].text
        return _parse_json_response(response_text)
    except (json.JSONDecodeError, IndexError, AttributeError) as exc:
        raise ValueError(f"Failed to parse AI response as JSON: {exc}. Response starts: {response_text[:300]!r}") from exc


def _history_context(review_day: date, session: Session) -> dict:
    """What the coach needs to judge the day against: the rules it set before and the trader's normal."""
    prior = session.exec(
        select(DailyReviewRecord).where(DailyReviewRecord.day < review_day).order_by(DailyReviewRecord.day.desc()).limit(PRIOR_REVIEWS)
    ).all()
    prior_reviews = []
    for record in prior:
        try:
            saved = json.loads(record.review_json)
        except ValueError:
            continue
        prior_reviews.append({"day": record.day.isoformat(), "days_before": (review_day - record.day).days,
                              "day_grade": saved.get("day_grade"), "next_session_rules": saved.get("next_session_rules") or []})

    # The trader's normal: the last BASELINE_DAYS days with trades before this one.
    window_start = review_day - timedelta(days=BASELINE_DAYS * 3)
    earlier = session.exec(
        select(Trade).where(Trade.opened_at >= datetime.combine(window_start, datetime.min.time()),
                            Trade.opened_at < datetime.combine(review_day, datetime.min.time()))
    ).all()
    days = sorted({trade.opened_at.date() for trade in earlier}, reverse=True)[:BASELINE_DAYS]
    in_window = [trade for trade in earlier if trade.opened_at.date() in set(days)]
    closed = [trade for trade in in_window if trade.status in {"closed", "expired"} and trade.realized_pnl is not None]
    wins = [float(trade.realized_pnl) for trade in closed if trade.realized_pnl > 0]
    losses = [float(trade.realized_pnl) for trade in closed if trade.realized_pnl < 0]
    premiums = [float(trade.total_premium_paid) for trade in in_window if trade.total_premium_paid]
    holds = [trade.hold_duration_mins for trade in closed if trade.hold_duration_mins is not None]
    by_day: dict[date, float] = {}
    for trade in closed:
        by_day[trade.opened_at.date()] = by_day.get(trade.opened_at.date(), 0.0) + float(trade.realized_pnl)
    baseline = {
        "trading_days": len(days),
        "first_day": days[-1].isoformat() if days else None,
        "trades_per_day": round(len(in_window) / len(days), 1) if days else None,
        "median_premium_per_trade": round(median(premiums), 2) if premiums else None,
        "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "median_hold_mins": median(holds) if holds else None,
        "avg_day_pnl": round(sum(by_day.values()) / len(by_day), 2) if by_day else None,
        "worst_day_pnl": round(min(by_day.values()), 2) if by_day else None,
    } if days else None
    return {"prior_reviews": prior_reviews, "baseline": baseline}


def _assemble_daily_context(
    day: str,
    trades: list[Trade],
    fills_by_trade_id: dict[str, list[Fill]],
    session: Session,
) -> dict:
    review_day = date.fromisoformat(day)
    account_ids = {trade.account_id for trade in trades}
    accounts = session.exec(select(Account).where(Account.id.in_(account_ids))).all() if account_ids else []
    account_map = {account.id: account for account in accounts}

    trade_fill_roles: dict[str, dict[str, str]] = {}
    trade_ids = [trade.id for trade in trades]
    if trade_ids:
        trade_fills = session.exec(select(TradeFill).where(TradeFill.trade_id.in_(trade_ids))).all()
        for tf in trade_fills:
            trade_fill_roles.setdefault(str(tf.trade_id), {})[str(tf.fill_id)] = tf.role

    # Fetch Alpaca context for all fills in one batch
    all_fill_ids = [fill.id for fills in fills_by_trade_id.values() for fill in fills]
    alpaca_context_map: dict[str, FillMarketContext] = {}
    if all_fill_ids:
        ctx_rows = session.exec(
            select(FillMarketContext).where(FillMarketContext.fill_id.in_(all_fill_ids))
        ).all()
        alpaca_context_map = {str(row.fill_id): row for row in ctx_rows}

    path_metrics_map: dict[str, TradePathMetrics] = {}
    if trade_ids:
        path_rows = session.exec(
            select(TradePathMetrics).where(TradePathMetrics.trade_id.in_(trade_ids))
        ).all()
        path_metrics_map = {str(row.trade_id): row for row in path_rows}

    trade_context = []
    for trade in trades:
        opened_today = trade.opened_at.date() == review_day if trade.opened_at else False
        closed_today = trade.closed_at.date() == review_day if trade.closed_at else False
        activity_today = []
        if opened_today:
            activity_today.append("opened")
        if closed_today:
            activity_today.append("closed")

        fills = fills_by_trade_id.get(str(trade.id), [])
        account = account_map.get(trade.account_id)
        fill_roles = trade_fill_roles.get(str(trade.id), {})
        trade_context.append(
            {
                "id": str(trade.id),
                "activity_today": activity_today,
                "opened_today": opened_today,
                "closed_today": closed_today,
                "account": {
                    "name": account.name if account else None,
                    "type": account.type if account else None,
                    "last4": account.last4 if account else None,
                },
                "ticker": trade.ticker,
                "instrument_type": trade.instrument_type,
                "option_type": trade.option_type,
                "strike": _float_or_none(trade.strike),
                "expiration": trade.expiration.isoformat() if trade.expiration else None,
                "contracts": _float_or_none(trade.contracts),
                "avg_entry_premium": _float_or_none(trade.avg_entry_premium),
                "avg_exit_premium": _float_or_none(trade.avg_exit_premium),
                "total_premium_paid": _float_or_none(trade.total_premium_paid),
                "realized_pnl": _float_or_none(trade.realized_pnl),
                "pnl_pct": _float_or_none(trade.pnl_pct),
                "hold_duration_mins": trade.hold_duration_mins,
                "entry_time_bucket": trade.entry_time_bucket,
                "expired_worthless": trade.expired_worthless,
                "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
                "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
                "status": trade.status,
                "path_metrics": _path_context(path_metrics_map.get(str(trade.id))),
                "fills": [_fill_context(fill, fill_roles.get(str(fill.id)), alpaca_context_map.get(str(fill.id))) for fill in fills],
            }
        )

    closed = [trade for trade in trades if trade.status in {"closed", "expired"}]
    winners = [trade for trade in closed if trade.realized_pnl is not None and trade.realized_pnl > 0]
    opened_today_count = len([trade for trade in trades if trade.opened_at and trade.opened_at.date() == review_day])
    closed_today_count = len([trade for trade in trades if trade.closed_at and trade.closed_at.date() == review_day])
    same_day_count = len([
        trade
        for trade in trades
        if trade.opened_at
        and trade.closed_at
        and trade.opened_at.date() == review_day
        and trade.closed_at.date() == review_day
    ])

    # Aggregate behavioral flags across all entry fills
    entry_contexts = [
        alpaca_context_map[str(fill.id)]
        for fills in fills_by_trade_id.values()
        for fill in fills
        if fill.side in {"buy_to_open", "sell_to_open", "buy"} and str(fill.id) in alpaca_context_map
    ]
    total_entries = len(entry_contexts)

    def _flag_count(attr: str) -> int:
        return sum(1 for ctx in entry_contexts if getattr(ctx, attr) == 1)

    behavioral_flags = {
        "total_entry_fills_with_context": total_entries,
        "chase_entry_count": _flag_count("is_chase_entry"),
        "trend_aligned_count": _flag_count("is_trend_aligned"),
        "late_move_count": _flag_count("is_late_move"),
        "vwap_reclaim_count": _flag_count("is_vwap_reclaim"),
        "or_breakout_count": _flag_count("is_opening_range_breakout"),
        "premarket_breakout_count": _flag_count("is_premarket_breakout"),
        "near_resistance_count": _flag_count("is_near_resistance_on_call_entry"),
        "near_support_count": _flag_count("is_near_support_on_put_entry"),
    } if entry_contexts else None

    return {
        "day": day,
        "summary_stats": {
            "trade_count": len(trades),
            "opened_today_count": opened_today_count,
            "closed_today_count": closed_today_count,
            "same_day_count": same_day_count,
            "closed_count": len(closed),
            "open_count": len([trade for trade in trades if trade.status == "open"]),
            "realized_pnl": round(sum(float(trade.realized_pnl or 0) for trade in trades), 2),
            "win_rate": round(len(winners) / len(closed), 4) if closed else None,
            "premium_risked": round(sum(float(trade.total_premium_paid or 0) for trade in trades), 2),
            "tickers": sorted({trade.ticker for trade in trades}),
            "behavioral_flags": behavioral_flags,
        },
        "trades": trade_context,
    }


def _fill_context(fill: Fill, role: str | None, alpaca: FillMarketContext | None = None) -> dict:
    base = {
        "id": str(fill.id),
        "role": role,
        "executed_at": fill.executed_at.isoformat() if fill.executed_at else None,
        "side": fill.side,
        "contracts": _float_or_none(fill.contracts),
        "price": _float_or_none(fill.price),
        "underlying_price_at_fill": _float_or_none(fill.underlying_price_at_fill),
        "vwap_at_fill": _float_or_none(fill.vwap_at_fill),
        "iv_at_fill": _float_or_none(fill.iv_at_fill),
        "delta_at_fill": _float_or_none(fill.delta_at_fill),
        "gamma_at_fill": _float_or_none(fill.gamma_at_fill),
        "theta_at_fill": _float_or_none(fill.theta_at_fill),
        "vega_at_fill": _float_or_none(fill.vega_at_fill),
        "sma_20_at_fill": _float_or_none(fill.sma_20_at_fill),
        "sma_50_at_fill": _float_or_none(fill.sma_50_at_fill),
        "ema_9_at_fill": _float_or_none(fill.ema_9_at_fill),
        "ema_20_at_fill": _float_or_none(fill.ema_20_at_fill),
        "ema_9h_at_fill": _float_or_none(fill.ema_9h_at_fill),
        "rsi_14_at_fill": _float_or_none(fill.rsi_14_at_fill),
        "macd_at_fill": _float_or_none(fill.macd_at_fill),
        "macd_signal_at_fill": _float_or_none(fill.macd_signal_at_fill),
    }
    if alpaca is not None:
        base["alpaca_context"] = {
            # Computed percentages — most actionable for coaching
            "entry_vs_vwap_pct": _float_or_none(alpaca.entry_vs_vwap_pct),
            "entry_vs_ema9_pct": _float_or_none(alpaca.entry_vs_ema9_pct),
            "entry_rsi_14": _float_or_none(alpaca.entry_rsi_14),
            "entry_atr_14": _float_or_none(alpaca.entry_atr_14),
            "entry_macd_histogram": _float_or_none(alpaca.entry_macd_histogram),
            "entry_gap_pct": _float_or_none(alpaca.entry_gap_pct),
            "simple_relative_volume": _float_or_none(alpaca.simple_relative_volume),
            "entry_day_range_used_pct": _float_or_none(alpaca.entry_day_range_used_pct),
            "entry_distance_from_day_high_pct": _float_or_none(alpaca.entry_distance_from_day_high_pct),
            "entry_distance_from_day_low_pct": _float_or_none(alpaca.entry_distance_from_day_low_pct),
            "entry_time_bucket": alpaca.entry_time_bucket,
            "dte_bucket": alpaca.dte_bucket,
            # Behavioral flags (1=yes, 0=no, null=no data)
            "is_chase_entry": alpaca.is_chase_entry,
            "is_trend_aligned": alpaca.is_trend_aligned,
            "is_late_move": alpaca.is_late_move,
            "is_vwap_reclaim": alpaca.is_vwap_reclaim,
            "is_opening_range_breakout": alpaca.is_opening_range_breakout,
            "is_premarket_breakout": alpaca.is_premarket_breakout,
            "is_near_resistance_on_call_entry": alpaca.is_near_resistance_on_call_entry,
            "is_near_support_on_put_entry": alpaca.is_near_support_on_put_entry,
            "is_overnight": alpaca.is_overnight,
        }
    return base


def _path_context(path: TradePathMetrics | None) -> dict | None:
    if path is None:
        return None
    return {
        "data_source": path.data_source,
        "hold_duration_bucket": path.hold_duration_bucket,
        "exit_time_bucket": path.exit_time_bucket,
        "underlying_mfe_pct": _float_or_none(path.underlying_mfe_pct),
        "underlying_mae_pct": _float_or_none(path.underlying_mae_pct),
        "underlying_exit_efficiency": _float_or_none(path.underlying_exit_efficiency),
        "underlying_giveback_pct": _float_or_none(path.underlying_giveback_pct),
        "moved_in_favor_first": path.moved_in_favor_first,
        "option_mfe_pct": _float_or_none(path.option_mfe_pct),
        "option_mae_pct": _float_or_none(path.option_mae_pct),
        "option_max_price_seen": _float_or_none(path.option_max_price_seen),
        "option_min_price_seen": _float_or_none(path.option_min_price_seen),
        "time_to_option_mfe_minutes": path.time_to_option_mfe_minutes,
        "option_exit_efficiency": _float_or_none(path.option_exit_efficiency),
        "option_giveback_pct": _float_or_none(path.option_giveback_pct),
        "option_peak_unrealized_pnl": _float_or_none(path.option_peak_unrealized_pnl),
        "option_worst_unrealized_pnl": _float_or_none(path.option_worst_unrealized_pnl),
        "option_giveback_from_peak": _float_or_none(path.option_giveback_from_peak),
    }


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_json_response(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


_TRADE_PICK = {
    "type": "object",
    "additionalProperties": False,
    "required": ["trade_id", "ticker", "reason"],
    "properties": {"trade_id": {"type": ["string", "null"]}, "ticker": {"type": ["string", "null"]}, "reason": {"type": "string"}},
}
REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [*REVIEW_FIELDS, "rules_check", "vs_baseline", "data_gaps", "market_read", "plan_vs_execution"],
    "properties": {
        "summary": {"type": "string"},
        "day_grade": {"type": "string"},
        "key_takeaways": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "best_trade": _TRADE_PICK,
        "worst_trade": _TRADE_PICK,
        "patterns": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "next_session_rules": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "rules_check": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["rule", "set_on", "result", "evidence"],
            "properties": {"rule": {"type": "string"}, "set_on": {"type": "string"},
                           "result": {"enum": ["kept", "broken", "partly", "not_tested"]}, "evidence": {"type": "string"}}}},
        "vs_baseline": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "market_read": {"type": "string"},
        "plan_vs_execution": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["ticker", "planned", "did", "result"],
            "properties": {"ticker": {"type": "string"}, "planned": {"type": "string"}, "did": {"type": "string"},
                           "result": {"enum": ["followed", "deviated", "partly", "no_plan"]}}}},
        "expectation_checks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["entry_id", "expected", "observed", "assessment", "evidence"],
            "properties": {"entry_id": {"type": "string"}, "expected": {"type": "string"},
                           "observed": {"type": "string"},
                           "assessment": {"enum": ["supported", "invalidated", "mixed", "unresolved"]},
                           "evidence": {"type": "string"}}}},
        "data_gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
}

_SYSTEM_PROMPT = """You are the trading coach for one retail trader who mostly day-trades and scalps US equity options,
reviewing one day from their own journal. Your job is to make tomorrow better, not to narrate today.

You receive JSON: summary_stats, trades (each with fills, enrichment and path_metrics) and history. A trade is included
when it opened or closed on the review day; use activity_today / opened_today / closed_today to separate entry decisions
from exit decisions.

## How to judge

- Grade the process, not the P&L. A rule-following loss can be a B; a lucky, oversized, chased winner is not an A.
  day_grade is "<letter A-F>: <one-line reason about decisions>". Mention the P&L in the summary, not as the grade.
- Pick best_trade and worst_trade by decision quality (entry, size, exit), not by dollars. Use null ids only when the day
  has no trades of that kind.
- Separate "never worked" from "worked, then given back": a small loss after a large option_peak_unrealized_pnl is an
  exit problem; a trade that went against them immediately is an entry problem.
- Judge size and frequency against history.baseline (the trader's own last trading days): more trades than usual,
  premium well above their median, or a loss larger than their average loss are coaching points. Put the clear
  differences in vs_baseline as short sentences with both numbers ("6 trades vs usual 3.5"). Empty when nothing stands out
  or there is no baseline.
- Check the rules from the most recent entry in history.prior_reviews against today, one rules_check item per rule,
  with set_on as that review's day: "kept", "broken", "partly", or "not_tested" when today gave no chance to test it.
  evidence names the trade(s) and the facts. Empty when there are no prior rules, or when that review's days_before is
  more than 4 (its rules were not the ones in force for this day).
- Every takeaway and pattern must point at evidence in the JSON: ticker and time, or the field and value. Never invent
  prices, levels, news or data that is not in the JSON. Fields are nullable; when missing data limits a judgement, say
  so in data_gaps (e.g. "No path metrics for 2 of 4 trades, so exit quality is unknown") instead of guessing.
- One-off observations are takeaways; patterns need two or more trades (today) or a repeat of a broken prior rule.

## Using day_context

day_context holds what was around the trades. Use it to judge decisions in their setting, not to explain P&L away:
- owner_timeline contains the owner's saved outlook and timestamped thoughts for this day. Compare each concrete expectation
  with observed market/trade evidence only when that evidence is present. If useful, return expectation_checks with the exact
  thought id, a concise expected and observed statement, assessment supported / invalidated / mixed / unresolved, and evidence
  naming the thought id plus source and time. Retrospective entries were saved after their stated day; never present their
  wording as a premarket forecast. Missing or insufficient market evidence means unresolved. Do not invent prices or levels.
  Keep forecast accuracy separate from adherence: following a valid plan can still lead to a forecast miss, and a correct
  forecast does not prove that the trader followed their plan.
  Market bars include source_bar_at (UTC) when available. Cite the thought id and relevant source bar time in evidence;
  if no source timestamp or value is available, leave the check unresolved. If owner_timeline_truncated_count or
  owner_timeline_text_truncated_count is present, some journal context was capped; disclose that limitation in data_gaps.
- plans: what the trader captured before entering (by_trade, with minutes_before_entry) and plans never traded
  (not_traded). This is the most important input when present: compare each plan with what was done (instrument,
  side, strike, size, timing) in plan_vs_execution, one item per traded plan; a traded position with no plan is
  "no_plan" only when other trades that day had plans. Empty when there are no plans. A plan not traded is not a
  mistake by itself; mention it only if it would have been the better trade by the facts given.
- market: when partial_as_of is set the review ran during the session, so every market and ticker number is intraday
  as of that time, not the close. The indexes' day (change, gap, close_in_range, range_vs_20d), SPY/QQQ intraday shape (trend_efficiency near
  1 is a trend day, near 0 chop; close_vs_vwap_pct; when the high and low printed) and VIX / 10-year yield.
  market_read is one or two sentences: what kind of day it was and whether the trader traded with it or against it
  (e.g. buying calls into a chop day with VIX up). Say "Market context unavailable" when it is missing.
- macro: FOMC, CPI and jobs releases that day or the next trading day, with New York times. Trades opened shortly before a
  release, or held through one, carry event risk worth naming.
- tickers: each underlying's move against SPY and its sector ETF (relative strength), earnings within a week
  (days_before / days_after; a report on the day itself has no known time of day), the day's headlines (observed,
  never proof of cause; a ticker without headlines had none found), option open-interest walls from the latest snapshot within five days (as_of_session; strikes
  where open interest clusters near the price), your_alerts_fired (the trader's own
  price alerts that day) and your_saved_levels_now (the trader's CURRENT saved levels: they may have been added or
  moved after this day, so treat them as a hint, never as proof the level existed then).
- tags: the trader's own labels on trades.
- gaps: parts that were unavailable; carry the ones that limit a judgement into data_gaps.

## next_session_rules

At most three. Each must be specific and checkable from the journal tomorrow, e.g. "No call entries after 80% of
the day's range is used" or "Max 2 contracts until 2 green trades". Prefer keeping or tightening a prior rule
that was broken over inventing a new one. No generic advice ("stay disciplined", "trust your plan").

## Style

Plain, direct, short sentences. Write for the trader, second person, in trading words: say "a choppy day", "80% of
the day's range", "below VWAP", never the JSON field names (trend_efficiency, close_in_range, ...); numbers are fine. No hedging boilerplate, no motivational language,
no recommendation to buy or sell any security.

## history

- prior_reviews: up to three earlier saved reviews, newest first: their day, days_before (calendar days before this
  one), grade and next_session_rules.
- baseline: the trader's last trading days before this one (trading_days, trades_per_day, median_premium_per_trade,
  win_rate, avg_win, avg_loss, median_hold_mins, avg_day_pnl, worst_day_pnl). Null when there is no earlier trading.

## Fill enrichment data

Each fill may contain two enrichment layers — all fields are nullable; only reference them when present.

**Polygon layer** (on the fill itself): underlying_price_at_fill, vwap_at_fill, iv_at_fill, delta/gamma/theta/vega,
moving averages (sma_20, sma_50, ema_9, ema_20, ema_9h), rsi_14, macd, macd_signal.

**Alpaca layer** (in alpaca_context sub-object):
- entry_vs_vwap_pct: how far above/below VWAP at entry (positive = above VWAP = buying strength or chasing)
- entry_vs_ema9_pct: distance from 9-period EMA (large positive means extended)
- entry_rsi_14: RSI at entry time (>70 overbought, <30 oversold)
- entry_atr_14: daily ATR for volatility context
- entry_macd_histogram: momentum direction at entry
- entry_gap_pct: today's open vs prior close
- simple_relative_volume: RVOL vs 20-day average (>1.5 = elevated, >2.0 = strong)
- entry_day_range_used_pct: how much of the day's range was consumed at entry time (>80% = late in the move)
- entry_distance_from_day_high_pct / entry_distance_from_day_low_pct: proximity to day extremes
- entry_time_bucket / dte_bucket: time of day and days-to-expiry buckets

**Behavioral flags** (1=yes, 0=no, null=no data):
- is_chase_entry: entered significantly above VWAP on a buy, or below VWAP on a short
- is_trend_aligned: entry direction matches daily trend (price above EMA-9 on call, below on put)
- is_late_move: entered after >70% of the day's range was already consumed
- is_vwap_reclaim: price was below VWAP but reclaimed it near entry
- is_opening_range_breakout: price broke above/below the 5- or 15-minute opening range
- is_premarket_breakout: price broke above premarket highs
- is_near_resistance_on_call_entry: call entry near a known resistance level (day high, OR high, PM high)
- is_near_support_on_put_entry: put entry near a known support level
- is_overnight: position held overnight

## Trade path metrics

Each trade may include path_metrics. These are precomputed summaries, not raw bars:
- underlying_mfe_pct / underlying_mae_pct: best and worst underlying move while the trade was open
- underlying_exit_efficiency / underlying_giveback_pct: how much favorable underlying move was captured or given back
- option_mfe_pct / option_mae_pct: best and worst option contract move while the trade was open
- option_peak_unrealized_pnl: maximum open P&L seen during the trade
- option_worst_unrealized_pnl: worst open P&L seen during the trade
- option_giveback_from_peak: dollars surrendered from peak open P&L to realized P&L
- option_exit_efficiency: realized P&L divided by peak open P&L

Use path_metrics to distinguish trades that were never working from trades that worked and then reversed.
A small realized loss after a large positive option_peak_unrealized_pnl is an exit/risk-management issue, not the same
as a trade that immediately failed.

## summary_stats.behavioral_flags

The summary_stats object includes aggregated flag counts across all entry fills that have Alpaca context.
Cross-reference these with P&L outcomes. For example: if chase_entry_count is high and the day was a net loser,
that is a key coaching point. If trend_aligned_count is high and winners outperformed, note the confirmation.

## Answer

Answer in the given JSON schema only: summary (2-4 sentences, include the day's P&L and the one thing that mattered most),
day_grade, market_read, key_takeaways (up to 3), best_trade, worst_trade, patterns (up to 4), plan_vs_execution,
next_session_rules (up to 3), rules_check, vs_baseline, data_gaps.
"""
