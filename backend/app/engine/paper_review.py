"""The weekly paper review (docs/copilot-lab.md § Paper): after Friday's close, the copilot compares the week's paper
trades with the owner's real ones, and the desk shows the review at the top of its Paper section until the next one.

What it says (``copilot_prompt.PAPER_REVIEW``): the week's paper and real closed P&L side by side, what worked, where he
took or broke his own stop or target, and one thing to try next week, tied to a trade from the week. It is written from
the week's facts alone (``facts``, ``pack``), with no tool, as the close-of-day read is (``engine/day_read.py``, whose
turn runner, figure check and hidden-ticker check it reuses): every dollar figure in the review must be one the facts
hold, and a review naming a ticker he does not follow is not shown. It never invents a trade: the facts list every one.

When and what it costs:

- once a week, on the week's last trading day (Friday; the day before a Friday holiday, per the market calendar) at or
  after ``AT`` (16:45 New York), from the level alert monitor's loop beside the other close-of-day senders, on its own
  thread; nothing runs while the copilot lab is off;
- skipped, with no call, in a week with no closed paper trade;
- one turn: one round, no tools, the day read's cap and output limit (``day_read.small``), a ``copilot_turn`` row
  (``kind="paper_review"``) on the shared ``COPILOT_DAILY_BUDGET_USD``, refused unless ``day_read.HEADROOM`` reads' worth
  of its cap still fits under the day's budget; a ``paper_review`` row already written today means the automatic review
  already ran, so a restart never pays for it twice.

Kept in ``data/paper_review/<friday>.json`` (the last ``KEEP_WEEKS`` weeks) and in memory; ``latest`` is what the desk's
paper read (``GET /copilot/paper``) carries. One phone ping, ``PAPER REVIEW · week of <Monday>``, carries it (kind
``paper_review``: its own daily budget of one in ``notification_policy``, so it never spends Radar's or the position
alerts'). Delivery is at most once: the claim turns ``pending`` into ``sending`` under one lock and the kept file says
``sending`` before the send, and a send that may have reached the phone is ``unknown`` and never resent; one not sent
within ``EXPIRE_SECONDS`` is ``expired``. Nothing here places, closes or changes a paper order, and it never calls
Robinhood. Its facts come from the desk's own paper read (``paper_book.view``), which settles an option still open past
its expiration's close at intrinsic value, as the desk's minute read does (at most one cached daily-history read
through the chart feed for that close).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Callable

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

KIND = "paper_review"
AT = 16 * 60 + 45  # New York, after the Friday-expiry settlements (15 minutes after the close)
RUN_SECONDS = 30
KEEP_WEEKS = 8
EXPIRE_SECONDS = 2 * 60 * 60
RETRY_SECONDS = 300
MAX_ATTEMPTS = 4
LISTED = 15
TITLE = "PAPER REVIEW"
ROOT = Path(__file__).resolve().parents[2] / "data" / "paper_review"
QUESTION = "Paper review: the week of {monday}. Review my paper week against my real one from the facts below.\n\n{pack}"

_latest: dict | None = None
_lock = threading.RLock()  # the kept review: its load, every save and the ping claim


def clear() -> None:
    """Forget the kept review in memory (tests)."""
    global _latest
    _latest = None


# --------------------------------------------------------------------------- the facts

def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _short(day: date) -> str:
    return f"{day:%a} {day:%b} {day.day}"


def facts(db, now: float) -> dict:
    """The week's facts (see the module text). Raises when the Not-following setting cannot be read: no review then."""
    from sqlmodel import col, select
    from app.ai.copilot_book import _not_webull
    from app.engine import day_journal, paper_book
    from app.engine.chart_journal import contract_label
    from app.models import Account, Trade

    day = datetime.fromtimestamp(now, ET).date()
    monday = _monday(day)
    start = datetime.combine(monday, wall_time(0), ET)
    hidden = day_journal.not_following(db)
    out = {"day": day.isoformat(), "monday": monday.isoformat(), "as_of": now, "hidden": hidden, "run": None,
           "closed": [], "paper": None, "open": [], "real": None, "real_closed": [], "partial": False}
    view = paper_book.view(db, now)  # the desk's own read: it settles an expired option at its close, as every minute
    run = view.get("run")
    if run is None:
        return out
    week = [c for c in view.get("closed") or [] if c["closed_at"] >= start.timestamp()]
    out["run"] = run
    out["partial"] = len(week) == paper_book.CLOSED_SHOWN  # the view lists the newest 50 closed: the week may hold more
    out["paper"] = paper_book.stats([c["realized"] for c in week],
                                    [(datetime.fromtimestamp(c["closed_at"], ET).date(), c["realized"]) for c in week])
    out["closed"] = [c for c in week if c["symbol"] not in hidden]
    out["open"] = [p for p in view.get("positions") or [] if p["symbol"] not in hidden]
    out["real"] = paper_book.real_trades(db, start.astimezone(UTC).replace(tzinfo=None))
    naive = start.replace(tzinfo=None)  # the journal's times are New York wall clocks
    rows = db.exec(select(Trade, Account).join(Account, Account.id == Trade.account_id).where(_not_webull())
                   .where(col(Trade.status).in_(("closed", "expired"))).where(Trade.closed_at >= naive)
                   .where(Trade.realized_pnl.is_not(None))).all()
    out["real_closed"] = [{"contract": contract_label(t.ticker, t.instrument_type, t.option_type, t.strike, t.expiration),
                           "account": a.name, "closed_at": t.closed_at, "realized": round(float(t.realized_pnl), 2)}
                          for t, a in sorted(rows, key=lambda p: p[0].closed_at) if t.ticker not in hidden]
    return out


def due(f: dict) -> bool:
    """A week with at least one closed paper trade (followed or not) has something to review."""
    return bool(f["paper"] and f["paper"]["trades"])


def _stats_line(name: str, s: dict | None) -> str:
    from app.engine.day_read import usd
    if not s or not s["trades"]:
        return f"{name} this week: no closed trades."
    parts = [f"{name} this week: {s['trades']} closed, realised {usd(s['pnl'])}", f"win rate {s['win_rate']:g}%"]
    if s["avg_win"] is not None:
        parts.append(f"average winner {usd(s['avg_win'])}")
    if s["avg_loss"] is not None:
        parts.append(f"average loser {usd(s['avg_loss'])}")
    if s["largest_loss"] is not None:
        parts.append(f"largest loss {usd(s['largest_loss'])}")
    return "; ".join(parts) + "."


def _levels(p: dict) -> str:
    bits = [f"stop {p['stop']:g}" if p.get("stop") is not None else "no stop",
            f"target {p['target']:g}" if p.get("target") is not None else "no target"]
    return ", ".join(bits) + " (stock prices)"


def _size(p: dict, key: str) -> str:
    n = p[key]
    unit = "share" if p["instrument"] == "stock" else "contract" if p["instrument"] == "option" else "spread"
    return f"{n:g} {unit}{'s' if n != 1 else ''}"


def pack(f: dict) -> str:
    """The facts as the model reads them. Every dollar figure here is written exactly as the review must quote it."""
    from app.engine.day_read import usd
    from app.engine.paper_book import clock
    monday, day = date.fromisoformat(f["monday"]), date.fromisoformat(f["day"])
    run = f["run"]
    lines = [f"This week's facts ({_short(monday)} to {_short(day)}, as of {clock(f['as_of'])}). His paper book (run "
             f"{run['number']}, started {clock(run['started_at'])}, practice with no money) and his journal's real trades "
             "(Webull left out). Tickers he does not follow are left out of the lists and stay in the totals. Every dollar "
             "figure is written exactly as it must be quoted; stops, targets and stock prices are plain numbers."]
    lines.append(_stats_line("Paper", f["paper"]))
    if f["partial"]:
        lines.append("(Paper totals cover the 50 newest closed paper trades only.)")
    lines.append(_stats_line("Real", f["real"]))
    if f["closed"]:
        lines.append("Paper trades closed this week:")
        for c in f["closed"][:LISTED]:
            ended = (c.get("verdict") or {}).get("text") or "no verdict"
            note = f'; his note: "{c["note"]}"' if c.get("note") else ""
            lines.append(f"- {c['label']}, {_size(c, 'quantity')}: in {clock(c['opened_at'])}, out {clock(c['closed_at'])}; "
                         f"realised {usd(c['realized'])}; {_levels(c)}; how it ended: {ended}{note}")
        if len(f["closed"]) > LISTED:
            lines.append(f"- and {len(f['closed']) - LISTED} more closed paper trades (in the totals above)")
    else:
        lines.append("Paper trades closed this week: none in tickers he follows.")
    if f["open"]:
        lines.append("Paper positions still open:")
        for p in f["open"][:LISTED]:
            mark = p.get("mark")
            now = f"open P&L {usd(mark['pnl'])} at the {clock(mark['at'])} price" if mark else "no price yet, so its P&L is unknown"
            lines.append(f"- {p['label']}, {_size(p, 'remaining')}: in {clock(p['opened_at'])}; {_levels(p)}; {now}")
    if f["real_closed"]:
        lines.append("Real trades closed this week:")
        for r in f["real_closed"][:LISTED]:
            lines.append(f"- {r['contract']}, {r['account']}: closed {r['closed_at']:%a %b} {r['closed_at'].day}, realised {usd(r['realized'])}")
        if len(f["real_closed"]) > LISTED:
            lines.append(f"- and {len(f['real_closed']) - LISTED} more real trades (in the totals above)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- the kept review

def _file(day: str) -> Path:
    return ROOT / f"{day}.json"


def _save(day: str, entry: dict) -> None:
    global _latest
    with _lock:
        _latest = entry
        try:
            ROOT.mkdir(parents=True, exist_ok=True)
            _file(day).write_text(json.dumps(entry))
            oldest = (date.fromisoformat(day) - timedelta(weeks=KEEP_WEEKS)).isoformat()
            for old in ROOT.glob("*.json"):
                if old.stem < oldest:
                    old.unlink(missing_ok=True)
        except OSError:
            log.warning("paper review could not be saved for %s", day, exc_info=True)


def _load(day: str) -> dict | None:
    try:
        entry = json.loads(_file(day).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        log.warning("paper review file unreadable for %s", day, exc_info=True)
        return None
    return entry if isinstance(entry, dict) and entry.get("state") == "ok" and entry.get("text") else None


def _newest() -> dict | None:
    """The newest kept review (memory, else the newest file)."""
    global _latest
    with _lock:
        if _latest is not None:
            return _latest
        try:
            names = sorted((p.stem for p in ROOT.glob("*.json")), reverse=True)
        except OSError:
            return None
        for name in names:
            if (entry := _load(name)) is not None:
                _latest = entry
                return entry
        return None


def latest() -> dict | None:
    """What the desk shows at the top of its Paper section: the newest review, with its week and date, until the next."""
    entry = _newest()
    if entry is None:
        return None
    return {"day": entry["day"], "monday": entry["monday"], "at": entry["at"], "text": entry["text"]}


# --------------------------------------------------------------------------- the review

def _today_count() -> dict | None:
    from app.ai import copilot_spend
    try:
        return copilot_spend.kind_today(KIND)
    except Exception:  # noqa: BLE001
        log.warning("Paper review count could not be read", exc_info=True)
        return None


def _facts(now: float) -> dict:
    from sqlmodel import Session
    from app.database import engine
    with Session(engine) as db:
        return facts(db, now)


async def write(now: float) -> dict:
    """Write this week's review. ``state``: ``ok`` (kept, with its ping ``pending``), ``skipped`` (no closed paper trade
    this week: no call), ``done`` (an automatic review already ran today), ``budget`` or ``error`` (``message``)."""
    from app.ai import copilot, copilot_spend
    from app.engine import day_read
    try:
        found = await asyncio.to_thread(_facts, now)
    except Exception:  # noqa: BLE001 - no review without its facts
        log.warning("paper review facts unreadable", exc_info=True)
        return {"state": "error", "message": "The paper book or the journal could not be read."}
    if not due(found):
        return {"state": "skipped", "message": "No closed paper trades this week, so no review was written."}
    before = await asyncio.to_thread(_today_count)
    if before is None or before["count"] + before["refused"] > 0:
        return {"state": "done", "message": "This week's review already ran (or its count could not be read)."}
    cfg = copilot.settings()
    if cfg.backend == "anthropic":
        spent = await asyncio.to_thread(copilot_spend.spent_today)
        if spent + day_read.HEADROOM * copilot.turn_cap(day_read.small(cfg), False) > cfg.daily_budget_usd:
            await asyncio.to_thread(copilot_spend.record_refused, kind=KIND, source="desk", backend=cfg.backend, code="daily_budget")
            return {"state": "budget", "message": f"No paper review: today's copilot budget (${cfg.daily_budget_usd:.2f}) is spent."}
    facts_text = pack(found)
    monday = date.fromisoformat(found["monday"])
    result = await day_read._run(found["day"], facts_text, cfg, now, kind=KIND,
                                 question=QUESTION.format(monday=_short(monday), pack=facts_text))
    if result["state"] != "ok":
        return result
    bad = day_read.unmatched(result["text"], facts_text)
    named = day_read.hidden_named(result["text"], found["hidden"], facts_text)
    if bad:
        log.warning("paper review quoted figures the facts do not hold: %s", ", ".join(bad))
        return {"state": "error", "cost_usd": result["cost_usd"],
                "message": f"The review quoted a figure the week's facts do not hold ({bad[0]}), so it is not shown."}
    if named:
        log.warning("paper review named %d ticker(s) he does not follow", len(named))
        return {"state": "error", "cost_usd": result["cost_usd"], "message": "The review named a ticker you do not follow, so it is not shown."}
    entry = {"state": "ok", "text": result["text"], "cost_usd": result["cost_usd"], "at": now, "day": found["day"],
             "monday": found["monday"], "facts": facts_text,
             "ping": {"state": "pending", "attempts": 0, "next_at": None, "error": None}}
    await asyncio.to_thread(_save, found["day"], entry)
    return entry


def ping_title(entry: dict) -> str:
    monday = date.fromisoformat(entry["monday"])
    return f"{TITLE} · week of {monday:%b} {monday.day}"


def _lab_on() -> bool:
    from app.ai import copilot
    return copilot.settings().enabled


class PaperReviews:
    """The review's place on the level alert monitor's loop: ``run`` writes the week's review once it is due (on its own
    thread), ``deliver`` sends its one ping."""

    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self._spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True, name="paper-review").start())
        self._last_run = 0.0
        self._done: set[str] = set()
        self._busy = False

    def run(self) -> None:
        from app.engine.week_review_auto import last_trading_day
        now = self.clock()
        if now - self._last_run < RUN_SECONDS or self._busy:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        key = moment.date().isoformat()
        if key in self._done or moment.hour * 60 + moment.minute < AT or not _lab_on():
            return
        if not last_trading_day(self.calendar, moment.date()):
            return
        if _load(key) is not None:  # written before a restart
            self._done.add(key)
            return
        self._busy = True
        self._spawn(lambda: self._write(now, key))

    def _write(self, now: float, key: str) -> None:
        try:
            entry = asyncio.run(write(now))
            log.info("Paper review for %s: %s%s", key, entry["state"], f" ({entry['message']})" if entry.get("message") else "")
        except Exception:  # noqa: BLE001
            log.exception("Paper review failed")
        finally:
            self._done.add(key)
            self._busy = False
        self.deliver()

    def deliver(self) -> None:
        """Send the newest review's ping when it is pending: at most once."""
        from sqlmodel import Session
        from app.engine import notification_policy, phone
        from app.engine.position_alerts import _surely_unsent
        now = self.clock()
        with _lock:  # the claim: pending is read and turned into sending in one step, so two passes never both send
            entry = _newest()
            ping = (entry or {}).get("ping") or {}
            if ping.get("state") != "pending" or (ping.get("next_at") and now < ping["next_at"]):
                return
            day = entry["day"]

            def mark(state: str, error: str | None = None, **more) -> None:
                entry["ping"] = {**entry["ping"], **more, "state": state, "error": error}
                _save(day, entry)
            if now - entry["at"] > EXPIRE_SECONDS:
                return mark("expired", "Not sent within 2 hours of the review, so it was not sent late.")
            if not phone.configured():
                return mark("off", "Phone pings are not set up on this server.")
            mark("sending", attempts=ping.get("attempts", 0) + 1)  # a crash from here on never sends twice
        title, body = ping_title(entry), entry["text"]
        with Session(self.engine) as db:
            ticket = notification_policy.decide(db, sender="paper_review", source_id=day, kind=KIND, title=title, body=body, now=now)
            if ticket.held:
                return mark("held", ticket.reason)
            try:
                phone.send(title, body + ticket.append, kind=KIND, priority=3, tags=("notebook",),
                           path=phone.desk_link("/copilot-lab"), direct_click=True)
            except phone.SendError as exc:
                if _surely_unsent(exc) and entry["ping"]["attempts"] < MAX_ATTEMPTS:
                    return mark("pending", str(exc)[:300], next_at=now + RETRY_SECONDS)
                notification_policy.delivered(db, ticket, now)
                db.commit()
                return mark("unknown", f"{exc} It may have reached the phone, so it was not resent."[:300])
            notification_policy.delivered(db, ticket, now)
            db.commit()
        mark("sent", sent_at=self.clock())


def fake_answer(prompt: str) -> str:
    """The scripted model's review, from the facts in its message, so the demo copies the figures exactly. Labelled
    simulated."""
    import re
    lines = prompt.splitlines()
    paper = next((ln for ln in lines if ln.startswith("Paper this week")), "Paper this week: unknown.")
    real = next((ln for ln in lines if ln.startswith("Real this week")), "Real this week: unknown.")

    def head(line: str) -> str:
        found = re.search(r"(\d+) closed, realised ([+\-]?\$[\d,]+\.\d\d)", line)
        return f"{found.group(2)} over {found.group(1)}" if found else "no closed trades"
    trades = [ln for ln in lines if ln.startswith("- ") and "realised " in ln and "how it ended" in ln]

    def realised(line: str) -> float:
        found = re.search(r"realised ([+\-]?)\$([\d,]+\.\d\d)", line)
        return (-1 if found and found.group(1) == "-" else 1) * float(found.group(2).replace(",", "")) if found else 0.0
    best = max(trades, key=realised, default=None)
    out = [f"Week: paper {head(paper)}, real {head(real)}."]
    if best:
        name = best[2:].split(",")[0]
        amount = re.search(r"realised ([+\-]?\$[\d,]+\.\d\d)", best).group(1)
        out.append(f"Worked: {name}, realised {amount} (simulated review: the scripted model does not judge why).")
        stops = [ln[2:].split(",")[0] + ": " + ln.split("how it ended: ")[1].split(";")[0] for ln in trades]
        out.append("Stops and targets: " + "; ".join(stops) + ".")
        out.append(f"Next week: set a stop and a target before the entry, as on {name}.")
    return "Simulated paper review, not Claude.\n" + "\n".join(out)
