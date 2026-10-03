"""The morning relative-volume history job (Charts C2.4).

No network: a fake history store and calendar stand in for Alpaca and Tradier.
The database is an in-memory SQLite built from the models.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import json
import time
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.engine.rvol_history as job_module
from app.engine.chart_history import HistoryError
from app.engine.chart_math import ET
from app.engine.rvol_history import RvolHistoryError, scope, store
from app.models import ChartSettingsRecord, JobRun
from app.routers import sync

MONDAY = datetime(2026, 9, 28, 6, 0, tzinfo=ET)
LABOR_DAY = date(2026, 9, 7)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def watch(db: Session, names) -> None:
    db.add(ChartSettingsRecord(name="default", data_json=json.dumps({"watchlist": names}), revision=1, updated_at=datetime(2026, 9, 1)))
    db.commit()


class Calendar:
    def __init__(self, unknown=()):
        self.unknown = set(unknown)

    def hours(self, day):
        if day in self.unknown:
            return None
        if day.weekday() >= 5 or day == LABOR_DAY:
            return {"status": "closed", "open": None, "close": None}
        return {"status": "open", "open": 570, "close": 960}


class History:
    """Stores sessions in memory. ``errors`` maps (symbol, day) to the HistoryErrors its next fetches raise."""

    def __init__(self, stored=(), errors=None):
        self.kept = set(stored)
        self.errors = {key: list(value) for key, value in (errors or {}).items()}
        self.fetched: list[tuple[str, date]] = []

    def stored(self, symbol, day):
        return [] if (symbol, day) in self.kept else None

    def session(self, symbol, day):
        queued = self.errors.get((symbol, day))
        if queued:
            raise queued.pop(0)
        self.fetched.append((symbol, day))
        self.kept.add((symbol, day))
        return []


WINDOW = [d for d in (date(2026, 8, 28) + timedelta(days=n) for n in range(31)) if d.weekday() < 5 and d != LABOR_DAY][:20]


def run(db, history, **kwargs):
    return store(db, history=history, calendar=kwargs.pop("calendar", Calendar()), clock=lambda: MONDAY, **kwargs)


def test_scope_is_the_shared_watchlist_each_name_once(db):
    assert scope(db) == []
    watch(db, ["spy", "QQQ", "SPY", "BRK.B", "../etc", 7, "", "NVDA"])
    assert scope(db) == ["SPY", "QQQ", "BRK.B", "NVDA"]


def test_it_stores_the_twenty_sessions_before_today_and_a_rerun_costs_nothing(db):
    watch(db, ["SPY", "NVDA"])
    assert WINDOW[0] == date(2026, 8, 28) and WINDOW[-1] == date(2026, 9, 25) and len(WINDOW) == 20
    history = History(stored=[("SPY", day) for day in WINDOW[:19]])
    seen = []
    fetched, message = run(db, history, progress=lambda done, total, text: seen.append((done, total, text)))
    assert history.fetched == [("SPY", WINDOW[-1])] + [("NVDA", day) for day in reversed(WINDOW)]  # newest first
    assert fetched == 21 and message == "2026-09-28: stored 21 session(s); 2 of 2 watchlist names have the 20 sessions before today."
    assert seen == [(0, 2, "SPY: 1 of 2 watchlist names"), (1, 2, "NVDA: 2 of 2 watchlist names")]
    history.fetched.clear()
    assert run(db, history)[0] == 0 and history.fetched == []


def test_on_a_weekend_it_stores_the_next_sessions_window(db):
    watch(db, ["SPY"])
    history = History()
    store(db, history=history, calendar=Calendar(), clock=lambda: datetime(2026, 9, 26, 6, 0, tzinfo=ET))
    assert [day for _, day in history.fetched] == WINDOW[::-1]


def test_it_waits_out_the_alpaca_budget_instead_of_exceeding_it(db, monkeypatch):
    watch(db, ["SPY"])
    monkeypatch.setattr(job_module, "time", SimpleNamespace(time=lambda: 1_000.0, monotonic=time.monotonic))
    history = History(stored=[("SPY", day) for day in WINDOW[:-1]], errors={("SPY", WINDOW[-1]): [
        HistoryError("Alpaca chart history is cooling down.", "rate_limited", 1_030), HistoryError("History is still loading.", "pending", 1_000)]})
    sleeps = []
    assert run(db, history, sleep=sleeps.append)[0] == 1
    assert sleeps == [30.0, 0.5] and history.fetched == [("SPY", WINDOW[-1])]


def test_refused_credentials_stop_the_run_and_keep_what_it_stored(db):
    watch(db, ["SPY", "NVDA"])
    history = History(errors={("NVDA", WINDOW[-1]): [HistoryError("Alpaca refused historical SIP access.", "access_denied")]})
    with pytest.raises(RvolHistoryError, match="refused historical SIP access"):
        run(db, history)
    assert len(history.fetched) == 20 and {symbol for symbol, _ in history.fetched} == {"SPY"}


def test_a_session_that_fails_is_named_after_the_others_are_stored(db):
    watch(db, ["SPY", "NVDA", "AMD"])
    history = History(errors={("SPY", WINDOW[3]): [HistoryError("Alpaca returned malformed history data.", "malformed")]})
    with pytest.raises(RvolHistoryError) as failed:
        run(db, history)
    assert str(failed.value).startswith("Relative volume history incomplete: SPY 2026-09-02 (Alpaca returned malformed history data.).")
    assert "stored 59 session(s); 2 of 3 watchlist names" in str(failed.value)
    assert ("SPY", WINDOW[3]) not in history.kept and len(history.kept) == 59


def test_a_name_alpaca_has_no_minutes_for_is_noted_and_never_fails_the_run(db):
    # An index (SPX) has none at all; a stock that listed on 2026-09-21 has none before it.
    watch(db, ["SPX", "NEW", "SPY"])
    listed = date(2026, 9, 21)
    errors = {("SPX", WINDOW[-1]): [HistoryError("Alpaca has no minute bars for SPX on 2026-09-25.", "no_data")]}
    errors.update({("NEW", day): [HistoryError(f"Alpaca has no minute bars for NEW on {day}.", "no_data")] for day in WINDOW if day < listed})
    history = History(errors=errors)
    fetched, message = run(db, history)
    # One request for the index; the new stock's five sessions, then one that shows nothing older trades.
    assert [s for s, _ in history.fetched].count("NEW") == 5 and "SPX" not in {s for s, _ in history.fetched}
    assert fetched == 25 and message == ("2026-09-28: stored 25 session(s); 1 of 3 watchlist names have the 20 sessions before today. "
                                         "Alpaca has no minutes for SPX on 2026-09-25 and earlier, NEW on 2026-09-18 and earlier "
                                         "(an index, or not listed yet), so RVol waits.")


def test_a_run_stops_after_its_time_and_the_next_one_continues(db, monkeypatch):
    watch(db, ["SPY", "NVDA"])
    clock = iter([0.0] + [1.0] * 25 + [700.0] * 100)
    monkeypatch.setattr(job_module, "time", SimpleNamespace(time=time.time, monotonic=lambda: next(clock)))
    history = History()
    fetched, message = run(db, history)
    assert fetched == 25 and message.endswith("1 of 2 watchlist names have the 20 sessions before today. 15 session(s) left for the next run.")
    monkeypatch.setattr(job_module, "time", SimpleNamespace(time=time.time, monotonic=lambda: 0.0))
    assert run(db, history)[0] == 15 and len(history.kept) == 40


def test_without_the_calendar_nothing_is_chosen_and_the_run_fails(db):
    watch(db, ["SPY"])
    history = History()
    with pytest.raises(RvolHistoryError, match="market calendar is unavailable"):
        run(db, history, calendar=Calendar(unknown={date(2026, 9, 14)}))
    assert history.fetched == []


@pytest.fixture
def job_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(sync, "engine", engine)
    yield engine
    engine.dispose()


def test_the_sync_job_runs_the_store_and_the_sync_center_queues_it(job_engine, monkeypatch):
    def fake_store(session, progress):
        progress(0, 2, "SPY: 1 of 2 watchlist names")
        return 21, "2026-09-28: stored 21 session(s); 2 of 2 watchlist names have the 20 sessions before today."

    monkeypatch.setattr(sync, "store_rvol_history", fake_store)
    with Session(job_engine) as session:
        job = JobRun(job_type=sync.JOB_RVOL_HISTORY, status="running")
        session.add(job)
        session.commit()
        session.refresh(job)
    sync.execute_sync_job(job)
    with Session(job_engine) as session:
        done = session.get(JobRun, job.id)
    assert (done.status, done.enriched) == ("succeeded", 21) and done.current.startswith("2026-09-28: stored 21")

    assert any(config["job_type"] == "rvol_history" and config["api_provider"] == "Alpaca" for config in sync.JOB_CONFIG)
    with Session(job_engine) as session:
        queued = asyncio.run(sync.run_sync_job("rvol_history", session=session))
        row = session.get(JobRun, uuid.UUID(queued["run_id"]))
    assert (row.job_type, row.status) == ("rvol_history", "queued")
