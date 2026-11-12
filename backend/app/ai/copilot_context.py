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
  only, since third-party words never enter the owner block). A ticker the owner
  set to not followed on the desk is left out of the rows and the count and named
  once in ``not_followed``, unless it is the turn's own symbol.
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
- ``practice``: the active practice goal the owner confirmed from a week review card
  (``practice_goal.current``): its words, measure, target and this week's count so far.
- ``market`` (added by ``with_market`` from ``market``, read beside the pack through the
  turn's own evidence, so live, fixture and replay each answer as their tools do): SPY,
  QQQ and VIX; for the symbol its quote, off-hours move, sector ETF, Radar group against
  SPY and today's Radar events that name it; with no symbol, the day's Radar leaders and
  laggards. Each line carries its as_of and source; a read that fails or runs past
  ``MARKET_TIMEOUT_S`` is listed as unavailable and never holds the turn.

Every section carries a provenance label the system prompt explains: ``owner said``
(their own words), ``measured`` (journal facts) or ``saved`` (earlier conclusions,
possibly stale). A section that fails reads as ``unavailable``; the others stand.
Nothing here writes. No account number, account id, trade id, fill id or broker id
leaves this module; the only ids are saved investigations', which the model may
pass to ``get_investigation_changes``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import nullcontext
from datetime import UTC, datetime

from app.ai import copilot_book
from app.ai.copilot_answer import ANSWER_SHAPE

log = logging.getLogger(__name__)

MAX_PACK_CHARS = 5500  # fits a tool result (copilot_tools.MAX_RESULT_CHARS) with headroom
MAX_MARKET_CHARS = 1400  # the turn's block also carries the market section (never a tool result): its own room
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
PRACTICE_TTL_S = 120
MARKET_TIMEOUT_S = 3.0  # the market reads run beside the pack read; past this they read as unavailable
MAX_MARKET_EVENTS = 3
MAX_MOVERS = 3

PROVENANCE = {
    "positions": "measured: journal fills and current marks; give-back watch and phone alerts; since_entry lines each name their source and as_of, and 'unavailable' means the input is missing, not zero; a plan's wording is owner said, a thesis_guess is the companion's",
    "history": "measured: the journal's closed trades in this symbol",
    "habits": "measured: the behavior audit's four exit habits, latest 30 closed long options vs. every trade before the alerts went live",
    "memories": "owner said: memories they approved (statements, theses, preferences, lessons)",
    "today": "owner said: today's day-journal entries",
    "investigations": "saved: earlier copilot conclusions and research results; re-check before relying on them",
    "watches": "saved: armed level alerts and research jobs still waiting",
    "practice": "owner said: the goal they confirmed from a week review; this_week measured",
}
MARKET_PROVENANCE = "measured: quotes, the regime and Radar read for this turn, each line with its as_of and source"

_habits_cache: dict = {"at": 0.0, "value": None}
_practice_cache: dict = {"at": 0.0, "day": None, "value": None}


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
    diff and headlines; every position with its thesis object. With the Robinhood feed on, its cached snapshot
    (``copilot_book.live_book``, never a new read): fresh, the positions it shows carry its numbers and the ones only it
    shows are added with no plan, the turn's symbol first; otherwise one note says the live numbers are unavailable."""
    from app.engine import trader_context
    # A ticker hidden on the desk collapses to one line, unless the turn is about it; the limit grows so it never
    # pushes a followed position out. A Robinhood-only position in a hidden ticker is named on that line too.
    hidden, quiet = hidden_positions(db, symbol)
    live = copilot_book.live_or_unavailable(db, now_et)
    found = trader_context.for_symbol(symbol, now_et.timestamp(), session=db, limit=MAX_POSITIONS + len(quiet), reads=reads,
                                      live=live)
    rows = [_render(r) for r in found["positions"] if r["symbol"] not in hidden][:MAX_POSITIONS]
    fresh = (live or {}).get("new", [])
    new = [{**{k: v for k, v in r.items() if k != "mark_as_of"}, "plan": {"source": "none"}} for r in fresh if r["symbol"] not in hidden]
    if new:  # the turn's symbol (the journal's, then new), then the other new ones, then the journal's rest
        def order(row: dict) -> int:
            return (0 if row.get("journal") is None else 1) if row["symbol"] == symbol else (2 if row.get("journal") else 3)
        rows = sorted(rows + new, key=order)[:MAX_POSITIONS]
    count = found["count"] - len(quiet) + len(new)
    quiet = sorted(quiet + [r["symbol"] for r in fresh if r["symbol"] in hidden])
    from app.engine.option_rolls import unresolved_rolls
    unresolved = unresolved_rolls(db)
    rolls = [{"symbol": r.ticker, "contracts": float(r.contracts), "net_per_contract_usd": float(r.net_per_contract),
              "at": copilot_book._journal_time(r.executed_at)} for r in unresolved[-MAX_ROLL_NOTES:]]
    note = copilot_book.live_note(live)
    return {"state": "ok", "count": count, "shown": len(rows), "positions": rows,
            **({"not_followed": not_followed_line(quiet)} if quiet else {}),
            **({"robinhood": note} if note is not None else {}),
            **({"unresolved_rolls": rolls, "unresolved_rolls_total": len(unresolved), "unresolved_rolls_note": "The broker's email names no contracts, so these positions and "
                "their realized P&L may be wrong until this resolves: the rolled-out contract can still show as held, or as expired worthless."} if rolls else {}),
            "units": found["units"]}


def hidden_positions(db, symbol: str | None = None) -> tuple[set[str], list[str]]:
    """The tickers set to not followed on the desk (less the turn's own ``symbol``) and one entry per open position in
    them (the book's own rows: Webull left out), read from the journal so a large book never hides one uncounted."""
    from sqlmodel import select
    from app.engine import day_journal
    from app.models import Account, Trade
    hidden = day_journal.quiet(db) - {symbol}
    if not hidden:
        return hidden, []
    tickers = db.exec(select(Trade.ticker).join(Account, Account.id == Trade.account_id)
                      .where(Trade.status == "open", Trade.ticker.in_(hidden)).where(copilot_book._not_webull())).all()
    return hidden, sorted(tickers)


def not_followed_line(symbols: list[str]) -> str:
    """'2 positions not followed: SLS, TE (...)', the one line a hidden ticker's positions get in a pack."""
    names = ", ".join(dict.fromkeys(symbols))
    return (f"{len(symbols)} position{'' if len(symbols) == 1 else 's'} not followed: {names} (hidden on the desk; "
            "not counted above, and not raised unless he asks about one by name)")


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
    _practice_cache.update(at=0.0, day=None, value=None)


def _practice(db, now_et: datetime) -> dict:
    """The active practice goal and this week's count so far (``GET /copilot/practice``), cached briefly: scoring
    reads the week's trades."""
    from app.engine import practice_goal
    stamp, day = time.monotonic(), now_et.date()
    if _practice_cache["value"] is not None and _practice_cache["day"] == day and stamp - _practice_cache["at"] < PRACTICE_TTL_S:
        return _practice_cache["value"]
    found = practice_goal.current(db, day)
    goal, week = found["goal"], found["this_week"]
    if goal is None:
        value = {"state": "ok", "goal": None}
    else:
        value = {k: v for k, v in {
            "state": "ok", "goal": _trim(goal["text"], SHORT), "measure": goal["label"], "target": goal["target"],
            "since": goal["since"],
            "this_week": f"{week['text']} {week['of_what']}" + ("" if week.get("met") is None else (" (met)" if week["met"] else " (not met yet)"))
            if week else f"starts the week of {goal['week_start']}",
            "as_of": copilot_book._iso(now_et)}.items() if v is not None}
    _practice_cache.update(at=stamp, day=day, value=value)
    return value


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
        pack["practice"] = _section("practice", lambda: _practice(db, now_et))
    return shed(pack) if bounded else pack


# --------------------------------------------------------------------------- the market read

def _pct_text(value) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _line(text: str, as_of, source: str) -> dict:
    return {k: v for k, v in {"line": text, "as_of": as_of, "from": source}.items() if v}


def _extended_line(symbol: str, block: dict | None) -> dict | None:
    """The symbol's off-hours move from a quote or regime read's ``extended`` block (pre-market, after-hours or the
    last session's after-hours), or None during the regular session."""
    if not block or symbol not in (block.get("symbols") or {}):
        return None
    row = block["symbols"][symbol]
    for key, label in (("premarket", "pre-market"), ("today", "after-hours"), ("last_session", "last after-hours")):
        part = row.get(key)
        part = part.get("after_hours") if isinstance(part, dict) and "after_hours" in part else part
        if isinstance(part, dict) and part.get("change_pct") is not None:
            return _line(f"{symbol} {label} {_pct_text(part['change_pct'])} at {part.get('last')}"
                         + (f" ({part['last_at']} ET)" if part.get("last_at") else ""), block.get("as_of"), "chart feed minute bars")
    return None


def _group_line(symbol: str, found: dict) -> dict | None:
    """The symbol against its Radar group's median and SPY since the open, and the last 15 minutes' breadth."""
    if found.get("state") != "ok" or not found.get("group"):
        return None
    session = found.get("session_context") or {}
    rows = {r["symbol"]: r for r in session.get("rows") or []}
    peers = sorted(r["change_pct"] for r in session.get("rows") or [] if r.get("role") == "peer" and r.get("change_pct") is not None)
    mine, spy = (rows.get(symbol) or {}).get("change_pct"), (rows.get("SPY") or {}).get("change_pct")
    median = peers[len(peers) // 2] if peers else None
    text = (f"{found['group']}: {symbol} {_pct_text(mine)} since the open vs group median {_pct_text(median)}, "
            f"SPY {_pct_text(spy)}")
    recent = found.get("recent_15m") or {}
    cover = recent.get("coverage") or {}
    if cover.get("peers_total"):
        own = next((r["change_pct"] for r in recent.get("rows") or [] if r["symbol"] == symbol), None)
        text += f"; last 15 min {cover.get('peers_up', 0)} of {cover['peers_total']} peers up, {symbol} {_pct_text(own)}"
    return _line(text, found.get("generated_at"), "Radar group comparison (sampled passes)")


def market_section(symbol: str | None, reads: dict, label: str = "") -> dict:
    """The pack's ``market`` section from the turn's reads: ``reads`` maps ``quotes``, ``regime``, ``group`` and
    ``radar`` to a tool result, or to a short reason when that read failed or was slow. Pure: tests feed it results."""
    lines: list[dict] = []
    missing = {name: value for name, value in reads.items() if isinstance(value, str)}
    got = {name: value for name, value in reads.items() if isinstance(value, dict)}
    quotes, regime, group, radar = (got.get(k) or {} for k in ("quotes", "regime", "group", "radar"))
    if quotes and quotes.get("state") != "ok":
        missing["quotes"] = quotes.get("reason") or quotes.get("issue") or "no quotes"
    q = quotes.get("quotes") or {}
    vix = regime.get("vix") or {}
    parts = [f"{s} {_pct_text(q[s].get('change_pct'))}" for s in ("SPY", "QQQ") if q.get(s)]
    indices = ((regime.get("radar") or {}).get("indices") or {}) if not parts else {}
    parts += [f"{s} {_pct_text(row.get('day_pct'))}" for s, row in indices.items() if s in ("SPY", "QQQ") and row]
    if vix.get("state") == "ok":
        parts.append(f"VIX {vix.get('last')} ({_pct_text(vix.get('change_pct'))})")
    if parts:
        source = "quotes" if q.get("SPY") or q.get("QQQ") else "Radar pass"
        lines.append(_line("day change " + " · ".join(parts), quotes.get("fetched_at") if source == "quotes" else
                           (regime.get("radar") or {}).get("pass_at"), source + (", VIX index quote" if vix.get("state") == "ok" else "")))
    if symbol:
        mine = q.get(symbol)
        if mine and mine.get("last") is not None:
            lines.append(_line(f"{symbol} last {mine['last']}, {_pct_text(mine.get('change_pct'))} on the day",
                               mine.get("trade_time") or quotes.get("fetched_at"), quotes.get("source_note") or "quote"))
        elif quotes:
            missing.setdefault("quote", f"no quote for {symbol}")
        ext = _extended_line(symbol, quotes.get("extended")) or _extended_line(symbol, regime.get("extended"))
        if ext:
            lines.append(ext)
        sector = (regime.get("radar") or {}).get("sector") or {}
        if sector.get("state") == "ok":
            lines.append(_line(f"sector {sector['etf']} {_pct_text(sector.get('day_pct'))}; {symbol} "
                               f"{sector.get('symbol_vs_sector_pct'):+.2f} pts vs {sector['etf']}" if sector.get("symbol_vs_sector_pct") is not None
                               else f"sector {sector['etf']} {_pct_text(sector.get('day_pct'))}",
                               (regime.get("radar") or {}).get("pass_at"), "Radar pass"))
        elif sector.get("reason"):
            missing["sector"] = sector["reason"]
        line = _group_line(symbol, group) if group else None
        if line:
            lines.append(line)
        elif group and group.get("state") not in ("ok", None):
            missing["group"] = group.get("reason") or group.get("state")
    out: dict = {"state": "ok" if lines or radar.get("state") == "ok" else "unavailable", "lines": lines}
    if radar.get("state") == "ok":
        at = radar.get("as_of")
        events = [e for e in radar.get("events") or [] if not symbol or symbol in (e.get("symbols") or [])]
        if events:
            out["radar_events"] = [{"line": _trim(e.get("summary"), 200), "first_seen": e.get("first_seen_at"),
                                    **({"now": (e.get("latest") or {}).get("status")} if (e.get("latest") or {}).get("status") else {})}
                                   for e in events[:MAX_MARKET_EVENTS]]
            out["radar_events_total"] = max(len(events), radar.get("events_total") or 0)
        movers = radar.get("movers") or {}
        if not symbol and movers:
            def ranked(rows):
                return ", ".join(f"{r['symbol']} {r['vs_spy']:+.2f}" for r in rows[:MAX_MOVERS] if r.get("vs_spy") is not None)
            if movers.get("leaders"):
                out["leaders_vs_spy"] = ranked(movers["leaders"])
            if movers.get("laggards"):
                out["laggards_vs_spy"] = ranked(movers["laggards"])
            out["movers_as_of"] = movers.get("pass_at") or at
        out["radar_session"] = radar.get("session") + (" (prior session)" if radar.get("prior_session") else "") if radar.get("session") else None
    elif radar:
        missing["radar"] = radar.get("reason") or radar.get("state")
    if label == "fixture":
        out["simulated"] = True
    if missing:
        out["unavailable"] = {k: _trim(str(v), 100) for k, v in missing.items()}
    return {k: v for k, v in out.items() if v not in (None, [], {})} | {"state": out["state"]}


def _market_reads(evidence, symbol: str | None) -> dict:
    """The reads the market section takes, each the same call the matching tool makes for this evidence."""
    # The symbol's quote is the prefetch's own call (copilot.prefetch), so live it is one Tradier read through the chart
    # feed's 15 s cache; the indices come from the regime's Radar pass, which is read anyway.
    reads = {"regime": lambda: evidence.get_market_regime(symbol),
             # A symbol passed as the group reads the events that name it, so a busy session never pushes them out.
             "radar": lambda: evidence.get_radar_today(symbol, 12)}
    if symbol:
        reads["quotes"] = lambda: evidence.get_quotes([symbol])
        reads["group"] = lambda: evidence.get_group_comparison(symbol)
    return reads


def _settle(task: asyncio.Future) -> None:
    if not task.cancelled():
        task.exception()  # retrieved, so a slow read that fails later logs nothing


async def market(evidence, symbol: str | None, timeout: float = MARKET_TIMEOUT_S) -> dict | None:
    """The ``market`` section for one turn, read side by side (worker threads) and never raising: a read that fails or
    is still running at ``timeout`` reads as unavailable. None when the evidence has no market reads."""
    if not all(hasattr(evidence, name) for name in ("get_quotes", "get_market_regime", "get_radar_today")):
        return None
    symbol = symbol.upper() if symbol else None
    try:
        tasks = {name: asyncio.ensure_future(asyncio.to_thread(read)) for name, read in _market_reads(evidence, symbol).items()}
        await asyncio.wait(tasks.values(), timeout=timeout)
        reads: dict = {}
        for name, task in tasks.items():
            if not task.done():
                task.add_done_callback(_settle)
                reads[name] = f"slower than {timeout:g} s"
            elif task.exception() is not None:
                log.info("copilot market read %s unavailable: %s", name, type(task.exception()).__name__)
                reads[name] = "the read failed"
            else:
                reads[name] = task.result()
        return market_section(symbol, reads, getattr(evidence, "label", ""))
    except Exception as exc:  # noqa: BLE001 - the market lines are a head start; the tools still answer
        log.warning("copilot market section unavailable: %s", type(exc).__name__)
        return {"state": "unavailable", "unavailable": {"market": "the market read failed"}}


def with_market(pack: dict, section: dict | None) -> dict:
    """The pack with ``market`` placed after its header (as_of, symbol), then shed to the cap again."""
    if section is None:
        return pack
    head = {k: pack[k] for k in ("state", "as_of", "symbol", "simulated", "note", "reason") if k in pack}
    out = {**head, "market": section, **{k: v for k, v in pack.items() if k not in head}}
    if isinstance(out.get("provenance"), dict):
        out["provenance"] = {**out["provenance"], "market": MARKET_PROVENANCE}
    return shed(out, MAX_PACK_CHARS + MAX_MARKET_CHARS) if out.get("state") == "ok" else out


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


LIVE_EXTRAS = ("bid", "ask", "day_change_pct", "gamma", "theta", "vega")  # Robinhood's; mark, P&L, delta and IV stay


def _slim_rows(pack: dict) -> None:
    """Past the first position, the plan's levels only: no decisions, alerts or revision notes, and of Robinhood's
    numbers only the mark, P&L, quantity, delta and IV."""
    for row in pack.get("positions", {}).get("positions", [])[1:]:
        row.pop("decisions", None)
        row.pop("phone_alerts", None)
        for key in LIVE_EXTRAS:
            row.pop(key, None)
        plan = row.get("plan") or {}
        for key in ("wording", "captured_at", "timing", "revisions", "entry"):
            plan.pop(key, None)


def _slim_market(pack: dict) -> None:
    """One Radar event and no source labels on the market lines (their as_of stays)."""
    market = pack.get("market") or {}
    if market.get("radar_events"):
        market["radar_events"] = market["radar_events"][:1]
    for line in market.get("lines", []):
        line.pop("from", None)


def _shed_steps(pack: dict):
    yield lambda: pack.get("history", {}).pop("recent", None)
    yield lambda: pack.get("today", {}).pop("entries", None)
    yield lambda: _slim_market(pack)
    yield lambda: _drop_sources(pack)
    yield lambda: _trim_diffs(pack)
    yield lambda: _slim_rows(pack)
    yield lambda: pack.get("investigations", {}).pop("investigations", None)
    yield lambda: pack.get("memories", {}).pop("memories", None)
    yield lambda: [pack.get("market", {}).pop(k, None) for k in ("radar_events", "leaders_vs_spy", "laggards_vs_spy", "unavailable")]
    yield lambda: pack.get("positions", {}).update(positions=pack["positions"].get("positions", [])[:3],
                                                   shown=min(3, len(pack["positions"].get("positions", []))))
    yield lambda: (pack.pop("provenance", None), (pack.get("positions", {}).get("robinhood") or {}).pop("units", None))


def shed(pack: dict, most: int = MAX_PACK_CHARS) -> dict:
    """Drop the least decision-relevant parts until the pack fits ``most`` characters (positions and habits last; the
    market lines and the practice goal are never dropped, only slimmed)."""
    for step in _shed_steps(pack):
        if len(json.dumps(pack, default=str, separators=(",", ":"))) <= most:
            return pack
        step()
        pack["trimmed"] = True
    return pack


def summary(pack: dict) -> str:
    """One line for the UI's evidence row."""
    if pack.get("state") != "ok":
        lines = len((pack.get("market") or {}).get("lines", []))
        return ((pack.get("reason") or "unavailable") + (f" · {lines} market lines" if lines else ""))[:160]
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
    if (pack.get("practice") or {}).get("goal"):
        parts.append("practice goal")
    market = pack.get("market") or {}
    if market.get("state") == "ok":
        parts.append(f"{len(market.get('lines', []))} market lines" + (f", {market['radar_events_total']} Radar events"
                                                                       if market.get("radar_events_total") else ""))
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
            "words (memories, today's notes, a captured plan, the practice goal); \"measured\" = journal facts and market reads "
            "(positions, trades, habit counts, quotes, Radar); "
            "\"saved\" = earlier copilot conclusions and armed watches, possibly stale. Use it before answering. The market "
            "section's lines were read for this turn, each with its as-of: fresh enough to answer from, so do not re-read "
            "them; use the tools for anything beyond them (charts, news, other symbols, older windows) or for a line marked "
            "unavailable. Do not re-read positions, trades or memories it already shows.]\n")
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
