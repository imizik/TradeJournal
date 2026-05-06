import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from sqlmodel import Session, select

from app.models import Fill, Trade, TradeFill, TradeTag, Tag

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")


def review_trade(
    trade: Trade,
    fills: list[Fill],
    companion_trades: Optional[list[Trade]] = None,
    stats: Optional[dict] = None,
    session: Optional[Session] = None,
) -> dict:
    """
    Generates an AI trade review using Claude API with prompt caching.

    Args:
        trade: The Trade object to review
        fills: List of Fill objects for this trade (sorted by executed_at)
        companion_trades: Other trades opened ~5min before/after this one on same ticker
        stats: Dict from /stats endpoint for trader-level context
        session: Database session for loading tags

    Returns:
        Dict with keys: strategy, flags, summary, entry_quality, exit_quality, suggestions
    """

    # Assemble trade context JSON
    context = _assemble_context(trade, fills, companion_trades, stats, session)

    # Call Claude API with prompt caching
    client = Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )

    message = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
        max_tokens=1024,
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
                "content": f"Review this trade:\n\n{json.dumps(context, indent=2, default=str)}",
            }
        ],
    )

    # Parse and validate response
    try:
        response_text = message.content[0].text
        review = _parse_json_response(response_text)
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        snippet = response_text[:300] if "response_text" in locals() else "<no text>"
        raise ValueError(f"Failed to parse AI response: {e}. Response starts: {snippet!r}") from e

    # Validate required fields
    required = {"strategy", "flags", "summary", "entry_quality", "exit_quality", "suggestions"}
    if not required.issubset(review.keys()):
        raise ValueError(f"AI response missing required fields. Got: {review.keys()}")

    return review


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
        },
        "fills": fills_data,
        "companion_trades": companion_data,
        "ticker_stats": ticker_stats,
        "trader_context": by_ticker_stats,
    }


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


_SYSTEM_PROMPT = """You are an expert options and stock trade reviewer. Your job is to analyze trades and provide actionable feedback.

You will receive a JSON object with:
- trade: Details about the trade (entry/exit prices, P&L, holding time, whether it expired worthless, etc.)
- fills: Individual executions with timestamps, IV/delta/underlying data where available
- companion_trades: Other trades opened ~5 minutes before/after this one (may indicate multi-leg strategies)
- ticker_stats: This ticker's historical performance (win rate, avg P&L %)
- trader_context: Overall trading stats and prior behavioral flags observed

**Output only a JSON object with these fields. Do not wrap it in markdown. Do not include any text before or after the JSON:**

```json
{
  "strategy": "<Name and direction, e.g. 'Long Call (bullish directional)', 'Iron Condor', 'PMCC'>",
  "flags": [
    "<flag1>",
    "<flag2>"
  ],
  "summary": "<1-2 sentence trade summary>",
  "entry_quality": "<1-2 sentence assessment of entry timing and price relative to the day's move and market context>",
  "exit_quality": "<1-2 sentence assessment of exit timing and price>",
  "suggestions": [
    "<actionable suggestion 1>",
    "<actionable suggestion 2>"
  ]
}
```

**Flag examples** (use as inspiration, not exhaustive):
- "early_exit" — sold before target, left money on table
- "late_exit" — held through reversal, reduced gains
- "oversized" — contracts too large for account
- "undersized" — tiny position, not worth the risk/reward
- "revenge_trade" — entered shortly after a loss
- "good_entry" — entered near support/key level
- "forced_exit" — closed for non-technical reasons
- "expired_worthless" — let profitable credit trade expire
- "scalp" — very short hold (minutes), high friction
- "lucky_win" — won despite poor entry/exit
- "time_decay_winner" — theta worked in trader's favor

**Scoring entry/exit quality:**
- "Excellent" — entered/exited at inflection point or key technical level
- "Good" — reasonable timing, within typical variance
- "Fair" — middle of the range, neither great nor poor
- "Poor" — missed obvious signal or overstayed
- "Terrible" — against the trend, reversed immediately

Prioritize actionable insights. If the trade was a winner, note what worked. If it lost, identify the teachable moment. Reference IV, delta, underlying price, and hold time when available.
"""
