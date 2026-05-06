import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, select

from app.models import Account, Fill, Trade, TradeFill

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
                "fills": [_fill_context(fill, fill_roles.get(str(fill.id))) for fill in fills],
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
        },
        "trades": trade_context,
    }


def _fill_context(fill: Fill, role: str | None) -> dict:
    return {
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
Fills may include underlying price, VWAP, IV, greeks, moving averages, RSI, and MACD. These fields are nullable; only
use enriched data when present.

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
  "patterns": ["<behavioral or execution pattern>", "<pattern>"],
  "next_session_rules": ["<specific rule for next session>", "<rule>", "<rule>"]
}

Focus on execution quality, risk sizing, repeated behavior, timing, and whether trades were held or exited well.
Be specific and concise. Do not invent market data that is not in the JSON.
"""
