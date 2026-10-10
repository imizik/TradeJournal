"""Deployment defaults preserve private access and keep assistant ingress off."""
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def module():
    spec = importlib.util.spec_from_file_location("access_config", ROOT / "deploy/access-config.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_configuration_is_separate_private_and_does_not_enable_ingress(tmp_path):
    directory = tmp_path / "config"
    names = module().generate(directory, "https://owner.example", "https://assistant.example")
    assert len(names) == 6
    assert "TJ_ASSISTANT_ENABLED=false" in (directory / "access-assistant.env").read_text()
    for name in names:
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    owner = (directory / "access-owner.env").read_text()
    public = (directory / "access-assistant.env").read_text()
    assert "TJ_OWNER_GATEWAY_KEY" not in public
    owner_key = next(line for line in owner.splitlines() if line.startswith("TJ_GATEWAY_KEY="))
    assert owner_key not in public
    backend = (directory / "access-backend.env").read_text()
    raw = next(line.split("=", 1)[1] for line in backend.splitlines() if line.startswith("TJ_ACCESS_SERVICES="))
    services = json.loads(raw.strip("'"))
    assert set(services) == {"monitor", "automation", "manual_mcp"}
    with pytest.raises(ValueError, match="refusing"):
        module().generate(directory, "https://owner.example", "https://assistant.example")


def test_local_http_cannot_be_used_for_internet_hostnames(tmp_path):
    with pytest.raises(ValueError):
        module().generate(tmp_path, "https://owner.example", "https://assistant.example", local_http=True)
    module().generate(tmp_path, "http://127.0.0.1:3100", "http://127.0.0.1:3101", local_http=True)


def test_public_unit_cannot_read_private_state_and_is_optional():
    text = (ROOT / "deploy/systemd/tradejournal-assistant.service").read_text()
    assert "DynamicUser=yes" in text
    assert "InaccessiblePaths=/etc/tradejournal /var/lib/tradejournal" in text
    assert "HOSTNAME=127.0.0.1 PORT=3001" in text
    assert "backend.env" not in text and "access-owner.env" not in text
    controller = (ROOT / "deploy/control.py").read_text()
    assert 'OPTIONAL_UNITS = ["tradejournal-assistant.service"' in controller
    assert 'for service in ["tradejournal-assistant.service"' in controller



def test_native_trial_refuses_non_ci_and_unrecognized_database(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "deploy"))
    spec = importlib.util.spec_from_file_location("auth_smoke", ROOT / "deploy/auth-smoke.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    monkeypatch.setattr(value.os, "geteuid", lambda: 0)
    monkeypatch.delenv("TJ_DISPOSABLE_RUNNER", raising=False)
    with pytest.raises(SystemExit, match="disposable"):
        value.main()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("TJ_DISPOSABLE_RUNNER", "1")
    monkeypatch.setattr(value, "call", lambda *a, **kw: (200, {"environment": {"identity": "production"}}))
    monkeypatch.setattr(value.control, "run", lambda *a, **kw: pytest.fail("Unrecognized installation was modified"))
    with pytest.raises(SystemExit, match="other database"):
        value.main()
