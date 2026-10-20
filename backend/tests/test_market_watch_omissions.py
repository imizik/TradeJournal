"""A proved no-price IEX minute is distinct from an unknown data hole."""
from datetime import timedelta

import pytest

from market_watch_common import digest, parse_time, seal, validate_snapshot, VERIFIED_OMISSION_REASON
from tests.test_market_watch_snapshot import fixture_snapshot, OPEN, NOW


def odd_lots(symbol, start, end):
    return {"trades": [{"t": (start + timedelta(seconds=10)).isoformat(), "c": ["@", "I"]}], "next_page_token": None}


def repaired(**kwargs):
    return fixture_snapshot(missing_minute=True, missing_at=20, trades_reader=odd_lots, **kwargs)


def reseal(packet):
    packet.pop("snapshot_id")
    packet.pop("content_sha256")
    packet["snapshot_id"] = "mws_" + digest(packet)[:32]
    return seal(packet)


@pytest.mark.parametrize("reader", [odd_lots, lambda *_: {"trades": [], "next_page_token": None}])
def test_verified_non_price_minute_restores_vwap_without_inventing_a_bar(reader):
    packet = fixture_snapshot(missing_minute=True, missing_at=20, trades_reader=reader)
    entry = next(x for x in packet["input_manifest"] if x["group"] == "indices.SPY.bars_1m")
    bars = entry["bars"]
    assert len(bars) == 29
    assert all(parse_time(b["start"]) != OPEN + timedelta(minutes=20) for b in bars)
    expected = sum((b["high"] + b["low"] + b["close"]) / 3 * b["volume"] for b in bars) / sum(b["volume"] for b in bars)
    assert packet["indices"]["SPY"]["vwap"] == {"value": expected, "status": "fresh", "reason": VERIFIED_OMISSION_REASON}
    assert len(entry["omitted_minutes"]) == 1
    assert len(packet["indices"]["SPY"]["bars_5m"]) == 5  # missing bucket is still absent
    validate_snapshot(packet)


@pytest.mark.parametrize("response", [
    {}, {"trades": [], "next_page_token": "more"},
    {"trades": []}, {"trades": [], "next_page_token": ""},
    {"trades": [{"t": (OPEN + timedelta(minutes=20, seconds=1)).isoformat(), "c": ["@"]}]},
    {"trades": [{"t": (OPEN + timedelta(minutes=20, seconds=1)).isoformat(), "c": []}]},
    {"trades": "malformed"},
    {"trades": [{"t": (OPEN + timedelta(minutes=20, seconds=1)).isoformat(), "c": ["I", "UNRECOGNIZED"]}], "next_page_token": None},
    {"trades": [{"t": (OPEN + timedelta(minutes=21, seconds=1)).isoformat(), "c": ["@"]}], "next_page_token": None},
])
def test_unverified_or_incomplete_trade_response_keeps_vwap_missing(response):
    packet = fixture_snapshot(missing_minute=True, missing_at=20, trades_reader=lambda *_: response)
    assert packet["indices"]["SPY"]["vwap"]["status"] == "missing"


def test_source_failure_and_opening_range_holes_remain_missing():
    def unavailable(*args):
        raise TimeoutError("fixture")
    assert fixture_snapshot(missing_minute=True, missing_at=20, trades_reader=unavailable)["indices"]["SPY"]["vwap"]["value"] is None
    calls = []
    packet = fixture_snapshot(missing_minute=True, trades_reader=lambda *args: calls.append(args) or odd_lots(*args))
    assert calls == []
    assert packet["indices"]["SPY"]["vwap"]["status"] == "missing"
    assert packet["indices"]["SPY"]["or15_high"]["status"] == "missing"


@pytest.mark.parametrize("change", ["price_trade", "unknown_condition", "incomplete", "future", "overlap", "private_field", "missing_disclosure", "wrong_vwap"])
def test_resealed_bad_evidence_is_refused(change):
    packet = repaired()
    entry = next(x for x in packet["input_manifest"] if x["group"] == "indices.SPY.bars_1m")
    proof = entry["omitted_minutes"][0]
    if change == "price_trade":
        proof["trades"][0]["c"] = ["@"]
    elif change == "unknown_condition":
        proof["trades"][0]["c"] = ["I", "UNRECOGNIZED"]
    elif change == "incomplete":
        proof["complete"] = False
    elif change == "future":
        proof["retrieved_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "overlap":
        proof.update(start=(OPEN + timedelta(minutes=21)).isoformat(), end=(OPEN + timedelta(minutes=22)).isoformat(), trades=[])
    elif change == "private_field":
        proof["trades"][0]["account"] = "must-not-publish"
    elif change == "missing_disclosure":
        packet["indices"]["SPY"]["vwap"]["reason"] = None
    else:
        packet["indices"]["SPY"]["vwap"]["value"] += 1
    with pytest.raises(ValueError):
        validate_snapshot(reseal(packet))


def test_removing_proof_cannot_leave_a_fresh_sparse_vwap():
    packet = repaired()
    next(x for x in packet["input_manifest"] if x["group"] == "indices.SPY.bars_1m").pop("omitted_minutes")
    with pytest.raises(ValueError, match="incomplete"):
        validate_snapshot(reseal(packet))


def test_trade_queries_are_bounded_and_only_for_interior_non_or_gaps():
    calls = []
    def reader(symbol, start, end):
        calls.append((symbol, start, end))
        return odd_lots(symbol, start, end)
    fixture_snapshot(missing_minute=True, missing_at=20, trades_reader=reader)
    assert calls == [("SPY", OPEN + timedelta(minutes=20), OPEN + timedelta(minutes=21))]


def test_only_the_exact_inclusive_end_boundary_is_excluded():
    packet = fixture_snapshot(missing_minute=True, missing_at=20,
                              trades_reader=lambda symbol, start, end: {"trades": [{"t": end.isoformat(), "c": ["@"]}],
                                                                        "next_page_token": None})
    assert packet["indices"]["SPY"]["vwap"]["status"] == "fresh"


def test_many_unknown_holes_do_not_start_unbounded_trade_queries():
    from app.engine.market_watch_snapshot import build_snapshot
    from tests.test_market_watch_snapshot import _sources
    bars, daily = _sources()
    bars["SPY"] = [b for b in bars["SPY"] if not 15 <= (parse_time(b["t"]) - OPEN).total_seconds() / 60 <= 24]
    calls = []
    packet = build_snapshot(NOW, protocol=__import__("market_watch_common").PROTOCOL, bars_reader=lambda *_: bars, daily_reader=lambda *_: daily,
                            trades_reader=lambda *args: calls.append(args) or odd_lots(*args),
                            bounds_reader=lambda _: (OPEN, OPEN + timedelta(hours=6, minutes=30)),
                            vix_reader=lambda: None, calendar_reader=lambda *_: fixture_snapshot()["calendar"],
                            news_reader=lambda *_: fixture_snapshot()["headlines"])
    assert calls == []
    assert packet["indices"]["SPY"]["vwap"]["value"] is None
