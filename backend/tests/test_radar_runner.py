"""Radar PR 1: the once-a-minute quote recorder and its startup gate."""
import asyncio
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.engine import radar_runner, tradier
from app.engine.chart_math import ET
from app.engine.radar_runner import RadarRunner
from app.engine.radar_store import RadarStore
from app.engine.tradier import TradierError, TradierQuote

OPEN = {"status": "open", "open": 570, "close": 960}
EARLY = {"status": "open", "open": 570, "close": 780}
CLOSED = {"status": "closed", "open": None, "close": None}


class Calendar:
    def __init__(self, hours):
        self.value = hours

    def hours(self, day):
        return self.value


def _at(hour, minute, day=20):
    return lambda: datetime(2026, 10, day, hour, minute, 5, tzinfo=ET).timestamp()


def _universe(count):
    return {"version": "radar-universe-test", "symbols": [{"symbol": f"S{i:03d}", "kind": "stock"} for i in range(count)],
            "groups": []}


class Quotes:
    def __init__(self, fail_on=None, missing=()):
        self.calls, self.fail_on, self.missing = [], fail_on, set(missing)

    def __call__(self, symbols):
        self.calls.append(list(symbols))
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise TradierError("Tradier rate limited /v1/markets/quotes")
        return {s: TradierQuote(symbol=s, last=10.0, bid=9.9, ask=10.1, volume=500, trade_date=1792500000000,
                                raw={"prevclose": "9.5", "open": "9.6", "high": "10.2", "low": "9.4"})
                for s in symbols if s not in self.missing}


def _runner(tmp_path, hours=OPEN, clock=_at(10, 0), count=120, quotes=None):
    quotes = quotes or Quotes()
    store = RadarStore(tmp_path / "radar.sqlite")
    return RadarRunner(store, Calendar(hours), universe=_universe(count), quotes=quotes, clock=clock), store, quotes


@pytest.mark.parametrize("hours,clock", [
    (OPEN, _at(9, 29)), (OPEN, _at(16, 0)), (CLOSED, _at(11, 0)),  # before the open, at the close, a holiday
    (EARLY, _at(13, 0)), (EARLY, _at(14, 30)),  # after an early close
    (None, _at(11, 0, day=24)),  # calendar unavailable on a Saturday
])
def test_no_pass_outside_regular_hours(tmp_path, hours, clock):
    runner, store, quotes = _runner(tmp_path, hours, clock)
    assert runner.run_once() is None
    assert quotes.calls == [] and store.passes() == []


def test_unavailable_calendar_in_clock_hours_records_a_skip(tmp_path):
    runner, store, quotes = _runner(tmp_path, None, _at(11, 0))
    runner.run_once()
    [row] = store.passes()
    assert quotes.calls == [] and row["status"] == "skipped" and row["skip_reason"] == "calendar_unavailable"


def test_pass_batches_by_fifty_and_records_quotes_and_unmatched(tmp_path):
    runner, store, quotes = _runner(tmp_path, EARLY, _at(12, 59), count=120, quotes=Quotes(missing={"S007", "S110"}))
    pass_id = runner.run_once()
    assert [len(c) for c in quotes.calls] == [50, 50, 20]
    [row] = store.passes()
    assert row["status"] == "ok" and row["requests_used"] == 3 and row["symbols_requested"] == 120
    assert row["symbols_returned"] == 118 and row["unmatched"] == ["S007", "S110"]
    assert row["universe_version"] == "radar-universe-test" and row["session_date"] == "2026-10-20"
    quote = store.quotes(pass_id)[0]
    assert (quote["last"], quote["prev_close"], quote["open"], quote["high"], quote["low"]) == (10.0, 9.5, 9.6, 10.2, 9.4)
    assert (quote["volume"], quote["bid"], quote["ask"], quote["trade_time_ms"]) == (500, 9.9, 10.1, 1792500000000)
    assert quote["retrieved_at"].startswith("2026-10-20T16:59:05")


def test_request_cap_limits_a_pass_to_six_requests(tmp_path):
    runner, store, quotes = _runner(tmp_path, count=320)
    runner.run_once()
    assert len(quotes.calls) == 6
    [row] = store.passes()
    assert row["status"] == "partial" and row["symbols_requested"] == 300 and "20 symbols not requested" in row["error"]


@pytest.mark.parametrize("fail_on,status,returned", [(1, "failed", 0), (2, "partial", 50)])
def test_rate_limit_ends_the_pass_without_retry(tmp_path, fail_on, status, returned):
    runner, store, quotes = _runner(tmp_path, count=120, quotes=Quotes(fail_on=fail_on))
    runner.run_once()
    assert len(quotes.calls) == fail_on  # nothing retried, later batches not sent
    [row] = store.passes()
    assert row["status"] == status and row["symbols_returned"] == returned and "rate limited" in row["error"]
    assert row["requests_used"] == fail_on


def test_default_quotes_make_one_attempt(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(tradier, "_post", lambda path, payload, attempts: calls.append(attempts) or {})
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    assert RadarRunner(RadarStore(tmp_path / "r.sqlite"), Calendar(OPEN)).quotes is tradier.get_quotes_once
    tradier.get_quotes_once(["SPY"])
    assert calls == [1]


def test_startup_is_off_unless_enabled_with_an_absolute_store_and_tradier(monkeypatch, tmp_path):
    from app import main
    for name in ("RADAR_ENABLED", "RADAR_STORE", "TJ_DOT_TRIAL_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    app_ = SimpleNamespace(state=SimpleNamespace())
    assert asyncio.run(main._maybe_start_radar(app_)) is None and app_.state.radar is None
    monkeypatch.setenv("RADAR_ENABLED", "true")
    assert radar_runner.runner_from_env() is None  # no store
    monkeypatch.setenv("RADAR_STORE", "radar.sqlite")
    assert radar_runner.runner_from_env() is None  # relative store
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    assert isinstance(radar_runner.runner_from_env(), RadarRunner)
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "")
    assert radar_runner.runner_from_env() is None  # Tradier unconfigured
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    monkeypatch.setenv("TJ_DOT_TRIAL_ENABLED", "true")
    assert asyncio.run(main._maybe_start_radar(app_)) is None and app_.state.radar is None


def test_bad_store_never_stops_the_api(monkeypatch, tmp_path):
    import sqlite3
    from app import main
    foreign = tmp_path / "foreign.sqlite"
    sqlite3.connect(foreign).execute("CREATE TABLE fills(id)").connection.commit()
    monkeypatch.delenv("TJ_DOT_TRIAL_ENABLED", raising=False)
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(foreign))
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    app_ = SimpleNamespace(state=SimpleNamespace())
    assert asyncio.run(main._maybe_start_radar(app_)) is None and app_.state.radar is None


def test_live_receipt_records_zero_events_and_detector_failure(tmp_path, monkeypatch):
    runner, store, _ = _runner(tmp_path)
    monkeypatch.setattr(runner, "detect", lambda *args: ([], []))
    first = runner.run_once()
    receipts, configs = store.detection_evidence()
    assert receipts[first]["origin"] == "live" and receipts[first]["status"] == "ok"
    assert receipts[first]["event_ids"] == [] and receipts[first]["hours"] == OPEN
    assert configs[receipts[first]["config_digest"]]["universe"] == runner.universe
    def fail(*args):
        raise RuntimeError("synthetic detector failure")
    monkeypatch.setattr(runner, "detect", fail)
    second = runner.run_once()
    receipts, _ = store.detection_evidence()
    assert store.passes()[-1]["status"] == "ok"
    assert receipts[second]["status"] == "failed"


# ------------------------------------------------------------------ the reversal rule and setup cards

def record_reversal(tmp_path, minutes, *, reversal=True, reversal_alerts=False, dip=None, setups=None, options=None,
                    paths=None, paper=None):
    """The recorder over the reversal fixture (AAA opens 3% below its close, then turns up), one pass a minute."""
    from app.engine import radar_reversal
    from tests import test_radar_dip as dipfix
    from tests.test_radar_reversal import reversal as reversal_path
    clock = dipfix.Clock()
    store = RadarStore(tmp_path / "radar.sqlite")
    runner = RadarRunner(store, dipfix.Calendar(), universe=dipfix.UNIVERSE,
                         quotes=dipfix.Quotes(clock, paths if paths is not None else {"AAA": reversal_path()}), clock=clock,
                         news=lambda *a, **k: [], alerts=dipfix.Alerts(), daily=lambda symbols, day: {}, dip=dip,
                         reversal=radar_reversal.V0 if reversal else None, reversal_alerts=reversal_alerts,
                         setups=setups, options=options)
    if paper is not None:
        runner.paper = paper
    for _ in range(minutes):
        runner.run_once()
        clock.now += 60
    return runner, store


@pytest.fixture
def db_engine():
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


class Paper:
    def __init__(self, fail=False):
        self.steps, self.fail = [], fail

    def step(self, session_date, close_at):
        self.steps.append((session_date, close_at))
        if self.fail:
            raise RuntimeError("paper exploded")


def setups(engine):
    from sqlmodel import Session, select
    from app.models import RadarSetup
    with Session(engine) as db:
        return db.exec(select(RadarSetup)).all()


def test_reversal_rule_writes_under_its_own_receipt_side_and_leaves_the_trial_alone(tmp_path):
    from app.engine import radar_reversal
    runner, store = record_reversal(tmp_path, 15)
    _, plain = record_reversal(tmp_path / "off", 15, reversal=False)
    [event] = [e for e in store.events("2030-01-15") if radar_reversal.is_reversal(e)]
    assert event["event_id"] == "rg0-2030-01-15-reversal-aaa-up-1" and runner.alerts.recorded == []  # record mode: no ping
    assert plain.events("2030-01-15") == []
    receipts, configs = store.detection_evidence()
    off_receipts, _ = plain.detection_evidence()
    for pass_id, receipt in receipts.items():
        trial = {k: v for k, v in receipt.items() if k not in ("reversal", "recorded_at")}
        assert trial == {k: v for k, v in off_receipts[pass_id].items() if k != "recorded_at"}
        assert "reversal" not in off_receipts[pass_id] and "dip" not in receipt
    assert configs[receipts[1]["reversal"]["config_digest"]]["rules"] == asdict(radar_reversal.V0)
    claimed = [i for r in receipts.values() for i in r["reversal"]["event_ids"]]
    assert claimed == [event["event_id"]] and all(event["event_id"] not in r["event_ids"] for r in receipts.values())


def test_reversal_alert_mode_hands_its_events_to_the_phone_beside_dip(tmp_path):
    from app.engine import radar_dip
    runner, store = record_reversal(tmp_path, 15, reversal_alerts=True, dip=radar_dip.V0)
    assert runner.alerts.recorded == ["rg0-2030-01-15-reversal-aaa-up-1"]
    receipts, _ = store.detection_evidence()
    assert {r["dip"]["status"] for r in receipts.values()} == {"ok"} and {r["reversal"]["status"] for r in receipts.values()} == {"ok"}


def test_a_failing_reversal_rule_never_touches_the_pass(tmp_path, monkeypatch):
    from app.engine import radar_reversal
    monkeypatch.setattr(radar_reversal, "detect", lambda *a, **k: 1 / 0)
    _, store = record_reversal(tmp_path, 12)
    receipts, _ = store.detection_evidence()
    assert {p["status"] for p in store.passes()} == {"ok"} and {r["status"] for r in receipts.values()} == {"ok"}
    assert {r["reversal"]["status"] for r in receipts.values() if r["reversal"]["status"] != "ok"} == {"failed"}


def test_cards_are_built_for_new_setup_events_in_record_mode_and_the_paper_book_steps(tmp_path, db_engine):
    from datetime import date
    from tests.test_radar_setup import GOOD, FakeOptions
    paper = Paper()
    options = FakeOptions(GOOD, expirations=[date(2030, 1, 18)])  # three days out
    runner, store = record_reversal(tmp_path, 12, setups=db_engine, options=options, paper=paper)
    [card] = setups(db_engine)
    assert (card.event_id, card.kind, card.symbol, card.direction) == ("rg0-2030-01-15-reversal-aaa-up-1", "gap_reversal", "AAA", "up")
    assert (card.entry, card.invalidation) == (98.8, 96.4) and card.contract_json is not None
    assert [c[0] for c in options.calls] == ["expirations", "chain"]  # one card: two option reads, no wait
    close = datetime(2030, 1, 15, 16, 0, tzinfo=ET).timestamp()
    assert paper.steps == [("2030-01-15", close)] * 12  # once a usable inside pass
    assert runner.alerts.recorded == []  # the card never makes a record-only rule ping


def test_at_most_three_cards_a_pass_and_a_failing_card_skips_only_itself(tmp_path, db_engine, monkeypatch):
    from app.engine import radar_setup
    runner, _ = record_reversal(tmp_path, 0, setups=db_engine, paper=Paper())
    built = []

    def build(db, event, *, now, options=None, record=None):
        built.append(event["event_id"])
        if event["event_id"] == "e1":
            raise RuntimeError("chain read blew up")
    monkeypatch.setattr(radar_setup, "build", build)
    events = [{"event_id": f"e{i}", "kind": "dip_turn" if i % 2 else "gap_reversal"} for i in range(1, 6)]
    runner.build_cards([{"event_id": "plain", "kind": "relative_to_spy"}] + events)
    assert built == ["e1", "e2", "e3"]  # a non-setup event takes no slot; e1's failure still used one


def test_card_work_stops_starting_cards_once_its_time_is_spent(tmp_path, db_engine, monkeypatch):
    from app.engine import radar_setup
    runner, _ = record_reversal(tmp_path, 0, setups=db_engine, paper=Paper())
    built = []

    def slow_build(db, event, *, now, options=None, record=None):
        built.append(event["event_id"])
        runner.clock.now += 10  # two slow option reads
    monkeypatch.setattr(radar_setup, "owner_record", lambda db, direction: None)
    monkeypatch.setattr(radar_setup, "build", slow_build)
    runner.build_cards([{"event_id": f"e{i}", "kind": "dip_turn", "direction": "up"} for i in range(1, 4)])
    assert radar_runner.CARD_SECONDS == 15 and built == ["e1", "e2"]  # 20 s spent before e3: it has no card


def test_the_owner_record_is_read_once_per_direction_a_pass(tmp_path, db_engine, monkeypatch):
    from app.engine import radar_setup
    runner, _ = record_reversal(tmp_path, 0, setups=db_engine, paper=Paper())
    reads, built = [], []

    def owner_record(db, direction):
        reads.append(direction)
        return f"record {direction}"
    monkeypatch.setattr(radar_setup, "owner_record", owner_record)
    monkeypatch.setattr(radar_setup, "build", lambda db, event, *, now, options=None, record=None: built.append(record))
    runner.build_cards([{"event_id": f"e{i}", "kind": "dip_turn", "direction": d} for i, d in enumerate(["up", "down", "up"])])
    assert reads == ["up", "down"] and built == ["record up", "record down", "record up"]


def test_trial_pings_go_before_card_work_and_setup_pings_after_it(tmp_path, db_engine, monkeypatch):
    from app.engine import radar_setup
    from tests import test_radar_dip as dipfix
    log = []

    class Alerts(dipfix.Alerts):
        def record(self, events):
            super().record(events)
            log.append(("record", [e["event_id"] for e in events]))

        def deliver(self):
            log.append(("deliver",))
    monkeypatch.setattr(radar_setup, "build", lambda db, event, **k: log.append(("card", event["event_id"])))
    monkeypatch.setattr(dipfix, "Alerts", Alerts)
    record_reversal(tmp_path, 12, setups=db_engine, reversal_alerts=True, paper=Paper())
    event = "rg0-2030-01-15-reversal-aaa-up-1"
    at = log.index(("card", event))
    assert log[at - 1] == ("deliver",) and log[at + 1:at + 3] == [("record", [event]), ("deliver",)]
    assert log.count(("deliver",)) == 13  # one a pass, plus the one after the setup ping


def test_a_card_or_paper_failure_never_touches_the_pass_or_its_events(tmp_path, db_engine, monkeypatch):
    from app.engine import radar_setup
    monkeypatch.setattr(radar_setup, "build", lambda *a, **k: 1 / 0)
    runner, store = record_reversal(tmp_path, 12, setups=db_engine, reversal_alerts=True, paper=Paper(fail=True))
    receipts, _ = store.detection_evidence()
    assert {p["status"] for p in store.passes()} == {"ok"} and len(store.events("2030-01-15")) == 1
    assert runner.alerts.recorded == ["rg0-2030-01-15-reversal-aaa-up-1"] and setups(db_engine) == []


def test_with_both_switches_off_nothing_new_runs(tmp_path, monkeypatch, db_engine):
    from app.engine import radar_setup, radar_setup_paper
    for name in ("RADAR_REVERSAL_RULES", "RADAR_SETUP_CARDS", "RADAR_DIP_RULES", "RADAR_ALERTS_ENABLED", "TJ_DOT_TRIAL_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    runner = radar_runner.runner_from_env()
    assert (runner.reversal, runner.reversal_alerts, runner.setups, runner.paper) == (None, False, None, None)
    monkeypatch.setattr(radar_setup, "build", lambda *a, **k: pytest.fail("a card was built"))
    monkeypatch.setattr(radar_setup_paper.SetupPaper, "step", lambda *a, **k: pytest.fail("the paper book stepped"))
    _, store = record_reversal(tmp_path / "off", 15, reversal=False)
    receipts, _ = store.detection_evidence()
    assert all(set(r) == {"pass_id", "config_digest", "origin", "status", "event_ids", "hours", "recorded_at"} for r in receipts.values())
    monkeypatch.setenv("RADAR_REVERSAL_RULES", "alert")
    monkeypatch.setenv("RADAR_SETUP_CARDS", "true")
    on = radar_runner.runner_from_env()
    assert on.reversal is not None and on.reversal_alerts is True and on.setups is not None and on.paper is not None
