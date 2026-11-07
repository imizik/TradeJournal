"""The owner context pack (docs/copilot-lab.md § Owner context): what the copilot
knows about the owner before it reads a word of the question.

One compact, bounded view assembled for the turn's symbol from services that
already exist, so the model spends no tool rounds rediscovering the owner:

- ``positions``: open positions through ``trader_context.for_symbol`` (one call a
  turn; ``copilot_book``'s rows and marks), each with its hold time, days to
  expiry, the give-back watch and phone alerts, its thesis object as ``plan``
  (plan card, Charts plan sheet, the companion's adopted draft, or ``none``) and
  the owner's decisions since the entry. The turn's symbol comes first, with its
  ``since_entry`` diff (each line with as_of and source; headlines as a count
  only, since third-party words never enter the owner block).
- ``history``: the owner's closed trades in the symbol and their total.
- ``habits``: the four exit habits of the October 21 behavior audit, the latest
  30 trades against the baseline (``exit_habits.scorecard``), cached briefly.
- ``memories``: approved memories for the symbol, then general ones.
- ``today``: the owner's day-journal entries for today (New York).
- ``investigations``: saved investigations and research results for the symbol;
  with no symbol, the open ones across every symbol.
- ``watches``: armed level alerts for the symbol, and queued or running research
  jobs that name it (question jobs) or are linked to one of its investigations
  (reassessments); Radar event jobs name an event, not a symbol, so they are not matched.
  With no symbol, armed level alerts across every symbol and every waiting job.

Every section carries a provenance label the system prompt explains: ``owner said``
(their own words), ``measured`` (journal facts) or ``saved`` (earlier conclusions,
possibly stale). A section that fails reads as ``unavailable``; the others stand.
Nothing here writes. No account number, account id, trade id, fill id or broker id
leaves this module; the only ids are saved investigations', which the model may
pass to ``get_investigation_changes``.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import nullcontext
from datetime import UTC, datetime

from app.ai import copilot_book
from app.ai.copilot_answer import ANSWER_SHAPE

log = logging.getLogger(__name__)

MAX_PACK_CHARS = 5500  # fits a tool result (copilot_tools.MAX_RESULT_CHARS) with headroom
MAX_POSITIONS = 8
MAX_SYMBOL_TRADES = 4
MAX_MEMORIES = 8
MAX_TODAY = 6
MAX_INVESTIGATIONS = 4
MAX_WATCHES = 6
MAX_WAITING_JOBS = 3  # no-symbol pack: jobs listed after up to MAX_WATCHES alerts
TEXT = 240
SHORT = 120
HABITS_TTL_S = 600

PROVENANCE = {
    "positions": "measured: journal fills and current marks; give-back watch and phone alerts; since_entry lines each name their source and as_of, and 'unavailable' means the input is missing, not zero; a plan's wording is owner said, a thesis_guess is the companion's",
    "history": "measured: the journal's closed trades in this symbol",
    "habits": "measured: the behavior audit's four exit habits, latest 30 closed long options vs. every trade before the alerts went live",
    "memories": "owner said: memories they approved (statements, theses, preferences, lessons)",
    "today": "owner said: today's day-journal entries",
    "investigations": "saved: earlier copilot conclusions and research results; re-check before relying on them",
    "watches": "saved: armed level alerts and research jobs still waiting",
}

_habits_cache: dict = {"at": 0.0, "value": None}


def _trim(text, most: int = TEXT) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= most else text[: most - 1] + "…"


def _et_now(now: datetime | None) -> datetime:
    from app.engine.chart_math import ET
    return (now or datetime.now(UTC)).astimezone(ET)


def _section(name: str, build):
    try:
        return build()
    except Exception as exc:  # one failing source must not take the pack down
        log.warning("owner context %s unavailable: %s", name, type(exc).__name__)
        return {"state": "unavailable"}


# --------------------------------------------------------------------------- sections

MAX_ROLL_NOTES = 5


GIVEBACK = {"watching": "not armed"}  # the pack's word for a watch that has not armed yet


def _plan(thesis: dict) -> dict:
    """The record's thesis as the pack shows it: the owner's words whole, the companion's marked as a guess."""
    if thesis.get("source") == "none":
        return {"source": "none"}
    level = thesis.get("invalidation") or {}
    stop = thesis.get("time_stop") or {}
    entry = thesis.get("entry_trigger") or {}
    return {k: v for k, v in {
        "source": thesis["source"], "setup": _trim(thesis.get("label"), 60),
        # The companion's guess was written by a model that had just read headlines: like a research job's conclusion it
        # stays out of the owner's turn (the desk shows it); only the owner's own wording comes here.
        "wording": _trim(thesis.get("text")) if not thesis.get("text_is_guess") else None,
        "entry": f"{entry['price']:,.2f} ({entry.get('state')})" if entry.get("price") else None,
        "invalidation": f"{level['price']:,.2f} ({level.get('state')})" if level.get("price") else None,
        "time_stop": f"{_trim(stop.get('text'), 60)} ({stop.get('state')})" if stop.get("text") else None,
        "horizon": thesis.get("horizon"), "captured_at": thesis.get("captured_at"), "timing": thesis.get("timing"),
        "revisions": [f"{r['at'][:16]} {r['by']}: {_trim(r['text'], 80)}" for r in thesis.get("revisions", [])[-2:] if r.get("text")] or None,
    }.items() if v}


def _since(since: dict) -> dict:
    """A line's ``as_of`` is shown when it differs from the diff's own (a quote's or a recording's time)."""
    at = since.get("as_of")
    return {"as_of": at, "lines": [
        {k: v for k, v in {"line": line["text"], "as_of": line.get("as_of") if line.get("as_of") != at else None,
                           "from": line.get("source")}.items() if v}
        for line in since.get("lines", [])]}


def _render(record: dict) -> dict:
    """One position of ``trader_context`` as the pack shows it: no trade id, plan in the owner's words."""
    skip = ("mark_as_of", "trade_id", "thesis", "alerts", "decisions", "since_entry", "contract", "greeks_as_of")
    out = {k: v for k, v in record.items() if k not in skip}
    if out.get("giveback"):
        out["giveback"] = GIVEBACK.get(out["giveback"], out["giveback"])
    phone = [a for a in record.get("alerts", []) if a.get("source") == "position alert"]
    if phone:
        out["phone_alerts"] = [{"kind": a["kind"], "at": a["at"]} for a in phone[-3:]]
    out["plan"] = _plan(record.get("thesis") or {"source": "none"})
    if record.get("decisions"):
        out["decisions"] = [f"{d['at'][:16]} {_trim(d['text'], 100)}" for d in record["decisions"][-2:]]
    if record.get("since_entry"):
        out["since_entry"] = _since(record["since_entry"])
    return out


def _positions(db, symbol: str | None, now_et: datetime, reads=None) -> dict:
    """The open positions through ``trader_context`` (one call a turn): the turn's symbol first, with its since-entry
    diff and headlines; every position with its thesis object."""
    from app.engine import trader_context
    found = trader_context.for_symbol(symbol, now_et.timestamp(), session=db, limit=MAX_POSITIONS, reads=reads)
    rows = [_render(r) for r in found["positions"]]
    from app.engine.option_rolls import unresolved_rolls
    unresolved = unresolved_rolls(db)
    rolls = [{"symbol": r.ticker, "contracts": float(r.contracts), "net_per_contract_usd": float(r.net_per_contract),
              "at": copilot_book._journal_time(r.executed_at)} for r in unresolved[-MAX_ROLL_NOTES:]]
    return {"state": "ok", "count": found["count"], "shown": len(rows), "positions": rows,
            **({"unresolved_rolls": rolls, "unresolved_rolls_total": len(unresolved), "unresolved_rolls_note": "The broker's email names no contracts, so these positions and "
                "their realized P&L may be wrong until this resolves: the rolled-out contract can still show as held, or as expired worthless."} if rolls else {}),
            "units": found["units"]}


def _history(db, symbol: str) -> dict:
    from sqlalchemy import func
    from sqlmodel import select
    from app.models import Account, Trade
    recent = copilot_book.trades(symbol, MAX_SYMBOL_TRADES, session=db)["trades"]
    for row in recent:
        row.pop("account", None)
    n, pnl = db.exec(select(func.count(Trade.id), func.sum(Trade.realized_pnl))
                     .join(Account, Account.id == Trade.account_id)
                     .where(Trade.ticker == symbol, Trade.status != "open").where(copilot_book._not_webull())).one()
    wins = db.exec(select(func.count(Trade.id)).join(Account, Account.id == Trade.account_id)
                   .where(Trade.ticker == symbol, Trade.status != "open", Trade.realized_pnl > 0)
                   .where(copilot_book._not_webull())).one()
    return {"state": "ok", "symbol": symbol, "closed_trades": int(n or 0), "wins": int(wins or 0),
            "realized_usd": None if pnl is None else round(float(pnl), 2), "recent": recent}


def _habits(db, now: datetime) -> dict:
    from app.engine import exit_habits
    stamp = time.monotonic()
    if _habits_cache["value"] is not None and stamp - _habits_cache["at"] < HABITS_TTL_S:
        return _habits_cache["value"]
    card = exit_habits.build(db)
    rows = []
    for habit in card["habits"]:
        recent, base = habit["recent"], habit["baseline"]
        rows.append({"habit": habit["label"],
                     "recent": f"{recent['n']} of {recent['trades']}" + (f" (+{recent['excluded']} unknown)" if recent["excluded"] else ""),
                     "baseline_pct": None if base["pct"] is None else round(100 * base["pct"], 1),
                     "recent_usd": recent["pnl"]})
    value = {"state": "ok", "as_of": copilot_book._iso(now), "since": card["go_live"], "recent_trades": card["recent_trades"],
             "baseline_trades": card["baseline_trades"], "habits": rows,
             "source": "behavior audit 2026-10-21: exits, not entries, lost the money; these are associations, not rules"}
    _habits_cache.update(at=stamp, value=value)
    return value


def clear_habits_cache() -> None:
    _habits_cache.update(at=0.0, value=None)


def _memories(db, symbol: str | None) -> dict:
    from app.engine import jo_briefing
    found = []
    if symbol:
        found += jo_briefing.memories(db, status="active", symbol=symbol, limit=MAX_MEMORIES)
    found += [m for m in jo_briefing.memories(db, status="active", limit=40) if not m.get("symbol")]
    seen, rows = set(), []
    for m in found:
        if m.get("redacted_at") or m.get("memory_id") in seen:
            continue
        seen.add(m.get("memory_id"))
        body = m.get("body") or {}
        rows.append({k: v for k, v in {"kind": body.get("kind"), "symbol": m.get("symbol"), "text": _trim(body.get("original_text")),
                                       "interpretation": _trim(body.get("interpretation"), SHORT),
                                       "saved_at": copilot_book._iso(m.get("received_at"))}.items() if v})
        if len(rows) >= MAX_MEMORIES:
            break
    return {"state": "ok", "memories": rows}


def _today(db, now_et: datetime) -> dict:
    from app.engine import day_journal
    entries = day_journal.entries(db, now_et.date())[-MAX_TODAY:]
    return {"state": "ok", "day": now_et.date().isoformat(), "entries": [
        {k: v for k, v in {"kind": e.kind, "symbol": e.symbol, "not_traded": e.not_traded or None,
                           "at": copilot_book._iso(e.created_at), "text": _trim(e.text)}.items() if v} for e in entries]}


def _investigations(db, symbol: str | None) -> dict:
    """The symbol's saved records, open first; with no symbol, the open records across every symbol, newest first."""
    from sqlmodel import col, select
    from app.engine import copilot_investigations
    from app.models import CopilotInvestigation
    if symbol:
        found = copilot_investigations.list_investigations(symbol=symbol, limit=MAX_INVESTIGATIONS * 2, session=db)
        found = sorted(found, key=lambda r: r["status"] != "open")  # open first; each group stays newest first
    else:
        found = [copilot_investigations.summary(r) for r in db.exec(
            select(CopilotInvestigation).where(CopilotInvestigation.status == "open")
            .order_by(col(CopilotInvestigation.updated_at).desc()).limit(MAX_INVESTIGATIONS)).all()]
    rows = []
    for r in found[:MAX_INVESTIGATIONS]:
        row = {"id": r["id"], "source": r["source"], "title": _trim(r["title"], 100), "status": r["status"], "updated_at": r["updated_at"]}
        if not symbol and r.get("symbol"):
            row["symbol"] = r["symbol"]
        # A research job's conclusion was written by a model that read untrusted web pages. It stays a tool result
        # (get_saved_research), never text in the owner's turn; only the owner's own conversations bring theirs here.
        if r["source"] == "copilot" and r.get("conclusion"):
            row["conclusion"] = _trim(r["conclusion"], 200)
        rows.append(row)
    return {"state": "ok", "investigations": rows,
            "note": "research_job and jo (an external model's research) records show title and status only; read their findings with get_saved_research"}


def _watches(db, symbol: str | None, investigation_ids: set[str]) -> dict:
    """Armed level alerts and waiting research jobs for the symbol (at most MAX_WATCHES in all). With no symbol, up to
    MAX_WATCHES armed alerts across every symbol, then up to MAX_WAITING_JOBS waiting jobs of any kind."""
    from sqlmodel import col, select
    from app.models import LevelAlert, ResearchJob
    query = select(LevelAlert).where(LevelAlert.state == "active")
    if symbol:
        query = query.where(LevelAlert.symbol == symbol)
    alerts = db.exec(query.order_by(col(LevelAlert.armed_at).desc()).limit(MAX_WATCHES)).all()
    rows = [{k: v for k, v in {"watch": "level alert", "symbol": None if symbol else a.symbol, "price": a.price,
                               "condition": a.condition, "interval": a.interval, "label": _trim(a.label, 60),
                               "source": a.source_kind, "armed_at": copilot_book._iso(a.armed_at)}.items()
             if v is not None and v != ""} for a in alerts]
    limit = MAX_WATCHES if symbol else len(rows) + MAX_WAITING_JOBS
    jobs = db.exec(select(ResearchJob).where(col(ResearchJob.status).in_(("queued", "running")))
                   .order_by(col(ResearchJob.created_at).desc()).limit(50)).all()
    for job in jobs:
        if len(rows) >= limit:
            break
        try:
            data = json.loads(job.input_json)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        linked = data.get("investigation_id") or data.get("from_investigation")
        if symbol is None or symbol in (data.get("symbols") or []) or (linked and str(linked) in investigation_ids):
            symbols = [s[:12] for s in data.get("symbols") or [] if isinstance(s, str)][:4] if symbol is None else None
            rows.append({k: v for k, v in {"watch": f"research job ({job.kind})", "status": job.status, "symbols": symbols,
                                           "question": _trim(data.get("question"), SHORT),
                                           "due": copilot_book._iso(job.next_attempt_at)}.items() if v})
    return {"state": "ok", "watches": rows[:limit]}


# --------------------------------------------------------------------------- the pack

def owner_context(symbol: str | None, session=None, now: datetime | None = None, bounded: bool = True) -> dict:
    """The pack for one turn. ``symbol`` orders positions and selects history, memories, investigations and watches.
    With no symbol there is no history; investigations are the open ones and watches the armed alerts and waiting jobs
    across every symbol (the lab's Open threads, ``GET /copilot/threads``). ``bounded=False`` skips the turn's size cap
    (``shed``) for that page read; each section keeps its own row caps."""
    from sqlmodel import Session
    from app.database import engine
    now_et = _et_now(now)
    symbol = symbol.upper() if symbol else None
    with (Session(engine) if session is None else nullcontext(session)) as db:
        pack: dict = {"state": "ok", "as_of": copilot_book._iso(now_et), "symbol": symbol, "provenance": PROVENANCE,
                      "positions": _section("positions", lambda: _positions(db, symbol, now_et)),
                      "habits": _section("habits", lambda: _habits(db, now_et)),
                      "memories": _section("memories", lambda: _memories(db, symbol)),
                      "today": _section("today", lambda: _today(db, now_et))}
        if symbol:
            pack["history"] = _section("history", lambda: _history(db, symbol))
        pack["investigations"] = _section("investigations", lambda: _investigations(db, symbol))
        ids = {r["id"] for r in pack["investigations"].get("investigations", [])}
        pack["watches"] = _section("watches", lambda: _watches(db, symbol, ids))
    return shed(pack) if bounded else pack


def _drop_sources(pack: dict) -> None:
    for row in pack.get("positions", {}).get("positions", []):
        for line in (row.get("since_entry") or {}).get("lines", []):
            line.pop("from", None)
        (row.get("plan") or {}).pop("revisions", None)


def _trim_diffs(pack: dict) -> None:
    """Past the first position with a diff, keep only its own mark line; the underlying, group, headline and time lines
    read nearly the same for every contract on the symbol."""
    rows = [r for r in pack.get("positions", {}).get("positions", []) if r.get("since_entry")]
    for row in rows[1:]:
        row["since_entry"]["lines"] = [line for line in row["since_entry"]["lines"] if line["line"].startswith(("mark ", "price "))]


def _slim_rows(pack: dict) -> None:
    """Past the first position, the plan's levels only: no decisions, alerts or revision notes."""
    for row in pack.get("positions", {}).get("positions", [])[1:]:
        row.pop("decisions", None)
        row.pop("phone_alerts", None)
        plan = row.get("plan") or {}
        for key in ("wording", "captured_at", "timing", "revisions", "entry"):
            plan.pop(key, None)


def _shed_steps(pack: dict):
    yield lambda: pack.get("history", {}).pop("recent", None)
    yield lambda: pack.get("today", {}).pop("entries", None)
    yield lambda: _drop_sources(pack)
    yield lambda: _trim_diffs(pack)
    yield lambda: _slim_rows(pack)
    yield lambda: pack.get("investigations", {}).pop("investigations", None)
    yield lambda: pack.get("memories", {}).pop("memories", None)
    yield lambda: pack.get("positions", {}).update(positions=pack["positions"].get("positions", [])[:3],
                                                   shown=min(3, len(pack["positions"].get("positions", []))))
    yield lambda: pack.pop("provenance", None)


def shed(pack: dict) -> dict:
    """Drop the least decision-relevant parts until the pack fits ``MAX_PACK_CHARS`` (positions and habits last)."""
    for step in _shed_steps(pack):
        if len(json.dumps(pack, default=str, separators=(",", ":"))) <= MAX_PACK_CHARS:
            return pack
        step()
        pack["trimmed"] = True
    return pack


def summary(pack: dict) -> str:
    """One line for the UI's evidence row."""
    if pack.get("state") != "ok":
        return (pack.get("reason") or "unavailable")[:160]
    parts = []
    held = pack.get("positions", {})
    if held.get("state") == "ok":
        focus = next((p for p in held.get("positions", []) if p.get("symbol") == pack.get("symbol")), None)
        note = ""
        if focus and focus.get("unrealized_pct") is not None:
            note = f" ({focus['symbol']} {focus['unrealized_pct']:+.1f}%" + (f", give-back {focus['giveback']}" if focus.get("giveback") in ("armed", "fired") else "") + ")"
        parts.append(f"{held.get('count', 0)} open{note}")
    for key, label in (("memories", "memories"), ("investigations", "investigations"), ("watches", "watches"), ("today", "notes today")):
        section = pack.get(key, {})
        if section.get("state") == "ok":
            rows = section.get(key if key != "today" else "entries", [])
            if rows:
                parts.append(f"{len(rows)} {label}")
    history = pack.get("history", {})
    if history.get("state") == "ok" and history.get("closed_trades"):
        parts.append(f"{history['closed_trades']} past trades in {history['symbol']}")
    missing = [k for k, v in pack.items() if isinstance(v, dict) and v.get("state") == "unavailable"]
    if missing:
        parts.append("unavailable: " + ", ".join(missing))
    return (" · ".join(parts) or "nothing on file")[:160]


BLOCK_END = "[end of owner context]"


def block(pack: dict) -> str:
    """The text that precedes the owner's message: framed so the model never mistakes it for their words."""
    head = ("[Owner context, assembled by TradeJournal for this turn; not the owner's message. Labels: \"owner said\" = their own "
            "words (memories, today's notes, a captured plan); \"measured\" = journal facts (positions, trades, habit counts); "
            "\"saved\" = earlier copilot conclusions and armed watches, possibly stale. Use it before answering. Read market "
            "evidence with the tools (or the earlier evidence, when it covers the question); do not re-read positions, "
            "trades or memories it already shows.]\n")
    return head + json.dumps(pack, default=str, separators=(",", ":")) + "\n" + BLOCK_END + "\n\n"


def user_text(content: str) -> str:
    """The owner's own words in a prepared user message: after the context line and the owner block, and before the
    answer-shape reminder, when present."""
    content = content.removesuffix("\n\n" + ANSWER_SHAPE)
    if BLOCK_END in content:
        content = content.split(BLOCK_END + "\n\n", 1)[-1]
    if content.startswith("[Copilot Lab context:") and "]\n\n" in content:
        content = content.split("]\n\n", 1)[1]
    return content
