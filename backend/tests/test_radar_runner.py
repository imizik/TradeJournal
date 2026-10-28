"""Radar PR 1: the once-a-minute quote recorder and its startup gate."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.engine import radar_runner, tradier
from app.engine.chart_math import ET
from app.engine.radar_runner import RadarRunner
from app.engine.radar_store import RadarStore
from app.engine.tradier import TradierError, TradierQuote

OPEN = {"status": "open", "open": 570, "close": 960}
EARLY = {"status": "open", "open": 570, "close": 780}
CLOSED = {"status": "closed", "open": None, "close": None}


class Calendar:
    def __init__(self, hours):
        self.value = hours

    def hours(self, day):
        return self.value


def _at(hour, minute, day=20):
    return lambda: datetime(2026, 10, day, hour, minute, 5, tzinfo=ET).timestamp()


def _universe(count):
    return {"version": "radar-universe-test", "symbols": [{"symbol": f"S{i:03d}", "kind": "stock"} for i in range(count)],
            "groups": []}


class Quotes:
    def __init__(self, fail_on=None, missing=()):
        self.calls, self.fail_on, self.missing = [], fail_on, set(missing)

    def __call__(self, symbols):
        self.calls.append(list(symbols))
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise TradierError("Tradier rate limited /v1/markets/quotes")
        return {s: TradierQuote(symbol=s, last=10.0, bid=9.9, ask=10.1, volume=500, trade_date=1792500000000,
                                raw={"prevclose": "9.5", "open": "9.6", "high": "10.2", "low": "9.4"})
                for s in symbols if s not in self.missing}


def _runner(tmp_path, hours=OPEN, clock=_at(10, 0), count=120, quotes=None):
    quotes = quotes or Quotes()
    store = RadarStore(tmp_path / "radar.sqlite")
    return RadarRunner(store, Calendar(hours), universe=_universe(count), quotes=quotes, clock=clock), store, quotes


@pytest.mark.parametrize("hours,clock", [
    (OPEN, _at(9, 29)), (OPEN, _at(16, 0)), (CLOSED, _at(11, 0)),  # before the open, at the close, a holiday
    (EARLY, _at(13, 0)), (EARLY, _at(14, 30)),  # after an early close
    (None, _at(11, 0, day=24)),  # calendar unavailable on a Saturday
])
def test_no_pass_outside_regular_hours(tmp_path, hours, clock):
    runner, store, quotes = _runner(tmp_path, hours, clock)
    assert runner.run_once() is None
    assert quotes.calls == [] and store.passes() == []


def test_unavailable_calendar_in_clock_hours_records_a_skip(tmp_path):
    runner, store, quotes = _runner(tmp_path, None, _at(11, 0))
    runner.run_once()
    [row] = store.passes()
    assert quotes.calls == [] and row["status"] == "skipped" and row["skip_reason"] == "calendar_unavailable"


def test_pass_batches_by_fifty_and_records_quotes_and_unmatched(tmp_path):
    runner, store, quotes = _runner(tmp_path, EARLY, _at(12, 59), count=120, quotes=Quotes(missing={"S007", "S110"}))
    pass_id = runner.run_once()
    assert [len(c) for c in quotes.calls] == [50, 50, 20]
    [row] = store.passes()
    assert row["status"] == "ok" and row["requests_used"] == 3 and row["symbols_requested"] == 120
    assert row["symbols_returned"] == 118 and row["unmatched"] == ["S007", "S110"]
    assert row["universe_version"] == "radar-universe-test" and row["session_date"] == "2026-10-20"
    quote = store.quotes(pass_id)[0]
    assert (quote["last"], quote["prev_close"], quote["open"], quote["high"], quote["low"]) == (10.0, 9.5, 9.6, 10.2, 9.4)
    assert (quote["volume"], quote["bid"], quote["ask"], quote["trade_time_ms"]) == (500, 9.9, 10.1, 1792500000000)
    assert quote["retrieved_at"].startswith("2026-10-20T16:59:05")


def test_request_cap_limits_a_pass_to_six_requests(tmp_path):
    runner, store, quotes = _runner(tmp_path, count=320)
    runner.run_once()
    assert len(quotes.calls) == 6
    [row] = store.passes()
    assert row["status"] == "partial" and row["symbols_requested"] == 300 and "20 symbols not requested" in row["error"]


@pytest.mark.parametrize("fail_on,status,returned", [(1, "failed", 0), (2, "partial", 50)])
def test_rate_limit_ends_the_pass_without_retry(tmp_path, fail_on, status, returned):
    runner, store, quotes = _runner(tmp_path, count=120, quotes=Quotes(fail_on=fail_on))
    runner.run_once()
    assert len(quotes.calls) == fail_on  # nothing retried, later batches not sent
    [row] = store.passes()
    assert row["status"] == status and row["symbols_returned"] == returned and "rate limited" in row["error"]
    assert row["requests_used"] == fail_on


def test_default_quotes_make_one_attempt(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(tradier, "_post", lambda path, payload, attempts: calls.append(attempts) or {})
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    assert RadarRunner(RadarStore(tmp_path / "r.sqlite"), Calendar(OPEN)).quotes is tradier.get_quotes_once
    tradier.get_quotes_once(["SPY"])
    assert calls == [1]


def test_startup_is_off_unless_enabled_with_an_absolute_store_and_tradier(monkeypatch, tmp_path):
    from app import main
    for name in ("RADAR_ENABLED", "RADAR_STORE", "TJ_DOT_TRIAL_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    app_ = SimpleNamespace(state=SimpleNamespace())
    assert asyncio.run(main._maybe_start_radar(app_)) is None and app_.state.radar is None
    monkeypatch.setenv("RADAR_ENABLED", "true")
    assert radar_runner.runner_from_env() is None  # no store
    monkeypatch.setenv("RADAR_STORE", "radar.sqlite")
    assert radar_runner.runner_from_env() is None  # relative store
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    assert isinstance(radar_runner.runner_from_env(), RadarRunner)
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "")
    assert radar_runner.runner_from_env() is None  # Tradier unconfigured
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    monkeypatch.setenv("TJ_DOT_TRIAL_ENABLED", "true")
    assert asyncio.run(main._maybe_start_radar(app_)) is None and app_.state.radar is None


def test_bad_store_never_stops_the_api(monkeypatch, tmp_path):
    import sqlite3
    from app import main
    foreign = tmp_path / "foreign.sqlite"
    sqlite3.connect(foreign).execute("CREATE TABLE fills(id)").connection.commit()
    monkeypatch.delenv("TJ_DOT_TRIAL_ENABLED", raising=False)
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(foreign))
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    app_ = SimpleNamespace(state=SimpleNamespace())
    assert asyncio.run(main._maybe_start_radar(app_)) is None and app_.state.radar is None


def test_live_receipt_records_zero_events_and_detector_failure(tmp_path, monkeypatch):
    runner, store, _ = _runner(tmp_path)
    monkeypatch.setattr(runner, "detect", lambda *args: ([], []))
    first = runner.run_once()
    receipts, configs = store.detection_evidence()
    assert receipts[first]["origin"] == "live" and receipts[first]["status"] == "ok"
    assert receipts[first]["event_ids"] == [] and receipts[first]["hours"] == OPEN
    assert configs[receipts[first]["config_digest"]]["universe"] == runner.universe
    def fail(*args):
        raise RuntimeError("synthetic detector failure")
    monkeypatch.setattr(runner, "detect", fail)
    second = runner.run_once()
    receipts, _ = store.detection_evidence()
    assert store.passes()[-1]["status"] == "ok"
    assert receipts[second]["status"] == "failed"
