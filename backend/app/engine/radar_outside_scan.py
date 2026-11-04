"""Four optional SIP checkpoints. Kept outside the Radar recorder and its alert pipeline."""
import asyncio
from datetime import date, datetime, time, timedelta
import logging
import os
from pathlib import Path

import httpx

from app.ai.copilot_breadth import members
from app.engine.premarket_archive import ET, Market, positive, timestamp
from app.engine.premarket_archive_job import now, sleep_until
from app.engine.radar_store import load_universe
from app.engine.radar_whole_market import LOOKBACK, MIN_PRICE, daily_inputs, sessions
from app.engine.scalp_shortlist_store import publish_once, read_record

CHECKPOINTS = (time(9, 45), time(10, 30), time(12), time(14))
ROOT = Path(__file__).resolve().parents[2] / "data" / "radar_outside_list"
log = logging.getLogger(__name__)


def enabled():
    return os.getenv("RADAR_WHOLE_MARKET_ENABLED", "").lower() == "true" and os.getenv("TJ_DOT_TRIAL_ENABLED") != "true"


def archive_path(slot):
    return ROOT / slot.date().isoformat() / f"{slot:%H%M}.json"


def feed_sessions():
    return sorted((p.name for p in ROOT.glob("????-??-??") if p.is_dir()), reverse=True)[:30]


def checkpoints(session):
    day = date.fromisoformat(session)
    records = []
    for t in reversed(CHECKPOINTS):
        slot = datetime.combine(day, t, ET)
        try:
            record = read_record(archive_path(slot))
        except (OSError, ValueError):
            record = dict(as_of=slot.isoformat(), status="unavailable", rows=[])
        if record is not None:
            records.append(record)
    return records


def prepare(day):
    with httpx.Client(timeout=30) as client:
        market = Market(client, os.environ)
        calendar = sessions(market, day - timedelta(days=45), day)
        if day not in calendar:
            return None
        adv, previous, _ = daily_inputs(market, day, list(calendar)[:-1][-LOOKBACK:])
    tracked = {r["symbol"] for r in load_universe()["symbols"]}
    outside = {s: avg for s, avg in adv.items() if s not in tracked and s != "SPY"}
    if not outside:
        raise ValueError("No liquid outside-list stocks")
    return calendar[day], outside, previous, members()[0]


def rank(slot, snapshots, outside, previous, sectors):
    # Use the same completed minute for SPY and every ranked name. The snapshot's
    # daily bar provides session dollar volume as observed during the checkpoint.
    required = slot - timedelta(minutes=1)

    def current(symbol):
        snap = snapshots.get(symbol) or {}
        minute, daily = snap.get("minuteBar"), snap.get("dailyBar")
        if not minute or not daily or timestamp(minute) != required or timestamp(daily).date() != slot.date():
            return None
        return float(positive(minute["c"])), float(positive(daily["vw"]) * positive(daily["v"]))

    spy = current("SPY")
    if spy is None:
        raise ValueError("No contemporaneous SPY snapshot")
    spy_return = (spy[0] / previous["SPY"] - 1) * 100
    rows = []
    covered = 0
    for symbol, avg in outside.items():
        reading = current(symbol)
        if reading is None:
            continue
        covered += 1
        price, dollars = reading
        relative = (price / previous[symbol] - 1) * 100 - spy_return
        if price >= MIN_PRICE and abs(round(relative, 8)) >= 4.5:
            rows.append(dict(kind="outside_list", symbol=symbol, price=price, move_vs_spy_pp=round(relative, 4),
                             dollar_volume=dollars, avg_dollar_volume=avg, sector=sectors.get(symbol)))
    if not covered:
        raise ValueError("No fresh outside-list snapshots")
    rows.sort(key=lambda r: (-abs(r["move_vs_spy_pp"]), r["symbol"]))
    return dict(as_of=slot.isoformat(), status="ok", covered=covered, requested=len(outside), rows=rows[:10])


def capture(slot, prepared, market, clock=now):
    path = archive_path(slot)
    if path.exists():
        return
    close, outside, previous, sectors = prepared
    deadline = slot + timedelta(minutes=1)
    if slot.time() >= close:
        return
    if not slot <= clock() < deadline:
        raise ValueError("Outside the checkpoint minute")
    snapshots = market.snapshots(sorted({*outside, "SPY"}))
    observed = clock()
    if not slot <= observed < deadline:
        raise ValueError("Snapshot pass missed the checkpoint")
    record = rank(slot, snapshots, outside, previous, sectors)
    return publish_once(path, dict(record, snapshot_finished_at=observed.isoformat()))


def collect(slot, prepared):
    with httpx.Client(timeout=25) as client:
        capture(slot, prepared, Market(client, os.environ))


async def scan_day(day):
    prepared = None
    for t in CHECKPOINTS:
        slot = datetime.combine(day, t, ET)
        if now() >= slot + timedelta(minutes=1) or archive_path(slot).exists():
            continue
        try:
            if prepared is None:
                await sleep_until(slot - timedelta(minutes=20))
                prepared = await asyncio.to_thread(prepare, day)
            if not prepared or t >= prepared[0]:
                break  # holiday or early close
            # Allow the bar that just closed to reach the batched snapshot endpoint.
            await sleep_until(slot + timedelta(seconds=5))
            await asyncio.to_thread(collect, slot, prepared)
        except Exception as exc:
            # A denied snapshot (or missing input) never becomes an empty ranking.
            log.warning("Outside-list checkpoint unavailable at %s (%s)", slot, type(exc).__name__)
            await sleep_until(slot)
            publish_once(archive_path(slot), dict(as_of=slot.isoformat(), status="unavailable", rows=[]))


async def run():
    while True:
        day = now().date()
        if day.weekday() < 5:
            try:
                await scan_day(day)
            except OSError:
                log.exception("Could not save outside-list checkpoints for %s", day)
        await sleep_until(datetime.combine(day + timedelta(days=1), time(0), ET))
