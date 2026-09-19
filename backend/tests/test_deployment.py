"""Destructive deployment operations are exercised only against tmp_path/fakes.

Native systemd and the packaged application have a separate Ubuntu CI smoke.
"""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest


def load(name):
    path = Path(__file__).resolve().parents[2] / "deploy" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"deployment_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def control(tmp_path, monkeypatch):
    module = load("control")
    monkeypatch.setattr(module, "ROOT", tmp_path / "opt")
    (module.ROOT / "releases").mkdir(parents=True)
    return module


def test_schema_mismatch_refuses_before_stopping_services(control, monkeypatch):
    old = control.release_path("old")
    old.mkdir()
    control.atomic_link(old, control.ROOT / "current")
    calls = []
    monkeypatch.setattr(control, "stop_services", lambda: calls.append("stop"))

    def incompatible(*args):
        raise RuntimeError("Database is ahead of this code")

    monkeypatch.setattr(control, "database", incompatible)
    with pytest.raises(RuntimeError, match="ahead"):
        control.activate(control.release_path("new"), "scratch")
    assert control.current() == old
    assert calls == []


def test_failed_activation_restores_previous_release(control, monkeypatch):
    old, new = [control.release_path(name) for name in ("old", "new")]
    old.mkdir()
    new.mkdir()
    control.atomic_link(old, control.ROOT / "current")
    events = []
    monkeypatch.setattr(control, "database", lambda release, *_: events.append(("check", release.name)))
    monkeypatch.setattr(control, "stop_services", lambda: events.append(("stop", "")))

    def start(release, _identity):
        events.append(("start", release.name))
        if release == new:
            raise RuntimeError("bad frontend")

    monkeypatch.setattr(control, "start_services", start)
    with pytest.raises(RuntimeError, match="bad frontend"):
        control.activate(new, "scratch")
    assert control.current() == old
    assert events == [("check", "new"), ("stop", ""), ("start", "new"), ("stop", ""), ("check", "old"), ("start", "old")]


def test_success_records_reversible_release_pair(control, monkeypatch):
    old, new = [control.release_path(name) for name in ("old", "new")]
    old.mkdir()
    new.mkdir()
    control.atomic_link(old, control.ROOT / "current")
    monkeypatch.setattr(control, "database", lambda *_: None)
    monkeypatch.setattr(control, "stop_services", lambda: None)
    monkeypatch.setattr(control, "start_services", lambda *_: None)
    control.activate(new, "scratch")
    assert (control.current(), control.current("previous")) == (new, old)
    control.activate(control.current("previous"), "scratch")
    assert (control.current(), control.current("previous")) == (old, new)


def test_checksum_failure_does_not_extract(control, tmp_path):
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(b"not an archive")
    with pytest.raises(ValueError, match="checksum"):
        control.install(archive, "0" * 64)
    assert list((control.ROOT / "releases").iterdir()) == []


def test_archive_traversal_is_rejected_and_partial_release_removed(control, tmp_path, monkeypatch):
    archive = tmp_path / "release.tar"
    with tarfile.open(archive, "w") as bundle:
        for name, content in [("new/release.json", json.dumps({"release_id": "new"})), ("new/../../../outside", "unsafe")]:
            info = tarfile.TarInfo(name)
            data = content.encode()
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(control, "validate_platform", lambda _: None)
    with pytest.raises(tarfile.FilterError):
        control.install(archive, hashlib.sha256(archive.read_bytes()).hexdigest())
    assert not (tmp_path / "outside").exists()
    assert not control.release_path("new").exists()


def test_database_owner_must_match_routing_parameters():
    target = load("database").target
    assert target("postgresql+psycopg://app:secret@db/journal") == target("postgresql+psycopg://owner:other@db:5432/journal")
    assert target("postgresql+psycopg://app@db/journal") != target("postgresql+psycopg://owner@db/journal?host=other")


def test_database_helper_resets_login_environment_before_dropping_privileges(monkeypatch):
    database = load("database")
    account = SimpleNamespace(pw_name="tradejournal", pw_dir="/var/lib/tradejournal", pw_uid=123, pw_gid=456)
    events = []
    monkeypatch.setattr(database.pwd, "getpwnam", lambda _: account)
    monkeypatch.setattr(database.os, "geteuid", lambda: 0)
    monkeypatch.setattr(database.os, "initgroups", lambda name, gid: events.append(("groups", name, gid)))
    monkeypatch.setattr(database.os, "setgid", lambda gid: events.append(("gid", gid)))
    monkeypatch.setattr(database.os, "setuid", lambda uid: events.append(("uid", uid)))
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("LOGNAME", "root")

    database.drop_to_service_account()

    assert {name: database.os.environ[name] for name in ("HOME", "USER", "LOGNAME")} == {
        "HOME": "/var/lib/tradejournal",
        "USER": "tradejournal",
        "LOGNAME": "tradejournal",
    }
    assert events == [("groups", "tradejournal", 456), ("gid", 456), ("uid", 123)]


def test_archive_link_cannot_target_an_existing_release(control, tmp_path, monkeypatch):
    archive = tmp_path / "release.tar"
    with tarfile.open(archive, "w") as bundle:
        metadata = json.dumps({"release_id": "new"}).encode()
        info = tarfile.TarInfo("new/release.json")
        info.size = len(metadata)
        bundle.addfile(info, io.BytesIO(metadata))
        link = tarfile.TarInfo("new/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../existing"
        bundle.addfile(link)
    monkeypatch.setattr(control, "validate_platform", lambda _: None)
    with pytest.raises(tarfile.FilterError, match="leaves its release"):
        control.install(archive, hashlib.sha256(archive.read_bytes()).hexdigest())
    assert not control.release_path("new").exists()


def test_launcher_forces_private_bind_and_shared_ownership(tmp_path, monkeypatch):
    launch = load("launch")
    (tmp_path / "backend").mkdir()
    (tmp_path / "release.json").write_text('{"release_id":"test"}')
    monkeypatch.setattr(launch, "RELEASE", tmp_path)
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "api"])
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("JOB_EXECUTION_MODE", "embedded")
    monkeypatch.setenv("JOB_LOCK_DIR", "/wrong")
    monkeypatch.chdir(tmp_path)
    commands = []
    monkeypatch.setattr(launch.os, "execv", lambda _, command: commands.append(command))
    launch.main()
    assert commands[0][-4:] == ["--host", "127.0.0.1", "--port", "8080"]
    assert launch.os.environ["JOB_LOCK_DIR"] == "/var/lib/tradejournal/job-locks"
    assert launch.os.environ["JOB_EXECUTION_MODE"] == "external"
