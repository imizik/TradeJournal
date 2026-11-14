"""GET /copilot/desk/overnight: the QQQ overnight paper book on the desk, from its own file only."""

from types import SimpleNamespace

from app.engine import desk_minute
from app.routers import copilot_desk
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)


def test_the_desk_route_reads_the_book_and_rides_the_minute_request(desk, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OVERNIGHT_BOOK_PATH", str(tmp_path / "none.sqlite3"))
    body = desk.get("/copilot/desk/overnight").json()
    assert (body["state"], body["nights"], body["symbol"]) == ("flat", [], "QQQ")
    assert not (tmp_path / "none.sqlite3").exists()  # reading never creates the file
    assert desk_minute.allowed("/copilot/desk/overnight")
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/overnight").status_code == 503


def test_the_momentum_route_reads_its_book_and_rides_the_minute_request(desk, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_PATH", str(tmp_path / "none.sqlite3"))
    body = desk.get("/copilot/desk/momentum").json()
    assert (body["holding"], body["days"], body["symbol"]) == (None, [], "QQQ")
    assert not (tmp_path / "none.sqlite3").exists()
    assert desk_minute.allowed("/copilot/desk/momentum")
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/momentum").status_code == 503
