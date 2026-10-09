"""Archive scope and rollback preserve the pinned Linux runtime and its state."""
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile

import pytest

spec = importlib.util.spec_from_file_location("dot_trial_update", Path(__file__).resolve().parents[2] / "deploy/dot_trial_update.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def archive(path, values):
    with tarfile.open(path, "w") as target:
        for name, value in values.items():
            member = tarfile.TarInfo(name)
            data = value.encode()
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))


@pytest.mark.parametrize("name", ["../outside", "/etc/tradejournal/backend.env", "node_modules/native", "public/node_modules/native"])
def test_frontend_archives_cannot_escape_or_replace_linux_dependencies(tmp_path, name):
    path = tmp_path / "bad.tar"
    archive(path, {name: "unsafe"})
    with pytest.raises(ValueError):
        updater.extract(path, tmp_path / "unpacked", backend=False)
    assert not (tmp_path / "outside").exists()


def test_backend_archive_requires_exact_selected_source_set(tmp_path):
    path = tmp_path / "bad.tar"
    archive(path, {"backend/.env": "no secrets allowed"})
    with pytest.raises(ValueError, match="selected update scope"):
        updater.extract(path, tmp_path / "unpacked", backend=True)


@pytest.fixture
def update_fixture(tmp_path, monkeypatch):
    runtime, config = tmp_path / "runtime", tmp_path / "config"
    runtime.mkdir()
    config.mkdir()
    monkeypatch.setattr(updater, "RUNTIME", runtime)
    monkeypatch.setattr(updater, "CONFIG", config)
    monkeypatch.setattr(updater, "check_target", lambda: None)
    for name in updater.SOURCE_FILES - {"backend/app/engine/sample_practice.py", "deploy/dot_trial_seed.py"}:
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# old source\n")
    for name, value in {".next/old.js": "old frontend", "server.js": "old server", "package.json": "old package", "public/icon.png": "old icon", "node_modules/native": "verified Linux dependency"}.items():
        path = runtime / "frontend" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    (config / "trial-runtime.env").write_text("TJ_SAMPLE_DECISION_WRITES=false\nDATABASE_URL=sample\n")
    (config / "manifest.json").write_text(json.dumps({"published": True}))
    backend, frontend = tmp_path / "backend.tar", tmp_path / "frontend.tar"
    archive(backend, {name: "# new source\n" for name in updater.SOURCE_FILES})
    archive(frontend, {".next/new.js": "new frontend", "server.js": "new server", "package.json": "new package", "public/icon.png": "new icon"})
    calls = []
    monkeypatch.setattr(updater, "run", lambda *args: calls.append(args))
    return runtime, config, backend, frontend, calls


def test_readiness_failure_restores_sources_assets_and_permissions(update_fixture, monkeypatch):
    runtime, config, backend, frontend, calls = update_fixture
    attempts = []
    def ready():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("new runtime failed")
    monkeypatch.setattr(updater, "ready", ready)
    with pytest.raises(RuntimeError, match="new runtime failed"):
        updater.update(backend, frontend, "a" * 40)
    assert (runtime / "frontend/server.js").read_text() == "old server"
    assert (runtime / "frontend/.next/old.js").read_text() == "old frontend"
    assert (runtime / "frontend/node_modules/native").read_text() == "verified Linux dependency"
    assert not (runtime / "backend/app/engine/sample_practice.py").exists()
    assert "TJ_SAMPLE_DECISION_WRITES=false" in (config / "trial-runtime.env").read_text()
    assert [call[1] for call in calls] == ["stop", "start", "stop", "start"]
    snapshots = list(runtime.parent.glob("sample-update-*/backup/backend/app/engine/access.py"))
    assert len(snapshots) == 1 and snapshots[0].read_text() == "# old source\n"


def test_partial_asset_move_does_not_delete_untouched_original_files(update_fixture, monkeypatch):
    runtime, config, backend, frontend, _ = update_fixture
    original = shutil.move
    failed = []
    def move(source, destination):
        if Path(source) == runtime / "frontend/server.js" and not failed:
            failed.append(True)
            raise OSError("cannot move server")
        return original(source, destination)
    monkeypatch.setattr(updater.shutil, "move", move)
    monkeypatch.setattr(updater, "ready", lambda: None)
    with pytest.raises(OSError, match="cannot move server"):
        updater.update(backend, frontend, "a" * 40)
    assert (runtime / "frontend/server.js").read_text() == "old server"
    assert (runtime / "frontend/package.json").read_text() == "old package"
    assert (runtime / "frontend/public/icon.png").read_text() == "old icon"
    assert (runtime / "frontend/.next/old.js").exists()


def test_symlinked_code_parent_is_refused_before_service_changes(update_fixture, monkeypatch, tmp_path):
    runtime, _, backend, frontend, calls = update_fixture
    real = tmp_path / "real-api"
    (runtime / "backend/app").rename(real)
    (runtime / "backend/app").symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(updater, "ready", lambda: None)
    with pytest.raises(ValueError, match="symlink"):
        updater.update(backend, frontend, "a" * 40)
    assert calls == []
    assert (real / "engine/access.py").read_text() == "# old source\n"

def test_manifest_failure_rolls_back_code_and_write_enablement(update_fixture, monkeypatch):
    runtime, config, backend, frontend, _ = update_fixture
    original = Path.write_text
    def write(path, value, *args, **kwargs):
        if path == config / "manifest.json":
            raise OSError("manifest save failed")
        return original(path, value, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(updater, "ready", lambda: None)
    with pytest.raises(OSError, match="manifest save failed"):
        updater.update(backend, frontend, "a" * 40)
    assert (runtime / "frontend/server.js").read_text() == "old server"
    assert "TJ_SAMPLE_DECISION_WRITES=false" in (config / "trial-runtime.env").read_text()
    assert json.loads((config / "manifest.json").read_text()) == {"published": True}


def test_snapshot_failure_never_stops_the_live_trial(update_fixture, monkeypatch):
    runtime, config, backend, frontend, calls = update_fixture
    original = Path.write_bytes
    def write(path, value):
        if path.name == "trial-runtime.env" and "backup" in path.parts:
            raise OSError("snapshot failed")
        return original(path, value)
    monkeypatch.setattr(Path, "write_bytes", write)
    with pytest.raises(OSError, match="snapshot failed"):
        updater.update(backend, frontend, "a" * 40)
    assert calls == []
    assert (runtime / "frontend/server.js").read_text() == "old server"


def test_partial_service_stop_restarts_original_trial_without_mutating_files(update_fixture, monkeypatch):
    runtime, config, backend, frontend, calls = update_fixture
    def run(*args):
        calls.append(args)
        if args[1] == "stop":
            raise RuntimeError("partial stop failed")
    monkeypatch.setattr(updater, "run", run)
    monkeypatch.setattr(updater, "ready", lambda: None)
    with pytest.raises(RuntimeError, match="partial stop failed"):
        updater.update(backend, frontend, "a" * 40)
    assert [call[1] for call in calls] == ["stop", "start"]
    assert (runtime / "frontend/server.js").read_text() == "old server"
    assert "TJ_SAMPLE_DECISION_WRITES=false" in (config / "trial-runtime.env").read_text()
