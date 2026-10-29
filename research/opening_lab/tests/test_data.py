"""data.py: normalization, cache sources, calendar and the fetch path (no network)."""

import json
from datetime import datetime, timedelta

import pytest

from research.opening_lab import data
from research.opening_lab.contract import ET, UTC, et_datetime, et_hhmm


def iso(day, hhmm, minute_offset=0):
    dt = et_datetime(day, hhmm) + timedelta(minutes=minute_offset)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_day(day, volume=100, start="04:00", end="20:00", skip=()):
    """Raw Alpaca-style minute bars from start to end (exclusive) ET."""
    bars, t, stop = [], et_datetime(day, start), et_datetime(day, end)
    while t < stop:
        if et_hhmm(int(t.timestamp())) not in skip:
            bars.append({"t": t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": 100.0, "h": 101.0,
                         "l": 99.0, "c": 100.5, "v": volume, "n": 10, "vw": 100.2})
        t += timedelta(minutes=1)
    return bars


def raw_daily(day, close=100.0):
    return {"t": iso(day, "00:00"), "o": 99.0, "h": 101.0, "l": 98.0, "c": close, "v": 1_000_000, "n": 5, "vw": 100.0}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    main, lab = tmp_path / "main", tmp_path / "lab"
    monkeypatch.setattr(data, "MAIN_CACHE_DIR", main)
    monkeypatch.setattr(data, "CACHE_DIR", lab)
    monkeypatch.setattr(data, "_request", lambda *a, **k: pytest.fail("network used"))
    return main, lab


def put_main_minutes(main, day, volume=100, **kw):
    for sym in data.SYMBOLS:
        path = main / "1Min" / "sip" / sym / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw_day(day, volume, **kw)))


def put_main_daily(main, days):
    for sym in data.SYMBOLS:
        path = main / "1Day" / "sip" / f"{sym}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([raw_daily(d, 100 + i) for i, d in enumerate(days)]))


PRIOR = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
DAY = "2026-10-12"


def test_normalize_bars_cleans_and_counts():
    day = DAY
    good = raw_day(day, start="09:30", end="09:32")
    raw = [good[1], good[0], good[0],  # out of order plus a duplicate
           {**good[0], "t": iso(day, "09:40"), "c": float("nan")},
           {**good[0], "t": iso(day, "09:41"), "o": -1},
           {**good[0], "t": iso(day, "09:42"), "h": 98.0},  # high below low
           {"t": iso(day, "09:43")},  # missing fields
           {**good[0], "t": iso(day, "03:00")}, {**good[0], "t": iso(day, "11:00")},  # outside window
           {**good[0], "t": iso(day, "09:50"), "vw": None, "n": None}]
    bars, stats = data.normalize_bars(raw, day)
    assert [et_hhmm(b["t"]) for b in bars] == ["09:30", "09:31", "09:50"]
    assert bars[2]["vw"] is None and bars[2]["n"] is None
    assert isinstance(bars[0]["t"], int) and isinstance(bars[0]["v"], int)
    assert stats["malformed"] == 4 and stats["outside_window"] == 2 and stats["duplicates"] == 1


def test_load_session_from_main_cache(dirs):
    main, _ = dirs
    for i, d in enumerate(PRIOR):
        put_main_minutes(main, d, volume=100 * (i + 1))
    put_main_minutes(main, DAY)
    put_main_daily(main, PRIOR + [DAY])
    s = data.load_session(DAY)

    assert s["date"] == DAY and s["news"] == [] and s["macro"] == []
    assert s["schedule"] == {"open": "09:30", "close": "16:00", "early_close": False}
    spy = s["symbols"]["SPY"]
    ts = [b["t"] for b in spy["minutes"]]
    assert ts == sorted(set(ts))
    assert et_hhmm(ts[0]) == "04:00" and et_hhmm(ts[-1]) == "10:59" and len(ts) == 420
    assert [d["date"] for d in spy["daily"]] == PRIOR  # strictly before the session
    assert spy["volume_profile"]["09:30"] == pytest.approx(300.0)  # mean of 100..500
    assert list(spy["volume_profile"])[0] == "09:30" and list(spy["volume_profile"])[-1] == "10:59"
    assert len(spy["volume_profile"]) == 90
    prov = s["provenance"]
    assert prov["feed"] == "sip" and prov["minutes"]["SPY"]["source"] == "main_cache"
    assert prov["volume_profile"]["SPY"]["sessions_used"] == 5
    assert "SPY:volume_profile_sessions=5" in prov["gaps"]
    json.dumps(s)  # JSON-serializable


def test_unusable_sessions_raise(dirs):
    main, _ = dirs
    put_main_minutes(main, DAY, start="04:00", end="09:00")
    with pytest.raises(data.SessionUnavailable):  # file stops before the kept window: treated as uncached
        data.load_session(DAY)
    put_main_minutes(main, DAY, skip={f"09:{m:02d}" for m in range(30, 60)} | {f"10:{m:02d}" for m in range(0, 15)})
    with pytest.raises(data.SessionUnavailable):  # too few RTH minutes
        data.load_session(DAY)
    with pytest.raises(data.SessionUnavailable):  # nothing cached at all
        data.load_session("2026-10-13")


def test_partial_gap_is_recorded_not_fatal(dirs):
    main, _ = dirs
    put_main_minutes(main, DAY, skip={"09:45", "09:46"})
    s = data.load_session(DAY)
    assert "QQQ:missing_minutes_0930_1030=2" in s["provenance"]["gaps"]


def test_derived_calendar_skips_weekends_and_missing_days(dirs):
    main, _ = dirs
    for d in ("2026-10-09", "2026-10-12"):
        put_main_minutes(main, d)
    assert data.trading_days("2026-10-08", "2026-10-13") == ["2026-10-09", "2026-10-12"]


def calendar_rows(days, early=()):
    return [{"date": d, "open": "09:30", "close": "13:00" if d in early else "16:00"} for d in days]


def test_calendar_fetch_cache_and_early_close(dirs, monkeypatch):
    main, lab = dirs
    calls = []

    def fake(url, params):
        calls.append((url, params))
        return calendar_rows(["2026-11-25", "2026-11-27"], early={"2026-11-27"})

    monkeypatch.setattr(data, "_request", fake)
    assert data.trading_days("2026-11-23", "2026-11-30", fetch=True) == ["2026-11-25", "2026-11-27"]
    assert data.trading_days("2026-11-24", "2026-11-29") == ["2026-11-25", "2026-11-27"]  # served from cache
    assert len(calls) == 1 and calls[0][0] == data.CALENDAR_URL
    cal, source = data.calendar("2026-11-24", "2026-11-29")
    assert source == "alpaca" and cal["2026-11-27"]["close"] == "13:00"


def test_early_close_schedule_and_profile_skips_it(dirs, monkeypatch):
    main, lab = dirs
    days = PRIOR + [DAY]
    for i, d in enumerate(PRIOR):
        put_main_minutes(main, d, volume=100 * (i + 1))
    put_main_minutes(main, DAY)
    put_main_daily(main, days)
    monkeypatch.setattr(data, "_request", lambda url, params: calendar_rows(days, early={"2026-10-07", DAY}))
    data.calendar("2026-07-01", DAY, fetch=True)
    monkeypatch.setattr(data, "_request", lambda *a, **k: pytest.fail("network used"))
    s = data.load_session(DAY)
    assert s["schedule"] == {"open": "09:30", "close": "13:00", "early_close": True}
    assert s["provenance"]["volume_profile"]["SPY"]["sessions_used"] == 4  # Oct 7 skipped
    assert s["symbols"]["SPY"]["volume_profile"]["09:30"] == pytest.approx((100 + 200 + 400 + 500) / 4)


def test_fetch_writes_lab_cache_only_and_skips_incomplete_day(dirs, monkeypatch):
    main, lab = dirs
    monkeypatch.setattr(data, "_session_complete", lambda d, now=None: d != "2026-10-13")
    requests = []

    def fake(url, params):
        requests.append(params)
        if url == data.CALENDAR_URL:
            return calendar_rows(["2026-10-09", "2026-10-12", "2026-10-13"])
        if params["timeframe"] == "1Day":
            return {"bars": {s: [raw_daily("2026-10-09"), raw_daily("2026-10-12")] for s in data.SYMBOLS}}
        if "page_token" not in params:  # first page: SPY; second page: QQQ
            return {"bars": {"SPY": raw_day("2026-10-09") + raw_day("2026-10-12")}, "next_page_token": "p2"}
        return {"bars": {"QQQ": raw_day("2026-10-09") + raw_day("2026-10-12")}, "next_page_token": None}

    monkeypatch.setattr(data, "_request", fake)
    summary = data.prefetch("2026-10-09", "2026-10-13")
    assert summary["sessions"] == 3
    assert (lab / "minutes" / "SPY" / "2026-10-12.json").exists()
    assert not (lab / "minutes" / "SPY" / "2026-10-13.json").exists()  # today is not complete
    assert summary["minute_days_still_missing"] == ["2026-10-13"]
    assert not main.exists()  # never written
    assert all(p["feed"] == "sip" and p["adjustment"] == "raw" for p in requests if "timeframe" in p)

    s = data.load_session("2026-10-12")
    assert s["provenance"]["minutes"]["QQQ"]["source"] == "lab_cache"
    assert [d["date"] for d in s["symbols"]["SPY"]["daily"]] == ["2026-10-09"]
    with pytest.raises(data.SessionUnavailable):
        data.load_session("2026-10-13")
    # A second prefetch finds everything cached and makes no further minute requests.
    n = len(requests)
    data.prefetch("2026-10-09", "2026-10-12")
    assert len([r for r in requests[n:] if r.get("timeframe") == "1Min"]) == 0


def test_not_a_trading_day(dirs, monkeypatch):
    monkeypatch.setattr(data, "_request", lambda url, params: calendar_rows(["2026-10-09", "2026-10-12"]))
    data.calendar("2026-07-01", "2026-10-31", fetch=True)
    with pytest.raises(data.SessionUnavailable, match="not a trading day"):
        data.load_session("2026-10-10")


def test_fetch_defaults_off(dirs):
    with pytest.raises(data.SessionUnavailable, match="fetch=True"):
        data.load_session(DAY)  # _request would fail the test if touched
