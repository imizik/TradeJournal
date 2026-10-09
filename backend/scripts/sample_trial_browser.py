"""Launch only the named disposable sample browser fixture with real auth guards."""
import importlib.util
import os
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
ROOT = BACKEND / "data/sample_browser_trial"
EXPECTED = f"sqlite:///{ROOT}/data/trial.db"


def build_app():
    if os.environ.get("DATABASE_URL") != EXPECTED or os.environ.get("MIGRATION_DATABASE_URL") != EXPECTED:
        raise RuntimeError("Browser fixture refuses any other database")
    spec = importlib.util.spec_from_file_location("dot_trial_app", BACKEND.parent / "deploy/dot_trial_app.py")
    trial = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trial)
    app = trial.build_app(root=ROOT)
    from sqlmodel import Session
    from app.database import engine
    from app.engine import sample_practice, sample_replay, access
    with Session(engine) as db:
        sample_practice.prepare(db)
        if access.sample_replays_enabled():
            sample_replay.prepare(db, scenarios=True)
        if access.market_writes_enabled():
            from scripts import market_trial_fixture
            market_trial_fixture.prepare(db)
    return app
