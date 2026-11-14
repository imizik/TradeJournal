"""The QQQ opening range breakout study's rules, on hand-built bars and a hand-built tape (no network, no database)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import opening_breakout_study as v1
from scripts import opening_breakout_top5_study as t5
from scripts import qqq_orb_study as q

DAY = "2024-03-05"


def _bars(first: list[tuple], later: dict[int, tuple] | None = None, flat: float = 100.0) -> dict[int, list]:
    """Five first-candle bars (o, h, l, c), then flat bars at ``flat`` to 15:59 unless ``later`` overrides a minute."""
    bars = {q.FIRST[k]: [*first[k], 1000.0] for k in range(5)}
    for m in range(q.ENTRY_MINUTE, q.EXIT_MINUTE + 1):
        bars[m] = [flat, flat + 0.02, flat - 0.02, flat, 1000.0]
    for m, row in (later or {}).items():
        bars[m] = [*row, 1000.0]
    return bars


UP = [(99.5, 99.8, 99.4, 99.7), (99.7, 99.9, 99.6, 99.8), (99.8, 100.0, 99.7, 99.9), (99.9, 100.0, 99.8, 99.9),
      (99.9, 100.0, 99.8, 99.95)]  # opens 99.5, closes 99.95: long, stop at the low 99.4


class Tape:
    """A hand-built tape: trades [(ns, price)] and quotes [(ns, bid, ask)], logging each answer like the Recorder."""

    def __init__(self, trades=(), quotes=()):
        self.trades, self.quotes, self.log = sorted(trades), sorted(quotes), {}

    def through(self, symbol, lo, hi, threshold, side):
        got = [[t, p] for t, p in self.trades if lo <= t < hi and (p >= threshold if side > 0 else p <= threshold)]
        self.log[t5.through_key(symbol, lo, hi, threshold, side)] = got
        return got

    def quote_at(self, symbol, t):
        rows = [[s, b, a] for s, b, a in self.quotes if s <= t and s >= t - t5.QUOTE_AGE]
        got = rows[-1] if rows else None
        self.log[t5.quote_key(symbol, t)] = got
        return got


def at(minute: int, second: int = 0) -> int:
    return t5.minute_ns(DAY, minute) + second * 10**9


def _quotes(bid: float, ask: float, minutes=range(q.OPEN_MINUTE, q.EXIT_MINUTE + 1)) -> list[tuple]:
    return [(at(m), bid, ask) for m in minutes]


def test_setup_reads_the_first_candle():
    s = q.setup(_bars(UP))
    assert (s["status"], s["side"], s["p"], s["stop"]) == ("setup", 1, 100.0, 99.4)
    assert s["risk"] == pytest.approx(0.6) and s["target"] == pytest.approx(106.0)
    down = [(r[0], r[1], r[2], r[3]) for r in UP[:4]] + [(99.9, 100.0, 99.3, 99.4)]  # closes below the 99.5 open
    s = q.setup(_bars(down, flat=99.6))
    assert (s["side"], s["stop"]) == (-1, 100.0)
    assert q.setup(_bars(UP[:4] + [(99.9, 100.0, 99.8, 99.5)]))["status"] == "doji"
    missing = _bars(UP)
    del missing[q.FIRST[2]]
    assert q.setup(missing)["status"] == "missing bars"
    assert q.setup(_bars(UP, flat=99.4))["status"] == "no room"  # entry at the stop


def test_tape_fills_entry_at_the_ask_and_the_stop_at_the_bid_a_second_later():
    bars = _bars(UP, later={q.ENTRY_MINUTE + 30: (99.6, 99.6, 99.3, 99.35)})
    s = q.setup(bars)
    tape = Tape(trades=[(at(q.ENTRY_MINUTE + 30, 20), 99.38)],
                quotes=_quotes(99.99, 100.01) + [(at(q.ENTRY_MINUTE + 30, 19), 99.39, 99.41),
                                                 (at(q.ENTRY_MINUTE + 30, 21), 99.36, 99.37)])
    t = q.tape_trade(s, bars, tape, DAY)
    assert (t["how"], t["fill"], t["exit"]) == ("stop", 100.01, 99.36)
    assert t["r"] == pytest.approx((99.36 - 100.01) / 0.6)
    assert t["spread_r"] == pytest.approx(0.02 / 0.6)
    assert t["r_extra_cent"] == pytest.approx((99.36 - 100.01 - 0.02) / 0.6)


def test_target_needs_a_trade_a_cent_through_and_must_come_before_the_stop():
    m = q.ENTRY_MINUTE + 60
    bars = _bars(UP, later={m: (105.9, 106.05, 105.8, 106.0)})
    s = q.setup(bars)
    quotes = _quotes(99.99, 100.01) + [(at(m), 105.99, 106.01)]
    touch = Tape(trades=[(at(m, 5), 106.0)], quotes=quotes)  # a touch is not a fill
    assert q.tape_trade(s, bars, touch, DAY)["how"] == "close"
    through = Tape(trades=[(at(m, 5), 106.01)], quotes=quotes)
    t = q.tape_trade(s, bars, through, DAY)
    assert (t["how"], t["exit"]) == ("target", s["target"])
    assert t["r"] == pytest.approx((106.0 - 100.01) / 0.6)
    # Without a target the same day closes at the 15:59 bid.
    t = q.tape_trade(s, bars, through, DAY, target=False)
    assert (t["how"], t["exit"]) == ("close", 99.99)


def test_a_trade_exactly_one_cent_through_fills_despite_float_error():
    # 167.18 + 10 x (167.18 - 166.85) is 170.48000000000013 in floats; the cent rule must still see 170.49 as through.
    first = [(167.0, 167.1, 166.85, 167.05), (167.05, 167.1, 167.0, 167.05), (167.05, 167.1, 167.0, 167.05),
             (167.05, 167.1, 167.0, 167.05), (167.05, 167.15, 167.0, 167.1)]
    m = q.ENTRY_MINUTE + 90
    bars = _bars(first, later={q.ENTRY_MINUTE: (167.18, 167.2, 167.1, 167.18), m: (170.4, 170.49, 170.3, 170.45)},
                 flat=167.18)
    s = q.setup(bars)
    assert (s["target"], s["through"]) == (170.48, 170.49)
    tape = Tape(trades=[(at(m, 5), 170.49)], quotes=_quotes(167.17, 167.19) + [(at(m), 170.48, 170.5)])
    assert q.tape_trade(s, bars, tape, DAY)["how"] == "target"


def test_early_closes_are_left_out_even_with_after_hours_bars():
    after_hours = {"2016-11-25": [[m, 1, 1, 1, 1, 1] for m in range(q.OPEN_MINUTE, q.EXIT_MINUTE + 1)],
                   "2016-11-28": [[m, 1, 1, 1, 1, 1] for m in range(q.OPEN_MINUTE, q.EXIT_MINUTE + 1)]}
    assert q.sessions(after_hours) == ["2016-11-28"]


def test_close_and_missing_quotes():
    bars = _bars(UP)
    s = q.setup(bars)
    assert q.tape_trade(s, bars, Tape(), DAY)["status"] == "no fill quote"
    only_entry = Tape(quotes=[(at(q.ENTRY_MINUTE), 99.99, 100.01)])
    t = q.tape_trade(s, bars, only_entry, DAY)
    assert (t["how"], t["exit"]) == ("close from bar", 100.0)


def test_paper_version_on_bars_takes_the_stop_first():
    m = q.ENTRY_MINUTE + 10
    bars = _bars(UP, later={m: (100.0, 106.5, 99.3, 100.0)})
    s = q.setup(bars)
    assert q.bar_trade(s, bars, DAY) == {"day": DAY, "side": 1, "how": "stop", "r": pytest.approx(-1.0)}
    bars = _bars(UP, later={m: (100.0, 106.5, 99.9, 100.0)})
    assert q.bar_trade(s, bars, DAY)["r"] == pytest.approx(10.0)
    closing = _bars(UP, later={q.EXIT_MINUTE: (100.3, 100.32, 100.28, 100.3)})
    assert q.bar_trade(s, closing, DAY)["r"] == pytest.approx(0.5)


def test_decide():
    ok = {"first": 0.1, "second": 0.1, "third": 0.05}
    assert q.decide([0.01, 0.2], ok, 0.05) == "worth a paper test"
    assert q.decide([0.01, 0.2], {**ok, "third": -0.01}, 0.05) == "no evidence either way"
    assert q.decide([0.01, 0.2], ok, -0.01) == "no evidence either way"
    assert q.decide([-0.3, -0.01], ok, 0.05) == "loses money"
    assert q.decide(None, ok, 0.05) == "no evidence either way"


def test_run_replays_the_saved_answers(tmp_path: Path, monkeypatch):
    bars = _bars(UP)
    s = q.setup(bars)
    tape = Tape(quotes=_quotes(99.99, 100.01))
    q.tape_trade(s, bars, tape, DAY)
    q.tape_trade(s, bars, tape, DAY, target=False)
    v1.save(tmp_path / "session" / f"{DAY}.json.gz", {"ticks": tape.log})
    early = {m: [100.0] * 5 for m in range(q.OPEN_MINUTE, 12 * 60)}
    doji = _bars(UP[:4] + [(99.9, 100.0, 99.8, 99.5)])
    rows = lambda b: [[m, *v] for m, v in sorted(b.items())]  # noqa: E731
    v1.save(tmp_path / "bars.json.gz", {DAY: rows(bars), "2024-03-06": rows(doji), "2024-11-29": rows(early)})
    results = q.run(tmp_path, tmp_path / "out.json")
    assert results["protocol_id"] == q.PROTOCOL_ID
    assert results["test"]["trades"] == 1
    assert results["test"]["mean_r"] == pytest.approx(round((99.99 - 100.01) / 0.6, 4))
    d = results["descriptive"]
    assert (d["sessions"], d["early_closes_left_out"], d["doji"], d["exits"]["close"]) == (2, 1, 1, 1)
    assert json.loads((tmp_path / "out.json").read_text()) == results
    # A question the fetch never asked is an error, not a guess.
    v1.save(tmp_path / "session" / f"{DAY}.json.gz", {"ticks": {}})
    with pytest.raises(KeyError):
        q.run(tmp_path)


def test_protocol_matches_the_script():
    protocol = json.loads((Path(__file__).resolve().parents[2] / "research" / "qqq-orb" / "protocol.json").read_text())
    assert protocol["protocol_id"] == q.PROTOCOL_ID
    assert "2016-01-04" in protocol["sessions"] and "2026-11-13" in protocol["sessions"]
    assert "seed 20261114" in protocol["test"]["uncertainty"] and "99%" in protocol["test"]["uncertainty"]
    assert "10 R" in protocol["rules"]["target"] and "one second later" in protocol["rules"]["entry"]
    assert "2023-02-21" in protocol["periods"]["third"] and "2023-02-17" in protocol["periods"]["second"]
