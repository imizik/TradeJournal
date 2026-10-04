"""D0 evidence gates: read-only capture, eligibility, time ordering and uncertainty."""
from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("d0_audit", Path(__file__).resolve().parents[1] / "scripts" / "audit_journal_data.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def snapshot():
    return {"snapshot_at": "2026-10-04T12:00:00+00:00", "accounts": [{"id": "a", "name": "fixture"}],
            "fills": [], "trades": [], "links": [], "contexts": [], "paths": []}


def add_trade(data, tid, opened, closed, pnl=10, account="a", ticker="SPY", status="closed"):
    entry, exit_fill = tid + "e", tid + "x"
    base = {"account_id": account, "ticker": ticker, "instrument_type": "stock", "option_type": None,
            "strike": None, "expiration": None, "contracts": 1}
    fills = [{**base, "id": entry, "side": "buy", "price": 100, "executed_at": opened, "raw_email_id": "manual:" + entry},
             {**base, "id": exit_fill, "side": "sell", "price": 100 + pnl, "executed_at": closed, "raw_email_id": "manual:" + exit_fill}]
    data["fills"].extend(fills)
    data["links"].extend([{"trade_id": tid, "fill_id": entry, "role": "entry"}, {"trade_id": tid, "fill_id": exit_fill, "role": "exit"}])
    data["trades"].append({**base, "id": tid, "opened_at": opened, "closed_at": closed, "status": status,
                           "avg_entry_premium": 100, "avg_exit_premium": 100 + pnl,
                           "total_premium_paid": 100, "realized_pnl": pnl, "pnl_pct": pnl / 100})
    return data["trades"][-1]


def test_eligibility_refuses_mismatch_missing_shared_and_future():
    data = snapshot()
    add_trade(data, "ok", "2026-09-01T10:00", "2026-09-01T11:00")
    bad = add_trade(data, "bad", "2026-09-02T10:00", "2026-09-02T11:00")
    bad["realized_pnl"] = 50
    absent = add_trade(data, "null", "2026-09-03T10:00", "2026-09-03T11:00")
    absent["realized_pnl"] = None
    add_trade(data, "future", "2026-10-06T10:00", "2026-10-06T11:00")
    add_trade(data, "shared", "2026-09-04T10:00", "2026-09-04T11:00")
    data["links"].append({"trade_id": "shared", "fill_id": "bade", "role": "entry"})
    result = audit.analyze(data, draws=200)
    assert result["eligible_summary"]["trade_ids"] == ["ok"]
    assert result["exclusion_counts"]["accounting_mismatch"] >= 1
    assert result["exclusion_counts"]["missing_or_nonfinite_pnl"] == 1
    assert result["exclusion_counts"]["shared_fill_allocation_unverifiable"] == 2
    assert result["exclusion_counts"]["invalid_or_future_trade_time"] == 1


def test_full_history_repeat_and_strict_prior_loss_batches():
    data = snapshot()
    add_trade(data, "first", "2026-09-01T09:30", "2026-09-01T10:00", -20)
    add_trade(data, "simultaneous", "2026-09-01T09:30", "2026-09-01T10:00", 30, ticker="QQQ")
    add_trade(data, "tie", "2026-09-01T10:00", "2026-09-01T10:05", -5)
    add_trade(data, "second", "2026-09-01T10:06", "2026-09-01T10:10", 5)
    add_trade(data, "otheraccount", "2026-09-01T10:06", "2026-09-01T10:10", 5, account="b")
    data["accounts"].append({"id": "b", "name": "second fixture"})
    rows = {r["id"]: r for r in audit.analyze(data, draws=200)["records"]}
    assert rows["tie"]["after_close"] is None
    assert rows["second"]["after_close"] == "after_loss"
    assert rows["second"]["repeat_entry"] == "repeat"
    assert rows["otheraccount"]["after_close"] == "no_prior_close"
    assert rows["otheraccount"]["repeat_entry"] == "first"
    # First trade can be unavailable for outcomes and must still establish repeat order.
    data["trades"][0]["realized_pnl"] = None
    rows = {r["id"]: r for r in audit.analyze(data, draws=200)["records"]}
    assert rows["second"]["repeat_entry"] == "repeat"
    # Latest simultaneous batch has unknown accounting: its outcome stays unknown.
    data["trades"][2]["realized_pnl"] = None
    rows = {r["id"]: r for r in audit.analyze(data, draws=200)["records"]}
    assert rows["second"]["after_close"] is None


def test_breakeven_null_return_and_later_boundary():
    data = snapshot()
    add_trade(data, "zero", "2026-09-01T10:00", "2026-09-01T11:00", 0)
    add_trade(data, "cross", "2026-09-02T10:00", "2026-09-05T11:00", 20)
    later = add_trade(data, "late", "2026-09-05T10:00", "2026-09-05T11:01", 10)
    later["pnl_pct"] = None
    result = audit.analyze(data, holdout_start="2026-09-05", draws=200)
    assert result["boundary_crossing_trade_ids"] == ["cross"]
    assert result["eligible_summary"]["win_rate_pct"] == pytest.approx(200 / 3)
    assert result["eligible_summary"]["return_observations"] == 2
    discovery_ids = {tid for p in result["discovery"]["panels"] for tid in p["cohort_summary"]["trade_ids"]}
    assert discovery_ids == {"zero"}
    assert all(p["status"] == "insufficient_evidence" for p in result["later_check"]["panels"])


def test_versions_and_future_context_never_become_verified():
    data = snapshot()
    add_trade(data, "a", "2026-09-01T10:00", "2026-09-01T11:00")
    data["contexts"] = [{"fill_id": "ae", "entry_vs_vwap_pct": 0, "calculation_version": None,
                          "entry_context_as_of": "2026-09-01T10:01"}]
    data["paths"] = [{"trade_id": "a", "option_mfe_pct": 99, "calculation_version": None}]
    result = audit.analyze(data, draws=200)
    assert result["freshness"]["context_future_as_of"] == 1
    assert result["coverage"]["context"]["entry_vs_vwap_pct"]["present"] == 1  # zero != missing
    assert result["coverage"]["context"]["entry_vs_vwap_pct"]["obsolete_version_present"] == 1
    assert not result["coverage"]["context"]["entry_vs_vwap_pct"]["source_validated"]
    assert all(lead["current_version_present"] == 0 for lead in result["market_leads"])
    assert audit.UNITS["option_exit_efficiency"].startswith("percent, 100 *")
    assert next(lead for lead in result["market_leads"] if lead["field"] == "option_mfe_pct")["eligible_trade_denominator"] == 0


def test_normalized_numeric_identity_and_same_timestamp_exclusion():
    data = snapshot()
    add_trade(data, "one", "2026-09-01T10:00", "2026-09-01T11:00")
    data["trades"][0]["strike"] = "100.000000"
    for f in data["fills"]:
        f["strike"] = 100.0
    assert audit.analyze(data, draws=200)["counts"]["eligible"] == 1
    add_trade(data, "two", "2026-09-01T10:00", "2026-09-01T11:02")
    data["trades"][1]["strike"] = 100.0
    for f in data["fills"]:
        f["strike"] = 100.0
    assert audit.analyze(data, draws=200)["exclusion_counts"]["same_timestamp_order_ambiguous"] == 2


def test_joint_bootstrap_clusters_days_and_is_reproducible():
    rows = []
    for day in range(24):
        for group in ("first", "repeat"):
            for i in range(2):
                rows.append({"id": f"{day}-{group}-{i}", "day": str(day), "stratum": "a/stock/buy",
                             "return_pp": day * 3 + (8 + day % 3 if group == "repeat" else 0), "pnl": 10,
                             "entry_time": "open", "repeat_entry": group, "after_close": "no_prior_close"})
    before = copy.deepcopy(rows)
    result = audit.comparisons(rows, draws=200, seed=12)
    assert result == audit.comparisons(rows, draws=200, seed=12)
    assert before == rows
    repeat = next(p for p in result["panels"] if p["cohort"] == "repeat")
    assert repeat["effect_return_pp"] == 9
    assert repeat["simultaneous_interval_pp"][0] < 9 < repeat["simultaneous_interval_pp"][1]
    # Replicating identical trades within a day adds no independent day evidence.
    duplicated = audit.comparisons(rows * 10, draws=200, seed=12)
    other = next(p for p in duplicated["panels"] if p["cohort"] == "repeat")
    assert other["simultaneous_interval_pp"] == pytest.approx(repeat["simultaneous_interval_pp"])


def create_database(path):
    db = sqlite3.connect(path)
    for table in audit.TABLES.values():
        db.execute(f'CREATE TABLE "{table}" (id TEXT, marker TEXT)')
        db.execute(f'INSERT INTO "{table}" VALUES (?, ?)', (table, "original"))
    db.execute("ALTER TABLE fill ADD COLUMN email_body_text TEXT")
    db.execute("UPDATE fill SET email_body_text='private-email' ")
    db.commit()
    return db


def test_sqlite_capture_pins_snapshot_and_omits_payload(tmp_path):
    path = tmp_path / "source.db"
    writer = create_database(path)
    writer.execute("PRAGMA journal_mode=WAL")
    reader = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    reader.execute("PRAGMA query_only=ON")

    class Cursor:
        def __init__(self):
            self.cursor = reader.cursor()
        def execute(self, query):
            if query.startswith('SELECT') and 'FROM "fill"' in query:
                writer.execute("UPDATE fill SET marker='new value'")
                writer.commit()
            return self.cursor.execute(query)
        def fetchall(self):
            return self.cursor.fetchall()
        def close(self):
            self.cursor.close()
    class Connection:
        def cursor(self):
            return Cursor()
        def rollback(self):
            reader.rollback()

    result = audit.capture(Connection())
    assert result["fills"][0]["marker"] == "original"
    assert "email_body_text" not in result["fills"][0]
    assert result["fills"][0]["has_source_payload"] == 1
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("UPDATE fill SET marker='forbidden'")
    reader.close()
    writer.close()


def test_postgres_capture_requests_readonly_repeatable_read_and_rolls_back():
    queries = []
    class Cursor:
        query = ""
        def execute(self, query, params=None):
            queries.append(query)
            self.query = query
        def fetchall(self):
            return [("id",)] if "information_schema" in self.query else []
        def close(self):
            queries.append("cursor closed")
    class Connection:
        def cursor(self):
            return Cursor()
        def rollback(self):
            queries.append("rollback")
    audit.capture(Connection(), postgres=True)
    assert queries[0] == "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert queries[-2:] == ["rollback", "cursor closed"]
    assert not any("COMMIT" in query or "UPDATE" in query for query in queries)


def test_cli_replay_writes_only_new_directory_and_ignores_ambient_database(tmp_path, monkeypatch):
    data = snapshot()
    add_trade(data, "a", "2026-09-01T10:00", "2026-09-01T11:00")
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    monkeypatch.setenv("DATABASE_URL", "postgresql://private-secret@invalid/production")
    args = ["--snapshot", str(path), "--output-dir", str(tmp_path / "report"), "--bootstrap-draws", "200"]
    assert audit.main(args) == 0
    assert path.read_bytes() == original
    assert (tmp_path / "report" / "report.md").exists()
    assert "records.md#trade-a" in (tmp_path / "report" / "report.md").read_text()
    assert audit.main(args) == 2
    assert path.read_bytes() == original
    assert audit.main(["--sqlite", str(tmp_path / "missing.db"), "--output-dir", str(tmp_path / "failed")]) == 2
    assert not (tmp_path / "missing.db").exists()
    assert not (tmp_path / "failed").exists()


def test_snapshot_duplicates_fail_and_empty_data_is_not_evidence():
    data = snapshot()
    result = audit.analyze(data, draws=200)
    assert result["counts"]["eligible"] == 0
    assert result["eligible_summary"]["mean_pnl_usd"] is None
    assert result["holdout_start_et"] is None
    data["fills"] = [{"id": "duplicate"}, {"id": "duplicate"}]
    with pytest.raises(ValueError, match="Duplicate"):
        audit.analyze(data, draws=200)


def test_unlinked_source_rows_and_missing_time_are_audited():
    data = snapshot()
    add_trade(data, "ok", "2026-09-01T10:00", "2026-09-01T11:00")
    data["fills"].append({"id": "orphan", "executed_at": None, "contracts": -1, "price": None})
    result = audit.analyze(data, draws=200)
    assert result["unlinked_fill_ids"] == ["orphan"]
    assert result["source_issue_counts"]["missing_or_invalid_execution_time"] == 1
    assert result["source_issue_counts"]["invalid_quantity_or_price"] == 1
    data["fills"][0]["executed_at"] = None
    result = audit.analyze(data, draws=200)
    assert result["counts"]["eligible"] == 0


def test_holdout_default_uses_whole_dates_and_not_trade_count():
    data = snapshot()
    for i in range(10):
        day = datetime(2026, 9, 1) + timedelta(days=i)
        add_trade(data, str(i), day.replace(hour=10).isoformat(), day.replace(hour=11).isoformat())
    assert audit.analyze(data, draws=200)["holdout_start_et"] == "2026-09-08"


def test_invalid_postgres_url_explains_input_without_leaking_credentials(tmp_path, monkeypatch, capsys):
    import psycopg
    def forbidden_connection(*args, **kwargs):
        pytest.fail("Invalid input must fail before any connection")
    monkeypatch.setattr(psycopg, "connect", forbidden_connection)
    for value in ('export D0_DATABASE_URL=super-private-password', 'postgresql://user:super-private-password@localhost/db?unrecognized=secret'):
        monkeypatch.setenv("D0_URL", value)
        assert audit.main(["--postgres-url-env", "D0_URL", "--output-dir", str(tmp_path / "never-created")]) == 2
        error = capsys.readouterr().err
        assert "Invalid PostgreSQL URL" in error
        assert "super-private-password" not in error
        assert "unrecognized" not in error
        assert not (tmp_path / "never-created").exists()
    assert audit.postgres_url(' postgresql+psycopg://user:password@127.0.0.1:55432/journal ') == 'postgresql://user:password@127.0.0.1:55432/journal'


def test_connection_errors_have_safe_stage_and_sqlstate(tmp_path, monkeypatch, capsys):
    import psycopg
    def failed_connection(*args, **kwargs):
        raise psycopg.errors.InvalidPassword('server error with super-private-password')
    monkeypatch.setattr(psycopg, "connect", failed_connection)
    monkeypatch.setenv("D0_URL", "postgresql://user:password@localhost/journal")
    assert audit.main(["--postgres-url-env", "D0_URL", "--output-dir", str(tmp_path / "failed")]) == 2
    error = capsys.readouterr().err
    assert "PostgreSQL connection" in error
    assert "SQLSTATE 28P01" in error
    assert "super-private-password" not in error
