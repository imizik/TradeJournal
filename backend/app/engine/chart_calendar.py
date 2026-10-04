"""Tradier market calendar for chart sessions: holidays and early closes.

Tradier field names stop here. Callers receive normalized New York days:
{"date", "status": "open"|"closed", "open", "close" (minutes of day, or None
when closed), "description", "source"}. A completed month is immutable and
kept on disk, so it costs one provider call per deployment. The current month
is refetched once per New York date. Reads go through the chart feed and share
its Tradier budget, lock and cooldowns. When no calendar is available the
caller falls back to clock hours and discloses it (`chart_math.CLOCK_NOTE`).
"""

from calendar import monthrange
from datetime import date, datetime
import json
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from app.engine.chart_feed import ChartFeed, ChartFeedError, chart_feed
from app.engine.chart_math import ET, EXTENDED_END, PRE_START

SCHEMA = 1
RETRY_SECONDS = 60
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "chart_calendar" / "v1" / "tradier"
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

Month = tuple[int, int]


def _minutes(value) -> int:
    match = _CLOCK.fullmatch(str(value))
    if not match:
        raise ValueError("calendar time")
    return int(match[1]) * 60 + int(match[2])


def _normalized(day: date, status, start, end, description, key: Month) -> dict:
    if (day.year, day.month) != key or not isinstance(description, str):
        raise ValueError("calendar day")
    if status == "closed" and start is None and end is None:
        return {"date": day.isoformat(), "status": "closed", "open": None, "close": None, "description": description[:120], "source": "tradier"}
    if status != "open" or type(start) is not int or type(end) is not int or not PRE_START <= start < end <= EXTENDED_END:
        raise ValueError("calendar hours")
    return {"date": day.isoformat(), "status": "open", "open": start, "close": end, "description": description[:120], "source": "tradier"}


def _day(row: dict, key: Month) -> dict:
    hours = row.get("open") if row.get("status") == "open" else None
    start, end = (_minutes(hours["start"]), _minutes(hours["end"])) if hours is not None else (None, None)
    return _normalized(date.fromisoformat(str(row["date"])), row.get("status"), start, end, str(row.get("description") or ""), key)


def parse_month(payload, year: int, month: int) -> dict[date, dict]:
    """Normalize one Tradier calendar month; anything incomplete is unavailable."""
    try:
        rows = payload["calendar"]["days"]["day"]
        rows = [rows] if isinstance(rows, dict) else rows
        days = {}
        for row in rows:
            item = _day(row, (year, month))
            days[date.fromisoformat(item["date"])] = item
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("malformed calendar") from exc
    if len(days) != monthrange(year, month)[1]:
        raise ValueError("incomplete calendar month")
    return days


def _month_end(key: Month) -> date:
    return date(key[0], key[1], monthrange(*key)[1])


class ChartCalendar:
    def __init__(self, root: Path = CACHE_DIR, feed: ChartFeed | None = None):
        self.root = root
        self.feed = feed or chart_feed
        self._lock = threading.Lock()
        self._months: dict[Month, tuple[date, dict[date, dict]]] = {}  # (fetched on, days)
        self._retry: dict[Month, float] = {}

    def cached(self, day: date) -> dict | None:
        """Memory only: never touches the provider or disk, so it is safe on the event loop."""
        with self._lock:
            entry = self._months.get((day.year, day.month))
        return entry[1].get(day) if entry else None

    def hours(self, day: date) -> dict | None:
        """The normalized day, or None when the calendar is unavailable."""
        key = (day.year, day.month)
        today = datetime.now(ET).date()
        if key > (today.year, today.month):
            return None  # Tradier rejects unpublished years; no caller needs future months.
        with self._lock:
            entry = self._months.get(key)
        if entry is None:
            entry = self._load(key)
        # A month is final once fetched after it ended; the current one is
        # refetched each New York date so newly announced closures appear.
        if entry is not None and (entry[0] > _month_end(key) or entry[0] == today):
            return entry[1].get(day)
        with self._lock:
            if time.monotonic() < self._retry.get(key, 0):
                return entry[1].get(day) if entry else None
        try:
            payload, _, issue = self.feed.read("/v1/markets/calendar", {"month": key[1], "year": key[0]}, 60)
            if issue:
                raise ChartFeedError(issue)
            days = parse_month(payload, *key)
        except (ChartFeedError, ValueError):
            with self._lock:
                self._retry[key] = time.monotonic() + RETRY_SECONDS
            # Yesterday's copy of this month is still the best available answer.
            return entry[1].get(day) if entry else None
        with self._lock:
            self._months[key] = (today, days)
            self._retry.pop(key, None)
        if today > _month_end(key):
            self._publish(key, days, today)
        return days.get(day)

    def _path(self, key: Month) -> Path:
        return self.root / f"{key[0]:04d}-{key[1]:02d}.json"

    def _load(self, key: Month) -> tuple[date, dict[date, dict]] | None:
        path = self._path(key)
        try:
            data = json.loads(path.read_text())
            fetched = date.fromisoformat(data["fetched_on"])
            if data.get("schema") != SCHEMA or data.get("provider") != "tradier" or fetched <= _month_end(key):
                raise ValueError("metadata")
            days = {}
            for item in data["days"]:
                day = date.fromisoformat(item["date"])
                days[day] = _normalized(day, item["status"], item["open"], item["close"], item["description"], key)
            if len(days) != monthrange(*key)[1]:
                raise ValueError("incomplete")
        except FileNotFoundError:
            return None
        except (OSError, KeyError, TypeError, ValueError):
            return None  # A damaged calendar copy is refetched and replaced.
        with self._lock:
            self._months[key] = (fetched, days)
        return fetched, days

    def _publish(self, key: Month, days: dict[date, dict], fetched: date) -> None:
        path = self._path(key)
        record = {"schema": SCHEMA, "provider": "tradier", "month": f"{key[0]:04d}-{key[1]:02d}",
                  "fetched_on": fetched.isoformat(), "days": [days[d] for d in sorted(days)]}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(json.dumps(record, separators=(",", ":")))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass  # Memory still holds the month; the next restart refetches it.


chart_calendar = ChartCalendar()
