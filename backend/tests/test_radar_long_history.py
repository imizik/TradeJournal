"""Radar long-history study on invented bars: the dated roster, the delayed card, one session end to end, the verdicts."""

from datetime import date

import numpy as np
import pytest

from scripts import radar_long_history as s
from scripts import radar_setup_lab as lab

DAY, PRIOR = date(2025, 3, 5), date(2025, 3, 4)


# ------------------------------------------------------------------ roster


def matrices(rows):
    """rows: {symbol: (close, dollar volume)} constant over 21 days."""
    symbols = sorted(rows)
    close = np.array([[rows[x][0]] * 21 for x in symbols], dtype=float)
    dollar = np.array([[rows[x][1]] * 21 for x in symbols], dtype=float)
    return [f"d{i:02d}" for i in range(21)], symbols, close, dollar


def test_roster_ranks_by_prior_dollar_volume_with_the_floors():
    days, symbols, close, dollar = matrices({"BIG": (50, 9e8), "MID": (20, 5e8), "CHEAP": (4, 8e8), "THIN": (30, 1e7),
                                             "TIE": (20, 5e8)})
    assert s.daily_rosters(days, symbols, close, dollar)[days[20]] == ["BIG", "MID", "TIE"]
    assert s.daily_rosters(days, symbols, close, dollar, size=2)[days[20]] == ["BIG", "MID"]


def test_roster_reads_nothing_from_the_session_itself_and_needs_all_twenty_bars():
    days, symbols, close, dollar = matrices({"AAA": (50, 9e8), "BBB": (20, 5e8)})
    before = s.daily_rosters(days, symbols, close, dollar)
    close[:, 20], dollar[:, 20] = 1.0, 1.0            # the session's own bar changes nothing
    assert s.daily_rosters(days, symbols, close, dollar) == before
    dollar[0, 7] = np.nan                             # one missing bar in the 20
    assert s.daily_rosters(days, symbols, close, dollar)[days[20]] == ["BBB"]
    close[1, 19] = 4.99                               # the latest close under $5
    assert s.daily_rosters(days, symbols, close, dollar)[days[20]] == []


# ------------------------------------------------------------------ the delayed card


def closes_path(values):
    out = np.full(390, np.nan)
    out[:len(values)] = values
    return out


def test_no_delay_is_the_setup_labs_card():
    closes = closes_path([100 + 0.05 * i for i in range(120)])
    own, theirs = s.delayed(closes, 10, 1, 99.0, 0), lab.score(closes, 10, 1, 99.0)
    assert own["pct"] == pytest.approx(theirs["pct"]) and own["exit_minute"] == theirs["exit_minute"]
    assert own["r"] == pytest.approx(theirs["r"])


def test_one_minute_delay_enters_the_next_close_and_counts_the_hold_from_there():
    closes = closes_path([100.0] * 9 + [101.0, 102.0] + [102.0 + 0.01 * i for i in range(1, 100)])
    trade = s.delayed(closes, 10, 1, None, 1)          # flagged at minute 10 (101), entered at minute 11 (102)
    assert trade["entry"] == 102.0 and trade["level"] == 100.0
    assert trade["exit_minute"] == 71 and trade["reason"] == "time"
    assert trade["pct"] == pytest.approx((closes[70] / 102.0 - 1) * 100)


def test_no_trade_when_the_next_close_is_through_the_level_or_missing():
    through = closes_path([100.0] * 9 + [101.0, 99.5] + [103.0] * 80)
    assert s.delayed(through, 10, 1, None, 0) is not None and s.delayed(through, 10, 1, None, 1) is None
    gap = closes_path([100.0] * 9 + [101.0])
    gap[10] = np.nan
    assert s.delayed(gap, 10, 1, None, 1) is None


def test_earnings_label():
    assert s.on_earnings(["2025-03-04"], DAY, PRIOR) is True and s.on_earnings(["2025-03-05"], DAY, PRIOR) is True
    assert s.on_earnings(["2025-03-03"], DAY, PRIOR) is False and s.on_earnings(None, DAY, PRIOR) is None


# ------------------------------------------------------------------ one session


def drifting(per_minute=0.002, start=100.0):
    return {i: [start + per_minute * i, start + per_minute * (i + 1), 50_000] for i in range(390)}


def reversing():
    """Gaps down 3%, climbs back from the open and keeps going."""
    rows = {}
    for i in range(390):
        price = 97.0 + 0.3 * min(i + 1, 12) + 0.01 * max(0, i - 11)
        rows[i] = [97.0 if i == 0 else rows[i - 1][1], price, 50_000]
    return rows


def session(extra=None):
    roster = ["GAP"] + [f"S{i:02d}" for i in range(24)]
    minutes = {"SPY": drifting(0.0), "GAP": reversing(), **{x: drifting() for x in roster[1:]}}
    if extra:
        minutes.update(extra)
    previous = {x: 100.0 for x in roster + ["SPY"]}
    return s.session_cards(DAY, PRIOR, roster, minutes, previous, {}, {"GAP": ["2025-03-04"], "S00": ["2025-01-01"]})


def test_a_gap_reversal_is_flagged_carded_and_compared_with_random_stocks():
    rows = [r for r in session() if r["symbol"] == "GAP"]
    assert {r["delay"] for r in rows} == {1, 0} and all(r["setup"] == "reversal" and r["direction"] == "up" for r in rows)
    first = next(r for r in rows if r["delay"] == 1)
    assert first["minute"] == 6 and first["carded"] and first["earnings"] is True   # +1.75% from the open by 09:36
    assert first["entry"] == pytest.approx(97.0 + 0.3 * 7) and first["level"] == 97.0
    assert first["base_n"] == 20 and first["base_pct"] == pytest.approx(0.12, abs=0.01)   # the drifting names: +0.002 a minute
    assert first["pct"] > first["base_pct"]


def test_flags_do_not_change_when_later_bars_do():
    later = reversing()
    for i in range(40, 390):
        later[i] = [50.0, 50.0, 1]
    crashed = [r for r in session({"GAP": later}) if r["symbol"] == "GAP" and r["delay"] == 1][0]
    plain = [r for r in session() if r["symbol"] == "GAP" and r["delay"] == 1][0]
    assert (crashed["minute"], crashed["entry"], crashed["level"]) == (plain["minute"], plain["entry"], plain["level"])
    assert crashed["reason"] == "stop" and crashed["pct"] < 0


def test_the_baseline_is_deterministic():
    assert session() == session()


# ------------------------------------------------------------------ summaries and verdicts


def cards_for(edge_by_session, setup="reversal", direction="up", earnings=False, delay=1):
    return [{"session": d, "setup": setup, "symbol": f"X{i}", "direction": direction, "minute": 10, "delay": delay,
             "carded": True, "earnings": earnings, "pct": e, "r": e, "reason": "time", "base_pct": 0.0, "base_green": 0.5,
             "base_n": 20} for d, values in edge_by_session.items() for i, e in enumerate(values)]


def sessions_in(years=("2024", "2025", "2026"), per_year=20):
    return [f"{y}-03-{d:02d}" for y in years for d in range(1, per_year + 1)]


def test_holds_up_needs_size_every_year_and_the_trimmed_mean():
    days = sessions_in()
    good = s.summarize(cards_for({d: [0.3, 0.5] for d in days}), days)
    assert good["verdicts"]["reversal"] == "holds up" and good["verdicts"]["dip"] == "inconclusive"
    cell = good["cells"]["reversal:delay1"]["all"]
    assert cell["cards"] == 120 and cell["edge_pct"] == pytest.approx(0.4) and cell["sessions_positive"] == 1.0
    small = s.summarize(cards_for({d: [0.03, 0.05] for d in days}), days)
    assert small["verdicts"]["reversal"] == "retire as a trade idea"          # clearly above zero, too small to matter
    one_bad_year = {d: [0.3, 0.5] if not d.startswith("2025") else [-0.01, -0.02] for d in days}
    assert s.summarize(cards_for(one_bad_year), days)["verdicts"]["reversal"] == "inconclusive"
    lucky = {d: [0.0, 0.0] for d in days}
    lucky[days[0]] = [60.0, 0.0]                                              # one card carries the mean
    assert s.summarize(cards_for(lucky), days)["verdicts"]["reversal"] == "inconclusive"


def test_no_edge_is_retired_and_noise_is_inconclusive():
    days = sessions_in()
    flat = s.summarize(cards_for({d: [0.01, -0.01] for d in days}), days)
    assert flat["verdicts"]["reversal"] == "retire as a trade idea"
    noisy = s.summarize(cards_for({d: [(-1) ** i * 3.0 + 0.2] for i, d in enumerate(days)}), days)
    assert noisy["verdicts"]["reversal"] == "inconclusive"


def test_the_zero_delay_cells_never_decide_and_directions_are_split():
    days = sessions_in()
    cards = cards_for({d: [0.4] for d in days}, delay=0) + cards_for({d: [0.4] for d in days}, direction="down")
    out = s.summarize(cards, days)
    assert out["cells"]["reversal:delay0"]["all"]["cards"] == 60 and out["cells"]["reversal_down:delay1"]["all"]["cards"] == 60
    assert out["cells"]["reversal_up:delay1"]["all"]["cards"] == 0 and set(out["verdicts"]) == {"dip", "reversal"}


def test_the_earnings_split_is_without_minus_with_a_report():
    days = sessions_in()
    cards = cards_for({d: [0.5] for d in days}) + cards_for({d: [0.1] for d in days}, earnings=True) + \
        cards_for({d: [9.0] for d in days[:3]}, earnings=None)
    out = s.summarize(cards, days)
    split = out["splits"]["reversal_without_minus_with_report"]
    assert split["difference"] == pytest.approx(0.4) and split["low"] == pytest.approx(0.4) and split["with_report"] == 60
    assert out["cells"]["reversal:delay1"]["earnings"]["unknown"]["cards"] == 3
    assert s.summarize(cards_for({d: [0.5] for d in days}), days)["splits"]["reversal_without_minus_with_report"] is None
