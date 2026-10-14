"""Focused leakage and stock-proxy execution tests for historical S1 selection."""

from datetime import UTC, date, datetime, time, timedelta
import copy
import json
import uuid
from zoneinfo import ZoneInfo

import pytest

from app.engine import scanner_replay_market as replay, scanner_rules as rules
from scripts import scanner_replay_capture as capture

ET = ZoneInfo("America/New_York")
DAY = date(2026, 8, 25)
OPEN = int(datetime.combine(DAY, time(9, 30), ET).timestamp())
CLOSE = int(datetime.combine(DAY, time(16), ET).timestamp())


def minute(at, opening=100, high=None, low=None, closing=None, volume=100):
    closing = opening if closing is None else closing
    return {"time": at, "end_time": at + 60, "open": opening,
            "high": max(opening, closing) + 0.1 if high is None else high,
            "low": min(opening, closing) - 0.1 if low is None else low,
            "close": closing, "volume": volume}


def bundle():
    # Fifteen completed prior sessions for ATR, and a clean 15-minute opening
    # range followed by the exact S1 opening-range break at 09:50.
    prior_sessions = [DAY - timedelta(days=i) for i in range(1, 30) if (DAY - timedelta(days=i)).weekday() < 5][:15]
    daily = [{"date": prior.isoformat(), "high": 101, "low": 99, "close": 100}
             for prior in prior_sessions]
    minutes = [minute(OPEN + i * 60) if i < 15 else minute(OPEN + i * 60, 100.2, 100.35, 100.1, 100.25)
               for i in range(35)]
    symbols = {symbol: {"minutes": [], "daily": copy.deepcopy(daily)} for symbol in rules.UNIVERSE}
    symbols["SPY"] = {"minutes": minutes, "daily": daily}
    return {"session_date": DAY.isoformat(), "retrieved_at": datetime.fromtimestamp(CLOSE + 60, UTC).isoformat(),
            "open_at": OPEN, "close_at": CLOSE, "symbols": symbols, "feed": "sip", "adjustment": "raw"}


def candidate(at=OPEN + 30 * 60, direction="long"):
    return {"candidate_id": str(uuid.uuid4()), "detected_at": replay._stamp(at), "direction": direction,
            "stop": 99 if direction == "long" else 101,
            "target": 102 if direction == "long" else 98, "facts": {"close": 100}}


def continuation(c, rows):
    return {"candidate_id": c["candidate_id"], "cutoff_at": replay._epoch(c["detected_at"]),
            "nonce": "a" * 64, "minutes": rows}


def test_scanner_signal_parity_and_no_future_in_published_packet():
    source = bundle()
    result = replay.generate_session(source)
    first = result["setups"][0]
    prefix = source["symbols"]["SPY"]["minutes"][:20]
    expected = rules.scan(rules.five_minute_bars(prefix, OPEN, CLOSE),
                          rules.atr14(source["symbols"]["SPY"]["daily"]),
                          OPEN, OPEN + (15 * 60 - 9 * 60 - 30) * 60, set())[-1]
    assert first["packet"]["candidate"]["symbol"] == "SPY"
    assert first["packet"]["candidate"]["setup"] == "orb"
    assert first["packet"]["candidate"]["bar_end"] == replay._stamp(OPEN + 20 * 60)
    assert first["packet"]["candidate"]["stop"] == expected["stop"]
    assert first["packet"]["candidate"]["target"] == expected["target"]
    assert first["packet"]["candidate"]["params_hash"] == rules.PARAMS_HASH
    assert all(m["end_time"] <= OPEN + 20 * 60 for m in first["packet"]["candles_1m_last60"])
    assert all(b["end"] <= OPEN + 20 * 60 for b in first["packet"]["candles_5m_session"])
    assert all(m["time"] >= OPEN + 20 * 60 for m in first["continuation"]["minutes"])
    assert first["packet"]["candidate"]["contract"] is None
    assert first["packet"]["live"]["option"] is None
    assert first["packet"]["live"]["market_state"] == "rth"
    assert first["packet"]["live"]["rvol"] is None
    assert first["packet"]["live"]["levels"]["or15_high"] == expected["facts"]["opening_range_high"]
    assert all(row["feed"] == "sip" and row["source"] == "alpaca_sip_raw"
               for row in first["packet"]["candles_1m_last60"] + first["packet"]["candles_5m_session"])
    assert len(first["continuation"]["nonce"]) == 64
    assert result["scoring_policy"]["hash"] == replay.scoring_policy()["hash"]
    assert result["daily_atr"]["SPY"] == {"prior_sessions": 15, "atr14": 2.0,
        "as_of_session": "2026-08-24",
        "source": "alpaca_sip_1day_raw", "feed": "sip", "adjustment": "raw"}
    assert set(result["daily_atr"]) == set(rules.UNIVERSE)
    assert any("Entry-minute stop not checked (optimistic)" in note for note in result["differences"])

    changed = copy.deepcopy(source)
    for bar in changed["symbols"]["SPY"]["minutes"]:
        if bar["time"] >= OPEN + 20 * 60:
            bar.update(open=103, high=103.1, low=102.9, close=103)
    other = replay.generate_session(changed)["setups"][0]
    assert other["packet"] == first["packet"]
    assert other["continuation"]["minutes"] != first["continuation"]["minutes"]


def test_cooldown_and_taken_state_after_proxy_exit(monkeypatch):
    source = bundle()
    spy = source["symbols"]["SPY"]["minutes"]
    spy.extend(minute(OPEN + i * 60, 100.2, 100.35, 100.1, 100.25) for i in range(35, 60))
    spy[23]["high"] = 101  # first candidate's target is hit after its entry minute
    original = rules.scan
    first = original(rules.five_minute_bars(spy[:20], OPEN, CLOSE), 2, OPEN, OPEN + 330 * 60, set())[-1]
    seen = []

    def repeated(bars, atr, open_at, last_end, taken):
        end = bars[-1]["end"]
        seen.append((end, set(taken)))
        if end in (OPEN + 20 * 60, OPEN + 25 * 60, OPEN + 55 * 60):
            return [{**first, "bar_start": end - 300, "bar_end": end}]
        return []

    monkeypatch.setattr(rules, "scan", repeated)
    setups = replay.generate_session(source)["setups"]
    assert [replay._epoch(x["packet"]["candidate"]["bar_end"]) for x in setups] == [OPEN + 20 * 60, OPEN + 55 * 60]
    assert ("orb", OPEN + 20 * 60) in dict(seen)[OPEN + 55 * 60]
    costly = replay.generate_session(source, scoring_policy=replay.scoring_policy(cost_per_share=0.5))["setups"]
    assert [x["packet"]["candidate"]["candidate_id"] for x in costly] == [
        x["packet"]["candidate"]["candidate_id"] for x in setups]


def test_sparse_opening_bucket_matches_live_rules_and_prior_daily_only():
    source = bundle()
    source["symbols"]["SPY"]["minutes"].pop(2)
    result = replay.generate_session(source)
    prefix = [m for m in source["symbols"]["SPY"]["minutes"] if m["end_time"] <= OPEN + 20 * 60]
    live_bars = rules.five_minute_bars(prefix, OPEN, CLOSE)
    expected = rules.scan(live_bars, 2, OPEN, OPEN + 330 * 60, set())[-1]
    assert len(result["setups"]) == 1
    assert result["setups"][0]["packet"]["candidate"]["stop"] == expected["stop"]
    assert result["setups"][0]["packet"]["candidate"]["target"] == expected["target"]
    assert replay.strict_v1_setup_counts(source)["symbols"]["SPY"] == 0
    assert result["coverage"]["symbols"]["SPY"]["parity_minus_strict_setups"] == 1
    assert [m["time"] for m in result["setups"][0]["packet"]["candles_1m_last60"]] == [m["time"] for m in prefix]
    source = bundle()
    source["symbols"]["SPY"]["daily"] = source["symbols"]["SPY"]["daily"][:14]
    source["symbols"]["SPY"]["daily"].append({"date": DAY.isoformat(), "high": 1000, "low": 1, "close": 500})
    with pytest.raises(ValueError, match="Prior daily ATR requires at least 15 sessions.*SPY"):
        replay.generate_session(source)


def test_coverage_counts_lost_symbol_time_without_inventing_setups():
    source = bundle()
    source["symbols"]["SPY"]["minutes"].pop(21)  # 09:51, after the first candidate
    result = replay.generate_session(source)
    spy = result["coverage"]["symbols"]["SPY"]
    assert spy["expected_minutes"] == 390
    assert spy["provided_minutes"] == 34
    assert spy["missing_minutes"] == 356
    assert spy["first_missing_epoch"] == OPEN + 21 * 60
    assert spy["evaluated_scan_slots"] == 4
    assert spy["blocked_scan_slots"] == spy["eligible_scan_slots"] - 4
    assert spy["scan_minutes_lost"] == 5 * spy["blocked_scan_slots"]
    assert spy["partial_scan_buckets"] == 1
    assert spy["empty_scan_buckets"] == spy["blocked_scan_slots"]
    assert spy["setups_emitted"] == 1
    assert spy["strict_v1_setups_emitted"] == 1
    assert spy["actual_suppressed_setups"] is None
    assert result["coverage"]["totals"]["actual_suppressed_setups"] is None
    assert len(result["setups"]) == 1
    assert "coverage" not in result["setups"][0]["packet"]
    assert "daily_atr" not in result["setups"][0]["packet"]


def test_empty_current_bucket_skips_only_that_bar_and_later_sparse_bars_resume():
    source = bundle()
    spy = source["symbols"]["SPY"]["minutes"]
    spy[15:20] = [minute(OPEN + i * 60) for i in range(15, 20)]
    spy[20:25] = []  # 09:50-09:54 is empty; the 10:00 bar remains occupied
    result = replay.generate_session(source)
    assert result["coverage"]["symbols"]["SPY"]["blocked_scan_slots"] > 0
    selected = [replay._epoch(s["packet"]["candidate"]["bar_end"]) for s in result["setups"]]
    assert selected == [OPEN + 30 * 60]
    prefix = [m for m in spy if m["end_time"] <= OPEN + 30 * 60]
    expected = rules.scan(rules.five_minute_bars(prefix, OPEN, CLOSE), 2, OPEN, OPEN + 330 * 60, set())[-1]
    assert result["setups"][0]["packet"]["candidate"]["stop"] == expected["stop"]
    assert replay.strict_v1_setup_counts(source)["symbols"]["SPY"] == 0


def test_strict_v1_counts_include_zeroed_setup_types_and_symbols():
    counts = replay.strict_v1_setup_counts(bundle())
    expected_types = {"orb:long", "fade:long", "fade:short"}
    assert counts["version"] == replay.STRICT_VERSION
    assert counts["total"] == 1
    assert counts["by_setup"] == {"orb:long": 1, "fade:long": 0, "fade:short": 0}
    assert set(counts["by_symbol_setup"]) == set(rules.UNIVERSE)
    assert all(set(per_symbol) == expected_types for per_symbol in counts["by_symbol_setup"].values())
    assert counts["by_symbol_setup"]["SPY"] == counts["by_setup"]
    assert all(sum(per_symbol.values()) == counts["symbols"][symbol]
               for symbol, per_symbol in counts["by_symbol_setup"].items())


def test_only_current_bar_signal_is_selected_when_rules_return_older_signal(monkeypatch):
    source = bundle()
    original = rules.scan
    old_signal = original(rules.five_minute_bars(source["symbols"]["SPY"]["minutes"][:20], OPEN, CLOSE),
                          2, OPEN, OPEN + 330 * 60, set())[-1]

    def older_only(bars, atr, open_at, last_end, taken):
        return [old_signal] if bars and bars[-1]["end"] >= old_signal["bar_end"] else []

    monkeypatch.setattr(rules, "scan", older_only)
    result = replay.generate_session(source)
    assert [replay._epoch(s["packet"]["candidate"]["bar_end"]) for s in result["setups"]] == [OPEN + 20 * 60]


def test_holdout_feed_and_universe_are_explicit():
    source = bundle()
    source["session_date"] = "2026-09-14"
    with pytest.raises(ValueError, match="Holdout"):
        replay.generate_session(source)
    source = bundle()
    source["feed"] = "iex"
    with pytest.raises(ValueError, match="SIP"):
        replay.generate_session(source)
    source = bundle()
    source["symbols"]["NVDA"] = {"minutes": [], "daily": []}
    with pytest.raises(ValueError, match="universe"):
        replay.generate_session(source)


def test_history_cohort_closes_before_midnight_and_excludes_fill_ids():
    source = bundle()
    def row(closed, key):
        return {"closed_at": closed, "underlying": "SPY", "side": "call", "time_bucket": "open",
                "vwap_bucket": "at", "realized_pnl": 10, "pnl_pct": 1, "mfe_pct": 1, "mae_pct": -1,
                "source_fill_key": key}
    rows = [row("2026-08-24T23:59:00", "before"), row("2026-08-25T00:00:00", "at-cutoff")]
    history = replay.generate_session(source, history_rows=rows)["setups"][0]["packet"]["history"]
    assert history["cohorts"][1]["trades"] == 1
    assert replay.generate_session(source, history_rows=rows)["setups"][0]["packet"]["history_cutoff"] == "2026-08-25T00:00:00-04:00"
    assert "source_fill_keys" not in history
    assert "before" not in json.dumps(history)
    assert history["as_of_ny"] == "2026-08-25T00:00:00-04:00"


def test_score_stop_first_gap_and_missing_exit():
    c = candidate()
    at = OPEN + 30 * 60
    rows = [minute(at + 60, 100), minute(at + 120, 100, 102.5, 98.5, 100)]
    result = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE},
                                replay.scoring_policy())
    assert result["resolved"] and result["reason"] == "stop" and result["exit_price"] == 99
    assert result["r"] == -1 and result["pnl_100"] == -100
    rows[1] = minute(at + 120, 98, 102.5, 97.5, 100)
    gap = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE}, replay.scoring_policy())
    assert gap["exit_price"] == 98 and gap["pnl_100"] == -200
    assert replay.score_setup(c, continuation(c, rows[:1]), {"open_at": OPEN, "close_at": CLOSE},
                              replay.scoring_policy())["status"] == "unresolved"
    assert replay.score_setup(c, continuation(c, rows[1:]), {"open_at": OPEN, "close_at": CLOSE},
                              replay.scoring_policy())["reason"] == "missing_entry_minute"
    rows = [minute(at + 60, 100), minute(at + 180, 100)]
    missing_middle = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE},
                                         replay.scoring_policy())
    assert missing_middle["status"] == "unresolved" and missing_middle["reason"] == "missing_exit_minute"


def test_delay_entry_invalidated_and_clock_flat():
    c = candidate()
    at = OPEN + 30 * 60
    rows = [minute(at + 60, 100), minute(at + 120, 100), minute(at + 180, 100)]
    baseline = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE},
                                  replay.scoring_policy())
    assert baseline["entry_at"] == at + 60
    delayed = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE},
                                 replay.scoring_policy(), delay_seconds=60)
    assert delayed["entry_at"] == at + 120
    rows[1] = minute(at + 120, 102)
    assert replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE},
                              replay.scoring_policy(), delay_seconds=60)["status"] == "invalidated"
    short_session = {"open_at": OPEN, "close_at": OPEN + 60 * 60}
    rows = [minute(t, 100) for t in range(at + 60, OPEN + 60 * 60, 60)]
    flat = replay.score_setup(c, continuation(c, rows), short_session, replay.scoring_policy())
    assert flat["reason"] == "flat" and flat["exit_at"] == short_session["close_at"] - 600


def test_live_fade_with_wrong_side_stop_is_counted_but_proxy_never_enters(monkeypatch):
    c = candidate(direction="short")
    c["stop"] = 99  # live rules can emit a stale fade stop below its short detection close of 100
    invalid = replay.score_setup(c, continuation(c, [minute(OPEN + 31 * 60, 100)]),
                                 {"open_at": OPEN, "close_at": CLOSE}, replay.scoring_policy())
    assert invalid["status"] == "invalidated" and invalid["reason"] == "invalid_frozen_stop_target_geometry"
    assert invalid["entry_at"] is None and invalid["r"] is None and invalid["pnl_100"] is None

    source = bundle()
    spy = source["symbols"]["SPY"]["minutes"]
    spy.extend(minute(OPEN + i * 60, 100.2, 100.35, 100.1, 100.25) for i in range(35, 60))
    original = rules.scan
    first = original(rules.five_minute_bars(spy[:20], OPEN, CLOSE), 2, OPEN, OPEN + 330 * 60, set())[-1]

    def wrong_side_then_valid(bars, atr, open_at, last_end, taken):
        end = bars[-1]["end"]
        if end == OPEN + 20 * 60:
            return [{**first, "setup": "fade", "direction": "short", "stop": 99, "target": 98,
                     "facts": {**first["facts"], "close": 100}}]
        if end == OPEN + 55 * 60:
            return [{**first, "bar_start": end - 300, "bar_end": end}]
        return []

    monkeypatch.setattr(rules, "scan", wrong_side_then_valid)
    generated = replay.generate_session(source)
    assert [replay._epoch(item["packet"]["candidate"]["bar_end"]) for item in generated["setups"]] == [
        OPEN + 20 * 60, OPEN + 55 * 60]
    assert generated["coverage"]["symbols"]["SPY"]["setups_emitted"] == 2


def test_scoring_costs_are_explicit_and_policy_is_frozen():
    c = candidate()
    at = OPEN + 30 * 60
    rows = [minute(at + 60, 100, 103, 98, 100), minute(at + 120, 100, 102.2, 99.9, 101)]
    policy = replay.scoring_policy(cost_per_share=0.01, slippage_bps=10)
    result = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE}, policy)
    assert result["reason"] == "target" and result["pnl_100"] < 200
    assert result["entry_at"] == at + 60  # entry-minute stop/target touches are ignored
    assert result["exit_price"] == result["raw_exit_price"] == 102  # target capped at raw fill
    assert result["net_fees_100"] == 2 and result["slippage_100"] > 0
    assert result["pnl_100_cost_sensitivity"] < result["pnl_100"]
    with pytest.raises(ValueError, match="modified"):
        replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE}, {**policy, "shares": 1})


def test_sensitivity_is_same_raw_fill_and_cost_cannot_invalidate_entry():
    c = candidate()
    at = OPEN + 30 * 60
    rows = [minute(at + 60, 101.99, 102, 101.8, 101.99),
            minute(at + 120, 102, 102.2, 101.8, 102.1)]
    zero = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE}, replay.scoring_policy())
    costly_policy = replay.scoring_policy(cost_per_share=0.5)
    costly = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE}, costly_policy)
    assert (zero["status"], zero["entry_at"], zero["exit_at"], zero["entry_price"], zero["exit_price"]) == (
        costly["status"], costly["entry_at"], costly["exit_at"], costly["entry_price"], costly["exit_price"])
    assert costly["resolved"] and costly["pnl_100"] < 0
    assert zero["pnl_100_cost_sensitivity"] == pytest.approx(zero["pnl_100"] - 4)
    assert costly["pnl_100_cost_sensitivity"] == zero["pnl_100_cost_sensitivity"]
    assert costly_policy["hash"] != replay.scoring_policy()["hash"]


def test_legacy_policy_is_validated_but_never_recomputed():
    legacy = replay._scoring_policy(replay.LEGACY_VERSION, 60, 0, 0)
    current = replay.scoring_policy()
    assert replay._policy(legacy) == legacy and legacy["hash"] != current["hash"]
    c = candidate()
    with pytest.raises(ValueError, match="original scores must not be recomputed"):
        replay.score_setup(c, continuation(c, []), {"open_at": OPEN, "close_at": CLOSE}, legacy)
    with pytest.raises(ValueError, match="reading, not new generation"):
        replay.generate_session(bundle(), scoring_policy=legacy)


def test_v2_policy_freezes_sparse_selection_while_v1_scores_remain_readable():
    current = replay.scoring_policy()
    strict_v1 = replay._scoring_policy(replay.STRICT_VERSION, 60, 0, 0)
    assert current["selection_gap_rule"] == "occupied_current_bucket;partial_five_minute_bars;resume_after_empty_bucket"
    assert current["hash"] != strict_v1["hash"]
    assert replay._policy(strict_v1) == strict_v1
    with pytest.raises(ValueError, match="reading, not new generation"):
        replay.generate_session(bundle(), scoring_policy=strict_v1)
    c = candidate()
    rows = [minute(OPEN + 31 * 60, 100), minute(OPEN + 32 * 60, 100, 102.2, 99.9, 101)]
    assert replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE},
                              strict_v1)["resolved"]


def test_capture_uses_calendar_and_daily_bar_calendar_date(monkeypatch):
    calls = []

    def provider(_client, url, params):
        calls.append((url, dict(params)))
        if url == capture.CALENDAR:
            return [{"date": DAY.isoformat(), "open": "09:30", "close": "16:00"}]
        stock = {"t": replay._stamp(OPEN), "o": 100, "h": 101, "l": 99, "c": 100, "v": 100}
        prior_days = [DAY - timedelta(days=i) for i in range(1, 30) if (DAY - timedelta(days=i)).weekday() < 5][:15]
        daily = [{**stock, "t": datetime.combine(prior, time(), ET).astimezone(UTC).isoformat().replace("+00:00", "Z")}
                 for prior in prior_days]
        bars = ({"SPY": [stock]} if params["timeframe"] == "1Min"
                else {symbol: daily for symbol in capture.UNIVERSE})
        return {"bars": bars,
                "next_page_token": None}

    monkeypatch.setattr(capture, "_read", provider)
    result = capture.capture(object(), [DAY])[0]
    assert len(calls) == 3
    assert all(p.get("feed", "sip") == "sip" and p.get("adjustment", "raw") == "raw" for _, p in calls)
    assert result["symbols"]["SPY"]["minutes"][0]["time"] == OPEN
    assert len(result["symbols"]["SPY"]["daily"]) == 15
    assert result["symbols"]["SPY"]["daily"][-1]["date"] == "2026-08-24"
    assert all(len(result["symbols"][symbol]["daily"]) == 15 for symbol in capture.UNIVERSE)


def test_capture_refuses_any_symbol_with_fewer_than_15_prior_sessions(monkeypatch):
    calls = []
    def provider(_client, url, params):
        calls.append(url)
        if url == capture.CALENDAR:
            return [{"date": DAY.isoformat(), "open": "09:30", "close": "16:00"}]
        if params["timeframe"] == "1Min":
            return {"bars": {}, "next_page_token": None}
        prior_days = [DAY - timedelta(days=i) for i in range(1, 30) if (DAY - timedelta(days=i)).weekday() < 5][:15]
        daily = [{"t": datetime.combine(prior, time(), ET).astimezone(UTC).isoformat().replace("+00:00", "Z"),
                  "o": 100, "h": 101, "l": 99, "c": 100, "v": 100} for prior in prior_days]
        return {"bars": {symbol: daily[:14] if symbol == "SPY" else daily for symbol in capture.UNIVERSE},
                "next_page_token": None}
    monkeypatch.setattr(capture, "_read", provider)
    with pytest.raises(capture.InsufficientDailyHistory, match=r"SPY\(14\)"):
        capture.capture(object(), [DAY])
    assert calls == [capture.CALENDAR, capture.STOCKS, capture.STOCKS]


def test_capture_bounded_pages_and_calendar_span(monkeypatch):
    with pytest.raises(ValueError, match="bounded date span"):
        capture._calendar(object(), [date(2025, 1, 1), date(2026, 8, 25)])
    calls = []

    def endless(_client, _url, params):
        calls.append(dict(params))
        return {"bars": {}, "next_page_token": f"next-{len(calls)}"}

    monkeypatch.setattr(capture, "_read", endless)
    monkeypatch.setattr(capture, "MAX_PAGES", 2)
    with pytest.raises(ValueError, match="bounded page count"):
        capture._bars(object(), datetime.fromtimestamp(OPEN, UTC), datetime.fromtimestamp(CLOSE, UTC), "1Min")
    assert len(calls) == 2 and all(call["feed"] == "sip" and call["adjustment"] == "raw" for call in calls)


@pytest.mark.parametrize("day,feed,existing", [
    ("2026-09-14", "sip", False),
    ("2026-08-25", "iex", False),
    ("2026-08-25", "sip", True),
])
def test_capture_refuses_before_network_without_echoing_inputs(monkeypatch, tmp_path, capsys, day, feed, existing):
    output = tmp_path / "out"
    if existing:
        output.mkdir()
        (output / f"bundle-{day}.json").write_text("old")
    monkeypatch.setattr("sys.argv", ["scanner_replay_capture.py", "--dates", day, "--output-dir", str(output)])
    monkeypatch.setenv("ALPACA_DATA_FEED", feed)
    monkeypatch.setenv("ALPACA_API_KEY", "SECRET_KEY_SENTINEL")
    monkeypatch.setenv("ALPACA_API_SECRET", "SECRET_SECRET_SENTINEL")
    monkeypatch.setattr(capture, "_read", lambda *_args, **_kwargs: pytest.fail("network read"))
    with pytest.raises(SystemExit):
        capture.main()
    error = capsys.readouterr().err
    assert "SECRET_" not in error and day not in error
    assert "invalid request or unavailable provider data" in error
    if existing:
        assert (output / f"bundle-{day}.json").read_text() == "old"
    else:
        assert not output.exists()
