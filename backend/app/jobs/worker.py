"""Supervised, single-host worker: python -m app.jobs.worker --lane sync."""

import argparse
import logging
import os
import signal
import threading

from app.database import engine
from app.engine.job_runtime import LANES, lock_directory, recover_interrupted, worker_tick
from app.schema import ensure_current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=LANES, default="sync")
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--once", action="store_true", help="Recover interrupted work and process one queued job, then exit")
    parser.add_argument("--recover-unowned", action="store_true", help="Fail legacy running rows; use only after stopping all old executors")
    parser.add_argument("--recover-only", action="store_true", help="Recover interrupted rows and exit without executing queued work")
    args = parser.parse_args()
    if args.poll_seconds < 1:
        parser.error("--poll-seconds must be at least 1")
    os.environ["JOB_EXECUTION_MODE"] = "external"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    lock_directory()
    ensure_current(engine)
    stop = threading.Event()
    # Finish the current job on SIGTERM. A supervisor can force-kill after its
    # shutdown timeout; the next worker records that interruption without replay.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if args.recover_unowned or args.recover_only:
        recovered = recover_interrupted(lane=args.lane, unowned=args.recover_unowned)
        logging.info("Recovered %d interrupted job(s)", recovered)
    if args.recover_only:
        return
    while not stop.is_set():
        try:
            worker_tick(args.lane)
        except Exception:
            logging.exception("Worker iteration failed (%s)", args.lane)
            if args.once:
                raise
        if args.once:
            break
        stop.wait(args.poll_seconds)


if __name__ == "__main__":
    main()
