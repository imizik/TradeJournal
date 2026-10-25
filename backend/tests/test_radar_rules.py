"""Radar step 2: the provisional ``radar-rules-v0`` alert rules, on invented fixture passes only."""
from datetime import datetime, timedelta

import pytest

from app.engine import radar_news, radar_rules
from app.engine.chart_math import ET
from app.engine.radar_runner import RadarRunner
from app.engine.radar_store import RETENTION_SESSIONS, RadarEvent, RadarStore
from app.engine.tradier import TradierQuote

DAY = "2030-01-15"  # an invented Tuesday; never a recorded session
OPEN = datetime(2030, 1, 15, 9, 30, tzinfo=ET)
STOCKS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
UNIVERSE = {
    "version": "radar-universe-test",
    "symbols": [{"symbol": "SPY", "kind": "etf", "benchmark": True}, {"symbol": "XLK", "kind": "etf", "benchmark": True}]
    + [{"symbol": s, "kind": "stock", "benchmark": False, "sector": "XLK"} for s in STOCKS],
    "groups": [{"name": "Test group", "members": ["AAA", "BBB", "CCC", "DDD", "EEE"]}],
}


def _iso(value: datetime) -> str:
    return radar_rules._iso(value.timestamp())


def steps(*points):
    """Price path: 100 until the first (minute, price), then each price from its minute on."""
    def price(i):
        value = 100.0
        for minute, p in points:
            if i >= minute:
                value = p
        return value
    return price


def _pass(i: int) -> dict:
    at = OPEN + timedelta(minutes=i)
    return {"id": i, "session_date": DAY, "started_at": _iso(at), "finished_at": _iso(at + timedelta(seconds=2)),
            "universe_version": "radar-universe-test", "status": "ok"}


def _quote(symbol: str, i: int, price: float, stale=False) -> dict:
    at = OPEN + timedelta(minutes=i, seconds=1)
    trade = at - timedelta(minutes=10 if stale else 0, seconds=1)
    return {"symbol": symbol, "last": price, "prev_close": 100.0, "open": 100.0, "high": price, "low": price,
            "volume": 1000, "bid": price, "ask": price, "trade_time_ms": int(trade.timestamp() * 1000),
            "retrieved_at": _iso(at)}


def session(paths: dict, minutes: int = 70, stale=()) -> tuple[list[dict], dict]:
    """Passes 1..minutes a minute apart from 09:31; a path returning None leaves that quote out."""
    passes, quotes = [], {}
    for i in range(1, minutes + 1):
        passes.append(_pass(i))
        quotes[i] = {}
        for symbol in ["SPY", "XLK"] + STOCKS:
            price = paths.get(symbol, steps())(i)
            if price is not None:
                quotes[i][symbol] = _quote(symbol, i, price, stale=(symbol, i) in stale or symbol in stale)
    return passes, quotes


def run(paths, minutes=70, **kw):
    passes, quotes = session(paths, minutes, **kw)
    return radar_rules.replay(UNIVERSE, passes, quotes)


def kinds(saved):
    return [(e["kind"], e["symbols"][0] if e["kind"] != "group_move" else e["group"], e["direction"]) for e, _ in saved]


def test_stock_ahead_of_spy_fills_every_field_after_three_passes():
    [(event, revisions)] = run({"AAA": steps((35, 106.0))})
    assert set(event) == set(RadarEvent.__annotations__)
    assert event["event_id"] == "rv0-2030-01-15-spy-aaa-up-1" and event["kind"] == "relative_to_spy"
    assert event["rule_version"] == "radar-rules-v0" and event["universe_version"] == "radar-universe-test"
    assert event["first_seen_at"] == _pass(37)["finished_at"]  # qualified on 35, 36 and 37
    assert event["summary"] == "AAA ahead of SPY by 6.0% over 30 min (AAA +6.0%, SPY 0.0%)"
    assert event["measures"]["relative_pct"] == 6.0 and event["measures"]["window_minutes"] == 30
    assert event["measures"]["day_change_pct"] == 6.0 and event["benchmark"] == "SPY" and event["group"] is None
    assert [(e["symbol"], e["pass_id"]) for e in event["evidence"]] == [("AAA", 7), ("SPY", 7), ("AAA", 37), ("SPY", 37)]
    assert event["coverage"] == {"passes_expected": 38, "passes_recorded": 37, "symbols_missing": []}
    assert event["chart"] == {"symbol": "AAA", "from": _pass(7)["started_at"], "to": _pass(37)["finished_at"]}
    assert revisions == []


@pytest.mark.parametrize("paths", [
    {"AAA": steps((35, 104.0))},  # 4% is under the threshold
    {"SPY": steps((35, 94.0)), "AAA": steps((35, 99.0))},  # 5 points ahead, but AAA itself moved 1%: under the floor
    {"AAA": steps((35, 106.0), (37, 100.0))},  # held on two passes only
    {"AAA": steps((1, 110.0))},  # gapped up 10% and flat from the first pass: the window never sees the gap
])
def test_no_spy_event_under_threshold_floor_persistence_or_for_a_gap(paths):
    assert ("relative_to_spy", "AAA", "up") not in kinds(run(paths))


def test_stock_ahead_of_its_falling_sector_is_a_sector_event():
    [(event, _)] = run({"XLK": steps((35, 93.0)), "BBB": steps((35, 97.8))})
    assert event["kind"] == "relative_to_sector" and event["benchmark"] == "XLK" and event["direction"] == "up"
    assert event["summary"] == "BBB ahead of its sector XLK by 4.8% over 30 min (BBB −2.2%, XLK −7.0%)"
    assert event["measures"]["spy_relative_pct"] == -2.2 and event["event_id"] == "rv0-2030-01-15-sector-bbb-up-1"


def test_sector_event_is_skipped_when_spy_says_the_same():
    saved = run({"AAA": steps((35, 106.0)), "XLK": steps((35, 100.5))})
    assert kinds(saved) == [("relative_to_spy", "AAA", "up")]


def test_group_move_reports_coverage_dominance_and_member_alerts():
    paths = {"AAA": steps((35, 88.0)), "BBB": steps((35, 97.5)), "CCC": steps((35, 97.5)), "DDD": steps((35, 97.5)),
             "EEE": lambda i: None}
    saved = run(paths)
    assert kinds(saved) == [("relative_to_spy", "AAA", "down"), ("group_move", "Test group", "down")]
    group = saved[1][0]
    assert group["symbols"] == ["AAA", "BBB", "CCC", "DDD"] and group["benchmark"] == "SPY"
    assert group["measures"]["members_with_data"] == 4 and group["measures"]["members_total"] == 5
    assert group["measures"]["median_relative_pct"] == -2.5 and group["measures"]["top_member_share_pct"] == 61.5
    assert group["coverage"]["symbols_missing"] == ["EEE"]
    assert group["summary"].startswith("Test group behind SPY: 4 of 4 members down vs SPY over 30 min, median −2.5%")
    assert "mostly AAA" in group["summary"] and group["summary"].endswith("Own alerts: AAA")
    assert group["chart"]["symbol"] == "AAA"


def test_group_lists_only_members_with_an_open_same_direction_alert():
    # AAA falls alone and its event fades; later the whole group, AAA included, falls 2-3%
    paths = {"AAA": steps((35, 94.0), (45, 101.0), (80, 98.0)), "BBB": steps((80, 97.0)), "CCC": steps((80, 97.0)),
             "DDD": steps((80, 97.0)), "EEE": steps((80, 97.0))}
    saved = run(paths, minutes=90)
    assert ("relative_to_spy", "AAA", "down") in kinds(saved)
    group = next(e for e, _ in saved if e["kind"] == "group_move")
    assert "AAA" in group["symbols"] and "Own alerts" not in group["summary"]  # AAA's own event closed earlier


def test_group_needs_four_members_with_data_and_agreement():
    falling = {s: steps((35, 97.0)) for s in ["AAA", "BBB", "CCC"]}
    assert kinds(run({**falling, "DDD": lambda i: None, "EEE": lambda i: None})) == []
    assert kinds(run({**falling, "DDD": steps((35, 103.0)), "EEE": steps((35, 103.0))})) == [
        ("group_move", "Test group", "down")]  # 3 of 5 is 60%
    split = {"AAA": steps((35, 94.0)), "BBB": steps((35, 94.0)), "CCC": steps((35, 101.0)), "DDD": steps((35, 101.0)),
             "EEE": lambda i: None}  # median 2.5 down, but only 2 of 4 agree
    assert all(kind != "group_move" for kind, _, _ in kinds(run(split)))


def _statuses(revisions):
    return [(r["revision"], r["status"], r["recorded_at"]) for r in revisions]


def test_revisions_extend_fade_and_reemerge_only_after_the_cooldown():
    path = steps((35, 106.0), (45, 108.0), (55, 103.5), (58, 112.0))
    saved = run({"AAA": path}, minutes=95)
    assert [e["event_id"] for e, _ in saved] == ["rv0-2030-01-15-spy-aaa-up-1", "rv0-2030-01-15-spy-aaa-up-2"]
    first, revisions = saved[0]
    assert _statuses(revisions) == [(1, "extended", _pass(45)["finished_at"]), (2, "faded", _pass(55)["finished_at"])]
    assert revisions[0]["measures"]["relative_pct"] == 8.0 and revisions[1]["measures"]["relative_pct"] == 3.5
    assert [e["symbol"] for e in revisions[0]["evidence"]] == ["AAA", "SPY"] and "was +6.0%" in revisions[0]["note"]
    # AAA qualified again from minute 60, inside the 30-minute cooldown; after it (from minute 86) the 30-minute
    # window from the 103.5 shelf holds on 85, 86 and 87
    assert saved[1][0]["first_seen_at"] == _pass(87)["finished_at"]


def test_a_reversal_closes_the_event_and_the_other_direction_is_its_own_event():
    saved = run({"AAA": steps((35, 106.0), (45, 95.0))})
    assert kinds(saved) == [("relative_to_spy", "AAA", "up"), ("relative_to_spy", "AAA", "down")]
    assert _statuses(saved[0][1]) == [(1, "reversed", _pass(45)["finished_at"])]
    assert saved[0][1][0]["measures"]["relative_pct"] == -5.0
    assert saved[1][0]["first_seen_at"] == _pass(47)["finished_at"]


def test_missing_or_stale_quotes_never_make_an_event():
    gap = {"AAA": lambda i: None if i == 36 else steps((35, 106.0))(i)}
    [(event, _)] = run(gap)
    assert event["first_seen_at"] == _pass(39)["finished_at"]  # 37, 38, 39: the missing minute broke the run
    assert run({"AAA": steps((35, 106.0))}, stale={"AAA"}) == []  # trades ten minutes old
    assert run({"AAA": steps((35, 106.0)), "SPY": lambda i: None if i >= 36 else 100.0}) == []


def test_replay_is_deterministic():
    paths = {"AAA": steps((35, 106.0), (45, 95.0)), "BBB": steps((40, 93.0)), "CCC": steps((40, 97.0)),
             "DDD": steps((40, 97.0)), "EEE": steps((40, 97.0))}
    assert run(paths) == run(paths) and len(run(paths)) == 4


# The runner: detection wired between the recorded pass and the news check.

class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


PATHS = {"AAA": steps((35, 106.0))}


def _store_with(tmp_path, upto: int) -> RadarStore:
    store = RadarStore(tmp_path / "radar.sqlite")
    passes, quotes = session(PATHS, upto)
    for p in passes:
        record = {k: p[k] for k in ("session_date", "started_at", "finished_at", "universe_version", "status")}
        record.update(symbols_requested=8, symbols_returned=8, unmatched=[], requests_used=1, error=None, skip_reason=None)
        store.append_pass(record, list(quotes[p["id"]].values()))
    return store


def _runner(store, minute: int, news=None):
    at = (OPEN + timedelta(minutes=minute)).timestamp()

    def quotes(symbols):
        return {s: TradierQuote(symbol=s, last=PATHS.get(s, steps())(minute), bid=None, ask=None, volume=1000,
                                trade_date=int(at * 1000), raw={"prevclose": "100"}) for s in symbols}
    return RadarRunner(store, Calendar(), universe=UNIVERSE, quotes=quotes, clock=lambda: at + 1,
                       news=news or (lambda symbols, start, end: []))


def test_runner_detects_before_news_and_a_restart_writes_nothing_twice(tmp_path):
    store = _store_with(tmp_path, 36)
    asked = []
    pass_id = _runner(store, 37, news=lambda symbols, start, end: asked.append(symbols) or []).run_once()
    [event] = store.events(DAY)
    assert event["event_id"] == "rv0-2030-01-15-spy-aaa-up-1"
    assert asked == [["AAA"]]  # the new event got its news check in the same pass
    assert [c["status"] for c in store.news_checks(event["event_id"])] == ["none_found"]
    restarted = _runner(store, 37)
    assert restarted.detect(DAY, pass_id) == ([], []) and len(store.events(DAY)) == 1
    replayed = radar_rules.replay(UNIVERSE, radar_rules.session_passes(store.passes(DAY), DAY),
                                  store.pass_quotes(p["id"] for p in store.passes(DAY)))
    assert [e for e, _ in replayed] == store.events(DAY)


def test_runner_keeps_the_pass_when_detection_fails(tmp_path, monkeypatch, caplog):
    store = _store_with(tmp_path, 36)

    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(radar_rules, "detect", broken)
    enriched = []
    monkeypatch.setattr(radar_news, "enrich", lambda *args: enriched.append(args) or 0)
    pass_id = _runner(store, 37).run_once()
    assert pass_id == 37 and store.passes(DAY)[-1]["status"] == "ok" and store.events(DAY) == []
    assert "Radar detection failed" in caplog.text and len(enriched) == 1


def test_detection_reads_only_the_passes_its_windows_need(tmp_path):
    store = _store_with(tmp_path, 40)
    passes = radar_rules.session_passes(store.passes(DAY), DAY)
    assert radar_rules.needed_pass_ids(passes, len(passes) - 1) == {38, 39, 40, 8, 9, 10}


def test_quote_retention_is_twenty_sessions_and_events_stay(tmp_path):
    assert RETENTION_SESSIONS == 20
    store = _store_with(tmp_path, 37)
    pass_id = _runner(store, 38).run_once()
    assert store.events(DAY)
    for day in range(1, 21):  # twenty later sessions push the fixture day out
        record = {**store.passes(DAY)[0], "session_date": f"2030-02-{day:02d}"}
        del record["id"]
        store.append_pass(record, [_quote("SPY", 1, 100.0)])
    assert store.prune_quotes() == 38 * 8 and store.pass_quotes([pass_id]) == {pass_id: {}}
    assert len(store.events(DAY)) == 1 and len(store.passes(DAY)) == 38
