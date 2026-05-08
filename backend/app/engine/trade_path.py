"""
Trade path metrics: MFE, MAE, exit efficiency, giveback.

Uses cached minute bars (already fetched by the Alpaca fill enricher).
Operates on closed/expired trades only. Does NOT make any Alpaca API calls
if the bars are already cached; if a date is missing it just skips.

Underlying path is computed for all instrument types.
Option-specific path (option_mfe_pct etc.) is left for Phase 5.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.engine.alpaca import ALPACA_DATA_FEED, fetch_minute_bars_for_date
from app.engine.indicators import bars_to_df, _f
from app.models import Fill, FillMarketContext, Trade, TradePathMetrics

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def compute_path_metrics_for_trades(
    trades: list[Trade],
    session: Session,
    on_progress=None,
    force: bool = False,
) -> int:
    """
    Compute and upsert TradePathMetrics for closed/expired trades.
    Returns count of trades processed.
    """
    closed = [t for t in trades if t.status in ("closed", "expired") and t.opened_at and t.closed_at]
    if not closed:
        return 0

    if not force:
        existing = set(session.exec(select(TradePathMetrics.trade_id)).all())
        closed = [t for t in closed if t.id not in existing]

    if not closed:
        return 0

    # Fetch fills for all trades in one query
    from app.models import TradeFill
    trade_ids = [t.id for t in closed]
    trade_fills = session.exec(select(TradeFill).where(TradeFill.trade_id.in_(trade_ids))).all()
    fill_ids = [tf.fill_id for tf in trade_fills]
    fills_list = session.exec(select(Fill).where(Fill.id.in_(fill_ids))).all() if fill_ids else []
    fills_by_id = {f.id: f for f in fills_list}

    fills_by_trade: dict = {}
    for tf in trade_fills:
        fills_by_trade.setdefault(tf.trade_id, []).append(fills_by_id[tf.fill_id])

    # Fetch Alpaca context for all fills
    ctx_rows = session.exec(select(FillMarketContext).where(FillMarketContext.fill_id.in_(fill_ids))).all() if fill_ids else []
    ctx_by_fill = {str(row.fill_id): row for row in ctx_rows}

    processed = 0
    for i, trade in enumerate(closed):
        if on_progress:
            on_progress(i + 1, trade.ticker)
        fills = fills_by_trade.get(trade.id, [])
        try:
            metrics = _compute(trade, fills, ctx_by_fill)
            if metrics:
                session.merge(metrics)
                processed += 1
        except Exception as e:
            log.warning("Failed path metrics for trade %s: %s", trade.id, e)

    session.commit()
    log.info("Trade path metrics: computed %d/%d trades", processed, len(closed))
    return processed


# ---------------------------------------------------------------------------
# Per-trade computation
# ---------------------------------------------------------------------------

def _compute(
    trade: Trade,
    fills: list[Fill],
    ctx_by_fill: dict[str, FillMarketContext],
) -> Optional[TradePathMetrics]:
    entry_fills = [f for f in fills if f.side in ("buy_to_open", "sell_to_open", "buy")]
    exit_fills = [f for f in fills if f not in entry_fills]

    if not entry_fills:
        return None

    entry_fill = min(entry_fills, key=lambda f: f.executed_at)
    entry_ctx = ctx_by_fill.get(str(entry_fill.id))

    # Entry underlying price: prefer Alpaca context, then Polygon fill enrichment, then stock price
    entry_price = (
        entry_ctx.entry_underlying_price if entry_ctx and entry_ctx.entry_underlying_price
        else entry_fill.underlying_price_at_fill
        if entry_fill.underlying_price_at_fill
        else float(trade.avg_entry_premium) if trade.instrument_type == "stock"
        else None
    )
    if not entry_price:
        return None

    bullish = _is_bullish(trade, entry_fill)

    # Collect minute bars across all dates in the trade window
    opened_et = trade.opened_at.replace(tzinfo=ET)
    closed_et = trade.closed_at.replace(tzinfo=ET)
    opened_utc = opened_et.astimezone(UTC)
    closed_utc = closed_et.astimezone(UTC)

    all_bars: list[dict] = []
    for day in _date_range(trade.opened_at.date(), trade.closed_at.date()):
        day_bars = fetch_minute_bars_for_date([trade.ticker], day).get(trade.ticker, [])
        all_bars.extend(day_bars)

    if not all_bars:
        return None

    df = bars_to_df(all_bars)
    df = df[(df.index >= opened_utc) & (df.index <= closed_utc)]
    if df.empty:
        return None

    # MFE / MAE as % of entry underlying price
    if bullish:
        favorable = (df["high"] - entry_price) / entry_price * 100
        adverse = (entry_price - df["low"]) / entry_price * 100
    else:
        favorable = (entry_price - df["low"]) / entry_price * 100
        adverse = (df["high"] - entry_price) / entry_price * 100

    mfe_pct = _f(favorable.max())
    mae_pct = _f(adverse.max())

    mfe_idx = favorable.idxmax() if mfe_pct is not None else None
    mae_idx = adverse.idxmax() if mae_pct is not None else None

    time_to_mfe = int((mfe_idx - opened_utc).total_seconds() / 60) if mfe_idx is not None else None
    time_to_mae = int((mae_idx - opened_utc).total_seconds() / 60) if mae_idx is not None else None

    moved_in_favor_first = None
    if mfe_idx is not None and mae_idx is not None:
        moved_in_favor_first = 1 if mfe_idx <= mae_idx else 0

    # Exit efficiency (underlying-based): what % of MFE did the exit capture?
    exit_efficiency = None
    giveback_pct = None
    if mfe_pct is not None and mfe_pct > 0:
        exit_price = _get_exit_underlying(exit_fills, trade, ctx_by_fill, df)
        if exit_price is not None:
            realized = (
                (exit_price - entry_price) / entry_price * 100 if bullish
                else (entry_price - exit_price) / entry_price * 100
            )
            exit_efficiency = _f(realized / mfe_pct * 100)
            giveback_pct = _f(mfe_pct - realized)

    # Buckets
    hold_mins = trade.hold_duration_mins or 0
    if hold_mins < 15:
        hold_bucket = "scalp"
    elif hold_mins < 360:
        hold_bucket = "intraday"
    elif hold_mins < 1440:
        hold_bucket = "swing"
    else:
        hold_bucket = "multi-day"

    exit_time_bucket = None
    if exit_fills:
        last_exit = max(exit_fills, key=lambda f: f.executed_at)
        m = last_exit.executed_at.hour * 60 + last_exit.executed_at.minute
        if m < 9 * 60 + 30:
            exit_time_bucket = "premarket"
        elif m < 10 * 60:
            exit_time_bucket = "open"
        elif m < 14 * 60:
            exit_time_bucket = "mid"
        elif m < 16 * 60:
            exit_time_bucket = "close"
        else:
            exit_time_bucket = "afterhours"

    return TradePathMetrics(
        trade_id=trade.id,
        data_source=f"alpaca_{ALPACA_DATA_FEED}",
        fetched_at=datetime.utcnow(),
        hold_duration_bucket=hold_bucket,
        exit_time_bucket=exit_time_bucket,
        underlying_mfe_pct=mfe_pct,
        underlying_mae_pct=mae_pct,
        time_to_underlying_mfe_minutes=time_to_mfe,
        time_to_underlying_mae_minutes=time_to_mae,
        underlying_exit_efficiency=exit_efficiency,
        underlying_giveback_pct=giveback_pct,
        moved_in_favor_first=moved_in_favor_first,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_bullish(trade: Trade, entry_fill: Fill) -> bool:
    if trade.instrument_type == "stock":
        return entry_fill.side in ("buy", "buy_to_open")
    if trade.option_type == "call":
        return entry_fill.side == "buy_to_open"
    if trade.option_type == "put":
        return entry_fill.side == "sell_to_open"
    return True


def _get_exit_underlying(
    exit_fills: list[Fill],
    trade: Trade,
    ctx_by_fill: dict,
    df,
) -> Optional[float]:
    if exit_fills:
        last_exit = max(exit_fills, key=lambda f: f.executed_at)
        ctx = ctx_by_fill.get(str(last_exit.id))
        if ctx and ctx.entry_underlying_price:
            return ctx.entry_underlying_price
        if last_exit.underlying_price_at_fill:
            return float(last_exit.underlying_price_at_fill)
        if trade.instrument_type == "stock" and trade.avg_exit_premium:
            return float(trade.avg_exit_premium)
    # Fallback: last bar close
    if not df.empty:
        return float(df["close"].iloc[-1])
    return None


def _date_range(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    return days
