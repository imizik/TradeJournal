"""Radar premarket pilot: checkpoint timing, the frozen v0 rule, the scan and its separate file, and the scorer."""
from datetime import datetime
import sqlite3
import sys

import pytest

from app.engine import radar_premarket, radar_runner
from app.engine.chart_math import ET
from app.engine.radar_premarket import PremarketScanner, PremarketStore, apply_rule, due_checkpoint, summarize
from app.engine.radar_runner import RadarRunner
from app.engine.radar_store import RadarStore
from app.engine.tradier import TradierError, TradierQuote

OPEN = {"status": "open", "open": 570, "close": 960}
CLOSED = {"status": "closed", "open": None, "close": None}
UNIVERSE = {"version": "radar-universe-test", "groups": [], "symbols": [
    {"symbol": "SPY", "kind": "etf", "benchmark": True},
    {"symbol": "XLK", "kind": "etf", "benchmark": True},
    {"symbol": "UPP", "kind": "stock", "benchmark": False},
    {"symbol": "DWN", "kind": "stock", "benchmark": False},
    {"symbol": "THIN", "kind": "stock", "benchmark": False},
    {"symbol": "OLD", "kind": "stock", "benchmark": False},
    {"symbol": "FLAT", "kind": "stock", "benchmark": False},
]}


class Calendar:
    def __init__(self, hours):
        self.value = hours

    def hours(self, day):
        return self.value


def _ts(hour, minute, day=26):
    return datetime(2026, 10, day, hour, minute, tzinfo=ET).timestamp()


class Clock:
    """Starts at a wall time and advances by whatever the scanner sleeps."""

    def __init__(self, hour, minute, second=5, day=26):
        self.now = _ts(hour, minute, day) + second

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _bar(hour, minute, close, volume, day=26):
    return {"timestamp": int(_ts(hour, minute, day)), "open": close, "high": close, "low": close, "close": close, "volume": volume}


# Prior close 100 for every symbol. SPY +1%; UPP +6% on $600k; DWN -3% on $400k; THIN +8% on $50k;
# OLD +7% but its last trade was 07:00; FLAT +1.5%. A bar after the 08:50 checkpoint must not count.
BARS = {
    "SPY": [_bar(8, 0, 100.5, 5000), _bar(8, 48, 101.0, 5000)],
    "XLK": [_bar(8, 40, 105.0, 5000)],
    "UPP": [_bar(7, 30, 103.0, 3000), _bar(8, 45, 107.0, 3000), _bar(8, 52, 120.0, 99999)],
    "DWN": [_bar(8, 41, 98.0, 4082)],
    "THIN": [_bar(8, 44, 109.0, 459)],
    "OLD": [_bar(7, 0, 108.0, 9000)],
    "FLAT": [_bar(8, 49, 102.5, 9000)],
}


class Feed:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, path, params, ttl):
        self.calls.append((path, dict(params), ttl))
        if params["symbol"] in self.fail:
            raise RuntimeError("cooling down")
        return {"series": {"data": BARS.get(params["symbol"], [])}}, 0.0, None


class Quotes:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, symbols):
        self.calls.append(list(symbols))
        if self.fail:
            raise TradierError("Tradier rate limited /v1/markets/quotes")
        return {s: TradierQuote(symbol=s, last=100.0, trade_date=1792700000000, raw={"prevclose": "100"}) for s in symbols}


def _scanner(tmp_path, clock, *, hours=OPEN, feed=None, quotes=None):
    store = PremarketStore(tmp_path / "radar-premarket.sqlite")
    feed, quotes = feed or Feed(), quotes or Quotes()
    scanner = PremarketScanner(store, Calendar(hours), UNIVERSE, quotes=quotes, read=feed, clock=clock, sleep=clock.sleep)
    return scanner, store, feed, quotes


@pytest.mark.parametrize("hm,hours,day,expected", [
    ((8, 50), OPEN, 26, ("08:50", None)), ((8, 57), OPEN, 26, ("08:50", None)), ((8, 58), OPEN, 26, (None, None)),
    ((9, 20), OPEN, 26, ("09:20", None)), ((9, 28), OPEN, 26, (None, None)), ((8, 30), OPEN, 26, (None, None)),
    ((8, 50), CLOSED, 26, (None, None)),  # a holiday
    ((8, 50), None, 26, ("08:50", "calendar_unavailable")), ((8, 50), None, 24, (None, None)),  # weekday vs Saturday
    ((9, 20), {"status": "open", "open": 555, "close": 960}, 26, (None, None)),  # the session already open
])
def test_due_checkpoint(hm, hours, day, expected):
    assert due_checkpoint(Calendar(hours), datetime(2026, 10, day, *hm, 5, tzinfo=ET)) == expected


def test_summarize_counts_only_premarket_minutes_completed_by_the_cutoff():
    bars = [{"time": int(_ts(3, 59)), "close": 1.0, "volume": 10}, {"time": int(_ts(8, 0)), "close": 2.0, "volume": 10},
            {"time": int(_ts(8, 49)), "close": 3.0, "volume": 10}, {"time": int(_ts(8, 50)), "close": 4.0, "volume": 10}]
    out = summarize(bars, _ts(8, 50), datetime(2026, 10, 26).date())
    assert out["last"] == 3.0 and out["bars"] == 2 and out["volume"] == 20 and out["dollar_volume"] == 50.0
    assert out["last_bar_at"] == "2026-10-26T12:49:00.000Z"


def test_rule_needs_spy_volume_freshness_and_a_stock():
    def row(symbol, last, dollars, at=(8, 45)):
        stamp = datetime.fromtimestamp(_ts(*at), ET).astimezone().isoformat()
        return {"symbol": symbol, "prev_close": 100.0, "last": last, "dollar_volume": dollars, "last_bar_at": stamp}
    rows = [row("SPY", 101.0, 1e7), row("UPP", 104.0, 3e5), row("DWN", 98.0, 3e5), row("THIN", 110.0, 1e5),
            row("OLD", 110.0, 1e6, at=(8, 30)), row("XLK", 110.0, 1e7), row("FLAT", 103.9, 1e6)]
    assert apply_rule(rows, {"UPP", "DWN", "THIN", "OLD", "FLAT"}, _ts(8, 50)) == 2
    assert {r["symbol"] for r in rows if r["flagged"]} == {"UPP", "DWN"}
    assert next(r for r in rows if r["symbol"] == "DWN")["excess_pct"] == -3.0
    no_spy = [r for r in rows if r["symbol"] != "SPY"]
    assert apply_rule(no_spy, {"UPP"}, _ts(8, 50)) == 0 and no_spy[0]["excess_pct"] is None


def test_scan_records_one_frozen_list_per_checkpoint(tmp_path):
    clock = Clock(8, 50)
    scanner, store, feed, quotes = _scanner(tmp_path, clock)
    scan_id = scanner.run_once()
    [scan] = store.scans()
    assert scan["id"] == scan_id and scan["status"] == "ok" and scan["checkpoint"] == "08:50"
    assert scan["symbols_requested"] == scan["symbols_read"] == 7 and scan["requests_used"] == 8 and scan["flagged"] == 2
    assert scan["rule_version"] == "radar-premarket-v0" and scan["universe_version"] == "radar-universe-test"
    rows = {r["symbol"]: r for r in store.readings(scan_id)}
    assert rows["UPP"]["last"] == 107.0 and rows["UPP"]["excess_pct"] == 6.0  # the 08:52 bar is after the checkpoint
    assert {s for s, r in rows.items() if r["flagged"]} == {"UPP", "DWN"}
    assert feed.calls[0] == ("/v1/markets/timesales", {"symbol": "SPY", "interval": "1min", "session_filter": "all",
                                                       "start": "2026-10-26 04:00", "end": "2026-10-26 20:00"}, 15)
    assert clock.now - _ts(8, 50) >= 6 * 60 / radar_premarket.READS_PER_MINUTE * 0.99  # paced reads
    assert scanner.run_once() is None and len(feed.calls) == 7  # never twice
    with pytest.raises(sqlite3.DatabaseError):
        with sqlite3.connect(store.path) as db:
            db.execute("UPDATE premarket_reading SET flagged=0")


def test_scan_stops_at_its_deadline(tmp_path):
    clock = Clock(8, 57, second=20)  # 25 s left: one read at 40 a minute is 1.5 s, so some symbols go unread
    feed = Feed()
    scanner, store, _, _ = _scanner(tmp_path, clock, feed=feed)
    old = radar_premarket.READS_PER_MINUTE
    radar_premarket.READS_PER_MINUTE = 6  # 10 s apart
    try:
        scanner.run_once()
    finally:
        radar_premarket.READS_PER_MINUTE = old
    [scan] = store.scans()
    assert scan["status"] == "partial" and "deadline" in scan["error"] and scan["symbols_read"] < 7
    assert sum(r["read_error"] == "deadline" for r in store.readings(scan["id"])) == 7 - scan["symbols_read"]


def test_failed_reads_and_quotes_are_recorded_not_raised(tmp_path):
    scanner, store, _, _ = _scanner(tmp_path, Clock(8, 51), feed=Feed(fail={"DWN"}))
    scanner.run_once()
    [scan] = store.scans()
    assert scan["status"] == "partial" and scan["symbols_read"] == 6 and scan["flagged"] == 1
    assert "cooling down" in next(r for r in store.readings(scan["id"]) if r["symbol"] == "DWN")["read_error"]

    scanner, store, feed, _ = _scanner(tmp_path / "q", Clock(8, 51), quotes=Quotes(fail=True))
    scanner.run_once()
    [scan] = store.scans()
    assert scan["status"] == "failed" and scan["error"].startswith("quotes:") and feed.calls == []
    assert store.readings(scan["id"]) == []


def test_unavailable_calendar_records_a_skip(tmp_path):
    scanner, store, feed, quotes = _scanner(tmp_path, Clock(8, 50), hours=None)
    scanner.run_once()
    [scan] = store.scans()
    assert scan["status"] == "skipped" and scan["skip_reason"] == "calendar_unavailable" and feed.calls == quotes.calls == []


def test_store_is_separate_and_refuses_foreign_files(tmp_path):
    radar = tmp_path / "radar.sqlite"
    assert radar_premarket.store_path(radar) == tmp_path / "radar-premarket.sqlite"
    RadarStore(radar)
    with pytest.raises(ValueError):
        PremarketStore(radar)
    with pytest.raises(ValueError):
        RadarStore(PremarketStore(tmp_path / "radar-premarket.sqlite").path)
    with pytest.raises(ValueError):
        PremarketStore("relative.sqlite")


class Scanner:
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def run_once(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")


@pytest.mark.parametrize("hm,calls", [((8, 50), 1), ((10, 0), 0)])
def test_runner_hands_out_of_hours_minutes_to_the_scanner(tmp_path, hm, calls):
    scanner = Scanner(fail=True)
    store = RadarStore(tmp_path / "radar.sqlite")
    runner = RadarRunner(store, Calendar(OPEN), universe={"version": "v", "symbols": [], "groups": []},
                         quotes=lambda s: {}, clock=lambda: _ts(*hm) + 5, news=lambda *a: [], premarket=scanner)
    result = runner.run_once()
    assert scanner.calls == calls
    assert (result is None) == (calls == 1)


def test_runner_from_env_builds_the_scanner_only_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    monkeypatch.setattr(radar_runner.tradier, "tradier_configured", lambda: True)
    monkeypatch.delenv("RADAR_PREMARKET_ENABLED", raising=False)
    assert radar_runner.runner_from_env().premarket is None
    assert not (tmp_path / "radar-premarket.sqlite").exists()
    monkeypatch.setenv("RADAR_PREMARKET_ENABLED", "true")
    monkeypatch.setattr(radar_premarket, "PremarketScanner", lambda store, calendar, universe: ("scanner", store.path))
    assert radar_runner.runner_from_env().premarket == ("scanner", tmp_path / "radar-premarket.sqlite")


def test_eval_scores_the_list_against_radar_passes(tmp_path, monkeypatch, capsys):
    scanner, pre, _, _ = _scanner(tmp_path, Clock(8, 50))
    scanner.run_once()  # flags UPP (+6) and DWN (-3)
    radar = RadarStore(tmp_path / "radar.sqlite")
    for minute, moves in ((31, {"SPY": 0.0, "UPP": 7.0, "DWN": -1.0}), (32, {"SPY": 1.0, "UPP": 8.0, "DWN": -1.0})):
        at = datetime(2026, 10, 26, 9, minute, 5, tzinfo=ET)
        stamp = at.astimezone().isoformat()
        rows = [{"symbol": s, "last": 100 * (1 + m / 100), "prev_close": 100.0, "open": None, "high": None, "low": None,
                 "volume": 1, "bid": None, "ask": None, "trade_time_ms": int(at.timestamp() * 1000) - 1000, "retrieved_at": stamp}
                for s, m in moves.items()]
        radar.append_pass({"session_date": "2026-10-26", "started_at": stamp, "finished_at": stamp, "universe_version": "v",
                           "status": "ok", "symbols_requested": 3, "symbols_returned": 3, "unmatched": [], "requests_used": 1,
                           "error": None, "skip_reason": None}, rows)
    sys.path.insert(0, str(radar_premarket.Path(__file__).resolve().parent.parent / "scripts"))
    import radar_premarket_eval
    monkeypatch.setattr(sys, "argv", ["radar_premarket_eval.py", str(radar.path), "--checkpoint", "08:50"])
    radar_premarket_eval.main()
    out = capsys.readouterr().out
    assert "UPP    premarket +6.0 vs SPY" in out and "after the open +7.0" in out
    assert "precision: 1/2 = 50%  -> pass" in out and "recall: 1/1 = 100%  -> pass" in out
    assert "list size: median 2 a session  -> FAIL" in out
