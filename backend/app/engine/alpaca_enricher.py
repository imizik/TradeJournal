"""
Alpaca enrichment orchestrator.

Groups fills by (ticker, date), fetches Alpaca bars in batches,
computes indicators and intraday context locally, then writes
FillMarketContext rows. Skips fills that already have a context row
unless force=True.

Does NOT touch Fill rows, Trade rows, or existing Polygon enrichment fields.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.engine.alpaca import (
    ALPACA_DATA_FEED,
    alpaca_configured,
    fetch_daily_bars,
    fetch_minute_bars_for_date,
)
from app.engine.indicators import (
    analyze_minute_bars,
    compute_avg_daily_volume,
    compute_daily_indicators,
    compute_flags,
    compute_rvol,
    compute_rvol_time_adjusted,
    get_previous_day_data,
    _pct_diff,
)
from app.engine.behavior import SequenceState
from app.models import Fill, FillMarketContext

log = logging.getLogger(__name__)


def enrich_fills_alpaca(
    fills: list[Fill],
    session: Session,
    on_progress=None,
    force: bool = False,
) -> int:
    """
    Compute and upsert FillMarketContext rows for the given fills.
    Returns the count of fills enriched.

    on_progress: optional callable(done_count: int, label: str)
    force: re-enrich fills that already have a context row
    """
    if not alpaca_configured():
        log.warning("Alpaca keys not configured — skipping Alpaca enrichment")
        return 0

    fills_with_time = [f for f in fills if f.executed_at is not None]
    if not fills_with_time:
        return 0

    # Skip already-enriched unless forced
    if not force:
        existing = set(
            session.exec(select(FillMarketContext.fill_id)).all()
        )
        fills_with_time = [f for f in fills_with_time if f.id not in existing]

    if not fills_with_time:
        log.info("All fills already have Alpaca context — nothing to do")
        return 0

    tickers = list({f.ticker for f in fills_with_time})
    dates = [f.executed_at.date() for f in fills_with_time]
    earliest_fill = min(dates)
    latest_fill = max(dates)

    # Fetch 400 calendar days of daily history for indicator warmup
    daily_start = earliest_fill - timedelta(days=400)
    daily_end = latest_fill + timedelta(days=2)

    log.info(
        "Alpaca enrichment: %d fills, %d tickers, daily range %s–%s",
        len(fills_with_time), len(tickers), daily_start, daily_end,
    )

    # --- 1. Daily bars (batched, cached per ticker) ---
    if on_progress:
        on_progress(0, f"Fetching history: {len(tickers)} ticker(s)…")
    daily_bars = fetch_daily_bars(tickers, daily_start, daily_end)

    # --- 2. Daily indicators per ticker ---
    if on_progress:
        on_progress(0, "Computing indicators…")
    daily_indicators: dict[str, dict[str, dict]] = {}
    for ticker, bars in daily_bars.items():
        daily_indicators[ticker] = compute_daily_indicators(bars)

    # --- 2b. Trader-state sequence metrics (journal-derived, no API) ---
    sequence = SequenceState(session)

    # --- 3. Group fills by date for minute bar batching ---
    by_date: dict[date, list[Fill]] = defaultdict(list)
    for f in fills_with_time:
        by_date[f.executed_at.date()].append(f)

    enriched = 0
    fills_done = 0
    total_dates = len(by_date)

    for date_idx, (trade_date, date_fills) in enumerate(sorted(by_date.items())):
        label = f"{trade_date} ({date_idx + 1}/{total_dates})"
        log.info("Alpaca enriching %s — %d fill(s)", label, len(date_fills))
        if on_progress:
            on_progress(fills_done, str(trade_date))

        date_tickers = list({f.ticker for f in date_fills})

        # --- 4. Minute bars for this date (batched, cached per ticker/date) ---
        try:
            minute_bars = fetch_minute_bars_for_date(date_tickers, trade_date)
        except Exception as e:
            log.warning("Failed to fetch minute bars for %s: %s", trade_date, e)
            minute_bars = {}

        for fill in date_fills:
            try:
                ctx = _build_context(fill, daily_bars, daily_indicators, minute_bars)
                for key, value in sequence.compute(fill).items():
                    setattr(ctx, key, value)
                session.merge(ctx)
                enriched += 1
            except Exception as e:
                log.warning("Failed to build context for fill %s: %s", fill.id, e)

        # Commit each trade date so SQLite does not hold a write lock across
        # the entire historical enrichment run. Postgres handles the longer
        # transaction, but local SQLite is the default development database.
        session.commit()
        fills_done += len(date_fills)

    log.info("Alpaca enrichment complete: %d fills enriched", enriched)
    return enriched


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context(
    fill: Fill,
    daily_bars: dict[str, list],
    daily_indicators: dict[str, dict[str, dict]],
    minute_bars: dict[str, list],
) -> FillMarketContext:
    ticker = fill.ticker
    fill_dt = fill.executed_at
    fill_date = fill_dt.date()
    day_str = fill_date.isoformat()

    # Intraday context from minute bars
    bars = minute_bars.get(ticker, [])
    intraday = analyze_minute_bars(bars, fill_dt) if bars else {}

    # Daily indicators: latest completed day strictly before the fill date.
    # The fill day's own indicator row is computed on that day's close, which
    # does not exist yet at fill time — using it would leak the future into
    # "at entry" fields (and made backfilled values differ from live ones).
    indic_by_date = daily_indicators.get(ticker, {})
    prior_days = [k for k in indic_by_date if k < day_str]
    daily_indic = indic_by_date[max(prior_days)] if prior_days else {}

    # Previous day OHLC from daily bars
    prev = get_previous_day_data(daily_bars.get(ticker, []), fill_date)

    # Avg daily volume
    adv = compute_avg_daily_volume(daily_bars.get(ticker, []), fill_date)

    # Derived cross-fields
    entry_price = intraday.get("entry_underlying_price")
    ema9 = daily_indic.get("ema_9")
    ema20 = daily_indic.get("ema_20")
    vs_ema9 = _pct_diff(entry_price, ema9)
    vs_ema20 = _pct_diff(entry_price, ema20)

    # Gap: today's open vs prev close — approximate with OR-5 high as "open"
    today_open = intraday.get("opening_range_5m_high")  # use first bar open if available
    entry_gap_pct = _pct_diff(today_open, prev.get("close"))

    # Previous day distance
    dist_prev_high = _pct_diff(entry_price, prev.get("high"))
    dist_prev_low = _pct_diff(entry_price, prev.get("low"))

    # Relative volume
    rvol = compute_rvol(intraday, adv, fill_dt)
    rvol_ta = compute_rvol_time_adjusted(ticker, fill_date, fill_dt, daily_bars.get(ticker, []))

    # Flags (need prev fields added to intraday dict for flag computation)
    intraday_with_prev = {
        **intraday,
        "entry_distance_from_prev_high_pct": dist_prev_high,
        "entry_distance_from_prev_low_pct": dist_prev_low,
    }
    flags = compute_flags(fill, intraday_with_prev, daily_indic)

    # Option moneyness at entry
    moneyness_pct: Optional[float] = None
    is_itm: Optional[int] = None
    is_otm: Optional[int] = None
    if fill.instrument_type == "option" and fill.strike is not None and entry_price is not None:
        strike = float(fill.strike)
        if fill.option_type == "call":
            moneyness_pct = round((entry_price - strike) / strike * 100, 4)
        elif fill.option_type == "put":
            moneyness_pct = round((strike - entry_price) / strike * 100, 4)
        if moneyness_pct is not None:
            is_itm = 1 if moneyness_pct > 0 else 0
            is_otm = 1 if moneyness_pct < 0 else 0

    return FillMarketContext(
        fill_id=fill.id,
        data_source=f"alpaca_{ALPACA_DATA_FEED}",
        fetched_at=datetime.utcnow(),
        # Underlying price
        entry_underlying_price=entry_price,
        entry_vwap=intraday.get("entry_vwap"),
        entry_vs_vwap_pct=intraday.get("entry_vs_vwap_pct"),
        entry_volume=intraday.get("entry_volume"),
        cumulative_volume_at_entry=intraday.get("cumulative_volume_at_entry"),
        avg_daily_volume_20=adv,
        simple_relative_volume=rvol,
        rvol_time_adjusted=rvol_ta,
        # Daily indicators
        entry_sma_20=daily_indic.get("sma_20"),
        entry_sma_50=daily_indic.get("sma_50"),
        entry_ema_9=ema9,
        entry_ema_20=ema20,
        entry_rsi_14=daily_indic.get("rsi_14"),
        entry_macd=daily_indic.get("macd"),
        entry_macd_signal=daily_indic.get("macd_signal"),
        entry_macd_histogram=daily_indic.get("macd_histogram"),
        entry_atr_14=daily_indic.get("atr_14"),
        entry_vs_ema9_pct=vs_ema9,
        entry_vs_ema20_pct=vs_ema20,
        # Intraday structure
        entry_day_high_so_far=intraday.get("entry_day_high_so_far"),
        entry_day_low_so_far=intraday.get("entry_day_low_so_far"),
        entry_day_range_used_pct=intraday.get("entry_day_range_used_pct"),
        entry_distance_from_day_high_pct=intraday.get("entry_distance_from_day_high_pct"),
        entry_distance_from_day_low_pct=intraday.get("entry_distance_from_day_low_pct"),
        premarket_high=intraday.get("premarket_high"),
        premarket_low=intraday.get("premarket_low"),
        entry_distance_from_premarket_high_pct=intraday.get("entry_distance_from_premarket_high_pct"),
        entry_distance_from_premarket_low_pct=intraday.get("entry_distance_from_premarket_low_pct"),
        opening_range_5m_high=intraday.get("opening_range_5m_high"),
        opening_range_5m_low=intraday.get("opening_range_5m_low"),
        opening_range_15m_high=intraday.get("opening_range_15m_high"),
        opening_range_15m_low=intraday.get("opening_range_15m_low"),
        entry_distance_from_or5_high_pct=intraday.get("entry_distance_from_or5_high_pct"),
        entry_distance_from_or5_low_pct=intraday.get("entry_distance_from_or5_low_pct"),
        entry_distance_from_or15_high_pct=intraday.get("entry_distance_from_or15_high_pct"),
        entry_distance_from_or15_low_pct=intraday.get("entry_distance_from_or15_low_pct"),
        previous_day_high=prev.get("high"),
        previous_day_low=prev.get("low"),
        previous_day_close=prev.get("close"),
        entry_distance_from_prev_high_pct=dist_prev_high,
        entry_distance_from_prev_low_pct=dist_prev_low,
        entry_gap_pct=entry_gap_pct,
        # Flags
        is_chase_entry=flags.get("is_chase_entry"),
        chase_score=flags.get("chase_score"),
        is_trend_aligned=flags.get("is_trend_aligned"),
        is_late_move=flags.get("is_late_move"),
        is_above_vwap=flags.get("is_above_vwap"),
        is_vwap_reclaim=flags.get("is_vwap_reclaim"),
        is_opening_range_breakout=flags.get("is_opening_range_breakout"),
        is_premarket_breakout=flags.get("is_premarket_breakout"),
        is_near_resistance_on_call_entry=flags.get("is_near_resistance_on_call_entry"),
        is_near_support_on_put_entry=flags.get("is_near_support_on_put_entry"),
        is_overnight=flags.get("is_overnight"),
        entry_time_bucket=flags.get("entry_time_bucket"),
        dte_bucket=flags.get("dte_bucket"),
        setup_quality_score=flags.get("setup_quality_score"),
        # Option moneyness
        moneyness_pct=moneyness_pct,
        is_itm=is_itm,
        is_otm=is_otm,
    )
