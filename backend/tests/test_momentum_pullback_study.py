"""The momentum pullback study's rules, on hand-built bars (no network, no database)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import momentum_pullback_study as m


def _days(n: int, start: date = date(2016, 1, 4)) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(closes: list[float], days: list[str] | None = None, volume: float = 1_000_000.0, ratio: float = 1.0,
          lows: list[float] | None = None, vols: list[float] | None = None, opens: list[float] | None = None) -> dict:
    days = days or _days(len(closes))
    return {"d": days, "o": opens or list(closes), "h": [c * 1.01 for c in closes], "l": lows or [c * 0.99 for c in closes],
            "c": list(closes), "v": vols or [volume] * len(closes), "rc": [c * ratio for c in closes]}


def _signal_series(n: int = 160, base: float = 50.0) -> tuple[list[float], list[float], list[float]]:
    """A steady climb, then three quiet lower closes whose last low reaches the 20-day average."""
    closes = [base * (1.004 ** k) for k in range(n - 3)]
    top = closes[-1]
    closes += [top * 0.99, top * 0.98, top * 0.97]
    vols = [1_000_000.0] * (n - 3) + [500_000.0] * 3
    lows = [c * 0.99 for c in closes]
    lows[-1] = min(lows[-1], m.ema(closes)[-1] - 0.01)
    return closes, lows, vols


def test_ema_starts_from_the_simple_average():
    values = [float(x) for x in range(1, 25)]
    out = m.ema(values, 20)
    assert out[18] is None and out[19] == pytest.approx(10.5)
    k = 2 / 21
    assert out[20] == pytest.approx(21 * k + 10.5 * (1 - k))


def test_features_find_the_quiet_pullback_and_require_the_filters():
    closes, lows, vols = _signal_series()
    bars = _bars(closes, lows=lows, vols=vols)
    index = {d: i for i, d in enumerate(bars["d"])}
    rows = m.features(bars, index, "2000-01-01", "2100-01-01")
    last = rows[-1]
    assert last[0] == bars["d"][-1] and last[3] is True
    assert last[1] == pytest.approx(closes[-1 - m.SKIP] / closes[-1 - m.HISTORY] - 1)
    assert last[4] == pytest.approx(min(lows[-3:]))
    assert not any(r[3] for r in rows[:-1])
    # Loud volume on the pullback: no signal.
    loud = _bars(closes, lows=lows, vols=vols[:-3] + [2_000_000.0] * 3)
    assert m.features(loud, index, "2000-01-01", "2100-01-01")[-1][3] is False
    # Under $10 unadjusted, or under $20M a day: out of the universe.
    assert m.features(_bars(closes, lows=lows, vols=vols, ratio=0.1), index, "2000", "2100") == []
    thin = _bars(closes, lows=lows, vols=[1000.0] * len(closes))
    assert m.features(thin, index, "2000", "2100") == []


def test_a_missing_calendar_session_in_the_window_drops_the_day():
    closes, lows, vols = _signal_series()
    bars = _bars(closes, lows=lows, vols=vols)
    calendar = list(bars["d"])
    index = {d: i for i, d in enumerate(calendar[:50] + ["1999-01-01"] + calendar[50:])}
    rows = m.features(bars, index, "2000", "2100")
    assert all(r[0] > calendar[50 + m.HISTORY - 1] for r in rows)


def test_leaders_take_the_top_fifth_above_qqq_and_in_an_uptrend():
    rows = [(f"S{k:02d}", k / 100, True, False, 1.0) for k in range(20)]
    rows[19] = ("S19", 0.19, False, True, 1.0)  # best momentum but below its 50-day average
    got = [r[0] for r in m.leaders(rows, benchmark=0.165)]
    assert got == ["S18", "S17"]  # top 4 of 20 = S19..S16; S19 not in uptrend, S16 below QQQ
    assert m.leaders(rows, None) == []


def test_simulate_exits_stop_no_progress_time_and_end_of_data():
    base = [100.0] * 5
    # Stop: the second session closes below the pullback low; out at the next open.
    bars = _bars(base + [100, 101, 94, 99, 99], opens=base + [100, 100.5, 98, 96, 99])
    t = m.simulate(bars, 4, low=95.0)
    assert (t["how"], t["entry_day"], t["exit_day"], t["hold"]) == ("stop", bars["d"][5], bars["d"][8], 3)
    assert t["gross"] == pytest.approx(96 / 100 - 1)
    # No progress: third session's close at or below the entry price.
    bars = _bars(base + [100, 101, 100, 102, 103], opens=base + [100, 100, 100, 101, 103])
    t = m.simulate(bars, 4, low=90.0)
    assert (t["how"], t["exit_day"]) == ("no progress", bars["d"][8])
    # Time: out at the open after the tenth session.
    up = [100 + k for k in range(14)]
    bars = _bars(base + up)
    t = m.simulate(bars, 4, low=90.0)
    assert (t["how"], t["hold"]) == ("time", 10) and t["exit_day"] == bars["d"][15]
    # End of data: the last close, counted.
    bars = _bars(base + [100, 101, 102])
    t = m.simulate(bars, 4, low=90.0)
    assert (t["how"], t["at_close"], t["exit_day"]) == ("end of data", True, bars["d"][-1])
    assert m.simulate(bars, len(bars["d"]) - 1, low=90.0) is None


def test_costs_use_basis_points_and_a_cent_on_the_unadjusted_price():
    assert m.cost(20.0, 1.0) == pytest.approx(0.0005 + 0.01 / 20)
    assert m.cost(10.0, 2.0) == pytest.approx(0.0005 + 0.01 / 20)  # adjusted $10 was $20 before a 2:1 split
    bars = _bars([100.0] * 5 + [100.0] * 11)
    t = m.simulate(bars, 4, low=90.0)
    c = 0.0005 + 0.0001
    assert t["net"] == pytest.approx((1 - c) / (1 + c) - 1)
    assert t["net_doubled"] == pytest.approx((1 - 2 * c) / (1 + 2 * c) - 1)


def test_control_enters_with_the_trade_and_leaves_on_its_exit_session():
    days = _days(12)
    bars = _bars([50.0 + k for k in range(12)], days=days, opens=[49.0 + k for k in range(12)])
    got = m.control(bars, days[2], days[6], at_close=False)
    entry, out = bars["o"][2], bars["o"][6]
    expect = out * (1 - m.cost(out, 1.0)) / (entry * (1 + m.cost(entry, 1.0))) - 1
    assert got == pytest.approx(expect)
    # Missing the exit session: the last close before it.
    gap = {k: v[:5] + v[7:] for k, v in bars.items()}
    got = m.control(gap, days[2], days[6], at_close=False)
    assert got == pytest.approx(bars["c"][4] * (1 - m.cost(bars["c"][4], 1.0)) / (entry * (1 + m.cost(entry, 1.0))) - 1)
    assert m.control(bars, "1999-01-01", days[6], False) is None


def test_decisions():
    ok = {"first": 0.1, "second": 0.2, "third": 0.05}
    assert m.decide_market([0.001, 0.01], ok, 0.002) == "worth a paper test"
    assert m.decide_market([0.001, 0.01], {**ok, "third": -0.01}, 0.002) == "no evidence either way"
    assert m.decide_market([0.001, 0.01], ok, -0.001) == "no evidence either way"
    assert m.decide_market([-0.02, -0.001], ok, 0.1) == "loses to the market"
    assert m.decide_market(None, ok, 0.1) == "no evidence either way"
    assert m.decide_pullback([0.001, 0.02]) == "the pullback adds"
    assert m.decide_pullback([-0.02, -0.001]) == "the pullback hurts"
    assert m.decide_pullback([-0.01, 0.01]) == "no evidence either way"


def test_run_over_saved_bars(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(m, "SIGNAL_START", date(2000, 1, 1))
    monkeypatch.setattr(m, "SIGNAL_END", date(2100, 1, 1))
    closes, lows, vols = _signal_series()
    n = len(closes) + 12
    days = _days(n)
    tail = [closes[-1] * (1.01 ** k) for k in range(1, 13)]
    lead = _bars(closes + tail, days=days, lows=lows + [c * 0.99 for c in tail], vols=vols + [1_000_000.0] * 12)
    flat = [40.0 * (1.005 ** k) for k in range(n)]
    other = _bars(flat, days=days)  # a leader without a pullback: the control
    laggards = {f"L{k}": _bars([30.0] * n, days=days) for k in range(8)}
    m.save(tmp_path / "daily" / "chunk-000.json.gz", {"LEAD": lead, "OTHR": other, **laggards})
    etf = {"SPY": _bars([200.0] * n, days=days), "QQQ": _bars([300.0] * n, days=days)}
    m.save(tmp_path / "daily" / "etf.json.gz", etf)
    out = tmp_path / "results.json"
    results = m.run(tmp_path, out)
    assert results["protocol_id"] == m.PROTOCOL_ID
    assert results["beats_market"]["trades"] == 1
    assert results["pullback_adds"]["trades"] == 1
    assert results["descriptive"]["exits"]["time"] == 1
    assert json.loads(out.read_text()) == results


def test_protocol_matches_the_script():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "momentum-pullback" / "protocol.json").read_text())
    assert protocol["protocol_id"] == m.PROTOCOL_ID
    assert "2016-07-01" in protocol["sessions"] and "2026-10-28" in protocol["sessions"]
    assert "seed 20261113" in protocol["tests"]["uncertainty"] and "97.5%" in protocol["tests"]["uncertainty"]
    assert "$10" in protocol["universe"] and "$20 million" in protocol["universe"]
    assert "5 basis points plus one cent" in protocol["rules"]["costs"]
