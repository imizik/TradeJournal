from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
import json

import pytest

from app.engine.tradingview import (
    MAX_ALERT_BODY_BYTES,
    MAX_BAR_TIME_MS,
    MIN_BAR_TIME_MS,
    PARSER_REVISION_V1,
    TradingViewContractError,
    canonical_alert_id,
    parse_alert,
    parse_alert_bytes,
    parse_alert_v1,
)


BAR_TIME_MS = 1_737_561_600_000


def _body(**overrides):
    body = {
        "v": 1,
        "indicator_version": "1.0.0",
        "alert_id": "v1:1.0.0:AAPL:5:1737561600000:orb_break:long",
        "symbol": "AAPL",
        "timeframe": "5",
        "setup": "orb_break",
        "side": "long",
        "price": 214.32,
        "bar_time_ms": BAR_TIME_MS,
        "levels": {
            "pdh": 214.45,
            "pdl": 204.51,
            "vwap": 211.10,
            "or_high": 213.9,
            "or_low": 210.2,
        },
        "context": {
            "rvol": 1.82,
            "ema9_over_ema20": True,
            "above_vwap": True,
            "rs_vs_spy": 0.31,
        },
    }
    body.update(overrides)
    return body


def _raw(body=None) -> bytes:
    return json.dumps(
        _body() if body is None else body,
        separators=(",", ":"),
    ).encode("utf-8")


def test_parse_alert_v1_normalizes_and_freezes_the_contract():
    raw = _raw(_body(symbol=" aapl ", setup="ORB_BREAK", side="LONG"))
    parsed = parse_alert_bytes(raw)

    assert parsed.contract_version == 1
    assert parsed.parser_revision == PARSER_REVISION_V1
    assert parsed.symbol == "AAPL"
    assert parsed.setup == "orb_break"
    assert parsed.side == "long"
    assert parsed.price == Decimal("214.32")
    assert parsed.bar_time == datetime(2025, 1, 22, 16, 0)
    assert parsed.bar_time.tzinfo is None
    assert parsed.levels["pdh"] == Decimal("214.45")
    assert parsed.context["above_vwap"] is True
    assert len(parsed.content_sha256) == 64
    assert parsed.raw_payload_sha256 == sha256(raw).hexdigest()
    assert MAX_ALERT_BODY_BYTES == 16 * 1024

    with pytest.raises(TypeError):
        parsed.levels["pdh"] = Decimal("1")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        parsed.symbol = "MSFT"  # type: ignore[misc]


def test_v1_golden_fingerprint_is_stable():
    parsed = parse_alert_bytes(_raw())

    assert parsed.canonical_fingerprint_json == (
        '{"alert_id":"v1:1.0.0:AAPL:5:1737561600000:orb_break:long",'
        '"bar_time_ms":1737561600000,"context":{"above_vwap":["bool",true],'
        '"ema9_over_ema20":["bool",true],"rs_vs_spy":["number","0.31"],'
        '"rvol":["number","1.82"]},"indicator_version":"1.0.0",'
        '"levels":{"or_high":["number","213.9"],"or_low":["number","210.2"],'
        '"pdh":["number","214.45"],"pdl":["number","204.51"],'
        '"vwap":["number","211.1"]},"price":["number","214.32"],'
        '"setup":"orb_break","side":"long","symbol":"AAPL","timeframe":"5","v":1}'
    )
    assert (
        parsed.content_sha256
        == "2591903e48a635c6ddee8a12bffa930ae45b37b2efa8dd4c3c152e1b8b0791bb"
    )


def test_equivalent_numeric_spellings_have_the_same_fingerprint():
    first = parse_alert(_body(price=214.32, context={"rvol": 1}))
    second = parse_alert(
        _body(
            price=Decimal("214.3200000000000"),
            context={"rvol": Decimal("1.0000000000000")},
        )
    )

    assert first.content_sha256 == second.content_sha256


def test_numeric_normalization_is_independent_of_decimal_context():
    body = _body(
        price=Decimal("214.123456789012"),
        context={"rvol": Decimal("1.820000000000")},
    )
    baseline = parse_alert(body)

    with localcontext() as context:
        context.prec = 6
        low_precision = parse_alert(body)

    assert low_precision.price == Decimal("214.123456789012")
    assert low_precision.content_sha256 == baseline.content_sha256
    assert (
        low_precision.canonical_fingerprint_json
        == baseline.canonical_fingerprint_json
    )


def test_raw_decoder_preserves_decimal_numbers_exactly():
    raw = _raw().replace(
        b'"price":214.32',
        b'"price":214.123456789012',
    )

    parsed = parse_alert_bytes(raw)

    assert parsed.price == Decimal("214.123456789012")


def test_scalar_type_changes_have_different_fingerprints():
    number = parse_alert(_body(context={"value": 1}))
    string = parse_alert(_body(context={"value": "1"}))

    assert number.content_sha256 != string.content_sha256


def test_content_changes_under_the_same_id_have_different_fingerprints():
    first = parse_alert(_body(context={"rvol": 1.8}))
    second = parse_alert(_body(context={"rvol": 2.1}))

    assert first.alert_id == second.alert_id
    assert first.content_sha256 != second.content_sha256


def test_canonical_alert_id_normalizes_identity_fields():
    assert canonical_alert_id(
        indicator_version="1.0.0",
        symbol=" aapl ",
        timeframe="5",
        bar_time_ms=BAR_TIME_MS,
        setup="ORB_BREAK",
        side="LONG",
    ) == "v1:1.0.0:AAPL:5:1737561600000:orb_break:long"


def test_alert_id_is_required_and_must_be_canonical():
    missing = _body()
    del missing["alert_id"]
    with pytest.raises(TradingViewContractError, match="missing required field"):
        parse_alert(missing)

    with pytest.raises(TradingViewContractError, match="canonical id"):
        parse_alert(_body(alert_id="client-chosen-id"))
    with pytest.raises(TradingViewContractError, match="canonical id"):
        parse_alert(
            _body(
                alert_id=" v1:1.0.0:AAPL:5:1737561600000:orb_break:long "
            )
        )


def test_raw_decoder_rejects_duplicate_keys_before_parsing():
    raw = _raw().replace(b'{"v":1,', b'{"v":1,"v":1,', 1)

    with pytest.raises(TradingViewContractError, match="duplicate JSON object key"):
        parse_alert_bytes(raw)


@pytest.mark.parametrize(
    "raw,match",
    [
        (b"", "must not be empty"),
        (b"\xff", "valid UTF-8"),
        (b'{"v":1,"price":NaN}', "non-finite"),
        (b" " * (MAX_ALERT_BODY_BYTES + 1), "exceeds"),
    ],
)
def test_raw_decoder_rejects_unsafe_transport_inputs(raw, match):
    with pytest.raises(TradingViewContractError, match=match):
        parse_alert_bytes(raw)


@pytest.mark.parametrize(
    "field",
    [
        "indicator_version",
        "symbol",
        "timeframe",
        "setup",
        "side",
        "price",
        "bar_time_ms",
    ],
)
def test_required_fields_are_enforced(field):
    body = _body()
    del body[field]

    with pytest.raises(TradingViewContractError, match="missing required field"):
        parse_alert(body)


@pytest.mark.parametrize("version", [None, True, "1", 1.0, 2])
def test_contract_version_is_strict(version):
    with pytest.raises(TradingViewContractError):
        parse_alert(_body(v=version))


def test_version_specific_parser_cannot_reinterpret_another_version():
    with pytest.raises(TradingViewContractError, match="integer 1"):
        parse_alert_v1(_body(v=2))


def test_unknown_top_level_fields_are_rejected():
    with pytest.raises(TradingViewContractError, match="unknown top-level"):
        parse_alert(_body(future_field=True))


@pytest.mark.parametrize("value", [True, "1737561600000", 1.7375616e12])
def test_bar_time_ms_must_be_a_strict_integer(value):
    with pytest.raises(TradingViewContractError, match="bar_time_ms"):
        parse_alert(_body(bar_time_ms=value))


@pytest.mark.parametrize(
    "value",
    [946_684_799_999, 4_102_444_800_000],
)
def test_bar_time_ms_has_stable_v1_bounds(value):
    with pytest.raises(TradingViewContractError, match="between 2000-01-01"):
        parse_alert(_body(bar_time_ms=value))


@pytest.mark.parametrize("value", [MIN_BAR_TIME_MS, MAX_BAR_TIME_MS - 1])
def test_bar_time_ms_accepts_both_v1_boundary_values(value):
    alert_id = canonical_alert_id(
        indicator_version="1.0.0",
        symbol="AAPL",
        timeframe="5",
        bar_time_ms=value,
        setup="orb_break",
        side="long",
    )

    parsed = parse_alert(_body(bar_time_ms=value, alert_id=alert_id))

    assert parsed.bar_time_ms == value


@pytest.mark.parametrize(
    "overrides",
    [
        {"indicator_version": "v" * 33},
        {"indicator_version": "bad:version"},
        {"symbol": "A" * 33},
        {"symbol": "NASDAQ:AAPL"},
        {"timeframe": "1" * 17},
        {"timeframe": "5-minute"},
        {"setup": "s" * 65},
        {"setup": "orb-break"},
        {"symbol": "AA\nPL"},
    ],
)
def test_identity_bounds_and_formats_are_frozen(overrides):
    with pytest.raises(TradingViewContractError):
        parse_alert(_body(**overrides))


@pytest.mark.parametrize("value", ["up", "", None, 1])
def test_side_is_limited_to_long_or_short(value):
    with pytest.raises(TradingViewContractError, match="side"):
        parse_alert(_body(side=value))


@pytest.mark.parametrize(
    "value",
    [0, -1, "214.32", True, float("nan"), float("inf"), 10**16],
)
def test_price_must_be_a_positive_bounded_finite_json_number(value):
    with pytest.raises(TradingViewContractError, match="price"):
        parse_alert(_body(price=value))


def test_numeric_precision_scale_and_magnitude_boundaries_are_frozen():
    accepted = parse_alert(
        _body(
            price=Decimal("999999999999.123456789012"),
            context={"limit": Decimal("1000000000000000")},
        )
    )
    assert accepted.price == Decimal("999999999999.123456789012")

    with pytest.raises(TradingViewContractError, match="precision"):
        parse_alert(_body(price=Decimal("9999999999999.123456789012")))
    with pytest.raises(TradingViewContractError, match="decimal places"):
        parse_alert(_body(price=Decimal("1.1234567890123")))
    with pytest.raises(TradingViewContractError, match="magnitude"):
        parse_alert(_body(context={"too_large": Decimal("1000000000000001")}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("levels", []),
        ("levels", {"nested": {"value": 1}}),
        ("levels", {"array": [1]}),
        ("context", None),
        ("context", {"bad-key": 1}),
        ("context", {"nested": {"value": 1}}),
        ("context", {"bad": float("nan")}),
    ],
)
def test_snapshots_must_be_flat_bounded_json_objects(field, value):
    with pytest.raises(TradingViewContractError, match=field):
        parse_alert(_body(**{field: value}))


def test_snapshot_entry_and_string_limits_are_enforced():
    with pytest.raises(TradingViewContractError, match="at most 32"):
        parse_alert(_body(context={f"k{index}": index for index in range(33)}))
    with pytest.raises(TradingViewContractError, match="at most 256"):
        parse_alert(_body(context={"note": "x" * 257}))


def test_snapshot_keys_are_not_silently_trimmed():
    with pytest.raises(TradingViewContractError, match="invalid format"):
        parse_alert(_body(context={" value ": 2}))


def test_snapshot_null_string_and_reordered_objects_have_stable_tags():
    first = parse_alert(
        _body(
            context={"label": "ready", "missing": None},
            levels={"or_low": 210.2, "or_high": 213.9},
        )
    )
    second = parse_alert(
        _body(
            context={"missing": None, "label": "ready"},
            levels={"or_high": Decimal("213.90"), "or_low": Decimal("210.20")},
        )
    )

    assert first.content_sha256 == second.content_sha256
    assert '"label":["string","ready"]' in first.canonical_fingerprint_json
    assert '"missing":["null",null]' in first.canonical_fingerprint_json


def test_optional_snapshots_default_to_empty_immutable_mappings():
    body = _body()
    del body["levels"]
    del body["context"]

    parsed = parse_alert(body)

    assert dict(parsed.levels) == {}
    assert dict(parsed.context) == {}
    assert parsed.content_sha256 == parse_alert(
        _body(levels={}, context={})
    ).content_sha256


def test_parsing_does_not_mutate_the_input():
    body = _body()
    original = deepcopy(body)

    parse_alert(body)

    assert body == original
