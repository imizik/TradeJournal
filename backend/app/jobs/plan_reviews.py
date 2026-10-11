"""The nightly daily reviews on the Claude plan (``tradejournal-plan-reviews.timer``).

Finite: one run reviews the latest trading day only (and, on its first run in
a new month, last month as a whole: app.ai.monthly_reviewer), asking Claude through
Claude Code on the owner's plan (``app.ai.plan_runner``), saves it as the Daily
Review button would, and writes a status file. The latest day is reviewed when
it has no review, when trades were added after its review (one written
mid-session), or when its review is marked stale. Older days are never
backfilled: a past day gets a review only from its own Daily Review button.

A sign-in other than the plan stops the run before any question. It never falls
back to API credits.

The status file is ``TJ_PLAN_REVIEW_DIR/status.json`` (production:
``/var/lib/tradejournal/plan-reviews``). ``GET /daily-review/runner`` serves it.
The exit status is 1 only when the run failed outright, so the phone-alert check
reports it.

    python -m app.jobs.plan_reviews [--dry-run]
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
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models import DailyReviewRecord, MonthlyReviewRecord, Trade

BACKEND_DIR = Path(__file__).resolve().parents[2]


def state_dir() -> Path:
    return Path(os.environ.get("TJ_PLAN_REVIEW_DIR") or BACKEND_DIR / "data" / "plan_reviews")


def read_status() -> dict | None:
    try:
        status = json.loads((state_dir() / "status.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(status, dict):
        return None
    if status.get("state") == "running" and not _run_in_progress():
        # Stopped mid-run (a deploy or a crash): the next run tries again.
        status = {**status, "state": "interrupted", "message": "The last run stopped before it finished; the next run tries again."}
    return status


def _run_in_progress() -> bool:
    try:
        with (state_dir() / "run.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
    except BlockingIOError:
        return True
    except OSError:
        return False
    return False


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
        # A status read holds the lock for an instant; only a lock still held after a second is another run.
        for attempt in range(10):
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == 9:
                    yield False
                    return
                time.sleep(0.1)
        yield True


def _label(key: date | str) -> str:
    return key if isinstance(key, str) else key.isoformat()


def trading_days(session: Session) -> list[date]:
    """Every day a trade opened or closed, newest first: the Daily Review calendar's days."""
    days: set[date] = set()
    for opened_at, closed_at in session.exec(select(Trade.opened_at, Trade.closed_at)).all():
        for value in (opened_at, closed_at):
            if value:
                days.add(value.date())
    return sorted(days, reverse=True)


def plan(session: Session) -> list[tuple[date, str]]:
    """The latest trading day with why, when it needs a review; otherwise nothing."""
    days = trading_days(session)
    if not days:
        return []
    from app.ai.daily_review_service import day_trade_ids

    record = session.exec(select(DailyReviewRecord).where(DailyReviewRecord.day == days[0])).first()
    if record is None:
        return [(days[0], "latest")]
    if record.trade_count < len(day_trade_ids(session, days[0])):
        return [(days[0], "trades added")]
    try:
        stale = bool(json.loads(record.review_json).get("source_data_stale"))
    except ValueError:
        stale = False
    return [(days[0], "stale")] if stale else []


def plan_month(session: Session, today: date) -> str | None:
    """Last calendar month, when it had closed trades and has no monthly review yet: the first run of a month writes it."""
    from app.ai import monthly_reviewer

    month = monthly_reviewer.previous_month(today.strftime("%Y-%m"))
    if session.exec(select(MonthlyReviewRecord.id).where(MonthlyReviewRecord.month == month)).first() is not None:
        return None
    return month if monthly_reviewer.closed_trades(session, month) else None


def run(session: Session, dry_run: bool = False, today: date | None = None) -> dict:
    from app.ai import daily_review_service, monthly_reviewer, plan_runner

    started = time.time()
    picked: list[tuple[date | str, str]] = list(plan(session))
    month = plan_month(session, today or datetime.now(ZoneInfo("America/New_York")).date())
    if month:
        picked.append((month, "monthly"))
    status: dict = {
        "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "finished_at": None, "state": "running", "message": "",
        "planned": [{"day": _label(key), "reason": reason} for key, reason in picked],
        "written": [], "failed": [],
        "usage": {"input_tokens": 0, "output_tokens": 0, "api_equivalent_usd": 0.0}, "model": None,
    }
    if dry_run:
        status.update(state="dry_run", message=f"{len(picked)} review(s) would be written.")
        return status
    if not picked:
        status.update(state="nothing", message="The latest trading day and last month already have current reviews.")
        return status
    _write_status(status)
    for key, reason in picked:
        try:
            # Always the plan, whatever AI_REVIEW_BACKEND says: the nightly run never bills API credits.
            if isinstance(key, str):
                _, review = monthly_reviewer.generate(session, key, backend="plan")
            else:
                _, review = daily_review_service.generate(session, key, backend="plan")
        except plan_runner.PlanUnavailable as exc:
            status["failed"].append({"day": _label(key), "reason": reason, "error": str(exc)})
            status.update(state="failed", message=f"The Claude plan is not available: {exc}")
            break
        except LookupError:
            continue
        except Exception as exc:  # e.g. the plan's usage limit: recorded, and the next run tries again
            session.rollback()
            status["failed"].append({"day": _label(key), "reason": reason, "error": str(exc)[:300]})
            continue
        status["written"].append({"day": _label(key), "reason": reason, "grade": review.get("day_grade") or review.get("month_grade")})
        usage = review.get("usage") or {}
        for key in ("input_tokens", "output_tokens"):
            status["usage"][key] += int(usage.get(key) or 0)
        status["usage"]["api_equivalent_usd"] = round(status["usage"]["api_equivalent_usd"] + float(usage.get("api_equivalent_usd") or 0), 4)
        status["model"] = review.get("generated_by")
    if status["state"] != "failed":
        status["state"] = "failed" if status["failed"] else "ok"
        if not status["message"]:
            status["message"] = f"{len(status['written'])} review(s) written" + (f", {len(status['failed'])} failed" if status["failed"] else "") + "."
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the nightly daily reviews on the Claude plan.")
    parser.add_argument("--dry-run", action="store_true", help="say whether it would review the latest day and stop")
    args = parser.parse_args(argv)
    from app.database import engine

    with _single_run() as alone:
        if not alone:
            print("Another plan review run is in progress.")
            return 0
        try:
            with Session(engine) as session:
                status = run(session, args.dry_run)
        except Exception as exc:  # a database or code failure still leaves a truthful status
            # Keep what this run already recorded; never last night's results as tonight's.
            previous = read_status() or {}
            kept = previous if previous.get("state") == "running" else {"planned": [], "written": [], "failed": []}
            status = {**kept, "state": "failed", "message": f"The run failed: {type(exc).__name__}: {str(exc)[:300]}",
                      "finished_at": datetime.now(timezone.utc).isoformat()}
            status.setdefault("started_at", status["finished_at"])
            if not args.dry_run:
                _write_status(status)
            raise
        if not args.dry_run:
            _write_status(status)
    print(json.dumps(status, indent=2))
    return 1 if status["state"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
