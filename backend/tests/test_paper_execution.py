"""Paper fills and exits for Practice plans (A2): the pure reducer, from supplied bars.

The first test is ``docs/agent/practice-policy.md``'s worked example, to the cent.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.engine import paper_execution as px

ET = ZoneInfo("America/New_York")


def at(day, hour, minute, second=0, month=10):
    return int(datetime(2026, month, day, hour, minute, second, tzinfo=ET).timestamp())


def plan(**over):
    result = {"trigger_level": 100.0, "stop": 98.0, "target": 104.0, "entry_guard": {"min": 100.0, "max": 101.0},
              "expiry": "2026-10-07T15:15:00-04:00", "max_holding_sessions": 2, "initial_risk_per_share": 2.0,
              "cost_model": {"version": "p0-cost-v1", "slippage_bps": 1.0, "slippage_per_share": 0.01}}
    result.update(over)
    return result


TERMS = px.terms_from_plan(plan())
OCT = [px.Session("2026-10-07", at(7, 9, 30), at(7, 16, 0)), px.Session("2026-10-08", at(8, 9, 30), at(8, 16, 0))]
# Thanksgiving week: Wednesday is a full day, Friday closes at 13:00.
NOV_TERMS = px.terms_from_plan(plan(expiry="2026-11-25T15:15:00-05:00"))
NOV = [px.Session("2026-11-25", at(25, 9, 30, month=11), at(25, 16, 0, month=11)),
       px.Session("2026-11-27", at(27, 9, 30, month=11), at(27, 13, 0, month=11))]


def bar(start, o, high=None, low=None, close=None):
    return {"start": start, "o": o, "h": o if high is None else high, "l": o if low is None else low,
            "c": o if close is None else close}


def flat(first, last, price=100.5):
    """One flat bar for every minute from ``first`` up to, not including, ``last``."""
    return [bar(t, price) for t in range(first, last, 60)]


def bar15(end, close):
    return {"start": end - 900, "end": end, "close": close}


def armed(terms=TERMS, when=at(7, 8, 50)):
    return px.fold([px.arm_event(when)])


def triggered(close=100.2, end=at(7, 10, 15), detected=at(7, 10, 15, 35), terms=TERMS, when=at(7, 8, 50)):
    events = px.watch(armed(terms, when), terms, [bar15(end, close)], detected)
    assert [e["type"] for e in events] == ["trigger"]
    return px.fold([px.arm_event(when)] + events)


def nov_triggered():
    return triggered(end=at(25, 10, 15, month=11), detected=at(25, 10, 15, 35, month=11), terms=NOV_TERMS,
                     when=at(25, 8, 50, month=11))


def run(state, bars, sessions=OCT, terms=TERMS, **kwargs):
    events = px.advance(state, terms, bars, sessions, **kwargs)
    return events, px.fold(_history(state) + events)


def _history(state):
    return [e for e in (_armed(state), state.trigger, state.entry, state.exit, state.ended) if e]


def _armed(state):
    return px.arm_event(state.armed_at)


# ---------------------------------------------------------------- the worked example


def test_worked_example_matches_the_policy_to_the_cent():
    state = triggered()
    bars = [bar(at(7, 10, 16), 100.50, 100.60, 100.40, 100.50), bar(at(7, 10, 17), 100.50, 104.10, 100.50, 104.0)]
    events, state = run(state, bars)
    assert [e["type"] for e in events] == ["entry", "exit"]
    base, triple = px.outcome(state, TERMS), px.outcome(state, TERMS, 3)
    assert base["entry_fill"] == pytest.approx(100.52005)
    assert base["exit_fill"] == pytest.approx(103.97960)
    assert base["net_per_share"] == pytest.approx(3.45955)
    assert base["planned_r"] == pytest.approx(1.729775)
    assert base["entry_to_stop_exposure"] == pytest.approx(2.52005)
    assert triple["cost_version"] == "p0-cost-v1-x3"
    assert triple["entry_fill"] == pytest.approx(100.56015)
    assert triple["exit_fill"] == pytest.approx(103.93880)
    assert triple["net_per_share"] == pytest.approx(3.37865)
    assert triple["planned_r"] == pytest.approx(1.689325)
    assert triple["entry_to_stop_exposure"] == pytest.approx(2.56015)
    assert events[0]["fill"] == pytest.approx(base["entry_fill"]) and events[1]["fill"] == pytest.approx(base["exit_fill"])


def test_tripling_the_costs_does_not_change_the_base_outcome():
    _, state = run(triggered(), [bar(at(7, 10, 16), 100.5), bar(at(7, 10, 17), 100.5, 104.1, 100.5, 104.0)])
    before = px.outcome(state, TERMS)
    px.outcome(state, TERMS, 3)
    assert px.outcome(state, TERMS) == before


# ---------------------------------------------------------------- the trigger


def test_a_close_exactly_at_the_trigger_does_not_fire():
    assert px.watch(armed(), TERMS, [bar15(at(7, 10, 15), 100.0)], at(7, 10, 15, 35)) == []


def test_a_bar_that_closed_before_arming_cannot_trigger():
    assert px.watch(armed(when=at(7, 10, 20)), TERMS, [bar15(at(7, 10, 15), 101.0)], at(7, 10, 21)) == []


def test_a_bar_that_began_before_arming_but_closed_after_it_can():
    state = armed(when=at(7, 10, 5))
    assert [e["type"] for e in px.watch(state, TERMS, [bar15(at(7, 10, 15), 100.3)], at(7, 10, 15, 30))] == ["trigger"]


def test_a_bar_not_yet_closed_at_detection_is_not_judged():
    assert px.watch(armed(), TERMS, [bar15(at(7, 10, 30), 101.0)], at(7, 10, 29)) == []


def test_a_trigger_seen_after_the_allowed_delay_is_missed_not_backdated():
    state = armed()
    on_time = px.watch(state, TERMS, [bar15(at(7, 10, 15), 100.5)], at(7, 10, 15) + px.MAX_DETECTION_DELAY)
    late = px.watch(state, TERMS, [bar15(at(7, 10, 15), 100.5)], at(7, 10, 15) + px.MAX_DETECTION_DELAY + 1)
    assert [e["type"] for e in on_time] == ["trigger"]
    assert [e["type"] for e in late] == ["missed_trigger"] and late[0]["reason"] == "detected_late"
    ended = px.fold([px.arm_event(1)] + late)
    assert ended.status == "missed" and px.advance(ended, TERMS, flat(at(7, 10, 16), at(7, 10, 30)), OCT) == []


def test_the_last_close_at_expiry_may_trigger_but_a_later_one_may_not():
    state = armed()
    assert [e["type"] for e in px.watch(state, TERMS, [bar15(at(7, 15, 15), 100.5)], at(7, 15, 15, 40))] == ["trigger"]
    assert px.watch(state, TERMS, [bar15(at(7, 15, 30), 100.5)], at(7, 15, 31)) == []


def test_only_the_first_qualifying_close_decides():
    events = px.watch(armed(), TERMS, [bar15(at(7, 10, 30), 100.9), bar15(at(7, 10, 15), 100.4)], at(7, 10, 31))
    assert len(events) == 1 and events[0]["bar_end"] == at(7, 10, 15) and events[0]["delay_seconds"] == 16 * 60


def test_an_untriggered_plan_expires_only_after_the_last_acceptable_detection():
    state = armed()
    assert px.check_expiry(state, TERMS, at(7, 15, 20)) == []
    expired = px.check_expiry(state, TERMS, at(7, 15, 20, 1))
    assert [e["type"] for e in expired] == ["expired"] and px.fold([px.arm_event(1)] + expired).status == "expired"
    assert px.check_expiry(triggered(), TERMS, at(7, 16, 0)) == []


# ---------------------------------------------------------------- the entry


def test_entry_waits_for_the_first_minute_starting_after_detection():
    state = triggered(detected=at(7, 10, 15, 35))
    early = [bar(at(7, 10, 15), 100.5)]  # started before detection: not eligible
    assert px.advance(state, TERMS, early, OCT) == []
    events, state = run(state, early + [bar(at(7, 10, 16), 100.5)])
    assert events[0]["type"] == "entry" and events[0]["bar_start"] == at(7, 10, 16)


def test_detection_exactly_on_a_minute_waits_for_the_next_minute():
    state = triggered(detected=at(7, 10, 16, 0))
    assert px.advance(state, TERMS, [bar(at(7, 10, 16), 100.5)], OCT) == []
    assert px.advance(state, TERMS, [bar(at(7, 10, 17), 100.5)], OCT)[0]["bar_start"] == at(7, 10, 17)


@pytest.mark.parametrize("open_price,reason", [
    (98.0, "at_or_below_stop"), (97.0, "at_or_below_stop"), (104.0, "at_or_above_target"), (105.0, "at_or_above_target"),
    (101.5, "above_guard"), (99.5, "below_guard"),
])
def test_entry_is_refused_outside_the_stop_target_and_guard(open_price, reason):
    events, state = run(triggered(), [bar(at(7, 10, 16), open_price, max(open_price, 106), min(open_price, 97), open_price)])
    assert [e["type"] for e in events] == ["entry_rejected"] and events[0]["reason"] == reason
    assert state.status == "rejected" and px.outcome(state, TERMS) is None


def test_the_guard_edges_are_inside_the_guard():
    for price in (100.0, 101.0):
        events, _ = run(triggered(), [bar(at(7, 10, 16), price)])
        assert events[0]["type"] == "entry"


def test_a_missing_entry_minute_leaves_the_plan_unresolved_not_filled_late():
    events, state = run(triggered(), [bar(at(7, 10, 17), 100.5)])
    assert [e["type"] for e in events] == ["unresolved"] and events[0]["stage"] == "entry"
    assert (events[0]["from_start"], events[0]["to_start"]) == (at(7, 10, 16), at(7, 10, 17))
    assert state.status == "unresolved" and state.entry is None


# ---------------------------------------------------------------- the exits


def entered(extra, sessions=OCT):
    return run(triggered(), [bar(at(7, 10, 16), 100.5)] + extra, sessions)


def test_a_touch_of_the_stop_exits_at_the_stop_with_adverse_slippage():
    events, state = entered([bar(at(7, 10, 17), 100.5, 100.6, 97.9, 98.5)])
    exit_ = events[-1]
    assert exit_["kind"] == "stop" and exit_["reference"] == 98.0 and not exit_["gap"] and not exit_["ambiguous"]
    assert exit_["fill"] == pytest.approx(98.0 - 0.0098 - 0.01)


def test_a_bar_that_opens_through_the_stop_exits_at_that_open():
    events, state = entered([bar(at(7, 10, 17), 100.5), bar(at(7, 10, 18), 97.5, 97.6, 97.0, 97.2)])
    exit_ = events[-1]
    assert exit_["kind"] == "stop" and exit_["gap"] and exit_["reference"] == 97.5
    assert exit_["fill"] == pytest.approx(97.5 - 0.00975 - 0.01)
    result = px.outcome(state, TERMS)
    assert result["net_per_share"] == pytest.approx(97.48025 - 100.52005) and result["planned_r"] == pytest.approx(-1.5199)


def test_a_bar_touching_both_stop_and_target_takes_the_stop_and_is_flagged():
    events, _ = entered([bar(at(7, 10, 17), 100.5, 105.0, 97.0, 101.0)])
    assert events[-1]["kind"] == "stop" and events[-1]["ambiguous"] and events[-1]["reference"] == 98.0


def test_a_target_touch_fills_the_target_less_slippage():
    events, _ = entered([bar(at(7, 10, 17), 100.5, 104.0, 100.5, 103.0)])
    assert events[-1]["kind"] == "target" and events[-1]["reference"] == 104.0
    assert events[-1]["fill"] == pytest.approx(103.9796)


def test_a_bar_that_opens_above_the_target_still_fills_no_better_than_the_target():
    events, _ = entered([bar(at(7, 10, 17), 106.0, 107.0, 105.5, 106.5)])
    assert events[-1]["kind"] == "target" and events[-1]["gap"] and events[-1]["reference"] == 104.0


def test_the_stop_and_target_rest_through_the_entry_minute():
    events, state = run(triggered(), [bar(at(7, 10, 16), 100.5, 100.6, 97.9, 98.5)])
    assert [e["type"] for e in events] == ["entry", "exit"] and events[1]["kind"] == "stop"
    assert events[1]["bar_start"] == events[0]["bar_start"] and state.status == "closed"


def test_a_position_stays_open_through_quiet_minutes():
    events, state = entered(flat(at(7, 10, 17), at(7, 11, 0)))
    assert [e["type"] for e in events] == ["entry"] and state.status == "open"


def test_a_missing_minute_while_holding_leaves_the_position_unresolved():
    events, state = entered(flat(at(7, 10, 17), at(7, 10, 20)) + flat(at(7, 10, 21), at(7, 10, 23)))
    assert events[-1]["type"] == "unresolved" and events[-1]["stage"] == "hold"
    assert (events[-1]["from_start"], events[-1]["to_start"]) == (at(7, 10, 20), at(7, 10, 21))
    assert state.status == "unresolved" and state.exit is None and px.outcome(state, TERMS) is None


def test_the_time_exit_is_the_second_sessions_last_minute_close():
    day_one = flat(at(7, 10, 17), at(7, 16, 0))
    day_two = flat(at(8, 9, 30), at(8, 15, 59)) + [bar(at(8, 15, 59), 100.8, 101.0, 100.7, 100.9)]
    events, state = entered(day_one + day_two)
    exit_ = events[-1]
    assert exit_["kind"] == "time" and exit_["bar_start"] == at(8, 15, 59) and exit_["at"] == at(8, 16, 0)
    assert exit_["reference"] == 100.9 and exit_["fill"] == pytest.approx(100.9 - 0.01009 - 0.01)
    assert state.status == "closed"


def test_the_entry_session_is_session_one_so_day_one_alone_does_not_time_exit():
    events, state = entered(flat(at(7, 10, 17), at(7, 16, 0)))
    assert state.status == "open" and [e["type"] for e in events] == ["entry"]


def test_an_early_close_ends_the_hold_at_its_own_last_minute():
    state = nov_triggered()
    day_one = flat(at(25, 10, 16, month=11), at(25, 16, 0, month=11))
    day_two = flat(at(27, 9, 30, month=11), at(27, 12, 59, month=11)) + [bar(at(27, 12, 59, month=11), 101.0)]
    events, state = run(state, day_one + day_two, NOV, NOV_TERMS)
    assert events[-1]["kind"] == "time" and events[-1]["bar_start"] == at(27, 12, 59, month=11)
    assert events[-1]["at"] == at(27, 13, 0, month=11)


def test_a_holiday_between_sessions_is_not_a_missing_minute():
    day_one = flat(at(25, 10, 16, month=11), at(25, 16, 0, month=11))
    state = nov_triggered()
    events, state = run(state, day_one + flat(at(27, 9, 30, month=11), at(27, 10, 0, month=11)), NOV, NOV_TERMS)
    assert state.status == "open" and [e["type"] for e in events] == ["entry"]


def test_extended_hours_minutes_are_ignored():
    pre = [bar(at(8, 9, 29), 90.0, 90.0, 80.0, 90.0)]  # premarket, below the stop
    state = triggered()
    events, state = run(state, [bar(at(7, 10, 16), 100.5)] + flat(at(7, 10, 17), at(7, 16, 0)) + [bar(at(7, 16, 0), 90.0)] + pre
                        + flat(at(8, 9, 30), at(8, 10, 0)))
    assert state.status == "open"


# ---------------------------------------------------------------- replay and restart


def all_bars():
    return ([bar(at(7, 10, 16), 100.5)] + flat(at(7, 10, 17), at(7, 16, 0))
            + flat(at(8, 9, 30), at(8, 11, 0)) + [bar(at(8, 11, 0), 100.5, 104.2, 100.5, 104.0)])


def test_judging_the_same_bars_again_adds_nothing():
    events, state = run(triggered(), all_bars())
    assert [e["type"] for e in events] == ["entry", "exit"] and events[1]["kind"] == "target"
    assert px.advance(state, TERMS, all_bars(), OCT) == []
    assert px.watch(state, TERMS, [bar15(at(7, 10, 45), 101.0)], at(7, 10, 46)) == []


def test_replay_in_chunks_with_a_rebuilt_projection_matches_a_single_pass():
    bars = all_bars()
    single, _ = run(triggered(), bars)
    collected, state = [], triggered()
    for cut in (1, 5, 200, 380, 400, len(bars)):
        events = px.advance(state, TERMS, bars[:cut], OCT)  # a restart: the projection is rebuilt from stored events only
        collected += events
        state = px.fold(_history(state) + events)
    assert collected == single


def test_a_restart_replay_marks_what_it_reconstructed():
    events, _ = run(triggered(), [bar(at(7, 10, 16), 100.5), bar(at(7, 10, 17), 100.5, 104.0, 100.5, 104.0)], reconstructed=True)
    assert all(e.get("reconstructed") is True for e in events) and len(events) == 2


def test_an_ended_plan_ignores_further_bars():
    state = run(triggered(), [bar(at(7, 10, 16), 99.0)])[1]
    assert state.status == "rejected" and px.advance(state, TERMS, flat(at(7, 10, 17), at(7, 10, 30)), OCT) == []


# ---------------------------------------------------------------- bad input


def test_bad_bars_are_refused_not_judged():
    state = triggered()
    for bad in (bar(at(7, 10, 16), 100.5, 100.0, 101.0, 100.5), bar(at(7, 10, 16), float("nan")), bar(at(7, 10, 16), -1.0)):
        with pytest.raises(ValueError):
            px.advance(state, TERMS, [bad], OCT)
    with pytest.raises(ValueError):
        px.advance(state, TERMS, [bar(at(7, 10, 16), 100.5), bar(at(7, 10, 16), 100.5)], OCT)


def test_an_unpublished_second_session_still_judges_stops_but_never_time_exits():
    events, state = run(triggered(), [bar(at(7, 10, 16), 100.5)] + flat(at(7, 10, 17), at(7, 16, 0)), OCT[:1])
    assert state.status == "open"
    events, state = run(state, [bar(at(7, 10, 16), 100.5)] + flat(at(7, 10, 17), at(7, 16, 0))
                        + [bar(at(8, 9, 30), 97.0)], OCT[:1])
    assert events == [] and state.status == "open"  # the uncovered session's minute is not judged
    events, _ = run(state, [bar(at(7, 10, 16), 100.5), bar(at(7, 10, 17), 100.5, 100.5, 97.5, 98.0)], OCT[:1])
    assert events[-1]["kind"] == "stop"


def test_a_split_ends_a_position_as_unresolved():
    _, state = run(triggered(), [bar(at(7, 10, 16), 100.5)])
    events = px.end_unresolved(state, at(8, 9, 30), "split")
    assert [e["type"] for e in events] == ["unresolved"] and events[0]["reason"] == "split"
    assert px.end_unresolved(px.fold([px.arm_event(1)]), 0, "split") == []


def test_a_plan_a1_would_have_refused_is_refused():
    for over in ({"stop": 101.0}, {"cost_model": {"version": "v", "slippage_bps": -1, "slippage_per_share": 0}},
                 {"expiry": "2026-10-07T15:15:00"}, {"max_holding_sessions": 0}):
        with pytest.raises(ValueError):
            px.terms_from_plan(plan(**over))
    with pytest.raises(ValueError):
        px.terms_from_plan({"trigger_level": 100})
