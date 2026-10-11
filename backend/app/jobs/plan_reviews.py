"""The nightly daily reviews on the Claude plan (``tradejournal-plan-reviews.timer``).

Finite: one run picks the days to review, asks Claude through Claude Code on
the owner's plan (``app.ai.plan_runner``) one day at a time, saves each review
as the Daily Review button would, and writes a status file. In order:

1. the latest trading day, when it has no review yet;
2. reviews marked stale (their fills or market context changed since);
3. older trading days that never had a review, newest first.

At most ``TJ_PLAN_REVIEW_MAX`` days (10) per run, so a long backfill takes
several nights instead of a large share of the plan's usage at once. A sign-in
other than the plan stops the run before any question; two failed calls in a
row stop it too (most likely the plan's usage limit), and the next run picks up
the rest. It never falls back to API credits.

The status file is ``TJ_PLAN_REVIEW_DIR/status.json`` (production:
``/var/lib/tradejournal/plan-reviews``). ``GET /daily-review/runner`` serves it.
The exit status is 1 only when the run failed outright, so the phone-alert check
reports it.

    python -m app.jobs.plan_reviews [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sys
import time

from sqlmodel import Session, select

from app.models import DailyReviewRecord, Trade

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MAX = 10
STOP_AFTER_FAILURES = 2


def state_dir() -> Path:
    return Path(os.environ.get("TJ_PLAN_REVIEW_DIR") or BACKEND_DIR / "data" / "plan_reviews")


def read_status() -> dict | None:
    try:
        status = json.loads((state_dir() / "status.json").read_text())
    except (OSError, ValueError):
        return None
    return status if isinstance(status, dict) else None


def _write_status(status: dict) -> None:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "status.json.tmp"
    temporary.write_text(json.dumps(status, indent=2) + "\n")
    temporary.replace(directory / "status.json")


@contextmanager
def _single_run():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def trading_days(session: Session) -> list[date]:
    """Every day a trade opened or closed, newest first: the Daily Review calendar's days."""
    days: set[date] = set()
    for opened_at, closed_at in session.exec(select(Trade.opened_at, Trade.closed_at)).all():
        for value in (opened_at, closed_at):
            if value:
                days.add(value.date())
    return sorted(days, reverse=True)


def plan(session: Session, limit: int) -> tuple[list[tuple[date, str]], int]:
    """The days to review this run with why, and how many unreviewed days are left after them."""
    days = trading_days(session)
    records = {record.day: record for record in session.exec(select(DailyReviewRecord)).all()}
    chosen: list[tuple[date, str]] = []
    if days:
        # The latest day again when trades were added after its review (a review written mid-session).
        from app.ai.daily_review_service import day_trade_ids

        latest = records.get(days[0])
        if latest is None or latest.trade_count < len(day_trade_ids(session, days[0])):
            chosen.append((days[0], "latest"))
    for day in sorted(records, reverse=True):
        try:
            stale = bool(json.loads(records[day].review_json).get("source_data_stale"))
        except ValueError:
            stale = False
        if stale and day in days and (not chosen or chosen[0][0] != day):
            chosen.append((day, "stale"))
    missing = [day for day in days[1:] if day not in records]
    chosen.extend((day, "backfill") for day in missing)
    picked = chosen[:limit]
    remaining = len([day for day in missing if day not in {day for day, _ in picked}])
    return picked, remaining


def run(session: Session, limit: int, dry_run: bool = False) -> dict:
    from app.ai import daily_review_service, plan_runner

    started = time.time()
    picked, remaining = plan(session, limit)
    status: dict = {
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "finished_at": None, "state": "running", "message": "",
        "planned": [{"day": day.isoformat(), "reason": reason} for day, reason in picked],
        "written": [], "failed": [], "backfill_remaining": remaining,
        "usage": {"input_tokens": 0, "output_tokens": 0, "api_equivalent_usd": 0.0}, "model": None,
    }
    if dry_run:
        status.update(state="dry_run", message=f"{len(picked)} day(s) would be reviewed.")
        return status
    if not picked:
        status.update(state="nothing", message="Every trading day already has a current review.")
        return status
    _write_status(status)
    failures_in_row = 0
    for day, reason in picked:
        try:
            _, review = daily_review_service.generate(session, day)
        except plan_runner.PlanUnavailable as exc:
            status["failed"].append({"day": day.isoformat(), "reason": reason, "error": str(exc)})
            status.update(state="failed", message=f"The Claude plan is not available: {exc}")
            break
        except LookupError:
            continue
        except Exception as exc:  # one day's failure must not stop the others, but two in a row stop the run
            session.rollback()
            status["failed"].append({"day": day.isoformat(), "reason": reason, "error": str(exc)[:300]})
            failures_in_row += 1
            if failures_in_row >= STOP_AFTER_FAILURES:
                status["message"] = "Stopped after two failed reviews in a row (possibly the plan's usage limit); the next run continues."
                break
            continue
        failures_in_row = 0
        status["written"].append({"day": day.isoformat(), "reason": reason, "grade": review.get("day_grade")})
        usage = review.get("usage") or {}
        for key in ("input_tokens", "output_tokens"):
            status["usage"][key] += int(usage.get(key) or 0)
        status["usage"]["api_equivalent_usd"] = round(status["usage"]["api_equivalent_usd"] + float(usage.get("api_equivalent_usd") or 0), 4)
        status["model"] = review.get("generated_by")
    status["backfill_remaining"] = plan(session, 0)[1]
    if status["state"] != "failed":
        status["state"] = "ok" if not status["failed"] else ("partial" if status["written"] else "failed")
        if not status["message"]:
            status["message"] = f"{len(status['written'])} review(s) written" + (f", {len(status['failed'])} failed" if status["failed"] else "") + "."
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the nightly daily reviews on the Claude plan.")
    parser.add_argument("--max", type=int, default=int(os.environ.get("TJ_PLAN_REVIEW_MAX") or DEFAULT_MAX))
    parser.add_argument("--dry-run", action="store_true", help="list the days it would review and stop")
    args = parser.parse_args(argv)
    from app.database import engine

    with _single_run() as alone:
        if not alone:
            print("Another plan review run is in progress.")
            return 0
        with Session(engine) as session:
            status = run(session, max(1, args.max), args.dry_run)
        if not args.dry_run:
            _write_status(status)
    print(json.dumps(status, indent=2))
    return 1 if status["state"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
