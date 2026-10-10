"""Invented provider-shaped historical browser data. Never shipped to the VPS."""
from datetime import datetime, timedelta, timezone
import uuid

from sqlmodel import select

from app.engine import historical_replay
from app.engine.chart_math import ET
from app.models import PracticeRun

IDENTIFIER = "historical-browser-" + uuid.uuid4().hex[:10]


def bundle():
    day = datetime.now(ET).date() - timedelta(days=4)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    following = day + timedelta(days=1)
    while following.weekday() >= 5:
        following += timedelta(days=1)
    cutoff = datetime.combine(day, datetime.min.time(), ET) + timedelta(hours=13, minutes=45)
    packets = {}
    for symbol, base in (("MU", 110), ("NBIS", 60)):
        bars = [{"t": (cutoff-timedelta(minutes=i+1)).isoformat(), "o": base, "h": base+4, "l": base-1,
            "c": base, "v": 100+i, "vw": base-.1} for i in range(60)]
        for i in range(135):
            bars.append({"t": (cutoff+timedelta(minutes=i)).isoformat(), "o": base+.2,
                "h": base+.4 if i != 17 else base+4.2, "l": base+.1, "c": base+.25, "v": 150, "vw": base+.2})
        next_open = datetime.combine(following, datetime.min.time(), ET) + timedelta(hours=9, minutes=30)
        bars.extend({"t": (next_open+timedelta(minutes=i)).isoformat(), "o": base+.2, "h": base+.4,
            "l": base+.1, "c": base+.25, "v": 100, "vw": base+.2} for i in range(390))
        packets[symbol] = {"symbol": symbol, "data_source": "alpaca_iex",
            "missing": ["Invented browser/test fixture, not a real provider observation"],
            "recent_minute_bars": sorted(bars, key=lambda b: b["t"], reverse=True)}
    return {"version": 1, "captured_at": datetime.now(timezone.utc).isoformat(), "simulated_as_of": cutoff.isoformat(),
        "sessions": [{"day": d.isoformat(), "open": 570, "close": 960, "source": "alpaca_calendar"} for d in (day, following)],
        "packets": packets}


def prepare(db):
    previous = db.exec(select(PracticeRun).where(PracticeRun.session_key.startswith(historical_replay.PREFIX))
        .order_by(PracticeRun.created_at.desc())).all()
    for run in previous:
        if historical_replay.eligible(run) and historical_replay.market_practice.visible_to(run, IDENTIFIER):
            return run
    return historical_replay.prepare(db, bundle(), identifier=IDENTIFIER, proof=True)


def prepare_expiry_cases(db):
    for zone in ("la", "ny", "utc"):
        historical_replay.prepare(db, bundle(),
            identifier=IDENTIFIER.replace("historical-browser-", "historical-expiry-") + "-" + zone, proof=True)
