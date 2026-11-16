"""The four-family strategy search's rules, on hand-built bars (no network, no database)."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from scripts import opening_breakout_study as v1
from scripts import qqq_intraday_momentum_study as im
from scripts import strategy_search_study as s


def weekdays(start: str, n: int) -> list[str]:
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def test_rsi_and_sma():
    assert s.rsi([1, 2, 3, 4], 2)[2:] == [100.0, 100.0]
    down = s.rsi([10, 9, 8, 7], 2)
    assert down[2] == pytest.approx(0.0)
    assert s.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_dip_buy_enters_on_the_oversold_close_and_exits_on_the_bounce():
    closes = [100, 99, 98, 97, 99, 101, 102]
    rows = [[d, c, c, c, c, 1] for d, c in zip(weekdays("2020-03-02", len(closes)), closes)]
    combo = {"rsi": 2, "below": 10, "trend": 0, "exit_sma": 3, "max_days": 10}
    out = s.dip_sleeve(rows, combo, 0.001)
    days = [r[0] for r in rows]
    # RSI(2) is 0 after two down closes (day 2): buy at 98 for a cost; day 3 holds (97); day 4's 99 is above the
    # 3-day average (98): sold at the close for its return less the cost.
    assert out[days[1]] == 0 and out[days[2]] == pytest.approx(-0.001)
    assert out[days[3]] == pytest.approx(97 / 98 - 1)
    assert out[days[4]] == pytest.approx(99 / 97 - 1 - 0.001)
    assert out[days[5]] == 0  # flat again


def test_trend_switch_daily_and_weekly_checks():
    closes = [10, 10, 10, 12, 12, 9, 9, 9]
    rows = [[d, c, c, c, c, 1] for d, c in zip(weekdays("2020-01-06", len(closes)), closes)]  # Monday Jan 6
    combo = {"sma": 2, "buffer": 0.0, "check": "daily"}
    strat, hold = s.switch_series(rows, combo, 0.0)
    days = [r[0] for r in rows]
    assert strat[days[3]] == 0  # goes long at this close (12 > 11)
    assert strat[days[4]] == pytest.approx(0.0)  # 12 -> 12
    assert strat[days[5]] == pytest.approx(9 / 12 - 1)  # held into the drop, exits at that close
    assert strat[days[6]] == 0 and hold[days[6]] == pytest.approx(0.0)
    weekly, _ = s.switch_series(rows, {**combo, "check": "weekly"}, 0.0)
    # Weekly: decides only on Friday Jan 10 (index 4), where the close (12) is not above its 2-day average (12): flat.
    assert all(weekly[d] == 0 for d in days[1:6])


def test_gap_fade_and_follow():
    bars = {m: [100.0, 100.0, 100.0, 100.0, 1000.0] for m in range(im.OPEN_MINUTE, im.LAST_MINUTE + 1)}
    for m in range(600, im.LAST_MINUTE + 1):
        bars[m] = [99.0, 99.0, 99.0, 99.0, 1000.0]
    day = im.Day("2020-03-10", bars, 100.0, 98.0, 99.0)  # opened +2.04% over a 98 close, slid to 99
    atr = {"2020-03-10": 0.01}
    fade = s.gap_sleeve([day], atr, {"gap_atr": 1.0, "direction": "fade", "entry": 571, "exit": im.LAST_MINUTE}, 0.0,
                        "2020-01-01", "2020-12-31")
    assert fade["2020-03-10"] == pytest.approx((100.0 - 99.0) / 100.0)
    follow = s.gap_sleeve([day], atr, {"gap_atr": 1.0, "direction": "follow", "entry": 571, "exit": 660}, 0.01,
                          "2020-01-01", "2020-12-31")
    assert follow["2020-03-10"] == pytest.approx((99.0 - 100.0 - 0.02) / 100.0)
    small = s.gap_sleeve([day], {"2020-03-10": 0.05}, {"gap_atr": 1.0, "direction": "fade", "entry": 571, "exit": 959},
                         0.0, "2020-01-01", "2020-12-31")
    assert small["2020-03-10"] == 0  # a gap under one range: no trade, a 0 day


def test_book_decide_and_interval():
    assert s.book({"A": {"d1": 0.01, "d2": 0.0}, "B": {"d1": -0.01}}) == {"d1": 0.0, "d2": 0.0}
    ok = {"first": 1.0, "second": 0.5}
    assert s.decide([0.1, 2.0], ok, 0.3) == "worth a paper test"
    assert s.decide([0.1, 2.0], {**ok, "second": -1}, 0.3) == "no evidence either way"
    assert s.decide([-2.0, -0.1], ok, 0.3) == "loses money"
    days = weekdays("2022-01-03", 60)
    xs = [0.001] * 60
    band = s.interval(lambda idx: sum(xs[i] for i in idx) / len(idx) * 1e4, days, __import__("random").Random(1))
    assert band == [pytest.approx(10.0), pytest.approx(10.0)]


def test_run_on_tiny_data(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(s, "SEARCH", ("2021-06-01", "2021-12-31"))
    monkeypatch.setattr(s, "EXAM", ("2022-01-03", "2022-03-31"))
    monkeypatch.setattr(s, "EXAM_PERIODS", (("first", "2022-01-03", "2022-02-15"), ("second", "2022-02-16", "2022-03-31")))
    monkeypatch.setattr(s, "BOOTSTRAP", 50)
    monkeypatch.setattr(im, "GRID", {"lookback": (14,), "vm": (1.0,), "every": (60,), "stop": ("band",)})
    monkeypatch.setattr(im, "WARMUP", 14)
    monkeypatch.setattr(im, "PAPER", {"lookback": 14, "vm": 1.0, "every": 60, "stop": "band"})
    monkeypatch.setattr(s, "GRIDS", {**s.GRIDS, "etf_momentum": im.GRID,
                                     "dip_buy": {"rsi": (2,), "below": (10,), "trend": (0,), "exit_sma": (3,), "max_days": (5,)},
                                     "trend_switch": {"sma": (20,), "buffer": (0.0,), "check": ("daily",)},
                                     "gap": {"gap_atr": (0.5,), "direction": ("fade",), "entry": (571,), "exit": (959,)}})
    monkeypatch.setattr(s.data, "INTRADAY", ("AAA",))
    days = weekdays("2021-03-01", 280)
    import random
    rng = random.Random(7)
    price, daily, minutes = 100.0, [], {}
    for d in days:
        o = price * (1 + rng.uniform(-0.01, 0.01))
        p, rows = o, []
        for m in range(im.OPEN_MINUTE, im.LAST_MINUTE + 1):
            q = p * (1 + rng.uniform(-0.0008, 0.0008))
            rows.append([m, p, max(p, q), min(p, q), q, 1000.0])
            p = q
        minutes[d] = rows
        daily.append([d, o, max(o, p), min(o, p), p, 1e6])
        price = p
    v1.save(tmp_path / "daily.json.gz", {"QQQ": daily, "AAA": daily})
    (tmp_path / "minutes").mkdir()
    v1.save(tmp_path / "minutes" / "AAA.json.gz", minutes)
    results = s.run(tmp_path, tmp_path / "out.json")
    assert results["protocol_id"] == s.PROTOCOL_ID
    for family in ("etf_momentum", "dip_buy", "trend_switch", "gap"):
        r = results["families"][family]
        assert r["search"]["combinations"] == 1 and r["exam"]["settings"] == r["search"]["chosen"]
        assert r["exam"]["decision"] in ("worth a paper test", "no evidence either way", "loses money")
    assert json.loads((tmp_path / "out.json").read_text()) == results


def test_protocol_matches_the_script():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "strategy-search" / "protocol.json").read_text())
    assert protocol["protocol_id"] == s.PROTOCOL_ID
    text = json.dumps(protocol)
    for value in (*s.SEARCH, *s.EXAM, "seed 20261115", "99%", "456"):
        assert value in text
    for family, grid in s.GRIDS.items():
        if family == "etf_momentum":
            continue
        for name, values in grid.items():
            assert all(str(v) in protocol["families"][family]["grid"] for v in values), (family, name)


def test_ties_go_to_the_setting_earlier_in_the_grid_and_the_book_has_a_fixed_denominator():
    grid = {"x": (2, 1), "stop": ("band_vwap", "band")}
    table = [{"x": 1, "stop": "band", "sharpe": 1.0}, {"x": 2, "stop": "band", "sharpe": 1.0},
             {"x": 2, "stop": "band_vwap", "sharpe": 1.0}, {"x": 1, "stop": "band_vwap", "sharpe": 0.5}]
    assert s.choose(table, grid)[0] == {"x": 2, "stop": "band_vwap", "sharpe": 1.0}
    assert s.book({"A": {"d1": 0.01}, "B": {}}) == {"d1": 0.005}  # a sleeve missing the day counts as 0
