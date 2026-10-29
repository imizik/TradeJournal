"""live.py: live SessionData from an injected HTTP getter (no network)."""

from datetime import datetime

import pytest

from research.opening_lab import data, live
from research.opening_lab.contract import ET, et_datetime, et_hhmm
from research.opening_lab.tests.test_data import DAY, PRIOR, put_lab_daily, put_main_minutes, raw_day


@pytest.fixture
def cached(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAIN_CACHE_DIR", tmp_path / "main")
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path / "lab")
    monkeypatch.setattr(data, "_request", lambda *a, **k: pytest.fail("network used"))
    for d in PRIOR:
        put_main_minutes(tmp_path / "main", d, volume=200)
    put_lab_daily(tmp_path / "lab", PRIOR)
    return tmp_path


def fake_get(calls, end="09:36"):
    """Serves today's bars 04:00..end in two pages; records every call."""
    bars = raw_day(DAY, start="04:00", end=end)

    def get(url, params, headers):
        calls.append((url, dict(params), headers))
        if "page_token" not in params:
            return {"bars": {"SPY": bars, "QQQ": []}, "next_page_token": "next"}
        return {"bars": {"QQQ": bars}, "next_page_token": None}

    return get


def test_live_session_drops_forming_bar_and_records_provenance(cached):
    calls = []
    now = et_datetime(DAY, "09:35").replace(second=30)  # 09:35 bar is still forming
    s = live.live_session(DAY, now, http_get=fake_get(calls))

    for sym in data.SYMBOLS:
        mins = s["symbols"][sym]["minutes"]
        assert et_hhmm(mins[-1]["t"]) == "09:34"
        assert all(b["t"] + 60 <= now.timestamp() for b in mins)
        assert et_hhmm(mins[0]["t"]) == "04:00"
        assert [d["date"] for d in s["symbols"][sym]["daily"]] == PRIOR
        assert s["symbols"][sym]["volume_profile"]["09:30"] == pytest.approx(200.0)
    prov = s["provenance"]
    assert prov["feed"] == "sip" and len(prov["received_at"]) == 2
    assert prov["minutes"]["SPY"]["forming_dropped"] == 1  # the 09:35 bar
    assert prov["minutes"]["SPY"]["last_bar_end"] == int(et_datetime(DAY, "09:35").timestamp())
    assert s["news"] == [] and s["macro"] == [] and s["schedule"]["early_close"] is False
    url, params, headers = calls[0]
    assert url == data.DATA_URL and params["feed"] == "sip" and params["timeframe"] == "1Min"
    assert params["end"] == "2026-10-12T13:35:30Z" and params["start"] == "2026-10-12T08:00:00Z"
    assert headers == {}  # injected getter gets no credentials


def test_live_session_feed_override_and_validation(cached):
    calls = []
    now = et_datetime(DAY, "09:40")
    s = live.live_session(DAY, now, http_get=fake_get(calls, end="09:40"), feed="iex")
    assert s["provenance"]["feed"] == "iex" and calls[0][1]["feed"] == "iex"
    assert et_hhmm(s["symbols"]["QQQ"]["minutes"][-1]["t"]) == "09:39"
    with pytest.raises(ValueError):
        live.live_session(DAY, datetime(2026, 10, 12, 9, 40), http_get=fake_get([]))  # naive
    with pytest.raises(ValueError):
        live.live_session("2026-10-13", now, http_get=fake_get([]))  # wrong day


def test_missing_prior_daily_is_a_gap_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "MAIN_CACHE_DIR", tmp_path / "main")
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path / "lab")
    s = live.live_session(DAY, et_datetime(DAY, "09:35"), http_get=lambda u, p, h: {"bars": {}})
    assert s["symbols"]["SPY"]["minutes"] == []
    assert "SPY:no_completed_bars" in s["provenance"]["gaps"]
    assert s["symbols"]["SPY"]["daily"] == []
