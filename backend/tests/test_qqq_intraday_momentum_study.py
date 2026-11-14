"""The QQQ intraday momentum study's rules, on hand-built minute bars (no network, no database)."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from scripts import opening_breakout_study as v1
from scripts import qqq_intraday_momentum_study as q


def flat_bars(price: float = 100.0, path: dict[int, float] | None = None, volume: float = 1000.0) -> dict[int, list]:
    """Bars at ``price`` from 09:30 to 15:59; ``path`` sets a bar's close (and the next bar's open) from a minute on."""
    bars, p = {}, price
    for m in range(q.OPEN_MINUTE, q.LAST_MINUTE + 1):
        o = p
        if path and m in path:
            p = path[m]
        bars[m] = [o, max(o, p), min(o, p), p, volume]
    return bars


def day(d: str, bars: dict[int, list], prev_close: float | None = 100.0) -> q.Day:
    return q.Day(d, bars, bars[q.OPEN_MINUTE][0], prev_close, bars[max(bars)][3])


SIGMA = {m: 0.005 for m in q.check_minutes(15)}  # bands at 99.5 / 100.5 around 100


def test_goes_long_above_the_band_at_the_check_and_fills_at_that_minute_open():
    bars = flat_bars(path={10 * 60 + 10: 101.0})  # through the upper band at 10:10, flat after
    t = q.trade_day(day("2024-03-05", bars), SIGMA, {}, 1.0, 30, "band", 0.0)
    # Checked at 10:30 (not 10:15, every 30): long at 101, out at the close 101: nothing made, one trade to the close.
    assert t["trades"] == [{"side": 1, "how": "close"}] and t["r"] == pytest.approx(0.0)


def test_band_stop_then_reversal_at_the_opposite_band():
    bars = flat_bars(path={10 * 60 + 10: 101.0, 11 * 60 + 10: 100.2, 12 * 60 + 10: 99.0})
    t = q.trade_day(day("2024-03-05", bars), SIGMA, {}, 1.0, 30, "band", 0.0)
    # Long at 10:30 (101), stopped at 11:30 inside the band (100.2), short at 12:30 (99), out at the close (99).
    assert [x["how"] for x in t["trades"]] == ["stop", "close"]
    assert [x["side"] for x in t["trades"]] == [1, -1]
    assert t["r"] == pytest.approx((100.2 - 101.0) / 100.0)
    # The opposite-band stop holds through 100.2 and reverses only below 99.5.
    t = q.trade_day(day("2024-03-05", bars), SIGMA, {}, 1.0, 30, "opposite", 0.0)
    assert [x["side"] for x in t["trades"]] == [1, -1]
    assert t["r"] == pytest.approx((99.0 - 101.0) / 100.0)


def test_vwap_stop_is_the_tighter_of_band_and_vwap():
    bars = flat_bars(path={10 * 60 + 10: 102.0, 11 * 60 + 10: 101.0})
    vwap = {m: 101.5 for m in q.check_minutes(15)}
    t = q.trade_day(day("2024-03-05", bars), SIGMA, vwap, 1.0, 30, "band_vwap", 0.0)
    assert t["trades"][0]["how"] == "stop"  # 101 is above the band (100.5) but below VWAP (101.5)
    t = q.trade_day(day("2024-03-05", bars), SIGMA, vwap, 1.0, 30, "band", 0.0)
    assert t["trades"][0]["how"] == "close"


def test_costs_a_cent_a_side_and_the_gap_widens_the_band():
    bars = flat_bars(path={10 * 60 + 10: 101.0})
    t = q.trade_day(day("2024-03-05", bars), SIGMA, {}, 1.0, 30, "band", 0.01)
    assert t["r"] == pytest.approx(-0.02 / 100.0)
    # After a gap down from 102 the upper band is 102 x 1.005 = 102.51: 101 is inside, no trade.
    t = q.trade_day(day("2024-03-05", bars, prev_close=102.0), SIGMA, {}, 1.0, 30, "band", 0.01)
    assert t["trades"] == [] and t["r"] == 0
    assert q.trade_day(day("2024-11-29", bars), SIGMA, {}, 1.0, 30, "band", 0.0) is None  # early close


def test_sigma_is_the_average_absolute_move_over_the_previous_sessions():
    start = date(2024, 3, 4)
    days = []
    for k, move in enumerate([0.01, -0.03, 0.02]):
        bars = flat_bars(path={q.OPEN_MINUTE + 1: 100.0 * (1 + move)})
        days.append(day((start + timedelta(days=k)).isoformat(), bars))
    days.append(day((start + timedelta(days=3)).isoformat(), flat_bars()))
    sig = q.sigmas(days, 3)
    assert list(sig) == [days[3].day]
    assert sig[days[3].day][10 * 60] == pytest.approx(0.02)


def test_vwap_uses_bars_before_the_check():
    bars = flat_bars()
    for m in range(q.OPEN_MINUTE, 10 * 60):
        bars[m] = [100.0, 100.0, 100.0, 100.0, 1.0]
    bars[9 * 60 + 59] = [106.0, 106.0, 106.0, 106.0, 1.0]
    bars[10 * 60] = [500.0, 500.0, 500.0, 500.0, 1000.0]  # the check minute's own bar is not in its VWAP
    v = q.vwaps(day("2024-03-05", bars))
    assert v[10 * 60] == pytest.approx((100.0 * 29 + 106.0) / 30)


def test_decide_and_sizing():
    ok = {"first": 1.0, "second": 0.5}
    assert q.decide([0.1, 3.0], ok, 0.4) == "worth a paper test"
    assert q.decide([0.1, 3.0], {**ok, "second": -0.1}, 0.4) == "no evidence either way"
    assert q.decide([0.1, 3.0], ok, -0.1) == "no evidence either way"
    assert q.decide([-3.0, -0.1], ok, 0.4) == "loses money"
    rows = [{"day": "a", "r": 0.001, "trades": []}, {"day": "b", "r": 0.001, "trades": []}]
    sized = q.sized(rows, {"a": 0.01, "b": 0.001})
    assert [r["r"] for r in sized] == pytest.approx([0.002, 0.004])  # 2x, then capped at 4x


def test_run_searches_then_examines_the_winner_only(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(q, "GRID", {"lookback": (3,), "vm": (1.0, 2.0), "every": (30,), "stop": ("band",)})
    monkeypatch.setattr(q, "WARMUP", 3)
    monkeypatch.setattr(q, "SEARCH", ("2021-12-01", "2021-12-31"))
    monkeypatch.setattr(q, "EXAM", ("2022-01-03", "2022-01-31"))
    monkeypatch.setattr(q, "EXAM_PERIODS", (("first", "2022-01-03", "2022-01-14"), ("second", "2022-01-15", "2022-01-31")))
    monkeypatch.setattr(q, "PAPER", {"lookback": 3, "vm": 1.0, "every": 30, "stop": "band"})
    rows, d, k = {}, date(2021, 12, 1), 0
    while d <= date(2022, 1, 31):
        if d.weekday() < 5:
            trend = 1 + (0.004 if k % 2 else 0.012)  # alternating quiet and trending mornings that hold to the close
            bars = flat_bars(path={10 * 60 + 10: 100.0 * trend})
            rows[d.isoformat()] = [[m, *v] for m, v in sorted(bars.items())]
            k += 1
        d += timedelta(days=1)
    v1.save(tmp_path / "bars.json.gz", rows)
    results = q.run(tmp_path / "bars.json.gz", tmp_path / "out.json")
    assert results["protocol_id"] == q.PROTOCOL_ID
    assert results["search"]["combinations"] == 2
    assert results["exam"]["settings"] == results["search"]["chosen"]
    assert results["exam"]["days"] > 0 and results["exam"]["decision"] in ("worth a paper test", "no evidence either way", "loses money")
    assert json.loads((tmp_path / "out.json").read_text()) == results


def test_protocol_matches_the_script():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "qqq-intraday-momentum" / "protocol.json").read_text())
    assert protocol["protocol_id"] == q.PROTOCOL_ID
    text = json.dumps(protocol)
    for value in (*q.SEARCH, *q.EXAM, "seed 20261114", "95%", "180"):
        assert value in text
    for name, values in q.GRID.items():
        assert all(str(v) in protocol["search"]["grid"][name] for v in values)


def test_band_vwap_never_closes_and_reopens_the_same_side_at_one_check():
    # Above the upper band but below VWAP all day: no long opens (it would already be past its stop), so no churn.
    bars = flat_bars(path={10 * 60 + 10: 102.0})
    vwap = {m: 103.0 for m in q.check_minutes(15)}
    t = q.trade_day(day("2024-03-05", bars), SIGMA, vwap, 1.0, 30, "band_vwap", 0.01)
    assert t["trades"] == [] and t["r"] == 0
    # Held long, then VWAP rises above the price: one stop, no same-side re-entry at that check or later.
    vwap = {m: (101.0 if m < 12 * 60 else 103.0) for m in q.check_minutes(15)}
    t = q.trade_day(day("2024-03-05", bars), SIGMA, vwap, 1.0, 30, "band_vwap", 0.01)
    assert [(x["side"], x["how"]) for x in t["trades"]] == [(1, "stop")]
    assert t["r"] == pytest.approx(-0.02 / 100.0)
