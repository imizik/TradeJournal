"""Opt-in finite 08:50 ET preparation; systemd owns its dedicated lane lock."""
import os

from sqlmodel import Session

from app.database import engine
from app.engine import practice
from app.engine.job_runtime import execute_job, recover_interrupted
from app.schema import ensure_current


def main():
    if os.environ.get("PRACTICE_SCHEDULE_ENABLED") != "true":
        print("Practice schedule disabled; no job created")
        return
    moment = practice.now_utc().replace(tzinfo=practice.UTC).astimezone(practice.ET)
    if moment.hour * 60 + moment.minute < 8 * 60 + 50:
        print("Before today's 08:50 schedule; yesterday's missed session is not replayed")
        return
    ensure_current(engine)
    recover_interrupted(lane="practice")
    with Session(engine) as db:
        run = practice.start(db, mode="scheduled")
        job_id = run.job_id
    execute_job(job_id)  # exact same canonical ID; failed/finished rows never replay


if __name__ == "__main__":
    main()
