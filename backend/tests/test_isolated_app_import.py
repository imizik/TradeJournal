"""The retained replay overlay can boot without optional journal review code."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("isolated", [True, False])
def test_optional_live_imports_are_excluded_only_from_isolated_trial(isolated):
    code = '''
import importlib.abc
import sys

ISOLATED = ISOLATED_VALUE
class MissingLiveModules(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if ISOLATED and fullname in {"app.routers.monthly_review", "app.routers.scanner",
                                     "app.engine.market_watch_wakes"}:
            raise ModuleNotFoundError("Live-only module is absent from the retained isolated overlay")

sys.meta_path.insert(0, MissingLiveModules())
from app.main import app, _maybe_start_market_watch
paths = app.openapi()["paths"]
assert ("/monthly-review" in paths) is not ISOLATED
assert ("app.routers.monthly_review" in sys.modules) is not ISOLATED
assert ("/scanner/settings" in paths) is not ISOLATED
assert ("app.routers.scanner" in sys.modules) is not ISOLATED
if ISOLATED:
    import asyncio
    assert asyncio.run(_maybe_start_market_watch(app)) is None
    assert app.state.market_watch is None
    assert "app.engine.market_watch_wakes" not in sys.modules
'''.replace("ISOLATED_VALUE", repr(isolated))
    backend = Path(__file__).resolve().parents[1]
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(backend),
           "DATABASE_URL": "sqlite:///:memory:", "MIGRATION_DATABASE_URL": "sqlite:///:memory:",
           "TJ_DOT_TRIAL_ENABLED": "true" if isolated else "false"}
    result = subprocess.run([sys.executable, "-c", code], cwd=backend, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
