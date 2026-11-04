"""Direction, point-in-time volume and breadth, and registered ranking on invented data."""
import numpy as np

from scripts import radar_v2_search as search
from scripts.radar_historical_replay import Flag


def test_surge_precedes_break_and_requires_twenty_observations():
    symbols = ["SPY", "A"]
    universe = {"symbols": [{"symbol": s, "kind": "etf" if s == "SPY" else "stock",
                             "benchmark": s == "SPY"} for s in symbols], "groups": []}
    px = np.full((390, 2), 100.)
    vol = np.full_like(px, 100.)
    past = [vol.copy() for _ in range(20)]
    px[5:, 1] = 101
    vol[5, 1] = 500  # surge simultaneous with break is too late

    def flags():
        return search.candidates(universe, symbols, px, px[0], px[0], vol, past, {"C02": "surge"})["C02"]

    assert flags() == []
    vol[4, 1] = 300
    assert flags() == [Flag(6, "C02", "up", ("A",))]
    past[0][4, 1] = np.nan
    assert flags() == []


def test_breadth_excludes_subject_and_requires_four_other_observations():
    symbols = ["SPY", "A", "B", "C", "D", "E"]
    universe = {"symbols": [{"symbol": s, "kind": "stock", "benchmark": s == "SPY"} for s in symbols],
                "groups": [{"members": symbols[1:]}]}
    px = np.full((390, len(symbols)), 100.)
    opening = px[0].copy()
    px[15:, 1:5] = [102, 100.6, 100.6, 100.6]

    def flags():
        return search.candidates(universe, symbols, px, opening, opening, px, [px] * 20, {"C04": "group"})["C04"]

    assert flags() == [Flag(16, "C04", "up", ("A",))]
    px[:, 5] = np.nan
    assert flags() == []


def test_scoring_counts_repeats_once_for_recall_and_excludes_group_members():
    stock = Flag(1, "x", "down", ("A",))
    group = Flag(1, "g", "down", ("A", "B"), "g")
    late = Flag(389, "x", "down", ("A",))
    prices = {1: {"A": 100, "B": 100, "SPY": 100}, 61: {"A": 96, "B": 98, "SPY": 100},
              389: {"A": 100, "SPY": 100}}
    labels = {"cc": {("A", "down")}, "oc": {("A", "up")}}
    row = search.score([late, group, stock], labels, {("A", "down"): 4}, prices)
    assert row["cc"] == {"hits": 1, "leads": [3], "precision_n": 3}
    assert row["oc"] == {"hits": 0, "leads": [], "precision_n": 2}
    assert row["horizons"] == [[0, 0, 0], [2, 2, 7], [0, 0, 0]]
    assert row["flags"] == 3


def test_shortlist_ranks_by_weaker_label_then_mean_then_id():
    def f1(cc, oc):
        return {"cc": {"f1": cc}, "oc": {"f1": oc}}
    assert search.ranking({"C01": f1(.3, .9), "C03": f1(.4, .6), "C02": f1(.4, .6),
                           "C04": f1(.4, .7), "Movers": f1(1, 1)}) == ["C04", "C02", "C03", "C01"]


def test_missing_previous_close_only_disables_dependent_clauses_and_label():
    symbols = ["SPY"] + [f"S{i:02}" for i in range(21)]
    new = symbols[-1]
    universe = {"symbols": [{"symbol": s, "kind": "stock", "benchmark": s == "SPY"} for s in symbols],
                "groups": []}
    bars = {s: {"0": [100, 100], "5": [100, 104 if s == new else 100]} for s in symbols}
    last, opening, prices = search.candidate_prices(bars, symbols)
    prev = np.full(len(symbols), 100.)
    prev[-1] = np.nan
    flags = search.candidates(universe, symbols, last, opening, prev, last, [last] * 20,
                              {"C06": "drive", "C07": "day"})
    assert flags["C06"] == [Flag(6, "C06", "up", (new,))]
    assert flags["C07"] == []
    assert prices[6][new] == 104
    daily = {"raw": {s: {"today": {"o": 100, "c": prices[6][s]}} for s in symbols}}
    closing = search.raw_daily_prices(daily, "today", "c")
    cc = search.targets(symbols[1:], dict.fromkeys(symbols[:-1], 100), closing)
    oc = search.targets(symbols[1:], search.raw_daily_prices(daily, "today", "o"), closing)
    assert (new, "up") in oc and (new, "up") not in cc
