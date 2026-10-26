"""Each copilot turn's model and cost (``copilot_turn``), and the day's API spend against ``COPILOT_DAILY_BUDGET_USD``.

A turn's ``done`` metrics are recorded once the stream ends: backend, model, rounds, tokens and the estimated USD.
Only ``billing == "api"`` rows (the ``anthropic`` backend) count toward the day's budget; the plan is not billed per
token and the fake backend makes no call. Days are New York days. No prompt or answer text is kept here.
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import UTC, datetime

log = logging.getLogger(__name__)

BILLING = {"anthropic": "api", "plan": "claude_plan", "fake": "none"}


def _day_start_utc() -> datetime:
    from app.engine.chart_math import ET
    start = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC).replace(tzinfo=None)


def record(metrics: dict, symbol: str | None = None, session=None) -> None:
    """One row for a finished turn; a failure to write never reaches the owner."""
    from sqlmodel import Session
    from app.database import engine
    from app.models import CopilotTurn
    usage = metrics.get("usage") or {}
    backend = str(metrics.get("backend") or "fake")
    row = CopilotTurn(backend=backend, billing=BILLING.get(backend, "none"), model=metrics.get("model"),
                      symbol=symbol, rounds=int(metrics.get("rounds") or 0),
                      input_tokens=int(usage.get("input_tokens") or 0), output_tokens=int(usage.get("output_tokens") or 0),
                      cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
                      cost_usd=float(metrics.get("cost_usd") or 0.0), total_ms=metrics.get("total_ms"))
    try:
        with (Session(engine) if session is None else nullcontext(session)) as db:
            db.add(row)
            db.commit()
    except Exception:  # noqa: BLE001 - bookkeeping must not break a turn that already answered
        log.warning("copilot turn not recorded", exc_info=True)


def spent_today(session=None) -> float:
    """Estimated API dollars for today's ``anthropic`` turns (New York day)."""
    from sqlmodel import Session, col, select
    from app.database import engine
    from app.models import CopilotTurn
    with (Session(engine) if session is None else nullcontext(session)) as db:
        rows = db.exec(select(CopilotTurn.cost_usd).where(CopilotTurn.billing == "api",
                                                          col(CopilotTurn.started_at) >= _day_start_utc())).all()
    return round(sum(float(c or 0) for c in rows), 6)
