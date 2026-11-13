"""The desk's read of a selected ticker (``POST /copilot/desk/read``, docs/copilot-lab.md § The desk read).

When the owner selects a ticker on the desk and no conversation about it is open, the copilot panel shows three or four
lines about it without his typing: where it is against his levels or plan, what is moving it today, and the one thing
that would change the picture (``copilot_prompt.DESK_READ``). Cost and noise are the point, so:

- one read per ticker is kept in memory for ``TTL_MARKET_S`` in the regular session and ``TTL_OFF_S`` outside it (never
  past the next open); a reselect inside that window gets the kept read and its age, and no model call. ``refresh`` (his
  tap, or the panel when the kept read has expired while he is still on the ticker) reads again;
- one read at a time, across every ticker: a second request waits, and one for the same ticker gets the first's result;
- a small turn: ``MAX_ROUNDS`` rounds (one of reads, one to write), ``MAX_TOOL_CALLS`` reads, ``READ_BUDGET_USD`` as its
  spend cap and ``MAX_TOKENS``, on the configured model (no cheaper model has held the answer shape in the eval:
  docs/copilot-lab.md § Follow-up model eval);
- every read is a ``copilot_turn`` row (``kind="desk_read"``) and counts toward the same ``COPILOT_DAILY_BUDGET_USD``. A
  read is refused, with a zero-cost row, unless ``HEADROOM`` reads' worth of its cap still fits under the day's budget: the
  cap is checked between rounds, so the answer round runs past it, never by as much again. Reads run one at a time, so
  the check sees every earlier read's cost;
- a ticker he does not follow never gets a read, and a setting that cannot be read gets none either.

The panel waits ``1.5 s`` on a selection before asking and keeps the off switch (``frontend/components/copilot/DeskRead.tsx``).
Nothing is saved but the turn's row; the read is never written into a conversation unless he asks more.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import re
import time
from datetime import datetime

log = logging.getLogger(__name__)

TTL_MARKET_S = 30 * 60
TTL_OFF_S = 2 * 60 * 60
READ_BUDGET_USD = 0.10  # the turn's spend cap (scaled up for a model dearer than Opus, as every turn's is)
HEADROOM = 2  # a read starts only while this many of its caps still fit under the day's budget
MAX_ROUNDS = 2
MAX_TOOL_CALLS = 4
MAX_TOKENS = 1500
KIND = "desk_read"
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
QUESTION = ("Desk read: {symbol}. A glance before I ask anything: where it is against my levels, what is moving it "
            "today, and the one thing that would change the picture.")

_kept: dict[str, dict] = {}
_lock: asyncio.Lock | None = None  # one read at a time, made on first use in the running loop
# Reads just finished, (monotonic time, cost): a turn's row is written after its stream ends, so the next read's budget
# check adds these until the row is surely in (counted twice meanwhile at worst, which only refuses a read sooner).
_just_spent: list[tuple[float, float]] = []
UNRECORDED_S = 30.0


def clear() -> None:
    """Forget every kept read (tests)."""
    global _lock
    _kept.clear()
    _just_spent.clear()
    _lock = None


def expires_at(now: float) -> float:
    """When a read made at ``now`` (epoch seconds) stops being shown as current: ``TTL_MARKET_S`` in the regular session,
    else ``TTL_OFF_S``, and never past the next regular open of the same day."""
    from app.engine.chart_math import ET, session_windows
    local = datetime.fromtimestamp(now, ET)
    try:
        from app.engine.chart_calendar import chart_calendar
        hours = chart_calendar.hours(local.date())
    except Exception:  # noqa: BLE001 - the clock hours stand in
        hours = None
    minute = local.hour * 60 + local.minute + local.second / 60
    regular = next(((start, end) for name, start, end in session_windows(local.date(), hours) if name == "regular"), None)
    if regular and regular[0] <= minute < regular[1]:
        return now + TTL_MARKET_S
    if regular and minute < regular[0]:
        return min(now + TTL_OFF_S, now + (regular[0] - minute) * 60)
    return now + TTL_OFF_S


def _shown(entry: dict, now: float, cached: bool) -> dict:
    return {"state": "ok", "text": entry["text"], "at": entry["at"], "expires_at": entry["expires_at"],
            "age_s": max(0, round(now - entry["at"])), "cached": cached, "cost_usd": entry["cost_usd"]}


def _not_followed(symbol: str) -> bool | None:
    """Whether he set ``symbol`` to Not following; None when the setting cannot be read (then there is no read)."""
    from sqlmodel import Session
    from app.database import engine
    from app.engine import day_journal
    try:
        with Session(engine) as db:
            return symbol in day_journal.not_following(db)
    except Exception:  # noqa: BLE001 - never a read for a ticker that may be hidden
        log.warning("Not-followed tickers could not be read; no desk read", exc_info=True)
        return None


def today() -> dict | None:
    """Today's reads: how many ran, how many the budget refused, what they cost. None when the record cannot be read."""
    from app.ai import copilot_spend
    try:
        return copilot_spend.kind_today(KIND)
    except Exception:  # noqa: BLE001 - the read stands without its count
        log.warning("Desk read count could not be read", exc_info=True)
        return None


async def read(symbol: str, *, refresh: bool = False, now: float | None = None) -> dict:
    """The read for ``symbol``: ``state`` ``ok`` (``text``, ``at``, ``expires_at``, ``age_s``, ``cached``), ``hidden``
    (not followed, or the setting unreadable), ``budget`` (the day's budget has no room for a read: ``message``) or
    ``error`` (``message``). ``today`` carries the day's read count and cost on every answer."""
    from app.ai import copilot, copilot_spend
    symbol = (symbol or "").strip().upper()
    if not SYMBOL.match(symbol):
        return {"state": "error", "message": "Not a ticker."}
    cfg = copilot.settings()
    asked = time.time() if now is None else now
    hidden = await asyncio.to_thread(_not_followed, symbol)
    if hidden is not False:
        _kept.pop(symbol, None)
        return {"state": "hidden"}
    entry = _kept.get(symbol)
    if entry and not refresh and asked < entry["expires_at"]:
        return {**_shown(entry, asked, True), "today": await asyncio.to_thread(today)}
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        entry = _kept.get(symbol)
        # Another request read it while this one waited (``at`` is when a read was asked): its read is the fresh one.
        if entry and (entry["at"] >= asked or (not refresh and asked < entry["expires_at"])):
            return {**_shown(entry, asked, True), "today": await asyncio.to_thread(today)}
        if cfg.backend == "anthropic":
            fresh = time.monotonic() - UNRECORDED_S
            _just_spent[:] = [(t, c) for t, c in _just_spent if t >= fresh]
            spent = await asyncio.to_thread(copilot_spend.spent_today) + sum(c for _, c in _just_spent)
            if spent + HEADROOM * copilot.turn_cap(small(cfg), False) > cfg.daily_budget_usd:
                await asyncio.to_thread(copilot_spend.record_refused, kind=KIND, source="desk", backend=cfg.backend,
                                        code="daily_budget", symbol=symbol)
                return {"state": "budget", "today": await asyncio.to_thread(today),
                        "message": f"No automatic read: today's copilot budget (${cfg.daily_budget_usd:.2f}) is spent."}
        # The day's count is read before the turn: its own row is written after the stream ends, so it is added here.
        before = await asyncio.to_thread(today)
        result = await _run(symbol, cfg, asked)
        if result.get("cost_usd"):
            _just_spent.append((time.monotonic(), result["cost_usd"]))
        counted = before if before is None or "cost_usd" not in result else {**before, "count": before["count"] + 1,
                              "cost_usd": round(before["cost_usd"] + result["cost_usd"], 4)}
        if result["state"] == "ok":
            for gone in [s for s, e in _kept.items() if e["expires_at"] <= asked]:  # only current reads stay in memory
                _kept.pop(gone, None)
            until = await asyncio.to_thread(expires_at, asked)  # the calendar may be read from the provider
            _kept[symbol] = {"text": result["text"], "at": asked, "expires_at": until, "cost_usd": result["cost_usd"]}
            return {**_shown(_kept[symbol], asked, False), "today": counted}
        return {**result, "today": counted}


def small(cfg):
    """The read's turn settings: the configured model, two rounds, four reads, its own cap and output limit."""
    return dataclasses.replace(cfg, max_rounds=MAX_ROUNDS, max_tool_calls=MAX_TOOL_CALLS, max_tokens=MAX_TOKENS,
                               turn_budget_usd=READ_BUDGET_USD)


async def _run(symbol: str, cfg, at: float) -> dict:
    """One small recorded turn; ``{"state": "ok", "text", "cost_usd"}`` or ``{"state": "error", "message"}``."""
    from app.ai import copilot, copilot_spend
    from app.engine.chart_math import ET
    turn_cfg = small(cfg)
    try:
        adapter = await asyncio.to_thread(copilot.adapter_for, turn_cfg)
        evidence = copilot.evidence_for(turn_cfg)
    except copilot.CopilotError as exc:
        return {"state": "error", "message": exc.message}  # no turn ran, so no row
    parts: list[str] = []
    errors: list[str] = []
    cost = 0.0
    try:
        turn = copilot_spend.recorded_turn([{"role": "user", "content": QUESTION.format(symbol=symbol)}], symbol, turn_cfg, adapter,
                                           evidence, datetime.fromtimestamp(at, ET), kind=KIND, source="desk")
        async with contextlib.aclosing(turn) as events:
            async for event in events:
                if event.get("type") == "text":
                    parts.append(event.get("delta") or "")
                elif event.get("type") == "error":
                    errors.append(event.get("message") or event.get("code") or "error")
                elif event.get("type") == "done":
                    cost = float((event.get("metrics") or {}).get("cost_usd") or 0.0)
    except Exception:  # noqa: BLE001 - the row records what happened; the panel says it plainly
        log.warning("desk read failed", exc_info=True)
        errors.append("The read failed.")
    finally:
        if hasattr(adapter, "aclose"):
            await adapter.aclose()
    text = "".join(parts).strip()
    if errors or not text:
        return {"state": "error", "message": errors[0] if errors else "The copilot wrote nothing.", "cost_usd": round(cost, 4)}
    return {"state": "ok", "text": text, "cost_usd": round(cost, 4)}
