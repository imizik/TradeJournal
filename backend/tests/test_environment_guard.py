"""
Knowing which database you are on, and not wiping the wrong one.

Two destructive endpoints delete every non-manual fill, both reachable as
one-click buttons in the UI, and until now neither knew nor cared which
database it was pointed at. With a Neon dev branch alongside production that
is one edited .env away from wiping real trading history.

The guard follows a rule this repository arrived at the hard way, after two
inference-based guards leaked: a stored flag authorizing destruction goes
stale the moment the database it described is repointed. So confirmation is
per-request and names the live target -- repoint DATABASE_URL and the expected
value changes with it.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.environment import describe, require_destructive_confirmation

NEON_DEV = (
    "postgresql+psycopg://tj_user:s3cret@"
    "ep-cool-dev-a1b2c3.us-east-2.aws.neon.tech/tradejournal?sslmode=require"
)
NEON_PROD = (
    "postgresql+psycopg://tj_user:s3cret@"
    "ep-prod-x9y8z7.us-east-2.aws.neon.tech/tradejournal?sslmode=require"
)


def test_local_sqlite_is_recognised_as_disposable():
    environment = describe("sqlite:////home/x/backend/data/trade_journal.db")
    assert environment.is_local
    assert environment.backend == "sqlite"
    assert environment.identity == "trade_journal.db"
    assert not environment.destructive_requires_confirmation


def test_hosted_database_requires_confirmation():
    environment = describe(NEON_PROD)
    assert not environment.is_local
    assert environment.backend == "postgresql"
    assert environment.destructive_requires_confirmation


def test_identity_never_contains_credentials():
    """It is returned by /health and written to job rows."""
    rendered = str(describe(NEON_PROD).as_dict())
    assert "s3cret" not in rendered
    assert "tj_user" not in rendered


def test_dev_branch_and_production_are_distinguishable():
    """
    The whole point. Neon gives each branch its own endpoint hostname, so the
    identity an operator has to type differs between them -- confirmation
    copied from the wrong environment does not work.
    """
    dev = describe(NEON_DEV).identity
    production = describe(NEON_PROD).identity
    assert dev != production
    assert "dev" in dev and "prod" in production


def test_app_env_labels_but_does_not_unlock(monkeypatch):
    """
    APP_ENV is display only. If a label could disable the guard, a stale label
    on a repointed database would authorize destroying it -- the exact failure
    mode of the marker-based guard in test_postgres_parity.py.
    """
    monkeypatch.setenv("APP_ENV", "dev")
    environment = describe(NEON_PROD)
    assert environment.name == "dev"
    assert environment.destructive_requires_confirmation, (
        "calling a hosted database 'dev' must not disable confirmation"
    )


def test_local_passes_without_confirmation(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/local.db")
    import app.database
    import importlib

    importlib.reload(app.database)
    require_destructive_confirmation(None, "POST /fills/resync-all")  # must not raise


def _reload_database_with(monkeypatch, url: str):
    monkeypatch.setenv("DATABASE_URL", url)
    import importlib

    import app.database

    importlib.reload(app.database)


def test_hosted_refuses_without_confirmation(monkeypatch):
    _reload_database_with(monkeypatch, NEON_PROD)
    with pytest.raises(HTTPException) as raised:
        require_destructive_confirmation(None, "POST /fills/resync-all")
    assert raised.value.status_code == 400
    # The message has to tell the caller exactly what to send.
    assert "ep-prod-x9y8z7" in raised.value.detail
    assert "confirm" in raised.value.detail


def test_hosted_refuses_the_wrong_database_name(monkeypatch):
    """Confirmation copied from the dev branch must not unlock production."""
    _reload_database_with(monkeypatch, NEON_PROD)
    dev_identity = describe(NEON_DEV).identity
    with pytest.raises(HTTPException):
        require_destructive_confirmation(dev_identity, "POST /fills/resync-all")


def test_hosted_accepts_the_matching_database_name(monkeypatch):
    """A guard that never accepts is as broken as one that never refuses."""
    _reload_database_with(monkeypatch, NEON_PROD)
    identity = describe().identity
    environment = require_destructive_confirmation(identity, "POST /fills/resync-all")
    assert environment.identity == identity


def test_health_reports_the_environment(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    _reload_database_with(monkeypatch, f"sqlite:///{tmp_path}/health.db")
    import importlib

    import app.main

    importlib.reload(app.main)

    with TestClient(app.main.app) as client:
        payload = client.get("/health").json()

    assert payload["status"] == "ok"
    environment = payload["environment"]
    assert environment["backend"] == "sqlite"
    assert environment["is_local"] is True
    assert environment["destructive_requires_confirmation"] is False
