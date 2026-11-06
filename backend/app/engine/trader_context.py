"""One record per open position: its thesis and what changed since the entry (docs/copilot-lab.md § Trader context).

The Desk header, Charts' Holding context, the Dashboard's Act now rows, position alert and companion phone bodies and
the copilot's owner pack all read this one record instead of rebuilding a position's plan on their own. It is built
only from readers that already exist; nothing here writes, arms, sends or places anything.

- ``thesis``: where the position's plan came from and what it says. ``source`` is ``plan_card`` (a confirmed Copilot
  Lab plan card: its capture, entry and invalidation level alerts and time stop), ``plan_sheet`` (a Charts plan capture
  linked to the trade: the owner's words; its chart levels are annotations, not rules), ``companion`` (the position
  companion's adopted draft, ``engine/position_companion.py``) or ``none`` (an unplanned position still gets a record).
  It carries the thesis text, entry trigger, invalidation, time stop, horizon (the owner's newest pick on the desk,
  else the plan's), and ``revisions`` (capture notes, companion updates, horizon changes). A plan card and a companion
  adoption produce the same shape, so every reader treats them alike.
- ``alerts``: the position's phone alerts sent (``position_alerts.for_trade``) and its plan's level alerts hit.
- ``decisions``: the owner's Holding / Exiting / Why entries on the desk since the entry (``day_journal``).
- ``since_entry``: deterministic lines, each with ``state`` (``ok`` or ``unavailable``, never a zero standing in for a
  missing input), ``as_of`` and ``source``: the underlying vs its price at the entry fill and vs the invalidation; the
  group vs SPY since the entry (Radar's same-session since-entry comparison, ``radar_entry``: today's regular-session
  entries only); the option mark vs the entry premium; IV now vs at the fill; headlines since the entry (the news
  reader, only when asked: it is a provider read); time held vs the horizon, time stop or expiry.

``for_symbol`` and ``for_day`` are the two entry points; ``records`` builds rows for a book a caller already read
(``copilot_book.position_rows``) so a page never reads marks twice. ``phone_line`` is the one-line "Since you entered"
for phone bodies: database and frozen-snapshot reads only, no provider call, so a send never waits on a quote.
No account number or broker id leaves this module; the only ids are trade ids (server-side callers) and the plan's
investigation id.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import math
import re
import threading
import time as _time
from typing import Callable

from sqlmodel import Session, select

log = logging.getLogger(__name__)

SOURCES = ("plan_card", "plan_sheet", "companion", "none")
MAX_POSITIONS = 8
MAX_REVISIONS = 6
MAX_ALERTS = 6
MAX_DECISIONS = 4
MAX_HEADLINES = 3
TEXT = 240
UNAVAILABLE = "unavailable"


def _trim(text, most: int = TEXT) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= most else text[: most - 1] + "…"


def _utc_iso(moment: datetime | None) -> str | None:
    """A naive UTC datetime as an ISO string (the journal's stamps for alerts, entries and pings)."""
    if moment is None:
        return None
    return (moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)).isoformat(timespec="seconds")


def _ny_iso(moment: datetime | None) -> str | None:
    """A naive New York wall clock (fills, trades) as an ISO string with its offset."""
    from app.engine.chart_math import ET
    if moment is None:
        return None
    return (moment.replace(tzinfo=ET) if moment.tzinfo is None else moment.astimezone(ET)).isoformat(timespec="seconds")


def _ny(moment: datetime) -> datetime:
    from app.engine.chart_math import ET
    return moment.replace(tzinfo=ET) if moment.tzinfo is None else moment.astimezone(ET)


def _utc_naive(moment: datetime) -> datetime:
    return _ny(moment).astimezone(UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------- injectable reads


def _read_quotes(symbols: list[str]) -> tuple[dict[str, float], str | None]:
    """Underlying last prices through the book's own stock-quote reader (one batched read, its 60-second cache)."""
    from app.engine.quotes import get_stock_quotes
    found = get_stock_quotes(symbols) or {}
    last = {s: float(v) for s, v in found.items() if isinstance(v, (int, float)) and v > 0}
    return last, datetime.now(UTC).isoformat(timespec="seconds") if last else None


def _read_group(db: Session, trade, now: float) -> dict:
    """Radar's since-entry group comparison for the trade, as ``GET /radar/groups/compare?trade_id=`` returns it."""
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_math import ET, session_windows
    from app.engine.radar_comparison import empty_comparison
    from app.engine.radar_entry import compare_resolved_entry, resolve_entry
    from app.engine.radar_store import load_universe
    from app.routers import radar
    result = empty_comparison(trade.ticker.upper(), None, load_universe(), now)
    if not resolve_entry(db, trade, result, now):
        return result
    if result["group"] is None:
        return {**result, "reason": result.get("reason") or "This symbol is in no recorded Radar group."}
    store, reason = radar._store(read_only=True)
    if store is None:
        return {**result, "state": "off", "reason": reason}
    clock = datetime.fromtimestamp(now, ET)
    try:
        hours = chart_calendar.hours(clock.date())
    except Exception:  # noqa: BLE001
        hours = None
    if hours is None:
        return {**result, "reason": "Market calendar unavailable; cannot identify the current recording session."}
    window = next((w[1:] for w in session_windows(clock.date(), hours) if w[0] == "regular"), None)
    live = bool(window and window[0] <= clock.hour * 60 + clock.minute < window[1])
    return compare_resolved_entry(store, result, now, window, live)


NEWS_TTL_S = 120  # the desk header and Charts refresh each minute, and every turn about a held symbol reads it
_news: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_news_lock = threading.Lock()


def _read_news(symbol: str, since: datetime, now: datetime) -> list[dict]:
    """Headlines naming the symbol since the entry, one provider read per symbol and entry every ``NEWS_TTL_S``."""
    from app.engine import news
    key, clock = (symbol, since.isoformat(timespec="minutes")), _time.monotonic()
    with _news_lock:
        hit = _news.get(key)
        if hit and clock - hit[0] < NEWS_TTL_S:
            return hit[1]
    found = news.fetch_news(symbols=[symbol], start=since, end=now, limit=20, fast=True, strict=True)
    with _news_lock:
        for stale in [k for k, (at, _) in _news.items() if clock - at >= NEWS_TTL_S]:
            del _news[stale]
        _news[key] = (clock, found)
    return found


@dataclass
class Reads:
    """The provider-backed reads, replaceable in tests. ``quotes`` -> (last by symbol, as_of); ``group`` -> a Radar
    comparison dict; ``news`` -> articles ``{headline, source, created_at, url}``."""
    quotes: Callable[[list[str]], tuple[dict[str, float], str | None]] = lambda symbols: _read_quotes(symbols)
    group: Callable[[Session, object, float], dict] = lambda db, trade, now: _read_group(db, trade, now)
    news: Callable[[str, datetime, datetime], list[dict]] = lambda symbol, since, now: _read_news(symbol, since, now)


@dataclass
class _Book:
    """What one build reads once for every position: adopted rows, horizons, quotes."""
    adopted: dict = field(default_factory=dict)
    horizons: dict = field(default_factory=dict)
    last: dict = field(default_factory=dict)
    quotes_as_of: str | None = None
    quotes_failed: bool = False


# --------------------------------------------------------------------------- the entry fill


def _first_entry(db: Session, trade):
    from sqlalchemy import func
    from app.models import Fill, TradeFill
    return db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id).where(
        TradeFill.trade_id == trade.id, TradeFill.role == "entry", Fill.account_id == trade.account_id)
        .order_by(Fill.executed_at, func.coalesce(Fill.raw_email_id, ""), Fill.id).limit(1)).first()


def _entry_facts(db: Session, trade) -> dict:
    """The underlying's price and the option's IV at the first entry fill, with where each came from."""
    from app.models import FillMarketContext
    fill = _first_entry(db, trade)
    if fill is None:
        return {}
    out: dict = {"filled_at": _ny_iso(fill.executed_at)}
    context = db.get(FillMarketContext, fill.id)
    if context is not None and context.entry_underlying_price:
        out["underlying"] = float(context.entry_underlying_price)
        out["underlying_source"] = f"fill context ({context.data_source})"
    elif fill.underlying_price_at_fill:
        out["underlying"] = float(fill.underlying_price_at_fill)
        out["underlying_source"] = "fill enrichment"
    if fill.iv_at_fill is not None:
        out["iv_pct"] = round(float(fill.iv_at_fill) * 100, 1)
    return out


# --------------------------------------------------------------------------- the thesis


def _level(alert, *, state: str | None = None) -> dict | None:
    if alert is None:
        return None
    return {k: v for k, v in {"price": float(alert.price), "condition": alert.condition,
                              "state": state or ("armed" if alert.state == "active" else "hit" if alert.state == "fired" else alert.state),
                              "hit_at": _utc_iso(alert.fired_at) if alert.state == "fired" else None}.items() if v is not None}


def _time_stop(stop) -> dict | None:
    if stop is None:
        return None
    return {"text": _trim(stop.text, 120), "due_at": _utc_iso(stop.due_at),
            "state": "pending" if stop.delivery == "scheduled" else stop.delivery}


def _capture_thesis(db: Session, trade, capture) -> dict:
    from app.engine import capture_links, copilot_plans, desk_context, plan_nudges, plan_positions
    from app.models import PlanTimeStop, TradeCaptureNote
    invalidation, stop = plan_positions._plan_parts(db, capture)
    investigation = plan_nudges._investigation(capture) or (stop.investigation_id if stop else None)
    card = investigation is not None or capture.setup_label == copilot_plans.PLAN_LABEL
    entry = None
    if investigation:
        found = desk_context.plan(db, investigation)
        if found is not None and found["symbol"] == capture.underlying:
            entry = found["entry"]
            invalidation = invalidation or found["invalidation"]
            stop = stop or found["stop"]
    if stop is None and capture.client_id:
        stop = db.exec(select(PlanTimeStop).where(PlanTimeStop.client_id == capture.client_id)).first()
    text = copilot_plans._thesis(capture.note) if card else None
    text = text or capture.wording or capture.transcript_text or capture.note
    notes = db.exec(select(TradeCaptureNote).where(TradeCaptureNote.capture_id == capture.id)
                    .order_by(TradeCaptureNote.created_at)).all()
    return {
        "source": "plan_card" if card else "plan_sheet",
        "label": plan_nudges.plan_name(capture),
        "text": _trim(text), "text_is_guess": False,
        "direction": "long" if capture.side in copilot_plans.LONG_SIDES else "short",
        "entry_trigger": _level(entry),
        "invalidation": _level(invalidation),
        "time_stop": _time_stop(stop),
        "plan_horizon": None,
        "captured_at": _utc_iso(capture.received_at),
        "timing": capture_links.timing(capture.received_at, trade.opened_at),
        "investigation_id": investigation,
        "revisions": [{"at": _utc_iso(n.created_at), "by": "owner", "kind": n.kind, "text": _trim(n.text, 160)} for n in notes],
    }


def _companion_thesis(db: Session, row) -> dict:
    from app.engine import position_companion
    from app.models import LevelAlert
    plan = position_companion.plan_of(row)
    alert = db.get(LevelAlert, row.alert_id) if row.alert_id else None
    price = plan.get("invalidation")
    if alert is not None:
        invalidation = _level(alert)
    elif price:
        invalidation = {"price": float(price), "condition": plan.get("condition") or "crosses", "state": "draft"}
    else:
        invalidation = None
    entry = plan.get("entry_underlying")
    revisions = [{"at": _utc_iso(row.decided_at), "by": "owner", "kind": "confirm" if row.state == "armed" else "decision",
                  "text": "Confirmed the draft plan" if row.state == "armed" else None}] if row.decided_at else []
    for update in position_companion.updates_of(row):
        at = update.get("at")
        at = datetime.fromtimestamp(at, UTC).isoformat(timespec="seconds") if isinstance(at, (int, float)) else None
        reasons = [_own_words(r) for r in update.get("reasons") or []]
        revisions.append({"at": at, "by": "companion", "kind": "update", "text": _trim("; ".join(reasons), 160)})
        if update.get("answer") in position_companion.ANSWERS:
            revisions.append({"at": at, "by": "owner", "kind": "decision", "text": position_companion.ANSWERS[update["answer"]]})
    return {
        "source": "companion",
        "label": "Adopted by the companion" + ("" if row.state == "armed" else " · draft"),
        "text": _trim(plan.get("thesis")), "text_is_guess": True,
        "direction": plan.get("direction"),
        "entry_trigger": {"price": float(entry), "condition": "touches", "state": "hit", "hit_at": _ny_iso(row.opened_at)} if entry else None,
        "invalidation": invalidation,
        "time_stop": {"text": _trim(plan.get("time_stop"), 120), "due_at": None, "state": "draft" if row.state != "armed" else "noted"}
        if plan.get("time_stop") else None,
        "plan_horizon": plan.get("horizon"),
        "captured_at": _utc_iso(row.detected_at), "timing": "retrospective",
        "investigation_id": str(row.investigation_id) if row.investigation_id else None,
        "revisions": [r for r in revisions if r.get("at")],
    }


THIRD_PARTY = re.compile(r"^thesis watch fired \((\w+):.*$", re.S)


def _own_words(reason: str) -> str:
    """A companion update's reason without the third-party text some carry (a thesis-watch headline): the record
    reaches the copilot's owner block, where only the app's and the owner's words belong."""
    return THIRD_PARTY.sub(r"thesis watch fired (\1)", str(reason))


def _no_thesis() -> dict:
    return {"source": "none", "label": "No plan", "text": None, "text_is_guess": False, "direction": None,
            "entry_trigger": None, "invalidation": None, "time_stop": None, "plan_horizon": None, "captured_at": None,
            "timing": None, "investigation_id": None, "revisions": []}


def thesis_for(db: Session, trade, *, adopted: dict | None = None, horizons: dict | None = None) -> dict:
    """The position's thesis object. ``adopted`` (``position_companion.adopted_trades``) and ``horizons``
    (``day_journal.check_ins``) are read once by a caller building several."""
    from app.engine import capture_links, day_journal, position_companion
    linked = capture_links.for_trade(db, trade.id)
    if linked:
        out = _capture_thesis(db, trade, min(linked, key=lambda c: c.received_at))
    else:
        adopted = position_companion.adopted_trades(db) if adopted is None else adopted
        row = adopted.get(str(trade.id))
        out = _companion_thesis(db, row) if row is not None else _no_thesis()
    if out["direction"] is None and trade.instrument_type == "option":
        out["direction"] = "long" if (trade.option_type or "") == "call" else "short"
    horizons = day_journal.check_ins(db)[0] if horizons is None else horizons
    owner = horizons.get(trade.ticker)
    out["horizon"] = owner or out["plan_horizon"]
    out["horizon_source"] = "owner's pick on the desk" if owner else "the plan" if out["plan_horizon"] else None
    out["revisions"] = out["revisions"][-MAX_REVISIONS:]
    return out


# --------------------------------------------------------------------------- alerts and decisions


def _alerts(db: Session, trade, thesis: dict) -> list[dict]:
    from app.engine import position_alerts
    from app.models import LevelAlert
    rows = []
    for a in position_alerts.for_trade(db, trade).get("alerts", []):
        if a.get("delivery") in ("sent", "unknown"):
            rows.append({"kind": a["kind"], "at": datetime.fromtimestamp(a["detected_at"], UTC).isoformat(timespec="seconds"),
                         "source": "position alert"})
    if thesis.get("investigation_id"):
        hit = db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", LevelAlert.source_id == thesis["investigation_id"],
                                               LevelAlert.state == "fired", LevelAlert.plan_role.is_not(None))).all()
        rows += [{"kind": f"{a.plan_role} hit", "at": _utc_iso(a.fired_at), "price": float(a.price), "source": "plan level alert"}
                 for a in hit if a.fired_at]
    rows.sort(key=lambda r: r["at"] or "")
    return rows[-MAX_ALERTS:]


def _decisions(db: Session, trade) -> list[dict]:
    from app.models import DayJournalEntry
    since = _ny(trade.opened_at).date()
    found = db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == "decision", DayJournalEntry.symbol == trade.ticker,
                                                  DayJournalEntry.day >= since)
                    .order_by(DayJournalEntry.created_at)).all()
    opened = _utc_naive(trade.opened_at)
    return [{"at": _utc_iso(e.created_at), "text": _trim(e.text, 200)} for e in found if e.created_at >= opened][-MAX_DECISIONS:]


# --------------------------------------------------------------------------- since entry


def _line(key: str, state: str, text: str, *, as_of: str | None, source: str, **values) -> dict:
    return {"key": key, "state": state, "text": text, "as_of": as_of, "source": source,
            **{k: v for k, v in values.items() if v is not None}}


def _missing(key: str, why: str, source: str) -> dict:
    return _line(key, UNAVAILABLE, f"unavailable: {why}", as_of=None, source=source)


def _pct(now: float, then: float) -> float:
    return (now / then - 1) * 100


def _underlying_line(trade, thesis: dict, entry: dict, last: float | None, as_of: str | None, failed: bool) -> dict:
    source = "quote (≤60 s cache); entry: " + (entry.get("underlying_source") or "none on file")
    if last is None:
        return _missing("underlying", "the underlying quote could not be read" if failed else "no underlying quote", source)
    parts, values = [f"{trade.ticker} {last:,.2f}"], {"now": last}
    if entry.get("underlying"):
        change = _pct(last, entry["underlying"])
        parts.append(f"{change:+.2f}% since entry ({entry['underlying']:,.2f})")
        values.update(entry=entry["underlying"], change_pct=round(change, 2))
    else:
        parts.append("price at entry unavailable")
    level = (thesis.get("invalidation") or {}).get("price")
    if level:
        gap = _pct(last, level)
        side = "above" if gap >= 0 else "below"
        parts.append(f"{abs(gap):.2f}% {side} the invalidation {level:,.2f}")
        values.update(invalidation=level, from_invalidation_pct=round(gap, 2))
    elif thesis["source"] == "none":
        parts.append("no invalidation (no plan)")
    else:
        parts.append("the plan names no invalidation")
    return _line("underlying", "ok", " · ".join(parts), as_of=as_of, source=source, **values)


def _group_line(result: dict) -> dict:
    source = "Radar since-entry"
    state = result.get("state")
    if state not in ("ready", "partial", "stale"):
        return _missing("group", (result.get("reason") or "no recorded comparison").rstrip("."), source)
    rows = {r["symbol"]: r.get("change_pct") for r in result.get("rows", [])}

    def pct(symbol):
        value = rows.get(symbol)
        return "unavailable" if value is None or not math.isfinite(value) else f"{value:+.2f}%"

    cover = result.get("coverage") or {}
    group = (result.get("group") or {}).get("name") or "group"
    text = (f"{result['symbol']} {pct(result['symbol'])} vs SPY {pct('SPY')} since the post-entry baseline; {group[:40]}: "
            f"{cover.get('peers_down', 0)} of {cover.get('peers_available', 0)} peers lower, {cover.get('peers_up', 0)} higher")
    if state != "ready":
        text += f" ({state})"
    window = result.get("window") or {}
    return _line("group", "ok", text, as_of=window.get("end"), source=source, symbol_pct=rows.get(result["symbol"]),
                 spy_pct=rows.get("SPY"), state_detail=state)


def _mark_line(row: dict) -> dict:
    source = "journal cost; option mid" if row.get("instrument") == "option" else "journal cost; quote"
    mark, cost = row.get("mark"), row.get("avg_entry")
    if mark is None or not cost:
        return _missing("mark", "no live mark" if mark is None else "no entry cost on file", source)
    unit = "a contract" if row.get("instrument") == "option" else "a share"
    change = row.get("unrealized_pct")
    return _line("mark", "ok", f"{'mark' if row.get('instrument') == 'option' else 'price'} {mark:,.2f} vs entry {cost:,.2f} {unit}"
                 + (f" ({change:+.1f}%)" if change is not None else ""), as_of=row.get("mark_as_of"), source=source,
                 mark=mark, entry=cost, change_pct=change)


def _iv_line(row: dict, entry: dict) -> dict | None:
    if row.get("instrument") != "option":
        return None
    source = "fill: Black-Scholes on its premium; now: provider (different methods)"
    now, then = row.get("iv_pct"), entry.get("iv_pct")
    if now is None and then is None:
        return _missing("iv", "neither IV now nor IV at the fill is on file", source)
    if now is None:
        return _missing("iv", f"IV now not quoted (at the fill {then:.1f}%)", source)
    if then is None:
        return _line("iv", "ok", f"IV {now:.1f}% now; at the fill unavailable", as_of=row.get("greeks_as_of"), source=source, now_pct=now)
    return _line("iv", "ok", f"IV {now:.1f}% now vs {then:.1f}% at the fill ({now - then:+.1f} pts)",
                 as_of=row.get("greeks_as_of"), source=source, now_pct=now, fill_pct=then)


def _headline_line(trade, now_utc: datetime, read) -> dict:
    source = "news reader"
    since = _ny(trade.opened_at).astimezone(UTC)
    try:
        found = read(trade.ticker, since, now_utc)
    except Exception as exc:  # noqa: BLE001 - a refused key is unavailable, never "no news"
        return _missing("headlines", f"the news source could not be read ({type(exc).__name__})", source)
    from app.engine.jo_morning_market import stamp
    rows = []
    for article in found or []:
        if not isinstance(article, dict) or not isinstance(article.get("headline"), str):
            continue
        at = stamp(article.get("created_at"))
        if at is None or not since <= at <= now_utc:
            continue
        rows.append({"headline": _trim(article["headline"], 160), "publisher": _trim(article.get("source"), 40),
                     "at": at.isoformat(timespec="minutes")})
    rows.sort(key=lambda r: r["at"], reverse=True)
    as_of = now_utc.isoformat(timespec="seconds")
    if not rows:
        return _line("headlines", "ok", "no headline naming it since the entry", as_of=as_of, source=source, count=0)
    # The line's text carries no third-party words (it reaches the copilot's owner block); the titles ride in
    # ``headlines`` for the screens, and the copilot reads them through its news tool.
    text = f"{len(rows)} headline{'s' if len(rows) != 1 else ''} naming it since the entry, newest {rows[0]['at'][11:16]} UTC"
    return _line("headlines", "ok", text, as_of=as_of, source=source, count=len(rows), headlines=rows[:MAX_HEADLINES])


def _held_line(trade, thesis: dict, now_et: datetime) -> dict:
    opened = _ny(trade.opened_at)
    minutes = max(0, int((now_et - opened).total_seconds() // 60))
    held = f"held {minutes} min" if minutes < 24 * 60 else f"held {minutes // (24 * 60)} days"
    parts, values = [held], {"held_minutes": minutes}
    stop = thesis.get("time_stop") or {}
    if stop.get("due_at"):
        due = datetime.fromisoformat(stop["due_at"])
        left = int((due - now_et.astimezone(UTC)).total_seconds() // 60)
        parts.append(f"time stop {due.astimezone(now_et.tzinfo):%H:%M} " + (f"in {left} min" if left > 0 else f"passed {-left} min ago"))
    elif stop.get("text"):
        parts.append(f"time stop {stop['text']}")
    if thesis.get("horizon"):
        parts.append(f"horizon {thesis['horizon']}")
    if trade.instrument_type == "option" and trade.expiration:
        days = (trade.expiration - now_et.date()).days
        parts.append("expires today" if days == 0 else f"{days} days to expiry")
        values["days_to_expiry"] = days
    if not stop and not thesis.get("horizon"):
        parts.append("no horizon or time stop on file")
    return _line("held", "ok", " · ".join(parts), as_of=now_et.isoformat(timespec="seconds"),
                 source="journal; the plan", **values)


def since_entry(db: Session, trade, row: dict, thesis: dict, now: float, book: _Book, reads: Reads, *,
                headlines: bool = False) -> dict:
    from app.engine.chart_math import ET
    now_et = datetime.fromtimestamp(now, ET)
    entry = _entry_facts(db, trade)
    lines = [_underlying_line(trade, thesis, entry, book.last.get(trade.ticker), book.quotes_as_of, book.quotes_failed)]
    if trade.instrument_type == "option":
        try:
            lines.append(_group_line(reads.group(db, trade, now)))
        except Exception as exc:  # noqa: BLE001
            log.warning("trader context: group comparison unavailable: %s", type(exc).__name__)
            db.rollback()
            lines.append(_missing("group", "the Radar comparison could not be read", "Radar since-entry"))
    lines.append(_mark_line(row))
    if (iv := _iv_line(row, entry)) is not None:
        lines.append(iv)
    if headlines:
        lines.append(_headline_line(trade, now_et.astimezone(UTC), reads.news))
    lines.append(_held_line(trade, thesis, now_et))
    as_of = now_et.isoformat(timespec="seconds")
    for line in lines:  # a line with no time of its own (unavailable, or a read that gave none) is as of this build
        line["as_of"] = line.get("as_of") or as_of
    return {"as_of": as_of, "entry": entry or None, "lines": lines}


# --------------------------------------------------------------------------- records


def _record(db: Session, trade, row: dict, now: float, book: _Book, reads: Reads, *, diff: bool, headlines: bool) -> dict:
    from app.engine import position_alerts
    from app.engine.chart_journal import contract_label
    from app.engine.chart_math import ET
    now_et = datetime.fromtimestamp(now, ET)
    thesis = thesis_for(db, trade, adopted=book.adopted, horizons=book.horizons)
    out = {**row, "trade_id": str(trade.id),
           "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration)}
    opened = _ny(trade.opened_at)
    if opened.date() == now_et.date():
        out["held_minutes"] = max(0, int((now_et - opened).total_seconds() // 60))
    if trade.instrument_type == "option" and trade.expiration:
        out["days_to_expiry"] = (trade.expiration - now_et.date()).days
        out["expires_today"] = trade.expiration == now_et.date()
        watch = position_alerts.for_trade(db, trade).get("watch")
        if watch:
            out["peak_gain_usd"] = watch.get("peak_gain")
            out["peak_gain_pct"] = None if watch.get("peak_gain_pct") is None else round(100 * watch["peak_gain_pct"], 1)
            out["giveback"] = "fired" if watch.get("fired") else "armed" if watch.get("armed") else "watching"
    out["thesis"] = thesis
    out["alerts"] = _alerts(db, trade, thesis)
    out["decisions"] = _decisions(db, trade)
    if diff:
        out["since_entry"] = since_entry(db, trade, row, thesis, now, book, reads, headlines=headlines)
    return out


def records(db: Session, pairs: list[tuple], now: float | None = None, *, diff_for: Callable[[object], bool] = lambda _t: True,
            headlines_for: Callable[[object], bool] = lambda _t: False, reads: Reads | None = None) -> list[dict]:
    """A record per ``(trade, row)`` from ``copilot_book.position_rows``. ``diff_for`` picks which get the since-entry
    diff (each costs a Radar read and the shared underlying quote read), ``headlines_for`` which also read headlines."""
    import time
    from app.engine import day_journal, position_companion
    now = time.time() if now is None else now
    reads = reads or Reads()
    book = _Book(adopted=position_companion.adopted_trades(db), horizons=day_journal.check_ins(db)[0])
    wanted = sorted({t.ticker for t, _ in pairs if diff_for(t)})
    if wanted:
        try:
            book.last, book.quotes_as_of = reads.quotes(wanted)
        except Exception as exc:  # noqa: BLE001
            log.warning("trader context: underlying quotes unavailable: %s", type(exc).__name__)
            book.quotes_failed = True
    # A failing journal read fails the whole build (the caller's section reads unavailable); a failing provider read
    # fails only its own line.
    return [_record(db, trade, row, now, book, reads, diff=diff_for(trade), headlines=headlines_for(trade)) for trade, row in pairs]


def for_symbol(symbol: str | None, now: float | None = None, *, session: Session | None = None, limit: int = MAX_POSITIONS,
               diff: str = "symbol", headlines: bool = True, reads: Reads | None = None) -> dict:
    """The open positions' records, ``symbol``'s first. ``diff``: ``symbol`` (the since-entry diff for that symbol's
    positions only), ``all`` or ``none``; headlines are read for the symbol's positions when ``headlines``."""
    import time
    from app.ai import copilot_book
    from app.database import engine
    from app.engine.chart_math import ET
    now = time.time() if now is None else now
    symbol = symbol.upper() if symbol else None
    with (Session(engine) if session is None else nullcontext(session)) as db:
        pairs, total = copilot_book.position_rows(db, limit=limit, first=symbol, now=datetime.fromtimestamp(now, UTC))
        mine = (lambda t: t.ticker == symbol) if symbol else (lambda _t: False)
        pick = {"all": lambda _t: True, "none": lambda _t: False}.get(diff, mine)
        rows = records(db, pairs, now, diff_for=pick, headlines_for=mine if headlines else (lambda _t: False), reads=reads)
    return {"state": "ok", "as_of": datetime.fromtimestamp(now, ET).isoformat(timespec="seconds"), "symbol": symbol,
            "count": total, "shown": len(rows), "positions": rows,
            "units": "Options: avg_entry, mark and peak are dollars per contract (premium x 100). Stocks: per share."}


def for_day(now: float | None = None, *, session: Session | None = None, limit: int = MAX_POSITIONS * 2,
            reads: Reads | None = None) -> dict:
    """Every open position's record with its since-entry diff (no headlines: the morning prep reads its own), and the
    day's decisions and phone pings."""
    import time
    from app.database import engine
    from app.engine.chart_math import ET
    from app.models import DayJournalEntry, PhonePing
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, ET).date()
    with (Session(engine) if session is None else nullcontext(session)) as db:
        out = for_symbol(None, now, session=db, limit=limit, diff="all", headlines=False, reads=reads)
        start = datetime.combine(day, datetime.min.time()).replace(tzinfo=ET).astimezone(UTC).replace(tzinfo=None)
        pings = db.exec(select(PhonePing).where(PhonePing.decided_at >= start)).all()
        decisions = db.exec(select(DayJournalEntry).where(DayJournalEntry.day == day, DayJournalEntry.kind == "decision")).all()
    out["day"] = day.isoformat()
    out["pings"] = {"sent": sum(p.decision == "sent" for p in pings), "held": sum(p.decision != "sent" for p in pings)}
    out["decisions"] = [{"symbol": d.symbol, "at": _utc_iso(d.created_at), "text": _trim(d.text, 160)} for d in decisions]
    return out


def for_trade(db: Session, trade, now: float | None = None, *, headlines: bool = False, reads: Reads | None = None) -> dict | None:
    """One open position's record (the companion's prompts), or None when the book no longer holds it."""
    from app.ai import copilot_book
    pairs, _total = copilot_book.position_rows(db, only=trade, now=None if now is None else datetime.fromtimestamp(now, UTC))
    if not pairs:
        return None
    return records(db, pairs, now, headlines_for=lambda _t: headlines, reads=reads)[0]


# --------------------------------------------------------------------------- text


def thesis_line(thesis: dict | None) -> str | None:
    """One line for a row (Act now, the desk header): the plan's own words, labelled by where they came from."""
    if not thesis or thesis.get("source") == "none":
        return None
    text = thesis.get("text")
    if not text:
        level = (thesis.get("invalidation") or {}).get("price")
        return f"{thesis.get('label') or 'Plan'}: invalidation {level:,.2f}" if level else thesis.get("label")
    return f"{text} (the companion's guess)" if thesis.get("text_is_guess") else text


def since_text(record: dict, *, most: int = 400) -> str:
    """The since-entry lines as one sentence for a prompt: ``Since you entered (as of …): …``."""
    since = record.get("since_entry") or {}
    lines = since.get("lines") or []
    if not lines:
        return "Since you entered: unavailable."
    text = f"Since you entered (as of {since.get('as_of', '?')[11:16]} ET): " + "; ".join(line["text"] for line in lines)
    return text if len(text) <= most else text[: most - 1] + "…"


def phone_line(db: Session, trade, now: float, snapshot_json: str | None = None, *, underlying: float | None = None) -> str:
    """'Since you entered: …' for a phone body. Database and the alert's frozen Radar snapshot only: no provider read,
    so it never delays a send. The thesis's own words, the invalidation and where the frozen underlying price sits
    against it (or ``underlying``, a price the caller read itself), and time held against the time stop, horizon or
    expiry. A failure says unavailable."""
    from app.engine.chart_math import ET
    try:
        thesis = thesis_for(db, trade)
        parts = []
        line = thesis_line(thesis)
        parts.append(f"plan: {_trim(line, 90)}" if line else "no plan saved")
        level = (thesis.get("invalidation") or {}).get("price")
        if level:
            price, at = _snapshot_price(snapshot_json, trade.ticker)
            if price is None and isinstance(underlying, (int, float)) and underlying > 0:
                price, at = float(underlying), f"{datetime.fromtimestamp(now, ET):%H:%M}"  # the caller's own read
            if price is not None:
                gap = _pct(price, level)
                parts.append(f"{trade.ticker} {price:,.2f} at {at} is {abs(gap):.1f}% {'above' if gap >= 0 else 'below'} the invalidation {level:,.2f}")
            else:
                parts.append(f"invalidation {level:,.2f} (distance unavailable)")
        held = _held_line(trade, thesis, datetime.fromtimestamp(now, ET))["text"]
        parts.append(held)
        return ("Since you entered: " + " · ".join(parts))[:300]
    except Exception:  # noqa: BLE001 - the alert itself never fails on this line
        log.warning("trader context: phone line unavailable", exc_info=True)
        db.rollback()
        return "Since you entered: unavailable."


def _snapshot_price(snapshot_json: str | None, symbol: str) -> tuple[float | None, str | None]:
    """The underlying's latest recorded price in a position alert's frozen Radar snapshot, and its New York clock."""
    from app.engine.chart_math import ET
    if not snapshot_json:
        return None, None
    try:
        result = json.loads(snapshot_json)["comparison"]
        if result.get("state") not in ("ready", "partial", "stale"):
            return None, None
        row = next(r for r in result.get("rows", []) if r.get("symbol") == symbol.upper())
        end = row.get("end") or {}
        price, at = end.get("price"), end.get("trade_at")
        if not isinstance(price, (int, float)) or not math.isfinite(price) or not at:
            return None, None
        clock = datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone(ET)
        return float(price), f"{clock:%H:%M}"
    except (ValueError, KeyError, TypeError, StopIteration, AttributeError):
        return None, None


