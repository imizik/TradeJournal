"""Fixture-only personal decision replay with frozen public and sealed packets."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine.decisions import _canonical, _hash
from app.models import PracticeReplayAttempt

SCENARIO_ID = "synthetic-option-position-v1"
SCENARIO = {
    "id": SCENARIO_ID,
    "title": "The open position",
    "symbol": "XYZ",
    "instrument": "Long call · 7 DTE",
    "option_contract": {"right": "call", "strike": 500.0, "expiry": "2026-02-17", "dte_at_entry": 7},
    "description": "A synthetic closed trade with two decision points. Every price and event is invented.",
    "checkpoint_count": 2,
}
ORDER = ("first-look", "later-look")
_ET = timezone(timedelta(hours=-5))
_BASE = datetime(2026, 2, 10, 13, 30, tzinfo=_ET)
_CUTOFFS = {
    "first-look": datetime(2026, 2, 10, 14, 30, tzinfo=_ET),
    "later-look": datetime(2026, 2, 10, 15, 0, tzinfo=_ET),
}


def _sha(value: object) -> str:
    return _hash(_canonical(value))


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _underlying_close(minute: int) -> float:
    """Invented 1-minute fixture path, specified directly at each minute."""
    anchors = ((0, 500.00), (35, 503.00), (60, 501.20), (90, 500.20), (95, 498.80))
    for (left_i, left_v), (right_i, right_v) in zip(anchors, anchors[1:]):
        if minute <= right_i:
            fraction = (minute - left_i) / (right_i - left_i)
            # Small fixed wobble gives each native minute a plausible distinct close.
            wobble = (0.08 if minute % 3 == 0 else -0.04 if minute % 3 == 1 else 0.02)
            return round(left_v + (right_v - left_v) * fraction + wobble, 2)
    return anchors[-1][1]


def _minute_bar(minute: int) -> dict:
    start = _BASE + timedelta(minutes=minute)
    end = start + timedelta(minutes=1)
    op = _underlying_close(max(0, minute - 1))
    close = _underlying_close(minute)
    observed = end
    published = end + timedelta(seconds=2)
    retrieved = end + timedelta(seconds=6)
    return {
        "interval_start": _stamp(start), "interval_end": _stamp(end),
        "open": op, "high": round(max(op, close) + 0.05, 2),
        "low": round(min(op, close) - 0.05, 2), "close": close,
        "volume": 1200 + (minute % 7) * 110,
        "observed_at": _stamp(observed), "published_at": _stamp(published),
        "retrieved_at": _stamp(retrieved), "source": "synthetic_fixture",
        "price_basis": "synthetic_underlying",
    }


def _bar_projection(bar: dict) -> dict:
    """Explicitly allowlist market observations; unknown fixture notes never cross the API."""
    return {key: bar[key] for key in (
        "interval_start", "interval_end", "open", "high", "low", "close", "volume",
        "observed_at", "published_at", "retrieved_at", "source", "price_basis")}


def _freeze_checkpoint(checkpoint_id: str) -> dict:
    cutoff = _CUTOFFS[checkpoint_id]
    cutoff_stamp = _stamp(cutoff)
    # Whitelist fixture facts, then enforce all independent time boundaries.
    source_bars = [_minute_bar(m) for m in range(95)]
    bars = []
    for source in source_bars:
        end = datetime.fromisoformat(source["interval_end"])
        observed = datetime.fromisoformat(source["observed_at"])
        published = datetime.fromisoformat(source["published_at"])
        retrieved = datetime.fromisoformat(source["retrieved_at"])
        if end <= datetime.fromisoformat(source["interval_start"]) or observed < end or published < observed or retrieved < published:
            raise ValueError("synthetic fixture provenance order is invalid")
        if end <= cutoff and observed <= cutoff and published <= cutoff:
            bars.append(_bar_projection(source))
    if not bars or any(datetime.fromisoformat(b["published_at"]) > cutoff for b in bars):
        raise ValueError("synthetic fixture has no complete evidence at its declared cutoff")
    recent_minutes = [{"t": b["interval_start"], "o": b["open"], "h": b["high"], "l": b["low"],
                       "c": b["close"], "v": b["volume"], "vw": None} for b in bars]
    chart_packet = {"sample_data": True, "recent_minute_bars": recent_minutes}
    chart_context = {"context_id": f"fixture-{checkpoint_id}", "symbol": SCENARIO["symbol"],
        "captured_at": cutoff_stamp, "provider": "sample_fixture", "context_sha256": _sha(chart_packet),
        "price_facts": [], "packet": chart_packet}
    position = ({"contracts": 2, "entry_premium_per_contract": 210.0,
                 "checkpoint_mark_per_contract": 315.0, "open_return_pct": 50.0,
                 "peak_open_return_pct": 75.0, "mark_time": _stamp(cutoff - timedelta(seconds=10)),
                 "mark_source": "synthetic_option_mark", "mark_type": "estimated mark, not an executable fill",
                 "mark_observed_at": _stamp(cutoff - timedelta(seconds=10)),
                 "mark_published_at": _stamp(cutoff - timedelta(seconds=5)),
                 "mark_retrieved_at": _stamp(cutoff - timedelta(seconds=2)),
                 "option_contract": {"right": "call", "strike": 500.0, "expiry": "2026-02-17", "dte_at_entry": 7},
                 "entry_time": _stamp(_BASE), "peak_mark_time": _stamp(datetime(2026, 2, 10, 14, 5, tzinfo=_ET)),
                 "historical_bid_ask": "unavailable", "greeks": "unavailable", "news": "unavailable"}
                if checkpoint_id == ORDER[0] else
                {"contracts": 2, "entry_premium_per_contract": 210.0,
                 "checkpoint_mark_per_contract": 280.0, "open_return_pct": 33.3,
                 "peak_open_return_pct": 75.0, "mark_time": _stamp(cutoff - timedelta(seconds=10)),
                 "mark_source": "synthetic_option_mark", "mark_type": "estimated mark, not an executable fill",
                 "mark_observed_at": _stamp(cutoff - timedelta(seconds=10)),
                 "mark_published_at": _stamp(cutoff - timedelta(seconds=5)),
                 "mark_retrieved_at": _stamp(cutoff - timedelta(seconds=2)),
                 "option_contract": {"right": "call", "strike": 500.0, "expiry": "2026-02-17", "dte_at_entry": 7},
                 "entry_time": _stamp(_BASE), "peak_mark_time": _stamp(datetime(2026, 2, 10, 14, 5, tzinfo=_ET)),
                 "historical_bid_ask": "unavailable", "greeks": "unavailable", "news": "unavailable"})
    original_plan = {
        "state": "captured_before_checkpoint",
        "captured_at": _stamp(_BASE),
        "text": "Take profit on one contract if the open gain gives back about one third of its peak; exit the rest below the underlying level 500 or reassess by 14:45 ET.",
        "source": "invented contemporaneous plan fixture",
    }
    packet = {"id": checkpoint_id, "input_cutoff": cutoff_stamp,
        "decision_received_at": None, "evidence_status": "synthetic fixture",
        "position": position, "original_plan": original_plan, "bars": bars,
        "chart_context": chart_context}
    return {"packet": packet, "evidence_sha256": _sha(packet)}


def _freeze_sealed() -> dict:
    first_cutoff, second_cutoff = _CUTOFFS[ORDER[0]], _CUTOFFS[ORDER[1]]
    # Only minute observations published by the next decision cutoff are eligible.
    first_continuation = []
    later_continuation = []
    for minute in range(95):
        bar = _minute_bar(minute)
        start = datetime.fromisoformat(bar["interval_start"])
        end = datetime.fromisoformat(bar["interval_end"])
        observed = datetime.fromisoformat(bar["observed_at"])
        published = datetime.fromisoformat(bar["published_at"])
        retrieved = datetime.fromisoformat(bar["retrieved_at"])
        if end <= start or observed < end or published < observed or retrieved < published:
            raise ValueError("synthetic continuation provenance order is invalid")
        if end > first_cutoff and end <= second_cutoff and observed <= second_cutoff and published <= second_cutoff:
            first_continuation.append(_bar_projection(bar))
        if end > second_cutoff and observed <= second_cutoff + timedelta(minutes=5) and published <= second_cutoff + timedelta(minutes=5):
            later_continuation.append(_bar_projection(bar))
    return {
        ORDER[0]: {
            "actual_action": {"decision": "held", "contracts": 2,
                "at": _stamp(datetime(2026, 2, 10, 14, 30, tzinfo=_ET)),
                "source": "synthetic_action_fixture", "execution_status": "invented historical action"},
            "continuation": first_continuation,
        },
        ORDER[1]: {
            "actual_action": {"decision": "exited", "contracts": 2,
                "fill": {"price_per_contract": 260.0, "filled_at": _stamp(datetime(2026, 2, 10, 15, 5, tzinfo=_ET)),
                         "source": "synthetic_fill_fixture", "execution_status": "invented historical fill"}},
            "continuation": later_continuation,
            "final_outcome": {"closed": True, "actual_synthetic_fills": [
                {"contracts": 2, "price_per_contract": 260.0, "filled_at": _stamp(datetime(2026, 2, 10, 15, 5, tzinfo=_ET))}],
                "pnl": {"value": 100.0, "unit": "USD", "status": "measured from invented synthetic fills"},
                "later_retrospective_rationale": {"status": "unavailable", "reason": "No contemporaneous later note exists in this fixture."}},
        },
    }


def _state(row: PracticeReplayAttempt) -> dict:
    data = json.loads(row.state_json)
    revealed_ids = data["revealed"]
    current = ORDER[len(revealed_ids)] if len(revealed_ids) < len(ORDER) else None
    phase = "complete" if current is None else "decision"
    revealed = []
    for cp in ORDER:
        if cp not in revealed_ids:
            break
        frozen_packet = data["checkpoints"][cp]["packet"]
        checkpoint = json.loads(_canonical(frozen_packet))
        checkpoint["decision_received_at"] = data["choices"][cp]["received_at"]
        revealed.append({"checkpoint_id": cp, "revealed_at": data.get("revealed_at", {}).get(cp),
                         "choice": data["choices"].get(cp),
                         "checkpoint": checkpoint, "original_plan": frozen_packet["original_plan"],
                         **data["sealed"][cp]})
    checkpoint = None
    if current:
        checkpoint = json.loads(_canonical(data["checkpoints"][current]["packet"]))
        choice = data["choices"].get(current)
        if choice:
            checkpoint["decision_received_at"] = choice["received_at"]
    return {"attempt_id": str(row.id), "operation_id": str(row.operation_id), "scenario_id": row.scenario_id,
            "repeated": data["repeated"], "phase": phase, "checkpoint": checkpoint,
            "choice": data["choices"].get(current) if current else None, "revealed": revealed}


def create_attempt(db: Session, operation_id: uuid.UUID) -> dict:
    existing = db.exec(select(PracticeReplayAttempt).where(PracticeReplayAttempt.operation_id == operation_id)).first()
    if existing:
        return _state(existing)
    prior = db.exec(select(PracticeReplayAttempt).order_by(PracticeReplayAttempt.created_at)).first()
    frozen = {cp: _freeze_checkpoint(cp) for cp in ORDER}
    row = PracticeReplayAttempt(operation_id=operation_id, scenario_id=SCENARIO_ID,
        state_json=_canonical({"choices": {}, "revealed": [], "repeated": prior is not None,
                               "checkpoints": frozen, "sealed": _freeze_sealed()}))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.exec(select(PracticeReplayAttempt).where(PracticeReplayAttempt.operation_id == operation_id)).first()
        if not existing:
            raise
        return _state(existing)
    db.refresh(row)
    return _state(row)


def get_attempt(db: Session, attempt_id: uuid.UUID) -> dict | None:
    row = db.get(PracticeReplayAttempt, attempt_id)
    return _state(row) if row else None


def _mutate(db: Session, row: PracticeReplayAttempt, data: dict) -> PracticeReplayAttempt:
    previous = row.revision
    result = db.execute(update(PracticeReplayAttempt).where(PracticeReplayAttempt.id == row.id,
        PracticeReplayAttempt.revision == previous).values(state_json=_canonical(data), revision=previous + 1,
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    if result.rowcount != 1:
        db.rollback()
        raise RuntimeError("replay changed concurrently; reload and retry")
    db.commit()
    db.refresh(row)
    return row


def save_choice(db: Session, attempt_id: uuid.UUID, checkpoint_id: str, decision: str, rationale: str | None) -> dict | None:
    if checkpoint_id not in ORDER:
        raise ValueError("unknown checkpoint")
    allowed = {"hold", "reduce", "exit"}
    if decision not in allowed:
        raise ValueError("decision is not valid for the current position")
    if rationale is not None and len(rationale) > 500:
        raise ValueError("rationale must be 500 characters or fewer")
    row = db.get(PracticeReplayAttempt, attempt_id)
    if not row:
        return None
    data = json.loads(row.state_json)
    index = len(data["revealed"])
    if index >= len(ORDER) or ORDER[index] != checkpoint_id:
        raise ValueError("checkpoint is not currently available")
    candidate = {"decision": decision, "rationale": rationale,
                 "received_at": datetime.now(timezone.utc).isoformat(),
                 "evidence_sha256": data["checkpoints"][checkpoint_id]["evidence_sha256"]}
    old = data["choices"].get(checkpoint_id)
    if old:
        if {k: old[k] for k in ("decision", "rationale")} != {"decision": decision, "rationale": rationale}:
            raise ValueError("saved choice is immutable")
        return _state(row)
    data["choices"][checkpoint_id] = candidate
    try:
        row = _mutate(db, row, data)
    except RuntimeError:
        latest = db.get(PracticeReplayAttempt, attempt_id)
        if latest:
            saved = json.loads(latest.state_json)["choices"].get(checkpoint_id)
            if saved and {k: saved[k] for k in ("decision", "rationale")} == {"decision": decision, "rationale": rationale}:
                return _state(latest)
        raise
    return _state(row)


def reveal(db: Session, attempt_id: uuid.UUID, checkpoint_id: str) -> dict | None:
    if checkpoint_id not in ORDER:
        raise ValueError("unknown checkpoint")
    row = db.get(PracticeReplayAttempt, attempt_id)
    if not row:
        return None
    data = json.loads(row.state_json)
    index = len(data["revealed"])
    if index >= len(ORDER) or ORDER[index] != checkpoint_id:
        if checkpoint_id in data["revealed"]:
            return _state(row)
        raise ValueError("checkpoint is not ready to reveal")
    if checkpoint_id not in data["choices"]:
        raise ValueError("save your choice before revealing")
    data["revealed"].append(checkpoint_id)
    data["revealed_at"] = {**data.get("revealed_at", {}), checkpoint_id: datetime.now(timezone.utc).isoformat()}
    try:
        row = _mutate(db, row, data)
    except RuntimeError:
        latest = db.get(PracticeReplayAttempt, attempt_id)
        if latest and checkpoint_id in json.loads(latest.state_json)["revealed"]:
            return _state(latest)
        raise
    return _state(row)


def copilot_context(db: Session, attempt_id: uuid.UUID) -> dict | None:
    """Return only the exact neutral active packet for a future same-checkpoint adapter."""
    state = get_attempt(db, attempt_id)
    if not state or state["phase"] != "decision" or not state["checkpoint"]:
        return None
    cp = state["checkpoint"]
    # The owner choice and receipt clock are excluded: an independent adapter must
    # receive only the same frozen decision packet, even after the owner commits.
    cp["decision_received_at"] = None
    return {"checkpoint_id": cp["id"], "input_cutoff": cp["input_cutoff"],
            "evidence_sha256": json.loads(db.get(PracticeReplayAttempt, attempt_id).state_json)
                ["checkpoints"][cp["id"]]["evidence_sha256"],
            "packet": cp}
