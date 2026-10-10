"""Real migration/CLI and fixture factory restart, with explicit disposable paths."""
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from advisor_shadow_demo import create_app


def test_operator_create_factory_restart_revoke_and_refuse_overwrite(tmp_path, monkeypatch):
    config = tmp_path / "capability.json"
    poison = tmp_path / "unused.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{poison}", "MIGRATION_DATABASE_URL": f"sqlite:///{poison}"}
    command = [sys.executable, "scripts/advisor_shadow_demo.py", "create", str(config)]
    backend = Path(__file__).resolve().parents[1]
    created = subprocess.run(command, cwd=backend, env=env, capture_output=True, text=True)
    assert created.returncode == 0, created.stderr
    data = json.loads(config.read_text())
    assert data["capability"] not in created.stdout
    assert not poison.exists() and config.stat().st_mode & 0o077 == 0
    assert subprocess.run(command, cwd=backend, env=env, capture_output=True).returncode != 0
    monkeypatch.setenv("TJ_ADVISOR_SHADOW_DEMO_CONFIG", str(config))
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    headers = {"authorization": f"Bearer {data['capability']}"}
    with monkeypatch.context() as patch:
        patch.setenv("OPENAI_API_KEY", "fixture-secret-must-not-leak")
        with pytest.raises(RuntimeError, match="refuses inherited") as denied:
            create_app()
        assert "fixture-secret-must-not-leak" not in str(denied.value)
    with TestClient(create_app()) as client:
        packet = client.get("/packet", headers=headers).json()
        body = {"assignment_id": packet["assignment_id"], "packet_sha256": packet["packet_sha256"],
            "choices": [{"opportunity_id": o["opportunity_id"], "decision": "skip", "rationale": "Invented demo"} for o in packet["packet"]["opportunities"]]}
        saved = client.post("/choices", json=body, headers=headers)
        assert saved.status_code == 200
    with TestClient(create_app()) as restarted:
        assert restarted.get("/receipt", headers=headers).json() == saved.json()
        revoked = subprocess.run([sys.executable, "scripts/advisor_shadow_demo.py", "revoke", str(config)], cwd=backend, env=env, capture_output=True)
        assert revoked.returncode == 0
        assert restarted.get("/receipt", headers=headers).status_code == 403
    with pytest.raises(ValueError, match="unavailable"):
        create_app()
