from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.engine import api_wait, enricher, jobs
from app.models import JobRun
from app.routers import sync


def test_observed_sleep_reports_only_user_visible_waits(monkeypatch):
    events: list[tuple[str, str | None, float]] = []
    slept: list[float] = []
    monkeypatch.setattr(api_wait.time, "sleep", slept.append)

    with api_wait.observe_api_waits(lambda provider, reason, seconds: events.append((provider, reason, seconds))):
        api_wait.observed_sleep("Polygon", "rate_limit", 13.25)
        api_wait.observed_sleep("Alpaca", "rate_limit", 1.0)

    assert slept == [13.25, 1.0]
    assert events == [
        ("Polygon", "rate_limit", 13.25),
        ("Polygon", None, 0.0),
    ]


def test_polygon_limiter_labels_its_intentional_wait(monkeypatch):
    limiter = enricher._RateLimiter(60.0)
    limiter._last = 10.0
    monotonic = iter([10.25, 11.0])
    waits: list[tuple[str, str, float]] = []
    monkeypatch.setattr(enricher.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(enricher, "observed_sleep", lambda provider, reason, seconds: waits.append((provider, reason, seconds)))

    limiter.wait()

    assert waits == [("Polygon", "rate_limit", 0.75)]


def test_job_wait_observer_sets_and_clears_durable_wait_state(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(jobs, "_set_job", lambda _job_id, **values: calls.append(values))
    observer = jobs._api_wait_observer(uuid.uuid4())
    before = datetime.utcnow()

    observer("Polygon", "provider_429", 30.0)
    observer("Polygon", None, 0.0)

    assert calls[0]["phase"] == "waiting_api"
    assert calls[0]["wait_provider"] == "Polygon"
    assert calls[0]["wait_reason"] == "provider_429"
    assert before + timedelta(seconds=29) <= calls[0]["wait_until"] <= datetime.utcnow() + timedelta(seconds=31)
    assert calls[1] == {
        "ignore_locked": True,
        "phase": "processing",
        "wait_provider": None,
        "wait_reason": None,
        "wait_until": None,
    }


def test_sync_job_row_exposes_exact_progress_wait_and_utc_timestamps():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    started = datetime(2026, 9, 16, 1, 30, 0)
    wait_until = started + timedelta(seconds=13)

    with Session(engine) as session:
        session.add(
            JobRun(
                job_type=jobs.JOB_POLYGON_ENRICH,
                status="running",
                total=136,
                done=15,
                current="NBIS",
                phase="waiting_api",
                wait_provider="Polygon",
                wait_reason="rate_limit",
                wait_until=wait_until,
                started_at=started,
                updated_at=started,
            )
        )
        session.commit()

        config = next(item for item in sync.JOB_CONFIG if item["job_type"] == jobs.JOB_POLYGON_ENRICH)
        row = sync._job_to_row(session, config)

    assert row["done"] == 15
    assert row["total"] == 136
    assert row["progress_unit"] == "fill"
    assert row["phase"] == "waiting_api"
    assert row["wait_provider"] == "Polygon"
    assert row["wait_reason"] == "rate_limit"
    assert row["wait_until"] == "2026-09-16T01:30:13Z"
    assert row["started_at"] == "2026-09-16T01:30:00Z"
