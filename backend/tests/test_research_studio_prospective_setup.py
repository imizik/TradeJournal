import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def setup_module_code():
    source = Path(__file__).parents[2]/"deploy/research_studio_prospective.py"
    spec = importlib.util.spec_from_file_location("forward_setup_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_runtime_guard_walks_actual_project_imports(tmp_path):
    module = setup_module_code()
    source = Path(__file__).parents[1]
    backend = tmp_path/"backend"
    for name in module.SOURCE_FILES:
        target = backend/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, target)
    assert set(module.validate_sources(backend)) == set(module.SOURCE_FILES)
    target = backend/"scripts/research_studio_prospective.py"
    target.write_text(target.read_text()+"\nfrom app.database import engine\n")
    with pytest.raises(ValueError, match="outside the frozen runtime"):
        module.validate_sources(backend)


def test_operator_directory_creation_refuses_symlink_ancestors(tmp_path):
    module = setup_module_code()
    outside = tmp_path/"outside"
    outside.mkdir()
    link = tmp_path/"link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        module._directory(link/"records", os.geteuid(), os.getegid())
    assert not (outside/"records").exists()


def test_private_credential_source_refuses_links_and_public_permissions(tmp_path):
    module = setup_module_code()
    file = tmp_path/"credentials.env"
    file.write_text("ALPACA_API_KEY=invented\n")
    file.chmod(0o644)
    with pytest.raises(ValueError, match="root-owned private"):
        module._private_file(file)
    link = tmp_path/"linked.env"
    link.symlink_to(file)
    with pytest.raises(OSError):
        module._private_file(link)


def test_study_units_keep_runtime_frozen_and_writes_scoped():
    module = setup_module_code()
    service, timer = module.service_unit(), module.timer_unit()
    assert "/opt/tradejournal/current" not in service
    assert "User=tradejournal" in service
    assert "ProtectSystem=strict" in service
    assert "ReadWritePaths="+str(module.ROOT)+"/records "+str(module.ROOT)+"/cache" in service
    assert "EnvironmentFile="+str(module.ENV) in service
    assert "20:30:00 America/New_York" in timer
    assert "Persistent=true" in timer


def test_offline_minimal_environment_executes_actual_study_runtime(tmp_path):
    module = setup_module_code()
    source = Path(__file__).parents[1]
    target = tmp_path/"backend"
    versions = module.copy_environment(source/".venv", target/".venv")
    assert "numpy" in versions and "httpx" in versions
    assert "sqlalchemy" not in versions and "alpaca-py" not in versions
    for name in module.SOURCE_FILES:
        file = target/name
        file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, file)
    moved = tmp_path/"frozen-runtime"
    target.rename(moved)
    assert not (moved/".venv/bin/python").resolve().is_relative_to(source/".venv")
    result = subprocess.run([str(moved/".venv/bin/python"), str(moved/"scripts/research_studio_prospective.py"), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "register" in result.stdout and "review" in result.stdout
