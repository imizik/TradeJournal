"""Trial lifetime isolation, credential shutdown, and failed-install recovery."""
import importlib.util
import io
import json
from pathlib import Path
import re
import tarfile
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select
from starlette.middleware import Middleware

from app import access_middleware
from app.engine import access
from app.main import app
from app.models import AccessPrincipal, Fill
from tests.test_browser_access import boundary as boundary, signin
from tests.test_dot_trial import trial


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[2] / f"deploy/{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


control = module("dot_trial_control")
installer = module("dot_trial_install")


def test_private_owner_cannot_mutate_any_trial_domain_route(boundary):
    boundary.patch.setenv("TJ_ACCESS_SAMPLE_DATA", "true")
    boundary.patch.setattr(app, "user_middleware", [app.user_middleware[0], Middleware(trial.FixtureMarket), *app.user_middleware[1:]])
    boundary.patch.setattr(app, "middleware_stack", None)
    # Sweep the real route inventory so future journal/job writes are denied too.
    for route in access_middleware.registered_routes(app.routes):
        for method in getattr(route, "methods", ()):
            if method not in {"POST", "PUT", "PATCH", "DELETE"} or route.path.startswith("/access/"):
                continue
            if (method, route.path) == ("POST", "/quotes/positions"):
                continue
            path = re.sub(r"\{[^}]+\}", "sample", route.path)
            response = boundary.owner.request(method, path, json={})
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["detail"] == "Sample trial data is read-only"
    with Session(boundary.engine) as db:
        assert db.exec(select(Fill)).all() == []
    # Auth management, fixture POST reads and assistant journal reads still work.
    created = boundary.owner.post("/access/assistants", json={"identifier": "inspector", "grants": {"symbols": ["MU"], "run_ids": [], "journal_read": True}})
    assert created.status_code == 201
    assert signin(boundary, identifier="inspector", key=created.json()["key"]).status_code == 200
    assert boundary.public.get("/fills").status_code == 200
    assert boundary.public.post("/quotes/positions", json=[]).status_code == 200
    assert boundary.public.post("/access/logout").status_code == 200


def test_shutdown_revokes_all_assistants_sessions_and_keys_preserving_owner(boundary):
    assert signin(boundary).status_code == 200
    created = boundary.owner.post("/access/assistants", json={"identifier": "second", "grants": {"symbols": ["MU"], "run_ids": [], "journal_read": False}})
    assert created.status_code == 201
    with TestClient(app) as second:
        second.headers.update({k: v for k, v in boundary.public.headers.items() if k != "x-tj-csrf"})
        other = SimpleNamespace(public=second, key=created.json()["key"])
        assert signin(other, identifier="second").status_code == 200
        with Session(boundary.engine) as db:
            db.add(AccessPrincipal(id="already-revoked", enabled=False, version=7))
            db.commit()
            before = {row.id: (row.enabled, row.version) for row in db.exec(select(AccessPrincipal)).all()}
            control.revoke_rows(db)
        assert boundary.public.get("/access/me").status_code == 401
        assert second.get("/access/me").status_code == 401
        assert boundary.owner.get("/access/me").status_code == 200
        assert signin(boundary).status_code == 401
        assert signin(other, identifier="second").status_code == 401
        with Session(boundary.engine) as db:
            for row in db.exec(select(AccessPrincipal)).all():
                if row.id == access.OWNER:
                    assert (row.enabled, row.version) == before[row.id]
                else:
                    assert not row.enabled
                    assert row.version == before[row.id][1] + 1


@pytest.fixture
def installation(tmp_path, monkeypatch):
    roots = {name: tmp_path / name.lower() for name in ("ROOT", "STATE", "CONFIG", "RELEASES", "UNIT_DIR")}
    for name, path in roots.items():
        monkeypatch.setattr(installer, name, path)
    roots["UNIT_DIR"].mkdir()
    unrelated = roots["UNIT_DIR"] / "tradejournal-api.service"
    unrelated.write_text("production stays untouched")
    proxy = tmp_path / "socket-proxy"
    proxy.touch()
    monkeypatch.setattr(installer, "SOCKET_PROXY", proxy)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installer.os, "chown", lambda *args: None)
    monkeypatch.setattr(installer.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=123, pw_gid=123))
    release = roots["RELEASES"] / "verified"
    for folder in ("backend", "bin", "deploy", "frontend/.next"):
        (release / folder).mkdir(parents=True)
    (release / "release.json").write_text(json.dumps({"commit": "6a2f5a50d092"}))
    archive = tmp_path / "frontend.tar"
    def archive_file(name):
        with tarfile.open(archive, "w") as target:
            entry = tarfile.TarInfo(name)
            entry.size = 2
            target.addfile(entry, io.BytesIO(b"js"))
    archive_file("server.js")
    source = tmp_path / "fixture.py"
    source.write_text("# fixture")
    args = SimpleNamespace(release=release, frontend_archive=archive, fixture_file=source, control_file=source,
        owner_origin="https://owner.example", assistant_origin="https://assistant.example")
    state = {"user": False, "fault": None, "calls": []}
    def command(*args, **kwargs):
        values = [str(value) for value in args]
        state["calls"].append(values)
        if values[0] == "useradd":
            state["user"] = True
        stage = "seed" if any(value.endswith("seed_dev_data.py") for value in values) else values[0]
        if values[:2] == ["systemctl", "enable"]:
            stage = "startup"
        if state["fault"] == stage:
            state["fault"] = None
            raise RuntimeError("injected " + stage)
        if any(value.endswith("access-config.py") for value in values):
            (roots["CONFIG"] / "access-assistant.env").write_text("TJ_ASSISTANT_ENABLED=false\n")
        if "-c" in values:
            (roots["CONFIG"] / "credential.json").write_text("temporary credential")
        if values[0] == "userdel":
            state["user"] = False
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(installer, "run", command)
    monkeypatch.setattr(installer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0 if state["user"] else 2))
    return SimpleNamespace(roots=roots, args=args, state=state, archive_file=archive_file, unrelated=unrelated)


@pytest.mark.parametrize("fault", ["archive", "seed", "useradd", "startup"])
def test_failed_install_removes_only_owned_artifacts_and_can_retry(installation, fault):
    case = installation
    if fault == "archive":
        case.archive_file("node_modules/unsafe")
    else:
        case.state["fault"] = fault
    with pytest.raises((ValueError, RuntimeError)):
        installer.install(case.args)
    assert not case.state["user"]
    for name in ("ROOT", "STATE", "CONFIG"):
        assert not case.roots[name].exists()
    assert list(case.roots["UNIT_DIR"].iterdir()) == [case.unrelated]
    assert case.unrelated.read_text() == "production stays untouched"
    if fault == "startup":
        actions = [call[1] for call in case.state["calls"] if call[0] == "systemctl"]
        assert actions.index("stop") > actions.index("enable")
        assert "disable" in actions
    case.archive_file("server.js")
    installer.install(case.args)
    assert case.state["user"]
    assert (case.roots["CONFIG"] / "manifest.json").is_file()
    # A successful installation is never overwritten by a retry.
    with pytest.raises(ValueError, match="already exists"):
        installer.install(case.args)


def test_cleanup_failure_retains_state_for_inspection(installation, monkeypatch):
    original = installer.run
    installation.state["fault"] = "startup"
    def fail_stop(*args, **kwargs):
        if args[:2] == ("systemctl", "stop"):
            raise RuntimeError("cannot stop service")
        return original(*args, **kwargs)
    monkeypatch.setattr(installer, "run", fail_stop)
    with pytest.raises(RuntimeError, match="rollback is incomplete"):
        installer.install(installation.args)
    assert installation.roots["STATE"].exists()
    assert installation.roots["CONFIG"].exists()
    assert installation.state["user"]


def test_existing_unit_is_not_removed_on_install_refusal(installation):
    existing = installation.roots["UNIT_DIR"] / installer.API
    existing.write_text("preexisting installation")
    with pytest.raises(ValueError, match="unit already exists"):
        installer.install(installation.args)
    assert existing.read_text() == "preexisting installation"
    assert not installation.roots["ROOT"].exists()
