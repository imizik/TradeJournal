from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
import json
from threading import Barrier

import pytest
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine.tradingview import parse_alert, parse_alert_bytes
from app.engine.tradingview_alerts import (
    TradingViewAlertCollisionError,
    TradingViewPersistenceBusyError,
    TradingViewPersistenceError,
    deserialize_snapshot,
    get_alert,
    list_alerts,
    persist_alert,
    serialize_snapshot,
)
from app.models import TradingViewAlert


BAR_TIME_MS = 1_737_561_600_000


@pytest.fixture
def alert_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


def _payload(**overrides) -> dict:
    payload = {
        "v": 1,
        "indicator_version": "1.0.0",
        "alert_id": (
            "v1:1.0.0:AAPL:5:1737561600000:orb_break:long"
        ),
        "symbol": "AAPL",
        "timeframe": "5",
        "setup": "orb_break",
        "side": "long",
        "price": 214.32,
        "bar_time_ms": BAR_TIME_MS,
        "levels": {
            "or_high": 213.9,
            "vwap": 211.1,
        },
        "context": {
            "above_vwap": True,
            "label": "ready",
            "missing": None,
            "rvol": 1.82,
        },
    }
    payload.update(overrides)
    return payload


def _raw_body(**overrides) -> bytes:
    return json.dumps(
        _payload(**overrides),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _persist(session: Session, **overrides):
    raw_body = _raw_body(**overrides)
    return persist_alert(session, parse_alert_bytes(raw_body), raw_body)


def test_persist_alert_creates_normalized_row_with_exact_evidence(alert_engine):
    raw_body = _raw_body()
    parsed = parse_alert_bytes(raw_body)

    with Session(alert_engine) as session:
        result = persist_alert(session, parsed, raw_body)

        assert result.created is True
        assert result.duplicate is False
        assert result.alert.alert_id == parsed.alert_id
        assert result.alert.price == Decimal("214.32")
        assert result.alert.payload_json == raw_body.decode("utf-8")
        assert result.alert.raw_payload_sha256 == parsed.raw_payload_sha256
        assert result.alert.content_sha256 == parsed.content_sha256
        assert result.alert.levels_json == (
            '{"or_high":213.9,"vwap":211.1}'
        )
        assert result.alert.context_json == (
            '{"above_vwap":true,"label":"ready",'
            '"missing":null,"rvol":1.82}'
        )
        assert deserialize_snapshot(result.alert.levels_json) == {
            "or_high": Decimal("213.9"),
            "vwap": Decimal("211.1"),
        }


def test_semantic_duplicate_preserves_first_raw_and_analysis_state(alert_engine):
    first_raw = _raw_body()
    first_parsed = parse_alert_bytes(first_raw)
    # Same semantic JSON with reordered fields, whitespace, and equivalent
    # numeric spellings produces a different raw hash.
    second_raw = (
        b'{ "v":1, "indicator_version":"1.0.0",'
        b'"alert_id":"v1:1.0.0:AAPL:5:1737561600000:orb_break:long",'
        b'"symbol":"AAPL","timeframe":"5","setup":"orb_break",'
        b'"side":"long","price":214.3200,"bar_time_ms":1737561600000,'
        b'"context":{"rvol":1.8200,"missing":null,"label":"ready",'
        b'"above_vwap":true},"levels":{"vwap":211.10,"or_high":213.900} }'
    )
    second_parsed = parse_alert_bytes(second_raw)

    assert first_parsed.content_sha256 == second_parsed.content_sha256
    assert first_parsed.raw_payload_sha256 != second_parsed.raw_payload_sha256

    with Session(alert_engine) as session:
        first = persist_alert(session, first_parsed, first_raw)
        first.alert.analysis_status = "done"
        first.alert.verdict = "long_scalp"
        first.alert.confidence = "high"
        first_received_at = first.alert.received_at
        session.add(first.alert)
        session.commit()

    with Session(alert_engine) as session:
        duplicate = persist_alert(session, second_parsed, second_raw)

        assert duplicate.created is False
        assert duplicate.duplicate is True
        assert duplicate.alert.payload_json == first_raw.decode("utf-8")
        assert (
            duplicate.alert.raw_payload_sha256
            == first_parsed.raw_payload_sha256
        )
        assert duplicate.alert.analysis_status == "done"
        assert duplicate.alert.verdict == "long_scalp"
        assert duplicate.alert.confidence == "high"
        assert duplicate.alert.received_at == first_received_at
        assert duplicate.alert.symbol == "AAPL"
        assert duplicate.alert.price == Decimal("214.32")

        third_time = BAR_TIME_MS + 300_000
        third_id = (
            "v1:1.0.0:MSFT:5:1737561900000:orb_break:long"
        )
        assert _persist(
            session,
            alert_id=third_id,
            symbol="MSFT",
            bar_time_ms=third_time,
        ).created


def test_same_identity_with_changed_content_is_a_collision(alert_engine):
    first_raw = _raw_body()
    first_parsed = parse_alert_bytes(first_raw)
    second_raw = _raw_body(price=215.01)
    second_parsed = parse_alert_bytes(second_raw)

    with Session(alert_engine) as session:
        persist_alert(session, first_parsed, first_raw)

    with Session(alert_engine) as session:
        with pytest.raises(TradingViewAlertCollisionError) as exc_info:
            persist_alert(session, second_parsed, second_raw)

        error = exc_info.value
        assert error.alert_id == first_parsed.alert_id
        assert error.stored_content_sha256 == first_parsed.content_sha256
        assert error.incoming_content_sha256 == second_parsed.content_sha256

        # The insert failure was rolled back and the caller's session remains
        # usable without touching the first immutable evidence.
        stored = session.get(TradingViewAlert, first_parsed.alert_id)
        assert stored is not None
        assert stored.payload_json == first_raw.decode("utf-8")
        assert stored.content_sha256 == first_parsed.content_sha256

        third_time = BAR_TIME_MS + 300_000
        third_id = (
            "v1:1.0.0:MSFT:5:1737561900000:orb_break:long"
        )
        assert _persist(
            session,
            alert_id=third_id,
            symbol="MSFT",
            bar_time_ms=third_time,
        ).created


def test_persist_rejects_unbound_or_mismatched_raw_evidence(alert_engine):
    raw_body = _raw_body()

    with Session(alert_engine) as session:
        parsed_without_raw_hash = parse_alert(_payload())
        with pytest.raises(
            TradingViewPersistenceError,
            match="parse_alert_bytes",
        ):
            persist_alert(session, parsed_without_raw_hash, raw_body)

        parsed = parse_alert_bytes(raw_body)
        with pytest.raises(
            TradingViewPersistenceError,
            match="does not match",
        ):
            persist_alert(session, parsed, raw_body + b" ")

        assert session.get(TradingViewAlert, parsed.alert_id) is None


def test_sqlite_lock_failure_is_explicitly_retryable(
    alert_engine,
    monkeypatch,
):
    raw_body = _raw_body()
    parsed = parse_alert_bytes(raw_body)

    with Session(alert_engine) as session:
        def fail_with_lock():
            raise OperationalError(
                "INSERT",
                {},
                Exception("database is locked"),
            )

        monkeypatch.setattr(session, "commit", fail_with_lock)
        with pytest.raises(TradingViewPersistenceBusyError):
            persist_alert(session, parsed, raw_body)


def test_sqlite_lock_during_conflict_lookup_is_explicitly_retryable(
    alert_engine,
    monkeypatch,
):
    raw_body = _raw_body()
    parsed = parse_alert_bytes(raw_body)

    with Session(alert_engine) as session:
        def fail_with_conflict():
            raise IntegrityError("INSERT", {}, Exception("duplicate"))

        def fail_lookup(*_args, **_kwargs):
            raise OperationalError(
                "SELECT",
                {},
                Exception("database is locked"),
            )

        monkeypatch.setattr(session, "commit", fail_with_conflict)
        monkeypatch.setattr(session, "get", fail_lookup)
        with pytest.raises(TradingViewPersistenceBusyError):
            persist_alert(session, parsed, raw_body)


def test_snapshot_serialization_is_stable_typed_and_flat():
    snapshot = {
        "zero": Decimal("-0.000"),
        "whole": Decimal("1E+3"),
        "fraction": Decimal("1.2300"),
        "flag": False,
        "label": "café",
        "missing": None,
    }

    encoded = serialize_snapshot(snapshot)

    assert encoded == (
        '{"flag":false,"fraction":1.23,"label":"café",'
        '"missing":null,"whole":1000,"zero":0}'
    )
    assert deserialize_snapshot(encoded) == {
        "flag": False,
        "fraction": Decimal("1.23"),
        "label": "café",
        "missing": None,
        "whole": Decimal("1000"),
        "zero": Decimal("0"),
    }
    assert serialize_snapshot(
        {"value": Decimal("1.230000")}
    ) == serialize_snapshot({"value": Decimal("1.23")})
    with pytest.raises(TradingViewPersistenceError, match="finite"):
        serialize_snapshot({"bad": Decimal("NaN")})
    with pytest.raises(TradingViewPersistenceError, match="flat scalar"):
        deserialize_snapshot('{"nested":{"value":1}}')


def test_snapshot_serialization_preserves_v1_decimal_boundaries_and_types():
    snapshot = {
        "boolean": True,
        "maximum": Decimal("999999999999.123456789012"),
        "minimum": Decimal("0.000000000001"),
        "null": None,
        "number": Decimal("1"),
        "text": "1",
    }

    decoded = deserialize_snapshot(serialize_snapshot(snapshot))

    assert decoded == snapshot
    assert isinstance(decoded["number"], Decimal)
    assert isinstance(decoded["text"], str)
    assert isinstance(decoded["boolean"], bool)


def test_list_alerts_filters_orders_paginates_and_defers_large_fields(
    alert_engine,
):
    with Session(alert_engine) as session:
        first = _persist(session).alert
        second_time = BAR_TIME_MS + 300_000
        second_id = (
            "v1:1.0.0:MSFT:5:1737561900000:vwap_reclaim:short"
        )
        second = _persist(
            session,
            alert_id=second_id,
            symbol="MSFT",
            setup="vwap_reclaim",
            side="short",
            bar_time_ms=second_time,
        ).alert
        first.received_at = datetime(2025, 1, 22, 16, 0)
        second.received_at = datetime(2025, 1, 22, 16, 1)
        second.analysis_status = "error"
        session.add(first)
        session.add(second)
        session.commit()

    with Session(alert_engine) as session:
        rows = list_alerts(session, limit=1)
        assert [row.symbol for row in rows] == ["MSFT"]
        assert {
            "payload_json",
            "levels_json",
            "context_json",
            "assessment_json",
            "analysis_error",
        }.issubset(sqlalchemy_inspect(rows[0]).unloaded)

        assert [
            row.symbol
            for row in list_alerts(session, limit=1, offset=1)
        ] == ["AAPL"]
        assert [
            row.symbol
            for row in list_alerts(session, symbol=" msft ")
        ] == ["MSFT"]
        assert [
            row.symbol
            for row in list_alerts(session, setup=" VWAP_RECLAIM ")
        ] == ["MSFT"]
        assert [
            row.symbol
            for row in list_alerts(session, analysis_status=" ERROR ")
        ] == ["MSFT"]

        detail = get_alert(session, second_id)
        assert detail is not None
        assert not {
            "payload_json",
            "levels_json",
            "context_json",
            "assessment_json",
            "analysis_error",
        }.intersection(sqlalchemy_inspect(detail).unloaded)
        assert detail.payload_json


def test_list_alerts_has_stable_tie_breaking_and_filters_before_offset(
    alert_engine,
):
    identities = [
        (
            "AAPL",
            BAR_TIME_MS,
            "v1:1.0.0:AAPL:5:1737561600000:orb_break:long",
        ),
        (
            "MSFT",
            BAR_TIME_MS + 300_000,
            "v1:1.0.0:MSFT:5:1737561900000:orb_break:long",
        ),
        (
            "AAPL",
            BAR_TIME_MS + 600_000,
            "v1:1.0.0:AAPL:5:1737562200000:orb_break:long",
        ),
    ]
    tied_time = datetime(2025, 1, 22, 16, 0)

    with Session(alert_engine) as session:
        for symbol, bar_time_ms, alert_id in identities:
            row = _persist(
                session,
                symbol=symbol,
                bar_time_ms=bar_time_ms,
                alert_id=alert_id,
            ).alert
            row.received_at = tied_time
            session.add(row)
            session.commit()

    with Session(alert_engine) as session:
        expected_ids = sorted(
            (alert_id for _, _, alert_id in identities),
            reverse=True,
        )
        first_page = list_alerts(session, limit=2)
        second_page = list_alerts(session, limit=2, offset=2)
        assert [row.alert_id for row in first_page + second_page] == (
            expected_ids
        )
        assert not {
            row.alert_id for row in first_page
        }.intersection(row.alert_id for row in second_page)

        aapl_ids = [
            row.alert_id
            for row in list_alerts(
                session,
                symbol="AAPL",
                limit=1,
                offset=1,
            )
        ]
        assert aapl_ids == [
            sorted(
                alert_id
                for symbol, _, alert_id in identities
                if symbol == "AAPL"
            )[0]
        ]


def test_concurrent_same_alert_creates_once_and_classifies_retries(tmp_path):
    database_path = tmp_path / "concurrent-alerts.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(engine)
    raw_body = _raw_body()
    parsed = parse_alert_bytes(raw_body)
    workers = 6
    barrier = Barrier(workers)

    def persist_once() -> bool:
        with Session(engine) as session:
            barrier.wait()
            return persist_alert(session, parsed, raw_body).created

    with ThreadPoolExecutor(max_workers=workers) as executor:
        created_results = list(
            executor.map(lambda _index: persist_once(), range(workers))
        )

    assert created_results.count(True) == 1
    assert created_results.count(False) == workers - 1
    with Session(engine) as session:
        stored = session.get(TradingViewAlert, parsed.alert_id)
        assert stored is not None
        assert stored.payload_json == raw_body.decode("utf-8")
        assert stored.raw_payload_sha256 == parsed.raw_payload_sha256


def test_concurrent_same_identity_different_content_preserves_winner(tmp_path):
    database_path = tmp_path / "concurrent-collision.sqlite"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(engine)
    first_raw = _raw_body()
    second_raw = _raw_body(price=215.01)
    variants = [
        (parse_alert_bytes(first_raw), first_raw),
        (parse_alert_bytes(second_raw), second_raw),
    ]
    barrier = Barrier(len(variants))

    def persist_variant(parsed, raw_body):
        with Session(engine) as session:
            barrier.wait()
            try:
                result = persist_alert(session, parsed, raw_body)
            except TradingViewAlertCollisionError as exc:
                return "collision", exc.stored_content_sha256
            return "created", result.alert.content_sha256

    with ThreadPoolExecutor(max_workers=len(variants)) as executor:
        futures = [
            executor.submit(persist_variant, parsed, raw_body)
            for parsed, raw_body in variants
        ]
        outcomes = [future.result() for future in futures]

    assert [status for status, _ in outcomes].count("created") == 1
    assert [status for status, _ in outcomes].count("collision") == 1
    winner_hashes = {content_hash for _, content_hash in outcomes}
    assert len(winner_hashes) == 1
    winner_hash = winner_hashes.pop()

    by_hash = {
        parsed.content_sha256: (parsed, raw_body)
        for parsed, raw_body in variants
    }
    expected_parsed, expected_raw = by_hash[winner_hash]
    with Session(engine) as session:
        stored = session.get(TradingViewAlert, expected_parsed.alert_id)
        assert stored is not None
        assert stored.content_sha256 == winner_hash
        assert stored.raw_payload_sha256 == expected_parsed.raw_payload_sha256
        assert stored.payload_json == expected_raw.decode("utf-8")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 201}, "limit"),
        ({"limit": True}, "limit"),
        ({"offset": -1}, "offset"),
        ({"offset": False}, "offset"),
        ({"symbol": "   "}, "symbol"),
        ({"setup": "   "}, "setup"),
        ({"analysis_status": "complete"}, "analysis_status"),
    ],
)
def test_list_alerts_rejects_invalid_query_arguments(
    alert_engine,
    kwargs,
    message,
):
    with Session(alert_engine) as session:
        with pytest.raises(ValueError, match=message):
            list_alerts(session, **kwargs)
