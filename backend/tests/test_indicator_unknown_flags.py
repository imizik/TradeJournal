from datetime import datetime
from types import SimpleNamespace

from app.engine.indicators import compute_flags


def test_missing_market_inputs_are_unknown_instead_of_false():
    fill = SimpleNamespace(side="buy_to_open", executed_at=datetime(2026, 9, 24, 12, 46), expiration=None)
    flags = compute_flags(fill, {}, {})

    for name in (
        "is_chase_entry", "is_late_move", "is_vwap_reclaim",
        "is_opening_range_breakout", "is_premarket_breakout",
        "is_near_resistance_on_call_entry",
    ):
        assert flags[name] is None
    assert flags["chase_score"] is None
    assert flags["setup_quality_score"] is None
    assert flags["entry_time_bucket"] == "mid"


def test_observed_non_breakout_is_false():
    fill = SimpleNamespace(side="buy_to_open", executed_at=datetime(2026, 9, 24, 12, 46), expiration=None)
    flags = compute_flags(fill, {
        "entry_underlying_price": 100,
        "entry_vwap": 101,
        "prev_bar_close": 100,
        "opening_range_5m_high": 110,
        "premarket_high": 120,
        "entry_distance_from_day_high_pct": -2,
        "entry_distance_from_prev_high_pct": -4,
    }, {})

    assert flags["is_vwap_reclaim"] == 0
    assert flags["is_opening_range_breakout"] == 0
    assert flags["is_premarket_breakout"] == 0
    assert flags["is_late_move"] == 0
    assert flags["is_near_resistance_on_call_entry"] == 0
