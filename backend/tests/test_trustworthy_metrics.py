"""Historical-context and position-exposure regressions."""
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import trade_path
from app.engine.alpaca_enricher import _build_context
from app.engine.indicators import analyze_minute_bars, compute_flags
from app.engine.metric_versions import CONTEXT_VERSION, PATH_VERSION
from app.models import Account, DailyReviewRecord, Fill, FillMarketContext, Tag, Trade, TradeTag, TradePathMetrics
from app.routers.fills import _rebuild_trades


def fill(side="buy_to_open", minute=0, qty=1, price=100, **values):
    defaults = dict(id=uuid.uuid4(), account_id=uuid.uuid4(), ticker="AMD", instrument_type="option",
                    option_type="call", strike=100, expiration=date(2026, 9, 30), side=side,
                    contracts=qty, price=price, raw_email_id=str(uuid.uuid4()), executed_at=datetime(2026, 9, 24, 10, minute))
    defaults.update(values)
    return Fill(**defaults)


def bar(minute, high=1.1, low=1.0, day="2026-09-24", hour=14):
    return dict(t=f"{day}T{hour:02}:{minute:02}:00Z", o=1, h=high, l=low, c=1, v=100)


def trade(fills, realized=190):
    return Trade(id=fills[0].id, account_id=fills[0].account_id, ticker="AMD", instrument_type="option",
                 option_type="call", strike=100, expiration=date(2026, 9, 30), contracts=10,
                 avg_entry_premium=100, total_premium_paid=1000, opened_at=fills[0].executed_at,
                 closed_at=fills[-1].executed_at, status="closed", realized_pnl=realized)


def test_entry_context_excludes_future_and_unfinished_ranges():
    bars = [bar(30, high=105, low=99, hour=13), bar(34, high=150, low=98, hour=13)]
    ctx = analyze_minute_bars(bars, datetime(2026, 9, 24, 9, 31))
    assert ctx == analyze_minute_bars(bars[:1], datetime(2026, 9, 24, 9, 31))
    assert ctx["opening_range_5m_high"] is None
    assert ctx["opening_range_15m_high"] is None
    assert ctx["entry_day_high_so_far"] == 105
    assert ctx["entry_context_as_of"] == datetime(2026, 9, 24, 9, 31)
    assert analyze_minute_bars(bars, datetime(2026, 9, 24, 9, 30)) == {}
    assert analyze_minute_bars(bars, datetime(2026, 9, 24, 9, 35))["opening_range_5m_high"] == 150


@pytest.mark.parametrize("price,high,low,expected", [(664.37,664.44,653.24,99.38),
    (13.11,13.245,12.765,71.88), (462.955,463.16,456.6,96.88)], ids=["SPY", "BULL", "MSFT"])
def test_entry_range_rounds_exact_decimal_ties(price, high, low, expected):
    bars = [dict(t="2026-09-24T13:30:00Z", o=price, h=high, l=low, c=price, v=100)]
    assert analyze_minute_bars(bars, datetime(2026,9,24,9,31))["entry_day_range_used_pct"] == expected


def test_entry_vwap_decimal_tie_and_derived_percentage():
    # The five completed FMST bars in the frozen production evidence.
    bars = [dict(t="2025-10-02T14:05:00Z", o=3.14, h=3.14, l=3.14, c=3.14, v=100),
            dict(t="2025-10-02T15:27:00Z", o=2.995, h=2.995, l=2.995, c=2.995, v=100),
            dict(t="2025-10-02T16:32:00Z", o=2.96, h=2.96, l=2.96, c=2.96, v=100),
            dict(t="2025-10-02T17:46:00Z", o=2.975, h=2.975, l=2.97, c=2.97, v=300),
            dict(t="2025-10-02T18:07:00Z", o=2.97, h=2.97, l=2.97, c=2.97, v=200)]
    result = analyze_minute_bars(bars, datetime(2025,10,2,14,19))
    assert result["entry_vwap"] == 2.9938  # exact volume-weighted value is 2.99375
    assert result["entry_vs_vwap_pct"] == -0.795


@pytest.mark.parametrize("option_type,side,aligned", [("call", "buy_to_open", 1), ("put", "buy_to_open", 0),
    ("put", "sell_to_open", 1), ("call", "sell_to_open", 0), (None, "buy_to_open", None)])
def test_flags_follow_underlying_direction(option_type, side, aligned):
    flags = compute_flags(fill(side=side, option_type=option_type),
                          dict(entry_underlying_price=110, entry_vwap=105, prev_bar_close=104),
                          dict(ema_9=108, ema_20=106, macd_histogram=1))
    assert flags["is_trend_aligned"] == aligned
    assert flags["is_above_vwap"] == aligned
    if aligned is None:
        assert flags["chase_score"] is None
        assert flags["setup_quality_score"] is None


def test_gap_uses_actual_open(monkeypatch):
    from app.engine import alpaca_enricher
    monkeypatch.setattr(alpaca_enricher, "compute_rvol_time_adjusted", lambda *_: None)
    f = fill(executed_at=datetime(2026, 9, 24, 9, 35))
    bars = [dict(t="2026-09-24T13:30:00Z", o=100, h=150, l=99, c=105, v=100)]
    daily = {"AMD": [dict(t="2026-09-23T04:00:00Z", o=100, h=101, l=99, c=100, v=100)]}
    ctx = _build_context(f, daily, {}, {"AMD": bars})
    assert ctx.entry_gap_pct == 0
    assert ctx.calculation_version == CONTEXT_VERSION


def test_partial_exit_reduces_later_exposure():
    fills = [fill(qty=10), fill("sell_to_close", 10, 9, 110), fill("sell_to_close", 30, 1, 200)]
    result = trade_path.option_position_path(trade(fills), fills,
        [bar(1), bar(11, high=2, low=1.1), bar(29, high=2, low=1.1)])
    assert result["option_peak_total_pnl"] == 190
    assert result["option_peak_unrealized_pnl"] == 100
    assert result["option_giveback_from_peak"] == 0
    assert result["option_exit_efficiency"] == 100


def test_scale_in_does_not_use_future_basis():
    fills = [fill(), fill(minute=10, qty=9, price=200), fill("sell_to_close", 30, 10, 200)]
    t = trade(fills, 100)
    t.avg_entry_premium = 190
    result = trade_path.option_position_path(t, fills, [bar(1, high=1.5), bar(11, high=2, low=1.9)])
    assert result["option_mfe_pct"] == 50
    assert result["option_peak_total_pnl"] == 100


def test_fill_minutes_and_outside_holding_bars_are_excluded():
    fills = [fill(), fill("sell_to_close", 10, 1, 110)]
    result = trade_path.option_position_path(trade(fills, 10), fills,
        [bar(59, high=99, hour=13), bar(0, high=99), bar(1), bar(10, high=99)])
    assert result["option_max_price_seen"] == 110
    assert result["option_peak_total_pnl"] == 10
    assert trade_path.option_position_path(trade(fills, 10), fills, [bar(0, high=99)])["option_path_quality"] == "unavailable_holding_bars"


def test_multiday_paths_use_minutes(monkeypatch):
    fills = [fill(), fill("sell_to_close", executed_at=datetime(2026, 9, 25, 10, 10))]
    calls = []
    def fetch(symbols, timeframe, start, end):
        calls.append((timeframe, start, end))
        return {symbols[0]: [bar(1, high=1.2), bar(1, high=1.3, day="2026-09-25")]}
    monkeypatch.setattr(trade_path, "fetch_option_bars", fetch)
    monkeypatch.setattr(trade_path, "_minute_session_complete", lambda _: True)
    result = trade_path._compute_option_path(trade(fills, 0), fills[0], fills)
    assert calls[0][0] == "1Min"
    assert isinstance(calls[0][1], datetime)
    assert result["option_max_price_seen"] == 130


def test_contract_and_market_inputs_change_fingerprint():
    f = fill()
    t = trade([f, fill("sell_to_close", 10)])
    before = trade_path.trade_inputs_fingerprint(t, [f])
    f.strike = Decimal(110)
    assert before != trade_path.trade_inputs_fingerprint(t, [f])
    ctx = FillMarketContext(fill_id=f.id, data_source="alpaca_iex", fetched_at=datetime.now(), entry_atr_14=2)
    contexts = {str(f.id): ctx}
    before = trade_path.market_inputs_fingerprint([f], contexts)
    ctx.fetched_at += timedelta(minutes=1)
    assert before == trade_path.market_inputs_fingerprint([f], contexts)
    ctx.entry_atr_14 = 3
    assert before != trade_path.market_inputs_fingerprint([f], contexts)


def test_rebuild_preserves_annotations_and_stales_changed_review():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(name="Test", type="individual", last4="1234")
        session.add(account)
        session.flush()
        fills = [fill(account_id=account.id), fill("sell_to_close", 10, price=110, account_id=account.id)]
        session.add_all(fills)
        session.flush()
        _rebuild_trades(session, "test")
        session.flush()
        t = session.get(Trade, fills[0].id)
        t.ai_review = json.dumps({"note": "keep"})
        group = uuid.uuid4()
        t.roll_group_id = group
        saved_daily = DailyReviewRecord(day=date(2026, 9, 24), review_json=json.dumps({"summary": "keep"}))
        session.add(saved_daily)
        tag = Tag(name="breakout", source="manual")
        session.add(tag)
        session.flush()
        session.add(TradeTag(trade_id=t.id, tag_id=tag.id))
        session.commit()
        _rebuild_trades(session, "unchanged")
        session.commit()
        assert json.loads(session.get(Trade, fills[0].id).ai_review) == {"note": "keep"}
        assert session.get(Trade, fills[0].id).roll_group_id == group
        assert json.loads(session.get(DailyReviewRecord, saved_daily.id).review_json) == {"summary": "keep"}
        assert len(session.exec(select(TradeTag)).all()) == 1
        fills[1].price = Decimal(120)
        session.add(fills[1])
        session.flush()
        _rebuild_trades(session, "changed")
        session.commit()
        assert json.loads(session.get(Trade, fills[0].id).ai_review) == {"note": "keep", "source_data_stale": True}
        assert json.loads(session.get(DailyReviewRecord, saved_daily.id).review_json) == {"summary": "keep", "source_data_stale": True}
        assert len(session.exec(select(TradeTag)).all()) == 1


def test_legacy_metrics_reselected():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(name="Test", type="individual", last4="1234")
        session.add(account)
        session.flush()
        f = fill(account_id=account.id)
        session.add(f)
        session.flush()
        t = trade([f, fill("sell_to_close", 10)], 10)
        session.add(t)
        session.flush()
        session.add(TradePathMetrics(trade_id=t.id, data_source="alpaca_iex", fetched_at=datetime.now(), underlying_mfe_pct=2))
        session.commit()
        assert trade_path.trades_needing_path_metrics(session, [t]) == [t.id]


def test_short_option_path_has_signed_exposure():
    fills = [fill("sell_to_open", qty=2, price=200), fill("buy_to_close", 10, 2, 100)]
    result = trade_path.option_position_path(trade(fills, 200), fills, [bar(1, high=2.5, low=1)])
    assert result["option_peak_total_pnl"] == 200
    assert result["option_worst_unrealized_pnl"] == -100
    assert result["option_exit_efficiency"] == 100


@pytest.mark.parametrize("price,qty,exit_price", [(220, 2, 63), (415, 1, 390)], ids=["RDDT", "NFLX"])
def test_zero_peak_from_audited_premiums_has_no_capture_ratios(price, qty, exit_price):
    # These premiums reproduced the production bug: 2.2*100 and 4.15*100
    # leave a positive float residue even though the observed peak is zero.
    fills = [fill(qty=qty, price=price), fill("sell_to_close", 10, qty, exit_price)]
    realized = (exit_price - price) * qty
    bars = [dict(t="2026-09-24T14:01:00Z", o=price/100, h=price/100,
                 l=exit_price/100, c=exit_price/100, v=100)]
    result = trade_path.option_position_path(trade(fills, realized), fills, bars)
    assert result["option_mfe_pct"] == 0
    assert result["option_peak_total_pnl"] == 0
    assert result["option_giveback_from_peak"] == -realized
    assert result["option_exit_efficiency"] is None
    assert result["option_giveback_pct"] is None
    assert result["time_to_option_mfe_minutes"] is None


def test_short_zero_peak_has_no_capture_ratios():
    fills = [fill("sell_to_open", price=230), fill("buy_to_close", 10, price=240)]
    bars = [dict(t="2026-09-24T14:01:00Z", o=2.3, h=2.4, l=2.3, c=2.4, v=100)]
    result = trade_path.option_position_path(trade(fills, -10), fills, bars)
    assert result["option_peak_total_pnl"] == 0
    assert result["option_exit_efficiency"] is None
    assert result["option_giveback_pct"] is None
    assert result["time_to_option_mfe_minutes"] is None


@pytest.mark.parametrize("high,peak,efficiency", [(2.000000001, 0, None), (2.0000001, 0.00001, -100000000)])
def test_capture_ratios_require_a_peak_representable_at_stored_dollar_precision(high, peak, efficiency):
    fills = [fill(price=200), fill("sell_to_close", 10, price=190)]
    bars = [dict(t="2026-09-24T14:01:00Z", o=2, h=high, l=1.9, c=2, v=100)]
    result = trade_path.option_position_path(trade(fills, -10), fills, bars)
    assert result["option_peak_total_pnl"] == peak
    assert result["option_exit_efficiency"] == efficiency
    if efficiency is None:
        assert result["option_giveback_pct"] is None
        assert result["time_to_option_mfe_minutes"] is None
    else:
        assert result["option_giveback_pct"] == 100000100
        assert result["time_to_option_mfe_minutes"] == 1


def test_ambiguous_fill_allocation_stays_missing():
    fills = [fill(), fill("sell_to_close", 10, 2, 110)]
    result = trade_path.option_position_path(trade(fills, 10), fills, [bar(1)])
    assert result == {"option_path_quality": "unavailable_fill_allocation"}


def test_version_and_context_change_reselect_a_current_complete_path():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(name="Test", type="individual", last4="1234")
        session.add(account)
        session.flush()
        fills = [fill(account_id=account.id), fill("sell_to_close", 10, price=110, account_id=account.id)]
        session.add_all(fills)
        session.flush()
        _rebuild_trades(session, "test")
        session.flush()
        t = session.get(Trade, fills[0].id)
        ctx = FillMarketContext(fill_id=fills[0].id, data_source="alpaca_iex", fetched_at=datetime.now(), entry_atr_14=2)
        session.add(ctx)
        session.flush()
        session.add(TradePathMetrics(trade_id=t.id, data_source="alpaca_iex", fetched_at=datetime.now(),
            calculation_version=PATH_VERSION, underlying_mfe_pct=2, mfe_atr_multiple=1, attr_delta_pnl=1,
            inputs_fingerprint=trade_path.trade_inputs_fingerprint(t, fills),
            market_inputs_fingerprint=trade_path.market_inputs_fingerprint(fills, {str(ctx.fill_id): ctx})))
        session.commit()
        assert trade_path.trades_needing_path_metrics(session, [t]) == []
        metrics = session.get(TradePathMetrics, t.id)
        metrics.calculation_version = "position-path-v2"
        session.add(metrics)
        session.commit()
        assert trade_path.trades_needing_path_metrics(session, [t]) == [t.id]
        metrics.calculation_version = PATH_VERSION
        session.add(metrics)
        session.commit()
        assert trade_path.trades_needing_path_metrics(session, [t]) == []
        ctx.entry_atr_14 = 3
        session.add(ctx)
        session.commit()
        assert trade_path.trades_needing_path_metrics(session, [t]) == [t.id]


def test_option_cache_written_before_session_final_is_refetched(tmp_path, monkeypatch):
    import os
    from app.engine import alpaca
    cache = tmp_path / "option.json"
    cache.write_text(json.dumps([bar(1, high=9)]))
    os.utime(cache, (0, 0))
    monkeypatch.setattr(alpaca, "_option_bars_cache_path", lambda *_: cache)
    calls = []
    def fetch(*args):
        calls.append(args)
        return {"AMD": [bar(1)]}
    monkeypatch.setattr(alpaca, "_fetch_all_pages", fetch)
    result = alpaca.fetch_option_bars(["AMD"], "1Min", date(2026, 9, 24), date(2026, 9, 24))
    assert result["AMD"][0]["h"] == 1.1
    assert len(calls) == 1
    alpaca.fetch_option_bars(["AMD"], "1Min", date(2026, 9, 24), date(2026, 9, 24))
    assert len(calls) == 1


def test_option_fetch_never_caches_provisional_bars(tmp_path, monkeypatch):
    from app.engine import alpaca
    cache = tmp_path / "option.json"
    monkeypatch.setattr(alpaca, "_option_bars_cache_path", lambda *_: cache)
    monkeypatch.setattr(alpaca, "_minute_session_complete", lambda _: False)
    monkeypatch.setattr(alpaca, "_fetch_all_pages", lambda *_: {"AMD": [bar(1)]})
    assert alpaca.fetch_option_bars(["AMD"], "1Min", date(2026, 9, 24), date(2026, 9, 24))["AMD"]
    assert not cache.exists()
