import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlmodel import Session, select

from app.models import Fill, Trade, TradeFill, TradePathMetrics, TradeTag, Tag

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")

PROMPT_VERSION = 2
REVIEW_FIELDS = ("strategy", "flags", "summary", "entry_quality", "exit_quality", "suggestions")
REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [*REVIEW_FIELDS, "market_read", "plan_check", "data_gaps"],
    "properties": {
        "strategy": {"type": "string"},
        "flags": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "summary": {"type": "string"},
        "entry_quality": {"type": "string"},
        "exit_quality": {"type": "string"},
        "suggestions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "market_read": {"type": "string"},
        "plan_check": {"type": ["string", "null"]},
        "data_gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
}


def review_trade(
    trade: Trade,
    fills: list[Fill],
    companion_trades: Optional[list[Trade]] = None,
    stats: Optional[dict] = None,
    session: Optional[Session] = None,
    backend: str | None = None,
) -> dict:
    """One trade's review, from Claude on the owner's plan (app.ai.plan_runner), like the daily review.

    The Anthropic API is used only when ``AI_REVIEW_BACKEND=api`` is set explicitly; nothing falls back to it.
    The day's context (plans, market, sector, news, option walls, alerts) comes from ``review_context`` for
    the trade's New York open date.
    """
    context = _assemble_context(trade, fills, companion_trades, stats, session)
    if session is not None and trade.opened_at is not None:
        from app.ai import review_context

        context["day_context"] = review_context.build(session, trade.opened_at.date(), [trade])
    message = f"Review this trade:\n\n{json.dumps(context, indent=2, default=str)}"
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
    review["prompt_version"] = PROMPT_VERSION
    return review


def _review_with_api(message: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
        max_tokens=2000,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"{message}\n\nAnswer with one JSON object matching this schema:\n{json.dumps(REVIEW_SCHEMA)}"}],
    )
    response_text = ""
    try:
        response_text = response.content[0].text
        return _parse_json_response(response_text)
    except (json.JSONDecodeError, IndexError, AttributeError) as exc:
        raise ValueError(f"Failed to parse AI response: {exc}. Response starts: {response_text[:300]!r}") from exc


def _assemble_context(
    trade: Trade,
    fills: list[Fill],
    companion_trades: Optional[list[Trade]] = None,
    stats: Optional[dict] = None,
    session: Optional[Session] = None,
) -> dict:
    """Assemble all relevant data for the AI prompt."""

    # Load tags if session provided
    tags = []
    if session and trade.id:
        try:
            trade_tags = session.exec(
                select(TradeTag).where(TradeTag.trade_id == trade.id)
            ).all()
            tag_ids = [tt.tag_id for tt in trade_tags]
            if tag_ids:
                tag_objs = session.exec(
                    select(Tag).where(Tag.id.in_(tag_ids))
                ).all()
                tags = [t.name for t in tag_objs]
        except Exception:
            pass

    # Format fills with role
    fills_data = []
    trade_fill_roles = {}
    if session and trade.id:
        try:
            trade_fills = session.exec(
                select(TradeFill).where(TradeFill.trade_id == trade.id)
            ).all()
            trade_fill_roles = {tf.fill_id: tf.role for tf in trade_fills}
        except Exception:
            pass

    for fill in fills:
        role = trade_fill_roles.get(fill.id, "entry" if fill.price == trade.avg_entry_premium else "exit")
        fills_data.append({
            "executed_at": fill.executed_at.isoformat() if fill.executed_at else None,
            "role": role,
            "side": fill.side,
            "contracts": float(fill.contracts),
            "price": float(fill.price),
            "iv_at_fill": float(fill.iv_at_fill) if fill.iv_at_fill else None,
            "delta_at_fill": float(fill.delta_at_fill) if fill.delta_at_fill else None,
            "iv_rank_at_fill": float(fill.iv_rank_at_fill) if fill.iv_rank_at_fill else None,
            "underlying_price_at_fill": float(fill.underlying_price_at_fill) if fill.underlying_price_at_fill else None,
        })

    # Companion trades for spread detection
    companion_data = []
    if companion_trades:
        for ct in companion_trades[:3]:  # Limit to 3 to avoid context bloat
            companion_data.append({
                "ticker": ct.ticker,
                "instrument_type": ct.instrument_type,
                "option_type": ct.option_type,
                "strike": float(ct.strike) if ct.strike else None,
                "expiration": ct.expiration.isoformat() if ct.expiration else None,
                "contracts": float(ct.contracts),
                "realized_pnl": float(ct.realized_pnl) if ct.realized_pnl else None,
                "opened_at": ct.opened_at.isoformat() if ct.opened_at else None,
            })

    # Ticker stats from the broader stats context
    ticker_stats = {}
    by_ticker_stats = {}
    if stats:
        by_ticker = stats.get("by_ticker", {})
        ticker_stats = by_ticker.get(trade.ticker, {})
        # Also include some overall stats for context
        by_ticker_stats = {
            "overall_win_rate": stats.get("win_rate", 0),
            "overall_avg_pnl_pct": stats.get("avg_win_pct", None),
            "avg_hold_mins": stats.get("avg_hold_mins", None),
            "behavioral_flags": stats.get("behavioral_flags", {}),
        }

    path_metrics = None
    if session and trade.id:
        try:
            path_metrics = session.get(TradePathMetrics, trade.id)
        except Exception:
            path_metrics = None

    return {
        "trade": {
            "id": str(trade.id),
            "ticker": trade.ticker,
            "instrument_type": trade.instrument_type,
            "option_type": trade.option_type,
            "strike": float(trade.strike) if trade.strike else None,
            "expiration": trade.expiration.isoformat() if trade.expiration else None,
            "contracts": float(trade.contracts),
            "avg_entry_premium": float(trade.avg_entry_premium),
            "avg_exit_premium": float(trade.avg_exit_premium) if trade.avg_exit_premium else None,
            "total_premium_paid": float(trade.total_premium_paid),
            "realized_pnl": float(trade.realized_pnl) if trade.realized_pnl else None,
            "pnl_pct": float(trade.pnl_pct) if trade.pnl_pct else None,
            "hold_duration_mins": trade.hold_duration_mins,
            "entry_time_bucket": trade.entry_time_bucket,
            "expired_worthless": trade.expired_worthless,
            "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
            "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
            "status": trade.status,
            "tags": tags,
            "path_metrics": _path_context(path_metrics),
        },
        "fills": fills_data,
        "companion_trades": companion_data,
        "ticker_stats": ticker_stats,
        "trader_context": by_ticker_stats,
    }


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


_SYSTEM_PROMPT = """You are an expert options and stock trade reviewer coaching one retail trader. Analyze one trade and give
actionable feedback grounded only in the JSON you receive.

You will receive a JSON object with:
- trade: entry/exit prices, P&L, holding time, whether it expired worthless, tags. Timestamps are New York wall-clock.
- fills: individual executions with timestamps and IV/delta/underlying data where available
- companion_trades: other trades on the same ticker opened within 5 minutes (may be legs of one spread)
- ticker_stats: this ticker's history (count, win rate, total P&L); trader_context: overall win rate and flags
- trade.path_metrics: when present, option peak open P&L, worst open P&L, giveback from peak, MFE/MAE and exit
  efficiency. Distinguish a trade that never worked from one that worked and then reversed: a small realized loss
  after a large positive option_peak_unrealized_pnl is an exit/risk-management issue.
- day_context: what was around the trade that day, when available:
  - plans: what the trader captured before entering (by_trade, with minutes_before_entry). When this trade has a plan,
    plan_check compares it with what was done (instrument, side, strike, size, timing, exit); null when there is none.
  - market: the indexes' day, SPY/QQQ intraday shape (trend_efficiency near 1 is a trend day, near 0 chop), VIX and the
    10-year yield. When partial_as_of is set, numbers are intraday as of that time. market_read is one sentence: what
    kind of day it was and whether this trade went with it or against it; "Market context unavailable" when missing.
  - macro: FOMC, CPI and jobs releases that day or the next trading day; a trade held into one carried event risk.
  - tickers: the underlying's move against SPY and its sector ETF, earnings within a week, the day's headlines
    (observed, never proof of cause), option open-interest walls, the trader's alerts that fired, and their CURRENT
    saved levels (may have been added later: a hint, never proof).
  - gaps: parts that were unavailable.
Never invent prices, levels, news or data that is not in the JSON. When missing data limits a judgement, name it in
data_gaps (at most three) instead of guessing.

Fields:
- strategy: name and direction, e.g. "Long Call (bullish directional)", "Iron Condor", "PMCC".
- flags: short snake_case labels such as early_exit, late_exit, oversized, revenge_trade, good_entry, chased_entry,
  against_the_tape, held_into_event, gave_back_peak, no_plan, followed_plan, scalp, lucky_win, expired_worthless.
- summary: one or two sentences.
- entry_quality / exit_quality: start with one word (Excellent, Good, Fair, Poor or Terrible), then one or two
  sentences on timing and price relative to the day's move, levels and context.
- suggestions: at most three, specific and checkable on the next trade (a rule, not a mood).

If the trade won, say what worked and whether it was repeatable or lucky. If it lost, find the teachable moment.
Reference IV, delta, underlying price and hold time when available.
"""
