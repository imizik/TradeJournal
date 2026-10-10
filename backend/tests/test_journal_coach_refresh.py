from __future__ import annotations

import json
import importlib
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

import journal_coach_refresh as refresh_module  # noqa: E402
import export_journal_coach as exporter  # noqa: E402
script_exporter = importlib.import_module("scripts.export_journal_coach")
from journal_coach_publication import rolling_window  # noqa: E402


def private_file(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def clean_db_env(monkeypatch):
    for name in list(__import__("os").environ):
        if name in {"DATABASE_URL", "MIGRATION_DATABASE_URL", "JOURNAL_EXPORT_DATABASE_URL"} or name.startswith("PG"):
            monkeypatch.delenv(name, raising=False)


def config_file(tmp_path, **changes):
    value = {
        "account_ids": ["123e4567-e89b-12d3-a456-426614174000"],
        "rolling_days": 30,
        "publication_file": str(tmp_path / "publication.json"),
    }
    value.update(changes)
    return private_file(tmp_path / "config.json", json.dumps(value).encode())


def test_scoped_query_is_one_view_with_fixed_projection_and_bound_scope():
    sql = str(exporter.SCOPED_TRADE_QUERY)
    assert "FROM public.journal_coach_export_trade" in sql
    assert "SELECT id, account_id, ticker, instrument_type, contracts, realized_pnl, status, opened_at, closed_at" in sql
    assert "account_id IN" in sql and "account_ids" in exporter.SCOPED_TRADE_QUERY._bindparams
    assert "closed_at >= :start_at" in sql and "closed_at < :after_end_at" in sql
    assert "LIMIT :row_limit" in sql and exporter.SCOPED_TRADE_QUERY._bindparams["account_ids"].expanding
    assert "FROM trade" not in sql and "SELECT *" not in sql


def test_scoped_role_audit_requires_exact_view_columns_and_no_other_reads():
    class Result:
        def __init__(self, rows=(), one=None, scalar=False):
            self.rows, self.one, self.scalar = rows, one, scalar
        def one_or_none(self): return self.one
        def scalar_one(self): return self.scalar
        def first(self): return self.one
        def all(self): return list(self.rows)

    class Connection:
        def __init__(self, view_columns, outside=None):
            self.calls = 0
            self.view_columns, self.outside = view_columns, outside
        def execute(self, query):
            self.calls += 1
            defaults = [
                Result(one=(False, False, False, False)), Result(), Result(scalar=False), Result(), Result(), Result(),
            ]
            if self.calls <= len(defaults):
                return defaults[self.calls - 1]
            if self.calls == 7:
                return Result(rows=self.view_columns)
            return Result(one=self.outside)

    columns = [
        (1, name, True, ["security_barrier=true"]) for name in
        ("id", "account_id", "ticker", "instrument_type", "contracts", "realized_pnl", "status", "opened_at", "closed_at")
    ]
    exporter._validate_role(Connection(columns), scoped_view=True)
    with pytest.raises(exporter.ExportError, match="exact scoped view"):
        exporter._validate_role(Connection(columns[:-1]), scoped_view=True)
    with pytest.raises(exporter.ExportError, match="outside the scoped view"):
        exporter._validate_role(Connection(columns, outside=("trade",)), scoped_view=True)


@pytest.mark.parametrize(("instant", "days", "expected"), [
    (datetime(2026, 3, 8, 6, 30, tzinfo=timezone.utc), 1, (date(2026, 3, 8), date(2026, 3, 8))),
    (datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc), 2, (date(2026, 10, 31), date(2026, 11, 1))),
])
def test_rolling_et_window_handles_dst_and_calendar_days(instant, days, expected):
    assert rolling_window(instant, days) == expected


def test_refresh_passes_exact_account_and_window_and_publishes_matching_real_snapshot(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    cred = private_file(tmp_path / "credential", b"postgresql+psycopg://journal:secret@db/journal\n")
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    account = uuid4()
    value = json.loads(cfg.read_text())
    value["account_ids"] = [str(account)]
    cfg.write_text(json.dumps(value))
    cfg.chmod(0o600)
    calls = {}

    class Snapshot:
        sample_data = False
        start_day, end_day = date(2026, 9, 11), date(2026, 10, 10)
        generated_at = now
        trades = [object()]

    def export(url, accounts, start, end, *, scoped_view):
        calls.update(url=url, accounts=accounts, start=start, end=end, scoped=scoped_view)
        return Snapshot()

    monkeypatch.setattr(script_exporter, "export_snapshot", export)
    monkeypatch.setattr(refresh_module, "publish_snapshot", lambda snap, path: {"snapshot_sha256": "a" * 64})
    result = refresh_module.refresh(cfg, cred, now=now)
    assert calls == {"url": "postgresql+psycopg://journal:secret@db/journal", "accounts": [account],
                     "start": date(2026, 9, 11), "end": date(2026, 10, 10), "scoped": True}
    assert result["trade_count"] == 1 and result["snapshot_sha256"] == "a" * 64
    assert "secret" not in json.dumps(result)


def test_refresh_accepts_systemd_owner_readonly_credential(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    cred = private_file(tmp_path / "credential", b"postgresql+psycopg://journal:secret@db/journal")
    cred.chmod(0o400)
    monkeypatch.setattr(script_exporter, "export_snapshot", lambda *args, **kwargs: type("Snapshot", (), {
        "sample_data": False, "start_day": date(2026, 9, 11), "end_day": date(2026, 10, 10),
        "generated_at": datetime(2026, 10, 10, 12, tzinfo=timezone.utc), "trades": [],
    })())
    monkeypatch.setattr(refresh_module, "publish_snapshot", lambda *args: {"snapshot_sha256": "c" * 64})
    result = refresh_module.refresh(cfg, cred, now=datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
    assert result["trade_count"] == 0


@pytest.mark.parametrize("bad_config", [
    {"extra": True}, {"rolling_days": True}, {"rolling_days": 32},
    {"account_ids": []}, {"account_ids": ["123E4567-E89B-12D3-A456-426614174000"]},
    {"publication_file": "relative.json"},
])
def test_config_scope_refusals(tmp_path, monkeypatch, bad_config):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path, **bad_config)
    with pytest.raises(refresh_module.RefreshError):
        refresh_module._config(cfg)


def test_refresh_refuses_database_environment_and_bad_credentials_without_publication(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    cred = private_file(tmp_path / "credential", b"secret-url")
    published = []
    monkeypatch.setattr(refresh_module, "publish_snapshot", lambda *args: published.append(args))
    monkeypatch.setenv("PGPASSWORD", "ambient-secret")
    with pytest.raises(refresh_module.RefreshError, match="environment"):
        refresh_module.refresh(cfg, cred)
    monkeypatch.delenv("PGPASSWORD")
    cred.chmod(0o644)
    with pytest.raises(refresh_module.RefreshError, match="owner-only mode"):
        refresh_module.refresh(cfg, cred)
    assert published == []


def test_refresh_database_or_schema_failure_leaves_publication_untouched(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    cred = private_file(tmp_path / "credential", b"postgresql+psycopg://journal:secret@db/journal")
    pointer = Path(json.loads(cfg.read_text())["publication_file"])
    pointer.write_text('{"snapshot_sha256":"' + "b" * 64 + '"}')
    old = pointer.read_bytes()

    def fail(*args, **kwargs):
        raise exporter.ExportError("schema or DB details must not escape")

    monkeypatch.setattr(script_exporter, "export_snapshot", fail)
    with pytest.raises(refresh_module.RefreshError, match="snapshot refresh failed") as error:
        refresh_module.refresh(cfg, cred)
    assert "schema or DB" not in str(error.value)
    assert pointer.read_bytes() == old


def test_refresh_lock_refuses_second_attempt_before_export(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    cred = private_file(tmp_path / "credential", b"postgresql+psycopg://journal:secret@db/journal")
    calls = []

    def export(*args, **kwargs):
        calls.append(True)
        with pytest.raises(refresh_module.RefreshError, match="already running"):
            refresh_module.refresh(cfg, cred)
        raise exporter.ExportError("finish outer refresh")

    monkeypatch.setattr(script_exporter, "export_snapshot", export)
    with pytest.raises(refresh_module.RefreshError, match="snapshot refresh failed"):
        refresh_module.refresh(cfg, cred)
    assert calls == [True]


def test_refresh_failure_releases_lock(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    cred = private_file(tmp_path / "credential", b"postgresql+psycopg://journal:secret@db/journal")
    monkeypatch.setattr(script_exporter, "export_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(
        exporter.ExportError("controlled failure")))
    with pytest.raises(refresh_module.RefreshError, match="snapshot refresh failed"):
        refresh_module.refresh(cfg, cred)
    publication = Path(json.loads(cfg.read_text())["publication_file"])
    with refresh_module._refresh_lock(publication.parent):
        assert (publication.parent / ".refresh.lock").exists()


def test_config_and_credential_symlink_paths_are_refused(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    link = tmp_path / "config-link"
    link.symlink_to(cfg)
    with pytest.raises(refresh_module.RefreshError, match="symlink"):
        refresh_module._config(link)


@pytest.mark.parametrize("which", ["config", "credential"])
def test_fifo_inputs_are_refused_without_blocking(tmp_path, monkeypatch, which):
    clean_db_env(monkeypatch)
    fifo = tmp_path / "blocked"
    os.mkfifo(fifo, 0o600)
    if which == "config":
        with pytest.raises(refresh_module.RefreshError, match="regular"):
            refresh_module._config(fifo)
    else:
        cfg = config_file(tmp_path)
        with pytest.raises(refresh_module.RefreshError, match="regular"):
            refresh_module.refresh(cfg, fifo)


def test_model_credentials_refused_before_export(tmp_path, monkeypatch):
    clean_db_env(monkeypatch)
    cfg = config_file(tmp_path)
    cred = private_file(tmp_path / "credential", b"postgresql+psycopg://journal:secret@db/journal")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-appear")
    monkeypatch.setattr(script_exporter, "export_snapshot", lambda *args, **kwargs: pytest.fail("export ran"))
    with pytest.raises(refresh_module.RefreshError, match="model or tunnel"):
        refresh_module.refresh(cfg, cred)


def test_refresh_cli_reports_only_safe_failure_and_metadata(tmp_path, monkeypatch, capsys):
    from export_journal_coach import refresh_main

    monkeypatch.setattr("journal_coach_refresh.refresh", lambda *args: (_ for _ in ()).throw(
        RuntimeError("credential=secret url=postgresql://private/path")))
    assert refresh_main(["--config", "/tmp/config", "--database-url-file", "/tmp/credential"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: journal snapshot refresh failed\n"
    monkeypatch.setattr("journal_coach_refresh.refresh", lambda *args: {
        "snapshot_sha256": "d" * 64, "generated_at": "2026-10-10T12:00:00+00:00", "trade_count": 7,
        "database_url": "secret", "account_ids": ["private"],
    })
    assert refresh_main(["--config", "/tmp/config", "--database-url-file", "/tmp/credential"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "sha256": "d" * 64, "generated_at": "2026-10-10T12:00:00+00:00", "trade_count": 7,
    }
    assert "secret" not in captured.out and "private" not in captured.out
