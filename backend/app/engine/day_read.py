"""The copilot's read of the owner's day at the close (``POST /copilot/desk/day-read``, docs/copilot-lab.md § The day read).

After the close the desk's copilot panel opens with four to six lines on his day, so he gets the takeaway without reading
the whole day report: realised and open P&L by account, which trades had a plan and which did not, the one thing that
cost or saved the most money and why, and one concrete thing to do differently tomorrow, tied to a trade from today
(``copilot_prompt.DAY_READ``). Nothing in it asks for a rating.

Facts only: the server builds the day's facts here (``facts``, ``pack``) from what the desk already reads (the journal's
trades closed and opened today, the plan streak's entry states, the plans saved today, the alert scorecard's rows, the
Robinhood account line held in memory and the order-history pass's unmatched fills, marked provisional), and the model
writes from them and the owner context block alone, with no tool. Every dollar figure in the answer must be one the pack
holds (``unmatched``): a read that quotes any other is not shown. Tickers he does not follow are left out of every part,
and an account holding one shows its open P&L from its followed positions only.

Cost:

- one read per New York day, asked by the panel on its first open after the session's close (the market calendar's,
  else 16:00) and kept for the day: in memory and in ``data/day_read/<day>.json``, so a restart shows the same read;
- one automatic call a day: once a ``day_read`` row exists for today, an automatic ask that finds nothing kept gets
  ``none`` and the panel offers Refresh; only his tap (``refresh``) writes it again;
- a day with no fills and no plans gets one line and no call (``quiet``);
- one turn: one round, no tools, ``READ_BUDGET_USD`` as its cap and ``MAX_TOKENS``, on the configured model (no cheaper
  model has held an answer shape in the eval: docs/copilot-lab.md § Follow-up model eval);
- a ``copilot_turn`` row (``kind="day_read"``) on the same ``COPILOT_DAILY_BUDGET_USD``; refused, with a zero-cost row,
  unless ``HEADROOM`` reads' worth of its cap still fits under the day's budget.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import re
import time
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

KIND = "day_read"
READ_BUDGET_USD = 0.10  # the turn's spend cap (scaled up for a model dearer than Opus, as every turn's is)
HEADROOM = 2
MAX_TOKENS = 1500
ROOT = Path(__file__).resolve().parents[2] / "data" / "day_read"
QUIET = "Nothing to read today: no fills and no plans."
QUESTION = ("Day read: {day}. Read my day from the facts below and write the close-of-day read.\n\n{pack}")
# A dollar figure: a sign before the $ only at a word's start (so "$1.20-$1.50" is two unsigned figures), or right after
# it ("$-375"), and a k or M suffix ("$1.2k"), which the facts never use.
MONEY = re.compile(r"(?:(?<![\w$.])([+\-−]))?\$\s?([+\-−]?)(\d[\d,]*(?:\.\d+)?)([kKmM]\b)?")

_kept: dict[str, dict] = {}
_lock: asyncio.Lock | None = None


def clear() -> None:
    """Forget every kept read in memory (tests)."""
    global _lock
    _kept.clear()
    _lock = None


# --------------------------------------------------------------------------- the facts

def usd(value: float) -> str:
    """A P&L figure as the read must quote it: ``+$1,204.50``, ``-$375.00``, ``$0.00``."""
    sign = "+" if value > 0 else "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def price(value: float | None) -> str:
    return "?" if value is None else f"${float(value):,.2f}"


def _clock(moment: datetime | float | None) -> str:
    """``14:05``: an epoch in New York, or a journal time (already a New York wall clock)."""
    if moment is None:
        return "?"
    local = datetime.fromtimestamp(moment, ET) if isinstance(moment, (int, float)) else moment
    return local.strftime("%H:%M")


def close_epoch(day: date) -> float:
    from app.engine import day_report
    return day_report._close_epoch(day)


def facts(db, now: float) -> dict:
    """The day's facts for the read (see the module text), tickers he does not follow left out. Raises when the
    Not-following setting cannot be read: then there is no read."""
    from sqlmodel import col, select
    from app.ai.copilot_book import _not_webull
    from app.engine import alert_scorecard, day_journal, plan_streak
    from app.engine.chart_journal import contract_label
    from app.models import Account, Trade, TradeCapture
    from app.routers import copilot_desk  # the account line and the order lines, as the desk holds them

    zone = ET
    day = datetime.fromtimestamp(now, zone).date()
    hidden = day_journal.not_following(db)
    start = datetime.combine(day, wall_time(0))  # the journal's times are New York wall clocks
    end = start + timedelta(days=1)

    week = plan_streak.streak(db, datetime.fromtimestamp(now, UTC).replace(tzinfo=None)).get("this_week") or {}
    by_trade = {e["trade_id"]: e for e in week.get("entries", [])}
    captures = {}
    ids = [e["capture_id"] for e in by_trade.values() if e.get("capture_id")]
    if ids:
        import uuid
        captures = {str(c.id): c for c in db.exec(select(TradeCapture).where(col(TradeCapture.id).in_([uuid.UUID(i) for i in ids]))).all()}

    def plan_of(trade_id: str) -> dict:
        entry = by_trade.get(trade_id)
        if entry is None:  # the plan streak does not track it: an older entry, or an untracked account or untimed fill
            return {"state": "unknown"}
        capture = captures.get(entry.get("capture_id") or "")
        words = " ".join(((capture.setup_label or "") + " " + (capture.wording or "")).split())[:160] if capture else ""
        return {"state": entry["state"], "words": words or None}

    def label(t: Trade) -> str:
        return contract_label(t.ticker, t.instrument_type, t.option_type, t.strike, t.expiration)

    pairs = db.exec(select(Trade, Account).join(Account, Account.id == Trade.account_id).where(_not_webull())
                    .where(Trade.closed_at >= start, Trade.closed_at < end)).all()
    closed = []
    for t, a in sorted(pairs, key=lambda p: p[0].closed_at):
        if t.ticker in hidden or t.realized_pnl is None:
            continue
        closed.append({"trade_id": str(t.id), "contract": label(t), "symbol": t.ticker, "account": a.name,
                       "contracts": float(t.contracts), "entry": float(t.avg_entry_premium),
                       "exit": float(t.avg_exit_premium) if t.avg_exit_premium is not None else None,
                       "realized": round(float(t.realized_pnl), 2), "opened_at": t.opened_at, "closed_at": t.closed_at,
                       "expired": bool(t.expired_worthless) or t.status == "expired", "option": t.instrument_type == "option",
                       "plan": plan_of(str(t.id))})
    realized: dict[str, float] = {}
    for c in closed:
        realized[c["account"]] = round(realized.get(c["account"], 0.0) + c["realized"], 2)

    opened_pairs = db.exec(select(Trade, Account).join(Account, Account.id == Trade.account_id).where(_not_webull())
                           .where(Trade.opened_at >= start, Trade.opened_at < end)).all()
    opened = [{"trade_id": str(t.id), "contract": label(t), "symbol": t.ticker, "account": a.name, "contracts": float(t.contracts),
               "entry": float(t.avg_entry_premium), "opened_at": t.opened_at, "still_open": t.closed_at is None,
               "option": t.instrument_type == "option", "plan": plan_of(str(t.id))}
              for t, a in sorted(opened_pairs, key=lambda p: p[0].opened_at) if t.ticker not in hidden]

    day_utc = (datetime.combine(day, wall_time(0), zone).astimezone(UTC).replace(tzinfo=None),
               datetime.combine(day + timedelta(days=1), wall_time(0), zone).astimezone(UTC).replace(tzinfo=None))
    plans = [c.underlying for c in db.exec(select(TradeCapture).where(TradeCapture.received_at >= day_utc[0],
                                                                       TradeCapture.received_at < day_utc[1])).all()
             if c.underlying not in hidden]

    since = day_utc[0].replace(tzinfo=UTC).timestamp()
    alerts = [r for r in alert_scorecard.scorecard(db, now, days=1)["rows"] if r["at"] >= since and r["symbol"] not in hidden]

    return {"day": day.isoformat(), "as_of": now, "hidden": hidden, "closed": closed, "realized": realized,
            "realized_total": round(sum(realized.values()), 2), "opened": opened, "plans": plans, "alerts": alerts,
            "accounts": copilot_desk.day_accounts(hidden), "provisional": copilot_desk.day_provisional(now, hidden)}


def quiet(f: dict) -> bool:
    """No fills (journal or provisional) and no plans: nothing to read."""
    return not (f["closed"] or f["opened"] or f["plans"] or f["provisional"])


PLAN_WORDS = {"planned": "plan saved before the entry", "late": "plan saved after the entry", "unplanned": "no plan",
              "pending": "a plan being linked", "unknown": "plan not tracked for this trade"}


def _plan(p: dict) -> str:
    return PLAN_WORDS.get(p["state"], p["state"]) + (f" (plan: {p['words']})" if p.get("words") else "")


def _size(row: dict) -> str:
    n = row["contracts"]
    count = f"{n:g}"
    return f"{count} contract{'s' if n != 1 else ''}" if row["option"] else f"{count} share{'s' if n != 1 else ''}"


def _premium(row: dict, key: str) -> str:
    """An option's price as the owner reads it (the premium a share; the journal keeps a contract's, x 100)."""
    value = row.get(key)
    if value is None:
        return "?"
    return price(value / 100 if row["option"] else value)


def pack(f: dict) -> str:
    """The facts as the model reads them. Every dollar figure here is written exactly as the read must quote it."""
    lines = [f"Today's facts ({f['day']}, as of {_clock(f['as_of'])} ET). TradeJournal's own day report; tickers the owner "
             "does not follow are left out. Every dollar figure is written exactly as it must be quoted."]
    if f["realized"]:
        parts = "; ".join(f"{name} {usd(v)}" for name, v in f["realized"].items())
        lines.append(f"Realised today (trades closed today): total {usd(f['realized_total'])}; {parts}")
    else:
        lines.append("Realised today: no trade closed today.")
    acc = f["accounts"]
    if acc["state"] == "ok" and acc["rows"]:
        parts = []
        for r in acc["rows"]:
            bit = f"{r['account']} open {usd(r['open_pnl']) if r['open_pnl'] is not None else 'unknown'}"
            if r["followed_only"]:
                bit += " (followed positions only)"
            elif r["day_change"] is not None:
                bit += f", today {usd(r['day_change'])}"
            parts.append(bit)
        lines.append(f"Open P&L now (Robinhood account line, read at {_clock(acc['as_of'])} ET): " + "; ".join(parts))
    else:
        lines.append(f"Open P&L now: the Robinhood account line is not available ({acc['state']}).")
    if f["closed"]:
        lines.append("Closed today:")
        for c in f["closed"]:
            how = "expired worthless" if c["expired"] else f"out {_clock(c['closed_at'])} at {_premium(c, 'exit')}"
            lines.append(f"- {c['contract']}, {c['account']}: {_size(c)}, in {_clock(c['opened_at'])} at {_premium(c, 'entry')}"
                         f"{' (opened ' + c['opened_at'].date().isoformat() + ')' if c['opened_at'].date().isoformat() != f['day'] else ''}, "
                         f"{how}, realised {usd(c['realized'])}; {_plan(c['plan'])}")
    still = [o for o in f["opened"] if o["still_open"]]  # the ones closed today are under Closed today
    if still:
        lines.append("Opened today, still open:")
        for o in still:
            lines.append(f"- {o['contract']}, {o['account']}: {_size(o)} in {_clock(o['opened_at'])} at {_premium(o, 'entry')}; "
                         f"{_plan(o['plan'])}")
    lines.append(f"Plans saved today: {len(f['plans'])}" + (f" ({', '.join(dict.fromkeys(f['plans']))})" if f["plans"] else ""))
    if f["alerts"]:
        lines.append("Position alerts sent today, and what followed:")
        for a in f["alerts"]:
            o = a["outcome"]
            at = f" at {a['pnl_pct_at_alert']:+g}%" if a.get("pnl_pct_at_alert") is not None else ""
            if o["state"] == "closed":
                what = (f"{'it expired' if o['how'] == 'expired' else 'you sold'} for {price(o['actual_usd'])} against "
                        f"{price(o['sell_at_alert_usd'])} at the alert ({usd(o['vs_alert_usd'])} against selling at the alert)")
            elif o["state"] == "open":
                what = f"still open; selling at the alert was {price(o['sell_at_alert_usd'])}"
            else:
                what = f"not measured ({o.get('why')})"
            lines.append(f"- {_clock(a['at'])} {a['kind_label']} on {a['contract']}{at}: {what}")
    if f["provisional"]:
        lines.append("Robinhood fills today the journal does not have yet (provisional: call them provisional if you mention them):")
        for p in f["provisional"]:
            lines.append(f"- {_clock(p['at'])} {p['action']} {p['filled']:g} {p['contract']} at {price(p['avg'])}, {p['account']} (provisional)")
    return "\n".join(lines)


def figures(text: str) -> list[tuple[str, float, str]]:
    """Each dollar figure in ``text``: (its sign, "" when none is written; its value; its k or M suffix, or "")."""
    out = []
    for before, after, digits, suffix in MONEY.findall(text):
        sign = before or after
        try:
            out.append(("-" if sign in ("-", "−") else sign, round(float(digits.replace(",", "")), 2), suffix))
        except ValueError:
            continue
    return out


def unmatched(text: str, facts_text: str) -> list[str]:
    """The dollar figures in the read that the facts do not hold (by value; a written sign must match too)."""
    held = figures(facts_text)
    values = {v for _, v, _ in held}
    signed = {(s, v) for s, v, _ in held if s}
    bad = []
    for sign, value, suffix in figures(text):
        if suffix or value not in values or (sign and (sign, value) not in signed and value != 0):
            bad.append(f"{sign}${value:,.2f}{suffix}")
    return bad


TIME_WORDS = frozenset({"ET", "AM", "PM", "EST", "EDT"})


def hidden_named(text: str, hidden: set[str], facts_text: str = "") -> list[str]:
    """Tickers he does not follow that the read names anyway (the owner context block can carry them). A one-letter
    ticker, a time word (``ET``, ``PM``) and a word the facts themselves use are ordinary words, never counted."""
    words = set(re.findall(r"[A-Z][A-Z.\-]*", facts_text)) | TIME_WORDS
    return sorted(s for s in hidden if len(s) > 1 and s not in words
                  and re.search(rf"(?<![A-Za-z]){re.escape(s)}(?![A-Za-z])", text))


# --------------------------------------------------------------------------- the kept read

def _file(day: str) -> Path:
    return ROOT / f"{day}.json"


def _load(day: str) -> dict | None:
    if day in _kept:
        return _kept[day]
    try:
        entry = json.loads(_file(day).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        log.warning("day read file unreadable for %s", day, exc_info=True)
        return None
    if not isinstance(entry, dict) or entry.get("state") != "ok" or not entry.get("text"):
        return None
    _kept[day] = entry
    return entry


def _keep(day: str, entry: dict) -> None:
    for old in [d for d in _kept if d != day]:
        _kept.pop(old, None)
    _kept[day] = entry
    if entry["state"] != "ok":
        return  # a refusal or a failure is kept for the day in memory only
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        _file(day).write_text(json.dumps(entry))
        for old in ROOT.glob("*.json"):  # only recent days stay on disk
            if old.stem < (date.fromisoformat(day) - timedelta(days=14)).isoformat():
                old.unlink(missing_ok=True)
    except OSError:
        log.warning("day read could not be saved for %s", day, exc_info=True)


def today() -> dict | None:
    from app.ai import copilot_spend
    try:
        return copilot_spend.kind_today(KIND)
    except Exception:  # noqa: BLE001
        log.warning("Day read count could not be read", exc_info=True)
        return None


def _shown(entry: dict, now: float, cached: bool) -> dict:
    return {**entry, "age_s": max(0, round(now - entry["at"])) if entry.get("at") else None, "cached": cached}


async def read(*, refresh: bool = False, now: float | None = None) -> dict:
    """The day's read. ``state``: ``early`` (the session has not closed), ``quiet`` (no fills and no plans: ``text``, no
    call), ``ok`` (``text``, ``at``, ``facts``: the facts it was written from), ``none`` (today's automatic read already
    ran and nothing is kept: Refresh writes it again), ``budget`` (``message``) or ``error`` (``message``). ``today``
    carries the day's count and cost. ``refresh`` is his tap: the only way a second read runs on one day."""
    from app.ai import copilot, copilot_spend
    asked = time.time() if now is None else now
    day = datetime.fromtimestamp(asked, ET).date()
    key = day.isoformat()
    if asked < await asyncio.to_thread(close_epoch, day):
        return {"state": "early"}
    entry = await asyncio.to_thread(_load, key)
    if entry and not refresh:
        return {**_shown(entry, asked, True), "today": await asyncio.to_thread(today)}
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        entry = _kept.get(key)
        if entry and (not refresh or (entry.get("at") or 0) >= asked):  # another request made it while this one waited
            return {**_shown(entry, asked, True), "today": await asyncio.to_thread(today)}
        try:
            found = await asyncio.to_thread(_facts, asked)
        except Exception:  # noqa: BLE001 - no read without its facts
            log.warning("day read facts unreadable", exc_info=True)
            return {"state": "error", "message": "The day report could not be read."}
        if quiet(found):  # not kept: fills that reach the journal later make it a day with something to read
            entry = {"state": "quiet", "text": QUIET, "at": asked}
            return {**_shown(entry, asked, False), "today": await asyncio.to_thread(today)}
        before = await asyncio.to_thread(today)
        if not refresh and before and before["count"] + before["refused"] > 0:
            return {"state": "none", "today": before, "message": "Today's read was written earlier. Refresh writes it again."}
        cfg = copilot.settings()
        if cfg.backend == "anthropic":
            spent = await asyncio.to_thread(copilot_spend.spent_today)
            if spent + HEADROOM * copilot.turn_cap(small(cfg), False) > cfg.daily_budget_usd:
                await asyncio.to_thread(copilot_spend.record_refused, kind=KIND, source="desk", backend=cfg.backend, code="daily_budget")
                entry = {"state": "budget", "at": asked,
                         "message": f"No read of your day: today's copilot budget (${cfg.daily_budget_usd:.2f}) is spent."}
                if not _good(key):
                    _kept[key] = entry
                return {**entry, "today": await asyncio.to_thread(today)}
        facts_text = pack(found)
        result = await _run(key, facts_text, cfg, asked)
        counted = before if before is None or "cost_usd" not in result else {
            **before, "count": before["count"] + 1, "cost_usd": round(before["cost_usd"] + result["cost_usd"], 4)}
        if result["state"] == "ok":
            bad = unmatched(result["text"], facts_text)
            named = hidden_named(result["text"], found.get("hidden") or set(), facts_text)
            if bad:
                log.warning("day read quoted figures the facts do not hold: %s", ", ".join(bad))
                result = {"state": "error", "cost_usd": result["cost_usd"],
                          "message": f"The read quoted a figure the day report does not hold ({bad[0]}), so it is not shown."}
            elif named:
                log.warning("day read named %d ticker(s) he does not follow", len(named))
                result = {"state": "error", "cost_usd": result["cost_usd"],
                          "message": "The read named a ticker you do not follow, so it is not shown."}
        entry = {**result, "at": asked, **({"facts": facts_text} if result["state"] == "ok" else {})}
        if entry["state"] == "ok" or not _good(key):  # a failed Refresh never hides the day's good read
            await asyncio.to_thread(_keep, key, entry)
        return {**_shown(entry, asked, False), "today": counted}


def _good(day: str) -> bool:
    kept = _kept.get(day)
    return bool(kept and kept.get("state") == "ok")


def _facts(now: float) -> dict:
    from sqlmodel import Session
    from app.database import engine
    with Session(engine) as db:
        return facts(db, now)


def small(cfg):
    """The read's turn settings: the configured model, one round and no tools, its own cap and output limit."""
    return dataclasses.replace(cfg, max_rounds=1, max_tool_calls=0, max_tokens=MAX_TOKENS, turn_budget_usd=READ_BUDGET_USD)


async def _run(day: str, facts_text: str, cfg, at: float) -> dict:
    """One small recorded turn: ``{"state": "ok", "text", "cost_usd"}`` or ``{"state": "error", "message"}``."""
    from app.ai import copilot, copilot_spend
    turn_cfg = small(cfg)
    try:
        adapter = await asyncio.to_thread(copilot.adapter_for, turn_cfg)
        evidence = copilot.evidence_for(turn_cfg)
    except copilot.CopilotError as exc:
        return {"state": "error", "message": exc.message}
    parts: list[str] = []
    errors: list[str] = []
    cost = 0.0
    try:
        question = QUESTION.format(day=day, pack=facts_text)
        turn = copilot_spend.recorded_turn([{"role": "user", "content": question}], None, turn_cfg, adapter, evidence,
                                           datetime.fromtimestamp(at, ET), kind=KIND, source="desk")
        async with contextlib.aclosing(turn) as events:
            async for event in events:
                if event.get("type") == "text":
                    parts.append(event.get("delta") or "")
                elif event.get("type") == "error":
                    errors.append(event.get("message") or event.get("code") or "error")
                elif event.get("type") == "done":
                    cost = float((event.get("metrics") or {}).get("cost_usd") or 0.0)
    except Exception:  # noqa: BLE001 - the row records what happened; the panel says it plainly
        log.warning("day read failed", exc_info=True)
        errors.append("The read failed.")
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()
    text = "".join(parts).strip()
    if errors or not text:
        return {"state": "error", "message": errors[0] if errors else "The copilot wrote nothing.", "cost_usd": round(cost, 4)}
    return {"state": "ok", "text": text, "cost_usd": round(cost, 4)}


def fake_answer(prompt: str) -> str:
    """The scripted model's read, from the facts in its message, so the demo copies the figures exactly. Labelled
    simulated."""
    lines = prompt.splitlines()
    realised = next((ln for ln in lines if ln.startswith("Realised today")), "Realised today: unknown.")
    opened = next((ln for ln in lines if ln.startswith("Open P&L now")), "")
    trades = [ln for ln in lines if ln.startswith("- ") and "realised " in ln]
    plans = {ln[2:].split(",")[0]: ln for ln in lines if ln.startswith("- ") and ("plan saved" in ln or "no plan" in ln)}
    with_plan = sum("plan saved before" in ln for ln in plans.values())
    total = re.search(r"total ([+\-]?\$[\d,]+\.\d\d)", realised)

    def realised_of(line: str) -> float:
        found = re.search(r"realised ([+\-]?)\$([\d,]+\.\d\d)", line)
        return (-1 if found and found.group(1) == "-" else 1) * float(found.group(2).replace(",", "")) if found else 0.0
    biggest = max(trades, key=lambda ln: abs(realised_of(ln)), default=None)
    out = [f"P&L: realised {total.group(1) if total else 'none'} today" + (f"; {opened.split(': ', 1)[1].rstrip('.')}" if opened and ": " in opened else "") + "."]
    out.append(f"Plans: {with_plan} of {len(plans)} trades had a plan saved before the entry.")
    if biggest:
        name = biggest[2:].split(",")[0]
        amount = re.search(r"realised ([+\-]?\$[\d,]+\.\d\d)", biggest).group(1)
        out.append(f"Biggest: {name}, realised {amount} (simulated read: the scripted model does not judge why).")
        out.append(f"Tomorrow: before entering a trade like {name}, save the plan first.")
    else:
        out.append("Biggest: no trade closed today.")
        out.append("Tomorrow: simulated read, not Claude.")
    return "Simulated day read, not Claude.\n" + "\n".join(out)
