from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Barrier, Event, Lock
import time

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine.tradingview import parse_alert_bytes
from app.engine.tradingview_alerts import persist_alert
from app.engine.tradingview_analysis import (
    AnalysisSettings,
    TradingViewAnalysisWorker,
    _finalize_done,
    claim_alert,
    next_recoverable_alert_id,
    run_alert_analysis,
)
from app.models import TradingViewAlert


NOW = datetime(2026, 7, 26, 18, 0, 0)


@pytest.fixture
def alert_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


def _file_engine(path: Path):
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _bar_time_ms(value: datetime) -> int:
    aware = value.replace(tzinfo=timezone.utc)
    return int(aware.timestamp() * 1000)


def _raw_body(
    *,
    symbol: str = "AAPL",
    bar_time: datetime = NOW,
    price: float = 214.32,
) -> bytes:
    bar_ms = _bar_time_ms(bar_time)
    payload = {
        "v": 1,
        "indicator_version": "1.0.0",
        "alert_id": (
            f"v1:1.0.0:{symbol}:5:{bar_ms}:orb_break:long"
        ),
        "symbol": symbol,
        "timeframe": "5",
        "setup": "orb_break",
        "side": "long",
        "price": price,
        "bar_time_ms": bar_ms,
        "levels": {"or_high": price},
        "context": {"above_vwap": True},
    }
    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _persist(
    engine,
    *,
    symbol: str = "AAPL",
    bar_time: datetime = NOW,
) -> str:
    raw_body = _raw_body(symbol=symbol, bar_time=bar_time)
    parsed = parse_alert_bytes(raw_body)
    with Session(engine) as session:
        persist_alert(session, parsed, raw_body)
    return parsed.alert_id


def _settings(**overrides) -> AnalysisSettings:
    values = {
        "max_attempts": 3,
        "max_signal_age_seconds": 1_800,
        "max_future_skew_seconds": 120,
        "running_lease_seconds": 60,
        "error_retry_seconds": 0,
        "poll_seconds": 0.02,
    }
    values.update(overrides)
    return AnalysisSettings(**values)


def _analysis_result(
    symbol: str,
    direction: str,
    *,
    verdict: str = "wait",
    confidence: str = "medium",
) -> dict:
    return {
        "request": {
            "symbol": symbol,
            "direction": direction,
            "instrument": "stock",
        },
        "assessment": {
            "symbol": symbol,
            "verdict": verdict,
            "confidence": confidence,
            "reasons_for": ["test reason"],
            "reasons_against": [],
        },
        "data": {
            "market_state": "open",
            "source": "test",
        },
    }


def test_successful_analysis_persists_fenced_result_and_preserves_evidence(
    alert_engine,
):
    alert_id = _persist(alert_engine)
    with Session(alert_engine) as session:
        before = session.get(TradingViewAlert, alert_id)
        immutable = (
            before.payload_json,
            before.raw_payload_sha256,
            before.content_sha256,
            before.levels_json,
            before.context_json,
        )

    status = run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=lambda symbol, direction: _analysis_result(
            symbol,
            direction,
            verdict="long_scalp",
            confidence="high",
        ),
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    )

    assert status == "done"
    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row is not None
        assert row.analysis_status == "done"
        assert row.analysis_attempts == 1
        assert row.scorer_revision == "scalper-v1"
        assert row.verdict == "long_scalp"
        assert row.confidence == "high"
        assert row.analysis_error_code is None
        stored = json.loads(row.assessment_json)
        assert stored["request"]["symbol"] == "AAPL"
        assert stored["assessment"]["verdict"] == "long_scalp"
        assert (
            row.payload_json,
            row.raw_payload_sha256,
            row.content_sha256,
            row.levels_json,
            row.context_json,
        ) == immutable


def test_missing_configuration_is_skipped_then_recovered_after_restart(
    alert_engine,
):
    alert_id = _persist(alert_engine)

    first = run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=lambda *_args, **_kwargs: pytest.fail(
            "analyzer must not run without Alpaca configuration"
        ),
        alpaca_ready=lambda: False,
        now_factory=lambda: NOW,
    )
    assert first == "skipped"
    with Session(alert_engine) as session:
        skipped = session.get(TradingViewAlert, alert_id)
        assert skipped.analysis_error_code == "alpaca_not_configured"
        assert skipped.analysis_attempts == 1

    second = run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=lambda symbol, direction: _analysis_result(
            symbol,
            direction,
        ),
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(seconds=1),
    )
    assert second == "done"
    with Session(alert_engine) as session:
        recovered = session.get(TradingViewAlert, alert_id)
        assert recovered.analysis_status == "done"
        assert recovered.analysis_attempts == 2


@pytest.mark.parametrize(
    ("bar_time", "code"),
    [
        (NOW - timedelta(minutes=31), "signal_stale"),
        (NOW + timedelta(minutes=3), "signal_time_in_future"),
    ],
)
def test_signal_time_guards_skip_without_market_calls(
    alert_engine,
    bar_time,
    code,
):
    alert_id = _persist(alert_engine, bar_time=bar_time)

    status = run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=lambda *_args, **_kwargs: pytest.fail(
            "time-invalid signal must not call the analyzer"
        ),
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    )

    assert status == "skipped"
    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_error_code == code
        assert row.verdict is None
        assert row.assessment_json is None


def test_retryable_error_is_bounded_by_attempt_limit(alert_engine):
    alert_id = _persist(alert_engine)
    settings = _settings(max_attempts=2)

    def fail(*_args, **_kwargs):
        raise RuntimeError(
            "Alpaca request failed after 5 retries: temporary outage"
        )

    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=settings,
        analyzer=fail,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    ) == "error"
    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=settings,
        analyzer=fail,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(seconds=1),
    ) == "error"
    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=settings,
        analyzer=fail,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(seconds=2),
    ) is None

    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_status == "error"
        assert row.analysis_attempts == 2
        assert row.analysis_error_code == "alpaca_retry_exhausted"
        assert "temporary outage" in row.analysis_error


@pytest.mark.parametrize(
    ("error_factory", "expected_code"),
    [
        (
            lambda: httpx.ReadTimeout(
                "timed out",
                request=httpx.Request("GET", "https://data.alpaca.test"),
            ),
            "alpaca_transport_error",
        ),
        (
            lambda: httpx.HTTPStatusError(
                "server unavailable",
                request=httpx.Request("GET", "https://data.alpaca.test"),
                response=httpx.Response(
                    503,
                    request=httpx.Request(
                        "GET",
                        "https://data.alpaca.test",
                    ),
                ),
            ),
            "alpaca_http_retryable",
        ),
    ],
)
def test_transient_alpaca_failures_are_bounded_and_retryable(
    alert_engine,
    error_factory,
    expected_code,
):
    alert_id = _persist(alert_engine)
    settings = _settings(max_attempts=2)

    def fail(*_args, **_kwargs):
        raise error_factory()

    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=settings,
        analyzer=fail,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    ) == "error"
    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=settings,
        analyzer=fail,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(seconds=1),
    ) == "error"
    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=settings,
        analyzer=lambda *_args, **_kwargs: pytest.fail(
            "attempt limit must be terminal"
        ),
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(seconds=2),
    ) is None

    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_attempts == 2
        assert row.analysis_error_code == expected_code


def test_generic_runtime_failure_is_terminal(alert_engine):
    alert_id = _persist(alert_engine)

    def fail(*_args, **_kwargs):
        raise RuntimeError("deterministic scorer bug")

    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=fail,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    ) == "error"
    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=lambda *_args, **_kwargs: pytest.fail(
            "generic runtime failures must not retry"
        ),
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(minutes=1),
    ) is None

    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_error_code == "analysis_runtime_error"
        assert row.analysis_attempts == 1


def test_invalid_output_is_terminal_and_does_not_retry(alert_engine):
    alert_id = _persist(alert_engine)

    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=lambda *_args, **_kwargs: {"assessment": {}},
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    ) == "error"
    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=_settings(),
        analyzer=lambda *_args, **_kwargs: pytest.fail(
            "invalid output must not retry"
        ),
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(minutes=5),
    ) is None

    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_error_code == "analysis_output_invalid"
        assert row.analysis_attempts == 1


def test_two_workers_racing_one_alert_run_the_scorer_once(tmp_path):
    engine = _file_engine(tmp_path / "claim-race.sqlite")
    alert_id = _persist(engine)
    barrier = Barrier(2)
    call_lock = Lock()
    calls = 0

    def analyzer(symbol, direction):
        nonlocal calls
        with call_lock:
            calls += 1
        time.sleep(0.1)
        return _analysis_result(symbol, direction)

    def run_once():
        barrier.wait()
        return run_alert_analysis(
            engine,
            alert_id,
            settings=_settings(),
            analyzer=analyzer,
            alpaca_ready=lambda: True,
            now_factory=lambda: NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: run_once(), range(2)))

    assert outcomes.count("done") == 1
    assert outcomes.count(None) == 1
    assert calls == 1
    with Session(engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_status == "done"
        assert row.analysis_attempts == 1


def test_attempt_fence_rejects_late_result_from_expired_worker(alert_engine):
    alert_id = _persist(alert_engine)
    settings = _settings(max_attempts=3, running_lease_seconds=60)
    first = claim_alert(
        alert_engine,
        alert_id,
        now=NOW,
        settings=settings,
        allow_config_recovery=True,
    )
    assert first is not None
    second = claim_alert(
        alert_engine,
        alert_id,
        now=NOW + timedelta(seconds=61),
        settings=settings,
        allow_config_recovery=True,
    )
    assert second is not None
    assert (first.attempt, second.attempt) == (1, 2)

    assert _finalize_done(
        alert_engine,
        first,
        assessment_json='{"winner":"old"}',
        verdict="long_scalp",
        confidence="high",
        now=NOW + timedelta(seconds=62),
    ) is False
    assert _finalize_done(
        alert_engine,
        second,
        assessment_json='{"winner":"new"}',
        verdict="wait",
        confidence="medium",
        now=NOW + timedelta(seconds=63),
    ) is True

    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert json.loads(row.assessment_json) == {"winner": "new"}
        assert row.verdict == "wait"
        assert row.analysis_attempts == 2


def test_run_discards_result_when_claim_is_replaced_during_analysis(
    alert_engine,
):
    alert_id = _persist(alert_engine)
    settings = _settings(running_lease_seconds=60)
    replacement = None

    def analyzer(symbol, direction):
        nonlocal replacement
        replacement = claim_alert(
            alert_engine,
            alert_id,
            now=NOW + timedelta(seconds=61),
            settings=settings,
            allow_config_recovery=True,
        )
        assert replacement is not None
        return _analysis_result(symbol, direction)

    assert run_alert_analysis(
        alert_engine,
        alert_id,
        settings=settings,
        analyzer=analyzer,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    ) is None

    with Session(alert_engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_status == "running"
        assert row.analysis_attempts == 2
        assert row.assessment_json is None


def test_network_phase_holds_no_database_transaction(tmp_path):
    engine = _file_engine(tmp_path / "no-open-transaction.sqlite")
    active_id = _persist(engine, symbol="AAPL")
    other_id = _persist(
        engine,
        symbol="MSFT",
        bar_time=NOW + timedelta(seconds=1),
    )
    entered = Event()
    release = Event()

    def analyzer(symbol, direction):
        entered.set()
        assert release.wait(3)
        return _analysis_result(symbol, direction)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_alert_analysis,
            engine,
            active_id,
            settings=_settings(),
            analyzer=analyzer,
            alpaca_ready=lambda: True,
            now_factory=lambda: NOW,
        )
        assert entered.wait(2)
        with Session(engine) as session:
            other = session.get(TradingViewAlert, other_id)
            other.updated_at = NOW + timedelta(seconds=2)
            session.add(other)
            session.commit()
        release.set()
        assert future.result(timeout=3) == "done"


def test_worker_drains_durable_rows_and_survives_one_failure(tmp_path):
    engine = _file_engine(tmp_path / "worker-drain.sqlite")
    ids = [
        _persist(
            engine,
            symbol=symbol,
            bar_time=NOW + timedelta(seconds=index),
        )
        for index, symbol in enumerate(("AAPL", "MSFT", "NVDA", "AMD"))
    ]

    def analyzer(symbol, direction):
        if symbol == "AAPL":
            raise RuntimeError("temporary scorer failure")
        return _analysis_result(symbol, direction)

    worker = TradingViewAnalysisWorker(
        engine,
        settings=_settings(max_attempts=1),
        analyzer=analyzer,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW + timedelta(seconds=5),
    )
    worker.start()
    deadline = time.monotonic() + 5
    statuses: dict[str, str] = {}
    while time.monotonic() < deadline:
        with Session(engine) as session:
            statuses = {
                alert_id: session.get(
                    TradingViewAlert,
                    alert_id,
                ).analysis_status
                for alert_id in ids
            }
        if all(status in {"done", "error"} for status in statuses.values()):
            break
        time.sleep(0.03)
    worker.stop(timeout=2)

    assert worker.running is False
    assert statuses[ids[0]] == "error"
    assert all(statuses[alert_id] == "done" for alert_id in ids[1:])


def test_worker_stop_is_bounded_during_blocking_analysis(tmp_path):
    engine = _file_engine(tmp_path / "bounded-stop.sqlite")
    _persist(engine)
    entered = Event()
    release = Event()

    def analyzer(symbol, direction):
        entered.set()
        assert release.wait(3)
        return _analysis_result(symbol, direction)

    worker = TradingViewAnalysisWorker(
        engine,
        settings=_settings(),
        analyzer=analyzer,
        alpaca_ready=lambda: True,
        now_factory=lambda: NOW,
    )
    worker.start()
    assert entered.wait(2)
    assert worker._thread is not None
    assert worker._thread.daemon is True

    started = time.monotonic()
    worker.stop(timeout=0.05)
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert worker.running is True
    release.set()
    deadline = time.monotonic() + 3
    while worker.running and time.monotonic() < deadline:
        time.sleep(0.02)
    worker.stop(timeout=0.1)
    assert worker.running is False


def test_recent_running_claim_is_not_recovered_until_lease_expires(
    alert_engine,
):
    alert_id = _persist(alert_engine)
    settings = _settings(running_lease_seconds=60)
    claim = claim_alert(
        alert_engine,
        alert_id,
        now=NOW,
        settings=settings,
        allow_config_recovery=True,
    )
    assert claim is not None

    assert next_recoverable_alert_id(
        alert_engine,
        now=NOW + timedelta(seconds=59),
        settings=settings,
        allow_config_recovery=True,
    ) is None
    assert next_recoverable_alert_id(
        alert_engine,
        now=NOW + timedelta(seconds=61),
        settings=settings,
        allow_config_recovery=True,
    ) == alert_id


def test_fast_restart_eventually_marks_final_claim_abandoned(tmp_path):
    engine = _file_engine(tmp_path / "final-claim-cleanup.sqlite")
    alert_id = _persist(engine)
    settings = _settings(max_attempts=1, running_lease_seconds=60)
    assert claim_alert(
        engine,
        alert_id,
        now=NOW,
        settings=settings,
        allow_config_recovery=True,
    ) is not None

    clock = {"now": NOW + timedelta(seconds=1)}
    worker = TradingViewAnalysisWorker(
        engine,
        settings=settings,
        analyzer=lambda *_args, **_kwargs: pytest.fail(
            "an exhausted claim must not run again"
        ),
        alpaca_ready=lambda: True,
        now_factory=lambda: clock["now"],
    )
    worker.start()
    with Session(engine) as session:
        assert (
            session.get(TradingViewAlert, alert_id).analysis_status
            == "running"
        )

    clock["now"] = NOW + timedelta(seconds=61)
    worker.wake()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with Session(engine) as session:
            row = session.get(TradingViewAlert, alert_id)
            if row.analysis_status == "error":
                break
        time.sleep(0.02)
    worker.stop(timeout=1)

    with Session(engine) as session:
        row = session.get(TradingViewAlert, alert_id)
        assert row.analysis_status == "error"
        assert row.analysis_error_code == "analysis_claim_abandoned"
        assert row.analysis_attempts == 1


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_poll_interval_falls_back_to_default(monkeypatch, value):
    monkeypatch.setenv("TRADINGVIEW_ANALYSIS_POLL_SECONDS", value)

    assert (
        AnalysisSettings.from_env().poll_seconds
        == AnalysisSettings().poll_seconds
    )
