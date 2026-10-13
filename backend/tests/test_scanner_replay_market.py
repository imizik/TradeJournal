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
    symbols = {symbol: {"minutes": [], "daily": []} for symbol in rules.UNIVERSE}
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


def test_missing_minute_blocks_scanning_and_prior_daily_only():
    source = bundle()
    source["symbols"]["SPY"]["minutes"].pop(2)
    assert not replay.generate_session(source)["setups"]
    source = bundle()
    source["symbols"]["SPY"]["daily"] = source["symbols"]["SPY"]["daily"][:14]
    source["symbols"]["SPY"]["daily"].append({"date": DAY.isoformat(), "high": 1000, "low": 1, "close": 500})
    result = replay.generate_session(source)
    assert not result["setups"]
    assert {g["reason"] for g in result["gaps"]} >= {"prior_daily_atr14_unavailable"}


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


def test_scoring_costs_are_explicit_and_policy_is_frozen():
    c = candidate()
    at = OPEN + 30 * 60
    rows = [minute(at + 60, 100, 103, 98, 100), minute(at + 120, 100, 102.2, 99.9, 101)]
    policy = replay.scoring_policy(cost_per_share=0.01, slippage_bps=10)
    result = replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE}, policy)
    assert result["reason"] == "target" and result["pnl_100"] < 200
    assert result["entry_at"] == at + 60  # entry-minute stop/target touches are ignored
    assert result["exit_price"] < 102  # adverse costs; favorable gap cannot improve target
    with pytest.raises(ValueError, match="modified"):
        replay.score_setup(c, continuation(c, rows), {"open_at": OPEN, "close_at": CLOSE}, {**policy, "shares": 1})


def test_capture_uses_calendar_and_daily_bar_calendar_date(monkeypatch):
    calls = []

    def provider(_client, url, params):
        calls.append((url, dict(params)))
        if url == capture.CALENDAR:
            return [{"date": DAY.isoformat(), "open": "09:30", "close": "16:00"}]
        stock = {"t": replay._stamp(OPEN), "o": 100, "h": 101, "l": 99, "c": 100, "v": 100}
        daily = {**stock, "t": "2026-08-24T00:00:00Z"}
        return {"bars": {"SPY": [stock if params["timeframe"] == "1Min" else daily]},
                "next_page_token": None}

    monkeypatch.setattr(capture, "_read", provider)
    result = capture.capture(object(), [DAY])[0]
    assert len(calls) == 3
    assert all(p.get("feed", "sip") == "sip" and p.get("adjustment", "raw") == "raw" for _, p in calls)
    assert result["symbols"]["SPY"]["minutes"][0]["time"] == OPEN
    assert result["symbols"]["SPY"]["daily"][0]["date"] == "2026-08-24"


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
