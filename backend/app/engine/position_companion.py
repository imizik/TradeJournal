"""The options position companion: every unplanned long option is adopted by the copilot, watched, and kept in one
Telegram conversation until it closes (docs/copilot-lab.md § Position companion).

The owner mostly enters options without a plan, and his losses come from managing them after the entry (green ridden
red, held an hour and lost, left to expire). So instead of a nudge to plan, the copilot drafts the plan for him:

- **Adopt.** ``GRACE`` (plan nudges' grace, default 3 minutes) after the first entry fill of a new long option, in the
  regular session, entered since this process started, Webull left out, with no plan linked by then
  (``capture_links.for_trade``): one ``run_turn`` with the position copilot's context ("Review this position:", so the
  turn reads the trade review, chart, group, headlines and the owner's record with the existing tools) writes a
  provisional plan in the plan card's fields and a three-line read. The invalidation is drafted in code from the 5m
  chart's nearest level below a call or above a put (VWAP when no level), the horizon and time stop from the expiry
  and the audit's 15-60 minute best holds; the turn may keep or move them. Saved as the investigation "Adopted: NBIS
  160C" and a ``PositionCompanion`` row in ``draft`` linked to the trade's position anchor. One Telegram message: the
  three lines, Confirm, Ignore, and Edit (the desk thread). Kind ``companion_adopt``, ranked and budgeted with ``nudge``.
- **Confirm** (``telegram_replies``) arms the invalidation alert as a confirmed plan card does (a ``copilot`` level
  alert with ``plan_role="invalidation"`` on the investigation; state ``armed``), so the desk's plan ladder and the
  Plans board read it. **Ignore** stops every later message for the position (state ``ignored``).
- **Watch.** Every ``RUN_SECONDS`` in the regular session, each adopted position still open, not ignored and among the
  newest ``COMPANION_MAX_POSITIONS`` (default 6; older ones are adopt-only) gets an update when, since the last one: a
  phone ping went out for it (give-back, hold-hour, expiry, time stop, invalidation), thesis watch fired on its symbol,
  Radar recorded an event on the symbol or its group (store read-only), the underlying moved ``COMPANION_MOVE_PCT``
  (default 3) from the last update, or a cadence floor passed: 60 minutes after the entry, and 15:30 New York while it
  is open. At most ``COMPANION_MAX_UPDATES`` (default 4) a position a day, besides the adopt and close turns, and one
  per quiet window. An update waits while a ping for the position is inside the notification policy's quiet window,
  and is recorded before its turn, so a failure after the turn never repeats it. A held adopt ping leaves the position
  adopt-only (no thread to reply in, no Ignore on the phone).
- **Update.** One ``run_turn``: what changed since the last update and whether it changes the plan, Verdict line
  first, at most 80 words, with the plan's invalidation and the live option mark in the question. Saved as messages on
  the adopted investigation and sent as a Telegram reply to the adopt message, with Closed it / Holding (recorded
  on the row, nothing else). Kind ``companion_update``, ranked just below ``hold_hour``, budget 12.
- **Close.** When the position's exits bring it to zero (the trade at its anchor is no longer open): one last turn
  writes the exit note (what the plan said, what he did, where the underlying and the option mark went), saved as
  the investigation's conclusion with status ``closed`` and sent as the thread's last reply. The row is claimed closed
  before the turn (a Confirm racing it arms nothing), the note waits out the quiet window, and closes run from the open
  to ``CLOSE_GRACE_MINUTES`` after the close. A confirmed invalidation that never fired is removed then (and on
  Ignore), so a closed position never pings "your plan says out". A multi-day hold gets
  no overnight update; it resumes in the next regular session.

Off unless ``POSITION_COMPANION_ENABLED=true``, and nothing runs while the lab is off (``COPILOT_ENABLED``). Turns use
the copilot's configured backend, its turn budget and, on the API backend, its daily budget; ``COMPANION_MODEL``
overrides the model. Every send asks ``notification_policy.decide`` first. A position is adopted once (its anchor is
unique), so a trade rebuild never re-adopts it. Delivery is at-most-once: a failed send is recorded, never retried.
Nothing here places, changes or suggests an order, and every prompt says so.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, date, datetime, timedelta
import json
import logging
import os
import re
import time
from typing import Awaitable, Callable
import uuid

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import capture_links, notification_policy, phone
from app.engine.chart_journal import contract_label, stamp
from app.engine.chart_math import ET, session_windows
from app.models import Account, Fill, PhonePing, PositionCompanion, ThesisWatchTrigger, Trade, TradeFill

log = logging.getLogger(__name__)

SENDER = "position_companion"
RUN_SECONDS = 60
ADOPT_SECONDS = 10 * 60  # an adopt still "adopting" this long after its claim died mid-turn: given up, never redone
FLOOR_MINUTES = 60  # the cadence floor after the entry: the audit's best holds were 15 to 60 minutes
LATE_MINUTE = 15 * 60 + 30  # the second floor, New York
UPDATE_WORDS = 80
CLOSE_GRACE_MINUTES = 30  # a position closed near the bell still gets its exit note this long after the close
DAY_HORIZON_DAYS = 7  # a contract expiring within this many days is drafted as a day trade
# The position's own pings that call for an update (the policy's kinds).
POSITION_KINDS = ("giveback", "hold_hour", "wrong_way", "expiry_eve", "expiry_first", "expiry_final", "time_stop", "invalidation")
ANSWERS = {"closed": "Closed it", "holding": "Holding"}
NO_ORDER = "Nothing here places, changes or suggests an order; say what each choice means and leave the decision to him."
PLAN_LINE = re.compile(r"^\**(thesis|invalidation|time stop)\**\s*:\s*(.+)$", re.I)
PRICE = re.compile(r"\$?(\d+(?:\.\d+)?)")


def enabled() -> bool:
    return os.environ.get("POSITION_COMPANION_ENABLED", "").strip().lower() == "true"


def active() -> bool:
    """Switched on and able to run: what plan nudges hand long options over on (with the lab off they keep nudging)."""
    return enabled() and _lab_on() and os.environ.get("TJ_DOT_TRIAL_ENABLED") != "true"


def _setting(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "").strip()))
    except ValueError:
        return default


def move_pct() -> float:
    return _setting("COMPANION_MOVE_PCT", 3.0)


def max_updates() -> int:
    return int(_setting("COMPANION_MAX_UPDATES", 4))


def max_positions() -> int:
    return int(_setting("COMPANION_MAX_POSITIONS", 6))


def _lab_on() -> bool:
    return os.environ.get("COPILOT_ENABLED") == "true"


def _utc(stamp_s: float) -> datetime:
    return datetime.fromtimestamp(stamp_s, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _clock(moment_et: datetime) -> str:
    return f"{moment_et.hour % 12 or 12}:{moment_et.minute:02d}"


def _regular(calendar, day: date):
    hours = calendar.hours(day) if calendar is not None else None
    return next((w for w in session_windows(day, hours) if w[0] == "regular"), None)


def label(ticker: str, option_type: str, strike) -> str:
    """'NBIS 160C': the thread's name."""
    return f"{ticker} {float(strike):g}{'C' if option_type == 'call' else 'P'}"


def desk_path(investigation_id) -> str:
    return f"/copilot-lab?investigation={investigation_id}"


def plan_of(row: PositionCompanion) -> dict:
    return json.loads(row.plan_json or "{}")


def updates_of(row: PositionCompanion) -> list[dict]:
    return json.loads(row.updates_json or "[]")


def unlabelled(line: str) -> str:
    return re.sub(r"^\**verdict\**:\**\s*", "", line.strip(), flags=re.I)


def words(text: str, limit: int) -> str:
    parts = text.split()
    return text.strip() if len(parts) <= limit else " ".join(parts[:limit]).rstrip(".,;") + "…"


# ------------------------------------------------------------------ the draft


def draft_plan(option_type: str, expiration: date, opened_at: datetime, chart: dict, regular) -> dict:
    """The provisional plan from code: the invalidation at the 5m chart's nearest level below a call (its low) or above
    a put (its high), else VWAP on that side, else none; a day-trade horizon with a time stop 60 minutes after the entry
    (the audit's best holds) for a contract expiring within ``DAY_HORIZON_DAYS``, else a swing to the day before expiry."""
    call = option_type == "call"
    last = chart.get("last")
    levels = chart.get("levels") or {}
    side = [z for z in levels.get("below" if call else "above") or [] if isinstance(z.get("low"), (int, float))]
    invalidation, source = None, None
    if side:
        zone = side[0]
        invalidation = float(zone["low"] if call else zone["high"])
        source = f"the nearest 5m level {'below' if call else 'above'}" + (f" ({zone['label']})" if zone.get("label") else "")
    else:
        vwap = (chart.get("vwap") or {}).get("vwap")
        if isinstance(vwap, (int, float)) and isinstance(last, (int, float)) and (vwap < last if call else vwap > last):
            invalidation, source = float(vwap), "VWAP"
    days = (expiration - opened_at.date()).days
    if days <= DAY_HORIZON_DAYS:
        stop = opened_at + timedelta(minutes=FLOOR_MINUTES)
        if regular is not None:
            stop = min(stop, datetime.combine(opened_at.date(), datetime.min.time()) + timedelta(minutes=regular[2] - 30))
        horizon, time_stop = "day", f"{_clock(stop)} today (60 min after the entry; his best holds were 15-60 min)"
    else:
        horizon, time_stop = "swing", f"the close before expiry ({expiration.month}/{expiration.day})"
    return {"thesis": "", "invalidation": invalidation, "invalidation_source": source, "condition": "crosses",
            "direction": "long" if call else "short", "horizon": horizon, "time_stop": time_stop,
            "entry_underlying": last if isinstance(last, (int, float)) else None}


def parse_answer(answer: str, plan: dict, last: float | None) -> tuple[dict, list[str]]:
    """The turn's plan lines (Thesis, Invalidation, Time stop) folded into the draft, and the read: the other lines. An
    invalidation on the wrong side of the price, or no number, keeps the drafted one."""
    plan, read = dict(plan), []
    call = plan.get("direction") == "long"
    for raw in answer.splitlines():
        line = raw.strip().lstrip("-• ").strip()
        if not line:
            continue
        found = PLAN_LINE.match(line)
        if not found:
            read.append(line)
            continue
        key, value = found.group(1).lower(), found.group(2).strip()
        if key == "thesis":
            plan["thesis"] = value[:300]
        elif key == "time stop":
            plan["time_stop"] = value[:80]
        elif (price := PRICE.search(value)) is not None:
            level = float(price.group(1))
            if level > 0 and (last is None or (level < last if call else level > last)):
                if plan.get("invalidation") != level:
                    plan["invalidation"], plan["invalidation_source"] = level, "the copilot's read"
    return plan, read


def adopt_lines(read: list[str], plan: dict, ticker: str) -> list[str]:
    """The Telegram body: the read's first two lines and the plan in one."""
    # The adopt's verdict is always Draft, and the title says so: its headline alone.
    lines = [re.sub(r"^draft\s*[—–-]\s*", "", unlabelled(read[0]), flags=re.I)] + read[1:2] if read else [
        "The copilot drafted a plan for this position."]
    stop = plan.get("invalidation")
    where = f"invalidation {stop:,.2f} ({ticker})" if stop else "no invalidation found on the chart"
    lines.append(f"Draft plan: {where} · time stop {plan.get('time_stop') or 'none'}")
    return [line[:300] for line in lines[:3]]


# ------------------------------------------------------------------ prompts


def adopt_prompt(trade: Trade, size: str, opened_at: datetime, plan: dict, chart: dict) -> str:
    stop = plan.get("invalidation")
    drafted = (f"invalidation {stop:,.2f} on {trade.ticker} ({plan.get('invalidation_source')})" if stop
               else "no invalidation (no level or VWAP on the right side of the price)")
    vwap = (chart.get("vwap") or {}).get("vwap")
    return (
        f"Review this position: {trade.id}. Adopted after the entry: the owner opened "
        f"{contract_label(trade.ticker, 'option', trade.option_type, trade.strike, trade.expiration)} ({size}) at "
        f"{_clock(opened_at)} New York with no plan, and you are drafting one for him to confirm or ignore.\n"
        f"Read the chart as of now (get_chart_context, 5m: the nearest levels and VWAP), the group versus SPY "
        f"(get_group_comparison), headlines in the last hour (get_symbol_news), and his record at the drafted invalidation "
        f"(get_level_history) and on this contract shape (the trade review and owner context).\n"
        f"Drafted from the chart: {drafted}; {trade.ticker} {chart.get('last')}, VWAP {vwap}; horizon {plan['horizon']}; "
        f"time stop {plan['time_stop']}. Keep them unless what you read shows a better level on the right side.\n"
        "Answer in exactly this shape, six lines, nothing else:\n"
        "Verdict: Draft — <one plain sentence on the position now>\n"
        "<one line: the read that decides it, with its number and as-of>\n"
        "Against: <the strongest case against your read>\n"
        "Thesis: <your best guess at why he took it, in one sentence, marked as a guess>\n"
        "Invalidation: <a price on the underlying>\n"
        "Time stop: <when>\n"
        f"The plan is provisional until he confirms it. {NO_ORDER}")


def update_prompt(row: PositionCompanion, trade: Trade, reasons: list[str], live: dict) -> str:
    plan = plan_of(row)
    since = _utc_et(row.last_update_at or row.detected_at)
    state = "confirmed, its invalidation alert armed" if row.state == "armed" else "a draft he has not confirmed"
    stop = plan.get("invalidation")
    return (
        f"Review this position: {trade.id}. Position companion update for the adopted {row.contract}, last update "
        f"{_clock(since)} New York: what changed since then for this position, and does it change the plan?\n"
        f"Since then: {'; '.join(reasons)}.\n"
        f"The plan ({state}): invalidation {f'{stop:,.2f}' if stop else 'none'} on {row.ticker}; time stop "
        f"{plan.get('time_stop') or 'none'}; thesis (a guess) {plan.get('thesis') or 'unstated'}.\n"
        f"Live now: option mark {live.get('mark_text', 'unavailable')}, {row.ticker} {live.get('underlying') or 'unavailable'}.\n"
        f"Verdict line first, at most {UPDATE_WORDS} words in all. {NO_ORDER}")


def close_prompt(row: PositionCompanion, trade: Trade, live: dict, confirmed: bool = False) -> str:
    plan = plan_of(row)
    stop = plan.get("invalidation")
    closed = trade.closed_at.strftime("%H:%M") if trade.closed_at else "?"
    pnl = f"{float(trade.realized_pnl):+,.0f} dollars" if trade.realized_pnl is not None else "unknown"
    exit_premium = f"${float(trade.avg_exit_premium) / 100:,.2f}" if trade.avg_exit_premium is not None else "?"
    return (
        f"Review this position: {trade.id}. The adopted {row.contract} is closed. Write its exit note: the Verdict line, "
        "then one paragraph under 90 words: what the provisional plan said (invalidation "
        f"{f'{stop:,.2f}' if stop else 'none'}, time stop {plan.get('time_stop') or 'none'}, thesis guess "
        f"{plan.get('thesis') or 'unstated'}; {'confirmed' if confirmed else 'never confirmed'}), what he did "
        f"(entered {_clock(row.opened_at)} at ${float(trade.avg_entry_premium) / 100:,.2f}, out {closed} at {exit_premium}, "
        f"P&L {pnl}), and where {row.ticker} and the option mark went after the exit (now {row.ticker} "
        f"{live.get('underlying') or 'unavailable'}, mark {live.get('mark_text', 'unavailable')}). {NO_ORDER}")


def _utc_et(moment_utc: datetime) -> datetime:
    return moment_utc.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)


# ------------------------------------------------------------------ readers (injectable)


def read_chart(symbol: str) -> dict:
    """The 5m chart as the copilot's get_chart_context sees it, from the configured evidence."""
    from app.ai import copilot
    try:
        return copilot.evidence_for(copilot.settings()).get_chart_context(symbol, "5m") or {}
    except Exception:  # noqa: BLE001 - a draft without a level still adopts
        log.warning("Companion chart read failed for %s", symbol, exc_info=True)
        return {}


def read_underlying(symbols: list[str]) -> dict[str, float]:
    from app.engine.copilot_plans import _quotes
    return _quotes(symbols)[0]


def read_marks(occs: list[str], now: float) -> dict[str, dict]:
    from app.engine.position_alerts import judged_quote
    from app.engine.tradier import TradierError, get_quotes_once
    try:
        quotes = get_quotes_once(sorted(set(occs)))
    except TradierError as exc:
        log.info("Companion: no option quotes this pass: %s", exc)
        return {}
    return {symbol: judged for symbol, quote in quotes.items() if (judged := judged_quote(quote, now))}


def read_radar(symbol: str, since: datetime, now: float) -> list[str]:
    """Radar events on the symbol or its group (a group event lists its members) first seen after ``since`` (UTC)."""
    from app.routers import radar
    store, _reason = radar._store(read_only=True)
    if store is None:
        return []
    session = datetime.fromtimestamp(now, ET).date().isoformat()
    out = []
    for event in store.events(session):
        try:
            seen = datetime.fromisoformat(str(event.get("first_seen_at")).replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)
        except ValueError:
            continue
        if seen > since and symbol in (event.get("symbols") or []):
            out.append(str(event.get("summary") or event.get("kind") or "Radar event")[:160])
    return out


TurnRunner = Callable[[str, str, float], Awaitable[tuple[str, str | None]]]


async def run_turn(question: str, symbol: str, now: float) -> tuple[str, str | None]:
    """One copilot turn: ``(answer, error)``, on the configured backend with its turn budget, the API backend's daily
    budget, and ``COMPANION_MODEL`` when it names a model."""
    from app.ai import copilot, copilot_spend
    cfg = copilot.settings()
    if not cfg.enabled:
        return "", "Copilot Lab is off."
    model = os.environ.get("COMPANION_MODEL", "").strip()
    if model and copilot.MODEL_ID.match(model):
        cfg = dataclasses.replace(cfg, model=model)
    if cfg.backend == "anthropic" and await asyncio.to_thread(copilot_spend.spent_today) >= cfg.daily_budget_usd:
        return "", f"Today's copilot API budget (${cfg.daily_budget_usd:.2f}) is spent."
    try:
        adapter = await asyncio.to_thread(copilot.adapter_for, cfg)
        evidence = copilot.evidence_for(cfg)
    except copilot.CopilotError as exc:
        return "", exc.message
    history = [{"role": "user", "content": question}]
    parts, error, done = [], None, None
    try:
        turn = (adapter.run_turn(history, symbol, cfg, evidence, datetime.fromtimestamp(now, ET)) if hasattr(adapter, "run_turn")
                else copilot.run_turn(history, symbol, cfg, adapter, evidence, datetime.fromtimestamp(now, ET)))
        async for event in turn:
            if event.get("type") == "text":
                parts.append(event.get("delta") or "")
            elif event.get("type") == "error" and error is None:
                error = event.get("message") or event.get("code") or "error"
            elif event.get("type") == "done":
                done = event.get("metrics")
    except Exception as exc:  # noqa: BLE001 - a failed turn is recorded on the row, never raised into the loop
        log.warning("Companion turn failed: %s", type(exc).__name__)
        error = "The copilot turn failed unexpectedly."
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()
        if done:
            await asyncio.to_thread(copilot_spend.record, done, symbol)
    answer = "".join(parts).strip()
    if error is None and not answer:
        error = "The copilot wrote nothing."
    return answer, error


# ------------------------------------------------------------------ the record


def save_messages(investigation_id, messages: list[dict], *, status: str | None = None, conclusion: str | None = None,
                  session: Session | None = None) -> None:
    """Append ``messages`` to the adopted investigation (retried once if the owner saved it meanwhile)."""
    from app.engine import copilot_investigations as investigations
    for attempt in range(2):
        found = investigations.get(investigation_id, session=session)
        fields = investigations.InvestigationFields(
            title=found["title"], symbol=found["symbol"], status=status or found["status"],
            conclusion=conclusion if conclusion is not None else found["conclusion"],
            transcript=found["transcript"] + [{"role": m["role"], "content": m["content"][:20_000]} for m in messages],
            evidence=found["evidence"])
        try:
            investigations.update(investigation_id, fields, found["revision"], session=session)
            return
        except investigations.InvestigationError as exc:
            if exc.code != "stale" or attempt:
                raise


def trade_of(db: Session, row: PositionCompanion) -> Trade | None:
    """The trade holding the position now (a rebuild gives it a new id)."""
    return notification_policy._trade_of(db, notification_policy.anchor(row.account_id, row.source_key))


def for_investigations(db: Session, ids: list[str]) -> dict[str, PositionCompanion]:
    """The adopted rows behind these investigation ids, for the Plans board."""
    keys = [k for k in (_uuid(i) for i in ids) if k is not None]
    if not keys:
        return {}
    try:
        rows = db.exec(select(PositionCompanion).where(PositionCompanion.investigation_id.in_(keys))).all()
    except Exception:  # noqa: BLE001 - a missing table (an older database) only leaves plans as they were
        db.rollback()
        return {}
    return {str(r.investigation_id): r for r in rows}


def adopted_trades(db: Session) -> dict[str, PositionCompanion]:
    """Open, not ignored adopted positions by their current trade id, for the desk's thread list."""
    try:
        rows = db.exec(select(PositionCompanion).where(PositionCompanion.state.in_(("draft", "armed")))).all()
    except Exception:  # noqa: BLE001
        db.rollback()
        return {}
    out = {}
    for row in rows:
        trade = trade_of(db, row)
        if trade is not None and trade.status == "open":
            out[str(trade.id)] = row
    return out


def _uuid(value) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ Telegram taps (telegram_replies)


def adopt_buttons(row: PositionCompanion, plan: dict) -> tuple[tuple[str, str], ...]:
    confirm = (("Confirm", f"pc:{row.id}:confirm"),) if plan.get("invalidation") else ()
    return confirm + (("Ignore", f"pc:{row.id}:ignore"),)


def update_buttons(row: PositionCompanion, index: int) -> tuple[tuple[str, str], ...]:
    return tuple((text, f"pu:{row.id}:{index}:{answer}") for answer, text in ANSWERS.items())


def confirm(engine, companion_id: str, *, quote: Callable[[str], float | None] | None = None, now: float | None = None) -> tuple[str, str | None]:
    """Confirm: arm the draft's invalidation as a confirmed plan card's invalidation alert. ``(reply, chosen label)``."""
    from app.engine.level_alert_monitor import create_alert
    now = time.time() if now is None else now
    key = _uuid(companion_id)
    with Session(engine) as db:
        row = db.get(PositionCompanion, key) if key else None
        if row is None:
            return "That position is no longer in the journal.", None
        if row.state == "armed":
            return "Already confirmed: its invalidation alert is armed.", "Confirmed"
        if row.state != "draft":
            return f"Not confirmed: this position is {row.state}.", None
        plan = plan_of(row)
        price = plan.get("invalidation")
        if not price:
            return "This draft has no invalidation to arm; edit it on the desk.", None
        trade = trade_of(db, row)
        if trade is not None and trade.status != "open":
            return "Not confirmed: this position has closed.", None
        last = (quote or (lambda s: read_underlying([s]).get(s)))(row.ticker)
        if not last:
            return f"The latest {row.ticker} quote is missing, so nothing was armed. Try again.", None
        call = plan.get("direction") == "long"
        if (last <= price) if call else (last >= price):
            return f"{row.ticker} is at {last:,.2f}, already past the invalidation at {price:,.2f}, so it was not armed.", None
        condition, ticker, contract = plan.get("condition") or "crosses", row.ticker, row.contract
        try:  # the plan card's invalidation alert, as its Confirm arms it (TradePlanCard: createPlanAlert)
            alert = create_alert(db, symbol=ticker, price=price, reference=last, condition=condition, interval=None, session="regular",
                                 source_kind="copilot", source_id=str(row.investigation_id),
                                 label=f"{ticker} invalidation: {condition} {price:,.2f}"[:60], now=now, plan_role="invalidation")
        except ValueError as exc:
            return f"Not armed: {exc}", None
        # Only a draft becomes armed: a close or an Ignore that landed meanwhile wins, and the alert just made goes.
        armed = db.exec(update(PositionCompanion).where(PositionCompanion.id == row.id, PositionCompanion.state == "draft")
                        .values(state="armed", alert_id=alert.id, decided_at=_utc(now)))
        db.commit()
        if armed.rowcount != 1:
            _remove_alert(db, alert.id)
            db.commit()
            return "Not confirmed: this position closed or was ignored meanwhile.", None
    log.info("Companion plan confirmed for %s: invalidation %.2f armed", contract, price)
    return f"Confirmed: invalidation {price:,.2f} on {ticker} is armed.", "Confirmed"


def ignore(engine, companion_id: str, *, now: float | None = None) -> tuple[str, str | None]:
    key = _uuid(companion_id)
    with Session(engine) as db:
        row = db.get(PositionCompanion, key) if key else None
        if row is None:
            return "That position is no longer in the journal.", None
        if row.state == "ignored":
            return "Already ignored.", "Ignored"
        if row.state not in ("draft", "armed"):
            return f"This position is {row.state}.", None
        ignored = db.exec(update(PositionCompanion).where(PositionCompanion.id == row.id, PositionCompanion.state.in_(("draft", "armed")))
                          .values(state="ignored", decided_at=_utc(time.time() if now is None else now)))
        db.commit()
        if ignored.rowcount != 1:
            return "This position changed meanwhile; nothing was ignored.", None
        db.refresh(row)
        _disarm(db, row)  # an Ignore after Confirm takes its invalidation alert with it
        db.commit()
        _close_thread(db, row, "Ignored: the companion sent nothing more for this position.")
    return "Ignored: no more updates for this position.", "Ignored"


def answer(engine, companion_id: str, index: str, choice: str) -> tuple[str, str | None]:
    """Closed it / Holding on an update: recorded on the row, nothing else."""
    key = _uuid(companion_id)
    if key is None or choice not in ANSWERS or not index.isdigit():
        return "That button is not one the app knows.", None
    with Session(engine) as db:
        row = db.get(PositionCompanion, key)
        updates = updates_of(row) if row else []
        if row is None or int(index) >= len(updates):
            return "That update is no longer in the journal.", None
        updates[int(index)]["answer"] = choice
        row.updates_json = json.dumps(updates)
        db.add(row)
        db.commit()
    return f"Saved: {ANSWERS[choice]}.", ANSWERS[choice]


# ------------------------------------------------------------------ the loop


@dataclasses.dataclass
class Draft:
    """A new position to adopt: the row as claimed, the trade and its size so far."""
    row_id: uuid.UUID
    trade_id: uuid.UUID
    size: str


class Companion:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time, turn: TurnRunner = run_turn,
                 chart: Callable[[str], dict] = read_chart, underlying: Callable[[list[str]], dict] = read_underlying,
                 marks: Callable[[list[str], float], dict] = read_marks, radar: Callable[[str, datetime, float], list[str]] = read_radar):
        self.engine, self.calendar, self.clock = engine, calendar, clock
        self.turn, self.chart, self.underlying, self.marks, self.radar = turn, chart, underlying, marks, radar
        self.started_at = clock()  # entries before this are never adopted
        self.last_error: str | None = None

    async def loop(self) -> None:
        while True:
            try:
                await self.run_once()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad pass never stops the companion
                self.last_error = "Position companion pass failed"
                log.exception("Position companion pass failed")
            await asyncio.sleep(RUN_SECONDS)

    async def run_once(self) -> None:
        if not active():
            return
        now = self.clock()
        moment = datetime.fromtimestamp(now, ET)
        regular = _regular(self.calendar, moment.date())
        minute = moment.hour * 60 + moment.minute
        await asyncio.to_thread(self._give_up, now)
        if regular is None or not regular[1] <= minute < regular[2] + CLOSE_GRACE_MINUTES:
            return  # nothing overnight: the companion resumes in the next regular session
        for row_id in await asyncio.to_thread(self._closed, now):
            await self._each("close", self.close, row_id)
        if not regular[1] <= minute < regular[2]:
            return
        for draft in await asyncio.to_thread(self._claim, now, regular):
            await self._each("adopt", self.adopt, draft, regular)
        for row_id, reasons in await asyncio.to_thread(self._due, now):
            await self._each("update", self.update, row_id, reasons)

    @staticmethod
    async def _each(what: str, step, *args) -> None:
        """One position's step; its failure is logged and never stops the others in the pass."""
        try:
            await step(*args)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Position companion %s failed", what)

    def _give_up(self, now: float) -> None:
        with Session(self.engine) as db:
            for row in db.exec(select(PositionCompanion).where(PositionCompanion.state == "adopting",
                                                               PositionCompanion.detected_at < _utc(now - ADOPT_SECONDS))).all():
                row.state, row.last_error = "failed", "The adopt turn did not finish, so it was given up."
                db.add(row)
            db.commit()

    # ------------------------------------------------------------ adopt

    def _claim(self, now: float, regular) -> list[Draft]:
        """New long options past the grace period, entered today since start, outside Webull, with no plan linked:
        each claimed once by its anchor."""
        from app.engine.plan_nudges import grace_seconds
        from app.engine.position_alerts import _count, _premium, open_positions
        today = datetime.fromtimestamp(now, ET).date()
        out = []
        with Session(self.engine) as db:
            webull = {a.id for a in db.exec(select(Account).where(Account.broker == "webull")).all()}
            for position in open_positions(db):
                trade, opened = position["trade"], position["opened_at"]
                if trade.account_id in webull or not capture_links.reliable(opened) or opened.date() != today:
                    continue
                first = stamp(opened)
                if first + 60 <= self.started_at or now < first + grace_seconds():
                    continue
                if not self._long_entry(db, trade.id):
                    continue
                if db.exec(select(PositionCompanion.id).where(PositionCompanion.account_id == trade.account_id,
                                                              PositionCompanion.source_key == position["source_key"])).first():
                    continue
                if capture_links.for_trade(db, trade.id):
                    continue  # planned: the plan's own alerts and desk thread have it
                row = PositionCompanion(account_id=trade.account_id, source_key=position["source_key"], trade_id=trade.id,
                                        ticker=trade.ticker, contract=position["contract"], option_type=trade.option_type or "call",
                                        expiration=trade.expiration, opened_at=opened, detected_at=_utc(now))
                db.add(row)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()  # another process claimed this position a moment earlier
                    continue
                out.append(Draft(row.id, trade.id, f"{_count(position['contracts'])} at {_premium(position['avg_cost'])}"))
            self._watch_newest(db)
        return out

    @staticmethod
    def _long_entry(db: Session, trade_id: uuid.UUID) -> bool:
        """A bought option (``open_positions`` already keeps long premium only; a sell-to-open entry is not adopted)."""
        sides = db.exec(select(Fill.side).join(TradeFill, TradeFill.fill_id == Fill.id)
                        .where(TradeFill.trade_id == trade_id, TradeFill.role == "entry")).all()
        return bool(sides) and "sell_to_open" not in sides

    def _watch_newest(self, db: Session) -> None:
        """At most ``COMPANION_MAX_POSITIONS`` watched at once: the newest win, the rest are adopt-only from then on."""
        live = db.exec(select(PositionCompanion).where(PositionCompanion.state.in_(("adopting", "draft", "armed")),
                                                       PositionCompanion.watched.is_(True))
                       .order_by(PositionCompanion.opened_at.desc(), PositionCompanion.detected_at.desc())).all()
        for row in live[max_positions():]:
            row.watched = False
            db.add(row)
        db.commit()

    async def adopt(self, draft: Draft, regular) -> None:
        now = self.clock()

        def read():
            with Session(self.engine) as db:
                row, trade = db.get(PositionCompanion, draft.row_id), db.get(Trade, draft.trade_id)
                chart = self.chart(row.ticker)
                plan = draft_plan(row.option_type, row.expiration, row.opened_at, chart, regular)
                return row.ticker, plan, adopt_prompt(trade, draft.size, row.opened_at, plan, chart), chart.get("last")

        ticker, plan, question, last = await asyncio.to_thread(read)
        answer, error = await self.turn(question, ticker, now)
        await asyncio.to_thread(self._adopted, draft, plan, question, answer, error, last)

    def _adopted(self, draft: Draft, plan: dict, question: str, answer: str, error: str | None, last) -> None:
        from app.engine import copilot_investigations as investigations
        now = self.clock()
        plan, read = parse_answer(answer, plan, last) if error is None else (plan, [])
        with Session(self.engine) as db:
            row = db.get(PositionCompanion, draft.row_id)
            if row is None or row.state != "adopting":
                return  # given up meanwhile
            name = label(row.ticker, row.option_type, _strike(row))
            reply = answer if error is None else f"Verdict: Unclear — The adopt turn failed: {error}\n" + "\n".join(adopt_lines([], plan, row.ticker))
            created = investigations.create(investigations.InvestigationFields(
                title=f"Adopted: {name}", symbol=row.ticker,
                transcript=[{"role": "user", "content": question[:20_000]}, {"role": "assistant", "content": reply[:20_000]}]), session=db)
            row.investigation_id, row.plan_json, row.state = uuid.UUID(created["id"]), json.dumps(plan), "draft"
            row.last_update_at, row.last_underlying = _utc(now), last if isinstance(last, (int, float)) else None
            row.last_error = None if error is None else f"Copilot turn failed: {error}"[:500]
            lines = adopt_lines(read, plan, row.ticker)
            db.add(row)
            db.commit()
            row.delivery, row.message_id, failure = self._send(
                db, row, source_id=str(row.id), kind="companion_adopt", title=f"Adopted: {name}", body="\n".join(lines),
                buttons=adopt_buttons(row, plan), reply_to=None, open_label="Edit", priority=4, now=now)
            row.last_error = failure or row.last_error
            if row.delivery not in ("sent", "unknown"):
                row.watched = False  # no thread to reply in and no Ignore on the phone: adopt-only, no updates
            contract, delivery = row.contract, row.delivery
            db.add(row)
            db.commit()
        log.info("Position companion adopted %s (%s)", contract, delivery)

    # ------------------------------------------------------------ watch

    def _due(self, now: float) -> list[tuple[uuid.UUID, list[str]]]:
        """Watched, open, not ignored positions with something new since their last update, under the day's ceiling and
        clear of the policy's quiet window."""
        moment = datetime.fromtimestamp(now, ET)
        today = moment.date()
        out = []
        with Session(self.engine) as db:
            rows = db.exec(select(PositionCompanion).where(PositionCompanion.state.in_(("draft", "armed")),
                                                           PositionCompanion.watched.is_(True))).all()
            trades = {row.id: trade_of(db, row) for row in rows}
            rows = [r for r in rows if trades[r.id] is not None and trades[r.id].status == "open"]
            if not rows:
                return []
            last = self.underlying(sorted({r.ticker for r in rows}))
            for row in rows:
                done_today = [u for u in updates_of(row) if u.get("day") == today.isoformat()]
                if len(done_today) >= max_updates():
                    continue
                since = row.last_update_at or row.detected_at
                if now - _epoch(since) < notification_policy.quiet_seconds():
                    continue  # at most one turn per quiet window, whatever keeps triggering
                reasons = self._reasons(db, row, trades[row.id], since, now, last.get(row.ticker))
                if not reasons:
                    continue
                if self._quiet(db, row, now):
                    continue  # the policy would hold it: wait for the window to pass
                out.append((row.id, reasons))
        return out

    def _reasons(self, db: Session, row: PositionCompanion, trade: Trade, since: datetime, now: float, underlying) -> list[str]:
        anchor = notification_policy.anchor(row.account_id, row.source_key)
        reasons = []
        pings = db.exec(select(PhonePing).where(PhonePing.sender != SENDER, PhonePing.decision == "sent", PhonePing.decided_at > since,
                                                PhonePing.kind.in_(POSITION_KINDS),
                                                or_(PhonePing.anchor == anchor, PhonePing.trade_id == trade.id))
                        .order_by(PhonePing.decided_at)).all()
        reasons += [f"a {notification_policy._label(p.kind)} alert went out ({p.title})" for p in pings]
        triggers = db.exec(select(ThesisWatchTrigger).where(ThesisWatchTrigger.symbol == row.ticker, ThesisWatchTrigger.fired_at > since)
                           .order_by(ThesisWatchTrigger.fired_at)).all()
        reasons += [f"thesis watch fired ({t.kind}: {t.text[:120]})" for t in triggers]
        try:
            reasons += [f"Radar: {summary}" for summary in self.radar(row.ticker, since, now)]
        except Exception:  # noqa: BLE001 - Radar is optional evidence
            log.warning("Companion Radar read failed", exc_info=True)
        if isinstance(underlying, (int, float)) and row.last_underlying:
            move = (underlying - row.last_underlying) / row.last_underlying * 100
            if abs(move) >= move_pct():
                reasons.append(f"{row.ticker} moved {move:+.1f}% since then ({row.last_underlying:,.2f} to {underlying:,.2f})")
        since_et, now_et = _utc_et(since), datetime.fromtimestamp(now, ET).replace(tzinfo=None)
        floor = row.opened_at + timedelta(minutes=FLOOR_MINUTES)
        if since_et < floor <= now_et:
            reasons.append(f"an hour since the entry at {_clock(row.opened_at)}")
        late = datetime.combine(now_et.date(), datetime.min.time()) + timedelta(minutes=LATE_MINUTE)
        if since_et < late <= now_et:
            reasons.append("15:30 and still open")
        return reasons

    @staticmethod
    def _quiet(db: Session, row: PositionCompanion, now: float) -> bool:
        anchor = notification_policy.anchor(row.account_id, row.source_key)
        return db.exec(select(PhonePing.id).where(PhonePing.anchor == anchor, PhonePing.decision == "sent",
                                                  PhonePing.decided_at >= _utc(now - notification_policy.quiet_seconds()))).first() is not None

    def _live(self, row: PositionCompanion, trade: Trade, now: float) -> dict:
        from app.engine.occ import occ_symbol
        from app.engine.position_alerts import _money, _premium
        out: dict = {}
        try:  # optional context: the prompt says "unavailable" without it
            out["underlying"] = self.underlying([row.ticker]).get(row.ticker)
            occ = occ_symbol(row.ticker, row.expiration, row.option_type, float(trade.strike))
            mark = self.marks([occ], now).get(occ) or {}
        except Exception:  # noqa: BLE001
            log.warning("Companion live read failed for %s", row.ticker, exc_info=True)
            return out
        if mark.get("mark") is not None:
            cost = float(trade.avg_entry_premium)
            gain = (mark["mark"] - cost) * float(trade.contracts) if trade.status == "open" else None
            out["mark"] = mark["mark"]
            out["mark_text"] = f"{_premium(mark['mark'])} (entry {_premium(cost)}" + (f", open P&L {_money(gain)})" if gain is not None else ")")
        return out

    async def update(self, row_id: uuid.UUID, reasons: list[str]) -> None:
        now = self.clock()

        def read():
            with Session(self.engine) as db:
                row = db.get(PositionCompanion, row_id)
                trade = trade_of(db, row)
                live = self._live(row, trade, now)
                return row, update_prompt(row, trade, reasons, live), live

        found = await asyncio.to_thread(read)
        row, question, live = found
        index = await asyncio.to_thread(self._attempt, row_id, reasons, live, now)
        if index is None:
            return
        answer, error = await self.turn(question, row.ticker, now)
        await asyncio.to_thread(self._updated, row_id, index, question, answer, error)

    def _attempt(self, row_id, reasons: list[str], live: dict, now: float) -> int | None:
        """Record the update before its turn, so it counts toward the ceiling and the pacing whatever happens next."""
        with Session(self.engine) as db:
            row = db.get(PositionCompanion, row_id)
            if row is None or row.state not in ("draft", "armed"):
                return None  # ignored or closed meanwhile
            updates = updates_of(row)
            updates.append({"at": int(now), "day": datetime.fromtimestamp(now, ET).date().isoformat(), "reasons": reasons[:8],
                            "delivery": "pending", "answer": None})
            row.updates_json, row.last_update_at = json.dumps(updates), _utc(now)
            if isinstance(live.get("underlying"), (int, float)):
                row.last_underlying = live["underlying"]
            db.add(row)
            db.commit()
            return len(updates) - 1

    def _updated(self, row_id, index: int, question: str, answer: str, error: str | None) -> None:
        now = self.clock()
        result: dict = {"delivery": "failed"}
        with Session(self.engine) as db:
            row = db.get(PositionCompanion, row_id)
            if row is None:
                return
            if error is not None:
                result["error"] = f"Copilot turn failed: {error}"[:300]
            elif row.state not in ("draft", "armed"):
                result["delivery"] = "skipped"  # ignored or closed while the turn ran
            else:
                try:
                    save_messages(row.investigation_id, [{"role": "user", "content": question},
                                                         {"role": "assistant", "content": answer}], session=db)
                except Exception as exc:  # noqa: BLE001 - the ping still goes; the desk thread misses this update
                    db.rollback()
                    log.warning("Companion update not saved on its investigation: %s", type(exc).__name__)
                    result["error"] = f"Not saved on the desk thread ({type(exc).__name__})."
                name = label(row.ticker, row.option_type, _strike(row))
                result["delivery"], result["message_id"], failure = self._send(
                    db, row, source_id=f"{row.id}:u{index}", kind="companion_update", title=f"{name} · update",
                    body=words(answer, UPDATE_WORDS), buttons=update_buttons(row, index), reply_to=row.message_id,
                    open_label="Open", priority=3, now=now)
                if failure:
                    result["error"] = failure[:300]
            db.commit()
            db.refresh(row)  # an answer tapped meanwhile is kept: only this update's entry changes
            updates = updates_of(row)
            if index < len(updates):
                updates[index].update(result)
                row.updates_json = json.dumps(updates)
                db.add(row)
                db.commit()

    # ------------------------------------------------------------ close

    def _closed(self, now: float) -> list[uuid.UUID]:
        """Adopted positions whose exits brought them to zero: any armed invalidation is removed now, and each is returned
        once no ping for it is inside the quiet window (so the exit note is not held by it)."""
        with Session(self.engine) as db:
            rows = db.exec(select(PositionCompanion).where(PositionCompanion.state.in_(("draft", "armed")))).all()
            out = []
            for row in rows:
                trade = trade_of(db, row)
                if trade is None or trade.status == "open":
                    continue
                _disarm(db, row)  # at once: only the note waits, so a closed position never pings "your plan says out"
                db.commit()
                if not row.watched or not self._quiet(db, row, now):
                    out.append(row.id)
            return out

    async def close(self, row_id: uuid.UUID) -> None:
        now = self.clock()

        def read():
            with Session(self.engine) as db:
                # Claimed closed before the turn: a failure after it never repeats the turn, and a Confirm racing it loses.
                claimed = db.exec(update(PositionCompanion).where(PositionCompanion.id == row_id,
                                                                  PositionCompanion.state.in_(("draft", "armed")))
                                  .values(state="closed", closed_at=_utc(now)))
                db.commit()
                if claimed.rowcount != 1:
                    return None
                row = db.get(PositionCompanion, row_id)
                _disarm(db, row)
                db.commit()
                if not row.watched:  # adopt-only: closed quietly, no turn
                    _close_thread(db, row, "Closed: adopt-only, so no exit note was written.")
                    return None
                trade = trade_of(db, row)
                prior = "armed" if row.alert_id else "draft"
                live = self._live(row, trade, now)
                return row, close_prompt(row, trade, live, confirmed=prior == "armed")

        found = await asyncio.to_thread(read)
        if found is None:
            return
        row, question = found
        try:
            answer, error = await self.turn(question, row.ticker, now)
        except Exception as exc:  # noqa: BLE001 - the row is already closed, so the thread must still be closed here
            log.warning("Companion close turn failed: %s", type(exc).__name__)
            answer, error = "", "The copilot turn failed unexpectedly."
        await asyncio.to_thread(self._finished, row_id, question, answer, error)

    def _finished(self, row_id, question: str, answer: str, error: str | None) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            row = db.get(PositionCompanion, row_id)
            if row is None:
                return
            note = answer if error is None else f"Verdict: Unclear — The exit note could not be written: {error}"
            first = next((line for line in note.splitlines() if line.strip()), "")
            try:
                save_messages(row.investigation_id, [{"role": "user", "content": question}, {"role": "assistant", "content": note}],
                              status="closed", conclusion=unlabelled(first)[:280] or None, session=db)
            except Exception as exc:  # noqa: BLE001 - the note still goes to the phone
                db.rollback()
                log.warning("Companion exit note not saved on its investigation: %s", type(exc).__name__)
                row.last_error = f"Exit note not saved on the desk thread ({type(exc).__name__})."
                db.add(row)
                db.commit()
            if error is None:
                name = label(row.ticker, row.option_type, _strike(row))
                _, _, failure = self._send(db, row, source_id=f"{row.id}:close", kind="companion_update", title=f"{name} · closed",
                                                  body=words(note, 120), buttons=(), reply_to=row.message_id, open_label="Open",
                                                  priority=3, now=now)
                row.last_error = failure
                db.add(row)
                db.commit()

    # ------------------------------------------------------------ send

    def _send(self, db: Session, row: PositionCompanion, *, source_id: str, kind: str, title: str, body: str,
              buttons: tuple, reply_to: str | None, open_label: str, priority: int, now: float) -> tuple[str, str | None, str | None]:
        """One ping through the policy: ``(delivery, Telegram message id, error)``. Never retried."""
        from app.engine.position_alerts import _surely_unsent
        if not phone.configured():
            return "off", None, "Phone alerts are not set up on this server."
        ticket = notification_policy.decide(db, sender=SENDER, source_id=source_id, kind=kind, title=title, body=body, now=now,
                                            anchor=notification_policy.anchor(row.account_id, row.source_key), symbol=row.ticker,
                                            trade_id=row.trade_id)
        if ticket.held:
            return "held", None, ticket.reason
        try:
            receipt, _ = phone.send(title, body + ticket.append, kind=kind, path=desk_path(row.investigation_id), buttons=buttons,
                                    priority=priority, reply_to=reply_to, open_label=open_label, tags=("robot",), direct_click=True)
        except phone.SendError as exc:
            if not _surely_unsent(exc):
                notification_policy.delivered(db, ticket, now)
                return "unknown", None, f"{exc} It may have reached the phone, so it was not resent."
            return "failed", None, str(exc)
        notification_policy.delivered(db, ticket, now)
        return "sent", receipt if phone.transport() == "telegram" else None, None


def _disarm(db: Session, row: PositionCompanion) -> None:
    """Remove the confirmed invalidation alert if it is still armed (the level alert route's delete); a fired one stays
    as the record of the hit. The monitor drops it on its next reload."""
    from app.models import LevelAlert
    alert = db.get(LevelAlert, row.alert_id) if row.alert_id else None
    if alert is not None and alert.state == "active":
        _remove_alert(db, alert.id)


def _remove_alert(db: Session, alert_id: uuid.UUID) -> None:
    from sqlmodel import delete
    from app.models import LevelAlert, LevelAlertEvent
    db.exec(delete(LevelAlertEvent).where(LevelAlertEvent.alert_id == alert_id))
    db.exec(delete(LevelAlert).where(LevelAlert.id == alert_id))


def _close_thread(db: Session, row: PositionCompanion, conclusion: str) -> None:
    """Close the adopted investigation with no new message, so it leaves the desk's open threads."""
    if row.investigation_id is None:
        return
    try:
        save_messages(row.investigation_id, [], status="closed", conclusion=conclusion, session=db)
    except Exception:  # noqa: BLE001 - the owner can still close it on the desk
        db.rollback()
        log.warning("Companion thread not closed", exc_info=True)


def _strike(row: PositionCompanion):
    """The strike, from the contract label ('NBIS 11/21/26 160C')."""
    found = re.search(r"(\d+(?:\.\d+)?)[CP]$", row.contract)
    return float(found.group(1)) if found else 0


def companion_from_env(engine):
    """The lifespan's companion, or None while it is off."""
    if not enabled():
        return None
    from app.engine.chart_calendar import chart_calendar
    return Companion(engine, chart_calendar)
