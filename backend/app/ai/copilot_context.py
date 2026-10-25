"""The owner context pack (docs/copilot-lab.md § Owner context): what the copilot
knows about the owner before it reads a word of the question.

One compact, bounded view assembled for the turn's symbol from services that
already exist, so the model spends no tool rounds rediscovering the owner:

- ``positions``: open positions through ``copilot_book`` (its rows, marks and
  labels), each with its hold time, days to expiry, the give-back watch and
  phone alerts ``position_alerts`` keeps for it, and the plan captured before
  it (``capture_links``). The turn's symbol comes first.
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
    "positions": "measured: journal fills and current marks; give-back watch and phone alerts; a captured plan is owner said",
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

def _positions(db, symbol: str | None, now_et: datetime) -> dict:
    from app.engine import capture_links, position_alerts
    pairs, total = copilot_book.position_rows(db, limit=MAX_POSITIONS, first=symbol)
    today = now_et.date()
    rows = []
    for trade, row in pairs[:MAX_POSITIONS]:
        out = {k: v for k, v in row.items() if k not in ("mark_as_of",)}
        opened = trade.opened_at
        if opened is not None:
            opened_et = opened.replace(tzinfo=now_et.tzinfo) if opened.tzinfo is None else opened.astimezone(now_et.tzinfo)
            if opened_et.date() == today:
                out["held_minutes"] = max(0, int((now_et - opened_et).total_seconds() // 60))
        if trade.instrument_type == "option" and trade.expiration:
            out["days_to_expiry"] = (trade.expiration - today).days
            out["expires_today"] = trade.expiration == today
            watch = position_alerts.for_trade(db, trade)
            if watch.get("watch"):
                w = watch["watch"]
                out["peak_gain_usd"] = w.get("peak_gain")
                out["peak_gain_pct"] = None if w.get("peak_gain_pct") is None else round(100 * w["peak_gain_pct"], 1)
                out["giveback"] = "fired" if w.get("fired") else "armed" if w.get("armed") else "not armed"
            sent = [a for a in watch.get("alerts", []) if a.get("delivery") in ("sent", "unknown")]
            if sent:
                out["phone_alerts"] = [{"kind": a["kind"], "at": copilot_book._iso(a["detected_at"])} for a in sent[-3:]]
        plans = capture_links.for_trade(db, trade.id)
        if plans:
            plan = sorted(plans, key=lambda c: c.received_at)[0]
            out["plan"] = {k: v for k, v in {
                "setup": _trim(plan.setup_label, 60), "wording": _trim(plan.wording), "note": _trim(plan.note),
                "captured_at": copilot_book._iso(plan.received_at)}.items() if v}
        rows.append(out)
    return {"state": "ok", "count": total, "shown": len(rows), "positions": rows,
            "units": "Options: avg_entry, mark and peak are dollars per contract (premium x 100). Stocks: per share."}


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
            "note": "research_job records show title and status only; read their findings with get_saved_research"}


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


def _shed_steps(pack: dict):
    yield lambda: pack.get("history", {}).pop("recent", None)
    yield lambda: pack.get("today", {}).pop("entries", None)
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
            "\"saved\" = earlier copilot conclusions and armed watches, possibly stale. Use it before answering. Re-check market "
            "evidence with the tools; do not re-read positions, trades or memories it already shows.]\n")
    return head + json.dumps(pack, default=str, separators=(",", ":")) + "\n" + BLOCK_END + "\n\n"


def user_text(content: str) -> str:
    """The owner's own words in a prepared user message: after the context line and the owner block, if present."""
    if BLOCK_END in content:
        content = content.split(BLOCK_END + "\n\n", 1)[-1]
    if content.startswith("[Copilot Lab context:") and "]\n\n" in content:
        content = content.split("]\n\n", 1)[1]
    return content
