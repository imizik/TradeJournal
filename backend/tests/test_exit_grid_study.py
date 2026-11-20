"""Exit settings grid on synthetic option bars: each part of a combo, the
earliest trigger winning, the extract from API JSON and the pass rule."""

from datetime import date, time as day_time
from decimal import Decimal
import json
import random

import pytest

from scripts import exit_grid_study as g
from tests.test_exit_counterfactual_study import at, fill, minutes, trade


def run(combo, fills, bars, expiration=date(2026, 5, 8)):
    t = trade(expiration=expiration)
    return g.combo_diffs(combo, t, g.prepare(t, fills, bars))


def test_giveback_waits_for_twenty_percent_then_sells_after_giving_back_its_share():
    # 1 contract at $1.00. Peak 1.40 (+40%); 30% give-back fires at +28% or less: the 1.25 bar.
    fills = [fill(g.cf.ENTRY, "10:00", 1, 100), fill(g.cf.EXIT, "10:30", 1, 100)]
    bars = minutes("10:01", [1.15, 1.40, 1.30, 1.25, 1.20, 1.10])
    combo = (Decimal("0.30"), None, None)
    assert g.combo_trigger(combo, trade(), g.prepare(trade(), fills, bars)[5]) == at("10:05")
    base, stress = run(combo, fills, bars)
    # Sold at the 10:05 open 1.20: 120 - 3.60 = 116.40 against 0 actual.
    assert base == pytest.approx(16.40)
    assert stress == pytest.approx(120 - 10.80 - 100)


def test_giveback_never_arms_below_twenty_percent():
    fills = [fill(g.cf.ENTRY, "10:00", 1, 100), fill(g.cf.EXIT, "10:30", 1, 50)]
    bars = minutes("10:01", [1.19, 1.00, 0.60])
    assert run((Decimal("0.50"), None, None), fills, bars) is None


def test_loss_stop_sells_at_the_next_open_after_the_threshold():
    fills = [fill(g.cf.ENTRY, "10:00", 2, 100), fill(g.cf.EXIT, "10:30", 2, 20)]
    bars = minutes("10:01", [0.80, 0.59, 0.55, 0.30])
    base, _ = run((None, Decimal("0.40"), None), fills, bars)
    # -41% at the 10:02 close; 10:03 open 0.55: 2 x (55 - 1.65 - 100) = -93.30 vs actual -160.
    assert base == pytest.approx(-93.30 + 160)


def test_expiry_exit_uses_the_clock_on_expiration_day_and_earliest_trigger_wins():
    day = date(2026, 5, 6)
    fills = [fill(g.cf.ENTRY, "10:00", 1, 100), fill(g.cf.EXIT, "15:45", 1, 10)]
    bars = minutes("10:01", [1.0] * 5) + [{"t": at("12:00"), "o": Decimal("0.80"), "c": Decimal("0.80")},
                                          {"t": at("13:00"), "o": Decimal("0.50"), "c": Decimal("0.50")}]
    combo = (None, Decimal("0.40"), day_time(12))
    t = trade(expiration=day)
    assert g.combo_trigger(combo, t, g.prepare(t, fills, bars)[5]) == at("12:00")
    base, _ = run(combo, fills, bars, expiration=day)
    assert base == pytest.approx(80 - 2.40 - 10)
    # Not on expiration day: the clock part does nothing.
    assert run((None, None, day_time(12)), fills, bars) is None


def test_extract_keeps_closed_and_expired_options_and_loads_through_the_shared_loader(tmp_path):
    trades = [
        {"id": "a", "instrument_type": "option", "status": "closed", "ticker": "SPY", "option_type": "call",
         "strike": 500.0, "expiration": "2026-05-08", "opened_at": "2026-05-06T10:00:00",
         "closed_at": "2026-05-06T10:30:00", "realized_pnl": 0.0, "total_premium_paid": 100.0, "account_id": "x"},
        {"id": "b", "instrument_type": "stock", "status": "closed", "opened_at": "2026-05-06T10:00:00"},
        {"id": "c", "instrument_type": "option", "status": "open", "opened_at": "2026-05-06T10:00:00"},
    ]
    fills = {"a": [{"id": "f1", "side": "buy_to_open", "contracts": 1.0, "price": 100.0, "executed_at": "2026-05-06T10:00:00"},
                   {"id": "f2", "side": "sell_to_close", "contracts": 1.0, "price": 100.0, "executed_at": "2026-05-06T10:30:00"}]}
    path = tmp_path / "extract.json"
    path.write_text(json.dumps(g.build_extract(trades, fills)))
    loaded, by_trade, excluded = g.cf.load_extract(path, g.PROTOCOL_ID)
    assert [t["id"] for t in loaded] == ["a"] and len(by_trade["a"]) == 2 and not excluded


def test_pass_needs_a_positive_total_mostly_positive_draws_and_more_than_one_trade():
    rows = [{"day": "2026-11-02", "k": (300.0, 200.0)}, {"day": "2026-11-03", "k": (-50.0, -60.0)},
            {"day": "2026-11-04", "k": None}]
    summary = g.summarize(rows, "k", random.Random(1))
    assert summary["dollar_diff"] == 250 and summary["without_biggest"] == -50
    assert not g.passes(summary)
    assert g.passes({"dollar_diff": 10, "share_above_zero": 0.85, "without_biggest": 1})
    assert not g.passes({"dollar_diff": 10, "share_above_zero": 0.7, "without_biggest": 1})


def test_grid_is_small_and_names_parse_back():
    assert len(g.COMBOS) == 36
    assert g.combo_name(g.parse_combo("30,none,15:30")) == "giveback 30%/no stop/expiry 15:30"
