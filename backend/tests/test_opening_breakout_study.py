"""Opening breakout study on invented bars, with hand-calculated selections, fills and R."""

import json
from pathlib import Path

import pytest

from scripts import opening_breakout_study as s


def daily(n=16, close=20.0, rng=1.0, volume=2_000_000):
    """n days of bars: each high/low ``rng`` around ``close``, so every true range is ``rng``."""
    return [[f"2026-05-{i + 1:02d}", close, close + rng / 2, close - rng / 2, close, volume] for i in range(n)]


def ratios(rows, value=1.0):
    return {r[0]: value for r in rows}


def test_a_candidate_needs_price_volume_range_and_no_split():
    rows = daily()
    got = s.candidate(rows, ratios(rows), 15)
    assert got == {"atr": pytest.approx(1.0), "close": 20.0}
    assert s.candidate(rows, ratios(rows), 13) is None  # not enough history
    assert s.candidate(daily(close=4.0), ratios(rows), 15) is None
    assert s.candidate(daily(volume=900_000), ratios(rows), 15) is None
    assert s.candidate(daily(rng=0.4), ratios(rows), 15) is None
    split = ratios(rows)
    split[rows[10][0]] = 2.0
    assert s.candidate(rows, split, 15) is None


def bars(spec):
    """{minute: [o, h, l, c, v]} from (minute, o, h, l, c) with volume 100."""
    return {m: [o, h, low, c, 100] for m, o, h, low, c in spec}


def test_the_opening_range_and_its_direction():
    up = bars([(570, 10, 10.5, 9.8, 10.2), (571, 10.2, 10.6, 10.1, 10.5), (572, 10.5, 10.7, 10.4, 10.6)])
    assert s.opening_range(up) == {"high": 10.7, "low": 9.8, "side": 1, "volume": 300}
    down = bars([(570, 10, 10.1, 9.5, 9.6), (571, 9.6, 9.7, 9.4, 9.5), (572, 9.5, 9.6, 9.3, 9.4), (575, 1, 99, 0.1, 1)])
    assert s.opening_range(down)["side"] == -1 and s.opening_range(down)["high"] == 10.1  # 09:35 is outside
    assert s.opening_range(bars([(570, 10, 10, 10, 10), (571, 10, 10, 10, 10), (572, 10, 10, 10, 10)]))["side"] == 0
    assert s.opening_range(bars([(570, 10, 11, 9, 10.5), (571, 10.5, 11, 10, 10.6)])) is None


def test_relative_volume_and_the_stocks_in_play():
    assert s.relative_volume(300, [100] * 9) is None
    assert s.relative_volume(300, [100] * 10) == 3.0
    rows = [{"symbol": f"S{i:02d}", "side": 1, "rvol": 1.0 + i} for i in range(25)]
    rows += [{"symbol": "FLAT", "side": 0, "rvol": 99}, {"symbol": "QUIET", "side": 1, "rvol": 0.9},
             {"symbol": "NEW", "side": 1, "rvol": None}]
    chosen = s.in_play(rows)
    assert len(chosen) == 20 and chosen[0]["symbol"] == "S24" and chosen[-1]["symbol"] == "S05"


PICK = {"symbol": "AAA", "side": 1, "rank": 1, "high": 10.0, "low": 9.5, "atr": 2.0}  # risk 0.20


def r(gross, fill, out):
    return (gross - s.cost(fill) - s.cost(out)) / 0.2


def test_a_long_fills_at_the_high_and_exits_at_the_close():
    t = s.trade(PICK, bars([(575, 9.9, 9.95, 9.8, 9.9), (576, 9.95, 10.1, 9.9, 10.05), (959, 10.4, 10.5, 10.3, 10.4)]))
    assert t["fill"] == 10.0 and t["exit"] == 10.4 and t["how"] == "close" and t["entered"] == 576
    assert t["r"] == pytest.approx(r(0.4, 10.0, 10.4)) and t["gross_r"] == pytest.approx(2.0)


def test_a_gap_through_the_level_fills_at_the_open_and_a_gap_through_the_stop_too():
    t = s.trade(PICK, bars([(575, 10.3, 10.4, 10.25, 10.35), (577, 9.9, 9.95, 9.8, 9.85), (959, 11, 11, 11, 11)]))
    # fill 10.30 (the open), stop 10.10, next bar opens 9.90 below it: out at 9.90.
    assert t["fill"] == 10.3 and t["exit"] == 9.9 and t["how"] == "stop"
    assert t["r"] == pytest.approx(r(-0.4, 10.3, 9.9))


def test_the_fill_bar_counts_a_stop_only_on_its_close_unless_worst_case():
    spec = [(575, 9.9, 10.1, 9.7, 10.05), (959, 10.5, 10.5, 10.5, 10.5)]  # touched 9.70 < stop 9.80, closed above
    assert s.trade(PICK, bars(spec))["how"] == "close"
    assert s.trade(PICK, bars(spec), worst_case=True)["exit"] == pytest.approx(9.8)
    closed_below = [(575, 9.9, 10.1, 9.7, 9.75), (959, 10.5, 10.5, 10.5, 10.5)]
    assert s.trade(PICK, bars(closed_below))["exit"] == pytest.approx(9.8)


def test_a_short_mirrors_and_late_or_missing_triggers_do_not_trade():
    short = dict(PICK, side=-1)  # level 9.50, stop 9.70
    t = s.trade(short, bars([(580, 9.6, 9.6, 9.45, 9.5), (600, 9.5, 9.75, 9.4, 9.7), (959, 9, 9, 9, 9)]))
    assert t["fill"] == 9.5 and t["exit"] == pytest.approx(9.7) and t["r"] == pytest.approx(r(-0.2, 9.5, 9.7))
    assert s.trade(PICK, bars([(575, 9.9, 9.95, 9.8, 9.9), (959, 9.9, 9.9, 9.9, 9.9)])) is None
    assert s.trade(PICK, bars([(956, 9.9, 10.5, 9.9, 10.4), (959, 10.4, 10.4, 10.4, 10.4)])) is None  # after 15:55
    assert s.trade(PICK, bars([(576, 9.95, 10.1, 9.9, 10.05), (959, 10.4, 10.5, 10.3, 10.4)]),
                   cost_multiple=3.0)["r"] == pytest.approx((0.4 - 3 * s.cost(10.0) - 3 * s.cost(10.4)) / 0.2)


def made(day, rr, side=1, rank=1):
    return {"day": day, "r": rr, "gross_r": rr + 0.1, "side": side, "rank": rank, "how": "close"}


def test_decisions_need_the_interval_both_periods_and_tripled_costs():
    good = [made(f"2024-0{m}-1{d}", 0.3) for m in range(1, 7) for d in range(5)] + \
           [made(f"2025-0{m}-1{d}", 0.2) for m in range(7, 10) for d in range(5)]
    out = s.summarize(good, [dict(t, r=0.1) for t in good], selected=len(good) * 2)
    assert out["both_sides"]["decision"] == "worth a paper test" and out["long_side"]["decision"] == "worth a paper test"
    assert out["descriptive"]["triggered_share"] == 0.5
    eaten = s.summarize(good, [dict(t, r=-0.1) for t in good], selected=len(good))
    assert eaten["both_sides"]["decision"] == "no evidence either way"
    bad = [dict(t, r=-0.3) for t in good]
    assert s.summarize(bad, bad, selected=len(bad))["both_sides"]["decision"] == "loses money"
    shorts = good + [made("2024-02-11", -5.0, side=-1)]
    out = s.summarize(shorts, shorts, selected=len(shorts))
    assert out["descriptive"]["short_side"]["trades"] == 1 and out["long_side"]["trades"] == len(good)


def test_run_reads_the_saved_sessions(tmp_path):
    days = [f"2026-04-{d:02d}" for d in range(1, 31)] + ["2026-05-04", "2026-05-05"]
    s.save(tmp_path / "daily.json.gz", {"days": days, "raw": {}, "ratios": {}})
    original = (s.START, s.END)
    s.START, s.END = s.date(2026, 5, 4), s.date(2026, 5, 5)
    try:
        s.save(tmp_path / "session" / "2026-05-04.json.gz",
               {"picks": [PICK], "bars": {"AAA": [[576, 9.95, 10.1, 9.9, 10.05, 1], [959, 10.4, 10.5, 10.3, 10.4, 1]]}})
        s.save(tmp_path / "session" / "2026-05-05.json.gz", {"picks": [PICK], "bars": {}})
        out = s.run(tmp_path, tmp_path / "copy.json")
    finally:
        s.START, s.END = original
    assert out["sessions"] == 2 and out["both_sides"]["trades"] == 1 and out["descriptive"]["selected"] == 2
    assert json.loads((tmp_path / "copy.json").read_text())["protocol_id"] == s.PROTOCOL_ID


def test_the_protocol_names_the_constants_in_code():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "opening-breakout" / "protocol.json").read_text())
    assert protocol["protocol_id"] == s.PROTOCOL_ID and protocol["tests"]["count"] == 2
    assert str(s.SEED) in protocol["tests"]["uncertainty"] and "97.5%" in protocol["tests"]["uncertainty"]
    assert "top 20" in protocol["selection"]["stocks_in_play"] and "0.10 x" in protocol["trade"]["stop"]
    assert "one cent a share plus 2 basis points" in protocol["trade"]["costs"]
