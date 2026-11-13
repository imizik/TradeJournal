"""Each copilot turn's record (``copilot_turn``) and the day's API spend against ``COPILOT_DAILY_BUDGET_USD``
(docs/copilot-lab.md § Measuring the copilot).

Every model turn the app runs goes through ``recorded_turn`` (the desk, the Charts dock, Telegram, the morning brief,
the week review, the companion) or ``record`` (the shadow book), so one row describes each: what it was for (``kind``),
where it came from (``source``), its model, rounds, tokens, cost, the owner's wait, the tools it read, and the error
code when it failed or was stopped. A refused turn (the daily budget spent) is a zero-cost row too. The saved
conversation links itself to its turns when the browser saves it (``link``). Only ``billing == "api"`` rows count
toward the day's budget. Days are New York days. No prompt or answer text is kept here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import AsyncIterator, Iterable, Sequence

log = logging.getLogger(__name__)

# "plan" only labels turns recorded before everything moved to the API.
BILLING = {"anthropic": "api", "shadow": "api_background", "plan": "claude_plan", "fake": "none"}
KINDS = frozenset({"ask", "briefing", "plan", "review", "week_review", "moment", "changes", "compare", "pushback", "prep",
                   "companion", "shadow", "check_call", "desk_read", "day_read"})
SOURCES = frozenset({"desk", "charts", "radar", "panel", "telegram", "prep", "week_review", "companion", "shadow", "eval"})
PUSHBACK = re.compile(r"^\s*push back on\b", re.I)
COMPARE_LINE = re.compile(r"^\**compare\**\s*:", re.I | re.M)
WHAT_MATTERS = "What matters right now across my open positions"  # frontend/lib/copilot.ts WHAT_MATTERS_PROMPT
MAX_TOOL_NAMES = 50
TEXT_FOR_KIND = 2000  # how much of the answer kind_of reads; nothing of it is stored


def _day_start_utc() -> datetime:
    from app.engine.chart_math import ET
    start = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC).replace(tzinfo=None)


def record(metrics: dict, symbol: str | None = None, session=None, *, turn_id: uuid.UUID | None = None, kind: str | None = None,
           source: str | None = None, investigation_id: uuid.UUID | str | None = None, tool_names: Sequence[str] | None = None,
           error: str | None = None, effort: str | None = None, evidence: str | None = None) -> uuid.UUID | None:
    """One row for a turn; a failure to write never reaches the owner. Returns the row id, or None when nothing was
    written. ``metrics`` is the turn's ``done`` metrics (or what a stopped turn had so far)."""
    from sqlmodel import Session
    from app.database import engine
    from app.models import CopilotTurn
    usage = metrics.get("usage") or {}
    backend = str(metrics.get("backend") or "fake")
    names = [str(n)[:64] for n in (tool_names if tool_names is not None else _names(metrics)) if n][:MAX_TOOL_NAMES]
    row = CopilotTurn(id=turn_id or uuid.uuid4(), backend=backend, billing=BILLING.get(backend, "none"), model=metrics.get("model"),
                      symbol=symbol, rounds=int(metrics.get("rounds") or 0),
                      input_tokens=int(usage.get("input_tokens") or 0), output_tokens=int(usage.get("output_tokens") or 0),
                      cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
                      cost_usd=float(metrics.get("cost_usd") or 0.0), total_ms=metrics.get("total_ms"),
                      kind=kind, source=source, investigation_id=_uuid(investigation_id), tool_names=json.dumps(names),
                      first_text_ms=metrics.get("first_text_ms"), max_silence_ms=metrics.get("max_silence_ms"),
                      cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                      error=(error or None) and str(error)[:80], effort=effort or metrics.get("effort"),
                      evidence=evidence or metrics.get("evidence"), timings=timings_json(metrics))
    try:
        with (Session(engine) if session is None else nullcontext(session)) as db:
            db.add(row)
            db.commit()
            return row.id
    except Exception:  # noqa: BLE001 - bookkeeping must not break a turn that already answered
        log.warning("copilot turn not recorded", exc_info=True)
        return None


def record_refused(*, kind: str, source: str, backend: str, code: str, symbol: str | None = None, session=None) -> uuid.UUID | None:
    """A turn that never ran (the daily budget was spent): a zero-cost row with the refusal as its error."""
    return record({"backend": backend, "rounds": 0, "usage": {}, "cost_usd": 0.0, "total_ms": 0}, symbol, session,
                  kind=kind, source=source, error=code)


CALL_KEYS = ("name", "status", "ms", "queue_ms", "feed_wait_ms", "feed_ms")  # copilot.call_metrics' row
MAX_ROUNDS = 12


def timings_json(metrics: dict) -> str | None:
    """Where the turn's wait went, as the row keeps it: the owner context read and each tool call with its time and split
    (``copilot.call_metrics``), each round's model time and, for a round that read tools, their wall clock
    (``metrics["rounds_ms"]``), and what the turn prefetched. None when the turn recorded none of it."""
    calls = [c for c in metrics.get("tool_calls") or [] if isinstance(c, dict)]
    rounds = [r for r in metrics.get("rounds_ms") or [] if isinstance(r, dict)]
    if not calls and not rounds:
        return None

    def row(call: dict) -> dict:
        return {k: (str(v)[:64] if k in ("name", "status") else v) for k, v in call.items() if k in CALL_KEYS and v is not None}

    pack = next((row(c) for c in calls if c.get("name") == "owner_context"), None)
    out = {"owner_context": pack, "rounds": [{k: r[k] for k in ("model_ms", "tools_ms") if r.get(k) is not None} for r in rounds][:MAX_ROUNDS],
           "tools": [row(c) for c in calls if c.get("name") != "owner_context"][:MAX_TOOL_NAMES],
           "prefetch": [str(n)[:64] for n in metrics.get("prefetch") or []][:4]}
    return json.dumps(out, separators=(",", ":"))


def _names(metrics: dict) -> list[str]:
    return [c.get("name") for c in metrics.get("tool_calls") or [] if c.get("name") and c.get("name") != "owner_context"]


def _uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def kind_of(question: str, tool_names: Iterable[str], proposal_kinds: Iterable[str], answer: str) -> str:
    """What a desk, dock or Telegram turn was for, from the owner's words, the tools it read, the cards it proposed and
    the answer's shape. First match wins; ``ask`` otherwise."""
    tools, cards = set(tool_names), set(proposal_kinds)
    if PUSHBACK.match(question or ""):
        return "pushback"
    if "get_week_review" in tools:
        return "week_review"
    if "get_trade_review" in tools:
        return "review"
    if "get_investigation_changes" in tools:
        return "changes"
    if "get_moment" in tools:
        return "moment"
    if "trade_plan" in cards:
        return "plan"
    if WHAT_MATTERS in (question or "")[:600]:  # the panel may put a "Context: …" line ahead of it
        return "briefing"
    if COMPARE_LINE.search(answer or ""):
        return "compare"
    return "ask"


async def recorded_turn(history: list[dict], symbol: str | None, cfg, adapter, evidence, now: datetime, *, kind: str | None,
                        source: str, images: list[dict] | None = None, carry_id: str | None = None,
                        investigation_id: uuid.UUID | str | None = None, web: bool = False) -> AsyncIterator[dict]:
    """``copilot.run_turn`` with its row: the same events, the ``done`` event carrying ``turn_id``, and one
    ``copilot_turn`` row whatever happens. A turn the consumer stops before ``done`` is recorded with what it spent and
    ``error="stopped"``. ``kind`` None means: work it out from the turn (``kind_of``)."""
    from app.ai import copilot, copilot_prompt
    from app.ai.copilot_context import user_text
    turn_id = uuid.uuid4()
    live: dict = {}
    error: str | None = None
    proposals: list[str] = []
    text: list[str] = []
    text_len = 0
    question = user_text(history[-1]["content"]) if history else ""
    finished = False
    try:
        async for event in copilot.run_turn(history, symbol, cfg, adapter, evidence, now, images=images, carry_id=carry_id, live=live,
                                              web=web, investigation_id=investigation_id,
                                              job=copilot_prompt.job_for(kind, source)):
            etype = event.get("type")
            if etype == "error" and error is None:
                error = event.get("code")
            elif etype == "proposal":
                proposals.append(event.get("kind"))
            elif etype == "text" and text_len < TEXT_FOR_KIND:
                text.append(event.get("delta") or "")
                text_len += len(text[-1])
            elif etype == "done":
                finished = True
                event = {**event, "turn_id": str(turn_id)}
            yield event
    finally:
        names = _names(live)
        chosen = kind or kind_of(question, names, proposals, "".join(text))
        # Never awaited here: a consumer that stopped (GeneratorExit) or a request being cancelled would re-raise through an
        # await and lose the row. The default executor writes it; a stopped turn keeps the cost it had reached.
        if not finished:
            live.setdefault("total_ms", None)
            error = "stopped"

        def write() -> None:
            record(live, symbol, turn_id=turn_id, kind=chosen, source=source, investigation_id=investigation_id,
                   tool_names=names, error=error, effort=cfg.effort, evidence=cfg.evidence)

        try:
            asyncio.get_running_loop().run_in_executor(None, write)
        except RuntimeError:  # no loop: record inline
            write()


def link(db, investigation_id: uuid.UUID | str, turn_ids: Iterable[str]) -> int:
    """Point each turn at the conversation it was saved into; a turn already linked elsewhere is left alone."""
    from sqlmodel import col, update
    from app.models import CopilotTurn
    ids = [t for t in (_uuid(v) for v in turn_ids) if t is not None]
    target = _uuid(investigation_id)
    if not ids or target is None:
        return 0
    result = db.exec(update(CopilotTurn).where(col(CopilotTurn.id).in_(ids), col(CopilotTurn.investigation_id).is_(None))
                     .values(investigation_id=target))
    db.commit()
    return result.rowcount or 0


def spent_today(session=None) -> float:
    """Estimated API dollars for today's ``anthropic`` turns (New York day)."""
    from sqlmodel import Session, col, select
    from app.database import engine
    from app.models import CopilotTurn
    with (Session(engine) if session is None else nullcontext(session)) as db:
        rows = db.exec(select(CopilotTurn.cost_usd).where(CopilotTurn.billing == "api",
                                                          col(CopilotTurn.started_at) >= _day_start_utc())).all()
    return round(sum(float(c or 0) for c in rows), 6)


def kind_today(kind: str, session=None) -> dict:
    """Today's turns of one ``kind`` (New York day): how many ran, how many were refused for the daily budget, and their
    estimated API dollars (``billing == "api"`` only, as ``spent_today`` counts them)."""
    from sqlmodel import Session, col, select
    from app.database import engine
    from app.models import CopilotTurn
    with (Session(engine) if session is None else nullcontext(session)) as db:
        rows = db.exec(select(CopilotTurn.billing, CopilotTurn.cost_usd, CopilotTurn.error).where(
            CopilotTurn.kind == kind, col(CopilotTurn.started_at) >= _day_start_utc())).all()
    refused = sum(1 for _, _, error in rows if error == "daily_budget")
    return {"count": len(rows) - refused, "refused": refused,
            "cost_usd": round(sum(float(cost or 0) for billing, cost, _ in rows if billing == "api"), 4)}
