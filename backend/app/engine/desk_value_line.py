"""The desk's line of account value through the day (docs/robinhood-read-feed.md § The value line).

Built only from readings the app already takes: each healthy snapshot of the live account feed that a desk read sees is
stored once (``record``), one row per account, in ``desk_account_value``; nothing here reads the feed or any broker,
and nothing reads more often than the feed already does. Rows are kept a week, so a restart keeps the morning.

``line`` turns a session's readings into what the desk draws: per account and for all accounts together, the line in
segments, the breaks between them, the first and last value, the change since the first reading in dollars and percent,
and the day's high and low. A break is a stretch with no healthy reading (the feed off, the sign-in expired, the app
restarted, no desk open): longer than three of the feed's refreshes, or a reading without the value. A break is never
bridged by a straight line and never read as zero. "All accounts" at a reading is the sum of the accounts the latest
reading holds, only when every one of them has a value then; otherwise that reading is a break for the total.

Display only: nothing here touches fills, trades, P&L or FIFO, and no account number is stored or sent, only its label
and its last four masked (``••8267``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Callable

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine.chart_math import ET
from app.models import DeskAccountValue

log = logging.getLogger(__name__)

KEEP_DAYS = 7
MISSED_REFRESHES = 3  # a stretch longer than this many of the feed's refreshes without a reading is a break
ALL = "all"


def _round(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 2) if value == value and abs(value) != float("inf") else None


def record(bind, snapshot: dict) -> int:
    """Stores one healthy feed snapshot's account values (once per snapshot: a second desk read of the same snapshot
    stores nothing). A weekend reading is not stored. Returns the rows written."""
    at = int(snapshot["at"])
    moment = datetime.fromtimestamp(at, ET)
    if moment.weekday() >= 5:
        return 0
    rows = [DeskAccountValue(day=moment.date().isoformat(), at=at, masked=a["masked"], label=str(a.get("label") or "Account")[:40],
                             total_value=_round(a.get("total_value")))
            for a in snapshot.get("accounts") or [] if isinstance(a.get("masked"), str) and a["masked"]]
    if not rows:
        return 0
    with Session(bind) as session:
        if session.exec(select(DeskAccountValue.id).where(DeskAccountValue.at == at).limit(1)).first() is not None:
            return 0
        session.add_all(rows)
        session.exec(delete(DeskAccountValue).where(DeskAccountValue.day < (moment.date() - timedelta(days=KEEP_DAYS)).isoformat()))
        try:
            session.commit()
        except IntegrityError:  # another desk read stored this snapshot first
            session.rollback()
            return 0
    return len(rows)


def session_day(now: float) -> date:
    """The session a read's line belongs to: a weekend read shows Friday's (holidays are not rolled back)."""
    day = datetime.fromtimestamp(now, ET).date()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _series(readings: list[tuple[int, dict]], value: Callable[[dict], float | None], gap: Callable[[int, int], bool],
            now: float) -> dict | None:
    """One line: its segments of ``[at, value]``, the breaks between them, and its figures; None with no known value."""
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    for at, values in readings:
        v = value(values)
        if v is None:
            if current:
                segments.append(current)
                current = []
            continue
        if current and gap(int(current[-1][0]), at):
            segments.append(current)
            current = []
        current.append([at, v])
    if current:
        segments.append(current)
    if not segments:
        return None
    points = [p for s in segments for p in s]
    first, last = points[0], points[-1]
    change = round(last[1] - first[1], 2)
    high = max(points, key=lambda p: p[1])  # the first time it was reached
    low = min(points, key=lambda p: p[1])
    return {
        "segments": segments,
        "breaks": [{"from": int(a[-1][0]), "to": int(b[0][0])} for a, b in zip(segments, segments[1:])],
        "first": {"at": int(first[0]), "value": first[1]}, "last": {"at": int(last[0]), "value": last[1]},
        "change": change, "change_pct": round(100 * change / first[1], 2) if first[1] > 0 else None,
        "high": {"at": int(high[0]), "value": high[1]}, "low": {"at": int(low[0]), "value": low[1]},
        # The newest reading is older than the feed would allow: the line stops there, and says since when.
        "quiet_since": int(last[0]) if gap(int(last[0]), int(now)) else None,
    }


def line(db: Session, now: float, refresh_seconds: Callable[[float], float], *, open_at: int | None = None,
         close_at: int | None = None, fills: list[dict] | None = None) -> dict:
    """The session's value line as the desk draws it. ``refresh_seconds(at)``: how often the feed reads at that moment
    (a gap is judged by the slower of its two ends). ``fills``: the session's fills already in memory, as
    ``{"at", "masked", "symbol", "text"}``, drawn as dots. ``series`` is empty before the first reading."""
    day = session_day(now)
    rows = db.exec(select(DeskAccountValue).where(DeskAccountValue.day == day.isoformat())
                   .order_by(DeskAccountValue.at, DeskAccountValue.id)).all()
    readings: dict[int, dict[str, float | None]] = {}
    labels: dict[str, str] = {}
    for r in rows:
        readings.setdefault(r.at, {})[r.masked] = r.total_value
        labels[r.masked] = r.label
    ordered = sorted(readings.items())

    def gap(a: int, b: int) -> bool:
        return b - a > MISSED_REFRESHES * max(refresh_seconds(a), refresh_seconds(b))

    series: dict[str, dict] = {}
    if ordered:
        latest = [m for m, _v in sorted(ordered[-1][1].items())]  # the accounts the latest reading holds
        for masked in latest:
            found = _series(ordered, lambda values, m=masked: values.get(m), gap, now)
            if found is not None:
                series[masked] = {"label": labels[masked], **found}

        def total(values: dict) -> float | None:
            parts = [values.get(m) for m in latest]
            return None if None in parts else round(sum(parts), 2)

        found = _series(ordered, total, gap, now)
        if found is not None:
            series[ALL] = {"label": "All accounts", **found}
    return {"day": day.isoformat(), "open": open_at, "close": close_at, "series": series,
            "fills": sorted(fills or [], key=lambda f: f["at"])}
