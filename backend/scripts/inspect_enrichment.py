"""
Inspect enrichment data for a single trade.

Usage:
    python scripts/inspect_enrichment.py <trade_id>
    python scripts/inspect_enrichment.py --recent          # show last 10 closed trades
    python scripts/inspect_enrichment.py --ticker NVDA     # most recent closed trade for ticker

Prints:
  - Trade summary
  - Per-fill: Polygon enrichment vs Alpaca context (cross-check underlying price & RSI)
  - Raw minute bars around entry/exit (so you can compare against a chart)
  - Trade path metrics with sanity flags
"""

import json
import sys
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Bootstrap path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select, create_engine
from app.models import Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "trade_journal.db"
engine = create_engine(f"sqlite:///{DB_PATH}")
ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def p(label, value, warn=False):
    flag = "  ⚠" if warn else ""
    print(f"    {label:<40} {value}{flag}")


def pct(val, decimals=2):
    if val is None:
        return "-"
    return f"{val:+.{decimals}f}%"


def num(val, decimals=4):
    if val is None:
        return "-"
    return f"{val:.{decimals}f}"


def flag(val):
    if val is None:
        return "?"
    return "YES" if val == 1 else "no"


# ---------------------------------------------------------------------------
# Main inspection
# ---------------------------------------------------------------------------

def inspect_trade(trade_id: str):
    with Session(engine) as session:
        trade = session.get(Trade, trade_id)
        if not trade:
            print(f"Trade {trade_id} not found")
            return

        # Fills
        tfs = session.exec(select(TradeFill).where(TradeFill.trade_id == trade.id)).all()
        fill_ids = [tf.fill_id for tf in tfs]
        fills = session.exec(select(Fill).where(Fill.id.in_(fill_ids))).all()
        fills = sorted(fills, key=lambda f: f.executed_at)

        # Alpaca contexts
        ctx_rows = session.exec(select(FillMarketContext).where(FillMarketContext.fill_id.in_(fill_ids))).all()
        ctx_by_fill = {str(r.fill_id): r for r in ctx_rows}

        # Path metrics
        path = session.get(TradePathMetrics, trade.id)

    print()
    print("=" * 70)
    print(f"  TRADE: {trade.ticker}  {trade.instrument_type.upper()}", end="")
    if trade.option_type:
        print(f"  {trade.option_type.upper()} ${trade.strike}  exp {trade.expiration}", end="")
    print()
    print(f"  ID: {trade.id}")
    print(f"  Status: {trade.status}   Contracts: {trade.contracts}")
    print(f"  Opened:  {trade.opened_at}  ET")
    print(f"  Closed:  {trade.closed_at}  ET")
    print(f"  Hold:    {trade.hold_duration_mins} mins")
    print(f"  Entry premium: ${trade.avg_entry_premium}   Exit: ${trade.avg_exit_premium}")
    pnl = trade.realized_pnl
    pnl_str = f"${pnl:+.2f}" if pnl is not None else "-"
    print(f"  Realized P&L: {pnl_str}   ({pct(trade.pnl_pct * 100 if trade.pnl_pct else None, 1)})")
    print("=" * 70)

    # ---- Fill detail ----
    for fill in fills:
        is_entry = fill.side in ("buy_to_open", "sell_to_open", "buy")
        label = "ENTRY" if is_entry else "EXIT"
        ctx = ctx_by_fill.get(str(fill.id))

        print()
        print(f"  [{label}]  {fill.executed_at} ET  |  {fill.side}  {fill.contracts}x @ ${fill.price}")
        print()

        # Cross-check: Polygon vs Alpaca underlying price
        poly_price = fill.underlying_price_at_fill
        alp_price = ctx.entry_underlying_price if ctx else None
        price_diff = abs(poly_price - alp_price) if poly_price and alp_price else None
        price_warn = price_diff is not None and price_diff > 0.50

        p("Polygon underlying price", f"${poly_price:.4f}" if poly_price else "-")
        p("Alpaca underlying price", f"${alp_price:.4f}" if alp_price else "-",
          warn=price_warn)
        if price_diff is not None:
            p("  → difference", f"${price_diff:.4f}" + (" ← LARGE, check timing" if price_warn else " ✓ close"))

        print()

        # Polygon enrichment
        print("    --- Polygon ---")
        p("VWAP at fill", f"${fill.vwap_at_fill:.4f}" if fill.vwap_at_fill else "-")
        p("IV at fill", pct(fill.iv_at_fill * 100 if fill.iv_at_fill else None, 1))
        p("Delta", num(fill.delta_at_fill))
        p("RSI-14", num(fill.rsi_14_at_fill, 1))
        p("MACD", num(fill.macd_at_fill, 4))
        p("MACD signal", num(fill.macd_signal_at_fill, 4))
        p("EMA-9d", f"${fill.ema_9_at_fill:.4f}" if fill.ema_9_at_fill else "-")
        p("EMA-20d", f"${fill.ema_20_at_fill:.4f}" if fill.ema_20_at_fill else "-")

        if ctx:
            print()
            print("    --- Alpaca context ---")
            p("VWAP", f"${ctx.entry_vwap:.4f}" if ctx.entry_vwap else "-")
            p("vs VWAP", pct(ctx.entry_vs_vwap_pct))
            p("RSI-14", num(ctx.entry_rsi_14, 1))

            # Cross-check RSI: Polygon vs Alpaca (should be within a few points)
            if fill.rsi_14_at_fill and ctx.entry_rsi_14:
                rsi_diff = abs(fill.rsi_14_at_fill - ctx.entry_rsi_14)
                p("  → RSI difference (Poly vs Alpaca)", f"{rsi_diff:.1f}" +
                  (" ← LARGE (different timeframe?)" if rsi_diff > 10 else " ✓"))

            p("EMA-9d", f"${ctx.entry_ema_9:.4f}" if ctx.entry_ema_9 else "-")
            p("EMA-20d", f"${ctx.entry_ema_20:.4f}" if ctx.entry_ema_20 else "-")
            p("vs EMA-9", pct(ctx.entry_vs_ema9_pct))
            p("MACD histogram", num(ctx.entry_macd_histogram, 4))
            p("ATR-14", f"${ctx.entry_atr_14:.4f}" if ctx.entry_atr_14 else "-")
            p("RVOL", num(ctx.simple_relative_volume, 2))
            p("Gap", pct(ctx.entry_gap_pct))
            p("Day range used", f"{ctx.entry_day_range_used_pct:.1f}%" if ctx.entry_day_range_used_pct else "-")
            p("Premarket High", f"${ctx.premarket_high:.4f}" if ctx.premarket_high else "-")
            p("Premarket Low", f"${ctx.premarket_low:.4f}" if ctx.premarket_low else "-")
            p("OR-5 High", f"${ctx.opening_range_5m_high:.4f}" if ctx.opening_range_5m_high else "-")
            p("OR-5 Low", f"${ctx.opening_range_5m_low:.4f}" if ctx.opening_range_5m_low else "-")
            p("Day High (so far)", f"${ctx.entry_day_high_so_far:.4f}" if ctx.entry_day_high_so_far else "-")
            p("Day Low (so far)", f"${ctx.entry_day_low_so_far:.4f}" if ctx.entry_day_low_so_far else "-")

            if is_entry:
                print()
                print("    --- Behavioral flags ---")
                p("Chase entry", flag(ctx.is_chase_entry))
                p("Trend aligned", flag(ctx.is_trend_aligned))
                p("Late move", flag(ctx.is_late_move))
                p("VWAP reclaim", flag(ctx.is_vwap_reclaim))
                p("OR breakout", flag(ctx.is_opening_range_breakout))
                p("PM breakout", flag(ctx.is_premarket_breakout))
                p("Near resistance (call)", flag(ctx.is_near_resistance_on_call_entry))
                p("Near support (put)", flag(ctx.is_near_support_on_put_entry))
                p("Entry time bucket", ctx.entry_time_bucket or "-")
                p("DTE bucket", ctx.dte_bucket or "-")
        else:
            print("    (no Alpaca context for this fill)")

    # ---- Raw minute bars around entry ----
    if fills:
        entry_fill = next((f for f in fills if f.side in ("buy_to_open", "sell_to_open", "buy")), fills[0])
        _print_bars_around(entry_fill, label="ENTRY")
        exit_fills = [f for f in fills if f not in [entry_fill]]
        if exit_fills:
            _print_bars_around(max(exit_fills, key=lambda f: f.executed_at), label="EXIT")

    # ---- Path metrics ----
    print()
    print("  --- Trade Path Metrics ---")
    if not path:
        print("    (not computed yet — run Path Metrics from dashboard)")
    else:
        mfe = path.underlying_mfe_pct
        mae = path.underlying_mae_pct
        eff = path.underlying_exit_efficiency

        p("Underlying MFE", pct(mfe))
        p("Underlying MAE", pct(mae))
        p("Exit efficiency", f"{eff:.1f}%" if eff is not None else "-",
          warn=eff is not None and eff < 0)
        p("Giveback", pct(path.underlying_giveback_pct))
        p("Time to MFE", f"{path.time_to_underlying_mfe_minutes}m" if path.time_to_underlying_mfe_minutes else "-")
        p("Time to MAE", f"{path.time_to_underlying_mae_minutes}m" if path.time_to_underlying_mae_minutes else "-")
        p("Moved in favor first", flag(path.moved_in_favor_first))
        p("Hold bucket", path.hold_duration_bucket or "-")
        p("Exit time bucket", path.exit_time_bucket or "-")

        # Sanity checks
        print()
        print("  --- Sanity checks ---")
        _sanity(trade, path)

    print()


def _print_bars_around(fill: Fill, label: str, window_mins: int = 5):
    """Print the minute bars ±5 min around a fill's execution time."""
    from app.engine.alpaca import fetch_minute_bars_for_date
    from app.engine.indicators import bars_to_df
    import pandas as pd
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
    UTC = ZoneInfo("UTC")

    fill_dt_et = fill.executed_at.replace(tzinfo=ET)
    fill_dt_utc = fill_dt_et.astimezone(UTC)
    fill_date = fill.executed_at.date()

    bars = fetch_minute_bars_for_date([fill.ticker], fill_date).get(fill.ticker, [])
    if not bars:
        print(f"\n    [{label}] No cached minute bars for {fill.ticker} on {fill_date}")
        return

    df = bars_to_df(bars)
    window_start = fill_dt_utc - timedelta(minutes=window_mins)
    window_end = fill_dt_utc + timedelta(minutes=window_mins)
    window = df[(df.index >= window_start) & (df.index <= window_end)]

    print(f"\n  [{label}] Minute bars ±{window_mins}m around {fill_dt_et.strftime('%H:%M')} ET")
    print(f"  {'Time ET':<10}  {'Open':>8}  {'High':>8}  {'Low':>8}  {'Close':>8}  {'Volume':>10}  {'VWAP':>8}")
    print(f"  {'-'*8:<10}  {'-'*8:>8}  {'-'*8:>8}  {'-'*8:>8}  {'-'*8:>8}  {'-'*10:>10}  {'-'*8:>8}")
    for ts, row in window.iterrows():
        et_str = ts.astimezone(ET).strftime("%H:%M")
        marker = " ←" if abs((ts - fill_dt_utc).total_seconds()) < 61 else ""
        vwap = f"{row.get('bar_vwap', float('nan')):.4f}" if not pd.isna(row.get('bar_vwap', float('nan'))) else "-"
        print(f"  {et_str:<10}  {row['open']:>8.4f}  {row['high']:>8.4f}  {row['low']:>8.4f}  {row['close']:>8.4f}  {int(row.get('volume', 0)):>10,}  {vwap:>8}{marker}")


def _sanity(trade: Trade, path: TradePathMetrics):
    issues = []
    mfe = path.underlying_mfe_pct
    mae = path.underlying_mae_pct
    eff = path.underlying_exit_efficiency
    hold = trade.hold_duration_mins or 0

    if mfe is not None and mfe < 0:
        issues.append("MFE is negative — impossible, likely a pricing error")
    if mae is not None and mae < 0:
        issues.append("MAE is negative — impossible, likely a pricing error")
    if eff is not None and eff < 0:
        issues.append("Exit efficiency < 0 — exit was below entry on a profitable underlying move")
    if eff is not None and eff > 200:
        issues.append(f"Exit efficiency {eff:.0f}% seems too high — check entry price accuracy")
    if path.time_to_underlying_mfe_minutes is not None and path.time_to_underlying_mfe_minutes > hold + 5:
        issues.append("Time to MFE exceeds hold duration — bar alignment issue")
    if path.time_to_underlying_mae_minutes is not None and path.time_to_underlying_mae_minutes > hold + 5:
        issues.append("Time to MAE exceeds hold duration — bar alignment issue")
    if trade.realized_pnl and trade.realized_pnl > 0 and mfe is not None and mfe <= 0:
        issues.append("Trade was profitable but MFE is 0 — underlying price lookup may be wrong")

    if issues:
        for issue in issues:
            print(f"    ⚠  {issue}")
    else:
        print("    ✓  No obvious issues detected")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def list_recent(ticker: str | None = None, n: int = 10):
    with Session(engine) as session:
        q = select(Trade).where(Trade.status.in_(["closed", "expired"])).order_by(Trade.opened_at.desc())
        trades = session.exec(q).all()

    if ticker:
        trades = [t for t in trades if t.ticker.upper() == ticker.upper()]

    trades = trades[:n]
    print(f"\n{'ID':<38}  {'Ticker':<8}  {'Type':<6}  {'Opened':<20}  {'P&L':>10}")
    print("-" * 100)
    for t in trades:
        pnl = f"${t.realized_pnl:+.2f}" if t.realized_pnl is not None else "-"
        label = f"{t.option_type} ${t.strike}" if t.instrument_type == "option" else "stock"
        print(f"{str(t.id):<38}  {t.ticker:<8}  {label:<12}  {str(t.opened_at)[:19]:<20}  {pnl:>10}")
    print()


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or "--help" in args:
        print(__doc__)
    elif "--recent" in args:
        list_recent()
    elif "--ticker" in args:
        idx = args.index("--ticker")
        ticker = args[idx + 1] if idx + 1 < len(args) else None
        list_recent(ticker=ticker)
    else:
        inspect_trade(args[0])
