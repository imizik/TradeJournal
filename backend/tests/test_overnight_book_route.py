"""GET /copilot/desk/overnight: the QQQ overnight paper book on the desk, from its own file only."""

from datetime import date, datetime
from types import SimpleNamespace

from app.engine import desk_minute, intraday_momentum_book, overnight_book, qqq_paper_coverage
from app.engine.chart_math import ET
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


def test_paper_books_disclose_unrecorded_windows_without_inventing_receipts(desk, tmp_path, monkeypatch):  # noqa: F811
    # Wednesday's calendar is unavailable; Thursday is closed and Friday is an early close.
    days = {
        date(2026, 11, 23): {"status": "open", "close": 960},
        date(2026, 11, 24): {"status": "open", "close": 960},
        date(2026, 11, 26): {"status": "closed", "close": None},
        date(2026, 11, 27): {"status": "open", "close": 780},
    }
    monkeypatch.setattr(qqq_paper_coverage, "chart_calendar", SimpleNamespace(cached=days.get))
    monkeypatch.setattr(copilot_desk.today, "_now", lambda: datetime(2026, 11, 27, 16, 5, tzinfo=ET).timestamp())
    monkeypatch.setenv("OVERNIGHT_BOOK_ENABLED", "true")
    night_path = tmp_path / "overnight.sqlite3"
    monkeypatch.setenv("OVERNIGHT_BOOK_PATH", str(night_path))
    nights = overnight_book.Store(night_path)
    nights.miss("2026-11-23", "no quote")
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_ENABLED", "true")
    momentum_path = tmp_path / "momentum.sqlite3"
    monkeypatch.setenv("INTRADAY_MOMENTUM_BOOK_PATH", str(momentum_path))
    momentum = intraday_momentum_book.Store(momentum_path, seed=None)
    momentum.add_check("2026-11-23", 840, "done")
    momentum.add_check("2026-11-23", 900, "missed", note="no quote")

    night = desk.get("/copilot/desk/overnight").json()
    day = desk.get("/copilot/desk/momentum").json()
    assert night["coverage"] == {"missing": 1, "latest_missing_day": "2026-11-24", "unknown_days": 1}
    assert day["coverage"] == {"missing": 6, "latest_missing_day": "2026-11-24", "unknown_days": 1}
    assert night["totals"]["missed"] == day["totals"]["missed_checks"] == 1
    assert night["totals"]["closed"] == 0
    assert [row["day"] for row in day["days"]] == ["2026-11-23"]
    assert len(nights.nights()) == 1 and len(momentum.checks()) == 2

    # Neither an open window nor a check still inside its grace period is counted.
    monkeypatch.setattr(copilot_desk.today, "_now", lambda: datetime(2026, 11, 24, 10, 4, tzinfo=ET).timestamp())
    assert desk.get("/copilot/desk/overnight").json()["coverage"]["missing"] == 0
    assert desk.get("/copilot/desk/momentum").json()["coverage"]["missing"] == 0
    monkeypatch.setattr(copilot_desk.today, "_now", lambda: datetime(2026, 11, 24, 10, 5, tzinfo=ET).timestamp())
    assert desk.get("/copilot/desk/momentum").json()["coverage"]["missing"] == 1
