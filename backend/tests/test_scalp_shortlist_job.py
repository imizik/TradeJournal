from datetime import date, datetime
import json

import pytest

from app.engine.scalp_shortlist import (
    FeedUnavailable,
    SESSIONS,
    StudyError,
    _previous_sessions,
    capture_live,
    load_universe,
    make_recap,
    rank_picks,
    warmup,
)


def bars(returns=None, volume=100):
    returns = returns or {}
    result = {}
    for symbol, pct in returns.items():
        start = 100.0
        close = start * (1 + pct)
        result[symbol] = {
            0: {"o": start, "h": start, "l": start, "c": start, "v": volume},
            9: {"o": start, "h": max(start, close), "l": min(start, close), "c": close, "v": volume},
            11: {"o": start, "h": start, "l": start, "c": start, "v": volume},
            21: {"o": close, "h": close, "l": close, "c": close, "v": volume},
        }
    return result


def test_fixed_study_dates_and_146_stock_list():
    assert len(SESSIONS) == 20
    assert SESSIONS[0] == "2026-11-04" and SESSIONS[-1] == "2026-12-02"
    assert date(2026, 11, 26).isoformat() not in SESSIONS
    assert len(load_universe()) == 146
    assert date(2026, 10, 12) in _previous_sessions(date(2026, 11, 4))


def test_rank_uses_directional_stock_sector_lead_and_biggest_mover_side():
    stocks = {"UP": "SECTOR_UP", "DOWN": "SECTOR_DOWN", "FLAT": "SECTOR_FLAT"}
    rows = bars({"UP": .03, "SECTOR_UP": .01, "DOWN": -.03,
                 "SECTOR_DOWN": -.01, "FLAT": .02, "SECTOR_FLAT": .03})
    baseline = [{symbol: 100 for symbol in stocks} for _ in range(20)]
    eligible, picks, movers = rank_picks(rows, baseline, stocks)
    assert eligible == 3
    assert [(pick["symbol"], pick["direction"]) for pick in picks] == [("DOWN", "down"), ("UP", "up")]
    assert [(pick["symbol"], pick["direction"]) for pick in movers] == [
        ("DOWN", "down"), ("UP", "up"), ("FLAT", "up")]


def test_incomplete_baseline_refuses_to_rank():
    with pytest.raises(StudyError, match="20-session"):
        rank_picks({}, [], {"UP": "SECTOR"})


def test_warmup_caches_daily_volumes_and_both_feed_baselines(tmp_path):
    calls = []
    stocks = {"ABC": "SPY"}

    def fetch(day, *, feed, symbols, start_minute, end_minute):
        calls.append((day, feed))
        return bars({symbol: .01 for symbol in symbols})

    first = warmup(date(2026, 11, 4), root=tmp_path, fetch=fetch, stocks=stocks)
    assert len(first["sessions"]) == 20
    assert first["baseline_feeds"] == ["iex", "sip"]
    assert len(calls) == 40
    second = warmup(date(2026, 11, 5), root=tmp_path, fetch=fetch, stocks=stocks)
    assert second["sessions"][-1] == "2026-11-04"
    assert calls[-2:] == [(date(2026, 11, 4), "iex"), (date(2026, 11, 4), "sip")]


def test_live_slate_falls_back_to_same_feed_and_is_immutable(tmp_path):
    day = date(2026, 11, 4)
    stocks = {"ABC": "SPY"}
    warmup(day, root=tmp_path, fetch=lambda *_a, **_k: bars({"ABC": .01, "SPY": 0}), stocks=stocks)

    def fetch(request_day, *, feed, **_kwargs):
        if request_day != day:
            return bars({"ABC": .01, "SPY": 0})
        if feed == "sip":
            raise FeedUnavailable("Restricted live SIP feed.")
        return bars({"ABC": .02, "SPY": 0}, volume=250)

    def now():
        return datetime.fromisoformat("2026-11-04T09:40:05-05:00")
    record = capture_live(day, root=tmp_path, now=now, fetch=fetch, stocks=stocks)
    assert record["feed"] == "iex" and record["picks"][0]["symbol"] == "ABC"
    def stale_fetch(*_args, **_kwargs):
        pytest.fail("published picks must never be recomputed")
    assert capture_live(day, root=tmp_path, now=now, fetch=stale_fetch, stocks=stocks) == record
    assert capture_live(day, root=tmp_path, now=lambda: datetime.fromisoformat("2026-11-04T09:41:00-05:00"),
                        fetch=stale_fetch, stocks=stocks) == record


def test_unavailable_live_data_never_becomes_valid_zero_pick_session(tmp_path):
    day = date(2026, 11, 4)
    with pytest.raises(StudyError, match="unavailable"):
        capture_live(day, root=tmp_path, now=lambda: datetime.fromisoformat("2026-11-04T09:40:05-05:00"),
                     fetch=lambda *_a, **_k: {})
    assert not (tmp_path / day.isoformat() / "live.json").exists()


def test_recap_scores_shown_picks_and_survives_missing_live_slate(tmp_path):
    day = date(2026, 11, 4)
    stocks = {"ABC": "SPY"}
    warmup(day, root=tmp_path, fetch=lambda *_a, **_k: bars({"ABC": .01, "SPY": 0}), stocks=stocks)
    live = {"day": day.isoformat(), "captured_at": "2026-11-04T09:40:05-05:00", "feed": "iex",
            "eligible": 1, "picks": [{"symbol": "ABC", "direction": "up"}], "movers": []}
    (tmp_path / day.isoformat()).mkdir()
    (tmp_path / day.isoformat() / "live.json").write_text(json.dumps(live))

    def fetch(request_day, *, feed, **_kwargs):
        return bars({"ABC": .04, "SPY": 0})

    recap = make_recap(day, root=tmp_path, fetch=fetch,
                       now=lambda: datetime.fromisoformat("2026-11-04T10:15:00-05:00"), stocks=stocks)
    assert recap["shown"] == [{"symbol": "ABC", "direction": "up", "return_pct": 4.0}]
    assert recap["movers"]
    # An official result can be recovered without inventing a live slate.
    next_day = date(2026, 11, 5)
    warmup(next_day, root=tmp_path, fetch=lambda *_a, **_k: bars({"ABC": .01, "SPY": 0}), stocks=stocks)
    no_live = make_recap(next_day, root=tmp_path, fetch=fetch,
                         now=lambda: datetime.fromisoformat("2026-11-05T10:15:00-05:00"), stocks=stocks)
    assert no_live["shown"] == [] and no_live["eligible"] == 1


def test_provider_keeps_exact_bar_bounds_and_distinguishes_entitlement(monkeypatch):
    import httpx
    from app.engine import scalp_shortlist as study

    day = date(2026, 11, 4)
    calls = []
    def fetch(url, *, params, headers, timeout):
        calls.append(params)
        return httpx.Response(200, json={"bars": {}})
    monkeypatch.setattr(study.market_http, "get", fetch)
    for minute in (9, 21):
        study._request_bars(day, feed="sip", symbols=["TEST"], start_minute=0, end_minute=minute)
    assert [q["end"] for q in calls] == ["2026-11-04T14:39:00+00:00", "2026-11-04T14:51:00+00:00"]
    assert all(q["asof"] == "2026-11-03" for q in calls)
    for status, message, expected in [(403, "subscription does not permit querying recent SIP data", FeedUnavailable),
                                      (403, "forbidden", StudyError), (429, "rate limited", StudyError)]:
        monkeypatch.setattr(study.market_http, "get", lambda *a, **kw: httpx.Response(status, text=message))
        with pytest.raises(expected) as caught:
            study._request_bars(day, feed="sip", symbols=["TEST"], start_minute=0, end_minute=9)
        assert type(caught.value) is expected


def test_feed_wide_delayed_exit_can_be_recovered(tmp_path):
    day = date(2026, 11, 4)
    stocks = {"ABC": "SPY"}
    def fetch(*args, **kwargs):
        return bars({"ABC": .04, "SPY": 0})
    def delayed(*args, **kwargs):
        result = fetch()
        for minutes in result.values():
            minutes.pop(21)
        return result

    warmup(day, root=tmp_path, fetch=fetch, stocks=stocks)
    def clock():
        return datetime.fromisoformat("2026-11-04T10:20:00-05:00")
    with pytest.raises(StudyError, match="scoring window"):
        make_recap(day, root=tmp_path, now=clock, fetch=delayed, stocks=stocks)
    assert not (tmp_path / day.isoformat() / "recap.json").exists()
    assert make_recap(day, root=tmp_path, now=clock, fetch=fetch, stocks=stocks)["eligible"] == 1
