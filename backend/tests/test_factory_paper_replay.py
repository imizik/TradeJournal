"""Invented bars only. No cache loader, Factory evaluation or candidate ledger."""
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.engine.factory_data import ET, FeatureContext, Series
from app.engine.factory_rules import run_candidate
from app.engine.market_map import Bar

PATH = Path(__file__).resolve().parents[1] / "scripts/factory_paper_replay.py"


@pytest.fixture(scope="module")
def replay():
    module_spec = importlib.util.spec_from_file_location("factory_paper_replay", PATH)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def reference(replay, observations):
    spec = replay.frozen_spec()
    s = Series.build("MU", [o.bar for o in observations], 5)
    # Explicit expected-calendar adapter contract, independent of prefix-last.
    s.last = [(t.hour, t.minute) in ((15, 55),) or
              (t.date().isoformat() == "2024-11-29" and (t.hour, t.minute) == (12, 55))
              for t in s.time]
    f = FeatureContext(s, None)
    return run_candidate(s, spec.rules().start(s), spec.exits, spec.costs, spec.window, spec.limits,
                         lambda signal: all(r.passes(f.at(signal.index, signal.side, signal.stop)) for r in spec.filters), f)


def test_every_prefix_matches_factory_and_does_not_liquidate_at_prefix_end(replay):
    bars = list(replay.synthetic_demo())
    for n in range(1, len(bars) + 1):
        events = replay.replay_snapshot("MU", bars[:n])
        expected = reference(replay, bars[:n])
        entries = [e for e in events if e["kind"] == "model_entry"]
        exits = [e for e in events if e["kind"] == "model_exit"]
        assert [(e["price"], e["stop"], e["side"]) for e in entries] == [(t.entry_price, t.stop, t.side) for t in expected]
        assert [(e["price"], e["reason"]) for e in exits] == [(t.exit_price, t.exit_reason) for t in expected if t.closed]
    assert len(entries) == len(exits) == 1
    assert entries[0]["price"] == 102.0102
    assert exits[0]["reason"] == "session"
    assert not [e for e in replay.replay_snapshot("MU", bars[:-1]) if e["kind"] == "model_exit"]


def test_rvol_warmup_and_consumed_rejected_breakout(replay):
    bars = list(replay.synthetic_demo())
    # First day's breakout has no five prior sessions and must be rejected.
    first = replace(bars[1], bar=replace(bars[1].bar, high=103, close=102))
    events = replay.replay_snapshot("MU", [bars[0], first, bars[2], bars[3]])
    signal, = [e for e in events if e["kind"] == "signal"]
    assert not signal["accepted"] and signal["rvol"] is None
    assert not [e for e in events if e["kind"] == "model_entry"]
    # Once the long direction was consumed, more volume cannot re-arm it.
    bars[-3] = replace(bars[-3], bar=replace(bars[-3].bar, volume=1))
    bars[-4] = replace(bars[-4], bar=replace(bars[-4].bar, volume=1))
    bars[-2] = replace(bars[-2], bar=replace(bars[-2].bar, volume=100000))
    signals = [e for e in replay.replay_snapshot("MU", bars) if e["kind"] == "signal"]
    assert len(signals) == 1 and not signals[0]["accepted"]


def test_two_sides_stops_and_gap_refusal_match_factory(replay):
    bars = list(replay.synthetic_demo())[:-1]
    # Stop the long on its entry bar; a close below the range proposes short.
    bars[-1] = replace(bars[-1], bar=replace(bars[-1].bar, low=98, close=99))
    last = bars[-1]
    short = replay.Observation(Bar(last.bar.time + timedelta(minutes=5), 99, 101, 98, 99, 3000),
                               last.observed_at + timedelta(minutes=5))
    bars.append(short)
    events = replay.replay_snapshot("MU", bars)
    trades = reference(replay, bars)
    assert [e["side"] for e in events if e["kind"] == "model_entry"] == [1, -1]
    assert [(e["price"], e["reason"]) for e in events if e["kind"] == "model_exit"] == [(t.exit_price, t.exit_reason) for t in trades]
    assert all(e["model_fill_at"] is None for e in events if e["kind"] == "model_exit")
    # The next observed open is through the original long stop: no long fill.
    gap = list(replay.synthetic_demo())
    gap[-2] = replace(gap[-2], bar=replace(gap[-2].bar, open=99, low=98))
    unfilled = [e for e in replay.replay_snapshot("MU", gap) if e["kind"] == "unfilled"]
    assert unfilled[0]["reason"] == "gap_through_stop"


def test_early_close_and_missing_open(replay):
    bars = list(replay.synthetic_demo())
    active = datetime(2024, 11, 29, 9, 30, tzinfo=ET)
    bars = bars[:-4] + [replace(o, bar=replace(o.bar, time=active + timedelta(minutes=offset)),
                                observed_at=active + timedelta(minutes=offset + 5))
                       for o, offset in zip(bars[-4:], (0, 5, 10, 205))]
    events = replay.replay_snapshot("MU", bars)
    exit_event, = [e for e in events if e["kind"] == "model_exit"]
    assert datetime.fromisoformat(exit_event["model_fill_at"]).astimezone(ET).hour == 13
    assert exit_event["price"] == reference(replay, bars)[0].exit_price
    # Without the 09:30 bar the frozen family does not arm a range.
    assert not replay.replay_snapshot("MU", bars[:-4] + bars[-3:])


def test_receipt_time_never_becomes_a_retroactive_paper_fill(replay):
    bars = list(replay.synthetic_demo())
    bars[-3] = replace(bars[-3], observed_at=bars[-3].observed_at + timedelta(seconds=20))
    entry_obs = bars[-2]
    quote = {"event_at": entry_obs.observed_at.isoformat(), "received_at": entry_obs.observed_at.isoformat(),
             "bid": 103, "ask": 104, "bid_size": 100, "ask_size": 100}
    bars[-2] = replace(entry_obs, quote=quote)
    entry, = [e for e in replay.replay_snapshot("MU", bars) if e["kind"] == "model_entry"]
    assert entry["order_eligible_at"] > entry["model_fill_at"]
    assert entry["paper_fill_at"] is None and entry["paper_fill_price"] is None
    assert entry["retroactive_open"] and entry["quote_status"] == "comparison_only"
    assert entry["quote_price"] == 104 and entry["adverse_price_difference"] == pytest.approx(1.9898)
    for bad, status in [(None, "missing"), ({**quote, "ask": 102}, "invalid"),
                        ({**quote, "event_at": (entry_obs.observed_at - timedelta(seconds=6)).isoformat()}, "stale_or_out_of_order"),
                        ({**quote, "received_at": (entry_obs.observed_at + timedelta(seconds=1)).isoformat()}, "stale_or_out_of_order")]:
        bars[-2] = replace(entry_obs, quote=bad)
        e, = [e for e in replay.replay_snapshot("MU", bars) if e["kind"] == "model_entry"]
        assert e["quote_status"] == status and e["paper_fill_at"] is None


def test_restart_deduplicates_inputs_and_events_without_revising_receipts(replay, tmp_path):
    bars = list(replay.synthetic_demo())
    fresh = []
    for obs in bars:
        fresh += replay.ReplayJournal(tmp_path, "MU").append(obs)
    path = tmp_path / "factory-paper-replay.jsonl"
    before = path.read_bytes()
    for obs in bars:
        assert replay.ReplayJournal(tmp_path, "MU").append(obs) == []
    assert path.read_bytes() == before
    assert fresh == replay.replay_snapshot("MU", bars)
    assert len({e["id"] for e in fresh}) == len(fresh)
    with pytest.raises(ValueError, match="revised observation"):
        replay.ReplayJournal(tmp_path, "MU").append(replace(bars[-1], observed_at=bars[-1].observed_at + timedelta(seconds=1)))
    assert path.read_bytes() == before


def test_journal_fails_closed_on_torn_corrupt_or_different_stream(replay, tmp_path):
    obs = next(replay.synthetic_demo())
    replay.ReplayJournal(tmp_path, "MU").append(obs)
    path = tmp_path / "factory-paper-replay.jsonl"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="differs"):
        replay.ReplayJournal(tmp_path, "AAPL").append(obs)
    for corrupt in (before[:-1], before.replace(b'"volume":1000', b'"volume":1001')):
        path.write_bytes(corrupt)
        with pytest.raises(ValueError):
            replay.ReplayJournal(tmp_path, "MU").append(obs)
        assert path.read_bytes() == corrupt


@pytest.mark.parametrize("fault", ["incomplete", "future", "naive", "bad_ohlc", "duplicate", "out_of_order", "missing_close", "split"])
def test_bad_input_is_refused_before_events_are_committed(replay, tmp_path, fault):
    bars = list(replay.synthetic_demo())
    obs = bars[0]
    if fault == "incomplete":
        obs = replace(obs, complete=False)
    elif fault == "future":
        obs = replace(obs, observed_at=obs.bar.time)
    elif fault == "naive":
        obs = replace(obs, observed_at=obs.observed_at.replace(tzinfo=None))
    elif fault == "bad_ohlc":
        obs = replace(obs, bar=replace(obs.bar, low=999))
    elif fault in ("duplicate", "out_of_order", "missing_close", "split"):
        prefix = bars[:4] if fault == "split" else bars[:1]
        for b in prefix:
            replay.ReplayJournal(tmp_path, "MU").append(b)
        if fault == "duplicate":
            obs = replace(obs, bar=replace(obs.bar, volume=1001))
        elif fault == "out_of_order":
            obs = replace(obs, bar=replace(obs.bar, time=obs.bar.time-timedelta(days=1)))
        else:
            obs = bars[4]
            if fault == "split":
                obs = replace(obs, bar=replace(obs.bar, open=10, high=10.05, low=9.95, close=10))
    path = tmp_path / "factory-paper-replay.jsonl"
    before = path.read_bytes() if path.exists() else b""
    with pytest.raises(ValueError):
        replay.ReplayJournal(tmp_path, "MU").append(obs)
    assert path.read_bytes() == before


def test_demo_has_no_historical_input_or_live_switch(replay, tmp_path, capsys):
    assert replay.main(["--demo", "--output", str(tmp_path)]) == 0
    assert "No executable fills or candidate evaluation" in capsys.readouterr().out
    assert replay.main(["--demo", "--output", str(tmp_path)]) == 0
    assert "0 new events" in capsys.readouterr().out
    for args in (["--output", str(tmp_path)], ["--demo", "--output", str(tmp_path), "--live"]):
        with pytest.raises(SystemExit):
            replay.main(args)
    records = [json.loads(line) for line in (tmp_path / "factory-paper-replay.jsonl").read_text().splitlines()]
    assert records[0]["mode"] == "disabled_fixture_replay"
    assert list(tmp_path.iterdir()) == [tmp_path / "factory-paper-replay.jsonl"]


def test_concurrent_retry_commits_one_observation(replay, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    obs = next(replay.synthetic_demo())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: replay.ReplayJournal(tmp_path, "MU").append(obs), range(2)))
    assert results == [[], []]  # first opening-range bar has no signal
    rows = (tmp_path / "factory-paper-replay.jsonl").read_text().splitlines()
    assert len(rows) == 2  # one header + one input, even under simultaneous retry


def test_restart_rejects_changed_implementation_and_forged_derived_event(replay, tmp_path, monkeypatch):
    for obs in replay.synthetic_demo():
        replay.ReplayJournal(tmp_path, "MU").append(obs)
    path = tmp_path / "factory-paper-replay.jsonl"
    original = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(replay, "_implementation", lambda: "different-code")
        with pytest.raises(ValueError, match="implementation differs"):
            replay.ReplayJournal(tmp_path, "MU").append(obs)
    assert path.read_bytes() == original
    rows = [json.loads(line) for line in original.splitlines()]
    rows[-1]["events"][0]["price"] += 1
    rows[-1]["hash"] = replay._digest({k: v for k, v in rows[-1].items() if k != "hash"})
    path.write_text("\n".join(replay._json(row) for row in rows) + "\n")
    with pytest.raises(ValueError, match="replay differs"):
        replay.ReplayJournal(tmp_path, "MU").append(obs)
