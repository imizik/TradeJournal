"""Durable, fenced analysis worker for persisted TradingView alerts.

The database is the queue. A worker atomically claims one recoverable row,
closes the claim session before any market-data call, then conditionally
finalizes with ``analysis_attempts`` as its fencing token. This keeps SQLite
transactions short and prevents an expired worker from overwriting a newer
attempt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import os
import threading
import time
from typing import Any

import httpx
from sqlalchemy import and_, case, or_, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.engine.alpaca import alpaca_configured
from app.engine.scalper import build_scalp_analysis
from app.models import TradingViewAlert


log = logging.getLogger(__name__)

SCORER_REVISION = "scalper-v1"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_SIGNAL_AGE_SECONDS = 30 * 60
DEFAULT_MAX_FUTURE_SKEW_SECONDS = 2 * 60
DEFAULT_RUNNING_LEASE_SECONDS = 15 * 60
DEFAULT_ERROR_RETRY_SECONDS = 60
DEFAULT_POLL_SECONDS = 1.0
MAX_ERROR_LENGTH = 2_000
FINALIZE_DB_ATTEMPTS = 3

VERDICTS = frozenset(
    {"no_trade", "wait", "long_scalp", "short_scalp"}
)
CONFIDENCES = frozenset({"low", "medium", "high"})
RETRYABLE_ERROR_CODES = frozenset(
    {
        "alpaca_retry_exhausted",
        "alpaca_transport_error",
        "alpaca_http_retryable",
    }
)


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_signal_age_seconds: int = DEFAULT_MAX_SIGNAL_AGE_SECONDS
    max_future_skew_seconds: int = DEFAULT_MAX_FUTURE_SKEW_SECONDS
    running_lease_seconds: int = DEFAULT_RUNNING_LEASE_SECONDS
    error_retry_seconds: int = DEFAULT_ERROR_RETRY_SECONDS
    poll_seconds: float = DEFAULT_POLL_SECONDS

    @classmethod
    def from_env(cls) -> "AnalysisSettings":
        return cls(
            max_attempts=_bounded_int_env(
                "TRADINGVIEW_ANALYSIS_MAX_ATTEMPTS",
                DEFAULT_MAX_ATTEMPTS,
                minimum=1,
                maximum=20,
            ),
            max_signal_age_seconds=_bounded_int_env(
                "TRADINGVIEW_ALERT_MAX_AGE_SECONDS",
                DEFAULT_MAX_SIGNAL_AGE_SECONDS,
                minimum=60,
                maximum=7 * 24 * 60 * 60,
            ),
            max_future_skew_seconds=_bounded_int_env(
                "TRADINGVIEW_ALERT_MAX_FUTURE_SKEW_SECONDS",
                DEFAULT_MAX_FUTURE_SKEW_SECONDS,
                minimum=0,
                maximum=60 * 60,
            ),
            running_lease_seconds=_bounded_int_env(
                "TRADINGVIEW_ANALYSIS_LEASE_SECONDS",
                DEFAULT_RUNNING_LEASE_SECONDS,
                minimum=60,
                maximum=24 * 60 * 60,
            ),
            error_retry_seconds=_bounded_int_env(
                "TRADINGVIEW_ANALYSIS_RETRY_SECONDS",
                DEFAULT_ERROR_RETRY_SECONDS,
                minimum=0,
                maximum=24 * 60 * 60,
            ),
            poll_seconds=_bounded_float_env(
                "TRADINGVIEW_ANALYSIS_POLL_SECONDS",
                DEFAULT_POLL_SECONDS,
                minimum=0.1,
                maximum=60.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class AnalysisClaim:
    alert_id: str
    symbol: str
    side: str
    bar_time: datetime
    attempt: int
    scorer_revision: str


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def run_alert_analysis(
    db_engine: Engine,
    alert_id: str,
    *,
    settings: AnalysisSettings | None = None,
    analyzer: Callable[..., dict[str, Any]] | None = None,
    alpaca_ready: Callable[[], bool] | None = None,
    now_factory: Callable[[], datetime] = utc_now_naive,
) -> str | None:
    """Claim and analyze one alert; return its final status or ``None``.

    ``None`` means another worker owns the row or it is not recoverable.
    """

    resolved_settings = settings or AnalysisSettings.from_env()
    resolved_analyzer = analyzer or build_scalp_analysis
    resolved_alpaca_ready = alpaca_ready or alpaca_configured
    now = now_factory()
    claim = claim_alert(
        db_engine,
        alert_id,
        now=now,
        settings=resolved_settings,
        allow_config_recovery=resolved_alpaca_ready(),
    )
    if claim is None:
        return None

    age_seconds = (now - claim.bar_time).total_seconds()
    if age_seconds > resolved_settings.max_signal_age_seconds:
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="skipped",
            code="signal_stale",
            detail=(
                "Signal bar close is too old for a live scalp assessment "
                f"({int(age_seconds)} seconds old)"
            ),
            now=now_factory(),
        )
        return "skipped" if finalized else None
    if age_seconds < -resolved_settings.max_future_skew_seconds:
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="skipped",
            code="signal_time_in_future",
            detail="Signal bar close is too far in the future",
            now=now_factory(),
        )
        return "skipped" if finalized else None
    if not resolved_alpaca_ready():
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="skipped",
            code="alpaca_not_configured",
            detail="Alpaca credentials are not configured",
            now=now_factory(),
        )
        return "skipped" if finalized else None

    try:
        result = resolved_analyzer(
            claim.symbol,
            direction=claim.side,
        )
        serialized, verdict, confidence = _validated_analysis_result(
            result,
            claim,
        )
    except httpx.TransportError as exc:
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="error",
            code="alpaca_transport_error",
            detail=_safe_error_text(exc),
            now=now_factory(),
        )
        return "error" if finalized else None
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        retryable = status_code in {408, 429} or status_code >= 500
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="error",
            code=(
                "alpaca_http_retryable"
                if retryable
                else "alpaca_http_error"
            ),
            detail=_safe_error_text(exc),
            now=now_factory(),
        )
        return "error" if finalized else None
    except RuntimeError as exc:
        message = _safe_error_text(exc)
        code = (
            "alpaca_retry_exhausted"
            if message.startswith("Alpaca request failed after 5 retries:")
            else "analysis_runtime_error"
        )
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="error",
            code=code,
            detail=message,
            now=now_factory(),
        )
        return "error" if finalized else None
    except (TypeError, ValueError, KeyError) as exc:
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="error",
            code="analysis_output_invalid",
            detail=_safe_error_text(exc),
            now=now_factory(),
        )
        return "error" if finalized else None
    except Exception as exc:
        log.exception(
            "Unexpected TradingView analysis failure for alert_id=%s",
            claim.alert_id,
        )
        finalized = _finalize_non_success(
            db_engine,
            claim,
            status="error",
            code="analysis_unexpected_error",
            detail=_safe_error_text(exc),
            now=now_factory(),
        )
        return "error" if finalized else None

    finalized = _finalize_done(
        db_engine,
        claim,
        assessment_json=serialized,
        verdict=verdict,
        confidence=confidence,
        now=now_factory(),
    )
    return "done" if finalized else None


def claim_alert(
    db_engine: Engine,
    alert_id: str,
    *,
    now: datetime,
    settings: AnalysisSettings,
    allow_config_recovery: bool,
) -> AnalysisClaim | None:
    """Atomically claim one eligible alert and return a detached work item."""

    eligibility = _recoverable_condition(
        now=now,
        settings=settings,
        allow_config_recovery=allow_config_recovery,
    )
    statement = (
        update(TradingViewAlert)
        .where(TradingViewAlert.alert_id == alert_id)
        .where(eligibility)
        .values(
            analysis_status="running",
            analysis_attempts=TradingViewAlert.analysis_attempts + 1,
            analysis_started_at=now,
            analysis_completed_at=None,
            scorer_revision=SCORER_REVISION,
            verdict=None,
            confidence=None,
            assessment_json=None,
            analysis_error_code=None,
            analysis_error=None,
            updated_at=now,
        )
    )
    with Session(db_engine) as session:
        result = session.exec(statement)
        claimed = result.rowcount == 1
        if not claimed:
            return None
        row = session.exec(
            select(
                TradingViewAlert.alert_id,
                TradingViewAlert.symbol,
                TradingViewAlert.side,
                TradingViewAlert.bar_time,
                TradingViewAlert.analysis_attempts,
                TradingViewAlert.scorer_revision,
            ).where(TradingViewAlert.alert_id == alert_id)
        ).one()
        claim = AnalysisClaim(
            alert_id=row[0],
            symbol=row[1],
            side=row[2],
            bar_time=row[3],
            attempt=row[4],
            scorer_revision=row[5],
        )
        session.commit()
        return claim


def next_recoverable_alert_id(
    db_engine: Engine,
    *,
    now: datetime,
    settings: AnalysisSettings,
    allow_config_recovery: bool,
) -> str | None:
    """Return the oldest recoverable ID; the later claim remains authoritative."""

    condition = _recoverable_condition(
        now=now,
        settings=settings,
        allow_config_recovery=allow_config_recovery,
    )
    priority = case(
        (TradingViewAlert.analysis_status == "pending", 0),
        (TradingViewAlert.analysis_status == "running", 1),
        (TradingViewAlert.analysis_status == "error", 2),
        else_=3,
    )
    with Session(db_engine) as session:
        return session.exec(
            select(TradingViewAlert.alert_id)
            .where(condition)
            .order_by(
                priority,
                TradingViewAlert.received_at.asc(),
                TradingViewAlert.alert_id.asc(),
            )
            .limit(1)
        ).first()


class TradingViewAnalysisWorker:
    """One cooperatively stoppable poller over the durable alert queue."""

    def __init__(
        self,
        db_engine: Engine,
        *,
        settings: AnalysisSettings | None = None,
        analyzer: Callable[..., dict[str, Any]] | None = None,
        alpaca_ready: Callable[[], bool] | None = None,
        now_factory: Callable[[], datetime] = utc_now_naive,
    ) -> None:
        self.db_engine = db_engine
        self.settings = settings or AnalysisSettings.from_env()
        self.analyzer = analyzer
        self.alpaca_ready = alpaca_ready or alpaca_configured
        self.now_factory = now_factory
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._wake_event.clear()
        _mark_abandoned_claims(
            self.db_engine,
            now=self.now_factory(),
            settings=self.settings,
        )
        self._thread = threading.Thread(
            target=self._run,
            name="tradingview-analysis-worker",
            # A bounded shutdown must not be defeated by an in-flight vendor
            # call. The fenced row remains running and is lease-recovered.
            daemon=True,
        )
        self._thread.start()

    def wake(self) -> None:
        self._wake_event.set()

    def stop(self, *, timeout: float = 10.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
            if thread.is_alive():
                log.warning(
                    "TradingView analysis worker did not stop within %.1fs; "
                    "its active claim will be recovered after the lease",
                    timeout,
                )
                return
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                _mark_abandoned_claims(
                    self.db_engine,
                    now=self.now_factory(),
                    settings=self.settings,
                )
                alert_id = next_recoverable_alert_id(
                    self.db_engine,
                    now=self.now_factory(),
                    settings=self.settings,
                    allow_config_recovery=self.alpaca_ready(),
                )
                if alert_id is not None:
                    run_alert_analysis(
                        self.db_engine,
                        alert_id,
                        settings=self.settings,
                        analyzer=self.analyzer,
                        alpaca_ready=self.alpaca_ready,
                        now_factory=self.now_factory,
                    )
                    continue
            except Exception:
                log.exception("TradingView analysis worker iteration failed")

            self._wake_event.wait(self.settings.poll_seconds)
            self._wake_event.clear()


def _recoverable_condition(
    *,
    now: datetime,
    settings: AnalysisSettings,
    allow_config_recovery: bool,
):
    attempts_available = (
        TradingViewAlert.analysis_attempts < settings.max_attempts
    )
    retry_cutoff = now - timedelta(seconds=settings.error_retry_seconds)
    lease_cutoff = now - timedelta(seconds=settings.running_lease_seconds)
    conditions = [
        and_(
            TradingViewAlert.analysis_status == "pending",
            attempts_available,
        ),
        and_(
            TradingViewAlert.analysis_status == "error",
            attempts_available,
            TradingViewAlert.analysis_error_code.in_(
                RETRYABLE_ERROR_CODES
            ),
            TradingViewAlert.updated_at <= retry_cutoff,
        ),
        and_(
            TradingViewAlert.analysis_status == "running",
            attempts_available,
            or_(
                TradingViewAlert.analysis_started_at.is_(None),
                TradingViewAlert.updated_at <= lease_cutoff,
            ),
        ),
    ]
    if allow_config_recovery:
        conditions.append(
            and_(
                TradingViewAlert.analysis_status == "skipped",
                attempts_available,
                TradingViewAlert.analysis_error_code
                == "alpaca_not_configured",
            )
        )
    return or_(*conditions)


def _mark_abandoned_claims(
    db_engine: Engine,
    *,
    now: datetime,
    settings: AnalysisSettings,
) -> None:
    lease_cutoff = now - timedelta(seconds=settings.running_lease_seconds)
    statement = (
        update(TradingViewAlert)
        .where(TradingViewAlert.analysis_status == "running")
        .where(TradingViewAlert.analysis_attempts >= settings.max_attempts)
        .where(
            or_(
                TradingViewAlert.analysis_started_at.is_(None),
                TradingViewAlert.updated_at <= lease_cutoff,
            )
        )
        .values(
            analysis_status="error",
            analysis_completed_at=now,
            verdict=None,
            confidence=None,
            assessment_json=None,
            analysis_error_code="analysis_claim_abandoned",
            analysis_error=(
                "Worker claim expired after the maximum number of attempts"
            ),
            updated_at=now,
        )
    )
    with Session(db_engine) as session:
        session.exec(statement)
        session.commit()


def _finalize_done(
    db_engine: Engine,
    claim: AnalysisClaim,
    *,
    assessment_json: str,
    verdict: str,
    confidence: str,
    now: datetime,
) -> bool:
    return _fenced_finalize(
        db_engine,
        claim,
        values={
            "analysis_status": "done",
            "analysis_completed_at": now,
            "verdict": verdict,
            "confidence": confidence,
            "assessment_json": assessment_json,
            "analysis_error_code": None,
            "analysis_error": None,
            "updated_at": now,
        },
    )


def _finalize_non_success(
    db_engine: Engine,
    claim: AnalysisClaim,
    *,
    status: str,
    code: str,
    detail: str,
    now: datetime,
) -> bool:
    return _fenced_finalize(
        db_engine,
        claim,
        values={
            "analysis_status": status,
            "analysis_completed_at": now,
            "verdict": None,
            "confidence": None,
            "assessment_json": None,
            "analysis_error_code": code,
            "analysis_error": detail[:MAX_ERROR_LENGTH],
            "updated_at": now,
        },
    )


def _fenced_finalize(
    db_engine: Engine,
    claim: AnalysisClaim,
    *,
    values: dict[str, Any],
) -> bool:
    statement = (
        update(TradingViewAlert)
        .where(TradingViewAlert.alert_id == claim.alert_id)
        .where(TradingViewAlert.analysis_status == "running")
        .where(TradingViewAlert.analysis_attempts == claim.attempt)
        .values(**values)
    )
    finalized = False
    for attempt in range(FINALIZE_DB_ATTEMPTS):
        try:
            with Session(db_engine) as session:
                result = session.exec(statement)
                finalized = result.rowcount == 1
                session.commit()
            break
        except OperationalError as exc:
            if not _is_sqlite_busy(exc) or attempt + 1 >= FINALIZE_DB_ATTEMPTS:
                raise
            time.sleep(0.05 * (attempt + 1))
    if not finalized:
        log.warning(
            "Discarded stale TradingView analysis result "
            "(alert_id=%s attempt=%d)",
            claim.alert_id,
            claim.attempt,
        )
    return finalized


def _validated_analysis_result(
    result: dict[str, Any],
    claim: AnalysisClaim,
) -> tuple[str, str, str]:
    if not isinstance(result, dict):
        raise TypeError("scalp analysis result must be an object")
    request = result.get("request")
    assessment = result.get("assessment")
    if not isinstance(request, dict) or not isinstance(assessment, dict):
        raise TypeError(
            "scalp analysis result must contain request and assessment objects"
        )
    if request.get("symbol") != claim.symbol:
        raise ValueError("scalp analysis result symbol does not match claim")
    if request.get("direction") != claim.side:
        raise ValueError(
            "scalp analysis result direction does not match claim"
        )
    verdict = assessment.get("verdict")
    confidence = assessment.get("confidence")
    if verdict not in VERDICTS:
        raise ValueError("scalp analysis result has an invalid verdict")
    if confidence not in CONFIDENCES:
        raise ValueError("scalp analysis result has an invalid confidence")
    serialized = json.dumps(
        result,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return serialized, verdict, confidence


def _safe_error_text(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:MAX_ERROR_LENGTH]


def _is_sqlite_busy(exc: OperationalError) -> bool:
    original = getattr(exc, "orig", None)
    error_code = getattr(original, "sqlite_errorcode", None)
    if error_code in {5, 6}:  # SQLITE_BUSY, SQLITE_LOCKED
        return True
    message = str(exc).lower()
    return (
        "database is locked" in message
        or "database table is locked" in message
    )


def _bounded_int_env(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("%s is invalid; using %d", name, default)
        return default
    if value < minimum or value > maximum:
        log.warning(
            "%s must be between %d and %d; using %d",
            name,
            minimum,
            maximum,
            default,
        )
        return default
    return value


def _bounded_float_env(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        log.warning("%s is invalid; using %.1f", name, default)
        return default
    if not math.isfinite(value) or value < minimum or value > maximum:
        log.warning(
            "%s must be between %.1f and %.1f; using %.1f",
            name,
            minimum,
            maximum,
            default,
        )
        return default
    return value
