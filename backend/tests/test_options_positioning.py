"""Option positioning (Charts C4.2) and the levels it draws (C4.4), on hand-built chains.

Every expected number here is worked by hand in the test's comments, not read
back from the code: Black-Scholes gamma at the money, dollar gamma for a 1%
move, and a gamma flip whose crossing has a closed form.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from math import exp, pi, sqrt

import pytest

from app.engine import chart_levels
from app.engine.chart_math import ET
from app.engine.options_models import OptionChain, OptionContract
from app.engine.options_positioning import (DEALER_SIDE, StrikeRow, bs_gamma, chart_levels as option_levels, dollar_gamma,
                                            expires_at, gamma_flip, max_pain, net_gamma_at, positioning, scope_expirations)

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=ET)  # a Monday morning
TODAY = date(2026, 10, 5)


def contract(strike, side="call", oi=0, volume=0, iv=0.2, root="SPY", expiration=TODAY, multiplier=100,
             smoothed=None, bid=None, ask=None, underlying=None):
    letter = "C" if side == "call" else "P"
    return OptionContract(
        symbol=f"{root}{expiration:%y%m%d}{letter}{int(strike * 1000):08d}", underlying=underlying or ("SPX" if root.startswith("SPX") else root),
        root=root, expiration=expiration, option_type=side, strike=float(strike), multiplier=multiplier,
        bid=bid, ask=ask, last=None, bid_size=None, ask_size=None, volume=volume, open_interest=oi,
        bid_time=None, ask_time=None, trade_time=None, iv=iv, iv_smoothed=smoothed, delta=None, gamma=None, theta=None,
        vega=None, greeks_updated_at="2026-10-02 20:00:06")


def chain(contracts, expiration=TODAY, underlying="SPY"):
    return OptionChain(underlying, expiration, "tradier", datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc), tuple(contracts))


# --- the gamma formula -----------------------------------------------------


def test_black_scholes_gamma_matches_a_hand_computation():
    # S = K = 100, T = 0.25 years, sigma = 20%, r = q = 0:
    # d1 = (ln 1 + 0.2^2/2 x 0.25) / (0.2 x 0.5) = 0.005 / 0.1 = 0.05
    # gamma = phi(0.05) / (S sigma sqrt(T)) = 0.3984439 / 10 = 0.03984439
    assert bs_gamma(100, 100, 0.25, 0.2) == pytest.approx(0.03984439, abs=1e-8)
    assert bs_gamma(100, 100, 0.0, 0.2) is None  # expired
    assert bs_gamma(100, 100, 0.25, 0.0) is None  # no volatility, no model


def test_dollar_gamma_is_the_dollar_delta_change_for_a_one_percent_move():
    # 0.03984439 x 1,000 contracts x 100 shares x 100^2 x 0.01 = 398,443.9 dollars of delta per 1%.
    assert dollar_gamma(0.03984439, 1000, 100, 100) == pytest.approx(398443.9, abs=0.1)


def test_contracts_expire_at_the_close_or_the_open_for_an_am_settled_root():
    assert expires_at(TODAY, "SPY") == datetime(2026, 10, 5, 16, 0, tzinfo=ET)
    assert expires_at(TODAY, "SPXW") == datetime(2026, 10, 5, 16, 0, tzinfo=ET)
    assert expires_at(TODAY, "SPX") == datetime(2026, 10, 5, 9, 30, tzinfo=ET)
    # An early close (13:00) from the calendar ends a PM-settled contract then.
    assert expires_at(date(2026, 11, 27), "SPY", {date(2026, 11, 27): 13 * 60}) == datetime(2026, 11, 27, 13, 0, tzinfo=ET)


def test_gamma_uses_the_price_handed_in_and_the_time_to_the_close():
    # 2026-10-05 10:00 to 16:00 New York is 6 hours: T = 6 / (365 x 24) years.
    years = 6 / (365 * 24)
    found = positioning([chain([contract(100, oi=1000, iv=0.2)])], "SPY", 100.0, NOW)
    d1 = (0.02 * years) / (0.2 * sqrt(years))
    expected = exp(-d1 * d1 / 2) / sqrt(2 * pi) / (100 * 0.2 * sqrt(years)) * 1000 * 100 * 100 ** 2 * 0.01
    assert found.strikes[0].call_gamma == pytest.approx(expected, rel=1e-12)
    # The provider's hourly greek is never used: the contract above carries none at all.
    assert found.missing == {}


# --- per strike and in aggregate -------------------------------------------


def test_strikes_sum_across_expirations_and_keep_roots_apart():
    later = date(2026, 10, 9)
    first = chain([contract(6600, "call", 100, 10, root="SPXW"), contract(6600, "put", 300, 40, root="SPXW"),
                   contract(6600, "call", 5000, 1, root="SPX")], underlying="SPX")
    second = chain([contract(6600, "call", 50, 5, root="SPXW", expiration=later), contract(6650, "put", 0, 0, root="SPXW", expiration=later)],
                   expiration=later, underlying="SPX")
    found = positioning([first, second], "SPX", 6610.0, NOW)

    assert found.root == "SPXW"  # SPX's dailies and weeklies are SPXW; the AM-settled SPX root is left out
    assert found.excluded == {"SPX": 1}
    assert found.expirations == (TODAY, later)
    rows = {row.strike: row for row in found.strikes}
    assert (rows[6600].call_oi, rows[6600].put_oi, rows[6600].call_volume, rows[6600].put_volume) == (150, 300, 15, 40)
    # A listed contract with no open interest is a real zero; a side with nothing listed stays unknown.
    assert (rows[6650].call_oi, rows[6650].put_oi, rows[6650].put_volume) == (None, 0, 0)


def test_a_missing_provider_value_stays_missing_and_is_counted():
    found = positioning([chain([contract(100, oi=None, volume=None), contract(100, "put", oi=7, volume=2, iv=None),
                                contract(105, oi=3, multiplier=None)])], "SPY", 100.0, NOW)
    rows = {row.strike: row for row in found.strikes}
    assert rows[100].call_oi is None and rows[100].put_oi == 7
    assert rows[100].call_gamma is None and rows[100].put_gamma is None  # no OI; no IV
    assert rows[105].call_gamma is None  # a contract size the provider did not give is not assumed to be 100
    assert found.missing == {"open_interest": 1, "volume": 1, "gamma": 3}


def test_the_smoothed_volatility_stands_in_for_a_missing_mid_iv():
    plain = positioning([chain([contract(100, oi=10, iv=0.3)])], "SPY", 100.0, NOW)
    smoothed = positioning([chain([contract(100, oi=10, iv=None, smoothed=0.3)])], "SPY", 100.0, NOW)
    assert smoothed.strikes[0].call_gamma == plain.strikes[0].call_gamma


def test_without_a_price_there_is_no_gamma_but_open_interest_still_counts():
    found = positioning([chain([contract(100, oi=10)])], "SPY", None, NOW)
    assert found.strikes[0].call_oi == 10 and found.strikes[0].call_gamma is None


def test_totals_and_ratios_never_divide_by_zero():
    found = positioning([chain([contract(100, "call", 200, 50), contract(100, "put", 300, 0), contract(95, "put", 100, 30)])], "SPY", 100.0, NOW)
    totals = found.totals()
    assert (totals["call_oi"], totals["put_oi"], totals["call_volume"], totals["put_volume"]) == (200, 400, 50, 30)
    assert totals["put_call_oi"] == 2.0 and totals["put_call_volume"] == 0.6
    assert totals["call_volume_oi"] == 0.25 and totals["put_volume_oi"] == 0.075
    assert positioning([chain([contract(95, "put", 10, 1)])], "SPY", 100.0, NOW).totals()["put_call_oi"] is None


def test_walls_are_the_highest_strike_on_each_side_and_a_tie_goes_to_the_nearer_strike():
    found = positioning([chain([contract(105, "call", 900), contract(110, "call", 1500), contract(120, "call", 1500),
                                contract(95, "put", 2000), contract(90, "put", 800)])], "SPY", 101.0, NOW)
    assert found.wall("oi", "call").strike == 110  # 110 and 120 tie at 1,500; 110 is nearer 101
    assert found.wall("oi", "put").strike == 95
    assert [row.strike for row in found.ranked("oi", "call")] == [110, 120, 105]
    assert found.rank(found.strikes[-1], "oi", "call") == 2  # 120
    assert found.rank(StrikeRow(90.0, put_oi=800), "oi", "call") is None


def test_signed_gamma_counts_calls_up_and_puts_down():
    row = StrikeRow(100.0, call_gamma=5.0, put_gamma=8.0)
    assert row.total("gamma") == 13.0
    assert row.total("gamma", signed=True) == -3.0
    assert "short puts" in DEALER_SIDE


# --- the gamma flip --------------------------------------------------------


def test_the_gamma_flip_lands_where_hand_algebra_puts_it():
    # One call at 105 and one put at 95, equal open interest, IV and time. Signed
    # gamma is zero where their Black-Scholes gammas are equal, where
    # |d1| matches: ln(S/105) + c = -(ln(S/95) + c), c = sigma^2 T / 2, so
    # S = sqrt(105 x 95) x e^-c. Here T = 30 days exactly (16:00 to 16:00):
    # c = 0.04 x 30/365 / 2 and S = 99.8749 x 0.998358 = 99.7109.
    expiry = date(2026, 11, 4)
    at = datetime(2026, 10, 5, 16, 0, tzinfo=ET)
    chains = [chain([contract(105, "call", 1000, expiration=expiry), contract(95, "put", 1000, expiration=expiry)], expiry)]
    flip = gamma_flip(chains, "SPY", 100.0, at)
    assert flip.price == pytest.approx(sqrt(105 * 95) * exp(-0.04 * 30 / 365 / 2), abs=0.01)
    assert flip.note.startswith("Model estimate")
    assert net_gamma_at(chains, "SPY", flip.price + 1, at) > 0 > net_gamma_at(chains, "SPY", flip.price - 1, at)


def test_the_gamma_flip_is_for_spy_qqq_and_spx_only_and_needs_a_crossing():
    expiry = date(2026, 11, 4)
    only_calls = [chain([contract(105, "call", 1000, expiration=expiry)], expiry)]
    assert gamma_flip(only_calls, "SPY", 100.0, NOW).price is None
    assert "does not change sign" in gamma_flip(only_calls, "SPY", 100.0, NOW).note
    assert gamma_flip(only_calls, "NVDA", 100.0, NOW).price is None
    assert "single name" in gamma_flip(only_calls, "NVDA", 100.0, NOW).note


# --- chart levels (C4.4) ---------------------------------------------------


def _ladder():
    return positioning([chain([
        contract(110, "call", 5000, 100), contract(105, "call", 3000, 900), contract(100, "call", 1000, 2000),
        contract(100, "put", 1000, 2500), contract(95, "put", 4000, 300), contract(90, "put", 6000, 50),
        contract(85, "put", 100, 1),
    ])], "SPY", 101.0, NOW)


def test_open_interest_levels_are_the_walls_then_the_top_strikes_each_strike_once():
    levels = option_levels(_ladder(), "oi")
    assert [(level.kind, level.label, level.price) for level in levels] == [
        ("call_wall", "Call wall", 110.0), ("put_wall", "Put wall", 90.0),
        ("options_oi", "OI #3", 95.0), ("options_oi", "OI #4", 105.0), ("options_oi", "OI #5", 100.0), ("options_oi", "OI #6", 85.0)]
    assert {level.evidence for level in levels} == {"calculated"}
    assert not any(level.developing for level in levels)  # open interest holds still through a session


def test_volume_levels_use_volume_walls_and_can_still_move():
    levels = option_levels(_ladder(), "volume")
    # 2,000 calls and 2,500 puts traded at 100: both walls on one strike, which then ranks no further.
    assert [(level.kind, level.label, level.price) for level in levels] == [
        ("call_volume_wall", "Call vol wall", 100.0), ("put_volume_wall", "Put vol wall", 100.0),
        ("options_volume", "Vol #2", 105.0), ("options_volume", "Vol #3", 95.0), ("options_volume", "Vol #4", 110.0),
        ("options_volume", "Vol #5", 90.0), ("options_volume", "Vol #6", 85.0)]
    assert all(level.developing for level in levels)
    zone = next(z for z in chart_levels.confluence(levels, None) if z.low == 100.0)
    assert zone.label == "Call vol wall + Put vol wall"


def test_signed_gamma_levels_and_the_flip_are_labelled_assumed():
    flip = gamma_flip([chain([contract(105, "call", 1000, expiration=date(2026, 11, 4)),
                              contract(95, "put", 1000, expiration=date(2026, 11, 4))], date(2026, 11, 4))], "SPY", 100.0, NOW)
    levels = option_levels(_ladder(), "gamma", signed=True, flip=flip)
    assert levels[-1].kind == "gamma_flip" and levels[-1].evidence == "assumed"
    assert {level.evidence for level in levels if level.kind == "options_gamma"} == {"assumed"}
    assert {level.evidence for level in option_levels(_ladder(), "gamma") if level.kind == "options_gamma"} == {"calculated"}


def test_a_wall_at_the_prior_day_high_merges_into_one_zone():
    pdh = chart_levels.Level("prior_day_high", "PDH", 110.05, "observed", "1D", "tradier", 1, 2)
    zones = chart_levels.confluence([pdh, *option_levels(_ladder(), "oi")], band=0.2)
    top = zones[-1]
    assert top.label == "PDH + Call wall" and (top.low, top.high) == (110.0, 110.05)
    assert top.score == 2


# --- scopes ----------------------------------------------------------------


LISTED = [date(2026, 10, d) for d in (2, 5, 6, 7, 8, 9, 12, 16)] + [date(2026, 11, 20), date(2026, 12, 18)]


def test_scopes_cover_the_nearest_the_week_or_45_days_of_unexpired_expirations():
    assert scope_expirations(LISTED, "nearest", NOW, "SPY") == [TODAY]  # today's: 0DTE
    assert scope_expirations(LISTED, "week", NOW, "SPY") == [date(2026, 10, d) for d in (5, 6, 7, 8, 9)]
    # 45 days from Oct 5 is Nov 19, so Nov 20 is out.
    assert scope_expirations(LISTED, "all", NOW, "SPY") == [date(2026, 10, d) for d in (5, 6, 7, 8, 9, 12, 16)]


def test_after_the_close_todays_expiration_is_gone_and_the_week_rolls_with_the_nearest():
    evening = datetime(2026, 10, 9, 17, 0, tzinfo=ET)  # Friday after the close
    assert scope_expirations(LISTED, "nearest", evening, "SPY") == [date(2026, 10, 12)]
    assert scope_expirations(LISTED, "week", evening, "SPY") == [date(2026, 10, 12), date(2026, 10, 16)]
    with pytest.raises(ValueError):
        scope_expirations(LISTED, "month", NOW, "SPY")


# --- max pain (C4.7) ---------------------------------------------------------


def test_max_pain_is_the_strike_paying_open_contracts_least_worked_by_hand():
    # Calls: 100 at 95, 50 at 100. Puts: 80 at 105, 120 at 100. Size 100 shares each.
    # Settle 95:  calls 0;                         puts 80 x 10 + 120 x 5 = 1,400   -> 140,000
    # Settle 100: calls 100 x 5 = 500;             puts 80 x 5 = 400                 -> 90,000
    # Settle 105: calls 100 x 10 + 50 x 5 = 1,250; puts 0                            -> 125,000
    rows = [contract(95, "call", oi=100), contract(100, "call", oi=50), contract(105, "call", oi=0),
            contract(95, "put", oi=0), contract(100, "put", oi=120), contract(105, "put", oi=80)]
    found = max_pain(chain(rows))
    assert found.price == 100 and found.payout == pytest.approx(90_000) and found.expiration == TODAY


def test_max_pain_keeps_roots_apart_takes_the_lower_strike_on_a_tie_and_needs_open_interest():
    # SPXW only: SPX's AM-settled contracts at the same strikes are left out.
    rows = [contract(5000, "call", oi=10, root="SPXW"), contract(5010, "put", oi=10, root="SPXW"),
            contract(5000, "call", oi=99999, root="SPX"), contract(5010, "call", oi=0, root="SPXW")]
    found = max_pain(chain(rows, underlying="SPX"))
    # Settle 5000: puts 10 x 10 = 100; settle 5010: calls 10 x 10 = 100. Equal, so the lower strike.
    assert found.price == 5000 and found.payout == pytest.approx(100 * 100)
    assert max_pain(chain([contract(100, "call", oi=0), contract(100, "put", oi=None)])) is None


def test_max_pain_draws_as_an_inferred_level_beside_the_walls():
    rows = [contract(95, "call", oi=100), contract(100, "put", oi=120), contract(105, "put", oi=80), contract(100, "call", oi=50)]
    found = positioning([chain(rows)], "SPY", 100.0, NOW)
    levels = option_levels(found, "oi", pain=max_pain(chain(rows)))
    pain = [level for level in levels if level.kind == "max_pain"]
    assert [(level.label, level.price, level.evidence, level.developing) for level in pain] == [("Max pain", 100.0, "inferred", False)]
    assert all(level.kind != "max_pain" for level in option_levels(found, "oi"))
