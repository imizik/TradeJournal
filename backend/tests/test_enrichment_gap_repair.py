"""The scheduled pipeline refills fields left empty, not just absent rows.

Same-day enrichment has no final minute bars or same-day hourly bar, and
columns added later start empty on old rows. These tests pin which gaps are
reselected, which are left alone as permanent, and that a gap-filling run
never replaces a stored value with nothing.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import enricher, trade_path
from app.engine.jobs import _alpaca_fill_ids, _polygon_fill_ids, _trade_path_ids
from app.models import Account, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        account = Account(id=uuid.uuid4(), name="Roth IRA", type="roth_ira", last4="8267")
        session.add(account)
        session.commit()
        session.info["account_id"] = account.id
        yield session


def _fill(session, *, executed_at=None, side="buy_to_open", **values) -> Fill:
    fill = Fill(
        id=uuid.uuid4(),
        account_id=session.info["account_id"],
        ticker=values.pop("ticker", "NVDA"),
        instrument_type=values.pop("instrument_type", "option"),
        side=side,
        contracts=1,
        price=values.pop("price", 150),
        executed_at=executed_at or datetime.utcnow() - timedelta(days=3),
        raw_email_id=str(uuid.uuid4()),
        **values,
    )
    session.add(fill)
    return fill


def _polygon_complete(**overrides) -> dict:
    values = {"underlying_price_at_fill": 100, "ema_9h_at_fill": 99, "rsi_14_at_fill": 50}
    values.update(overrides)
    return values


def test_polygon_reselects_fills_with_empty_indicators_inside_the_history_window(session):
    complete = _fill(session, **_polygon_complete())
    same_day_run = _fill(session, **_polygon_complete(ema_9h_at_fill=None))
    failed_daily_fetch = _fill(session, **_polygon_complete(rsi_14_at_fill=None))
    never_enriched = _fill(session)
    three_years_ago = datetime.utcnow() - timedelta(days=3 * 365)
    too_old_for_indicators = _fill(session, executed_at=three_years_ago, **_polygon_complete(ema_9h_at_fill=None))
    too_old_never_enriched = _fill(session, executed_at=three_years_ago)
    session.commit()

    selected = set(_polygon_fill_ids(session, "all", force=False))

    assert {same_day_run.id, failed_daily_fetch.id, never_enriched.id, too_old_never_enriched.id} <= selected
    assert complete.id not in selected
    assert too_old_for_indicators.id not in selected


def test_alpaca_reselects_rows_written_before_minute_bars_were_final(session):
    before_close = _fill(session)
    session.add(
        FillMarketContext(
            fill_id=before_close.id,
            data_source="alpaca_iex",
            fetched_at=datetime.utcnow(),
            entry_rsi_14=50,
            entry_ema_9=100,
            entry_ema_20=95,
        )
    )
    session.commit()

    assert before_close.id in set(_alpaca_fill_ids(session, "all", force=False))


def test_gap_filling_polygon_run_keeps_values_it_could_not_recompute(session, monkeypatch):
    fill = _fill(
        session,
        instrument_type="stock",
        executed_at=datetime(2026, 5, 14, 14, 30),
        **_polygon_complete(ema_9h_at_fill=None, sma_20_at_fill=97),
    )
    session.commit()
    monkeypatch.setattr(enricher, "POLYGON_API_KEY", "test")
    # The daily fetch fails and no minute bars come back; only the hourly
    # series answers, which is the gap this run exists to fill.
    monkeypatch.setattr(enricher, "_daily_indicator_series", lambda *_: {})
    monkeypatch.setattr(enricher, "_hourly_ema_series", lambda *_: {"2026-05-14 13": 101.5})
    monkeypatch.setattr(enricher, "fetch_minute_bars_for_days", lambda *_: {})

    enricher.enrich_fills([fill], session, keep_existing=True)

    stored = session.get(Fill, fill.id)
    assert float(stored.ema_9h_at_fill) == 101.5
    assert float(stored.underlying_price_at_fill) == 100
    assert float(stored.rsi_14_at_fill) == 50
    assert float(stored.sma_20_at_fill) == 97


def _trade(session, *, instrument_type="option", held=timedelta(minutes=30), fills=()) -> Trade:
    opened = datetime(2026, 5, 14, 10, 0)
    trade = Trade(
        id=uuid.uuid4(),
        account_id=session.info["account_id"],
        ticker="NVDA",
        instrument_type=instrument_type,
        contracts=1,
        avg_entry_premium=150,
        total_premium_paid=150,
        realized_pnl=25,
        opened_at=opened,
        closed_at=opened + held,
        status="closed",
    )
    session.add(trade)
    for fill in fills:
        session.add(TradeFill(trade_id=trade.id, fill_id=fill.id, role="entry" if fill.side == "buy_to_open" else "exit"))
    return trade


def _metrics(trade: Trade, **values) -> TradePathMetrics:
    complete = {"underlying_mfe_pct": 1.0, "mfe_atr_multiple": 0.5, "attr_delta_pnl": 10.0}
    complete.update(values)
    return TradePathMetrics(trade_id=trade.id, data_source="alpaca_iex", fetched_at=datetime.utcnow(), **complete)


def _option_round_trip(session, *, entry_delta=0.5, exit_underlying=101.0):
    entry = _fill(session, executed_at=datetime(2026, 5, 14, 10, 0), underlying_price_at_fill=100, delta_at_fill=entry_delta)
    exit_ = _fill(
        session, side="sell_to_close", executed_at=datetime(2026, 5, 14, 10, 30), underlying_price_at_fill=exit_underlying
    )
    return entry, exit_


def test_path_metrics_reselect_only_gaps_whose_inputs_exist_now(session):
    complete = _trade(session, fills=_option_round_trip(session))
    session.add(_metrics(complete))

    not_computed = _trade(session, fills=_option_round_trip(session))

    before_polygon = _trade(session, fills=_option_round_trip(session))
    session.add(_metrics(before_polygon, attr_delta_pnl=None))

    no_implied_vol = _trade(session, fills=_option_round_trip(session, entry_delta=None))
    session.add(_metrics(no_implied_vol, attr_delta_pnl=None))

    closed_same_day = _trade(session, fills=_option_round_trip(session))
    session.add(_metrics(closed_same_day, underlying_mfe_pct=None, mfe_atr_multiple=None))

    swing = _trade(session, instrument_type="stock", held=timedelta(days=30))
    session.add(_metrics(swing, underlying_mfe_pct=None, mfe_atr_multiple=None, attr_delta_pnl=None))

    entry = _fill(session, instrument_type="stock", side="buy", executed_at=datetime(2026, 5, 14, 10, 0))
    session.add(FillMarketContext(fill_id=entry.id, data_source="alpaca_iex", fetched_at=datetime.utcnow(), entry_atr_14=3.0))
    atr_column_added_later = _trade(session, instrument_type="stock", fills=[entry])
    session.add(_metrics(atr_column_added_later, mfe_atr_multiple=None, attr_delta_pnl=None))
    session.commit()

    selected = set(_trade_path_ids(session, "all", force=False))

    assert selected == {not_computed.id, before_polygon.id, closed_same_day.id, atr_column_added_later.id}


def test_recomputed_path_row_keeps_stored_values_when_fills_are_unchanged(session, monkeypatch):
    fills = _option_round_trip(session)
    trade = _trade(session, fills=fills)
    fingerprint = trade_path.trade_inputs_fingerprint(trade, list(fills))
    session.add(_metrics(trade, attr_delta_pnl=None, post_exit_mfe_30m=0.8, inputs_fingerprint=fingerprint))
    session.commit()

    def recompute_without_bars(trade, fills, ctx_by_fill, bar_store):
        # Bars failed to load this time, but Polygon greeks have arrived.
        return _metrics(trade, underlying_mfe_pct=None, mfe_atr_multiple=None, attr_delta_pnl=12.0)

    monkeypatch.setattr(trade_path, "_prefetch_minute_bars", lambda *_: {})
    monkeypatch.setattr(trade_path, "_compute", recompute_without_bars)

    trade_path.compute_path_metrics_for_trades([trade], session, force=True, keep_existing=True)

    stored = session.exec(select(TradePathMetrics).where(TradePathMetrics.trade_id == trade.id)).one()
    assert stored.attr_delta_pnl == 12.0
    assert stored.underlying_mfe_pct == 1.0
    assert stored.mfe_atr_multiple == 0.5
    assert stored.post_exit_mfe_30m == 0.8
