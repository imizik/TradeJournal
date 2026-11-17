"""The desk's open self-check (docs/copilot-lab.md § Open self-check): once each regular session, a minute after the open,
try the desk's newest features on the first live data and send the owner one Telegram line.

Six checks, each on its own thread with its own short timeout, so one failing or hanging never blocks the others or
the API, and none writes anything into his books (no paper order, plan, rule record or goal):

1. ``paper pricing`` — the paper book's own fill price (``paper_book.contract``, ``_live_quotes`` and ``price``, all
   pure) for SPY shares and the at-the-money SPY call expiring today, on a fresh quote. Two quote reads.
2. ``paper runner`` — the paper book's minute (``paper_runner``) passed in the last ``RUNNER_FRESH`` seconds; ``off``
   when it is not running.
3. ``replay`` — the option replay's source (``replay_options.trades``) returns previous-session bars for today's
   at-the-money SPY call while it is still listed. One timesales read (none when it is already kept).
4. ``desk minute`` — the desk minute request's dispatcher (``desk_minute.read_all``) answers two of its reads that read
   only the database and kept state (``MINUTE_READS``), routed inside the app: no network, no provider call.
5. ``deep links`` — a ping's tap (``phone.desk_link``) opens the desk route with only the parameters the desk reads.
6. ``health strip`` — the data-health strip (``desk_health.build``) reads every source; its bad rows ride the line.

At most three Tradier reads a day, each through the chart feed's single-flight and budget. Robinhood: only the health
strip's existing reader of the feed's cached state (``kick=False``), never a read.

The ping is one line under its own kind, ``self_check`` (``notification_policy``: a budget of one a day of its own, so it
never spends another kind's), only in a regular session (the market calendar must confirm it: never a holiday or a
weekend). Each run is kept in ``data/self_check/<day>.json`` (the last ``KEEP_DAYS``); the health strip shows the newest.
``SELF_CHECK_ENABLED=false`` switches it off; it is on by default.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

KIND = "self_check"
AFTER_OPEN = 60  # seconds after the open: 09:31 on a normal day
TIMEOUT = 15.0  # seconds per check
RUNNER_FRESH = 120  # the paper runner passed within this many seconds
LOOP_SECONDS = 20
KEEP_DAYS = 30
SYMBOL = "SPY"
ROOT = Path(__file__).resolve().parents[2] / "data" / "self_check"
DESK_PATH = "/copilot-lab"
DESK_PARAMS = frozenset({"symbol", "investigation", "radar", "feed"})  # what the desk reads from a ping's link
# Two minute reads that call no provider and never start a Robinhood read (the thread list does both, so it is not one).
MINUTE_READS = ("/copilot/investigations", "/copilot/desk/health")
NAMES = ("paper pricing", "paper runner", "replay", "desk minute", "deep links", "health strip")
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("SELF_CHECK_ENABLED", "true").strip().lower() != "false"


class CheckFailed(Exception):
    """A check's short reason for the line."""


# --------------------------------------------------------------------------- the kept runs

def _file(day: str) -> Path:
    return ROOT / f"{day}.json"


def _save(entry: dict) -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        _file(entry["day"]).write_text(json.dumps(entry))
        oldest = (date.fromisoformat(entry["day"]) - timedelta(days=KEEP_DAYS)).isoformat()
        for old in ROOT.glob("*.json"):
            if old.stem < oldest:
                old.unlink(missing_ok=True)
    except OSError:
        log.warning("self-check could not be saved for %s", entry.get("day"), exc_info=True)


def _load(day: str) -> dict | None:
    try:
        return json.loads(_file(day).read_text())
    except (OSError, ValueError):
        return None


def latest() -> dict | None:
    """The newest kept run, or None."""
    try:
        names = sorted((p.stem for p in ROOT.glob("*.json")), reverse=True)
    except OSError:
        return None
    for name in names:
        if (entry := _load(name)) is not None:
            return entry
    return None


# --------------------------------------------------------------------------- the line

def _hhmm(at: float) -> str:
    return datetime.fromtimestamp(at, ET).strftime("%H:%M")


def _hms(at: float) -> str:
    return datetime.fromtimestamp(at, ET).strftime("%H:%M:%S")


def line(results: list[dict], at: float) -> str:
    """``Self-check 09:31 ✅ all 6 OK``, or which failed and why (an ``off`` check is named, not failed)."""
    failed = [r for r in results if r["status"] == "fail"]
    off = [r for r in results if r["status"] == "off"]
    head = f"Self-check {_hhmm(at)}"
    if failed:
        named = ", ".join(f"{r['name']} ({r['detail']})" for r in failed)
        return f"{head} ⚠️ {len(failed)} of {len(results)} failed: {named}"
    if off:
        return f"{head} ✅ {len(results) - len(off)} of {len(results)} OK, off: {', '.join(r['name'] for r in off)}"
    return f"{head} ✅ all {len(results)} OK"


def data_line(health: dict | None) -> str:
    """The health strip's result in a few words: ``Data: all live``, or what is behind."""
    if not health:
        return "Data: health strip not read"
    words = {"stale": "behind", "down": "down", "low": "low"}
    rows = [r for r in health.get("sources", []) if r.get("id") != "self_check"]
    bad = [f"{r['name']} {words[r['state']]}" for r in rows if r.get("state") in words]
    if bad:
        return "Data: " + ", ".join(bad)
    if any(r.get("state") == "unknown" for r in rows):
        return "Data: some sources not known yet"
    return "Data: all live"


# --------------------------------------------------------------------------- the checks

def _atm_call(price: float, expiry: date) -> dict:
    from app.engine import replay_options
    strike = min(replay_options.strikes(SYMBOL, price), key=lambda s: (abs(s - price), s))
    return {"symbol": SYMBOL, "instrument": "option", "option_type": "call", "strike": strike, "expiry": expiry.isoformat()}


def check_paper_pricing(now: float, facts: dict) -> str:
    """SPY shares and today's at-the-money SPY call priced as a paper buy would be, on fresh quotes; nothing written."""
    from app.engine import paper_book
    today = datetime.fromtimestamp(now, ET).date()
    priced = []
    for body in ({"symbol": SYMBOL, "instrument": "stock"}, None):
        if body is None:
            stock = facts.get("spy")
            if not stock:
                raise CheckFailed(f"no {SYMBOL} price to pick a contract")
            body = _atm_call(stock, today)
        spec = paper_book.contract(body, today)
        quotes = paper_book._live_quotes([leg["quote"] for leg in spec["legs"]])
        if spec["instrument"] == "stock":
            facts["spy"] = paper_book._stock_price(spec, quotes)  # the replay check's strike, even on a stale quote
        for leg in spec["legs"]:  # the stale case named in the line's own words
            quote = quotes.get(leg["quote"])
            if quote is not None and not paper_book._fresh(quote, now - paper_book.FRESH_SECONDS):
                stamps = [t / 1000 for t in (quote.bid_date, quote.ask_date) if isinstance(t, (int, float))]
                since = f" since {_hms(min(stamps))}" if stamps else ""
                raise CheckFailed(f"no fresh {spec['label'] if spec['instrument'] != 'stock' else SYMBOL} quote{since}")
        try:
            got = paper_book.price(spec, quotes, now, closing=False)
        except paper_book.PaperError as exc:
            raise CheckFailed(str(exc)) from None
        if spec["instrument"] == "stock" and not facts.get("spy"):
            facts["spy"] = abs(got["per_share"])
        priced.append(f"{spec['label']} {abs(got['per_share']):.2f}")
    return ", ".join(priced)


def check_paper_runner(now: float, runner) -> str:
    if runner is None:
        raise _Off("not running")
    last = getattr(runner, "last_pass_at", None)
    if getattr(runner, "last_error", None):
        raise CheckFailed(runner.last_error.lower())
    if last is None or now - last > RUNNER_FRESH:
        raise CheckFailed(f"no pass since {_hms(last)}" if last else "no pass yet")
    return f"passed {_hms(last)}"


def check_replay(now: float, facts: dict) -> str:
    """Read the prior session's trades for today's at-the-money SPY call, which is still listed at the open."""
    from app.engine import paper_replay, replay_options
    from app.engine.occ import occ_symbol
    found = paper_replay.days(now, 1)
    if not found:
        raise CheckFailed("no previous session")
    day = date.fromisoformat(found[0]["date"])
    if reason := replay_options.off_reason(day, now):
        raise CheckFailed(reason.split(".")[0].lower())
    price = facts.get("spy")
    if not price:
        raise CheckFailed(f"no {SYMBOL} price to pick a contract")
    expiry = datetime.fromtimestamp(now, ET).date()
    spec = _atm_call(price, expiry)
    occ = occ_symbol(SYMBOL, expiry, "call", spec["strike"])
    try:
        bars = replay_options.trades(occ, day)
    except replay_options.OptionsOff as exc:
        raise CheckFailed(f"timesales {getattr(exc, 'status', '')}: {exc}".strip()) from None
    if not bars:
        raise CheckFailed(f"no bars for {occ} on {day:%b %-d}")
    return f"{len(bars)} bars for {occ}"


async def check_desk_minute(app) -> str:
    """Two of the desk's minute reads through the minute request's own dispatcher, routed inside the app."""
    from app.engine import desk_minute
    if app is None:
        raise CheckFailed("no app")

    from contextlib import AsyncExitStack
    from starlette.middleware.exceptions import ExceptionMiddleware
    # The app's routes with FastAPI's own innermost layers (error answers, the request's exit stack, under the key each
    # FastAPI version reads), without the network-facing middleware: a request from inside the server, as the minute
    # request's reads are once admitted.
    inner = ExceptionMiddleware(app.router, handlers=app.exception_handlers)

    async def routed(scope, receive, send):
        async with AsyncExitStack() as stack:
            scope.update(app=app, fastapi_middleware_astack=stack, fastapi_astack=stack)
            await inner(scope, receive, send)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "scheme": "http",
             "server": ("127.0.0.1", 80), "client": ("127.0.0.1", 0), "root_path": "", "headers": []}
    answers = await desk_minute.read_all(routed, scope, list(MINUTE_READS))
    bad = [f"{path.rsplit('/', 1)[-1]} {a['status']}" for path, a in zip(MINUTE_READS, answers) if a["status"] != 200]
    if bad:
        raise CheckFailed(", ".join(bad))
    return f"{len(answers)} reads answered"


def check_deep_links() -> str:
    """A ping's tap opens the desk on its symbol: the path is the desk route and every parameter one the desk reads."""
    from app.engine import phone
    path = phone.desk_link("/", symbol=SYMBOL)
    parts = urlsplit(path)
    if parts.path != DESK_PATH:
        raise CheckFailed(f"opens {parts.path or path!r}, not the desk")
    params = parse_qs(parts.query)
    if params.get("symbol") != [SYMBOL] or set(params) - DESK_PARAMS:
        raise CheckFailed(f"link {path!r} carries what the desk does not read")
    if app_url := os.environ.get("ALERT_APP_URL", "").strip():
        full = urlsplit(app_url.rstrip("/") + path)
        if full.scheme not in ("http", "https") or not full.netloc:
            raise CheckFailed("ALERT_APP_URL is not a web address")
    return path


def check_health(engine, now: float, holder: dict) -> str:
    from sqlmodel import Session
    from app.engine import desk_health
    from app.routers import copilot_desk
    with Session(engine) as db:
        built = desk_health.build(db, now, lambda: copilot_desk._robinhood_health(now))
    holder["health"] = built
    unread = [r["name"] for r in built["sources"] if r.get("state") == "unknown" and r.get("line") == "Could not read its state just now"]
    if unread:
        raise CheckFailed(f"could not read {', '.join(unread)}")
    return f"{len(built['sources'])} sources read, {built['overall']}"


class _Off(Exception):
    pass


# --------------------------------------------------------------------------- the run

class SelfCheck:
    def __init__(self, engine, *, app=None, runner: Callable[[], object] = lambda: None, clock: Callable[[], float] = time.time,
                 send=None, session=None, timeout: float = TIMEOUT):
        self.engine, self.app, self.runner, self.clock, self._send = engine, app, runner, clock, send
        self._session = session  # (regular session in epoch seconds or None, calendar confirmed) at a moment; tests
        self.timeout = timeout
        self._claimed: str | None = None  # the day run here, so an unwritable folder never reruns it every pass

    def regular(self, now: float) -> tuple[int, int] | None:
        """Today's regular session while it is open and the market calendar confirms it, else None."""
        if self._session is not None:
            return self._session(now)
        from app.engine import desk_sparks
        _day, phase, hours, regular = desk_sparks._session(now)
        if hours is None or phase != "regular" or regular is None:  # no calendar: never guess a holiday is a session
            return None
        return regular

    def due(self, now: float) -> bool:
        regular = self.regular(now)
        if regular is None or now < regular[0] + AFTER_OPEN:
            return False
        day = datetime.fromtimestamp(now, ET).date().isoformat()
        return self._claimed != day and _load(day) is None

    async def _one(self, name: str, work) -> dict:
        started = time.monotonic()
        try:
            if asyncio.iscoroutine(work):
                detail = await asyncio.wait_for(work, self.timeout)
            else:
                detail = await asyncio.wait_for(asyncio.to_thread(work), self.timeout)
            status = "ok"
        except _Off as exc:
            status, detail = "off", str(exc)
        except CheckFailed as exc:
            status, detail = "fail", str(exc)
        except TimeoutError:
            status, detail = "fail", f"no answer in {self.timeout:g} s"
        except Exception as exc:  # noqa: BLE001 -- one check's failure is its own line, never the run's
            log.warning("self-check %s failed", name, exc_info=True)
            status, detail = "fail", f"{type(exc).__name__}: {exc}"
        detail = str(detail)
        return {"name": name, "status": status, "detail": detail if len(detail) <= 90 else detail[:89] + "…",
                "ms": round((time.monotonic() - started) * 1000)}

    async def run(self) -> dict:
        """All six checks, kept and pinged once. The day is claimed first, so a restart mid-run never runs it twice."""
        now = self.clock()
        day = datetime.fromtimestamp(now, ET).date().isoformat()
        with _lock:
            if self._claimed == day or _load(day) is not None:
                return _load(day) or {"day": day, "state": "claimed"}
            self._claimed = day
            _save({"day": day, "at": now, "state": "running"})
        facts, holder = {}, {}
        results = [
            await self._one(NAMES[0], lambda: check_paper_pricing(now, facts)),
            await self._one(NAMES[1], lambda: check_paper_runner(now, self.runner())),
            await self._one(NAMES[2], lambda: check_replay(now, facts)),
            await self._one(NAMES[3], check_desk_minute(self.app)),
            await self._one(NAMES[4], check_deep_links),
            await self._one(NAMES[5], lambda: check_health(self.engine, now, holder)),
        ]
        entry = {"day": day, "at": now, "state": "done", "results": results,
                 "failed": sum(r["status"] == "fail" for r in results), "line": line(results, now),
                 "data": data_line(holder.get("health")), "ping": None}
        _save(entry)
        entry["ping"] = await asyncio.to_thread(self.ping, entry)
        _save(entry)
        return entry

    def ping(self, entry: dict) -> str:
        """One line under ``self_check``'s own budget; never retried (a failed send may still have arrived)."""
        from sqlmodel import Session
        from app.engine import notification_policy, phone
        if self._send is None and not phone.configured():
            return "off: phone pings are not set up"
        now = self.clock()
        try:
            with Session(self.engine) as db:
                ticket = notification_policy.decide(db, sender=KIND, source_id=entry["day"], kind=KIND, title=entry["line"],
                                                    body=entry["data"], now=now)
                if ticket.held:
                    return f"held: {ticket.reason}"
                path = phone.desk_link("/")
                if self._send is not None:
                    self._send(entry["line"], entry["data"] + ticket.append, path=path)
                else:
                    # Quiet when all is well; a failure buzzes.
                    phone.send(entry["line"], entry["data"] + ticket.append, kind=KIND, path=path,
                               priority=4 if entry["failed"] else 2)
                notification_policy.delivered(db, ticket, now)
                db.commit()
            return "sent"
        except Exception as exc:  # noqa: BLE001 -- recorded, never retried
            log.exception("self-check ping failed")
            return f"failed: {type(exc).__name__}"

    async def loop(self) -> None:
        while True:
            try:
                if await asyncio.to_thread(self.due, self.clock()):
                    await self.run()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("self-check pass failed")
            await asyncio.sleep(LOOP_SECONDS)
