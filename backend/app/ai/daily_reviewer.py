import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, select

from app.models import Account, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")


def review_trading_day(
    day: str,
    trades: list[Trade],
    fills_by_trade_id: dict[str, list[Fill]],
    session: Session,
) -> dict:
    context = _assemble_daily_context(day, trades, fills_by_trade_id, session)

    from anthropic import Anthropic

    client = Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )
    message = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
        max_tokens=1600,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Review this trading day:\n\n{json.dumps(context, indent=2, default=str)}",
            }
        ],
    )

    try:
        response_text = message.content[0].text
        review = _parse_json_response(response_text)
    except (json.JSONDecodeError, IndexError, AttributeError) as exc:
        snippet = response_text[:300] if "response_text" in locals() else "<no text>"
        raise ValueError(f"Failed to parse AI response as JSON: {exc}. Response starts: {snippet!r}") from exc

    required = {"summary", "day_grade", "key_takeaways", "best_trade", "worst_trade", "patterns", "next_session_rules"}
    if not required.issubset(review.keys()):
        raise ValueError(f"AI response missing required fields. Got: {review.keys()}")

    return review


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


_SYSTEM_PROMPT = """You are an expert trading coach reviewing one trading day from a local trade journal.

You will receive JSON with summary_stats and a list of stock/option trades. A trade is included when it opened or
closed on the review day. Use activity_today/opened_today/closed_today to separate entry decisions from exit decisions.

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

## Instructions

Return only valid JSON with this exact shape. Do not wrap it in markdown. Do not include any text before or after the JSON:

{
  "summary": "<2-4 sentence direct assessment of the day>",
  "day_grade": "<A, B, C, D, or F with a short reason>",
  "key_takeaways": ["<takeaway>", "<takeaway>", "<takeaway>"],
  "best_trade": {
    "trade_id": "<id or null>",
    "ticker": "<ticker or null>",
    "reason": "<why this was strongest>"
  },
  "worst_trade": {
    "trade_id": "<id or null>",
    "ticker": "<ticker or null>",
    "reason": "<why this was weakest>"
  },
  "patterns": ["<behavioral or execution pattern observed across multiple trades>", "<pattern>"],
  "next_session_rules": ["<specific, actionable rule for next session>", "<rule>", "<rule>"]
}

Focus on execution quality, risk sizing, repeated behavioral patterns, timing, and whether trades were held or exited well.
When behavioral flags are present, explicitly call out patterns — e.g. repeated chase entries, late moves, or entries near
resistance. Be specific and concise. Do not invent market data that is not in the JSON.
When path_metrics are present, account for peak open P&L, giveback, and exit efficiency.
"""
