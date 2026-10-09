import importlib.util
import os
from pathlib import Path
import sqlite3

import pytest
from starlette.middleware import Middleware

from app import access_middleware
from app.main import app
from tests.test_browser_access import boundary as boundary, signin

spec = importlib.util.spec_from_file_location("dot_trial_app", Path(__file__).resolve().parents[2] / "deploy/dot_trial_app.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


@pytest.fixture
def sample_env(tmp_path):
    root = tmp_path / "trial"
    (root / "data").mkdir(parents=True)
    (root / ".sample-installation").touch()
    path = root / "data/trial.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE fill (raw_email_id TEXT)")
        db.execute("INSERT INTO fill VALUES ('seed:sample')")
    env = {"TJ_DOT_TRIAL_ENABLED": "true", "TJ_ACCESS_ENABLED": "true", "TJ_ACCESS_SAMPLE_DATA": "true",
           "DATABASE_URL": f"sqlite:///{path}", "MIGRATION_DATABASE_URL": f"sqlite:///{path}", "JOB_EXECUTION_MODE": "external",
           **{name: "false" for name in trial.OFF_FLAGS}}
    return root, env


def test_only_seeded_isolated_database_is_accepted(sample_env):
    root, env = sample_env
    trial.validate_environment(env, root)
    with sqlite3.connect(root / "data/trial.db") as db:
        db.execute("INSERT INTO fill VALUES ('real-email')")
    with pytest.raises(RuntimeError, match="exclusively seeded"):
        trial.validate_environment(env, root)


@pytest.mark.parametrize("key,value", [("DATABASE_URL", "postgresql://host/production"),
    ("MIGRATION_DATABASE_URL", "postgresql://host/production"), ("TJ_ACCESS_ENABLED", "false"),
    ("TJ_ACCESS_SAMPLE_DATA", "false"), ("OPENAI_API_KEY", "configured"),
    ("PRACTICE_AGENT_ENABLED", "true"), ("GMAIL_LISTENER_ENABLED", "true"), ("JOB_EXECUTION_MODE", "embedded")])
def test_trial_refuses_live_config_before_opening_database(sample_env, key, value):
    root, env = sample_env
    with pytest.raises(RuntimeError, match="non-isolated"):
        trial.validate_environment({**env, key: value}, root)


def test_symlink_to_another_database_is_refused(sample_env):
    root, env = sample_env
    path = root / "data/trial.db"
    path.rename(root / "other.db")
    path.symlink_to(root / "other.db")
    with pytest.raises(RuntimeError, match="non-isolated"):
        trial.validate_environment(env, root)


def test_fixture_replies_remain_inside_auth_and_symbol_boundary(boundary):
    assert app.user_middleware[0].cls is access_middleware.AccessMiddleware
    boundary.patch.setattr(app, "user_middleware", [app.user_middleware[0], Middleware(trial.FixtureMarket), *app.user_middleware[1:]])
    boundary.patch.setattr(app, "middleware_stack", None)
    assert boundary.public.get("/charts/workspace?symbol=MU&watchlist=MU").status_code == 401
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/charts/workspace?symbol=NVDA&watchlist=NVDA").status_code == 403
    result = boundary.public.get("/charts/workspace?symbol=MU&watchlist=MU,NBIS")
    assert result.status_code == 200
    data = result.json()
    assert data["provider"] == trial.SOURCE
    assert len(data["panels"]["5m"]["bars"]) == 120
    assert [quote["symbol"] for quote in data["quotes"]] == ["MU", "NBIS"]
    assert boundary.public.post("/practice/prepare", json={}).status_code == 403
    assert boundary.public.get("/unregistered-fixture").status_code == 404


def test_fixture_candles_are_bounded_and_labelled():
    bars = trial.candles("NBIS", "1m", limit=100000)
    assert len(bars) == 120
    assert all(row["source"] == trial.SOURCE and row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"] for row in bars)
    assert not any(os.environ.get(name) for name in ("TJ_DOT_TRIAL_ENABLED",))
