"""
Trade path metrics: MFE, MAE, exit efficiency, giveback.

Uses cached minute bars (already fetched by the Alpaca fill enricher).
Operates on closed/expired trades only. Does NOT make any Alpaca API calls
if the bars are already cached; if a date is missing it just skips.

Underlying path is computed for all instrument types.
Option-specific path (option_mfe_pct etc.) is left for Phase 5.
"""

import hashlib
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.engine.alpaca import ALPACA_DATA_FEED, fetch_minute_bars_for_date, fetch_option_bars
from app.engine.indicators import bars_to_df, _f
from app.models import Fill, FillMarketContext, Trade, TradePathMetrics

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
MAX_PATH_WINDOW_DAYS = 10


def trade_inputs_fingerprint(trade: Trade, fills: list[Fill]) -> str:
    """Stable hash of a trade's status plus the fills that compose it.

    Trade ids are stable across rebuilds (the id is the first entry fill's id),
    but a trade's fills can change while the id stays the same (scale-in, a new
    exit, an edited fill price). That invalidates any previously computed path
    metrics. Rebuilds compare this fingerprint to decide whether an existing
    TradePathMetrics row can be reused or must be recomputed.
    """
    parts = sorted(
        "{}|{}|{}|{}|{}".format(f.id, f.side, f.contracts, f.price, f.executed_at.isoformat())
        for f in fills
    )
    blob = "{}::{}".format(trade.status, "||".join(parts))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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

    # Pre-fetch every minute-bar (ticker, day) the trades will need, batched by
    # day. fetch_minute_bars_for_date() takes up to 50 tickers per call and
    # caches per ticker/date, so this collapses what used to be one serial
    # single-ticker call per trade-day into a handful of batched calls. The
    # per-trade loop below then reads only from this in-memory store, so
    # "compute path metrics" never silently turns into hundreds of API fetches.
    bar_store = _prefetch_minute_bars(closed, on_progress)

    processed = 0
    for i, trade in enumerate(closed):
        if on_progress:
            on_progress(i + 1, trade.ticker)
        fills = fills_by_trade.get(trade.id, [])
        try:
            metrics = _compute(trade, fills, ctx_by_fill, bar_store)
            if metrics:
                metrics.inputs_fingerprint = trade_inputs_fingerprint(trade, fills)
                session.merge(metrics)
                processed += 1
        except Exception as e:
            log.warning("Failed path metrics for trade %s: %s", trade.id, e)

        session.commit()

    log.info("Trade path metrics: computed %d/%d trades", processed, len(closed))
    return processed


# ---------------------------------------------------------------------------
# Minute-bar prefetch
# ---------------------------------------------------------------------------

def _window_days(trade: Trade) -> list[date]:
    """Days a trade's underlying path needs, or [] if outside the window cap."""
    if not (trade.opened_at and trade.closed_at):
        return []
    post_exit_end = trade.closed_at.replace(tzinfo=ET) + timedelta(hours=1)
    window_days = (post_exit_end.date() - trade.opened_at.date()).days + 1
    if window_days > MAX_PATH_WINDOW_DAYS:
        return []
    return _date_range(trade.opened_at.date(), post_exit_end.date())


def _prefetch_minute_bars(trades: list[Trade], on_progress=None) -> dict[tuple[str, str], list]:
    """
    Batch-fetch minute bars for every (ticker, day) the trades will need,
    grouped by day so each network call covers up to 50 tickers at once.
    Returns {(ticker, day_iso): [bar_dict]} for the per-trade loop to read.
    """
    by_day: dict[date, set[str]] = defaultdict(set)
    for trade in trades:
        for day in _window_days(trade):
            by_day[day].add(trade.ticker)

    bar_store: dict[tuple[str, str], list] = {}
    total_days = len(by_day)
    for idx, (day, tickers) in enumerate(sorted(by_day.items())):
        if on_progress:
            on_progress(0, f"Loading bars {day} ({idx + 1}/{total_days})")
        try:
            fetched = fetch_minute_bars_for_date(sorted(tickers), day)
        except Exception as e:
            log.warning("Prefetch failed for %s: %s", day, e)
            fetched = {}
        for ticker, bars in fetched.items():
            bar_store[(ticker, day.isoformat())] = bars
    return bar_store


# ---------------------------------------------------------------------------
# Per-trade computation
# ---------------------------------------------------------------------------

def _compute(
    trade: Trade,
    fills: list[Fill],
    ctx_by_fill: dict[str, FillMarketContext],
    bar_store: dict[tuple[str, str], list],
) -> Optional[TradePathMetrics]:
    entry_fills = [f for f in fills if f.side in ("buy_to_open", "sell_to_open", "buy")]
    exit_fills = [f for f in fills if f not in entry_fills]

    if not entry_fills:
        return None

    entry_fill = min(entry_fills, key=lambda f: f.executed_at)
    entry_ctx = ctx_by_fill.get(str(entry_fill.id))
    option_path = _compute_option_path(trade, entry_fill)

    # Entry underlying price: prefer Alpaca context, then Polygon fill enrichment, then stock price
    entry_price = (
        entry_ctx.entry_underlying_price if entry_ctx and entry_ctx.entry_underlying_price
        else entry_fill.underlying_price_at_fill
        if entry_fill.underlying_price_at_fill
        else float(trade.avg_entry_premium) if trade.instrument_type == "stock"
        else None
    )
    if not entry_price:
        if option_path:
            metrics = _base_metrics(trade, exit_fills, f"alpaca_{ALPACA_DATA_FEED}_option_only")
            _apply_option_path(metrics, option_path)
            return metrics
        return None

    bullish = _is_bullish(trade, entry_fill)

    # Collect minute bars across all dates in the trade window
    opened_et = trade.opened_at.replace(tzinfo=ET)
    closed_et = trade.closed_at.replace(tzinfo=ET)
    opened_utc = opened_et.astimezone(UTC)
    closed_utc = closed_et.astimezone(UTC)

    # Path metrics use minute bars. Multi-month/year positions can require
    # thousands of per-day cache/API checks, so mark them as skipped instead.
    post_exit_end = closed_et + timedelta(hours=1)
    window_days = (post_exit_end.date() - trade.opened_at.date()).days + 1
    if window_days > MAX_PATH_WINDOW_DAYS:
        log.info(
            "Skipping path metrics for %s trade %s: %d-day window exceeds %d-day cap",
            trade.ticker,
            trade.id,
            window_days,
            MAX_PATH_WINDOW_DAYS,
        )
        metrics = _base_metrics(trade, exit_fills, f"alpaca_{ALPACA_DATA_FEED}_skipped_long_window")
        _apply_option_path(metrics, option_path)
        return metrics

    # Bars for the trade window + 60m of post-exit. Read from the prefetched
    # in-memory store; fall back to the on-disk cache only (never the network)
    # for any day the prefetch did not cover.
    all_bars: list[dict] = []
    for day in _date_range(trade.opened_at.date(), post_exit_end.date()):
        key = (trade.ticker, day.isoformat())
        day_bars = bar_store.get(key)
        if day_bars is None:
            day_bars = fetch_minute_bars_for_date([trade.ticker], day, cache_only=True).get(trade.ticker, [])
            bar_store[key] = day_bars
        all_bars.extend(day_bars)

    if not all_bars:
        if option_path:
            metrics = _base_metrics(trade, exit_fills, f"alpaca_{ALPACA_DATA_FEED}_option_only")
            _apply_option_path(metrics, option_path)
            return metrics
        return None

    full_df = bars_to_df(all_bars)
    df = full_df[(full_df.index >= opened_utc) & (full_df.index <= closed_utc)]
    if df.empty:
        if option_path:
            metrics = _base_metrics(trade, exit_fills, f"alpaca_{ALPACA_DATA_FEED}_option_only")
            _apply_option_path(metrics, option_path)
            return metrics
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

    # Post-exit continuation: how much did price move in favor after exit?
    post_15m, post_30m, post_60m, time_to_post_high = _compute_post_exit(
        full_df, closed_utc, entry_price, bullish
    )

    metrics = TradePathMetrics(
        trade_id=trade.id,
        data_source=f"alpaca_{ALPACA_DATA_FEED}",
        fetched_at=datetime.utcnow(),
        hold_duration_bucket=_hold_bucket(trade),
        exit_time_bucket=_exit_time_bucket(exit_fills),
        underlying_mfe_pct=mfe_pct,
        underlying_mae_pct=mae_pct,
        time_to_underlying_mfe_minutes=time_to_mfe,
        time_to_underlying_mae_minutes=time_to_mae,
        underlying_exit_efficiency=exit_efficiency,
        underlying_giveback_pct=giveback_pct,
        moved_in_favor_first=moved_in_favor_first,
        post_exit_mfe_15m=post_15m,
        post_exit_mfe_30m=post_30m,
        post_exit_mfe_60m=post_60m,
        time_to_post_exit_high_minutes=time_to_post_high,
    )
    _apply_option_path(metrics, option_path)
    return metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_metrics(trade: Trade, exit_fills: list[Fill], data_source: str) -> TradePathMetrics:
    return TradePathMetrics(
        trade_id=trade.id,
        data_source=data_source,
        fetched_at=datetime.utcnow(),
        hold_duration_bucket=_hold_bucket(trade),
        exit_time_bucket=_exit_time_bucket(exit_fills),
    )


def _hold_bucket(trade: Trade) -> str:
    hold_mins = trade.hold_duration_mins or 0
    if hold_mins < 15:
        return "scalp"
    if hold_mins < 360:
        return "intraday"
    if hold_mins < 1440:
        return "swing"
    return "multi-day"


def _exit_time_bucket(exit_fills: list[Fill]) -> Optional[str]:
    if not exit_fills:
        return None
    last_exit = max(exit_fills, key=lambda f: f.executed_at)
    minutes = last_exit.executed_at.hour * 60 + last_exit.executed_at.minute
    if minutes < 9 * 60 + 30:
        return "premarket"
    if minutes < 10 * 60:
        return "open"
    if minutes < 14 * 60:
        return "mid"
    if minutes < 16 * 60:
        return "close"
    return "afterhours"


def _compute_option_path(trade: Trade, entry_fill: Fill) -> dict | None:
    if trade.instrument_type != "option" or not trade.expiration or trade.strike is None or not trade.option_type:
        return None

    symbol = _option_contract_symbol(trade.ticker, trade.expiration, trade.option_type, float(trade.strike))
    if not symbol:
        return None

    opened_et = trade.opened_at.replace(tzinfo=ET)
    closed_et = trade.closed_at.replace(tzinfo=ET)
    same_day = opened_et.date() == closed_et.date()
    timeframe = "1Min" if same_day else "1Day"
    start = opened_et if same_day else opened_et.date()
    end = closed_et if same_day else closed_et.date()

    bars = fetch_option_bars([symbol], timeframe, start, end).get(symbol, [])
    if not bars:
        return None

    df = bars_to_df(bars)
    if df.empty:
        return None
    if same_day:
        opened_utc = opened_et.astimezone(UTC)
        closed_utc = closed_et.astimezone(UTC)
        df = df[(df.index >= opened_utc) & (df.index <= closed_utc)]
        if df.empty:
            return None

    entry_price = float(trade.avg_entry_premium)
    if entry_price <= 0:
        return None

    max_price = float(df["high"].max()) * 100
    min_price = float(df["low"].min()) * 100
    contracts = float(trade.contracts or 0)
    long_option = entry_fill.side == "buy_to_open"

    if long_option:
        peak_unrealized = (max_price - entry_price) * contracts
        worst_unrealized = (min_price - entry_price) * contracts
        option_mfe_pct = (max_price - entry_price) / entry_price * 100
        option_mae_pct = (entry_price - min_price) / entry_price * 100
        extreme_idx = df["high"].idxmax()
    else:
        peak_unrealized = (entry_price - min_price) * contracts
        worst_unrealized = (entry_price - max_price) * contracts
        option_mfe_pct = (entry_price - min_price) / entry_price * 100
        option_mae_pct = (max_price - entry_price) / entry_price * 100
        extreme_idx = df["low"].idxmin()

    realized = float(trade.realized_pnl or 0)
    exit_efficiency = None
    giveback_from_peak = None
    giveback_pct = None
    if peak_unrealized > 0:
        exit_efficiency = realized / peak_unrealized * 100
        giveback_from_peak = peak_unrealized - realized
        giveback_pct = giveback_from_peak / peak_unrealized * 100

    time_to_mfe = None
    if same_day and extreme_idx is not None:
        time_to_mfe = int((extreme_idx - opened_et.astimezone(UTC)).total_seconds() / 60)

    return {
        "option_mfe_pct": _f(option_mfe_pct),
        "option_mae_pct": _f(option_mae_pct),
        "option_max_price_seen": _f(max_price),
        "option_min_price_seen": _f(min_price),
        "time_to_option_mfe_minutes": time_to_mfe,
        "option_exit_efficiency": _f(exit_efficiency),
        "option_giveback_pct": _f(giveback_pct),
        "option_peak_unrealized_pnl": _f(peak_unrealized),
        "option_worst_unrealized_pnl": _f(worst_unrealized),
        "option_giveback_from_peak": _f(giveback_from_peak),
    }


def _apply_option_path(metrics: TradePathMetrics, option_path: dict | None) -> None:
    if not option_path:
        return
    for key, value in option_path.items():
        setattr(metrics, key, value)


def _option_contract_symbol(ticker: str, expiration: date, option_type: str, strike: float) -> str | None:
    root = "".join(ch for ch in ticker.upper() if ch.isalnum())
    if not root:
        return None
    side = "C" if option_type.lower() == "call" else "P" if option_type.lower() == "put" else None
    if side is None:
        return None
    strike_part = f"{int(round(strike * 1000)):08d}"
    return f"{root}{expiration:%y%m%d}{side}{strike_part}"


def _compute_post_exit(
    full_df,
    closed_utc,
    entry_price: float,
    bullish: bool,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[int]]:
    """
    Compute how much price moved in the favorable direction after the exit.
    Uses bars strictly after closed_utc, up to 60 minutes.
    Returns (post_15m_mfe, post_30m_mfe, post_60m_mfe, time_to_extreme_minutes).
    """
    windows = [15, 30, 60]
    results: list[Optional[float]] = []
    time_to_extreme: Optional[int] = None

    # Determine RTH close for the exit day — don't look past 16:00 ET
    exit_et = closed_utc.astimezone(ET)
    rth_close = exit_et.replace(hour=16, minute=0, second=0, microsecond=0)
    rth_close_utc = rth_close.astimezone(UTC)
    cap = min(closed_utc + timedelta(hours=1), rth_close_utc)

    post_df = full_df[(full_df.index > closed_utc) & (full_df.index <= cap)]
    if post_df.empty:
        return None, None, None, None

    for w in windows:
        end = closed_utc + timedelta(minutes=w)
        seg = post_df[post_df.index <= end]
        if seg.empty:
            results.append(None)
            continue
        if bullish:
            mfe = float((seg["high"].max() - entry_price) / entry_price * 100)
        else:
            mfe = float((entry_price - seg["low"].min()) / entry_price * 100)
        results.append(_f(mfe))

    # Time to the post-exit extreme within 60m
    if bullish:
        extreme_idx = post_df["high"].idxmax()
    else:
        extreme_idx = post_df["low"].idxmin()
    if extreme_idx is not None:
        time_to_extreme = int((extreme_idx - closed_utc).total_seconds() / 60)

    return results[0], results[1], results[2], time_to_extreme


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
