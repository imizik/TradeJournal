"""Invented provider-shaped bytes only; no network, collection or journal use."""

import ast
import importlib.util
import json
import socket
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from tests.scalp_fixtures.execution import ExitExample, Print, Quote, enter
from tests.test_scalp_conformance import at, contract, position, session, signal

BACKEND = Path(__file__).resolve().parents[1]
PATH = BACKEND / "scripts/scalp_event_adapter.py"


@pytest.fixture(scope="module")
def adapter():
    spec = importlib.util.spec_from_file_location("scalp_event_adapter", PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("offline fixture adapter cannot use network")
    monkeypatch.setattr(socket, "socket", refused)
    monkeypatch.setattr(socket, "create_connection", refused)


def millis(t):
    return str((t - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(milliseconds=1))


def quote_row(**changes):
    return {"type": "quote", "symbol": "SPY300107C00102000", "bid": "2.98", "ask": "3.02",
            "bidsz": 1, "asksz": 2, "biddate": millis(at(second=10)), "askdate": millis(at(second=10)),
            "bidexch": "X", "askexch": "Y", **changes}


def trade_row(**changes):
    return {"type": "timesale", "symbol": "SPY", "last": "103", "size": "100", "date": millis(at(second=10)),
            "seq": 99, "flag": "", "session": "normal", "cancel": False, "correction": False, "exch": "X", **changes}


def decode(adapter, rows, received=None):
    raw = b"\n".join(json.dumps(row).encode() for row in rows)
    return adapter.decode_frame(raw, received_at=received or at(second=10), received_mono_ns=123456789)


def oracle_quote(frame, event):
    # Explicit TEST-ONLY binding: invented quote sizes are contract counts and
    # the invented source represents NBBO. The parser never makes those claims.
    if frame.issues or event.issues or event.kind != "quote":
        raise ValueError("no usable fixture quote")
    q = event.observation
    return Quote(q.symbol, frame.received_at, q.bid_at, q.ask_at, q.bid, q.ask, q.bid_size, q.ask_size)


def oracle_trade(frame, event):
    # Explicit TEST-ONLY interpretation of one invented condition. Production
    # exchange eligibility, sequence semantics and feed identity are unverified.
    t = event.observation
    known = not frame.issues and not event.issues and t.condition == "" and t.session == "normal"
    return Print(t.symbol, t.source_at, frame.received_at, t.price, t.size, t.sequence,
                 conditions_known=known, regular=t.session == "normal", cancelled=t.cancelled, correction=t.correction)


def test_distinct_quote_clocks_decimal_precision_and_raw_bytes_retained(adapter):
    raw = (b' {"type":"quote","symbol":"SPY300107C00102000","bid":2.98,"ask":3.02,'
           b'"bidsz":1,"asksz":2,"biddate":"1893768430000","askdate":"1893768431000",'
           b'"bidexch":"X","askexch":"Y","unknown":{"keep":"this"}} \r\n')
    frame = adapter.decode_frame(raw, received_at=at(second=12), received_mono_ns=7)
    event, = frame.events
    q = event.observation
    assert not frame.issues and not event.issues
    assert frame.raw is raw and event.raw == raw[:-1]
    assert q.bid == D("2.98") and q.ask == D("3.02")
    assert q.bid_at == at(second=10) and q.ask_at == at(second=11)
    assert frame.received_at == at(second=12) and frame.received_mono_ns == 7
    assert (q.bid_size, q.ask_size, q.bid_exchange, q.ask_exchange) == (1, 2, "X", "Y")
    with pytest.raises(FrozenInstanceError):
        frame.received_mono_ns = 8
    with pytest.raises(FrozenInstanceError):
        q.bid = D(3)


def test_raw_trade_fields_preserved_without_sequence_sorting_or_coalescing(adapter):
    first = trade_row(seq=20, last="103.75", flag="UNKNOWN", cancel=True)
    second = trade_row(seq=10, last="102.5", correction=True)
    frame = decode(adapter, [first, second, second])
    assert [e.observation.sequence for e in frame.events] == [20, 10, 10]
    assert [e.observation.price for e in frame.events] == [D("103.75"), D("102.5"), D("102.5")]
    assert [e.ordinal for e in frame.events] == [0, 1, 2]
    assert frame.events[0].observation.condition == "UNKNOWN"
    assert frame.events[0].observation.cancelled is True
    assert frame.events[1].observation.correction is True
    assert frame.events[1].raw == frame.events[2].raw
    assert frame.events[0].observation.exchange == "X"


@pytest.mark.parametrize("condition", ["", " ", " @ ", "UNKNOWN"])
def test_condition_codes_are_opaque_not_trimmed_or_promoted_to_known(adapter, condition):
    frame = decode(adapter, [trade_row(flag=condition)])
    event, = frame.events
    assert event.observation.condition == condition and not event.issues
    assert oracle_trade(frame, event).conditions_known == (condition == "")


@pytest.mark.parametrize("row_factory,key,attribute", [
    (quote_row, "biddate", "bid_at"), (quote_row, "askdate", "ask_at"),
    (quote_row, "bidsz", "bid_size"), (quote_row, "bid", "bid"),
    (trade_row, "seq", "sequence"), (trade_row, "flag", "condition"),
    (trade_row, "session", "session"), (trade_row, "cancel", "cancelled"),
    (trade_row, "correction", "correction"), (trade_row, "date", "source_at"),
])
def test_missing_fields_stay_missing_and_cannot_use_receipt_time_defaults(adapter, row_factory, key, attribute):
    row = row_factory()
    row.pop(key)
    event, = decode(adapter, [row]).events
    assert event.issues == (f"missing:{key}",)
    assert getattr(event.observation, attribute) is None


@pytest.mark.parametrize("key,value", [
    ("bid", True), ("ask", "NaN"), ("bid", "Infinity"), ("bid", -1), ("bid", {}),
    ("biddate", 1893768430000.5), ("askdate", "not-a-time"), ("biddate", True),
    ("askdate", "9" * 5000), ("biddate", "9999999999999999999999"),
    ("bidsz", 1.5), ("asksz", True), ("symbol", " SPY "),
])
def test_invalid_numeric_types_and_clocks_are_visible(adapter, key, value):
    event, = decode(adapter, [quote_row(**{key: value})]).events
    assert f"invalid:{key}" in event.issues


@pytest.mark.parametrize("key,value", [("cancel", "false"), ("correction", 0), ("seq", -1),
                                      ("flag", False), ("size", True), ("last", "NaN")])
def test_trade_types_do_not_coerce_missing_semantics_into_validity(adapter, key, value):
    event, = decode(adapter, [trade_row(**{key: value})]).events
    assert f"invalid:{key}" in event.issues


@pytest.mark.parametrize("raw", [b'[]', b'null', b'123', b'"message"', b'\xff', b'{',
                               b'{"type":"quote","type":"timesale"}', b'{"type":"quote","bid":NaN}'])
def test_invalid_json_has_an_evidence_record_instead_of_disappearing(adapter, raw):
    frame = adapter.decode_frame(raw, received_at=at(), received_mono_ns=0)
    event, = frame.events
    assert event.kind == "invalid" and event.observation is None
    assert event.raw == frame.raw == raw and event.issues == ("invalid_json_object",)


@pytest.mark.parametrize("row", [{"type": "summary"}, {"error": "stream refused"},
                               {"type": "heartbeat"}, {"type": "trade"}, {"type": ["quote"]}])
def test_unsupported_status_or_error_is_retained_and_never_asserts_health(adapter, row):
    event, = decode(adapter, [row]).events
    assert event.kind == "unsupported" and event.observation is None
    assert event.issues == ("unsupported_event_type",)


def test_malformed_line_does_not_hide_between_two_valid_events(adapter):
    raw = json.dumps(trade_row()).encode() + b'\n{broken\n' + json.dumps(quote_row()).encode()
    frame = adapter.decode_frame(raw, received_at=at(second=10), received_mono_ns=1)
    assert [e.kind for e in frame.events] == ["timesale", "invalid", "quote"]
    assert frame.raw == raw


@pytest.mark.parametrize("fault", ["empty", "large", "many"])
def test_bounded_frames_refuse_whole_frame_without_truncating_away_evidence(adapter, fault):
    raw, issue = {"empty": (b" \r\n", "empty_frame"),
                  "large": (b"x" * (adapter.MAX_FRAME_BYTES + 1), "frame_too_large"),
                  "many": (b"{}\n" * (adapter.MAX_FRAME_EVENTS + 1), "too_many_events")}[fault]
    frame = adapter.decode_frame(raw, received_at=at(), received_mono_ns=0)
    assert frame.raw is raw and frame.events == () and frame.issues == (issue,)


def test_complete_frames_preserve_receipt_clock_and_reject_invalid_envelopes(adapter):
    local = datetime(2030, 1, 4, 9, 47, tzinfo=timezone(timedelta(hours=-5)))
    frame = adapter.decode_frame(b'{}', received_at=local, received_mono_ns=123)
    assert frame.received_at == at() and frame.received_at.tzinfo == timezone.utc
    with pytest.raises(ValueError, match="aware receipt"):
        adapter.decode_frame(b'{}', received_at=at().replace(tzinfo=None), received_mono_ns=0)
    for bad in (True, -1, 1.5, "1"):
        with pytest.raises(ValueError, match="monotonic"):
            adapter.decode_frame(b'{}', received_at=at(), received_mono_ns=bad)
    with pytest.raises(TypeError, match="immutable bytes"):
        adapter.decode_frame(bytearray(b'{}'), received_at=at(), received_mono_ns=0)


@pytest.mark.parametrize("bid_at,ask_at,status", [(10, 10, "entered"), (9, 10, "unfilled_quote"),
                                              (10, 9, "unfilled_quote"), (11, 10, "unfilled_quote")])
def test_decoded_quote_respects_frozen_two_sided_latency_and_source_clocks(adapter, bid_at, ask_at, status):
    frame = decode(adapter, [quote_row(biddate=millis(at(second=bid_at)), askdate=millis(at(second=ask_at))), trade_row()])
    q = oracle_quote(frame, frame.events[0])
    p = oracle_trade(frame, frame.events[1])
    result, filled = enter(signal(), contract(), at(second=8), session(), [q], [p], at(second=18))
    assert result == status
    if filled:
        assert filled.entry.ask == D("3.02") and filled.target == D("103.75")


@pytest.mark.parametrize("changes,expected", [({"bid": "0"}, "unfilled_quote"), ({"bidsz": 0}, "unfilled_quote"),
                                           ({"bid": "3.03"}, "unfilled_quote"), ({"bid": "2.90"}, "spread_rejected")])
def test_bad_quote_economics_are_preserved_then_refused_by_frozen_rules(adapter, changes, expected):
    frame = decode(adapter, [quote_row(**changes), trade_row()])
    assert not frame.events[0].issues  # Structurally parsed is not economically eligible.
    q, p = oracle_quote(frame, frame.events[0]), oracle_trade(frame, frame.events[1])
    assert enter(signal(), contract(), at(second=8), session(), [q], [p], at(second=18))[0] == expected


def test_seconds_timestamp_is_not_guessed_or_repaired_into_milliseconds(adapter):
    frame = decode(adapter, [quote_row(biddate="1893768430", askdate="1893768430"), trade_row()])
    q, p = oracle_quote(frame, frame.events[0]), oracle_trade(frame, frame.events[1])
    assert q.bid_at.year == 1970
    assert enter(signal(), contract(), at(second=8), session(), [q], [p], at(second=18))[0] == "unfilled_quote"


@pytest.mark.parametrize("seqs,expected", [((20, 10), "stop"), ((10, 20), "target"), ((None, None), "unresolved_reference")])
def test_same_receipt_crossings_keep_real_sequence_and_do_not_use_transport_ordinal(adapter, seqs, expected):
    rows = [trade_row(last="103.75", date=millis(at(second=13)), seq=seqs[0]),
            trade_row(last="102.5", date=millis(at(second=13)), seq=seqs[1])]
    frame = decode(adapter, rows, at(second=13))
    runner = ExitExample(position(), session())
    runner.batch(frame.received_at, [oracle_trade(frame, e) for e in frame.events])
    assert runner.reason == expected


@pytest.mark.parametrize("changes", [{"date": millis(at(second=11))}, {"flag": "UNKNOWN"}, {"cancel": None}])
def test_bad_pending_exit_observation_cannot_disappear_into_a_later_fill(adapter, changes):
    runner = ExitExample(position(), session())
    good = decode(adapter, [trade_row(last="103.75", date=millis(at(second=13)))], at(second=13))
    runner.batch(good.received_at, [oracle_trade(good, good.events[0])])
    frame = decode(adapter, [trade_row(**{"date": millis(at(second=14)), **changes})], at(second=14))
    runner.batch(frame.received_at, [oracle_trade(frame, frame.events[0])])
    assert runner.unresolved and runner.intent == at(second=13) and runner.reason == "target"
    final = decode(adapter, [quote_row(biddate=millis(at(second=15)), askdate=millis(at(second=15)))], at(second=15))
    assert runner.liquidate([oracle_quote(final, final.events[0])], at(second=15)) == ("unresolved", None)


def pure_adapter_imports(source):
    allowed = {"dataclasses", "datetime", "decimal", "json"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            assert all(x.name in allowed for x in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "exec", "eval", "compile", "__import__", "input"}


def test_adapter_has_no_io_dependencies_and_no_application_importers():
    pure_adapter_imports(PATH.read_text())
    # Enumerate all app Python files: adding a runtime caller is not silently
    # permitted by this PR. Other standalone scripts must not activate it either.
    for directory in (BACKEND / "app", BACKEND / "scripts"):
        for path in directory.rglob("*.py"):
            if path == PATH:
                continue
            assert "scalp_event_adapter" not in path.read_text(), path


@pytest.mark.parametrize("planted", ["import socket", "from app.database import engine", "import os",
                                    "from dotenv import load_dotenv", "open('data.json')"])
def test_adapter_dependency_guard_detects_planted_journal_and_io_paths(planted):
    with pytest.raises(AssertionError):
        pure_adapter_imports(planted)
