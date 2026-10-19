"""Recorded-shape, invented prices: Tradier boundaries and fixed request budget."""
from datetime import timedelta
import json
from pathlib import Path
import sys
from unittest.mock import Mock
import urllib.error
import urllib.parse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import advisor_forecast as core  # noqa: E402
import advisor_forecast_runtime as runtime  # noqa: E402


def provider_bar(day="2026-10-16", minute="09:30:00"):
    return {"time": day + "T" + minute, "open": 100, "high": 102, "low": 99,
            "close": 101, "volume": 50}


def transport(monkeypatch, body):
    monkeypatch.setenv("TRADIER_API_KEY", "synthetic-only")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(body).encode()
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(runtime.urllib.request, "build_opener", lambda *args: opener)
    return opener


def test_exchange_timezone_inclusive_end_and_one_bounded_get(monkeypatch):
    opener = transport(monkeypatch, {"series": {"data": [provider_bar(), provider_bar(minute="09:31:00")]}})
    rows = runtime.tradier_bars("MU", "2026-10-16", "09:30:00", "2026-10-16", "09:31:00")
    assert [r["t"] for r in rows] == ["2026-10-16T09:30:00-04:00", "2026-10-16T09:31:00-04:00"]
    assert rows[0]["c"] == 101
    request = opener.open.call_args.args[0]
    assert request.get_method() == "GET"
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query) == {
        "symbol": ["MU"], "interval": ["1min"], "session_filter": ["open"],
        "start": ["2026-10-16 09:30"], "end": ["2026-10-16 09:31"]}
    assert opener.open.call_args.kwargs["timeout"] == 10
    opener.open.assert_called_once()


def test_winter_offset_and_single_object_shape(monkeypatch):
    transport(monkeypatch, {"series": {"data": provider_bar("2026-11-02")}})
    assert runtime.tradier_bars("JPM", "2026-11-02", "09:30:00", "2026-11-02", "09:30:00")[0]["t"].endswith("-05:00")


@pytest.mark.parametrize("change", ["future", "duplicate", "unordered", "symbol", "ohlc", "negative_volume", "seconds", "empty"])
def test_provider_rejects_corrupt_or_out_of_window_data(monkeypatch, change):
    bars = [provider_bar(), provider_bar(minute="09:31:00")]
    if change == "future":
        bars.append(provider_bar(minute="09:32:00"))
    elif change == "duplicate":
        bars[1] = bars[0]
    elif change == "unordered":
        bars.reverse()
    elif change == "symbol":
        bars[0]["symbol"] = "NVDA"
    elif change == "ohlc":
        bars[0]["high"] = 99
    elif change == "negative_volume":
        bars[0]["volume"] = -1
    elif change == "seconds":
        bars[0]["time"] = "2026-10-16T09:30:01"
    else:
        bars = []
    transport(monkeypatch, {"series": {"data": bars}})
    with pytest.raises(ValueError):
        runtime.tradier_bars("MU", "2026-10-16", "09:30:00", "2026-10-16", "09:31:00")


def test_rate_limit_never_retries_or_changes_provider(monkeypatch):
    opener = transport(monkeypatch, {})
    opener.open.side_effect = urllib.error.HTTPError(runtime.DATA_URL, 429, "limited", {}, None)
    with pytest.raises(ValueError, match="no retry"):
        runtime.tradier_bars("MU", "2026-10-16", "09:30:00", "2026-10-16", "09:31:00")
    opener.open.assert_called_once()


def test_history_uses_seven_range_requests_and_exact_twenty_windows(monkeypatch):
    spec = core.read_json(core.SPEC_DIR / "spec.json")
    days = [(core.at("2098-01-01", "00:00") + timedelta(days=i)).date().isoformat() for i in range(20)]
    full = [bar for day in days for bar in core.fixture_bars(day, 570, 390 if day != days[-1] else 90)]
    fetch = Mock(return_value=full)
    monkeypatch.setattr(runtime, "tradier_bars", fetch)
    history = runtime.fetch_history(days, spec)
    assert fetch.call_count == 7
    assert all(len(history[t][d]) == 90 for t in spec["tickers"] for d in days)
    assert fetch.call_args.args[1:] == (days[0], "09:30:00", days[-1], "10:59:00")
    full.pop(0)
    with pytest.raises(ValueError, match="every expected minute"):
        runtime.fetch_history(days, spec)


def test_current_capture_seven_requests_and_deadline_rejects_late_completion(monkeypatch, tmp_path):
    spec = core.with_timing(core.read_json(core.SPEC_DIR / "spec.json"), 0)
    fetch = Mock(return_value=core.fixture_bars("2098-02-01", 570, 29))
    monkeypatch.setattr(runtime, "tradier_bars", fetch)
    assert set(runtime.fetch_bars("2098-02-01", "09:30:00", "09:58:00", spec)) == set(spec["tickers"])
    assert fetch.call_count == 7
    monkeypatch.setattr(runtime, "STATE", tmp_path)
    monkeypatch.setattr(runtime, "BASELINES", tmp_path / "baseline")
    day = "2098-02-01"
    prior = [f"2098-01-{i:02d}" for i in range(1, 21)]
    for ticker in spec["tickers"]:
        packet = core.snapshot(day, ticker, core.fixture_bars(day, count=29),
                               {d: core.fixture_bars(d) for d in prior}, prior, core.at(day, "10:00:05"), spec)
        core.exclusive_json(tmp_path / "snapshots" / day / f"{ticker}.json", packet)
    monkeypatch.setattr(runtime, "now", Mock(side_effect=[core.at(day, "10:02:00"), core.at(day, "10:02:00"), core.at(day, "10:02:31")]))
    monkeypatch.setattr(runtime, "fetch_bars", Mock(return_value={t: core.fixture_bars(day, 570, 32) for t in spec["tickers"]}))
    with pytest.raises(ValueError, match="capture window"):
        runtime.baseline_job(day, {}, spec)
    assert not (tmp_path / "baseline" / day / "manifest.json").exists()
