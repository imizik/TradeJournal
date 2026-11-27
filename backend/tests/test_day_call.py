"""The day call (app/engine/day_call.py): an opening call, code-run flip checks, re-asks on its own thread, a paper score."""
from datetime import datetime

import pytest

from app.ai import api_runner
from app.engine import day_call
from app.engine.chart_math import ET

MON = (2026, 11, 30)


def at(hour: int, minute: int = 0) -> float:
    return datetime(*MON, hour, minute, tzinfo=ET).timestamp()


def bars(prices: list[float], start=(9, 30)) -> list[dict]:
    t0 = at(*start)
    return [{"time": t0 + 60 * i, "open": p, "high": p + 0.1, "low": p - 0.1, "close": p, "volume": 1000} for i, p in enumerate(prices)]


def regime(spy=0.4, rsp=0.1, vix=15.0) -> dict:
    return {"radar": {"state": "ok", "indices": {"SPY": {"day_pct": spy}, "QQQ": {"day_pct": 0.6}, "IWM": {"day_pct": -0.2},
                                                 "RSP": {"day_pct": rsp}}},
            "vix": {"state": "ok", "last": vix}, "us10y": {"state": "ok", "yield_pct": 4.1}, "macro": {"state": "ok", "events": []}}


def test_spy_facts_and_metrics_come_from_the_session_so_far():
    found = day_call.spy_facts(bars([100.0] * 15 + [101.0] * 20 + [999.0]), datetime(*MON).date(), 10 * 60 + 5)
    assert found["state"] == "ok" and found["minutes"] == 35  # the 10:05 bar has not closed: never counted
    assert (found["price"], found["open"], found["or15_high"], found["or15_low"]) == (101.0, 100.0, 100.1, 99.9)
    assert found["vwap"] == pytest.approx(100.57, abs=0.01) and found["vs_vwap_pct"] > 0
    assert found["last_30m_pct"] == 1.0
    values = day_call.metrics({"spy": found, "regime": regime()})
    assert values["spy_price"] == 101.0 and values["rsp_minus_spy_pct"] == pytest.approx(-0.3) and values["vix"] == 15.0
    # Radar or VIX off: unknown, so no flip check on them can trip.
    blank = day_call.metrics({"spy": {"state": "unavailable"}, "regime": {"radar": {"state": "off"}, "vix": {"state": "unavailable"}}})
    assert set(blank.values()) == {None}
    assert day_call.tripped({"flips": [{"metric": "vix", "op": "above", "value": 1, "why": ""}]}, blank) == []


def test_clean_keeps_only_known_calls_and_checks():
    out = day_call.clean({"call": "moon", "confidence": 7, "read": "x", "changed": "",
                          "flips": [{"metric": "spy_price", "op": "below", "value": 99, "why": "loses the open"},
                                    {"metric": "made_up", "op": "below", "value": 1, "why": ""},
                                    {"metric": "vix", "op": "sideways", "value": 1, "why": ""}] + [
                                       {"metric": "vix", "op": "above", "value": v, "why": ""} for v in (18, 19, 20)]})
    assert out["call"] == "mixed" and out["confidence"] == 1.0 and out["changed"] is None
    assert [f["metric"] for f in out["flips"]] == ["spy_price", "vix", "vix"]


def test_score_judges_each_call_until_the_next_and_skips_mixed():
    calls = [{"time_et": "09:45", "call": "risk_on", "spy_price": 100.0}, {"time_et": "11:00", "call": "mixed", "spy_price": 101.0},
             {"time_et": "13:00", "call": "risk_off", "spy_price": 100.5}]
    out = day_call.score(calls, 101.5)
    assert [r["right"] for r in out["calls"]] == [True, None, False]
    assert (out["scored"], out["right"], out["opening_right"]) == (2, 1, True)


class Calendar:
    def __init__(self):
        self.days = {}

    def hours(self, day):
        return self.days.get(day, {"status": "open", "open": 570, "close": 960}) if day.weekday() < 5 else {"status": "closed"}


class World:
    """A pinned clock, SPY's price and the facts the pass reads, and a scripted Claude."""

    def __init__(self, answers):
        self.t = at(9, 40)
        self.price = 100.0
        self.vix = 15.0
        self.answers = list(answers)
        self.asked: list[str] = []

    def facts(self, now):
        moment = datetime.fromtimestamp(now, ET)
        spy = {"state": "ok", "price": self.price, "vs_vwap_pct": 0.1} if self.price else {"state": "unavailable"}
        return {"time_et": moment.strftime("%H:%M"), "spy": spy,
                "regime": regime(vix=self.vix)}

    def ask(self, system, message):
        self.asked.append(message)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer, 0.03, "claude-sonnet-5-5"

    def today_minutes(self, symbol, now):
        return bars([100.0] * 389 + [self.price])

    def step(self, calls, minutes=1):
        self.t += 60 * minutes
        calls.run()


def answer(call, flips=(), changed=None):
    return {"call": call, "confidence": 0.6, "read": f"{call} read", "changed": changed,
            "flips": [{"metric": m, "op": op, "value": v, "why": "w"} for m, op, v in flips]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(day_call, "ROOT", tmp_path)
    pinged = []
    monkeypatch.setattr(day_call.DayCalls, "_ping", lambda self, day, n, prev, entry, now: pinged.append((prev, entry["call"])))
    monkeypatch.setenv("DAY_CALL_PINGS", "true")
    w = World([answer("risk_on", [("vix", "above", 17)]), answer("risk_off", [("spy_price", "above", 101)], changed="VIX jumped")])
    w.pinged = pinged
    w.calendar = Calendar()
    w.calls = day_call.DayCalls(w.calendar, feed=w, clock=lambda: w.t, ask=w.ask, facts=w.facts, background=False)
    return w


def test_the_opening_call_then_a_confirmed_flip_check_asks_again_with_the_thread(world):
    calls = world.calls
    world.step(calls)  # 09:41: too early
    assert world.asked == []
    world.step(calls, 5)  # 09:46: the opening call
    assert len(world.asked) == 1 and "Make the opening call" in world.asked[0]
    state = day_call.load("2026-11-30")
    assert state["calls"][0]["call"] == "risk_on" and state["calls"][0]["spy_price"] == 100.0
    world.vix = 18.0  # the flip check holds...
    world.step(calls)
    world.step(calls)  # ...twice in a row, but inside the 20 minutes since the call
    assert len(world.asked) == 1
    world.step(calls, 20)
    assert len(world.asked) == 2
    assert "Your calls so far today" in world.asked[1] and "vix above 17" in world.asked[1]
    assert "flip check held for 2 checks: vix above 17" in world.asked[1]
    assert [c["call"] for c in day_call.load("2026-11-30")["calls"]] == ["risk_on", "risk_off"]
    assert world.pinged == [("risk_on", "risk_off")]


def test_a_check_that_holds_once_is_noise_and_a_sharp_move_asks_on_its_own(world):
    calls = world.calls
    world.answers.insert(1, answer("risk_on", [("vix", "above", 30)]))
    world.step(calls, 6)
    world.step(calls, 25)
    world.vix = 18.0
    world.step(calls)
    world.vix = 15.0
    world.step(calls)
    assert len(world.asked) == 1  # held one check, then not: no ask
    world.price = 100.6  # SPY 0.6% from the last call's price
    world.step(calls)
    assert len(world.asked) == 2 and "SPY moved +0.60% since the last call" in world.asked[1]
    assert world.pinged == []  # held the call: no ping


def test_no_call_without_spy_or_a_calendar_or_after_the_opening_window(world):
    world.price = None
    world.step(world.calls, 6)
    assert world.asked == []  # SPY's minutes unreadable: retried next check
    world.price = 100.0
    world.calendar.hours = lambda day: None  # calendar down: never a paid call on the clock's guess
    world.step(world.calls)
    assert world.asked == []
    world.calendar = world.calls.calendar = Calendar()
    world.t = at(10, 40)  # a process that starts late makes no opening call
    world.calls.run()
    assert world.asked == []
    world.calendar.days[datetime(*MON).date()] = {"status": "open", "open": 570, "close": 780}  # an early close
    assert world.calls._regular(datetime(*MON).date()) == (570, 780)


def test_failed_asks_stop_the_day_after_a_few(world):
    world.answers[:] = [api_runner.ApiCallFailed("max_tokens")] * 5
    for _ in range(5):
        world.step(world.calls, 11)
    assert len(world.asked) == day_call.MAX_FAILURES
    assert day_call.load("2026-11-30")["stopped"] == "3 asks failed today."


def test_a_damaged_score_file_never_breaks_the_record(world):
    day_call.ROOT.mkdir(parents=True, exist_ok=True)
    (day_call.ROOT / "2026-11-20.json").write_text('{"day": "2026-11-20", "calls": [], "score": {"close": 1}}')
    (day_call.ROOT / "2026-11-21.json").write_text('{"score": "x"}')
    assert day_call.record()["days"] == 1 and day_call.record()["scored"] == 0


def test_the_monitor_pass_never_waits_on_the_reads_or_the_ask(world):
    import threading
    gate = threading.Event()
    slow = day_call.DayCalls(world.calendar, feed=world, clock=lambda: world.t, ask=world.ask,
                             facts=lambda now: (gate.wait(5), world.facts(now))[1])
    world.t = at(9, 46)
    started = datetime.now()
    slow.run()
    assert (datetime.now() - started).total_seconds() < 1 and world.asked == []
    slow.run()  # still busy: no second worker
    gate.set()
    slow._asking.join(5)
    assert len(world.asked) == 1


def test_no_key_or_a_spent_month_stops_the_day_and_a_failed_ask_waits(world):
    world.answers[:] = [api_runner.ApiCallFailed("timeout"), api_runner.ApiUnavailable("No ANTHROPIC_API_KEY")]
    world.step(world.calls, 6)
    world.step(world.calls)
    assert len(world.asked) == 1  # waits RETRY_SECONDS after a failure
    world.step(world.calls, 10)
    assert len(world.asked) == 2 and day_call.load("2026-11-30")["stopped"].startswith("No ANTHROPIC_API_KEY")
    world.step(world.calls, 30)
    assert len(world.asked) == 2


def test_the_close_scores_the_day_and_the_view_carries_the_record(world, monkeypatch):
    calls = world.calls
    world.step(calls, 6)
    world.price = 101.0
    world.t = at(16, 1)
    calls.run()
    state = day_call.load("2026-11-30")
    assert state["score"]["right"] == 1 and state["score"]["close"] == 101.0
    monkeypatch.setenv("DAY_CALL_ENABLED", "true")
    shown = day_call.view(at(16, 5))
    assert shown["enabled"] and shown["calls"][0]["call"] == "risk_on"
    assert shown["record"] == {"days": 1, "scored": 1, "right": 1, "hit_rate": 1.0, "opening_calls": 1, "opening_right": 1}
    world.t = at(9, 46) + 86400 * 5  # a Saturday: nothing runs
    calls.run()
    assert len(world.asked) == 1


def test_off_by_default():
    assert not day_call.enabled() and not day_call.pings_enabled()
