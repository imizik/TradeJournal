import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.database import get_session
from app.main import app
from app.models import Account, Fill
from app.routers import fills


@pytest.fixture
def migrated_scratch_engine(tmp_path, monkeypatch):
    """Give this lifespan/API integration test its own real migrated database."""
    from alembic import command
    from alembic.config import Config

    from app import database, main

    database_url = f"sqlite:///{tmp_path / 'manual-fills.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)
    config = Config()
    config.set_main_option("script_location", str(database._BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")

    scratch_engine = create_engine(database_url, connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", scratch_engine)
    monkeypatch.setattr(main, "engine", scratch_engine)

    def isolated_session():
        with Session(scratch_engine) as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_session, isolated_session)
    yield scratch_engine
    scratch_engine.dispose()


def test_backup_override_is_used_for_startup_restore_and_post(tmp_path, monkeypatch, migrated_scratch_engine):
    normal_backup = tmp_path / "normal" / "manual_fills.json"
    configured_backup = tmp_path / "isolated" / "manual_fills.json"
    monkeypatch.setattr(fills, "MANUAL_FILLS_BACKUP", normal_backup)
    monkeypatch.setenv("TJ_MANUAL_FILLS_BACKUP", str(configured_backup))
    monkeypatch.setattr("app.engine.enricher.enrich_fills", lambda *_args, **_kwargs: None)

    with Session(migrated_scratch_engine) as session:
        account = Account(name="Roth IRA", type="roth_ira", last4="8267")
        session.add(account)
        session.commit()
        session.refresh(account)

    restored_id = uuid.uuid4()
    configured_backup.parent.mkdir(parents=True)
    configured_backup.write_text(json.dumps([{
        "id": str(restored_id), "account_id": str(account.id), "ticker": "RESTORED",
        "instrument_type": "stock", "side": "buy", "contracts": "1", "price": "10",
        "executed_at": "2026-01-02T10:00:00", "raw_email_id": "manual:configured-backup",
    }]))
    normal_backup.parent.mkdir(parents=True)
    sentinel = '[{"raw_email_id":"manual:must-not-be-read-or-written"}]'
    normal_backup.write_text(sentinel)

    with TestClient(app) as client:
        with Session(migrated_scratch_engine) as session:
            restored = session.get(Fill, restored_id)
            assert restored is not None
            assert session.exec(select(Fill).where(Fill.raw_email_id == "manual:must-not-be-read-or-written")).first() is None

        response = client.post("/fills", json={
            "account_id": str(account.id), "ticker": "POSTED", "instrument_type": "stock",
            "side": "buy", "contracts": "2", "price": "12.50",
            "executed_at": "2026-01-02T11:00:00", "raw_email_id": "manual:post-override",
        })
        assert response.status_code == 200, response.text

    assert normal_backup.read_text() == sentinel
    saved = json.loads(configured_backup.read_text())
    ids = {item["raw_email_id"] for item in saved}
    assert "manual:configured-backup" in ids
    assert "manual:post-override" in ids
    assert "manual:must-not-be-read-or-written" not in ids

    # With no override, restore and save retain the established default. Patch
    # the constant to a fake temporary path so this never touches user data.
    monkeypatch.delenv("TJ_MANUAL_FILLS_BACKUP")
    default_path = tmp_path / "default" / "manual_fills.json"
    monkeypatch.setattr(fills, "MANUAL_FILLS_BACKUP", default_path)
    default_restore_id = uuid.uuid4()
    default_path.parent.mkdir(parents=True)
    default_path.write_text(json.dumps([{
        "id": str(default_restore_id), "account_id": str(account.id), "ticker": "DEFAULT",
        "instrument_type": "stock", "side": "buy", "contracts": "1", "price": "11",
        "executed_at": "2026-01-02T12:00:00", "raw_email_id": "manual:default-backup",
    }]))
    with Session(migrated_scratch_engine) as session:
        assert fills.restore_manual_fills_from_backup(session) == 1
        session.commit()
        assert session.get(Fill, default_restore_id) is not None
        fills.backup_manual_fills(session)
    default_ids = {item["raw_email_id"] for item in json.loads(default_path.read_text())}
    assert {"manual:default-backup", "manual:post-override"} <= default_ids
