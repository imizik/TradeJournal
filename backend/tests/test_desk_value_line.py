"""The desk's line of account value through the day (app/engine/desk_value_line.py): readings stored once from the feed's
snapshots, the line per account and for all of them, change and percent, high and low, and breaks that are never
bridged or read as zero. Every figure is invented; nothing here reaches a broker."""

from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import desk_value_line as vl
from app.engine.chart_math import ET
from app.models import DeskAccountValue

ROTH, MCP = "••8267", "••7884"


def at(day: int, hour: int, minute: int = 0, second: int = 0, month: int = 10) -> int:
    return int(datetime(2026, month, day, hour, minute, second, tzinfo=ET).timestamp())


def refresh(moment: float) -> int:
    """The feed's cadence: a minute in market hours, fifteen otherwise (as the live feed's ``ttl``)."""
    t = datetime.fromtimestamp(moment, ET)
    minutes = t.hour * 60 + t.minute
    return 60 if t.weekday() < 5 and 9 * 60 + 25 <= minutes <= 16 * 60 + 15 else 900


def snapshot(moment: int, roth: float | None = 10_000.0, mcp: float | None = 500.0) -> dict:
    accounts = [{"label": "Roth IRA", "masked": ROTH, "last4": "8267", "total_value": roth}]
    if mcp is not ...:
        accounts.append({"label": "MCP", "masked": MCP, "last4": "7884", "total_value": mcp})
    return {"at": moment + 0.4, "accounts": accounts}


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def draw(engine, now, **kw):
    with Session(engine) as db:
        return vl.line(db, now, refresh, **kw)


def test_a_snapshot_is_stored_once_with_masked_accounts_only(engine):
    assert vl.record(engine, snapshot(at(21, 9, 31))) == 2
    assert vl.record(engine, snapshot(at(21, 9, 31))) == 0  # the next desk read of the same snapshot
    with Session(engine) as db:
        rows = db.exec(select(DeskAccountValue)).all()
    assert [(r.day, r.at, r.masked, r.label, r.total_value) for r in rows] == [
        ("2026-10-21", at(21, 9, 31), ROTH, "Roth IRA", 10_000.0), ("2026-10-21", at(21, 9, 31), MCP, "MCP", 500.0)]


def test_a_weekend_reading_is_not_stored_and_a_week_old_day_is_dropped(engine):
    assert vl.record(engine, snapshot(at(24, 12))) == 0  # Saturday
    vl.record(engine, snapshot(at(13, 10)))
    vl.record(engine, snapshot(at(14, 10)))
    vl.record(engine, snapshot(at(21, 10)))
    with Session(engine) as db:
        assert sorted({r.day for r in db.exec(select(DeskAccountValue)).all()}) == ["2026-10-14", "2026-10-21"]


def test_before_the_first_reading_there_is_no_line(engine):
    vl.record(engine, snapshot(at(20, 15)))  # yesterday's readings are not today's line
    line = draw(engine, at(21, 8))
    assert line["day"] == "2026-10-21" and line["series"] == {} and line["fills"] == []


def test_each_account_and_all_of_them_with_change_percent_high_and_low(engine):
    for minute, roth, mcp in ((31, 10_000.0, 500.0), (32, 10_250.5, 480.0), (33, 9_900.25, 510.0), (34, 10_100.0, 490.0)):
        vl.record(engine, snapshot(at(21, 9, minute), roth, mcp))
    line = draw(engine, at(21, 9, 35), open_at=at(21, 9, 30), close_at=at(21, 16))
    assert (line["open"], line["close"]) == (at(21, 9, 30), at(21, 16))
    roth, mcp, total = line["series"][ROTH], line["series"][MCP], line["series"]["all"]
    assert roth["label"] == "Roth IRA" and total["label"] == "All accounts"
    assert [v for _t, v in total["segments"][0]] == [10_500.0, 10_730.5, 10_410.25, 10_590.0]
    # Change since the first reading: a gain, a loss, in dollars and in percent of the first value.
    assert (roth["change"], roth["change_pct"]) == (100.0, 1.0)
    assert (mcp["change"], mcp["change_pct"]) == (-10.0, -2.0)
    assert (total["change"], total["change_pct"]) == (90.0, 0.86)
    assert total["first"] == {"at": at(21, 9, 31), "value": 10_500.0} and total["last"] == {"at": at(21, 9, 34), "value": 10_590.0}
    assert total["high"] == {"at": at(21, 9, 32), "value": 10_730.5} and total["low"] == {"at": at(21, 9, 33), "value": 10_410.25}
    assert mcp["high"]["value"] == 510.0 and mcp["low"]["value"] == 480.0
    assert total["breaks"] == [] and total["quiet_since"] is None


def test_a_stretch_without_readings_is_a_break_never_a_straight_line(engine):
    for moment in (at(21, 10), at(21, 10, 1), at(21, 10, 2), at(21, 10, 31), at(21, 10, 32)):
        vl.record(engine, snapshot(moment))
    total = draw(engine, at(21, 10, 33))["series"]["all"]
    assert [[t for t, _v in s] for s in total["segments"]] == [[at(21, 10), at(21, 10, 1), at(21, 10, 2)], [at(21, 10, 31), at(21, 10, 32)]]
    assert total["breaks"] == [{"from": at(21, 10, 2), "to": at(21, 10, 31)}]
    # Two or three minutes apart in market hours is still one line (a desk reads each minute; a beat can skip).
    vl.record(engine, snapshot(at(21, 10, 35)))
    assert len(draw(engine, at(21, 10, 36))["series"]["all"]["segments"]) == 2


def test_a_reading_without_a_value_breaks_that_account_and_the_total_never_zero(engine):
    vl.record(engine, snapshot(at(21, 11), 10_000.0, 500.0))
    vl.record(engine, snapshot(at(21, 11, 1), 10_010.0, None))
    vl.record(engine, snapshot(at(21, 11, 2), 10_020.0, 505.0))
    series = draw(engine, at(21, 11, 3))["series"]
    assert len(series[ROTH]["segments"]) == 1  # the other account's line is whole
    assert [[v for _t, v in s] for s in series[MCP]["segments"]] == [[500.0], [505.0]]
    assert [[v for _t, v in s] for s in series["all"]["segments"]] == [[10_500.0], [10_525.0]]
    assert series["all"]["breaks"] == [{"from": at(21, 11), "to": at(21, 11, 2)}]
    assert 0 not in [v for s in series["all"]["segments"] for _t, v in s]


def test_the_total_is_the_accounts_the_latest_reading_holds(engine):
    vl.record(engine, {"at": at(21, 12), "accounts": [{"label": "Roth IRA", "masked": ROTH, "total_value": 10_000.0}]})
    vl.record(engine, snapshot(at(21, 12, 1), 10_000.0, 500.0))
    total = draw(engine, at(21, 12, 2))["series"]["all"]
    # The first reading lacks MCP: it is not a smaller total, it is no total.
    assert [[v for _t, v in s] for s in total["segments"]] == [[10_500.0]] and total["change"] == 0.0


def test_premarket_quarter_hours_are_one_line_and_an_old_last_reading_says_so(engine):
    for moment in (at(21, 8, 45), at(21, 9), at(21, 9, 15), at(21, 9, 26), at(21, 9, 27)):
        vl.record(engine, snapshot(moment))
    total = draw(engine, at(21, 9, 28))["series"]["all"]
    assert len(total["segments"]) == 1 and total["quiet_since"] is None
    assert draw(engine, at(21, 9, 40))["series"]["all"]["quiet_since"] == at(21, 9, 27)


def test_a_weekend_shows_fridays_line_and_change_needs_a_positive_start(engine):
    vl.record(engine, snapshot(at(23, 15), 0.0, ...))
    vl.record(engine, snapshot(at(23, 15, 1), 25.0, ...))
    line = draw(engine, at(24, 12))  # Saturday
    roth = line["series"][ROTH]
    assert line["day"] == "2026-10-23" and roth["change"] == 25.0 and roth["change_pct"] is None
    assert set(line["series"]) == {ROTH, "all"}


def test_fills_are_drawn_in_time_order(engine):
    vl.record(engine, snapshot(at(21, 13)))
    fills = [{"at": at(21, 13, 5), "masked": MCP, "symbol": "APLD", "text": "Sell to close 1 APLD 11/27/26 30P"},
             {"at": at(21, 13, 1), "masked": ROTH, "symbol": "NBIS", "text": "Buy to open 2 NBIS 10/23/26 100C"}]
    assert [f["symbol"] for f in draw(engine, at(21, 13, 6), fills=fills)["fills"]] == ["NBIS", "APLD"]
