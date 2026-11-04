"""Prepare the dated roster before 09:00, then capture exactly one SIP snapshot pass."""
import asyncio
from datetime import datetime, timedelta
import logging
import os

import httpx

from app.engine.premarket_archive import ET, ROOT, Market, at, ranking, save

log = logging.getLogger(__name__)


def start():
    if os.environ.get("PREMARKET_ARCHIVE_ENABLED", "").lower() != "true" or os.environ.get("TJ_DOT_TRIAL_ENABLED") == "true":
        return None
    return asyncio.create_task(run())


def now():
    return datetime.now(ET)


def prepare(day):
    with httpx.Client(timeout=30) as client:
        market = Market(client, os.environ)
        days = market.calendar(day - timedelta(days=14), day)
        if days[-1] == day:
            return days[-2], market.symbols(day)
    return None


def capture(day, prior, symbols, market, root, clock=now):
    cutoff = at(day, 9)
    deadline = cutoff + timedelta(minutes=1)
    started = clock()
    if not cutoff <= started < deadline or (root / f"{day}.json").exists():
        return
    snapshots = market.snapshots(symbols)
    finished = clock()
    if finished >= deadline:
        raise ValueError("09:00 snapshot window expired")
    record = ranking(market, day, prior, symbols, snapshots)
    saved = clock()
    if saved >= cutoff + timedelta(minutes=30):
        raise ValueError("Archive was not ready before the regular session")
    record.update(snapshot_started_at=started.isoformat(), snapshot_finished_at=finished.isoformat(),
                  saved_at=saved.isoformat())
    return save(root, day, record)


def collect(day, prepared):
    with httpx.Client(timeout=30) as client:
        capture(day, *prepared, Market(client, os.environ), ROOT)


async def sleep_until(target):
    # Wall-clock subtraction across a weekend DST change can miss Monday's pass.
    await asyncio.sleep(max(0, target.timestamp() - now().timestamp()))


async def run():
    while True:
        current = now()
        day = current.date()
        cutoff = at(day, 9)
        if current >= cutoff + timedelta(minutes=1):
            day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        cutoff = at(day, 9)
        await sleep_until(cutoff - timedelta(minutes=15))
        try:
            if not (ROOT / f"{day}.json").exists():
                prepared = await asyncio.to_thread(prepare, day)
                if prepared:
                    await sleep_until(cutoff)
                    await asyncio.to_thread(collect, day, prepared)
        except Exception:
            log.exception("Pre-market archive failed for %s", day)
        # No late catch-up can be called contemporaneous.
        await sleep_until(cutoff + timedelta(minutes=1))
