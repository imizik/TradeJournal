"""The Deploys page's read of the server's releases and automatic deployment state."""

import json
import os

from fastapi.testclient import TestClient

from app.main import app
from app.routers import deploys


def release(root, name, commit, installed):
    directory = root / "releases" / name
    directory.mkdir(parents=True)
    (directory / "release.json").write_text(json.dumps({"release_id": name, "commit": commit}))
    os.utime(directory, (installed, installed))
    return directory


def test_reports_no_server_on_a_laptop(tmp_path, monkeypatch):
    monkeypatch.setattr(deploys, "ROOT", tmp_path / "missing")
    body = TestClient(app).get("/deploys").json()
    assert body == {"server": False, "running": None, "previous": None, "releases": [], "autodeploy": None}


def test_reports_running_release_installed_releases_and_autodeploy_history(tmp_path, monkeypatch):
    root = tmp_path / "opt"
    old = release(root, "build-old", "a" * 40, 1_800_000_000)
    new = release(root, "build-new", "b" * 40, 1_800_000_600)
    (root / "current").symlink_to(new)
    (root / "previous").symlink_to(old)
    status = tmp_path / "autodeploy.json"
    status.write_text(json.dumps({"history": [{"outcome": "deployed", "commit": "b" * 40}], "checked": {"result": "Up to date"}}))
    monkeypatch.setattr(deploys, "ROOT", root)
    monkeypatch.setattr(deploys, "STATUS", status)
    body = TestClient(app).get("/deploys").json()
    assert body["server"] is True
    assert body["running"]["release_id"] == "build-new" and body["running"]["commit"] == "b" * 40
    assert body["previous"] == {"release_id": "build-old", "commit": "a" * 40}
    assert [r["release_id"] for r in body["releases"]] == ["build-new", "build-old"]
    assert body["autodeploy"]["checked"]["result"] == "Up to date"
