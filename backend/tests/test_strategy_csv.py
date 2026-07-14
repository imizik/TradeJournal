from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.strategy_csv import (
    MAX_CSV_BYTES,
    TradingViewCSVError,
    parse_tradingview_csv,
)


FIXTURES = Path(__file__).parent / "fixtures" / "tradingview"


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _parse_fixture(name: str, timezone: str = "America/New_York"):
    return parse_tradingview_csv(
        _fixture_bytes(name),
        source_timezone=timezone,
    )


def _issue_codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def _csv(rows: list[str]) -> bytes:
    return ("\n".join(rows) + "\n").encode("utf-8")


def test_paired_export_handles_bom_exit_first_rows_and_decimal_values() -> None:
    source = _fixture_bytes("paired_trades.csv")
    result = parse_tradingview_csv(source, source_timezone="America/New_York")

    assert result.source_sha256 == hashlib.sha256(source).hexdigest()
    assert result.headers[0] == "Trade number"
    assert result.mapping["trade_number"] == "Trade number"
    assert result.mapping["timestamp"] == "Date and time"
    assert result.row_count == 4
    assert result.total_group_count == 2
    assert result.accepted_count == 2
    assert result.rejected_count == 0

    by_number = {trade.trade_number: trade for trade in result.trades}
    long_trade = by_number[101]
    assert long_trade.direction == "long"
    assert long_trade.entry_at_raw == "2026-03-09 09:45:00"
    assert long_trade.exit_at_raw == "2026-03-09 10:15:00"
    assert long_trade.entry_at == datetime(2026, 3, 9, 13, 45)
    assert long_trade.exit_at == datetime(2026, 3, 9, 14, 15)
    assert long_trade.duration_minutes == 30
    assert long_trade.entry_price == Decimal("11.50")
    assert long_trade.exit_price == Decimal("12.75")
    assert long_trade.quantity == Decimal("125.5")
    # Trade-level metrics are canonicalized from the exit row.
    assert long_trade.net_pnl == Decimal("156.25")
    assert long_trade.return_pct == Decimal("9.97")
    assert long_trade.mfe == Decimal("210.00")
    assert long_trade.mfe_pct == Decimal("13.40")
    assert long_trade.mae == Decimal("-42.50")
    assert long_trade.mae_pct == Decimal("-2.71")
    assert long_trade.cumulative_pnl == Decimal("156.25")
    assert long_trade.cumulative_return_pct == Decimal("9.97")
    assert long_trade.duration_bars == 7
    assert long_trade.entry_signal == "Long reclaim"
    assert long_trade.exit_signal == "Target reached"
    assert long_trade.raw_entry_row["Type"] == "Entry long"
    assert long_trade.raw_exit_row["Type"] == "Exit long"

    short_trade = by_number[102]
    assert short_trade.direction == "short"
    assert short_trade.entry_at == datetime(2026, 11, 6, 15, 30)
    assert short_trade.exit_at == datetime(2026, 11, 6, 16, 0)
    assert short_trade.net_pnl == Decimal("-75.00")
    assert short_trade.mae == Decimal("-90.00")

    # The invented fixture intentionally disagrees on duplicated entry/exit
    # metrics for trade 101; the trade stays usable and the difference is loud.
    assert "duplicate_value_mismatch" in _issue_codes(result.warnings)
    assert "duplicate_value_mismatch" in _issue_codes(long_trade.warnings)
    assert all(issue.message for issue in long_trade.warnings)

    preview = result.preview_dict()
    assert preview["source_sha256"] == result.source_sha256
    assert preview["accepted_count"] == 2
    assert preview["rejected_count"] == 0
    assert len(preview["trades"]) == 2
    json.dumps(preview)


def test_header_aliases_and_export_visible_feature_metadata() -> None:
    result = _parse_fixture("feature_metadata.csv")

    assert result.accepted_count == 2
    assert result.rejected_count == 0
    assert result.mapping["trade_number"] == "Trade #"
    assert result.mapping["type"] == "Order type"
    assert result.mapping["timestamp"] == "Date/Time"
    assert result.mapping["comment"] == "Comment"

    by_number = {trade.trade_number: trade for trade in result.trades}
    first = by_number[201]
    assert first.entry_comment == (
        "sl1|setup=vwap_reclaim|rvol=1.82|qqq_vwap=1|confirmed=true|gap=null"
    )
    assert first.exit_comment == "sl1|exit=target_one"
    assert first.feature_snapshot == {
        "setup": "vwap_reclaim",
        "rvol": 1.82,
        "qqq_vwap": 1,
        "confirmed": True,
        "gap": None,
        "exit": "target_one",
    }

    second = by_number[202]
    assert second.feature_snapshot["setup"] == "opening_rejection"
    assert second.feature_snapshot["rvol"] == 2.05
    assert "malformed_feature_token" in _issue_codes(result.warnings)
    assert "malformed_feature_token" in _issue_codes(second.warnings)
    assert all(issue.message for issue in second.warnings)


def test_bad_trade_groups_are_rejected_without_discarding_valid_pairs() -> None:
    result = _parse_fixture("malformed.csv")

    assert result.row_count == 9
    assert result.total_group_count == 4
    assert result.accepted_count == 1
    assert result.rejected_count == 3
    assert [trade.trade_number for trade in result.trades] == [301]

    rejected = {trade.trade_number: trade for trade in result.rejected_trades}
    assert _issue_codes(rejected[302].issues) == {"missing_exit"}
    assert "duplicate_entry" in _issue_codes(rejected[303].issues)
    assert "duplicate_exit" in _issue_codes(rejected[304].issues)
    assert all(
        issue.message
        for rejected_trade in result.rejected_trades
        for issue in rejected_trade.issues
    )

    preview = result.preview_dict()
    assert preview["accepted_count"] == 1
    assert preview["rejected_count"] == 3
    assert len(preview["rejected_trades"]) == 3
    json.dumps(preview)


@pytest.mark.parametrize(
    ("source", "timezone", "code"),
    [
        (b"", "UTC", "empty_file"),
        (b"\xff\xfe\x00\x00", "UTC", "invalid_encoding"),
        (_fixture_bytes("paired_trades.csv"), "Mars/Olympus", "invalid_timezone"),
        (b"x" * (MAX_CSV_BYTES + 1), "UTC", "file_too_large"),
        (
            _csv(
                [
                    "Trade number,Date and time,Signal,Price USD,Size (qty)",
                    "1,2026-01-02 09:30:00,Long,$10.00,1",
                ]
            ),
            "UTC",
            "missing_header",
        ),
    ],
)
def test_invalid_file_level_inputs_raise_typed_errors(
    source: bytes,
    timezone: str,
    code: str,
) -> None:
    with pytest.raises(TradingViewCSVError) as exc_info:
        parse_tradingview_csv(source, source_timezone=timezone)

    assert exc_info.value.code == code
    assert str(exc_info.value)


def test_dst_nonexistent_trade_is_rejected_and_ambiguous_time_warns() -> None:
    source = _csv(
        [
            "Trade number,Type,Date and time,Signal,Price USD,Size (qty)",
            "401,Entry long,2026-03-08 02:30:00,Spring gap,$10.00,1",
            "401,Exit long,2026-03-08 03:15:00,After gap,$10.50,1",
            "402,Entry long,2026-11-01 01:30:00,Fall overlap,$20.00,2",
            "402,Exit long,2026-11-01 02:30:00,After overlap,$21.00,2",
        ]
    )

    result = parse_tradingview_csv(
        source,
        source_timezone="America/New_York",
    )

    assert result.accepted_count == 1
    assert result.rejected_count == 1
    assert result.trades[0].trade_number == 402
    # Ambiguous wall times deterministically use fold=0 (the earlier instant).
    assert result.trades[0].entry_at == datetime(2026, 11, 1, 5, 30)
    rejected = result.rejected_trades[0]
    assert rejected.trade_number == 401
    assert "nonexistent_local_time" in _issue_codes(rejected.issues)
    assert "ambiguous_local_time" in _issue_codes(result.warnings)
    assert "ambiguous_local_time" in _issue_codes(result.trades[0].warnings)


def test_numeric_18_6_scale_is_exact_and_optional_overprecision_warns() -> None:
    source = _csv(
        [
            "Trade number,Type,Date and time,Price USD,Size (qty),Net PnL USD",
            "501,Entry long,2026-01-02 09:30:00,10.1234567,1,1.00",
            "501,Exit long,2026-01-02 09:35:00,11.00,1,1.00",
            "502,Entry long,2026-01-02 10:00:00,10.1234560,1.0000000,1.2345670",
            "502,Exit long,2026-01-02 10:05:00,11.0000000,1,1.2345678",
        ]
    )

    result = parse_tradingview_csv(source, source_timezone="UTC")

    assert result.accepted_count == 1
    assert result.trades[0].trade_number == 502
    assert result.trades[0].entry_price == Decimal("10.123456")
    assert result.trades[0].quantity == Decimal("1.000000")
    assert result.trades[0].net_pnl is None
    assert "invalid_optional_value" in _issue_codes(result.trades[0].warnings)
    rejected = {trade.trade_number: trade for trade in result.rejected_trades}
    assert "invalid_price" in _issue_codes(rejected[501].issues)


def test_exit_row_is_canonical_when_paired_quantity_differs() -> None:
    source = _csv(
        [
            "Trade number,Type,Date and time,Price USD,Size (qty)",
            "506,Entry long,2026-01-02 09:30:00,10,2",
            "506,Exit long,2026-01-02 09:35:00,11,1",
        ]
    )

    result = parse_tradingview_csv(source, source_timezone="UTC")

    assert result.accepted_count == 1
    assert result.trades[0].quantity == Decimal("1.000000")
    assert "duplicate_value_mismatch" in _issue_codes(result.trades[0].warnings)


def test_numeric_18_6_twelve_digit_boundary_and_overflow() -> None:
    source = _csv(
        [
            "Trade number,Type,Date and time,Price USD,Size (qty),Net PnL USD",
            "511,Entry long,2026-01-02 09:30:00,999999999999.999999,1,-999999999999.999999",
            "511,Exit long,2026-01-02 09:35:00,999999999999.999999,1,-999999999999.999999",
            "512,Entry long,2026-01-02 10:00:00,1000000000000,1,0",
            "512,Exit long,2026-01-02 10:05:00,10,1,0",
        ]
    )

    result = parse_tradingview_csv(source, source_timezone="UTC")

    assert result.accepted_count == 1
    assert result.trades[0].entry_price == Decimal("999999999999.999999")
    assert result.trades[0].net_pnl == Decimal("-999999999999.999999")
    rejected = {trade.trade_number: trade for trade in result.rejected_trades}
    assert "invalid_price" in _issue_codes(rejected[512].issues)


def test_signed_integer_storage_limits_are_enforced() -> None:
    source = _csv(
        [
            "Trade number,Type,Date and time,Price USD,Size (qty),Duration (bars)",
            "2147483648,Entry long,2026-01-02 09:30:00,10,1,1",
            "2147483648,Exit long,2026-01-02 09:35:00,11,1,1",
            "521,Entry long,2026-01-02 10:00:00,10,1,2147483648",
            "521,Exit long,2026-01-02 10:05:00,11,1,2147483648",
        ]
    )

    result = parse_tradingview_csv(source, source_timezone="UTC")

    assert result.accepted_count == 1
    assert result.trades[0].trade_number == 521
    assert result.trades[0].duration_bars is None
    assert "invalid_optional_value" in _issue_codes(result.trades[0].warnings)
    invalid_numbers = [
        trade
        for trade in result.rejected_trades
        if "invalid_trade_number" in _issue_codes(trade.issues)
    ]
    assert len(invalid_numbers) == 2


def test_computed_duration_minutes_must_fit_signed_integer() -> None:
    source = _csv(
        [
            "Trade number,Type,Date and time,Price USD,Size (qty)",
            "531,Entry long,0001-01-01 00:00:00,10,1",
            "531,Exit long,5000-01-01 00:00:00,11,1",
        ]
    )

    result = parse_tradingview_csv(source, source_timezone="UTC")

    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert "duration_minutes_out_of_range" in _issue_codes(
        result.rejected_trades[0].issues
    )


def test_long_invalid_timezone_is_typed_and_bounded() -> None:
    timezone_name = "x" * 1000

    with pytest.raises(TradingViewCSVError) as exc_info:
        parse_tradingview_csv(
            _fixture_bytes("paired_trades.csv"),
            source_timezone=timezone_name,
        )

    assert exc_info.value.code == "invalid_timezone"
    assert len(str(exc_info.value)) < 300
    assert timezone_name not in str(exc_info.value)


def test_untrusted_issue_values_are_bounded_without_changing_raw_rows() -> None:
    long_type = "Entry long " + "x" * 1000
    source = _csv(
        [
            "Trade number,Type,Date and time,Price USD,Size (qty)",
            f"541,{long_type},not-a-time,not-a-number,1",
            "541,Exit long,2026-01-02 10:05:00,11,1",
        ]
    )

    result = parse_tradingview_csv(source, source_timezone="UTC")

    rejected = result.rejected_trades[0]
    assert all(len(issue.message) < 400 for issue in rejected.issues)
    assert rejected.raw_rows[0]["Type"] == long_type


def test_net_p_and_l_header_alias_is_recognized() -> None:
    source = _csv(
        [
            "Trade number,Type,Date and time,Price USD,Size (qty),Net P&L USD",
            "551,Entry long,2026-01-02 10:00:00,10,1,2.50",
            "551,Exit long,2026-01-02 10:05:00,12.50,1,2.50",
        ]
    )

    result = parse_tradingview_csv(source, source_timezone="UTC")

    assert result.mapping["net_pnl"] == "Net P&L USD"
    assert result.trades[0].net_pnl == Decimal("2.500000")
