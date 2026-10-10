from __future__ import annotations

import hashlib
import json
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import export_journal_coach as exporter  # noqa: E402
from journal_coach_snapshot import JournalCoachSnapshot, load_snapshot, summary  # noqa: E402


def trade(**overrides):
    data = {
        "id": str(uuid4()),
        "ticker": "AAPL",
        "instrument_type": "stock",
        "quantity": "2.500",
        "realized_pnl": "12.30",
        "status": "closed",
        "opened_at": "2026-10-08T09:30:00",
        "closed_at": "2026-10-08T10:30:00",
    }
    data.update(overrides)
    return data


def snapshot(**overrides):
    data = {
        "schema_version": "journal-coach-snapshot-v1",
        "generated_at": "2026-10-09T14:00:00Z",
        "start_day": "2026-10-08",
        "end_day": "2026-10-09",
        "source": "approved_journal_export",
        "sample_data": True,
        "trades": [trade()],
    }
    data.update(overrides)
    return data


def test_snapshot_is_curated_strict_and_serializable():
    model = JournalCoachSnapshot.model_validate_json(json.dumps(snapshot()))
    row = model.trades[0].model_dump()
    assert set(row) == {"id", "ticker", "instrument_type", "quantity", "realized_pnl", "status", "opened_at", "closed_at"}
    assert "account_id" not in row and "ai_review" not in row and "notes" not in row
    assert set(model.model_dump()) == {"schema_version", "generated_at", "start_day", "end_day", "source", "sample_data", "trades"}


@pytest.mark.parametrize("extra", ["account_id", "broker", "option_type", "strike", "expiration", "ai_review", "notes", "email", "fills"])
def test_forbidden_trade_columns_fail_closed(extra):
    with pytest.raises(ValidationError):
        JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=[trade(**{extra: "sensitive"})])))


@pytest.mark.parametrize("field,value", [
    ("id", "{uuid}"), ("ticker", "aapl"), ("ticker", "AAPL/NYSE"),
    ("quantity", "-0.1"), ("quantity", "NaN"), ("quantity", "1e3"),
    ("realized_pnl", "Infinity"), ("realized_pnl", "1e2"),
    ("instrument_type", "future"), ("status", "open"),
    ("opened_at", "2026-10-08T09:30:00-04:00"),
    ("closed_at", "2026-10-08T10:30:00Z"),
])
def test_invalid_trade_fields_rejected(field, value):
    if value == "{uuid}":
        value = "not-a-uuid"
    with pytest.raises(ValidationError):
        JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=[trade(**{field: value})])))


@pytest.mark.parametrize("value", ["1000000000000", "1.0000001", "-1000000000000.000000"])
def test_decimal_rejects_values_outside_storage_decimal_18_6(value):
    for field in ("quantity", "realized_pnl"):
        with pytest.raises(ValidationError):
            JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=[trade(**{field: value})])))


def test_decimal_accepts_storage_boundary():
    max_value = "999999999999.999999"
    model = JournalCoachSnapshot.model_validate_json(
        json.dumps(snapshot(trades=[trade(quantity=max_value, realized_pnl=max_value)]))
    )
    assert model.trades[0].quantity == max_value
    assert model.trades[0].realized_pnl == max_value


def test_duplicate_ids_chronology_window_and_max_range_rejected():
    row = trade()
    with pytest.raises(ValidationError):
        JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=[row, row])))
    with pytest.raises(ValidationError):
        JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=[trade(opened_at="2026-10-08T11:00:00")])))
    with pytest.raises(ValidationError):
        JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=[trade(closed_at="2026-10-07T23:59:00")])))
    with pytest.raises(ValidationError):
        JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(end_day="2026-11-08", trades=[])))


def test_summary_keeps_missing_pnl_out_of_total_and_counts_breakeven_in_rate():
    rows = [
        trade(realized_pnl="10.00"),
        trade(id=str(uuid4()), realized_pnl="-3.50"),
        trade(id=str(uuid4()), realized_pnl="0"),
        trade(id=str(uuid4()), realized_pnl=None),
    ]
    result = summary(JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=rows))))
    assert result == {
        "start_day": "2026-10-08", "end_day": "2026-10-09", "trade_count": 4,
        "known_pnl_count": 3, "missing_pnl_count": 1, "win_count": 1,
        "loss_count": 1, "breakeven_count": 1, "win_rate": "0.333333",
        "realized_pnl_total": "6.50",
    }


@pytest.mark.parametrize("rows", [[], [trade(realized_pnl=None)]])
def test_summary_reports_unknown_total_when_no_pnl_is_known(rows):
    result = summary(JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=rows))))
    assert result["known_pnl_count"] == 0
    assert result["win_rate"] is None
    assert result["realized_pnl_total"] is None


def test_summary_total_is_exact_at_maximum_row_count_and_value():
    max_value = "999999999999.999999"
    rows = [trade(realized_pnl=max_value) for _ in range(500)]
    for row in rows[1:]:
        row["id"] = str(uuid4())
    result = summary(JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=rows))))
    assert result["realized_pnl_total"] == "499999999999999.999500"


def test_load_snapshot_verifies_hash_size_and_freshness(tmp_path):
    raw = json.dumps(snapshot()).encode()
    path = tmp_path / "snapshot.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    now = datetime(2026, 10, 9, 14, 30, tzinfo=timezone.utc)
    assert load_snapshot(path, digest, now=now).sample_data is True
    with pytest.raises(ValueError, match="SHA-256"):
        load_snapshot(path, "0" * 64, now=now)
    with pytest.raises(ValueError, match="stale"):
        load_snapshot(path, digest, max_age_seconds=1, now=now)
    with pytest.raises(ValueError, match="future"):
        load_snapshot(path, digest, now=datetime(2026, 10, 9, 13, 59, tzinfo=timezone.utc))
    path.write_bytes(b" " * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="1 MiB"):
        load_snapshot(path, hashlib.sha256(path.read_bytes()).hexdigest(), now=now)


def test_missing_pnl_is_allowed_and_sample_marker_is_explicit():
    model = JournalCoachSnapshot.model_validate_json(json.dumps(snapshot(trades=[trade(realized_pnl=None)])))
    assert model.trades[0].realized_pnl is None
    with pytest.raises(ValidationError):
        JournalCoachSnapshot.model_validate_json(json.dumps({key: value for key, value in snapshot().items() if key != "sample_data"}))


def test_export_query_is_fixed_and_uses_expanding_bound_parameters():
    sql = str(exporter.TRADE_QUERY)
    assert "account_id IN" in sql and "closed_at >= :start_at" in sql and "closed_at < :after_end_at" in sql
    assert "LIMIT :row_limit" in sql
    assert "ai_review" not in sql and "account_id," not in sql and "SELECT *" not in sql
    assert exporter.TRADE_QUERY._bindparams["account_ids"].expanding


def test_role_audit_refuses_privileged_or_writable_roles():
    class Result:
        def __init__(self, row=None, scalar=None):
            self.row = row
            self.scalar = scalar
        def one_or_none(self): return self.row
        def scalar_one(self): return self.scalar
        def first(self): return self.row

    class Connection:
        def __init__(self, role=(False, False, False, False), membership=None, database_create=False, create=None, owned=None, writable=None):
            self.role, self.membership = role, membership
            self.create, self.owned, self.writable = create, owned, writable
            self.database_create = database_create
            self.calls = 0
        def execute(self, query):
            self.calls += 1
            return [Result(self.role), Result(self.membership), Result(scalar=self.database_create), Result(self.create), Result(self.owned), Result(self.writable)][self.calls - 1]

    restricted = (False, False, False, False)
    for connection in [
        Connection((True, False, False, False)),
        Connection((False, True, False, False)),
        Connection((False, False, True, False)),
        Connection((False, False, False, True)),
        Connection(restricted, membership=("writer_role",)),
        Connection(restricted, database_create=True),
        Connection(restricted, create=("public",)),
        Connection(restricted, owned=("public",)),
        Connection(restricted, writable=("trade",)),
    ]:
        with pytest.raises(exporter.ExportError):
            exporter._validate_role(connection)
    exporter._validate_role(Connection())


def test_safe_output_is_private_no_clobber_and_rejects_symlink(tmp_path):
    output = tmp_path / "snapshot.json"
    exporter._safe_output(output, b"{}", False)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(exporter.ExportError, match="already exists"):
        exporter._safe_output(output, b"changed", False)
    exporter._safe_output(output, b"replacement", True)
    assert output.read_bytes() == b"replacement"
    target = tmp_path / "target"
    target.write_text("safe")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(exporter.ExportError, match="symlink"):
        exporter._safe_output(link, b"bad", True)
    assert target.read_text() == "safe"
