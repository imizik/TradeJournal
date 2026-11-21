from datetime import date

import numpy as np

from app.engine import radar_rules
from scripts import radar_historical_replay as replay
from scripts import radar_rules_study as study

DAY = date(2025, 3, 4)
UNIVERSE = {"version": "test-u", "groups": [], "symbols": [
    {"symbol": "SPY", "kind": "etf", "benchmark": True, "sector": None},
    {"symbol": "XLK", "kind": "etf", "benchmark": True, "sector": None},
    {"symbol": "UPP", "kind": "stock", "benchmark": False, "sector": "XLK"},
    {"symbol": "DWN", "kind": "stock", "benchmark": False, "sector": "XLK"},
    {"symbol": "FLT", "kind": "stock", "benchmark": False, "sector": "XLK"},
]}


def _path(moves):
    """390 one-minute bars from 100, with {offset: price} breakpoints linearly joined."""
    points = sorted(moves.items())
    out = {}
    for m in range(390):
        price = 100.0
        for (a, pa), (b, pb) in zip(points, points[1:]):
            if a <= m <= b:
                price = pa + (pb - pa) * (m - a) / (b - a)
        if m > points[-1][0]:
            price = points[-1][1]
        out[str(m)] = [price, price]
    return out


def _day():
    bars = {"SPY": _path({0: 100, 389: 100.5}), "XLK": _path({0: 100, 389: 100}),
            "UPP": _path({0: 100, 60: 100, 80: 107, 389: 108}),
            "DWN": _path({0: 100, 150: 100, 165: 94, 389: 93}),
            "FLT": _path({0: 100, 389: 101})}
    previous = {s: 100.0 for s in bars}
    passes, quotes = replay.reconstruct(DAY, UNIVERSE, bars, previous)
    prices = np.full((5, study.MINUTES + 1), np.nan)
    for m, rows in quotes.items():
        for s, q in rows.items():
            prices[[r["symbol"] for r in UNIVERSE["symbols"]].index(s), m] = q["last"]
    return passes, quotes, prices


def test_live_variant_finds_the_same_first_flags_as_the_exact_replay():
    passes, quotes, prices = _day()
    by_stamp = {p["finished_at"]: p["id"] for p in passes}
    exact = {}
    for e, _ in radar_rules.replay(UNIVERSE, passes, quotes, radar_rules.V0):
        if e["kind"] == "relative_to_spy":
            exact.setdefault(e["symbols"][0], (by_stamp[e["first_seen_at"]], 1 if e["direction"] == "up" else -1))
    mine = study.detect(prices, 0, [2, 3, 4], 30, 4.5)
    assert {UNIVERSE["symbols"][r]["symbol"]: v for r, v in mine.items()} == exact
    assert set(exact) == {"UPP", "DWN"} and exact["UPP"][1] == 1 and exact["DWN"][1] == -1


def test_detect_respects_the_time_range_and_a_higher_trigger():
    _, _, prices = _day()
    assert 2 not in study.detect(prices, 0, [2, 3], 30, 4.5, first=100)
    assert 3 in study.detect(prices, 0, [2, 3], 30, 4.5, first=100)
    assert study.detect(prices, 0, [2, 3], 30, 9.0) == {}


def test_ffill_and_relative():
    p = np.array([[np.nan, 10, np.nan, 11], [np.nan, 100, 100, 100]], float)
    f = study.ffill(p)
    assert f[0, 2] == 10 and np.isnan(f[0, 0])
    assert round(study.relative(f, 1, 0, 1, 3), 6) == 10.0


def test_horizons_cap_at_the_close():
    assert study.horizons(10) == (11, 71, 390)
    assert study.horizons(350) == (351, 390, 390)
    assert study.horizons(389) is None


def test_normal_needs_enough_history():
    day = np.array([[100.0, 101.0], [100.0, 100.0]])
    assert study.normal([day] * 9, 1, 0, 0, 1) == 0.0
    assert round(study.normal([day] * 12, 1, 0, 0, 1), 6) == 1.0


def test_summarize_drop_days_and_paired_share():
    days = [f"d{i}" for i in range(10)]
    big = [("d0", 50.0)] + [(d, -1.0) for d in days[1:]]
    s = study.summarize(days, big)
    assert s["episodes"] == 10 and s["mean"] > 0
    assert s["mean_without_top_days"] < 0  # one day carries it
    steady = [(d, 1.0) for d in days]
    assert study.paired_share(days, steady, [(d, 0.0) for d in days]) == 1.0
    assert study.summarize(days, [])["episodes"] == 0


def test_exam_checks():
    good = {"mean": 0.2, "positive_share": 0.55, "draws_above_zero": 0.9, "mean_without_top_days": 0.1,
            "episodes": 300}
    assert study.passes_exam(good, 0.85)["passed"]
    assert not study.passes_exam(good, 0.5)["passed"]
    assert not study.passes_exam({**good, "episodes": 50}, 0.9)["passed"]
    assert study.live_edge(good) and not study.live_edge({**good, "draws_above_zero": 0.6})


def test_grid_is_small_and_named_uniquely():
    names = [v.name for v in study.grid()]
    assert len(names) == len(set(names)) == 26
