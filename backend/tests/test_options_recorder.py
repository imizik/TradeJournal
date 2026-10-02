"""Options positioning recorder (Charts C4.3).

No network. A fake chain client and calendar stand in for Tradier, except in
the budget test, which drives the real adapter through a replaced `httpx.get`
and a fake clock. The database is an in-memory SQLite built from the models.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.engine.options_chain as options_module
from app.engine.chart_math import ET
from app.engine.occ import occ_symbol
from app.engine.options_chain import OptionsChainError, TradierOptions
from app.engine.options_models import OptionChain, OptionContract
from app.engine.options_recorder import RecorderError, record, scope
from app.models import Account, ChartSettingsRecord, JobRun, OptionChainSnapshot, OptionSnapshotDay, Trade
from app.routers import sync

THURSDAY = date(2026, 10, 1)
AFTER_CLOSE = datetime(2026, 10, 1, 16, 30, tzinfo=ET)
CAPTURED = datetime(2026, 10, 1, 20, 30, tzinfo=timezone.utc)
# Listed for every symbol: four fall within 45 days (today and +45 included).
LISTED = [THURSDAY + timedelta(days=n) for n in (0, 7, 44, 45, 46, 90)]
WITHIN = LISTED[:4]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


class Calendar:
    def __init__(self, closed=(), early=(), unknown=()):
        self.closed, self.early, self.unknown = set(closed), set(early), set(unknown)
        self.asked: list[date] = []

    def hours(self, day):
        self.asked.append(day)
        if day in self.unknown:
            return None
        if day.weekday() >= 5 or day in self.closed:
            return {"date": day.isoformat(), "status": "closed", "open": None, "close": None}
        return {"date": day.isoformat(), "status": "open", "open": 570, "close": 780 if day in self.early else 960}


class Crash(Exception):
    """Stands in for the worker process dying mid-run."""


def _contract(underlying, root, expiration, side, strike, oi, volume, traded=None):
    return OptionContract(
        symbol=occ_symbol(root, expiration, side, strike), underlying=underlying, root=root, expiration=expiration,
        option_type=side, strike=strike, multiplier=100, bid=1.0, ask=1.1, last=1.05, bid_size=1, ask_size=1,
        volume=volume, open_interest=oi, bid_time=None, ask_time=None, trade_time=traded, iv=0.2, iv_smoothed=0.2,
        delta=0.5, gamma=0.01, theta=-0.1, vega=0.1, greeks_updated_at=None,
    )


def _chain(symbol, expiration, contracts=None):
    contracts = contracts if contracts is not None else (
        _contract(symbol, symbol, expiration, "call", 100.0, 10, 5),
        _contract(symbol, symbol, expiration, "put", 100.0, 7, None),
    )
    return OptionChain(symbol, expiration, "tradier", CAPTURED, tuple(contracts))


class Client:
    """Lists LISTED for every symbol unless told otherwise; records every call."""

    def __init__(self, listed=None, chains=None, fail=None, crash_after=None, on_chain=None):
        self.listed = listed or {}
        self.chains = chains or {}
        self.fail = fail or {}
        self.crash_after = crash_after
        self.on_chain = on_chain
        self.calls: list[tuple] = []

    def expirations(self, symbol, wait=False):
        self.calls.append(("expirations", symbol, wait))
        if (symbol, None) in self.fail:
            raise self.fail[(symbol, None)]
        return self.listed.get(symbol, LISTED)

    def chain(self, symbol, expiration, wait=False):
        self.calls.append(("chain", symbol, expiration, wait))
        if self.crash_after is not None and len(self.chain_calls()) > self.crash_after:
            raise Crash()
        if self.on_chain:
            self.on_chain()
        if (symbol, expiration) in self.fail:
            raise self.fail[(symbol, expiration)]
        return self.chains.get((symbol, expiration)) or _chain(symbol, expiration)

    def chain_calls(self):
        return [(c[1], c[2]) for c in self.calls if c[0] == "chain"]


def _run(db, client, *, at=AFTER_CLOSE, calendar=None, clock=None):
    return record(db, client=client, calendar=calendar or Calendar(), clock=clock or (lambda: at))


def _snapshots(db):
    return db.exec(select(OptionChainSnapshot).order_by(OptionChainSnapshot.underlying, OptionChainSnapshot.expiration)).all()


def _days(db):
    return {(d.session_date, d.underlying): d for d in db.exec(select(OptionSnapshotDay)).all()}


# --- a normal session --------------------------------------------------------


def test_each_underlying_records_every_expiration_within_45_days(db):
    client = Client()

    stored, message = _run(db, client)

    assert stored == 12
    assert [c[1] for c in client.calls if c[0] == "expirations"] == ["SPY", "QQQ", "SPX"]
    assert client.chain_calls() == [(s, d) for s in ("SPY", "QQQ", "SPX") for d in WITHIN]
    assert all(call[-1] is True for call in client.calls)  # every read waits for the options budget
    assert {(s.underlying, s.expiration) for s in _snapshots(db)} == {(s, d) for s in ("SPY", "QQQ", "SPX") for d in WITHIN}
    assert all(s.session_date == THURSDAY and s.provider == "tradier" for s in _snapshots(db))
    days = _days(db)
    assert {key: (d.status, d.expirations, d.recorded) for key, d in days.items()} == {
        (THURSDAY, s): ("recorded", 4, 4) for s in ("SPY", "QQQ", "SPX")
    }
    assert message == "2026-10-01: recorded 12 expiration(s); 3 of 3 underlyings complete."


def test_a_snapshot_packs_open_interest_and_volume_per_contract_with_its_root(db):
    expiration = THURSDAY + timedelta(days=15)
    traded = datetime(2026, 10, 1, 19, 59, 30, tzinfo=timezone.utc)
    spx = _chain("SPX", expiration, [
        _contract("SPX", "SPXW", expiration, "call", 7680.0, 232, 3, traded),
        _contract("SPX", "SPX", expiration, "put", 7680.0, 574, 0),
        _contract("SPX", "SPX", expiration, "call", 7680.0, 528, None),
        _contract("SPX", "SPXW", expiration, "put", 7675.0, None, 12, traded - timedelta(hours=3)),
    ])
    client = Client(listed={"SPY": [], "QQQ": [], "SPX": [expiration]}, chains={("SPX", expiration): spx})

    _run(db, client)

    [snapshot] = _snapshots(db)
    assert (snapshot.underlying, snapshot.expiration, snapshot.contracts) == ("SPX", expiration, 4)
    assert snapshot.captured_at == datetime(2026, 10, 1, 20, 30)  # naive UTC, like every other column
    assert snapshot.last_trade_at == datetime(2026, 10, 1, 19, 59, 30)
    assert json.loads(snapshot.data_json) == {
        "columns": ["root", "type", "strike", "open_interest", "volume"],
        "rows": [
            ["SPX", "C", 7680.0, 528, None],
            ["SPX", "P", 7680.0, 574, 0],
            ["SPXW", "P", 7675.0, None, 12],
            ["SPXW", "C", 7680.0, 232, 3],
        ],
    }
    # An underlying with nothing listed inside the horizon is complete, and says why.
    assert _days(db)[(THURSDAY, "SPY")].note == "No listed expirations within 45 days."


def _account(db, broker=None, last4="1111"):
    account = Account(name=f"acct {last4}", type="individual", last4=last4, broker=broker)
    db.add(account)
    db.commit()
    return account


def _trade(db, account, ticker, kind="option", status="open", expiration=THURSDAY + timedelta(days=3)):
    db.add(Trade(
        account_id=account.id, ticker=ticker, instrument_type=kind, contracts=1, avg_entry_premium=1,
        total_premium_paid=100, opened_at=datetime(2026, 9, 30, 10), status=status,
        option_type="call" if kind == "option" else None, strike=100 if kind == "option" else None,
        expiration=expiration if kind == "option" else None,
    ))


def test_scope_is_the_indexes_open_positions_then_ten_watchlist_names(db):
    robinhood, webull = _account(db), _account(db, broker="webull", last4="2222")
    _trade(db, robinhood, "NVDA")
    _trade(db, robinhood, "AMD", kind="stock")
    _trade(db, robinhood, "SPXW")  # an index option root: its underlying is SPX
    _trade(db, robinhood, "TSLA", expiration=THURSDAY - timedelta(days=1))  # expired, not yet closed
    _trade(db, robinhood, "META", status="closed")
    _trade(db, webull, "MU")  # Webull is dormant
    watchlist = ["SPY", "qqq", "MRVL", "NVDA", "AAPL", "MSFT", "GOOG", "CVNA", "COIN", "LLY", "SNDK", "AVGO"]
    db.add(ChartSettingsRecord(name="default", data_json=json.dumps({"watchlist": watchlist})))
    db.commit()

    assert scope(db, THURSDAY) == [
        "SPY", "QQQ", "SPX", "NVDA", "AMD",
        "MRVL", "AAPL", "MSFT", "GOOG", "CVNA", "COIN", "LLY",  # the first ten entries, minus repeats
    ]


def test_scope_survives_missing_or_damaged_settings(db):
    assert scope(db, THURSDAY) == ["SPY", "QQQ", "SPX"]
    db.add(ChartSettingsRecord(name="default", data_json="not json"))
    db.commit()
    assert scope(db, THURSDAY) == ["SPY", "QQQ", "SPX"]


# --- when nothing is recorded -----------------------------------------------


@pytest.mark.parametrize("at, calendar, says", [
    pytest.param(datetime(2026, 10, 3, 16, 30, tzinfo=ET), Calendar(), "Market closed on 2026-10-03", id="Saturday"),
    pytest.param(AFTER_CLOSE, Calendar(closed=[THURSDAY]), "Market closed on 2026-10-01", id="holiday"),
    pytest.param(datetime(2026, 10, 1, 11, 0, tzinfo=ET), Calendar(), "from 16:15 to 20:00", id="during the session"),
    pytest.param(datetime(2026, 10, 1, 16, 14, tzinfo=ET), Calendar(), "from 16:15 to 20:00", id="before the settle"),
    pytest.param(datetime(2026, 10, 1, 20, 0, tzinfo=ET), Calendar(), "After 20:00 New York SPX volume", id="after 20:00"),
])
def test_outside_a_sessions_capture_window_nothing_is_requested_or_stored(db, at, calendar, says):
    client = Client()

    stored, message = _run(db, client, at=at, calendar=calendar)

    assert (stored, client.calls, _snapshots(db), _days(db)) == (0, [], [], {})
    assert says in message


def test_an_early_close_opens_the_window_15_minutes_after_it(db):
    client = Client(listed={"SPY": [THURSDAY], "QQQ": [], "SPX": []})

    stored, _ = _run(db, client, at=datetime(2026, 10, 1, 13, 15, tzinfo=ET), calendar=Calendar(early=[THURSDAY]))

    assert stored == 1


def test_an_unavailable_calendar_records_nothing_rather_than_guess(db):
    client = Client()

    with pytest.raises(RecorderError, match="market calendar is unavailable"):
        _run(db, client, calendar=Calendar(unknown=[THURSDAY]))

    assert client.calls == [] and _snapshots(db) == []


# --- restarts, failures and the window --------------------------------------


def test_a_restarted_run_fetches_only_what_the_interrupted_one_missed(db):
    with pytest.raises(Crash):
        _run(db, Client(crash_after=2))
    assert [(s.underlying, s.expiration) for s in _snapshots(db)] == [("SPY", WITHIN[0]), ("SPY", WITHIN[1])]
    assert {d.status for d in _days(db).values()} == {"partial"}  # every underlying says it is unfinished

    resumed = Client()
    stored, _ = _run(db, resumed)

    assert stored == 10
    assert resumed.chain_calls() == [("SPY", d) for d in WITHIN[2:]] + [(s, d) for s in ("QQQ", "SPX") for d in WITHIN]
    assert len(_snapshots(db)) == 12
    assert {d.status for d in _days(db).values()} == {"recorded"}

    again = Client()
    assert _run(db, again)[0] == 0
    assert again.calls == []  # a complete session costs no request


def test_a_snapshot_another_run_stored_first_is_kept_not_replaced(db):
    theirs = '{"columns":[],"rows":[]}'

    def another_run_stores_it_first():
        db.add(OptionChainSnapshot(session_date=THURSDAY, underlying="SPY", expiration=THURSDAY, provider="tradier",
                                   captured_at=datetime(2026, 10, 1, 20, 21), contracts=0, data_json=theirs))
        db.commit()

    client = Client(listed={"SPY": [THURSDAY], "QQQ": [], "SPX": []}, on_chain=another_run_stores_it_first)
    stored, _ = _run(db, client)

    assert stored == 0
    assert [s.data_json for s in _snapshots(db)] == [theirs]
    assert _days(db)[(THURSDAY, "SPY")].status == "recorded"


def test_a_failed_expiration_leaves_the_session_partial_and_the_next_run_completes_it(db):
    broken = OptionsChainError("Tradier could not read options (502).")
    client = Client(fail={("QQQ", WITHIN[1]): broken})

    with pytest.raises(RecorderError) as failed:
        _run(db, client)

    assert str(failed.value).startswith("Options snapshot incomplete for 2026-10-01: QQQ 2026-10-08 (Tradier could not read options (502).)")
    assert len(_snapshots(db)) == 11
    qqq = _days(db)[(THURSDAY, "QQQ")]
    assert (qqq.status, qqq.expirations, qqq.recorded) == ("partial", 4, 3)
    assert "2026-10-08" in qqq.note

    retry = Client()
    stored, _ = _run(db, retry)
    assert retry.chain_calls() == [("QQQ", WITHIN[1])]
    assert stored == 1 and _days(db)[(THURSDAY, "QQQ")].status == "recorded"


def test_an_unlisted_underlying_is_partial_and_the_others_still_record(db):
    client = Client(fail={("QQQ", None): OptionsChainError("Tradier could not read options (500).")})

    with pytest.raises(RecorderError, match="QQQ expirations"):
        _run(db, client)

    assert {s.underlying for s in _snapshots(db)} == {"SPY", "SPX"}
    assert _days(db)[(THURSDAY, "QQQ")].status == "partial"


def test_a_refused_token_stops_the_run(db):
    client = Client(fail={("SPY", WITHIN[1]): OptionsChainError("Tradier refused option data.", "access_denied")})

    with pytest.raises(RecorderError, match="refused option data"):
        _run(db, client)

    assert client.chain_calls() == [("SPY", WITHIN[0]), ("SPY", WITHIN[1])]


def test_the_run_stops_when_the_capture_window_closes(db):
    moment = {"now": datetime(2026, 10, 1, 19, 58, tzinfo=ET)}

    def tick():
        moment["now"] += timedelta(minutes=1)

    client = Client(on_chain=tick)
    with pytest.raises(RecorderError, match="capture window closed"):
        _run(db, client, clock=lambda: moment["now"])

    assert client.chain_calls() == [("SPY", WITHIN[0]), ("SPY", WITHIN[1])]
    assert all(s.session_date == THURSDAY for s in _snapshots(db))


# --- missed sessions ----------------------------------------------------------


def _held(db, day, *symbols, status="recorded"):
    for symbol in symbols:
        db.add(OptionSnapshotDay(session_date=day, underlying=symbol, status=status))
    db.commit()


def test_a_missed_session_is_marked_unavailable_and_never_backfilled(db):
    monday, tuesday, wednesday = date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)
    _held(db, monday, "SPY", "QQQ")
    calendar = Calendar(closed=[wednesday])  # a holiday is not a missed session

    stored, message = _run(db, Client(), calendar=calendar)

    days = _days(db)
    assert {u for (d, u) in days if d == tuesday} == {"QQQ", "SPY"}  # what Monday held
    assert {days[(tuesday, u)].status for u in ("QQQ", "SPY")} == {"unavailable"}
    assert "cannot be backfilled" in days[(tuesday, "SPY")].note
    assert not any(d == wednesday for d, _ in days)
    assert {s.session_date for s in _snapshots(db)} == {THURSDAY}  # nothing captured today is filed under Tuesday
    assert message.startswith("Marked 2 missed underlying-session(s) unavailable.")


def test_missed_sessions_are_marked_even_by_a_run_that_records_nothing(db):
    _held(db, date(2026, 9, 28), "SPY")

    _run(db, Client(), at=datetime(2026, 10, 1, 9, 0, tzinfo=ET))

    assert {(d, u, x.status) for (d, u), x in _days(db).items()} == {
        (date(2026, 9, 28), "SPY", "recorded"),
        (date(2026, 9, 29), "SPY", "unavailable"),
        (date(2026, 9, 30), "SPY", "unavailable"),
    }


def test_a_session_the_calendar_cannot_describe_is_left_for_a_later_run(db):
    tuesday = date(2026, 9, 29)
    _held(db, date(2026, 9, 28), "SPY")

    _run(db, Client(), calendar=Calendar(unknown=[tuesday]), at=datetime(2026, 10, 1, 9, 0, tzinfo=ET))
    assert (tuesday, "SPY") not in _days(db)

    _run(db, Client(), at=datetime(2026, 10, 1, 9, 5, tzinfo=ET))
    assert _days(db)[(tuesday, "SPY")].status == "unavailable"


def test_nothing_is_marked_before_the_recorder_first_ran(db):
    _run(db, Client(), at=datetime(2026, 10, 1, 9, 0, tzinfo=ET))

    assert _days(db) == {}


# --- the real adapter's budget -----------------------------------------------


def test_a_large_run_stays_inside_the_options_budget(db, monkeypatch):
    """63 requests through the real adapter: never more than 30 in any minute."""
    start = datetime(2026, 10, 1, 16, 20, tzinfo=ET).timestamp()
    now = {"t": start}
    sent: list[float] = []
    listed = [THURSDAY + timedelta(days=n) for n in range(20)]

    def fake_get(url, params=None, headers=None, timeout=None):
        sent.append(now["t"])
        now["t"] += 0.2  # each request takes a moment
        payload = ({"expirations": {"date": [d.isoformat() for d in listed]}} if url.endswith("/expirations")
                   else {"options": None})

        class Response:
            status_code = 200

            def json(self):
                return payload
        return Response()

    def sleep(seconds):
        now["t"] += seconds

    monkeypatch.setattr(options_module.tradier, "TRADIER_API_KEY", "test-token")
    monkeypatch.setattr(options_module.httpx, "get", fake_get)
    client = TradierOptions(clock=lambda: now["t"], sleep=sleep)

    stored, _ = record(db, client=client, calendar=Calendar(), clock=lambda: datetime.fromtimestamp(now["t"], ET))

    assert stored == 60 and len(sent) == 63
    assert max(sum(1 for t in sent if first <= t < first + 60) for first in sent) == 30
    assert now["t"] - start > 120  # it waited for the budget rather than exceeding it


# --- the job ----------------------------------------------------------------------


@pytest.fixture
def job_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(sync, "engine", engine)
    yield engine
    engine.dispose()


def _job(engine):
    with Session(engine) as session:
        job = JobRun(job_type=sync.JOB_OPTIONS_SNAPSHOT, status="running")
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def test_the_sync_job_runs_the_recorder_and_keeps_its_message(job_engine, monkeypatch):
    job = _job(job_engine)
    seen = []

    def fake_record(session, progress):
        progress(0, 3, "SPY: 1 of 3 underlyings")
        with Session(job_engine) as other:
            seen.append(other.get(JobRun, job.id).current)
        return 12, "2026-10-01: recorded 12 expiration(s); 3 of 3 underlyings complete."

    monkeypatch.setattr(sync, "record_option_snapshots", fake_record)
    sync.execute_sync_job(job)

    with Session(job_engine) as session:
        done = session.get(JobRun, job.id)
    assert seen == ["SPY: 1 of 3 underlyings"]
    assert (done.status, done.enriched, done.current) == (
        "succeeded", 12, "2026-10-01: recorded 12 expiration(s); 3 of 3 underlyings complete.")


def test_an_incomplete_snapshot_fails_the_job_with_the_reason_first(job_engine, monkeypatch):
    def fake_record(session, progress):
        raise RecorderError("Options snapshot incomplete for 2026-10-01: QQQ 2026-10-08 (502).")

    monkeypatch.setattr(sync, "record_option_snapshots", fake_record)
    job = _job(job_engine)

    sync.execute_sync_job(job)

    with Session(job_engine) as session:
        failed = session.get(JobRun, job.id)
    assert failed.status == "failed"
    assert failed.error.startswith("Options snapshot incomplete for 2026-10-01")


def test_the_sync_center_lists_and_queues_the_snapshot(job_engine):
    assert any(config["job_type"] == "options_snapshot" for config in sync.JOB_CONFIG)

    with Session(job_engine) as session:
        queued = asyncio.run(sync.run_sync_job("options_snapshot", session=session))
        job = session.get(JobRun, uuid.UUID(queued["run_id"]))

    assert (job.job_type, job.status) == ("options_snapshot", "queued")
