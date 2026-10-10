import json
import uuid
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.main import app
from app.models import Account, Fill
from app.routers import fills


def test_backup_override_is_used_for_startup_restore_and_post(tmp_path, monkeypatch):
    normal_backup = tmp_path / "normal" / "manual_fills.json"
    configured_backup = tmp_path / "isolated" / "manual_fills.json"
    monkeypatch.setattr(fills, "MANUAL_FILLS_BACKUP", normal_backup)
    monkeypatch.setenv("TJ_MANUAL_FILLS_BACKUP", str(configured_backup))

    with Session(engine) as session:
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
        with Session(engine) as session:
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

    # The unset override retains the established backend/data default. Patch
    # that constant to a temporary fake path so this assertion never touches
    # the developer's actual backup.
    monkeypatch.delenv("TJ_MANUAL_FILLS_BACKUP")
    default_path = tmp_path / "default" / "manual_fills.json"
    monkeypatch.setattr(fills, "MANUAL_FILLS_BACKUP", default_path)
    with Session(engine) as session:
        fills.backup_manual_fills(session)
    assert default_path.exists()
