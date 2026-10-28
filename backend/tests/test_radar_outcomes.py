"""Radar outcome scorer on a synthetic store: signed returns against SPY, horizons, the Movers and random
comparisons, exclusions, the append-only output and the per-version read-out, with hand-worked numbers."""
from datetime import UTC, datetime
from dataclasses import asdict
import hashlib
import json

import pytest

from app.engine import radar_movers, radar_rules
from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore
from scripts import radar_outcomes as ro

SESSION = "2026-10-27"


def _at(hh_mm: str, session: str = SESSION) -> float:
    return datetime.fromisoformat(f"{session}T{hh_mm}:00").replace(tzinfo=ET).timestamp()


def _stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _stock(symbol):
    return {"symbol": symbol, "kind": "stock", "benchmark": False, "sector": None, "sources": []}


UNIVERSE = {"version": "t", "groups": [{"name": "Pair", "members": ["AAA", "BBB"]}],
            "symbols": [{"symbol": "SPY", "kind": "etf", "benchmark": True, "sources": []}]
            + [_stock(s) for s in ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")]}
PREV = {"SPY": 100, "AAA": 95, "BBB": 96, "CCC": 97, "DDD": 103, "EEE": 104, "FFF": 105}  # ranks at 10:00


def _add_pass(store, hh_mm, prices, session=SESSION, stale=()):
    at = _at(hh_mm, session)
    record = {"session_date": session, "started_at": _stamp(at), "finished_at": _stamp(at + 5),
              "universe_version": "t", "status": "ok", "symbols_requested": 7, "symbols_returned": 7, "unmatched": [],
              "requests_used": 1, "error": None, "skip_reason": None}
    quotes = [{"symbol": s, "last": p, "prev_close": PREV[s], "open": PREV[s], "high": None, "low": None, "volume": 1,
               "bid": None, "ask": None, "trade_time_ms": (at - (600 if s in stale else 1)) * 1000,
               "retrieved_at": _stamp(at + 2)} for s, p in prices.items()]
    store.append_pass(record, quotes)
    return record


def _event(store, event_id, kind, direction, symbols, first_seen, rule="radar-rules-v1", session=SESSION):
    store.append_event({"event_id": event_id, "session_date": session, "rule_version": rule, "universe_version": "t",
                        "kind": kind, "direction": direction, "symbols": symbols, "benchmark": "SPY",
                        "group": "Pair" if kind == "group_move" else None, "first_seen_at": first_seen["finished_at"],
                        "summary": "", "measures": {}, "evidence": [], "coverage": {}, "chart": {}})


def _certify(store, hours=None, origin="live", failed=()):
    receipts, _ = store.detection_evidence()
    for p in store.passes():
        if p['id'] in receipts:
            continue
        ids = [e['event_id'] for e in store.events(p['session_date']) if e['first_seen_at'] == p['finished_at']]
        store.append_detection(p['id'], universe=UNIVERSE, rules=asdict(radar_rules.V1),
                               hours=hours or {"status": "open", "open": 570, "close": 960},
                               status="failed" if p['id'] in failed else "ok", event_ids=ids,
                               recorded_at=p['finished_at'], origin=origin)


FLAT = {s: 100.0 for s in PREV}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(radar_movers, "TOP", 2)
    s = RadarStore(tmp_path / "radar.sqlite")
    start = _add_pass(s, "10:00", FLAT)
    _add_pass(s, "10:31", {**FLAT, "AAA": 102.0, "BBB": 101.0})                 # 30m, one minute off target
    _add_pass(s, "11:00", {**FLAT, "SPY": 101.0, "AAA": 104.0, "FFF": 98.0})    # 60m
    _add_pass(s, "15:59", {**FLAT, "AAA": 99.0})                                # close
    _event(s, "up_aaa", "relative_to_spy", "up", ["AAA"], start)
    _event(s, "down_fff", "relative_to_spy", "down", ["FFF"], start)
    _event(s, "pair", "group_move", "up", ["AAA", "BBB"], start)
    _certify(s)
    return s


def _rows(store, today="2026-10-28"):
    _certify(store)
    return {r["event_id"]: r for r in ro.score_store(RadarStore(store.path, read_only=True), UNIVERSE, set(), today)}


def test_an_up_event_is_scored_against_spy_movers_and_random_at_each_horizon(store):
    h = _rows(store)["up_aaa"]["horizons"]
    # Movers leaders at 10:00 are AAA (+5.3%) and BBB (+4.2%); AAA is the event, so the comparison is BBB.
    assert h["30m"] == {"end_pass": 2, "event": 2.0, "movers": 1.0, "movers_n": 1, "random": 0.2}
    # 60m: AAA +4% vs SPY +1% = +3; BBB 0% = -1; the five others -1, -1, -1, -1, -3 (FFF fell 2%).
    assert h["60m"]["event"] == pytest.approx(3.0) and h["60m"]["movers"] == pytest.approx(-1.0)
    assert h["60m"]["random"] == pytest.approx(-1.4)
    assert h["close"]["event"] == pytest.approx(-1.0) and h["close"]["movers"] == 0.0


def test_a_down_event_is_signed_so_a_further_fall_counts_as_kept_going(store):
    h = _rows(store)["down_fff"]["horizons"]
    # FFF -2% vs SPY +1%, signed down: +3. Laggards are FFF and EEE; the comparison is EEE: -(0 - 1) = +1.
    assert h["60m"]["event"] == pytest.approx(3.0) and h["60m"]["movers"] == pytest.approx(1.0)


def test_a_group_event_is_the_equal_weight_average_of_its_members(store):
    assert _rows(store)["pair"]["horizons"]["30m"]["event"] == pytest.approx(1.5)  # AAA +2, BBB +1


def test_a_late_event_is_excluded_at_horizons_the_session_does_not_reach(tmp_path, monkeypatch):
    monkeypatch.setattr(radar_movers, "TOP", 2)
    s = RadarStore(tmp_path / "radar.sqlite")
    late = _add_pass(s, "15:30", FLAT)
    _add_pass(s, "15:45", {**FLAT, "AAA": 101.0})  # the last pass: 15 minutes short of the 30-minute target
    _event(s, "late", "relative_to_spy", "up", ["AAA"], late)
    row = _rows(s)["late"]
    assert row["excluded"] == {"30m": "no pass at the horizon", "60m": "no pass at the horizon"}
    assert row["horizons"]["close"]["event"] == pytest.approx(1.0)


def test_a_stale_quote_at_an_endpoint_excludes_that_horizon(tmp_path, monkeypatch):
    monkeypatch.setattr(radar_movers, "TOP", 2)
    s = RadarStore(tmp_path / "radar.sqlite")
    start = _add_pass(s, "10:00", FLAT)
    _add_pass(s, "11:00", {**FLAT, "AAA": 104.0}, stale={"AAA"})
    _event(s, "e", "relative_to_spy", "up", ["AAA"], start)
    assert _rows(s)["e"]["excluded"]["60m"] == "no usable quote at an endpoint"


def test_a_first_seen_pass_that_was_not_recorded_excludes_every_horizon(store):
    ghost = {"finished_at": _stamp(_at("12:00"))}
    _event(store, "ghost", "relative_to_spy", "up", ["AAA"], ghost)
    assert set(_rows(store)["ghost"]["excluded"]) == {"30m", "60m", "close"}


def test_main_appends_once_skips_today_and_never_writes_the_store(store, tmp_path, capsys):
    out = tmp_path / "outcomes.jsonl"
    before = hashlib.sha256(store.path.read_bytes()).hexdigest()
    ro.main([str(store.path), "--out", str(out), "--today", SESSION])  # the session is today: nothing scored
    assert not out.exists()
    ro.main([str(store.path), "--out", str(out), "--today", "2026-10-28"])
    first = out.read_text().splitlines()
    capsys.readouterr()
    ro.main([str(store.path), "--out", str(out), "--today", "2026-10-28"])
    assert out.read_text().splitlines() == first and len(first) == 4
    printed = json.loads(capsys.readouterr().out)
    assert printed["scored_now"] == 0 and printed["versions"]["radar-rules-v1"]["excluded_events"] == 3
    assert hashlib.sha256(store.path.read_bytes()).hexdigest() == before


def test_the_read_out_is_per_rule_version_and_keeps_calibration_sessions_out():
    def row(event_id, version, session, value, movers):
        return {"event_id": event_id, "rule_version": version, "session_date": session,
                "horizons": {"60m": {"event": value, "movers": movers, "random": 0.0}}}
    rows = [row("a", "radar-rules-v0", "2026-10-22", 5.0, 0.0), row("b", "radar-rules-v0", "2026-10-26", 1.0, 0.0),
            row("c", "radar-rules-v1", "2026-10-27", -1.0, 1.0)]
    for r in rows:
        r.update(evidence_verified=True, config_digest="frozen")
    rows += [{"record_type": "session", "rule_version": r["rule_version"], "session_date": r["session_date"],
              "verified": True, "config_digest": "frozen"} for r in list(rows)]
    out = ro.summarize(rows)
    v0, v1 = out["radar-rules-v0"], out["radar-rules-v1"]
    assert (v0["events"], v0["sessions"]) == (1, 1)
    assert v0["horizons"]["60m"]["event_mean"] == 1.0  # the calibration session's +5 is not in it
    assert v0["in_sample"]["sessions"] == ["2026-10-22"] and v0["in_sample"]["horizons"]["60m"]["event_mean"] == 5.0
    assert "in_sample" not in v1
    assert v1["horizons"]["60m"]["radar_minus_movers"] == -2.0
    assert v1["decision"] == "not reviewed: 1 of 20 sessions"


def test_decisions_follow_the_spec():
    def report(interval, kept):
        return {"sessions": 20, "horizons": {"60m": {"radar_minus_movers_95": interval, "kept_going": kept}}}
    assert ro.decide(report([0.1, 0.9], 0.6)) == "Radar beats Movers at +60 min"
    assert ro.decide(report([0.1, 0.9], 0.5)) == "no demonstrated timing value over Movers"
    assert ro.decide(report([-0.9, -0.1], 0.4)).startswith("Radar does worse")
    assert ro.decide(report([-0.1, 0.9], 0.7)) == "no demonstrated timing value over Movers"


def test_the_session_bootstrap_of_a_constant_is_that_constant():
    assert ro._interval({"d1": [1.0, 1.0], "d2": [1.0]}) == [1.0, 1.0]
    assert ro._interval({"d1": [1.0]}) is None
