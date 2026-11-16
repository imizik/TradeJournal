"""How he uses the desk (``app/engine/desk_use.py``): daily totals per desk piece and device size, the 14-day summary the
"How I use the desk" view and the fold suggestion read, and folds saved per size. Invented numbers, no network."""

from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine as sa_create_engine, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import desk_use
from app.models import DeskUseDay
from app.routers import copilot_desk_use
from tests.test_plan_target import _alembic

NOW = datetime(2026, 11, 20, 11, 0, tzinfo=desk_use.ET)  # Friday Nov 20 2026, 11:00 New York
TODAY = date(2026, 11, 20)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def row(day: date, piece: str, opens=0, taps=0, seen_s=0):
    return {"day": day, "piece": piece, "opens": opens, "taps": taps, "seen_s": seen_s}


def test_flushes_add_onto_the_day_per_size_and_skip_empty_and_out_of_range_days(db):
    assert desk_use.record(db, "desk", [row(TODAY, "tab.grid", opens=1, seen_s=30), row(TODAY, "feed.chatter"),
                                        row(date(2026, 9, 1), "tab.grid", opens=5), row(date(2026, 11, 22), "tab.grid", opens=5)], NOW) \
        == {"saved": 1, "skipped": 2}
    desk_use.record(db, "desk", [row(TODAY, "tab.grid", opens=2, taps=3, seen_s=15)], NOW)
    desk_use.record(db, "phone", [row(TODAY, "tab.grid", taps=1)], NOW)
    rows = {(r.size, r.piece): (r.opens, r.taps, r.seen_s) for r in db.exec(select(DeskUseDay)).all()}
    assert rows == {("desk", "tab.grid"): (3, 3, 45), ("phone", "tab.grid"): (0, 1, 0)}  # chatter's empty row is never kept


def test_counts_are_capped_and_only_catalog_shaped_ids_are_taken(db):
    desk_use.record(db, "desk", [row(TODAY, "paper", taps=50_000, seen_s=999_999)], NOW)
    found = db.exec(select(DeskUseDay)).one()
    assert (found.taps, found.seen_s) == (desk_use.MAX_COUNT, desk_use.MAX_SEEN)
    for bad in ("NVDA buy", "Paper", "", "x" * 41, "tab/grid"):
        with pytest.raises(desk_use.UseError):
            desk_use.record(db, "desk", [row(TODAY, bad, taps=1)], NOW)
    with pytest.raises(desk_use.UseError):
        desk_use.record(db, "tablet", [row(TODAY, "paper", taps=1)], NOW)


def test_the_summary_is_the_last_14_calendar_days_with_last_use_at_any_time(db):
    desk_use.record(db, "desk", [
        row(date(2026, 11, 6), "tab.grid", opens=4),  # 15 days back: outside the window, still its last use
        row(date(2026, 11, 7), "tab.grid", seen_s=600),  # first day in the window: on screen, never opened
        row(date(2026, 11, 7), "tab.chain", opens=2),
        row(TODAY, "tab.chain", opens=1, taps=2, seen_s=120),
    ], NOW)
    desk_use.record(db, "phone", [row(TODAY, "tab.grid", opens=9)], NOW)
    out = desk_use.summary(db, "desk", NOW)
    assert (out["today"], out["window_start"], out["window_days"]) == ("2026-11-20", "2026-11-07", 14)
    assert out["days_with_use"] == 3 and out["first_day"] == "2026-11-06"
    assert out["pieces"]["tab.grid"] == {"opens": 0, "taps": 0, "seen_s": 600, "last_used": "2026-11-06"}
    assert out["pieces"]["tab.chain"] == {"opens": 3, "taps": 2, "seen_s": 120, "last_used": "2026-11-20"}
    assert out["folds"] == {"folded": [], "snoozed_until": None}


def test_folds_are_saved_per_size_and_never_touch_the_other(db):
    desk_use.save_folds(db, "desk", ["tab.grid", "feed.chatter", "tab.grid"], None)
    desk_use.save_folds(db, "phone", ["paper"], date(2026, 12, 4))
    assert desk_use.read_folds(db) == {"desk": {"folded": ["feed.chatter", "tab.grid"], "snoozed_until": None},
                                       "phone": {"folded": ["paper"], "snoozed_until": "2026-12-04"}}
    desk_use.save_folds(db, "desk", [], None)  # Show again: one tap brings it back
    assert desk_use.read_folds(db)["phone"]["folded"] == ["paper"]
    with pytest.raises(desk_use.UseError):
        desk_use.save_folds(db, "desk", ["not a piece"], None)


def test_routes_are_owner_only_refuse_while_off_and_round_trip(db, monkeypatch):
    for route in ("POST /copilot/desk/use", "GET /copilot/desk/use", "PUT /copilot/desk/folds"):
        assert route in DOMAIN_ROUTES
    enabled = {"on": False}
    monkeypatch.setattr(copilot_desk_use.copilot, "settings", lambda: type("S", (), {"enabled": enabled["on"]})())
    app = FastAPI()
    app.include_router(copilot_desk_use.router, prefix="/copilot")
    app.dependency_overrides[get_session] = lambda: db
    client = TestClient(app)
    assert client.get("/copilot/desk/use").status_code == 503
    enabled["on"] = True
    day = desk_use.today().isoformat()
    saved = client.post("/copilot/desk/use", json={"size": "desk", "rows": [{"day": day, "piece": "tab.grid", "opens": 1, "seen_s": 15}]})
    assert saved.status_code == 200 and saved.json() == {"saved": 1, "skipped": 0}
    assert client.post("/copilot/desk/use", json={"size": "desk", "rows": [{"day": day, "piece": "NVDA", "taps": 1}]}).status_code == 422
    assert client.put("/copilot/desk/folds", json={"size": "desk", "folded": ["tab.grid"], "snoozed_until": None}).status_code == 200
    out = client.get("/copilot/desk/use", params={"size": "desk"}).json()
    assert out["pieces"]["tab.grid"]["opens"] == 1 and out["folds"]["folded"] == ["tab.grid"]
    assert client.get("/copilot/desk/use", params={"size": "phone"}).json()["folds"]["folded"] == []


def test_desk_use_stays_in_this_database():
    for path in ("app/engine/desk_use.py", "app/routers/copilot_desk_use.py"):
        imports = [line for line in (Path(__file__).resolve().parents[1] / path).read_text().splitlines()
                   if line.startswith(("import ", "from "))]
        assert not [line for line in imports if any(w in line for w in ("robinhood", "requests", "httpx", "tradier", "urllib"))], path


def test_the_migration_adds_only_the_desk_use_table(tmp_path):
    path = tmp_path / "use.sqlite"
    _alembic(path, "upgrade", "c4e8a2d6f0b3")
    engine = sa_create_engine(f"sqlite:///{path}")
    before = {name: [c["name"] for c in inspect(engine).get_columns(name)] for name in inspect(engine).get_table_names()}
    engine.dispose()
    _alembic(path, "upgrade", "d7a1c5e9b3f2")
    engine = sa_create_engine(f"sqlite:///{path}")
    after = {name: [c["name"] for c in inspect(engine).get_columns(name)] for name in inspect(engine).get_table_names()}
    engine.dispose()
    assert set(after) - set(before) == {"desk_use_day"}
    assert {k: v for k, v in after.items() if k in before} == before
    _alembic(path, "downgrade", "c4e8a2d6f0b3")
