"""The QQQ overnight hold study's rules, on hand-built bars and quotes (no network, no database)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import opening_breakout_study as v1
from scripts import opening_breakout_top5_study as t5
from scripts import qqq_overnight_study as q

D0, D1 = "2024-03-05", "2024-03-06"


def _bars(open_: float = 100.0, close: float = 100.0) -> dict[int, list]:
    bars = {m: [open_, open_, open_, open_, 1000.0] for m in range(q.OPEN_MINUTE, q.ENTRY_MINUTE)}
    bars[q.ENTRY_MINUTE] = [close, close, close, close, 1000.0]
    return bars


class Quotes:
    """Hand-built quotes [(ns, bid, ask)], logging each answer like the Recorder."""

    def __init__(self, quotes=()):
        self.quotes, self.log = sorted(quotes), {}

    def quote_at(self, symbol, t):
        rows = [[s, b, a] for s, b, a in self.quotes if t - t5.QUOTE_AGE <= s <= t]
        got = rows[-1] if rows else None
        self.log[t5.quote_key(symbol, t)] = got
        return got


def _close_quote(day, bid, ask):
    return (t5.minute_ns(day, q.ENTRY_MINUTE), bid, ask)


def _open_quote(day, bid, ask, seconds_before=0):
    return (t5.minute_ns(day, q.OPEN_MINUTE) - seconds_before * 10**9, bid, ask)


def test_holds_pair_each_full_session_with_the_next_and_skip_early_close_entries():
    by_day = {d: [] for d in ("2016-11-23", "2016-11-25", "2016-11-28", "2016-11-29")}
    assert q.holds(by_day) == [("2016-11-23", "2016-11-25"), ("2016-11-28", "2016-11-29")]
    # The window's last day is only an exit.
    assert q.holds({"2026-11-12": [], "2026-11-13": []}) == [("2026-11-12", "2026-11-13")]


def test_buys_at_the_ask_and_sells_at_the_bid_a_second_later():
    src = Quotes([_close_quote(D0, 99.99, 100.01), _open_quote(D1, 100.49, 100.51, seconds_before=5)])
    t = q.tape_hold(D0, D1, _bars(), _bars(), src)
    assert (t["status"], t["fill"], t["exit"], t["how"]) == ("held", 100.01, 100.49, "bid")
    assert t["bp"] == pytest.approx((100.49 - 100.01) / 100.01 * 10_000)
    assert t["bp_extra_cent"] == pytest.approx((100.49 - 100.01 - 0.02) / 100.01 * 10_000)
    assert t["spread_bp"] == pytest.approx(0.02 / 100.01 * 10_000)


def test_missing_quotes():
    assert q.tape_hold(D0, D1, _bars(), _bars(), Quotes())["status"] == "no fill quote"
    # A quote over 60 seconds old is not in effect: the exit falls back to the 09:30 bar's open.
    src = Quotes([_close_quote(D0, 99.99, 100.01), _open_quote(D1, 100.49, 100.51, seconds_before=120)])
    t = q.tape_hold(D0, D1, _bars(), _bars(open_=100.3), src)
    assert (t["how"], t["exit"]) == ("open from bar", 100.3)


def test_bar_versions():
    assert q.bar_hold(D0, D1, _bars(close=100.0), _bars(open_=101.0))["bp"] == pytest.approx(100.0)
    assert q.bar_intraday(D0, _bars(open_=100.0, close=99.0))["bp"] == pytest.approx(-100.0)


def test_decide():
    ok = {"first": 1.0, "second": 1.0, "third": 0.5}
    assert q.decide([0.1, 2.0], ok, 0.5, 0.2, 1.0) == "worth a paper test"
    assert q.decide([0.1, 2.0], ok, 0.5, 1.5, 1.0) == "no evidence either way"  # intraday did better
    assert q.decide([0.1, 2.0], {**ok, "third": -0.1}, 0.5, 0.2, 1.0) == "no evidence either way"
    assert q.decide([0.1, 2.0], ok, -0.1, 0.2, 1.0) == "no evidence either way"
    assert q.decide([-2.0, -0.1], ok, 0.5, 0.2, 1.0) == "loses money"
    assert q.decide(None, ok, 0.5, 0.2, 1.0) == "no evidence either way"


def test_growth_compounds_in_day_order():
    assert q.growth([{"day": D1, "bp": -100.0}, {"day": D0, "bp": 100.0}]) == pytest.approx(round(1.01 * 0.99, 3))


def test_run_replays_the_saved_answers(tmp_path: Path):
    src = Quotes([_close_quote(D0, 99.99, 100.01), _open_quote(D1, 100.49, 100.51)])
    q.tape_hold(D0, D1, _bars(), _bars(), src)
    v1.save(tmp_path / "session" / f"{D0}.json.gz", {"ticks": src.log})
    rows = lambda b: [[m, *v] for m, v in sorted(b.items())]  # noqa: E731
    missing = _bars()
    del missing[q.ENTRY_MINUTE]
    v1.save(tmp_path / "bars.json.gz", {D0: rows(_bars()), D1: rows(missing), "2024-03-07": rows(_bars(open_=100.4))})
    results = q.run(tmp_path, tmp_path / "out.json")
    assert results["protocol_id"] == q.PROTOCOL_ID
    assert results["test"]["holds"] == 1
    assert results["test"]["mean_bp"] == pytest.approx(round((100.49 - 100.01) / 100.01 * 10_000, 3))
    d = results["descriptive"]
    assert (d["entry_sessions"], d["holds_possible"], d["missing_bars"], d["exits"]["bid"]) == (2, 2, 1, 1)
    assert json.loads((tmp_path / "out.json").read_text()) == results
    # A question the fetch never asked is an error, not a guess.
    v1.save(tmp_path / "session" / f"{D0}.json.gz", {"ticks": {}})
    with pytest.raises(KeyError):
        q.run(tmp_path)


def test_protocol_matches_the_script():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "qqq-overnight" / "protocol.json").read_text())
    assert protocol["protocol_id"] == q.PROTOCOL_ID
    assert "2016-01-04" in protocol["sessions"] and "2026-11-12" in protocol["sessions"]
    assert "seed 20261114" in protocol["test"]["uncertainty"] and "95%" in protocol["test"]["uncertainty"]
    assert "15:59:00" in protocol["rules"]["entry"] and "09:30:00" in protocol["rules"]["exit"]
    for name, lo, hi in q.PERIODS:
        assert lo in protocol["periods"][name] and hi in protocol["periods"][name]
