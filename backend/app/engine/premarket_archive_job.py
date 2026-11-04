"""Prepare the dated roster before 09:00, then capture exactly one SIP snapshot pass."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import logging
import os

import httpx

from app.engine.premarket_archive import ET, ROOT, Market, at, inputs, rank_inputs, read_minutes, save

log = logging.getLogger(__name__)


def now():
    return datetime.now(ET)


def prepare(day):
    with httpx.Client(timeout=30) as client:
        market = Market(client, os.environ)
        days = market.calendar(day - timedelta(days=14), day)
        if days[-1] == day:
            symbols = market.symbols(day)
            # Finish historical setup ahead of the time-critical 09:00 batch.
            through = at(day, 9) - timedelta(minutes=16)
            closes, totals = inputs(market, day, days[-2], symbols, through)
            return symbols, closes, totals
    return None


def capture(day, symbols, closes, totals, market, root, clock=now):
    cutoff = at(day, 9)
    deadline = cutoff + timedelta(minutes=1)
    started = clock()
    if not cutoff <= started < deadline or (root / f"{day}.json").exists():
        return
    # Both independent read passes start at the checkpoint. The warmed-up
    # minute accumulator contains only 04:00..08:44. Never accept a late floor.
    with ThreadPoolExecutor(max_workers=1) as pool:
        tail = pool.submit(read_minutes, market, symbols, cutoff - timedelta(minutes=15),
                           cutoff - timedelta(minutes=1), totals)
        snapshots = market.snapshots(symbols)
        snapshot_end = clock()
        tail.result()
    observed = clock()
    if observed >= deadline:
        raise ValueError("09:00 market-data window expired")
    record = rank_inputs(day, symbols, closes, totals, snapshots)
    record.update(snapshot_started_at=started.isoformat(), snapshot_finished_at=snapshot_end.isoformat(),
                  inputs_finished_at=observed.isoformat(), saved_at=clock().isoformat())
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
            if now() < cutoff and not (ROOT / f"{day}.json").exists():
                prepared = await asyncio.to_thread(prepare, day)
                if prepared:
                    await sleep_until(cutoff)
                    await asyncio.to_thread(collect, day, prepared)
        except Exception:
            log.exception("Pre-market archive failed for %s", day)
        # No late catch-up can be called contemporaneous.
        await sleep_until(cutoff + timedelta(minutes=1))
