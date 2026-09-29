"""
Trade path metrics: MFE, MAE, exit efficiency, giveback.

Uses cached minute bars (already fetched by the Alpaca fill enricher).
Operates on closed/expired trades only. Underlying bars are prefetched in
batches and reused from cache; per-trade computation reads that store.

Underlying path is computed for all instrument types.
Option paths use finalized minute bars and the actual changing FIFO exposure.
"""

import hashlib
import logging
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.engine.alpaca import ALPACA_DATA_FEED, fetch_minute_bars_for_date, fetch_option_bars, _minute_session_complete
from app.engine.occ import occ_symbol
from app.engine.metric_versions import PATH_VERSION, underlying_direction
from app.engine.indicators import bars_to_df, _f
from app.models import FILL_LIGHT, Fill, FillMarketContext, Trade, TradePathMetrics

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
MAX_PATH_WINDOW_DAYS = 10


def _fingerprint_value(value) -> str:
    # Persisted NUMERIC values gain trailing zeroes; that is not an input change.
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(Decimal(str(value)).normalize())
    return str(value)


def trade_inputs_fingerprint(trade: Trade, fills: list[Fill]) -> str:
    """Stable hash of a trade's status plus the fills that compose it.

    Trade ids are stable across rebuilds (the id is the first entry fill's id),
    but a trade's fills can change while the id stays the same (scale-in, a new
    exit, an edited fill price). That invalidates any previously computed path
    metrics. Rebuilds compare this fingerprint to decide whether an existing
    TradePathMetrics row can be reused or must be recomputed.
    """
    parts = sorted(
        "|".join(_fingerprint_value(getattr(f, key)) for key in (
            "id", "account_id", "ticker", "instrument_type", "option_type", "strike", "expiration",
            "side", "contracts", "price", "executed_at", "underlying_price_at_fill",
            "delta_at_fill", "gamma_at_fill", "theta_at_fill", "vega_at_fill", "iv_at_fill",
        ))
        for f in fills
    )
    blob = "{}::{}".format(trade.status, "||".join(parts))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def market_inputs_fingerprint(fills: list[Fill], contexts: dict) -> str:
    values = []
    for fill in sorted(fills, key=lambda f: str(f.id)):
        ctx = contexts.get(str(fill.id))
        values.append((str(fill.id), {
            key: _fingerprint_value(value) for key, value in ctx.model_dump(exclude={"fetched_at"}).items()
        } if ctx else None))
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


_ENTRY_SIDES = ("buy_to_open", "sell_to_open", "buy")


def trades_needing_path_metrics(session: Session, trades: list[Trade]) -> list:
    """Ids of closed trades with no path metrics or with gaps a rerun can fill.

    A row computed the day a trade closed has no underlying path (minute bars
    are not final until 20:05 ET); a row computed before Polygon finished has
    no greeks attribution; rows from before a column existed lack it entirely.
    Only gaps whose inputs are present now are selected, so permanent ones are
    not recomputed on every scheduled run.
    """
    closed = [t for t in trades if t.status in ("closed", "expired") and t.opened_at and t.closed_at]
    if not closed:
        return []
    metrics_by_trade = {
        row.trade_id: row
        for row in session.exec(
            select(TradePathMetrics).where(TradePathMetrics.trade_id.in_([t.id for t in closed]))
        ).all()
    }

    from app.models import TradeFill
    links = session.exec(select(TradeFill).where(TradeFill.trade_id.in_([t.id for t in closed]))).all()
    fill_ids = [link.fill_id for link in links]
    source_fills = session.exec(select(Fill).options(*FILL_LIGHT).where(Fill.id.in_(fill_ids))).all() if fill_ids else []
    fill_by_id = {f.id: f for f in source_fills}
    context_rows = session.exec(select(FillMarketContext).where(FillMarketContext.fill_id.in_(fill_ids))).all() if fill_ids else []
    contexts = {str(c.fill_id): c for c in context_rows}
    sources = defaultdict(list)
    for link in links:
        sources[link.trade_id].append(fill_by_id[link.fill_id])
    selected = []
    to_check: dict = {}
    for trade in closed:
        metrics = metrics_by_trade.get(trade.id)
        if metrics is None:
            selected.append(trade.id)
        elif (metrics.calculation_version != PATH_VERSION
              or metrics.inputs_fingerprint != trade_inputs_fingerprint(trade, sources[trade.id])
              or metrics.market_inputs_fingerprint != market_inputs_fingerprint(sources[trade.id], contexts)):
            selected.append(trade.id)
        elif metrics.underlying_mfe_pct is None and _window_days(trade):
            selected.append(trade.id)  # bars can arrive after the first run
        else:
            atr_gap = metrics.underlying_mfe_pct is not None and metrics.mfe_atr_multiple is None
            attr_gap = trade.instrument_type == "option" and metrics.attr_delta_pnl is None and trade.realized_pnl is not None
            if atr_gap or attr_gap:
                to_check[trade.id] = (atr_gap, attr_gap)
    if not to_check:
        return selected

    rows = session.exec(
        select(
            TradeFill.trade_id,
            Fill.side,
            Fill.executed_at,
            Fill.delta_at_fill,
            Fill.underlying_price_at_fill,
            FillMarketContext.entry_atr_14,
        )
        .join(Fill, Fill.id == TradeFill.fill_id)
        .outerjoin(FillMarketContext, FillMarketContext.fill_id == Fill.id)
        .where(TradeFill.trade_id.in_(list(to_check)))
    ).all()
    fills_by_trade: dict = defaultdict(list)
    for row in rows:
        fills_by_trade[row.trade_id].append(row)

    for trade_id, (atr_gap, attr_gap) in to_check.items():
        fills = fills_by_trade.get(trade_id, [])
        entries = [f for f in fills if f.side in _ENTRY_SIDES]
        exits = [f for f in fills if f.side not in _ENTRY_SIDES]
        if not entries:
            continue
        entry = min(entries, key=lambda f: f.executed_at)
        last_exit = max(exits, key=lambda f: f.executed_at) if exits else None
        atr_ready = atr_gap and entry.entry_atr_14 is not None
        attr_ready = (
            attr_gap
            and len(entries) == 1 and len(exits) == 1
            and last_exit is not None
            and entry.delta_at_fill is not None
            and entry.underlying_price_at_fill is not None
            and last_exit.underlying_price_at_fill is not None
        )
        if atr_ready or attr_ready:
            selected.append(trade_id)
    return selected


def compute_path_metrics_for_trades(
    trades: list[Trade],
    session: Session,
    on_progress=None,
    force: bool = False,
    keep_existing: bool = False,
) -> int:
    """
    Compute and upsert TradePathMetrics for closed/expired trades.
    Returns count of trades processed.

    keep_existing: a recomputed row keeps any stored value this run could not
    produce (a failed or missing bar fetch), provided the trade's fills are
    unchanged. The scheduled gap repair uses it.
    """
    closed = [t for t in trades if t.status in ("closed", "expired") and t.opened_at and t.closed_at]
    if not closed:
        return 0

    if not force:
        selected = set(trades_needing_path_metrics(session, closed))
        closed = [t for t in closed if t.id in selected]

    if not closed:
        return 0

    # Fetch fills for all trades in one query
    from app.models import TradeFill
    trade_ids = [t.id for t in closed]
    trade_fills = session.exec(select(TradeFill).where(TradeFill.trade_id.in_(trade_ids))).all()
    fill_ids = [tf.fill_id for tf in trade_fills]
    fills_list = session.exec(select(Fill).options(*FILL_LIGHT).where(Fill.id.in_(fill_ids))).all() if fill_ids else []
    fills_by_id = {f.id: f for f in fills_list}

    fills_by_trade: dict = {}
    for tf in trade_fills:
        fills_by_trade.setdefault(tf.trade_id, []).append(fills_by_id[tf.fill_id])

    # Fetch Alpaca context for all fills
    ctx_rows = session.exec(select(FillMarketContext).where(FillMarketContext.fill_id.in_(fill_ids))).all() if fill_ids else []
    ctx_by_fill = {str(row.fill_id): row for row in ctx_rows}

    previous_by_trade = (
        {
            row.trade_id: row
            for row in session.exec(select(TradePathMetrics).where(TradePathMetrics.trade_id.in_(trade_ids))).all()
        }
        if keep_existing
        else {}
    )

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
                metrics.calculation_version = PATH_VERSION
                metrics.market_inputs_fingerprint = market_inputs_fingerprint(fills, ctx_by_fill)
                previous = previous_by_trade.get(trade.id)
                if (previous is not None and previous.inputs_fingerprint == metrics.inputs_fingerprint
                        and previous.calculation_version == PATH_VERSION
                        and previous.market_inputs_fingerprint == metrics.market_inputs_fingerprint):
                    # Retain a valid option calculation as one group when a
                    # repeat fetch fails, including its quality description.
                    keep_option = (metrics.option_path_quality != "observed_1min"
                                   and previous.option_path_quality == "observed_1min")
                    for column in TradePathMetrics.__table__.columns:
                        if column.name.startswith("option_") or column.name == "time_to_option_mfe_minutes":
                            if keep_option:
                                setattr(metrics, column.name, getattr(previous, column.name))
                            continue
                        if getattr(metrics, column.name) is None:
                            setattr(metrics, column.name, getattr(previous, column.name))
                session.merge(metrics)
                processed += 1
        except Exception as e:
            log.warning("Failed path metrics for trade %s: %s", trade.id, e)

        # Commit in batches: one commit per trade is a full network round trip
        # on hosted Postgres (minutes of pure latency across a big run). The
        # write lock on SQLite is only taken at commit, so batching is safe
        # there too.
        if (i + 1) % 25 == 0:
            session.commit()

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
    entry_fills = [f for f in fills if f.side in _ENTRY_SIDES]
    exit_fills = [f for f in fills if f not in entry_fills]

    if not entry_fills:
        return None

    entry_fill = min(entry_fills, key=lambda f: (f.executed_at, str(f.id)))
    entry_ctx = ctx_by_fill.get(str(entry_fill.id))
    option_path = _compute_option_path(trade, entry_fill, fills)

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
            _apply_attribution(metrics, trade, entry_fill, exit_fills, len(entry_fills))
            return metrics
        return None

    bullish = _is_bullish(trade, entry_fill)
    if bullish is None:
        metrics = _base_metrics(trade, exit_fills, f"alpaca_{ALPACA_DATA_FEED}_unknown_direction")
        _apply_option_path(metrics, option_path)
        return metrics

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
        _apply_attribution(metrics, trade, entry_fill, exit_fills, len(entry_fills))
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
            _apply_attribution(metrics, trade, entry_fill, exit_fills, len(entry_fills))
            return metrics
        return None

    full_df = bars_to_df(all_bars)
    df = full_df[(full_df.index > opened_utc) & (full_df.index + timedelta(minutes=1) <= closed_utc)]
    if df.empty:
        if option_path:
            metrics = _base_metrics(trade, exit_fills, f"alpaca_{ALPACA_DATA_FEED}_option_only")
            _apply_option_path(metrics, option_path)
            _apply_attribution(metrics, trade, entry_fill, exit_fills, len(entry_fills))
            return metrics
        return None

    # MFE / MAE as % of entry underlying price
    if bullish:
        favorable = (df["high"] - entry_price) / entry_price * 100
        adverse = (entry_price - df["low"]) / entry_price * 100
    else:
        favorable = (entry_price - df["low"]) / entry_price * 100
        adverse = (df["high"] - entry_price) / entry_price * 100

    mfe_pct = _f(max(0, favorable.max()))
    mae_pct = _f(max(0, adverse.max()))

    mfe_idx = favorable.idxmax() if mfe_pct is not None else None
    mae_idx = adverse.idxmax() if mae_pct is not None else None

    time_to_mfe = int((mfe_idx - opened_utc).total_seconds() / 60) if mfe_idx is not None else None
    time_to_mae = int((mae_idx - opened_utc).total_seconds() / 60) if mae_idx is not None else None

    moved_in_favor_first = None
    if mfe_idx is not None and mae_idx is not None and mfe_idx != mae_idx:
        moved_in_favor_first = 1 if mfe_idx < mae_idx else 0

    # Exit efficiency (underlying-based): what % of MFE did the exit capture?
    exit_efficiency = None
    giveback_pct = None
    if len(entry_fills) == 1 and len(exit_fills) <= 1 and mfe_pct is not None and mfe_pct > 0:
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

    # ATR-normalized excursions: entry ATR (last completed day) as % of entry
    # price is the unit, so MFE/MAE are comparable across volatility profiles.
    entry_atr = entry_ctx.entry_atr_14 if entry_ctx else None
    if entry_atr and entry_price:
        atr_pct = float(entry_atr) / entry_price * 100
        if atr_pct > 0:
            if mfe_pct is not None:
                metrics.mfe_atr_multiple = _f(mfe_pct / atr_pct)
            if mae_pct is not None:
                metrics.mae_atr_multiple = _f(mae_pct / atr_pct)

    _apply_option_path(metrics, option_path)
    _apply_attribution(metrics, trade, entry_fill, exit_fills, len(entry_fills))
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
    if minutes < 15 * 60:
        return "mid"
    if minutes < 16 * 60:
        return "close"
    return "afterhours"


def _compute_option_path(trade: Trade, entry_fill: Fill, fills: list[Fill]) -> dict | None:
    if trade.instrument_type != "option" or not trade.expiration or trade.strike is None or not trade.option_type:
        return None
    symbol = occ_symbol(trade.ticker, trade.expiration, trade.option_type, float(trade.strike))
    if not symbol:
        return None
    if (trade.closed_at.date() - trade.opened_at.date()).days + 1 > MAX_PATH_WINDOW_DAYS:
        return {"option_path_quality": "unavailable_long_window"}
    if not _minute_session_complete(trade.closed_at.date()):
        return {"option_path_quality": "unavailable_session_incomplete"}
    opened = trade.opened_at.replace(tzinfo=ET)
    closed = trade.closed_at.replace(tzinfo=ET)
    bars = fetch_option_bars([symbol], "1Min", opened, closed).get(symbol, [])
    return option_position_path(trade, fills, bars)


def option_position_path(trade: Trade, fills: list[Fill], bars: list[dict]) -> dict:
    """Observed minute-bar excursions using actual FIFO exposure at each minute.

    Fill minutes are excluded: minute-granular fills cannot locate executions
    within their bar. These are observed estimates, never executable quotes.
    Premiums in fills are total dollars per contract; bars need the 100 multiplier.
    """
    from collections import deque
    ordered = sorted(fills, key=lambda f: (f.executed_at, f.side not in _ENTRY_SIDES, str(f.id)))
    entries = [f for f in ordered if f.side in _ENTRY_SIDES]
    if not entries or not bars:
        return {"option_path_quality": "unavailable_bars"}
    entered = sum(float(f.contracts) for f in entries)
    exited = sum(float(f.contracts) for f in ordered if f.side not in _ENTRY_SIDES)
    if exited > entered + 1e-9 or (trade.status == "closed" and abs(entered - exited) > 1e-9):
        return {"option_path_quality": "unavailable_fill_allocation"}
    df = bars_to_df(bars)
    opened = trade.opened_at.replace(tzinfo=ET).astimezone(UTC)
    closed = trade.closed_at.replace(tzinfo=ET).astimezone(UTC)
    df = df[(df.index >= opened) & (df.index + timedelta(minutes=1) <= closed)]
    fill_times = [f.executed_at.replace(tzinfo=ET).astimezone(UTC) for f in ordered]
    sign = 1 if entries[0].side == "buy_to_open" else -1
    lots = deque()
    realized = 0.0
    pointer = 0
    peak_open = worst_open = 0.0
    peak_total = 0.0
    mfe = mae = 0.0
    high_seen, low_seen, peak_time = None, None, None
    for stamp, bar in df.iterrows():
        while pointer < len(ordered) and fill_times[pointer] <= stamp:
            fill = ordered[pointer]
            qty, price = float(fill.contracts), float(fill.price)
            if fill.side in _ENTRY_SIDES:
                lots.append([qty, price])
            else:
                while qty > 1e-9 and lots:
                    used = min(qty, lots[0][0])
                    realized += sign * (price - lots[0][1]) * used
                    lots[0][0] -= used
                    qty -= used
                    if lots[0][0] < 1e-9:
                        lots.popleft()
                if qty > 1e-9:
                    return {"option_path_quality": "unavailable_fill_allocation"}
            pointer += 1
        if not lots or any(stamp <= t < stamp + timedelta(minutes=1) for t in fill_times):
            continue
        qty = sum(lot[0] for lot in lots)
        basis = sum(lot[0] * lot[1] for lot in lots)
        if basis <= 0:
            continue
        high, low = float(bar["high"]) * 100, float(bar["low"]) * 100
        favorable = sign * ((high if sign > 0 else low) * qty - basis)
        adverse = sign * ((low if sign > 0 else high) * qty - basis)
        peak_open, worst_open = max(peak_open, favorable), min(worst_open, adverse)
        mfe, mae = max(mfe, favorable / basis * 100), max(mae, -adverse / basis * 100)
        if realized + favorable > peak_total:
            peak_total, peak_time = realized + favorable, stamp
        high_seen = high if high_seen is None else max(high_seen, high)
        low_seen = low if low_seen is None else min(low_seen, low)
    if high_seen is None:
        return {"option_path_quality": "unavailable_holding_bars"}
    final = float(trade.realized_pnl) if trade.realized_pnl is not None else None
    if final is not None and final > peak_total:
        peak_total, peak_time = final, closed
    giveback = max(0, peak_total - final) if final is not None else None
    return {
        "option_path_quality": "observed_1min",
        "option_mfe_pct": _f(mfe), "option_mae_pct": _f(mae),
        "option_max_price_seen": _f(high_seen), "option_min_price_seen": _f(low_seen),
        "option_peak_unrealized_pnl": _f(peak_open), "option_worst_unrealized_pnl": _f(worst_open),
        "option_peak_total_pnl": _f(peak_total), "option_giveback_from_peak": _f(giveback),
        "option_exit_efficiency": _f(final / peak_total * 100) if final is not None and peak_total > 0 else None,
        "option_giveback_pct": _f(giveback / peak_total * 100) if giveback is not None and peak_total > 0 else None,
        "time_to_option_mfe_minutes": int((peak_time - opened).total_seconds() / 60) if peak_time else None,
    }


def _apply_option_path(metrics: TradePathMetrics, option_path: dict | None) -> None:
    if not option_path:
        return
    for key, value in option_path.items():
        setattr(metrics, key, value)


def _apply_attribution(
    metrics: TradePathMetrics,
    trade: Trade,
    entry_fill: Fill,
    exit_fills: list[Fill],
    entry_count: int = 1,
) -> None:
    """First-order greeks PnL attribution for option trades.

    realized_pnl ≈ delta + gamma + theta + vega + residual, all in dollars and
    signed for the position (short options flip the sign). Uses the entry
    fill's Black-Scholes greeks (per-share, theta per day, vega per IV point)
    and the entry/exit fills' Polygon-enriched underlying prices and IVs. The
    residual absorbs higher-order terms, path effects, and spread/slippage.
    """
    if entry_count != 1 or len(exit_fills) != 1:
        return
    if trade.instrument_type != "option" or not exit_fills:
        return
    if trade.realized_pnl is None or not trade.opened_at or not trade.closed_at:
        return
    if entry_fill.delta_at_fill is None or entry_fill.underlying_price_at_fill is None:
        return

    last_exit = max(exit_fills, key=lambda f: f.executed_at)
    if last_exit.underlying_price_at_fill is None:
        return

    s_entry = float(entry_fill.underlying_price_at_fill)
    ds = float(last_exit.underlying_price_at_fill) - s_entry
    mult = float(trade.contracts or 0) * 100.0  # shares represented
    if mult <= 0:
        return
    sign = 1.0 if entry_fill.side == "buy_to_open" else -1.0
    hold_days = max(0.0, (trade.closed_at - trade.opened_at).total_seconds() / 86400.0)

    metrics.attr_delta_pnl = _f(sign * float(entry_fill.delta_at_fill) * ds * mult)
    if entry_fill.gamma_at_fill is not None:
        metrics.attr_gamma_pnl = _f(sign * 0.5 * float(entry_fill.gamma_at_fill) * ds * ds * mult)
    if entry_fill.theta_at_fill is not None:
        metrics.attr_theta_pnl = _f(sign * float(entry_fill.theta_at_fill) * hold_days * mult)

    entry_iv = float(entry_fill.iv_at_fill) if entry_fill.iv_at_fill is not None else None
    exit_iv = float(last_exit.iv_at_fill) if last_exit.iv_at_fill is not None else None
    metrics.entry_iv = _f(entry_iv)
    metrics.exit_iv = _f(exit_iv)
    if entry_fill.vega_at_fill is not None and entry_iv is not None and exit_iv is not None:
        # vega is per 1 IV *point*; IVs are stored as decimals
        metrics.attr_vega_pnl = _f(
            sign * float(entry_fill.vega_at_fill) * (exit_iv - entry_iv) * 100.0 * mult
        )

    if None not in (
        metrics.attr_delta_pnl,
        metrics.attr_gamma_pnl,
        metrics.attr_theta_pnl,
        metrics.attr_vega_pnl,
    ):
        explained = (
            metrics.attr_delta_pnl
            + metrics.attr_gamma_pnl
            + metrics.attr_theta_pnl
            + metrics.attr_vega_pnl
        )
        metrics.attr_residual_pnl = _f(float(trade.realized_pnl) - explained)


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


def _is_bullish(trade: Trade, entry_fill: Fill) -> bool | None:
    return underlying_direction(entry_fill)


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
