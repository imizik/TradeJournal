"""Setup lab: card levels, exits, setup timing and point-in-time reads on small hand-built sessions."""
from datetime import date

import numpy as np

from scripts import radar_setup_lab as lab
from scripts.radar_historical_replay import bounds

NAN = np.nan


def closes(values, length=390):
    out = np.full(length, NAN)
    out[:len(values)] = values
    return out


def test_card_takes_the_low_so_far_and_refuses_a_flag_at_the_low():
    px = closes([100, 99, 101, 102])
    assert lab.card(px, 4, 1) == (102.0, 99.0, 3 / 102 * 100)
    assert lab.card(px, 2, 1) is None  # entry is the low: no level beyond the price
    assert lab.card(px, 4, -1) is None  # down needs a high above the entry
    assert lab.card(closes([100, 103, 101]), 3, -1)[1] == 103.0
    # The reversal card also counts the open, as its live extreme_price does.
    assert lab.card(px, 4, 1, opening=98.5)[1] == 98.5


def test_exit_stop_time_and_close():
    px = closes([100, 99, 101] + [101.5] * 10 + [98.9] + [102] * 300)
    trade = lab.score(px, 3, 1)
    assert (trade["exit_minute"], trade["reason"]) == (14, "stop")
    assert np.isclose(trade["pct"], (98.9 / 101 - 1) * 100) and trade["r"] < 0
    calm = closes([100, 99, 101] + [102] * 387)
    assert lab.score(calm, 3, 1)["exit_minute"] == 63 and lab.score(calm, 3, 1)["reason"] == "time"
    late = lab.score(calm, 340, 1)
    assert (late["exit_minute"], late["reason"]) == (385, "close")
    gap = calm.copy()
    gap[62:70] = NAN  # no close at +60: the first available one after it
    assert lab.score(gap, 3, 1)["exit_minute"] == 71
    on_time = calm.copy()
    on_time[62] = 98  # a stop on the time-stop minute is a stop
    assert lab.score(on_time, 3, 1)["reason"] == "stop"
    assert lab.score(closes([100, 99, 101]), 3, 1) is None  # no later close: unscored


def test_card_reads_nothing_after_the_flag_minute():
    px = closes([100, 99, 101, 102, 103])
    before = lab.card(px, 4, 1)
    px[4:] = 50  # the future crashes
    assert lab.card(px, 4, 1) == before


def test_laggard_needs_four_moving_peers_and_reads_only_its_row():
    since_open = np.zeros((390, 6))
    since_open[19:, :5] = 1.5  # five members up 1.5 pp from minute 20; member 5 flat
    group = [[0, 1, 2, 3, 4, 5]]
    assert lab.laggards(group, since_open) == [(5, 1, 20)]
    future = since_open.copy()
    future[20:, 5] = 3.0  # the laggard catches up later: its first minute does not change
    assert lab.laggards(group, future) == [(5, 1, 20)]
    thin = since_open.copy()
    thin[:, 1:4] = NAN  # only one other valid member (plus the laggard): no group read
    assert lab.laggards(group, thin) == []
    assert lab.laggards([[0, 1, 2, 3]], since_open) == []  # groups under five members are skipped
    early = np.zeros((390, 6))
    early[:9, :5] = 1.5  # moving only before the 10-minute window
    assert lab.laggards(group, early) == []


def test_pullback_bars_cut_at_a_missing_minute_and_alert_window(monkeypatch):
    rows = {str(i): [100 + i * 0.1, 100.05 + i * 0.1] for i in range(30)}
    del rows["12"]
    bars = lab.pullback_bars(rows, {str(i): 1000 for i in range(90)}, 0)
    assert len(bars) == 12 and bars[0]["high"] == 100.05 and bars[0]["low"] == 100
    assert len(lab.pullback_bars(rows, {str(i): 1000 for i in range(5)}, 0)) == 5  # missing volume cuts too

    class Signal:
        side, end = 1, 0

    for minute, expected in ((16, None), (17, (1, 17)), (89, (1, 89)), (90, None)):
        Signal.end = minute * 60
        monkeypatch.setattr(lab, "first_trigger", lambda *a: Signal)
        assert lab.pullback_flag([], 0) == expected


def _session(future=0.0):
    """SPY flat; five group members rise 2% from minute 20; F stays flat (a laggard), then maybe moves later."""
    day = date(2026, 9, 2)
    names = ["A", "B", "C", "D", "E", "F"]
    universe = {"version": "test", "groups": [{"name": "g", "members": names}],
                "symbols": [{"symbol": "SPY", "kind": "etf", "benchmark": True}]
                + [{"symbol": s, "kind": "stock", "benchmark": False} for s in names]}
    bars = {}
    for s in ["SPY", *names]:
        rows = {}
        for i in range(390):
            price = 100 + (0.01 * (i % 3))
            if s != "SPY" and s != "F" and i >= 19:
                price += 2
            if s == "F" and i >= 30:
                price += future
            rows[str(i)] = [price, price]
        bars[s] = rows
    previous = {s: 100.0 for s in bars}
    volume = {s: {str(i): 1000 for i in range(390)} for s in names}
    past = [volume] * 20
    return lab.Session(day, universe, bars, previous, volume, past, {})


def test_session_cards_point_in_time_with_matched_baseline():
    cards = [c for c in _session().cards() if c["setup"] == "laggard"]
    f = next(c for c in cards if c["symbol"] == "F")
    assert (f["direction"], f["minute"], f["carded"]) == ("up", 20, True)
    assert f["baseline"]["n"] >= 1 and "time_0_30" in f["filters"] and "spy_with" in f["filters"]
    assert "vol_normal" in f["filters"] and "gap_small" in f["filters"]
    moved = next(c for c in _session(future=-5).cards() if c["setup"] == "laggard" and c["symbol"] == "F")
    # What happens after the flag changes only the exit, never the flag, entry or level.
    assert {k: moved[k] for k in ("minute", "entry", "level")} == {k: f[k] for k in ("minute", "entry", "level")}
    assert moved["reason"] == "stop" and moved["pct"] < 0


def test_baseline_is_deterministic_and_excludes_the_flagged_stock():
    session = _session()
    first = session.baseline("laggard", "F", 40, 1)
    assert first == _session().baseline("laggard", "F", 40, 1)
    assert first["n"] <= 5


def test_summary_and_ranking_follow_the_protocol():
    def card(session, pct, base):
        return {"session": session, "setup": "drive", "carded": True, "filters": ["all", "dir_up"], "pct": pct,
                "r": pct, "reason": "time", "risk": 1.0, "baseline": {"pct": base, "r": base, "green": 0.5}}

    days = [f"d{i}" for i in range(10)]
    cards = [card(d, 1.0, 0.0) for d in days for _ in range(5)]
    summary = lab.summarize(cards, days)
    assert summary["drive:all"]["cards"] == 50 and summary["drive:all"]["edge_low"] == 1.0
    assert lab.ranking(summary) == ["drive:all", "drive:dir_up"]
    assert lab.verdicts(summary, ["drive:all"])["drive:all"] == "pass"
    assert lab.verdicts(summary, [])["dip:all live"] == "no evidence either way"


def test_bounds_are_new_york_regular_hours():
    start, end = bounds(date(2026, 9, 2))
    assert (start.hour, start.minute, end.hour) == (9, 30, 16)
