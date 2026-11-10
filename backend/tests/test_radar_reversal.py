"""Radar's gap-reversal rule ``radar-reversal-v0``, on invented fixture passes only (no recorded session, no trades)."""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.engine import radar_reversal, radar_rules
from app.engine.chart_math import ET
from app.engine.radar_store import RadarEvent

DAY = "2030-01-15"  # an invented Tuesday
OPEN = datetime(2030, 1, 15, 9, 30, tzinfo=ET)
STOCKS = ["AAA", "BBB", "CCC"]
UNIVERSE = {
    "version": "radar-universe-test",
    "symbols": [{"symbol": "SPY", "kind": "etf", "benchmark": True}]
    + [{"symbol": s, "kind": "stock", "benchmark": False, "sector": None} for s in STOCKS],
    "groups": [],
}
V0 = radar_reversal.V0


def reversal(opened=97.0, sign=1, dip=0.6, step=0.4, turn_at=3, cap=None):
    """Opens at ``opened``, runs ``dip`` further the gap's way by minute ``turn_at``, then turns ``step`` a minute the
    other way (held at ``cap`` once reached)."""
    def price(i):
        if i <= turn_at:
            p = opened - sign * dip * i / turn_at
        else:
            p = opened - sign * dip + sign * step * (i - turn_at)
            if cap is not None:
                p = min(p, cap) if sign > 0 else max(p, cap)
        return round(p, 4)
    return price


def flat(i):
    return 100.0


def _iso(value: datetime) -> str:
    return radar_rules._iso(value.timestamp())


def session(paths: dict, minutes: int = 40, first: int = 0, opens: dict | None = None):
    """Passes at 09:30 + ``first`` … one a minute; ``paths`` give each symbol's last by minute (default flat 100) and
    each row's ``open`` is the path at minute 0 unless ``opens`` says otherwise."""
    passes, quotes = [], {}
    for i in range(first, first + minutes):
        at = OPEN + timedelta(minutes=i)
        passes.append({"id": i + 1, "session_date": DAY, "started_at": _iso(at), "finished_at": _iso(at + timedelta(seconds=2)),
                       "universe_version": UNIVERSE["version"], "status": "ok"})
        quotes[i + 1] = {}
        for symbol in ["SPY"] + STOCKS:
            price = paths.get(symbol, flat)(i)
            quotes[i + 1][symbol] = {
                "symbol": symbol, "last": price, "prev_close": 100.0,
                "open": (opens or {}).get(symbol, paths.get(symbol, flat)(0)),
                "high": None, "low": None, "volume": 100_000 * (i + 1), "bid": price, "ask": price,
                "trade_time_ms": int((at + timedelta(seconds=0.5)).timestamp() * 1000), "retrieved_at": _iso(at + timedelta(seconds=1))}
    return passes, quotes


def run(paths, thresholds=V0, **kw):
    passes, quotes = session(paths, **kw)
    return radar_reversal.replay(UNIVERSE, passes, quotes, thresholds)


def at(minute: int) -> str:
    return _iso(OPEN + timedelta(minutes=minute, seconds=2))


# ------------------------------------------------------------------ trigger


def test_gap_down_that_reverses_up_fires_once_with_every_field():
    [event] = run({"AAA": reversal()})
    assert set(event) == set(RadarEvent.__annotations__)
    assert event["event_id"] == "rg0-2030-01-15-reversal-aaa-up-1"
    assert (event["kind"], event["direction"], event["rule_version"], event["symbols"]) == ("gap_reversal", "up", "radar-reversal-v0", ["AAA"])
    assert (event["benchmark"], event["group"], event["universe_version"]) == ("SPY", None, "radar-universe-test")
    # 96.4 at 09:33, then +0.4 a minute: 09:39 is the first pass 1.75% above the 97 open (98.8, +1.86%).
    assert event["first_seen_at"] == at(9)
    assert event["summary"] == ("AAA reversing up after a gap down: gapped −3.0% vs SPY, +1.9% vs SPY from the open, "
                                "+2.1% in the last 5 minutes")
    m = event["measures"]
    assert m["gap_relative_pct"] == -3.0 and m["open_relative_pct"] == pytest.approx(1.856, abs=1e-3)
    assert m["relative_pct"] == m["open_relative_pct"] == m["change_pct"] and m["benchmark_change_pct"] == 0.0
    assert m["five_minute_relative_pct"] == pytest.approx(2.066, abs=1e-3)  # 96.8 at 09:34 to 98.8
    assert m["day_change_pct"] == -1.2 and m["spy_day_change_pct"] == 0.0
    assert (m["open_price"], m["last_price"], m["extreme_price"], m["extreme_minutes_ago"]) == (97.0, 98.8, 96.4, 6)
    assert m["extreme_price"] < m["last_price"]
    # The opening (09:31), the low (09:33), five back (09:34) and now (09:39).
    assert [(e["symbol"], e["pass_id"]) for e in event["evidence"]] == [
        ("AAA", 2), ("SPY", 2), ("AAA", 4), ("SPY", 4), ("AAA", 5), ("SPY", 5), ("AAA", 10), ("SPY", 10)]
    assert event["coverage"] == {"passes_expected": 10, "passes_recorded": 10, "symbols_missing": []}
    assert event["chart"] == {"symbol": "AAA", "from": _iso(OPEN), "to": at(9)}


def test_gap_up_that_reverses_down_fires_down():
    [event] = run({"BBB": reversal(opened=103.0, sign=-1)})
    assert event["event_id"] == "rg0-2030-01-15-reversal-bbb-down-1" and event["direction"] == "down"
    assert event["first_seen_at"] == at(10)  # 100.8 at 09:40 is 2.1% under the 103 open; 101.2 at 09:39 was 1.7%
    assert event["summary"] == ("BBB reversing down after a gap up: gapped +3.0% vs SPY, −2.1% vs SPY from the open, "
                                "−1.9% in the last 5 minutes")
    m = event["measures"]
    assert m["gap_relative_pct"] == 3.0 and m["open_relative_pct"] < 0 and m["five_minute_relative_pct"] < 0
    assert (m["extreme_price"], m["extreme_minutes_ago"]) == (103.6, 7) and m["extreme_price"] > m["last_price"]


def test_everything_is_relative_to_spy():
    spy_down = lambda i: round(100.0 - 0.1 * i, 4)  # noqa: E731
    # SPY gapped down 3% with the stock: no gap against SPY, so no event however hard the stock reverses.
    assert run({"AAA": reversal(), "SPY": reversal(opened=97.0, dip=0, step=0)}) == []
    # A stock that only keeps pace with a falling SPY never reverses relative to it.
    assert run({"AAA": lambda i: round(97.0 * spy_down(i) / 100, 4), "SPY": spy_down}) == []


def test_extreme_can_equal_last_when_spy_falls_harder():
    """The rule is relative to SPY, so it can fire on a stock sitting at its session low while SPY drops faster: the
    extreme is then the last itself, not a level below it (the conditions do not rule this out)."""
    spy = lambda i: round(100.0 - 0.4 * i, 4)  # noqa: E731
    stock = lambda i: round(97.0 - 0.01 * i, 4)  # noqa: E731
    [event] = run({"AAA": stock, "SPY": spy}, opens={"SPY": 100.0})
    m = event["measures"]
    assert event["direction"] == "up" and m["extreme_price"] == m["last_price"] and m["extreme_minutes_ago"] == 0


# ------------------------------------------------------------------ each condition alone blocks it


@pytest.mark.parametrize("path,relaxed,why", [
    (reversal(opened=98.5), {"gap_relative_pct": 1.0}, "a 1.5% gap is under the 2% floor"),
    (reversal(cap=98.5), {"open_relative_pct": 1.5}, "held at +1.5% from the open, under 1.75%"),
    (reversal(step=0.09), {"five_minute_relative_pct": 0.4}, "a +0.45% five minutes is under 0.5%"),
    (reversal(dip=0.6, step=0.4, turn_at=118), {"window_minutes": 130}, "1.75% from the open only at 10:34"),
])
def test_one_condition_failing_blocks_it(path, relaxed, why):
    assert run({"AAA": path}, minutes=140) == [], why
    [event] = run({"AAA": path}, thresholds=replace(V0, **relaxed), minutes=140)  # that threshold alone held it back
    assert event["symbols"] == ["AAA"]


def test_nothing_after_minute_120():
    passes, quotes = session({}, minutes=140)
    assert radar_reversal.needed_pass_ids(passes, 120) == {p["id"] for p in passes[:121]}  # 11:30 still reads
    assert radar_reversal.needed_pass_ids(passes, 121) == set()  # 11:31 reads nothing
    assert radar_reversal.needed_pass_ids(passes, 5) == set()  # 09:35: no five-minute-back pass from 09:31 yet
    assert radar_reversal.needed_pass_ids(passes, 6) == {p["id"] for p in passes[:7]}


# ------------------------------------------------------------------ one per stock and side


def test_first_sighting_only_and_each_side_is_its_own_key():
    events = run({s: reversal() for s in STOCKS}, minutes=120)
    assert [e["symbols"][0] for e in events] == STOCKS and {e["first_seen_at"] for e in events} == {at(9)}
    passes, quotes = session({"AAA": reversal(opened=103.0, sign=-1)})
    up = {"symbols": ["AAA"], "direction": "up"}
    [down] = radar_reversal.detect(UNIVERSE, passes, 10, quotes, [up])  # an up event does not hold back a down one
    assert down["direction"] == "down"
    assert radar_reversal.detect(UNIVERSE, passes, 11, quotes, [up, down]) == []


# ------------------------------------------------------------------ missing or unusable quotes


def test_missing_or_unusable_quotes_give_no_reading():
    passes, quotes = session({"AAA": reversal()})
    del quotes[10]["SPY"]  # no SPY at 09:39: nothing that pass; 09:40 still qualifies
    [event] = radar_reversal.replay(UNIVERSE, passes, quotes)
    assert event["first_seen_at"] == at(10)

    passes, quotes = session({"AAA": reversal()})
    quotes[2]["AAA"]["trade_time_ms"] -= 600_000  # the 09:31 quote is stale: no opening price all session
    assert radar_reversal.replay(UNIVERSE, passes, quotes) == []

    passes, quotes = session({"AAA": reversal()})
    for rows in quotes.values():
        rows["AAA"]["open"] = None  # no open field: no gap and no move from the open
    assert radar_reversal.replay(UNIVERSE, passes, quotes) == []

    passes, quotes = session({"AAA": reversal()})
    quotes[5]["AAA"]["last"] = 0  # 09:34 unusable: 09:39 has no five-minute start; 09:40 reads 09:35
    [event] = radar_reversal.replay(UNIVERSE, passes, quotes)
    assert event["first_seen_at"] == at(10)

    assert run({"AAA": reversal()}, first=2) == []  # recording started 09:32: the 09:31 opening pass is missing


def test_another_universe_version_is_not_read():
    passes, quotes = session({"AAA": reversal()})
    passes[1]["universe_version"] = "older"  # the 09:31 pass came from another roster
    assert radar_reversal.replay(UNIVERSE, passes, quotes) == []


# ------------------------------------------------------------------ causality


def test_no_future_pass_is_read():
    passes, quotes = session({"AAA": reversal()})
    [event] = radar_reversal.replay(UNIVERSE, passes, quotes)
    fired = next(i for i, p in enumerate(passes) if p["finished_at"] == event["first_seen_at"])
    for p in passes[fired + 1:]:
        for q in quotes[p["id"]].values():
            q["last"], q["open"] = 1.0, 1.0
    assert radar_reversal.replay(UNIVERSE, passes, quotes) == [event]
    assert radar_reversal.replay(UNIVERSE, passes[:fired + 1], quotes) == [event]
    assert radar_reversal.replay(UNIVERSE, passes[:fired], quotes) == []
    assert max(radar_reversal.needed_pass_ids(passes, fired)) == passes[fired]["id"]


def test_replay_equals_step_by_step_detect_on_the_needed_quotes_only():
    passes, quotes = session({"AAA": reversal(), "BBB": reversal(opened=103.0, sign=-1), "CCC": reversal(step=0.09)},
                             minutes=130)
    saved = []
    for end in range(len(passes)):
        needed = radar_reversal.needed_pass_ids(passes, end)
        saved += radar_reversal.detect(UNIVERSE, passes, end, {i: quotes[i] for i in needed}, saved)
    assert saved == radar_reversal.replay(UNIVERSE, passes, quotes)
    assert [e["event_id"] for e in saved] == ["rg0-2030-01-15-reversal-aaa-up-1", "rg0-2030-01-15-reversal-bbb-down-1"]


# ------------------------------------------------------------------ identity and switch


def test_event_id_and_is_reversal():
    assert radar_reversal.event_id(DAY, "BRK.B", "down") == "rg0-2030-01-15-reversal-brk-b-down-1"
    assert radar_reversal.VERSIONS == {"radar-reversal-v0": V0}
    assert (V0.window_minutes, V0.gap_relative_pct, V0.open_relative_pct, V0.five_minute_relative_pct) == (120, 2.0, 1.75, 0.5)
    assert radar_reversal.is_reversal({"rule_version": "radar-reversal-v0"})
    assert not radar_reversal.is_reversal({"rule_version": "radar-dip-v0"}) and not radar_reversal.is_reversal({})


@pytest.mark.parametrize("value,mode", [("", "off"), ("record", "record"), ("ALERT", "alert"), ("on", "off")])
def test_mode_from_env(monkeypatch, value, mode):
    monkeypatch.setenv("RADAR_REVERSAL_RULES", value)
    assert radar_reversal.mode_from_env() == mode


def test_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("RADAR_REVERSAL_RULES", raising=False)
    assert radar_reversal.mode_from_env() == "off"
