"""Radar PR 1: one Tradier quote pass a minute over the tracked symbol list.

Off unless ``RADAR_ENABLED`` is true and ``RADAR_STORE`` is an absolute path,
and off when Tradier is not configured. A pass runs only inside the regular
session of ``ChartCalendar.hours`` (holidays and early closes included); when
the calendar is unavailable during clock hours the pass is recorded as skipped
rather than guessed. Symbols go out in requests of at most ``BATCH_SIZE``
through ``tradier.get_quotes_once``, at most ``MAX_REQUESTS`` per pass. A rate
limit or transport failure ends the pass at once (recorded failed or partial);
the next minute tries again. Nothing is retried within a pass, sent or traded
here. After an ok or partial pass, ``radar_rules.detect`` appends new events and
revisions (step 2) under the rule version ``RADAR_RULES_VERSION`` selects (v0 by default), then ``radar_news.enrich`` checks headlines near recent
events (PR 5), so a new event gets its news the same minute. With
``RADAR_ALERTS_ENABLED`` the new events also go to the phone through
``radar_alerts`` (off by default). None of these failures affects the recorded pass. Outside the regular session an optional
``radar_premarket`` scanner (off unless ``RADAR_PREMARKET_ENABLED``) records its
own pre-open lists in a separate file.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
import logging
import os
import time
from typing import Callable

from app.engine import radar_alerts, radar_news, radar_premarket, radar_rules, tradier
from app.engine.chart_math import ET, REGULAR_CLOSE, REGULAR_OPEN, session_windows
from app.engine.radar_store import RadarEvent, RadarEventRevision, RadarPass, RadarQuote, RadarStore, load_universe

log = logging.getLogger(__name__)

PASS_SECONDS = 60
BATCH_SIZE = 50
MAX_REQUESTS = 6


def enabled() -> bool:
    return os.environ.get("RADAR_ENABLED", "false").lower() in ("1", "true", "yes")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _raw_float(raw: dict | None, key: str) -> float | None:
    return tradier._f((raw or {}).get(key))


class RadarRunner:
    def __init__(self, store: RadarStore, calendar, *, universe: dict | None = None,
                 quotes: Callable[[list[str]], dict] = tradier.get_quotes_once,
                 clock: Callable[[], float] = time.time, news: radar_news.NewsReader = radar_news.fetch,
                 premarket: radar_premarket.PremarketScanner | None = None, alerts: radar_alerts.RadarAlerts | None = None,
                 rules: radar_rules.Thresholds = radar_rules.V0):
        self.store = store
        self.calendar = calendar
        self.universe = universe or load_universe()
        self.symbols = [row["symbol"] for row in self.universe["symbols"]]
        self.quotes = quotes
        self.clock = clock
        self.news = news
        self.premarket = premarket
        self.alerts = alerts  # phone pings for new events; None keeps Radar silent
        self.rules = rules
        self._pruned_for: date | None = None

    def _regular(self, today: date, minute: int) -> tuple[bool, str | None]:
        """(inside the regular session, skip reason to record or None)."""
        hours = self.calendar.hours(today)
        self._session_hours = hours
        if hours is None:
            # Clock hours cannot see holidays or early closes, so record the gap instead of guessing.
            clock_hours = today.weekday() < 5 and REGULAR_OPEN <= minute < REGULAR_CLOSE
            return False, "calendar_unavailable" if clock_hours else None
        regular = next((w for w in session_windows(today, hours) if w[0] == "regular"), None)
        return regular is not None and regular[1] <= minute < regular[2], None

    def run_once(self) -> int | None:
        """Record one pass when the regular session is open; returns the pass id, or None outside hours."""
        started = datetime.fromtimestamp(self.clock(), ET)
        today, minute = started.date(), started.hour * 60 + started.minute
        inside, skip = self._regular(today, minute)
        if not inside and skip is None:
            if self.premarket is not None:
                try:
                    self.premarket.run_once()
                except Exception:  # the pilot is extra; it never stops the recorder
                    log.exception("Radar premarket scan failed")
            return None
        record: RadarPass = {"session_date": today.isoformat(), "started_at": _iso(started), "finished_at": "",
                             "universe_version": self.universe["version"], "status": "skipped",
                             "symbols_requested": 0, "symbols_returned": 0, "unmatched": [], "requests_used": 0,
                             "error": None, "skip_reason": skip}
        rows: list[RadarQuote] = []
        if inside:
            if self._pruned_for != today:
                self.store.prune_quotes()
                self._pruned_for = today
            rows = self._collect(record)
        record["finished_at"] = _iso(datetime.fromtimestamp(self.clock(), ET))
        pass_id = self.store.append_pass(record, rows)
        new_events: list[RadarEvent] = []
        detection_status = "skipped"
        if inside and record["status"] in radar_rules.USABLE:
            try:
                new_events, _ = self.detect(record["session_date"], pass_id)
                detection_status = "ok"
            except Exception:  # detection is extra; the recorded pass stands either way
                detection_status = "failed"
                log.exception("Radar detection failed")
        try:
            self.store.append_detection(pass_id, universe=self.universe, rules=asdict(self.rules),
                                        hours=self._session_hours, status=detection_status,
                                        event_ids=[e["event_id"] for e in new_events],
                                        recorded_at=_iso(datetime.fromtimestamp(self.clock(), UTC)), origin="live")
        except Exception:
            # Keep collection/alerts running, but the scorer cannot certify this pass.
            log.exception("Radar detection receipt failed")
        if inside and self.alerts is not None:
            try:
                if new_events:
                    self.alerts.record(new_events)
                self.alerts.deliver()
            except Exception:  # a phone ping is extra; the recorded pass and its events stand either way
                log.exception("Radar alerts failed")
        if inside:
            try:
                radar_news.enrich(self.store, record["session_date"], datetime.fromtimestamp(self.clock(), UTC), self.news)
            except Exception:  # news is extra context; the recorded pass stands either way
                log.exception("Radar news enrichment failed")
        return pass_id

    def detect(self, session_date: str, pass_id: int) -> tuple[list[RadarEvent], list[RadarEventRevision]]:
        """Append the rules' new events and revisions for one recorded pass; returns the rows written.

        Reads the session's pass list, the quotes of only the passes the windows need, and the session's saved
        events of this rule version. Rows already saved (same ids) are skipped, so a restart writes nothing twice.
        """
        passes = radar_rules.session_passes(self.store.passes(session_date), session_date)
        end = next((i for i, p in enumerate(passes) if p["id"] == pass_id), None)
        if end is None:
            return [], []
        quotes = self.store.pass_quotes(radar_rules.needed_pass_ids(passes, end, self.rules))
        saved = [(e, self.store.revisions(e["event_id"])) for e in self.store.events(session_date)
                 if e["rule_version"] == self.rules.version]
        events, revisions = radar_rules.detect(self.universe, passes, end, quotes, saved, self.rules)
        written_events, written_revisions = [], []
        for event in events:
            if self.store.event(event["event_id"]) is None:
                self.store.append_event(event)
                written_events.append(event)
        for revision in revisions:
            if len(self.store.revisions(revision["event_id"])) < revision["revision"]:
                self.store.append_revision(revision)
                written_revisions.append(revision)
        return written_events, written_revisions

    def _collect(self, record: RadarPass) -> list[RadarQuote]:
        batches = [self.symbols[i:i + BATCH_SIZE] for i in range(0, len(self.symbols), BATCH_SIZE)]
        errors = []
        if len(batches) > MAX_REQUESTS:
            left = sum(len(b) for b in batches[MAX_REQUESTS:])
            errors.append(f"request cap {MAX_REQUESTS}: {left} symbols not requested")
            batches = batches[:MAX_REQUESTS]
        rows: list[RadarQuote] = []
        unmatched: list[str] = []
        failed = False
        for batch in batches:
            record["requests_used"] += 1
            record["symbols_requested"] += len(batch)
            try:
                found = self.quotes(batch)
            except Exception as exc:  # a 429 or transport error ends the pass; the next minute tries again
                errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
                failed = True
                break
            retrieved = _iso(datetime.fromtimestamp(self.clock(), ET))
            for symbol in batch:
                quote = found.get(symbol)
                if quote is None:
                    unmatched.append(symbol)
                    continue
                rows.append({"symbol": symbol, "last": quote.last, "prev_close": _raw_float(quote.raw, "prevclose"),
                             "open": _raw_float(quote.raw, "open"), "high": _raw_float(quote.raw, "high"),
                             "low": _raw_float(quote.raw, "low"), "volume": quote.volume, "bid": quote.bid,
                             "ask": quote.ask, "trade_time_ms": quote.trade_date, "retrieved_at": retrieved})
        record["symbols_returned"] = len(rows)
        record["unmatched"] = unmatched
        record["error"] = "; ".join(errors) or None
        if failed:
            record["status"] = "partial" if rows else "failed"
        else:
            record["status"] = "partial" if errors else "ok"
        return rows


def runner_from_env() -> RadarRunner | None:
    if not enabled():
        return None
    store = os.environ.get("RADAR_STORE", "").strip()
    if not store or not os.path.isabs(store):
        log.error("RADAR_ENABLED needs an absolute RADAR_STORE; Radar stays off")
        return None
    if not tradier.tradier_configured():
        log.error("RADAR_ENABLED needs TRADIER_API_KEY; Radar stays off")
        return None
    from app.engine.chart_calendar import chart_calendar
    universe = load_universe()
    runner = RadarRunner(RadarStore(store), chart_calendar, universe=universe, rules=radar_rules.from_env())
    if radar_alerts.enabled():
        from app.database import engine
        runner.alerts = radar_alerts.RadarAlerts(engine, store=runner.store)
    try:
        runner.premarket = radar_premarket.scanner_from_env(store, chart_calendar, universe)
    except Exception:  # an unusable pilot file must not turn the recorder off
        log.exception("Radar premarket pilot could not start; it stays off")
    return runner
