"""Trade mode: causal packets, the enter/manage clock, option-cost grading, resume, scoring."""

import copy

import pytest

from research.opening_lab import cross, trades
from research.opening_lab.baselines import BASELINES
from research.opening_lab.contract import checkpoint_ts
from research.opening_lab.tests.test_packet import DAY, make_session


def with_cross(session):
    minutes = {}
    for i, sym in enumerate(("TLT", "NVDA", "XLK", "XLF")):
        base = 100.0 + i
        minutes[sym] = [{"t": t, "o": base + k * 0.01, "h": base + k * 0.01 + 0.02, "l": base + k * 0.01 - 0.02,
                         "c": base + (k + 1) * 0.01 * (1 if i % 2 else -1), "v": 100}
                        for k, t in enumerate(range(checkpoint_ts(DAY, "08:00"), checkpoint_ts(DAY, "11:00"), 60))]
    return {**session, "cross": {"prior_close": {s: 99.0 for s in minutes}, "minutes": minutes}}


@pytest.fixture
def session():
    return with_cross(make_session())


def _future_scrambled(session, c_ts):
    s = copy.deepcopy(session)
    for sym in s["symbols"].values():
        for b in sym["minutes"]:
            if b["t"] + 60 > c_ts:
                b.update(o=b["o"] * 1.5, h=b["h"] * 1.5, l=b["l"] * 1.5, c=b["c"] * 1.5, v=b["v"] * 3)
    for bars in s["cross"]["minutes"].values():
        for b in bars:
            if b["t"] + 60 > c_ts:
                b.update(o=1.0, h=1.0, l=1.0, c=1.0)
    s["news"] = [n for n in s["news"]] + [{"id": "future", "headline": "Fed cuts rates in surprise move",
                                           "summary": "", "symbols": ["SPY"], "source": "benzinga",
                                           "created_at": "2026-07-15T14:29:30Z"}]
    return s


def test_trade_packets_are_causal(session):
    trade = {"symbol": "QQQ", "side": "SHORT", "entry_cp": "09:40", "exit_cp": None}
    for cp in trades.CHECKPOINTS:
        c_ts = checkpoint_ts(DAY, cp)
        open_trade = trade if cp > "09:40" else None
        a = trades.build_trade_packet(session, cp, "full", trade=open_trade)
        b = trades.build_trade_packet(_future_scrambled(session, c_ts), cp, "full", trade=open_trade)
        assert a == b, cp
    assert a["cross"]["breadth"]["sectors_up_since_open"] is not None
    assert a["position"]["forced_exit_et"] == "10:11"


def test_variants_hide_context(session):
    bars = trades.build_trade_packet(session, "09:50", "bars")
    assert bars["cross"] is None and bars["news"] == [] and bars["symbols"]["SPY"]["features"] is None
    assert trades.build_trade_packet(session, "09:50", "market")["cross"] is None


def test_enter_then_exit_on_its_own_and_grading(session):
    def answer(cp, phase, trade, decisions):
        if phase == "entry":
            return {"action": "LONG", "symbol": "SPY", "reason": ""} if cp == "09:40" else \
                {"action": "WAIT", "symbol": None, "reason": ""}
        return {"action": "EXIT" if cp == "09:55" else "HOLD", "symbol": None, "reason": ""}

    trade, decisions = trades.walk(DAY, answer)
    assert [cp for cp, _ in decisions] == ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55"]
    g = trades.grade(session, trade)
    by_t = {b["t"]: b for b in session["symbols"]["SPY"]["minutes"]}
    entry, out = by_t[checkpoint_ts(DAY, "09:41")]["o"], by_t[checkpoint_ts(DAY, "09:56")]["o"]
    gross = (out / entry - 1) * 1e4
    assert g["exit"] == "model" and g["minutes"] == 15
    assert g["net_bps"] == pytest.approx(gross - trades.OPTION_SPREAD_BPS - 15 * trades.OPTION_DECAY_BPS_PER_MIN,
                                         abs=1e-3)
    assert trades.grade(session, trade, exit_kind="max")["minutes"] == trades.MAX_HOLD_MINUTES


def test_hold_runs_to_the_forced_exit_and_no_second_trade(session):
    def answer(cp, phase, trade, decisions):
        if phase == "entry":
            return {"action": "SHORT" if cp == "10:00" else "WAIT", "symbol": "QQQ" if cp == "10:00" else None,
                    "reason": ""}
        return {"action": "HOLD", "symbol": None, "reason": ""}

    trade, decisions = trades.walk(DAY, answer)
    assert [cp for cp, _ in decisions][-5:] == ["10:05", "10:10", "10:15", "10:20", "10:25"]
    g = trades.grade(session, trade)
    assert g["exit"] == "max" and g["exit_et"] == "10:31" and g["side"] == "SHORT"

    exits_early = trades.walk(DAY, lambda cp, phase, t, d: (
        {"action": "LONG", "symbol": "SPY", "reason": ""} if phase == "entry"
        else {"action": "EXIT", "symbol": None, "reason": ""}))
    assert [cp for cp, _ in exits_early[1]] == ["09:30", "09:35"]   # flat again, but done for the morning


def test_decisions_validate_and_wrong_phase_counts_as_no_action(tmp_path, session):
    with pytest.raises(ValueError):
        trades.validate_decision({"action": "LONG", "symbol": None, "reason": ""})
    assert trades.validate_decision({"action": "EXIT", "symbol": "SPY", "reason": "x"})["symbol"] is None

    class HoldsWhenFlat(trades.FakeTrader):
        def forecast(self, packet):
            return {"status": "ok", "forecast": {"action": "HOLD", "symbol": None, "reason": ""},
                    "error": None, "cost_usd": 0.0}

    run = trades.replay(tmp_path, [DAY], sessions={DAY: session}, model=HoldsWhenFlat(), model_name="m",
                        variants=["bars"], log=lambda _m: None)
    rows = run.rows()
    assert len(rows) == len(trades.ENTRY_CHECKPOINTS)
    assert all(r["status"] == "invalid" and r["error"] == "phase_entry_HOLD" for r in rows)


class Counting(trades.FakeTrader):
    def __init__(self):
        self.calls = 0

    def forecast(self, packet):
        self.calls += 1
        return super().forecast(packet)


def test_replay_resumes_and_scores(tmp_path, session):
    first = Counting()
    run = trades.replay(tmp_path, [DAY], sessions={DAY: session}, model=first, model_name="m",
                        variants=["bars", "full"], log=lambda _m: None)
    # 09:30, 09:35 wait; 09:40 long; re-checks 09:45, 09:50, 09:55 (exit) -> 6 per variant
    assert first.calls == 12 and len(run.rows()) == 12
    again = Counting()
    trades.replay(tmp_path, [DAY], sessions={DAY: session}, model=again, model_name="m",
                  variants=["bars", "full"], log=lambda _m: None)
    assert again.calls == 0

    report = trades.score_trades(run.rows(), {DAY: session}, rules=BASELINES, draws=50)
    s = report["strategies"]["m/bars"]
    assert s["trades"] == 1 and s["own_exits"] == 1 and s["minutes"] == 15
    assert "rule always_long, exit 15m" in report["strategies"]
    assert report["strategies"]["no trade"]["net_per_morning"] == 0.0
    names = {(c["a"], c["b"]) for c in report["comparisons"]}
    assert ("m/bars", "no trade") in names and ("m/bars", "m/full") in names
    assert "trade scorecard" in trades.render_trades(report)


def test_cross_rows_use_previous_close_and_visible_bars(session):
    block = cross.cross_block(session, checkpoint_ts(DAY, "09:31"))
    gap, since_open, last5 = block["macro"]["TLT"]
    first_open = session["cross"]["minutes"]["TLT"][90]["o"]          # 09:30 bar (08:00 + 90 min)
    assert gap == pytest.approx(100 * (first_open / 99.0 - 1), abs=1e-3)
    assert since_open is not None and last5 is None                   # one RTH bar: no 5-minute change yet
    assert block["macro"]["UUP"] == [None, None, None]                 # not in the cache: unavailable
