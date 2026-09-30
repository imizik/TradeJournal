"""Completed New York chart sessions from explicitly requested Alpaca SIP minutes.

This cache belongs to Charts. It never reads the journal's Alpaca caches or
changes the journal feed setting. A completed file is immutable until an
operator deliberately removes it.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time as wall_time, timedelta, timezone
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.engine import alpaca
from app.engine.chart_calendar import ChartCalendar, chart_calendar
from app.engine.chart_math import CLOCK_NOTE, ET, chart_bars, indicators, normalize_bars

FLOOR = date(2016, 1, 1)
SCHEMA = 1
WARMUP = 1400
PAGE = 1200
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "chart_history" / "v1" / "stocks" / "1Min" / "sip" / "raw"


class HistoryError(Exception):
    def __init__(self, message: str, code: str = "history_unavailable", retry_at: int | None = None):
        super().__init__(message)
        self.code, self.retry_at = code, retry_at


@dataclass
class Work:
    identity: tuple[str, str, str, int, int]
    day: date
    bars: list[dict] = field(default_factory=list)
    token: str | None = None
    candidate: list[dict] = field(default_factory=list)
    touched: float = field(default_factory=time.monotonic)
    clock_days: set[date] = field(default_factory=set)  # sessions resampled without the calendar


class ChartHistory:
    def __init__(self, root: Path = CACHE_DIR, calendar: ChartCalendar | None = None):
        self.root = root
        self.calendar = calendar  # None: clock hours, disclosed on every page
        self._lock = threading.RLock()  # history-only; never held by Tradier reads
        self._calls: deque[float] = deque()
        self._cooldown = 0.0
        self._work: dict[str, Work] = {}

    def _path(self, symbol: str, day: date) -> Path:
        if not SYMBOL.fullmatch(symbol):
            raise HistoryError("Invalid chart symbol.", "invalid_request")
        # Tickers may contain '/', but a ticker must remain one path segment.
        return self.root / quote(symbol, safe="") / f"{day.isoformat()}.json"

    @staticmethod
    def _bounds(day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, wall_time(4), ET).astimezone(timezone.utc)
        end = datetime.combine(day, wall_time(20), ET).astimezone(timezone.utc)
        return start, end

    def _cached(self, symbol: str, day: date) -> list[dict] | None:
        path = self._path(symbol, day)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            start, end = self._bounds(day)
            required = {"schema": SCHEMA, "symbol": symbol, "date": day.isoformat(),
                        "provider": "alpaca", "feed": "sip", "adjustment": "raw",
                        "window_start": start.isoformat(), "window_end": end.isoformat(), "complete": True}
            if not isinstance(data, dict) or any(data.get(k) != v for k, v in required.items()) or not isinstance(data.get("fetched_at"), int) or not isinstance(data.get("minutes"), list):
                raise ValueError("metadata")
            rows = data["minutes"]
            if any(not isinstance(b, dict) or b.get("source") != "alpaca_sip" or not start.timestamp() <= b.get("time", -1) < end.timestamp() for b in rows):
                raise ValueError("minutes")
            if [b["time"] for b in rows] != sorted(set(b["time"] for b in rows)):
                raise ValueError("order")
            # Check OHLCV again; a parseable but edited cache is not trusted.
            check = normalize_bars([{"timestamp": b["time"], **{k: b[k] for k in ("open", "high", "low", "close", "volume")}} for b in rows], source="alpaca_sip")
            if len(check) != len(rows) or any(a != b for a, b in zip(check, rows)):
                raise ValueError("OHLCV")
            return rows
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
            raise HistoryError(f"Completed chart cache is invalid for {symbol} {day}; deliberate repair is required.", "cache_invalid") from exc

    def _publish(self, symbol: str, day: date, minutes: list[dict]) -> None:
        path = self._path(symbol, day)
        start, end = self._bounds(day)
        record = {"schema": SCHEMA, "symbol": symbol, "date": day.isoformat(),
                  "provider": "alpaca", "feed": "sip", "adjustment": "raw",
                  "window_start": start.isoformat(), "window_end": end.isoformat(),
                  "fetched_at": int(time.time()), "complete": True, "minutes": minutes}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(record, separators=(",", ":")))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _attempt(self, symbol: str, day: date, token: str | None, deadline: float, attempts: list[int]) -> dict:
        now = time.monotonic()
        while self._calls and self._calls[0] <= now - 60:
            self._calls.popleft()
        if now < self._cooldown or len(self._calls) >= 30:
            retry = self._cooldown if now < self._cooldown else self._calls[0] + 60
            raise HistoryError("Alpaca chart history is cooling down.", "rate_limited", int(time.time() + max(1, retry - now)))
        if attempts[0] >= 8 or deadline - now < 0.05:
            raise HistoryError("History is still loading.", "pending", int(time.time() + 1))
        if not alpaca.ALPACA_API_KEY or not alpaca.ALPACA_API_SECRET:
            raise HistoryError("Alpaca historical SIP credentials are not configured.", "not_configured")
        start, end = self._bounds(day)
        # Even at NY midnight, never ask for the restricted latest 15 minutes.
        if day >= datetime.now(ET).date():
            raise HistoryError("Only completed New York sessions are historical.", "invalid_request")
        safe_at = end + timedelta(minutes=15)
        if safe_at > datetime.now(timezone.utc):
            raise HistoryError("Completed-session SIP data is not yet safe to request.", "pending", int(safe_at.timestamp()) + 1)
        params = {"timeframe": "1Min", "start": start.isoformat(), "end": end.isoformat(),
                  "limit": 10000, "feed": "sip", "adjustment": "raw"}
        if token:
            params["page_token"] = token
        attempts[0] += 1
        self._calls.append(now)
        try:
            response = httpx.get(f"{alpaca.DATA_URL}/v2/stocks/{quote(symbol, safe='')}/bars", params=params,
                                 headers={"APCA-API-KEY-ID": alpaca.ALPACA_API_KEY,
                                          "APCA-API-SECRET-KEY": alpaca.ALPACA_API_SECRET},
                                 timeout=max(0.05, min(10, deadline - now)))
        except httpx.HTTPError as exc:
            raise HistoryError("Alpaca history connection failed; retry this page.") from exc
        if response.status_code == 429:
            value = response.headers.get("Retry-After", "60")
            try:
                delay = max(1, min(300, int(value)))
            except ValueError:
                delay = 60
            self._cooldown = time.monotonic() + delay
            raise HistoryError("Alpaca history allowance is cooling down.", "rate_limited", int(time.time() + delay))
        if response.status_code in (401, 403):
            raise HistoryError("Alpaca refused historical SIP access.", "access_denied")
        if response.status_code >= 400:
            raise HistoryError("Alpaca history request failed; retry this page.")
        try:
            body = response.json()
        except ValueError as exc:
            raise HistoryError("Alpaca returned malformed history data.", "malformed") from exc
        if not isinstance(body, dict) or not isinstance(body.get("bars"), list) or (body.get("next_page_token") is not None and not isinstance(body["next_page_token"], str)):
            raise HistoryError("Alpaca returned malformed history data.", "malformed")
        return body

    def _session(self, symbol: str, day: date, work: Work, deadline: float, attempts: list[int]) -> list[dict]:
        cached = self._cached(symbol, day)
        if cached is not None:
            return cached
        start, end = self._bounds(day)
        while True:
            body = self._attempt(symbol, day, work.token, deadline, attempts)
            rows = []
            for raw in body["bars"]:
                if not isinstance(raw, dict):
                    raise HistoryError("Alpaca returned malformed history data.", "malformed")
                try:
                    stamp = int(datetime.fromisoformat(raw["t"].replace("Z", "+00:00")).timestamp())
                    row = {"timestamp": stamp, "open": raw["o"], "high": raw["h"], "low": raw["l"], "close": raw["c"], "volume": raw["v"]}
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    raise HistoryError("Alpaca returned malformed history data.", "malformed") from exc
                if start.timestamp() <= stamp < end.timestamp():
                    rows.append(row)
            normalized = normalize_bars(rows, source="alpaca_sip")
            if len(normalized) != len(rows):
                raise HistoryError("Alpaca returned malformed history data.", "malformed")
            work.candidate.extend(normalized)
            next_token = body.get("next_page_token") or None
            if next_token and next_token == work.token:
                raise HistoryError("Alpaca returned a repeating page token.", "malformed")
            work.token = next_token
            if not next_token:
                minutes = sorted({b["time"]: b for b in work.candidate}.values(), key=lambda b: b["time"])
                self._publish(symbol, day, minutes)
                work.candidate = []
                return minutes

    def page(self, symbol: str, interval: str, session: str, before: int, limit: int = PAGE,
             continuation: str | None = None) -> dict:
        if not SYMBOL.fullmatch(symbol) or interval not in ("1m", "3m", "5m", "15m", "30m", "1h", "4h") or session not in ("regular", "extended") or limit < 1 or limit > PAGE or before <= 0 or before > time.time() + 60:
            raise HistoryError("Invalid chart history request.", "invalid_request")
        identity = (symbol, interval, session, before, limit)
        with self._lock:
            now = time.monotonic()
            self._work = {k: v for k, v in self._work.items() if now - v.touched < 600}
            if len(self._work) > 64:
                oldest = min(self._work, key=lambda item: self._work[item].touched)
                self._work.pop(oldest)
            if continuation:
                work = self._work.get(continuation)
                if work is None or work.identity != identity:
                    raise HistoryError("History continuation expired or does not match this chart.", "invalid_request")
                key = continuation
            else:
                day = min(datetime.fromtimestamp(before, ET).date(), datetime.now(ET).date() - timedelta(days=1))
                work = Work(identity, day)
                key = uuid4().hex
                self._work[key] = work
            work.touched = now
            deadline = now + 10
            attempts = [0]
            issue: dict | None = None
            try:
                while work.day >= FLOOR and sum(b["time"] < before for b in work.bars) < limit + WARMUP:
                    if time.monotonic() >= deadline:
                        raise HistoryError("History is still loading.", "pending", int(time.time() + 1))
                    hours = self.calendar.hours(work.day) if self.calendar and work.day.weekday() < 5 else None
                    if work.day.weekday() >= 5 or (hours is not None and hours["status"] == "closed"):
                        work.day -= timedelta(days=1)  # holidays cost no Alpaca request
                        continue
                    if hours is None:
                        work.clock_days.add(work.day)
                    minutes = self._session(symbol, work.day, work, deadline, attempts)
                    # Each session resamples with its own date's hours (half days end at 13:00).
                    day_bars = [b for b in chart_bars(minutes, [], interval, session, {work.day: hours}) if b["time"] < before]
                    # Full-day resampling supplies VWAP and complete buckets.
                    work.bars = (day_bars + work.bars)[-(limit + WARMUP):]
                    work.day -= timedelta(days=1)
                    work.token = None
            except HistoryError as exc:
                if exc.code == "invalid_request" or exc.code == "cache_invalid":
                    self._work.pop(key, None)
                    raise
                if exc.code != "pending":
                    # Failed candidates never become complete files or reusable work.
                    work.candidate, work.token = [], None
                issue = {"code": exc.code, "message": str(exc), "retry_at": exc.retry_at or int(time.time() + 15)}
            exhausted = work.day < FLOOR
            eligible = [b for b in work.bars if b["time"] < before]
            visible = eligible[-limit:]
            prefix = eligible[:max(0, len(eligible) - len(visible))]
            warmed = len(prefix) >= WARMUP
            ready = (warmed and len(eligible) >= limit) or exhausted
            if ready:
                computed = indicators((prefix + visible)[- (WARMUP + limit):])
                visible = computed[-len(visible):] if visible else []
                if not warmed:
                    visible = [{**b, **{f"ema{n}": None for n in (9, 20, 50, 200)}, "rsi": None} for b in visible]
            else:
                visible = [{**b, **{f"ema{n}": None for n in (9, 20, 50, 200)}, "rsi": None} for b in visible]
            pending = not ready and issue is None
            if pending:
                issue = {"code": "pending", "message": "Indicator warmup is still loading.", "retry_at": int(time.time() + 1)}
            if ready:
                self._work.pop(key, None)
            shown = {datetime.fromtimestamp(b["time"], ET).date() for b in visible}
            return {"symbol": symbol, "interval": interval, "session": session, "before": before,
                    "limit": limit, "bars": visible, "older_cursor": visible[0]["time"] if visible else (int(datetime.combine(work.day, wall_time(20), ET).timestamp()) if not exhausted else None),
                    "exhausted": exhausted and len(eligible) <= limit, "continuation": None if ready else key,
                    "warmup": "ready" if warmed else "insufficient" if exhausted else "pending",
                    "source": "alpaca_sip", "price_basis": "raw", "issue": issue,
                    "calendar_note": CLOCK_NOTE if shown & work.clock_days else None}


chart_history = ChartHistory(calendar=chart_calendar)
