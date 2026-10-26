"""Thesis watch (docs/copilot-lab.md § Thesis watch): when new information touches something the owner has a thesis
on, tell him once and offer the re-check.

Off unless ``THESIS_WATCH_ENABLED=true``. Runs as its own task in the API process (``app/main.py``), ticking every
minute and passing every ``PASS_MINUTES`` inside the regular session plus once at ``MORNING_HOUR`` New York on a
trading day. The watched set is the symbols with an active thesis memory, the open copilot investigations' symbols
and the open positions (Webull left out, as the book does), held symbols first, at most ``MAX_SYMBOLS``.

A pass makes one batched news read and one batched quote read for that set, and reads earnings from the events cache
only; nothing here is a market read the app does not already do. Three triggers:

- ``news``: a new eligible headline (``eligible_headlines``) for the symbol since the last pass, deduped by URL;
- ``move``: ``THESIS_WATCH_MOVE_PCT`` (default 4) or more since the open investigation's latest evidence as-of
  (its day's cached minute bars; the prior close when that day is not cached), or since the prior close for a thesis
  with no investigation;
- ``earnings``: the next report inside two trading days.

A trigger is written once per dedupe key, so a restart never fires it twice; a skipped one is keyed to its day, so
the same signal can still be told on a later day. One ping per symbol per day and ``THESIS_WATCH_DAILY_CAP``
(default 4) a day; the rest are recorded ``skipped``. Right before the send, the app's notification policy
(``notification_policy.decide``, kind ``thesis_watch``, anchored to the symbol's open position or the symbol) may
hold it: the shared daily cap or the quiet window after a ping for the same position. A held trigger is recorded
``held`` with the reason, keyed to its day as a skipped one is, and counts toward neither limit. The ping opens the investigation with
the What-changed question prepared and unsent, or the lab on the symbol for a thesis with no investigation. With
``RESEARCH_QUEUE_ENABLED=true`` a fired trigger with an investigation also queues one ``reassess`` job through the
research queue (its budget and its one-a-day key); the queue's own result ping is the only other notification.
Headline text is third-party data: it is cleaned, quoted in the prepared question and plain in the ping body,
never anywhere as an instruction.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Callable
from urllib.parse import quote, urlencode

from sqlmodel import Session, col, select

from app.engine.chart_math import ET, session_windows
from app.engine.jo_morning_market import catalyst_first, eligible_headlines, stamp
from app.models import CopilotInvestigation, ThesisWatchTrigger

log = logging.getLogger(__name__)

TICK_SECONDS = 60
PASS_MINUTES = 15
MORNING_HOUR = 8
MAX_SYMBOLS = 25
MOVE_PCT_DEFAULT = 4.0
DAILY_CAP_DEFAULT = 4
EARNINGS_WITHIN_DAYS = 2
NEWS_LOOKBACK_REGULAR = timedelta(minutes=30)  # the first pass of a process; later passes read since the last one
NEWS_LOOKBACK_MORNING = timedelta(hours=16)  # overnight, back to the prior close
CONTEXT_MAX = 300
TEXT_MAX = 300
KINDS = ("news", "move", "earnings")

# Control characters and bidirectional overrides never reach a notification or a prepared question.
_UNSAFE = re.compile("[\x00-\x1f\x7f‪-‮⁦-⁩]")

NewsReader = Callable[[list[str], datetime, datetime], list[dict]]
QuoteReader = Callable[[list[str]], dict[str, dict]]  # {symbol: {"last": float|None, "previous_close": float|None}}
BarReader = Callable[[str, date], list[dict] | None]  # cached minute bars for one completed session, never a fetch
EarningsReader = Callable[[list[str], date], dict[str, str | None]]  # {symbol: next report date (ISO) or None}


def enabled() -> bool:
    return os.environ.get("THESIS_WATCH_ENABLED", "false").lower() in ("1", "true", "yes")


def _number(name: str, default: float, cast=float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default
    if not value > 0:
        log.warning("%s=%r must be above zero; using %s", name, raw, default)
        return default
    return value


def move_pct() -> float:
    return _number("THESIS_WATCH_MOVE_PCT", MOVE_PCT_DEFAULT)


def daily_cap() -> int:
    return int(_number("THESIS_WATCH_DAILY_CAP", DAILY_CAP_DEFAULT, int))


def clean(text) -> str:
    return " ".join(_UNSAFE.sub(" ", str(text or "")).split())


def _trim(text: str, most: int) -> str:
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


# --------------------------------------------------------------------------- default readers

def read_news(symbols: list[str], start: datetime, end: datetime) -> list[dict]:
    """One page on a short budget, strict so a refused key is "unavailable", never "none found"."""
    from app.engine import news
    return news.fetch_news(symbols=symbols, start=start, end=end, limit=50, fast=True, strict=True)


def read_quotes(symbols: list[str]) -> dict[str, dict]:
    """The chart feed's batched quote read (one request), as the Plans board uses."""
    from app.engine.chart_feed import ChartFeedError, chart_feed
    try:
        rows, _, issue = chart_feed.quote_rows(symbols)
    except ChartFeedError as exc:
        raise RuntimeError(str(exc)) from exc
    if issue and not rows:
        raise RuntimeError(issue)
    return {r["symbol"]: {"last": r.get("last"), "previous_close": r.get("previous_close")} for r in rows}


def read_bars(symbol: str, day: date) -> list[dict] | None:
    from app.engine.chart_history import chart_history
    return chart_history.stored(symbol, day)


def read_earnings(symbols: list[str], today: date) -> dict[str, str | None]:
    """From the events cache only (stale symbols refresh in the background, as the chart's earnings do)."""
    from app.engine.symbol_info_tradier import symbol_events
    found = symbol_events.chart_earnings(symbols, [], today)
    out: dict[str, str | None] = {}
    for symbol in symbols:
        nxt = (found.get(symbol) or {}).get("next") or {}
        out[symbol] = nxt.get("date") if isinstance(nxt.get("date"), str) else None
    return out


# --------------------------------------------------------------------------- the watched set

@dataclass
class Watched:
    symbol: str
    held: bool = False
    investigation: dict | None = None  # {"id", "as_of": aware datetime | None, "as_of_text"}
    memory_id: str | None = None
    reasons: list[str] = field(default_factory=list)


def _evidence_as_of(record: CopilotInvestigation) -> datetime | None:
    """The newest evidence as-of among the saved references (ISO text or epoch seconds), aware UTC."""
    latest = None
    try:
        refs = json.loads(record.evidence_json or "[]")
    except ValueError:
        return None
    for ref in refs:
        value = ref.get("as_of") if isinstance(ref, dict) else None
        moment = None
        if isinstance(value, (int, float)):
            try:
                moment = datetime.fromtimestamp(float(value), UTC)
            except (OverflowError, OSError, ValueError):
                moment = None
        elif isinstance(value, str):
            moment = stamp(value)
            if moment is None:  # a naive ISO time: the lab writes UTC
                try:
                    parsed = datetime.fromisoformat(value)
                    moment = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
                except ValueError:
                    moment = None
        if moment is not None and (latest is None or moment > latest):
            latest = moment
    return latest


def watched_set(db: Session, limit: int = MAX_SYMBOLS) -> list[Watched]:
    """Held symbols first (alphabetical), then open investigations newest first, then thesis memories; cut at
    ``limit``. A symbol held and investigated is one entry carrying both."""
    from sqlmodel import select as _select
    from app.ai.copilot_book import _not_webull
    from app.engine import jo_briefing
    from app.models import Account, Trade
    by_symbol: dict[str, Watched] = {}

    def entry(symbol: str) -> Watched:
        return by_symbol.setdefault(symbol, Watched(symbol=symbol))

    held = db.exec(_select(Trade.ticker).join(Account, Account.id == Trade.account_id)
                   .where(Trade.status == "open").where(_not_webull())).all()
    for ticker in sorted({t for t in held if t}):
        row = entry(ticker.upper())
        row.held = True
        row.reasons.append("held")
    open_records = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.status == "open",
                                                             col(CopilotInvestigation.symbol).is_not(None))
                           .order_by(col(CopilotInvestigation.updated_at).desc())).all()
    # The owner's own latest open investigation is the one the ping re-checks; a research job's output (a
    # reassessment's result) stands in only when he has none, and is never reassessed itself.
    for record in sorted(open_records, key=lambda r: r.source != "copilot"):
        row = entry(record.symbol.upper())
        if row.investigation is None:
            as_of = _evidence_as_of(record)
            row.investigation = {"id": str(record.id), "source": record.source, "as_of": as_of,
                                 "as_of_text": as_of.astimezone(ET).strftime("%b %-d %H:%M") if as_of else None}
            row.reasons.append("investigation")
    for memory in jo_briefing.memories(db, status="active", limit=200):
        body = memory.get("body") or {}
        symbol = memory.get("symbol") or body.get("symbol")
        if body.get("kind") != "thesis" or not symbol:
            continue
        row = entry(str(symbol).upper())
        if row.memory_id is None:
            row.memory_id = memory["memory_id"]
            row.reasons.append("thesis")
    ordered = ([r for r in by_symbol.values() if r.held]
               + [r for r in by_symbol.values() if not r.held and r.investigation is not None]
               + [r for r in by_symbol.values() if not r.held and r.investigation is None])
    return ordered[:limit]


# --------------------------------------------------------------------------- deep links and wording

def prepared_question(row: Watched, text: str) -> str:
    """The question waiting, unsent, in the lab's message box. For an investigation it carries the What-changed
    instruction so one tap re-checks the saved conclusion; third-party text is quoted as data."""
    if row.investigation:
        tail = f". What changed? Use get_investigation_changes for investigation {row.investigation['id']} and say whether it still holds."
    else:
        tail = ". Does it still hold?"
    room = CONTEXT_MAX - len('New since my thesis: ""') - len(tail)
    return f'New since my thesis: "{_trim(text, max(20, room)).rstrip(".")}"{tail}'


def deep_link(row: Watched, text: str, trigger_id: uuid.UUID | None = None) -> str:
    """The lab, with the question ready; ``origin`` names the trigger, so a plan made from it records what prompted it."""
    question = prepared_question(row, text)
    origin = {"origin": f"thesis_watch:{trigger_id}"} if trigger_id else {}
    if row.investigation:
        return "/copilot-lab?" + urlencode({"investigation": row.investigation["id"], "context": question, **origin}, quote_via=quote)
    return "/copilot-lab?" + urlencode({"symbol": row.symbol, "context": question, **origin}, quote_via=quote)


def title_for(symbol: str) -> str:
    return f"New on {symbol} since your thesis"


# --------------------------------------------------------------------------- the pass

@dataclass
class Candidate:
    row: Watched
    kind: str
    key: str
    text: str
    detail: dict


class ThesisWatch:
    def __init__(self, engine, calendar, *, clock: Callable[[], float] = time.time,
                 news: NewsReader = read_news, quotes: QuoteReader = read_quotes, bars: BarReader = read_bars,
                 earnings: EarningsReader = read_earnings, publish=None, queue_enabled: Callable[[], bool] | None = None):
        self.engine, self.calendar, self.clock = engine, calendar, clock
        self.news, self.quotes, self.bars, self.earnings = news, quotes, bars, earnings
        self._publish = publish
        self._queue_enabled = queue_enabled or (lambda: os.environ.get("RESEARCH_QUEUE_ENABLED") == "true")
        self._last_pass: datetime | None = None  # aware
        self._morning_done: date | None = None
        self.last_error: str | None = None

    # -------------------------------------------------------------- schedule

    def _regular_window(self, day: date) -> tuple[int, int] | None:
        hours = self.calendar.hours(day) if self.calendar is not None else None
        regular = next((w for w in session_windows(day, hours) if w[0] == "regular"), None)
        return (regular[1], regular[2]) if regular else None

    def due(self, now: datetime) -> str | None:
        """``morning`` once at or after 08:00 New York before the open on a trading day, ``regular`` every
        ``PASS_MINUTES`` inside the regular session, else None."""
        local = now.astimezone(ET)
        window = self._regular_window(local.date())
        if window is None:
            return None
        minute = local.hour * 60 + local.minute
        if MORNING_HOUR * 60 <= minute < window[0] and self._morning_done != local.date():
            return "morning"
        if window[0] <= minute < window[1]:
            if self._last_pass is None or (now - self._last_pass) >= timedelta(minutes=PASS_MINUTES):
                return "regular"
        return None

    def run_once(self) -> dict | None:
        """One pass when one is due; returns what it found, or None."""
        now = datetime.fromtimestamp(self.clock(), UTC)
        when = self.due(now)
        if when is None:
            return None
        since = self._last_pass or (now - (NEWS_LOOKBACK_MORNING if when == "morning" else NEWS_LOOKBACK_REGULAR))
        if when == "morning":
            self._morning_done = now.astimezone(ET).date()
        self._last_pass = now
        return self.run_pass(now, since)

    # -------------------------------------------------------------- one pass

    def run_pass(self, now: datetime, since: datetime) -> dict:
        today = now.astimezone(ET).date()
        with Session(self.engine) as db:
            rows = watched_set(db)
        symbols = [r.symbol for r in rows]
        result = {"day": today.isoformat(), "watched": symbols, "fired": [], "skipped": [], "issues": []}
        if not rows:
            return result
        candidates: list[Candidate] = []
        candidates += self._news_candidates(rows, since, now, result["issues"])
        candidates += self._move_candidates(rows, today, result["issues"])
        candidates += self._earnings_candidates(rows, today, result["issues"])
        with Session(self.engine) as db:
            for candidate in candidates:
                try:
                    outcome = self._record(db, candidate, today, now)
                except Exception as exc:  # noqa: BLE001 - one trigger's failure must not lose the others this pass
                    db.rollback()
                    log.exception("Thesis watch could not record %s for %s", candidate.kind, candidate.row.symbol)
                    result["issues"].append(f"{candidate.kind} {candidate.row.symbol} not recorded: {type(exc).__name__}")
                    continue
                if outcome is None:
                    continue
                (result["fired"] if outcome["delivery"] in ("sent", "failed") else result["skipped"]).append(outcome)
        return result

    def _news_candidates(self, rows: list[Watched], since: datetime, now: datetime, issues: list) -> list[Candidate]:
        by_symbol = {r.symbol: r for r in rows}
        try:
            articles = eligible_headlines(self.news(sorted(by_symbol), since, now), now)
        except Exception as exc:  # the provider being down is "unavailable", never a trigger
            issues.append(f"news unavailable: {type(exc).__name__}")
            return []
        found: list[Candidate] = []
        taken: set[str] = set()
        for article in catalyst_first(articles):  # catalysts first, then newest first within the rest
            published = stamp(article["created_at"])
            if published is None or published < since:
                continue
            for symbol in [s for s in article["symbols"] if isinstance(s, str)]:
                row = by_symbol.get(symbol.upper())
                if row is None or row.symbol in taken:
                    continue
                taken.add(row.symbol)
                headline = _trim(clean(article["headline"]), TEXT_MAX)
                source = clean(article.get("source"))
                text = f"{headline} ({source}, {published.astimezone(ET).strftime('%H:%M')})" if source else headline
                found.append(Candidate(row, "news", f"news:{row.symbol}:{article['url'][:500]}", text,
                                       {"url": article["url"][:1200], "published_at": published.isoformat(), "headline": headline}))
        return found

    def _reference(self, row: Watched, quote: dict, today: date) -> tuple[float | None, str, str]:
        """(reference price, basis key, wording). An investigation's evidence as-of uses that day's cached minute
        bars when the day is complete and stored, else the prior close. Evidence from today has no reference: the
        owner just read that price, so a move since the prior close would only repeat what he saw."""
        inv = row.investigation
        if inv and inv.get("as_of") is not None:
            as_of = inv["as_of"]
            day = as_of.astimezone(ET).date()
            if day >= today:
                return None, "", ""
            if day < today:
                try:
                    bars = self.bars(row.symbol, day) or []
                except Exception:  # noqa: BLE001 - a cache problem is not a move
                    bars = []
                at_or_before = [b for b in bars if isinstance(b.get("time"), (int, float)) and b["time"] <= as_of.timestamp()]
                if at_or_before:
                    close = at_or_before[-1].get("close")
                    if isinstance(close, (int, float)) and close > 0:
                        return float(close), f"evidence:{inv['id']}:{as_of.isoformat()}", f"since your investigation's evidence ({inv['as_of_text']} NY)"
            previous = quote.get("previous_close")
            if isinstance(previous, (int, float)) and previous > 0:
                return float(previous), f"close:{today.isoformat()}", "since the prior close"
            return None, "", ""
        previous = quote.get("previous_close")
        if isinstance(previous, (int, float)) and previous > 0:
            return float(previous), f"close:{today.isoformat()}", "since the prior close"
        return None, "", ""

    def _move_candidates(self, rows: list[Watched], today: date, issues: list) -> list[Candidate]:
        try:
            quotes = self.quotes([r.symbol for r in rows])
        except Exception as exc:  # noqa: BLE001 - no quotes, no move triggers this pass
            issues.append(f"quotes unavailable: {type(exc).__name__}")
            return []
        threshold = move_pct()
        found: list[Candidate] = []
        for row in rows:
            quote = quotes.get(row.symbol) or {}
            last = quote.get("last")
            if not isinstance(last, (int, float)) or last <= 0:
                continue
            reference, basis, wording = self._reference(row, quote, today)
            if reference is None:
                continue
            pct = round(100.0 * (float(last) - reference) / reference, 1)
            if abs(pct) < threshold:
                continue
            text = f"{row.symbol} {pct:+.1f}% {wording}: {reference:g} → {float(last):g}"
            found.append(Candidate(row, "move", f"move:{row.symbol}:{basis}", text,
                                   {"pct": pct, "last": float(last), "reference": reference, "basis": basis}))
        return found

    def _trading_days_until(self, today: date, target: date) -> int | None:
        if target < today:
            return None
        count, day = 0, today
        while day < target:
            day += timedelta(days=1)
            if self._regular_window(day) is not None:
                count += 1
            if count > EARNINGS_WITHIN_DAYS:
                return count
        return count

    def _earnings_candidates(self, rows: list[Watched], today: date, issues: list) -> list[Candidate]:
        try:
            dates = self.earnings([r.symbol for r in rows], today)
        except Exception as exc:  # noqa: BLE001 - the cache being unreadable is not a trigger
            issues.append(f"earnings unavailable: {type(exc).__name__}")
            return []
        found: list[Candidate] = []
        for row in rows:
            raw = dates.get(row.symbol)
            try:
                target = date.fromisoformat(raw) if raw else None
            except ValueError:
                target = None
            if target is None:
                continue
            days = self._trading_days_until(today, target)
            if days is None or days > EARNINGS_WITHIN_DAYS:
                continue
            when = "today" if days == 0 else ("next trading day" if days == 1 else f"in {days} trading days")
            text = f"Earnings {target.strftime('%a %b %-d')}, {when}"
            found.append(Candidate(row, "earnings", f"earnings:{row.symbol}:{target.isoformat()}", text,
                                   {"date": target.isoformat(), "trading_days": days}))
        return found

    # -------------------------------------------------------------- record, deliver, hand off

    def _record(self, db: Session, candidate: Candidate, today: date, now: datetime) -> dict | None:
        """Write the trigger once (its key is unique), decide its delivery, send, and record the outcome.
        Returns the row's view, or None when the key was already written."""
        from app.engine import ntfy
        row = candidate.row
        day = today.isoformat()
        # A delivered (or attempted) trigger keeps its key for good; a skipped one keeps it for the day only, so a
        # cap or a missing ntfy does not swallow the signal when the same thing is still true tomorrow.
        skipped_key = f"{candidate.key}#skipped:{day}"
        if db.exec(select(ThesisWatchTrigger).where(col(ThesisWatchTrigger.dedupe_key).in_((candidate.key, skipped_key)))).first() is not None:
            return None
        attempted = db.exec(select(ThesisWatchTrigger).where(ThesisWatchTrigger.day == day,
                                                            col(ThesisWatchTrigger.delivery).in_(("sending", "sent", "failed")))).all()
        reason = None
        if any(t.symbol == row.symbol for t in attempted):
            reason = "already told today"
        elif len(attempted) >= daily_cap():
            reason = "daily cap reached"
        elif not ntfy.configured():
            reason = "ntfy not configured"
        trigger_id = uuid.uuid4()
        trigger = ThesisWatchTrigger(
            id=trigger_id, symbol=row.symbol, kind=candidate.kind, dedupe_key=skipped_key if reason else candidate.key,
            investigation_id=uuid.UUID(row.investigation["id"]) if row.investigation else None,
            memory_id=uuid.UUID(row.memory_id) if row.memory_id and not row.investigation else None,
            held=row.held, day=day, fired_at=now.replace(tzinfo=None), text=candidate.text[:TEXT_MAX + 60],
            detail_json=json.dumps(candidate.detail), path=deep_link(row, candidate.text, trigger_id),
            delivery="skipped" if reason else "sending", reason=reason)
        db.add(trigger)
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - another writer took the key between the read and the insert
            db.rollback()
            return None
        if reason:
            return self._view(trigger)
        from app.engine import notification_policy
        anchor, trade_id = notification_policy.symbol_anchor(db, row.symbol)
        ticket = notification_policy.decide(db, sender="thesis_watch", source_id=str(trigger.id), kind="thesis_watch",
                                            title=title_for(row.symbol), body=candidate.text, now=now.timestamp(), anchor=anchor,
                                            symbol=row.symbol, trade_id=trade_id)
        if ticket.held:
            # Not told: keyed to the day like a skipped trigger, so the same signal can still be told tomorrow.
            trigger.delivery, trigger.reason, trigger.dedupe_key = "held", ticket.reason, skipped_key
            db.add(trigger)
            db.commit()
            return self._view(trigger)
        from app.engine import ping_images
        try:
            if self._publish is not None:
                trigger.message_id = self._publish(title_for(row.symbol), candidate.text + ticket.append, path=trigger.path, direct_click=True)
            else:
                # The ping's chart: today with the price the move is measured from.
                basis = str(candidate.detail.get("basis") or "")
                image = ping_images.picture(ping_images.thesis(
                    title_for(row.symbol), row.symbol, candidate.detail.get("reference"),
                    "since evidence" if basis.startswith("evidence:") else "since close" if basis else "", now.timestamp()))
                trigger.message_id, image_state = ping_images.publish(title_for(row.symbol), candidate.text + ticket.append, image,
                                                                      path=trigger.path, direct_click=True)
                ping_images.record(db, ticket, image_state)
            trigger.delivery = "sent"
        except Exception as exc:  # noqa: BLE001 - recorded, never retried: a failed push may still have been delivered
            trigger.delivery, trigger.reason = "failed", f"{type(exc).__name__}: {exc}"[:300]
        notification_policy.delivered(db, ticket, now.timestamp())
        if row.investigation and row.investigation.get("source") == "copilot" and self._queue_enabled():
            trigger.reassess_job_id = self._queue_reassess(row.investigation["id"], candidate, day, db)
        db.add(trigger)
        db.commit()
        return self._view(trigger)

    @staticmethod
    def _queue_reassess(investigation_id: str, candidate: Candidate, day: str, db: Session) -> uuid.UUID | None:
        """One reassess job a day for the investigation through the existing queue, which charges its own budget
        when the job runs. The same key as the queue's own stale-investigation trigger, so never two in a day."""
        from app.engine import research_queue
        try:
            job, _ = research_queue.enqueue("reassess", {"investigation_id": investigation_id, "from_investigation": investigation_id,
                                                         "requested_by": "thesis_watch", "trigger": candidate.kind},
                                            f"reassess:{investigation_id}:{day}", db)
            return uuid.UUID(job["id"])
        except Exception:  # noqa: BLE001 - the ping stands; the hand-off is extra
            log.exception("Thesis watch could not queue a reassessment")
            return None

    @staticmethod
    def _view(trigger: ThesisWatchTrigger) -> dict:
        return view(trigger)


def view(trigger: ThesisWatchTrigger) -> dict:
    return {"id": str(trigger.id), "symbol": trigger.symbol, "kind": trigger.kind, "text": trigger.text,
            "fired_at": trigger.fired_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"), "day": trigger.day,
            "delivery": trigger.delivery, "reason": trigger.reason, "path": trigger.path,
            "investigation_id": str(trigger.investigation_id) if trigger.investigation_id else None,
            "reassess_job_id": str(trigger.reassess_job_id) if trigger.reassess_job_id else None}


def recent_for(db: Session, investigation_ids: list[str], limit: int = 3) -> dict[str, list[dict]]:
    """The last few triggers for each investigation (newest first), for the lab's Open threads row."""
    keys: list[uuid.UUID] = []
    for value in investigation_ids:
        try:
            keys.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    if not keys:
        return {}
    out: dict[str, list[dict]] = {}
    for trigger in db.exec(select(ThesisWatchTrigger).where(col(ThesisWatchTrigger.investigation_id).in_(keys))
                           .order_by(col(ThesisWatchTrigger.fired_at).desc())):
        bucket = out.setdefault(str(trigger.investigation_id), [])
        if len(bucket) < limit:
            bucket.append({k: v for k, v in view(trigger).items() if k in ("kind", "text", "fired_at", "delivery", "reason", "path")})
    return out


def watch_from_env(engine) -> ThesisWatch | None:
    if not enabled():
        return None
    from app.engine.chart_calendar import chart_calendar
    return ThesisWatch(engine, chart_calendar)
