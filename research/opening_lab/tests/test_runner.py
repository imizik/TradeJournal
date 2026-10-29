"""Replay driver: resume without re-asking, prior decisions stay causal, budget stops calls."""

import json
from datetime import datetime, timedelta

import pytest

from research.opening_lab import contract, runner
from research.opening_lab.baselines import BASELINES
from research.opening_lab.model import FakeForecaster
from research.opening_lab.tests.test_packet import DAY, make_session


class Counting(FakeForecaster):
    def __init__(self, cost=0.01):
        super().__init__()
        self.packets = []
        self.cost = cost

    def forecast(self, packet):
        self.packets.append(packet)
        return {**super().forecast(packet), "cost_usd": self.cost}


@pytest.fixture
def sessions():
    return {DAY: make_session()}


def test_replay_records_every_slot_and_resumes_without_new_calls(tmp_path, sessions):
    model = Counting()
    run = runner.replay(tmp_path, [DAY], sessions=sessions, model=model, model_name="m",
                        variants=["bars", "full"], baselines=BASELINES)
    expected = len(contract.CHECKPOINTS_ET) * (2 + len(BASELINES))
    assert len(run.rows()) == expected
    assert len(model.packets) == 2 * len(contract.CHECKPOINTS_ET)

    again = Counting()
    run = runner.replay(tmp_path, [DAY], sessions=sessions, model=again, model_name="m",
                        variants=["bars", "full"], baselines=BASELINES)
    assert again.packets == [] and len(run.rows()) == expected
    report = runner.write_report(run, sessions)
    assert "Opening lab scorecard" in report
    assert json.loads((tmp_path / "report.json").read_text())["agents"]


def test_prior_decisions_are_the_models_own_earlier_answers(tmp_path, sessions):
    model = Counting()
    runner.replay(tmp_path, [DAY], sessions=sessions, model=model, model_name="m", variants=["market"])
    for i, packet in enumerate(model.packets):
        assert [p["checkpoint_et"] for p in packet["prior_decisions"]] == list(contract.CHECKPOINTS_ET[:i])


def test_changed_settings_refuse_the_same_run_directory(tmp_path, sessions):
    runner.replay(tmp_path, [DAY], sessions=sessions, model=Counting(), model_name="m", variants=["bars"])
    with pytest.raises(SystemExit):
        runner.replay(tmp_path, [DAY], sessions=sessions, model=Counting(), model_name="other", variants=["bars"])


def test_cost_cap_stops_new_calls(tmp_path, sessions):
    model = Counting(cost=0.05)
    messages = []
    run = runner.replay(tmp_path, [DAY], sessions=sessions, model=model, model_name="m",
                        variants=["bars"], max_cost_usd=0.1, log=messages.append)
    assert len(model.packets) == 2 and len(run.rows()) == 2
    assert messages and "cost cap" in messages[0]


def test_unknown_cost_stops_new_calls(tmp_path, sessions):
    model = Counting(cost=None)
    runner.replay(tmp_path, [DAY], sessions=sessions, model=model, model_name="m",
                  variants=["bars"], max_cost_usd=5.0, log=lambda _m: None)
    assert len(model.packets) == 1


def test_live_freezes_after_each_checkpoint_and_records_missed(tmp_path, sessions, monkeypatch):
    import research.opening_lab.context as context
    import research.opening_lab.live as live

    start = contract.et_datetime(DAY, "09:35").astimezone(contract.UTC) + timedelta(seconds=40)
    now = {"t": start}
    seen = []

    def fake_live_session(day, at, feed="sip"):
        seen.append(at)
        return sessions[DAY]

    monkeypatch.setattr(live, "live_session", fake_live_session)
    monkeypatch.setattr(context, "attach_context", lambda s, fetch=False, refresh=False: s)

    def sleep(seconds):
        now["t"] += timedelta(seconds=max(seconds, 0.001))

    class Clocked(Counting):
        def forecast(self, packet):
            now["t"] += timedelta(seconds=8)
            return super().forecast(packet)

    model = Clocked()
    run = runner.live(tmp_path, DAY, model=model, model_name="m", variant="full", baselines=BASELINES,
                      clock=lambda: now["t"], sleep=sleep, log=lambda _m: None)
    statuses = {r["checkpoint_et"]: r["status"] for r in run.rows() if r["agent"] == "m"}
    assert statuses["09:30"] == statuses["09:35"] == "missed"
    assert all(statuses[c] == "ok" for c in contract.CHECKPOINTS_ET[2:])
    # every packet was frozen at or after checkpoint + 5 s, never before
    for at, checkpoint in zip(seen, contract.CHECKPOINTS_ET[2:]):
        assert at.timestamp() >= contract.checkpoint_ts(DAY, checkpoint) + 5
    assert isinstance(start, datetime)


class Failing(Counting):
    def __init__(self, fail_at=None, cost=0.01):
        super().__init__(cost=cost)
        self.fail_at = fail_at

    def forecast(self, packet):
        if self.fail_at in (None, packet["checkpoint_et"]):
            self.packets.append(packet)
            return {"status": "error", "forecast": None, "error": "http_529", "cost_usd": None}
        return super().forecast(packet)


def test_resume_retries_failures_and_redoes_later_checkpoints(tmp_path, sessions):
    runner.replay(tmp_path, [DAY], sessions=sessions, model=Failing(fail_at="09:40"), model_name="m",
                  variants=["market"])
    fixed = Counting()
    run = runner.replay(tmp_path, [DAY], sessions=sessions, model=fixed, model_name="m", variants=["market"])
    # 09:40 is asked again; 09:45..10:00 are asked again because their prior_decisions now include it
    assert [p["checkpoint_et"] for p in fixed.packets] == list(contract.CHECKPOINTS_ET[2:])
    assert all(r["status"] == "ok" for r in run.rows())
    assert [p["checkpoint_et"] for p in fixed.packets[-1]["prior_decisions"]] == list(contract.CHECKPOINTS_ET[:-1])


def test_cost_cap_counts_spend_already_recorded(tmp_path, sessions):
    first = Counting(cost=0.05)
    runner.replay(tmp_path, [DAY], sessions=sessions, model=first, model_name="m", variants=["bars"],
                  max_cost_usd=0.1, log=lambda _m: None)
    second = Counting(cost=0.05)
    runner.replay(tmp_path, [DAY], sessions=sessions, model=second, model_name="m", variants=["bars"],
                  max_cost_usd=0.1, log=lambda _m: None)
    assert len(first.packets) == 2 and second.packets == []


def test_repeated_errors_stop_the_invocation(tmp_path, sessions):
    model = Failing()
    messages = []
    runner.replay(tmp_path, [f"{DAY}"], sessions=sessions, model=model, model_name="m",
                  variants=["bars", "market", "full"], workers=1, log=messages.append)
    # errors cost nothing but each chain keeps going; the breaker caps the invocation
    assert len(model.packets) <= runner.MAX_ERRORS_PER_INVOCATION
    assert len(model.packets) == 3 * len(contract.CHECKPOINTS_ET) or "provider errors" in messages[0]
