from datetime import UTC, date, datetime, timedelta
import json

import pytest

from market_watch_common import PROTOCOL, canonical, digest, parse_time, seal, validate_snapshot, verify
from app.engine.market_watch_snapshot import build_snapshot, publish_snapshot, read_latest_snapshot


DAY = date(2026, 10, 14)
OPEN = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=UTC)


def _bar(start, n):
    price = 100 + n / 10
    return {"t": start.isoformat().replace("+00:00", "Z"), "o": price, "h": price + .2,
            "l": price - .2, "c": price + .1, "v": 1000}


def _sources(*, missing_qqq=False, stale=False, missing_minute=False, duplicate_minute=False):
    bars = {}
    for symbol in ("SPY", "QQQ"):
        bars[symbol] = [_bar(OPEN + timedelta(minutes=i), i) for i in range(30)]
        # A partially formed, future minute must not enter the packet or aggregate.
        bars[symbol].append(_bar(NOW, 31))
    if missing_qqq:
        bars["QQQ"] = []
    daily = {symbol: [{"t": "2026-10-13T00:00:00Z", "c": 99}] for symbol in ("SPY", "QQQ")}
    if stale:
        bars["SPY"] = [_bar(OPEN + timedelta(minutes=i), i) for i in range(10)]
    if missing_minute:
        bars["SPY"] = [row for i, row in enumerate(bars["SPY"]) if i != 10]
    if duplicate_minute:
        bars["SPY"].append(dict(bars["SPY"][10]))
    return bars, daily


def fixture_snapshot(**options):
    now = options.pop("now", NOW)
    bounds = options.pop("bounds", (OPEN, datetime(2026, 10, 14, 20, 0, tzinfo=UTC)))
    vix = options.pop("vix", {"observed_at": now - timedelta(minutes=5), "value": 17.2, "change_pct": 2.1})
    news_items = options.pop("news_items", [])
    bars, daily = _sources(**options)
    return build_snapshot(
        now, bars_reader=lambda *_: bars, daily_reader=lambda *_: daily,
        vix_reader=lambda: vix,
        calendar_reader=lambda day, at: {"status": "fresh", "reason": None, "source": "official_calendar",
            "observed_at": at.isoformat().replace("+00:00", "Z"), "retrieved_at": at.isoformat().replace("+00:00", "Z"),
            "age_seconds": 0, "source_sha256": digest({"coverage_start": "2026-01-01", "coverage_end": "2027-01-01",
                "calendar_version": "fixture", "events": []}), "coverage_start": "2026-01-01", "coverage_end": "2027-01-01",
            "calendar_version": "fixture", "events": []},
        news_reader=lambda start, end: {"status": "fresh", "reason": None, "source": "Alpaca Benzinga",
            "observed_at": end.isoformat().replace("+00:00", "Z"), "retrieved_at": end.isoformat().replace("+00:00", "Z"),
            "age_seconds": 0, "source_sha256": digest(news_items), "query_symbols": ["SPY", "QQQ"],
            "window_start": start.isoformat().replace("+00:00", "Z"), "window_end": end.isoformat().replace("+00:00", "Z"),
            "coverage": "fixture", "errors": [], "items": news_items},
        bounds_reader=lambda day: bounds,
    )


def test_protocol_hashes_and_timestamp_offsets_are_strict():
    assert PROTOCOL["protocol_id"] == "mw-v1"
    sealed = seal({"record": "fixture"})
    verify(sealed)
    assert canonical({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert digest({"a": 2, "b": 1}) == digest({"b": 1, "a": 2})
    with pytest.raises(ValueError, match="offset"):
        parse_time("2026-10-14T10:00:00")
    sealed["record"] = "changed"
    with pytest.raises(ValueError, match="hash"):
        verify(sealed)


def test_snapshot_has_exact_universe_completed_bars_and_reproducible_manifest():
    packet = fixture_snapshot()
    validate_snapshot(packet)
    assert packet["session_date"] == "2026-10-14"
    assert set(packet["indices"]) == {"SPY", "QQQ"}
    spy = packet["indices"]["SPY"]
    assert spy["bar_1m"]["start"] == "2026-10-14T13:59:00.000000Z"
    assert spy["bar_1m"]["end"] == "2026-10-14T14:00:00.000000Z"
    assert len(spy["bars_5m"]) == 6
    assert spy["or15_high"]["value"] is not None
    assert packet["input_manifest"][0]["payload_sha256"] == spy["source_sha256"]
    assert packet["content_sha256"] == digest({k: v for k, v in packet.items() if k != "content_sha256"})


def test_partial_source_is_explicit_and_future_bars_never_enter(tmp_path):
    packet = fixture_snapshot(missing_qqq=True)
    assert packet["indices"]["QQQ"]["bar_1m"] is None
    assert packet["indices"]["QQQ"]["vwap"]["status"] == "missing"
    assert any(gap["group"] == "indices.QQQ" for gap in packet["gaps"])
    publish_snapshot(tmp_path, packet)
    assert (tmp_path / "protocols" / f"{packet['protocol_sha256']}.json").exists()
    assert read_latest_snapshot(tmp_path, NOW)["content_sha256"] == packet["content_sha256"]
    assert read_latest_snapshot(tmp_path, NOW + timedelta(days=1)) is None
    stored = json.loads((tmp_path / "latest.json").read_text())
    content = tmp_path / f"{stored['content_sha256']}.json"
    tampered = json.loads(content.read_text())
    tampered["indices"]["SPY"]["price"]["value"] = 999
    content.write_text(json.dumps(tampered))
    assert read_latest_snapshot(tmp_path, NOW) is None


def test_latest_publication_never_regresses_with_older_collection(tmp_path):
    newer = fixture_snapshot()
    publish_snapshot(tmp_path, newer)
    older_time = NOW - timedelta(minutes=10)
    older = fixture_snapshot(now=older_time)
    publish_snapshot(tmp_path, older)
    assert read_latest_snapshot(tmp_path, NOW)["content_sha256"] == newer["content_sha256"]


def test_stale_last_bar_and_unpublished_inputs_remain_visible():
    packet = fixture_snapshot(stale=True)
    assert packet["indices"]["SPY"]["status"] == "stale"
    assert packet["indices"]["SPY"]["price"]["status"] == "stale"
    assert packet["headlines"]["coverage"] == "fixture"


def test_snapshot_rejects_unclosed_bar_and_future_source_time():
    packet = fixture_snapshot()
    packet["indices"]["SPY"]["bar_1m"]["end"] = (NOW + timedelta(minutes=1)).isoformat()
    packet.pop("content_sha256")
    packet.pop("snapshot_id")
    packet["snapshot_id"] = "mws_" + digest(packet)[:32]
    packet = seal({k: v for k, v in packet.items() if k != "content_sha256"})
    with pytest.raises(ValueError, match="after collection|future|minute bar"):
        validate_snapshot(packet)


def test_opening_range_is_ready_after_first_15_bars_and_vwap_requires_contiguous_minutes():
    packet = fixture_snapshot()
    assert packet["indices"]["SPY"]["or15_high"]["status"] == "fresh"
    broken = fixture_snapshot(missing_minute=True)
    spy = broken["indices"]["SPY"]
    assert spy["vwap"]["value"] is None
    assert spy["vwap"]["status"] == "missing"
    assert any(gap["group"] == "indices.SPY.vwap" for gap in broken["gaps"])


def test_duplicate_minute_is_a_typed_gap_and_does_not_choose_a_duplicate():
    packet = fixture_snapshot(duplicate_minute=True)
    assert packet["indices"]["SPY"]["status"] == "missing"
    assert any(gap == {"group": "indices.SPY", "reason": "duplicate_minute_bar"} for gap in packet["gaps"])


def test_missing_exchange_calendar_does_not_invent_session_times_or_request_bars():
    before_open = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    packet = fixture_snapshot(now=before_open, bounds=None)
    assert packet["market_phase"] == "calendar_unavailable"
    assert packet["session_open_at"] is None and packet["session_close_at"] is None
    assert packet["indices"]["SPY"]["bar_1m"] is None
    assert any(gap["group"] == "session_calendar" for gap in packet["gaps"])


def test_nested_future_market_inputs_are_rejected():
    with pytest.raises(ValueError, match="source timestamp"):
        fixture_snapshot(vix={"observed_at": NOW + timedelta(seconds=1), "value": 18, "change_pct": 1})
    future_article = {"article_id": "1", "provider": "fixture", "url": "https://example.com/story",
        "headline": "fixture", "published_at": NOW.isoformat(), "provider_updated_at": None,
        "first_observed_at": None, "retrieved_at": (NOW + timedelta(seconds=1)).isoformat(),
        "payload_sha256": "0" * 64, "truncated": False}
    future_article["payload_sha256"] = digest({k: v for k, v in future_article.items() if k != "payload_sha256"})
    with pytest.raises(ValueError, match="headline source timestamp"):
        fixture_snapshot(news_items=[future_article])


def test_schema_refuses_private_fields_and_content_address_symlinks(tmp_path):
    packet = fixture_snapshot()
    private = dict(packet)
    private["api_key"] = "credential-like"
    private.pop("content_sha256")
    private.pop("snapshot_id")
    private["snapshot_id"] = "mws_" + digest(private)[:32]
    private = seal(private)
    with pytest.raises(ValueError, match="outside the public market schema"):
        validate_snapshot(private)
    content = tmp_path / f"{packet['content_sha256']}.json"
    content.symlink_to(tmp_path / "external.json")
    with pytest.raises(ValueError, match="symlink"):
        publish_snapshot(tmp_path, packet)


def test_protocol_id_is_content_bound_and_cached_session_bounds_do_not_fetch(monkeypatch):
    import market_watch_common as common
    from app.engine.chart_calendar import chart_calendar
    day = date(2026, 10, 14)
    monkeypatch.setattr(chart_calendar, "hours", lambda *_: (_ for _ in ()).throw(AssertionError("network path used")))
    monkeypatch.setattr(chart_calendar, "cached", lambda value: {"status": "open", "open": 570, "close": 960})
    assert common.session_bounds(day) == (datetime(2026, 10, 14, 13, 30, tzinfo=UTC), datetime(2026, 10, 14, 20, 0, tzinfo=UTC))
    packet = fixture_snapshot()
    packet["protocol_sha256"] = "0" * 64
    packet.pop("content_sha256")
    packet.pop("snapshot_id")
    packet["snapshot_id"] = "mws_" + digest(packet)[:32]
    packet = seal(packet)
    with pytest.raises(ValueError, match="protocol hash"):
        validate_snapshot(packet)
