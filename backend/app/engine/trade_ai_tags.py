"""Model-written review tags on closed trades (``TradeAiTag``): setup, mistakes and whether the trade broke the cut rule.

Read-only here. A tag is anchored in its trade's first entry fill (account and ``raw_email_id``), so it follows the trade
through a rebuild. ``upsert`` is only for the one-off loader script; nothing in the app writes tags.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.models import Fill, TradeAiTag, TradeFill


def _row(tag: TradeAiTag) -> dict:
    return {"setup": tag.setup, "mistakes": json.loads(tag.mistakes_json or "[]"), "primary_mistake": tag.primary_mistake,
            "broke_cut_rule": tag.broke_cut_rule, "rule_broken_computed": tag.rule_broken_computed, "grade": tag.grade,
            "confidence": tag.confidence, "rationale": tag.rationale, "model": tag.model}


def for_trades(db: Session, trade_ids: list[uuid.UUID]) -> dict[str, dict]:
    """Each tagged trade's tag, keyed by trade id string. Two queries for any number of trades."""
    if not trade_ids:
        return {}
    keys = db.exec(select(TradeFill.trade_id, Fill.raw_email_id, Fill.account_id)
                   .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(trade_ids))).all()
    trade_of = {(raw, account): trade_id for trade_id, raw, account in keys if raw}
    if not trade_of:
        return {}
    out: dict[str, dict] = {}
    for tag in db.exec(select(TradeAiTag).where(TradeAiTag.source_key.in_({raw for raw, _ in trade_of}))).all():
        trade_id = trade_of.get((tag.source_key, tag.account_id))
        if trade_id is not None:
            out[str(trade_id)] = _row(tag)
    return out


def upsert(db: Session, rows: list[dict], *, model: str, batch_id: str | None) -> tuple[int, int]:
    """Insert or replace tags by anchor. Each row: account_id, source_key, trade_id, tag (the model's JSON), facts."""
    existing = {(t.account_id, t.source_key): t for t in db.exec(select(TradeAiTag)).all()}
    added = updated = 0
    for r in rows:
        account, key, tag, facts = uuid.UUID(r["account_id"]), r["source_key"], r["tag"], r.get("facts") or {}
        row = existing.get((account, key))
        if row is None:
            row = TradeAiTag(account_id=account, source_key=key, setup="unclear", model=model)
            existing[(account, key)] = row  # a repeated anchor later in the same load updates this row
            added += 1
        else:
            updated += 1
        row.trade_id_at_tagging = uuid.UUID(r["trade_id"]) if r.get("trade_id") else None
        row.setup = tag["setup"]
        row.mistakes_json = json.dumps(tag.get("mistakes") or [])
        row.primary_mistake = tag.get("primary_mistake") or "none"
        row.broke_cut_rule = bool(tag.get("broke_cut_rule"))
        row.rule_broken_computed = bool(facts.get("rule_broken_computed"))
        row.grade, row.confidence, row.rationale = tag.get("grade"), tag.get("confidence"), tag.get("rationale")
        row.facts_json = json.dumps(facts) if facts else None
        row.model, row.batch_id, row.tagged_at = model, batch_id, datetime.utcnow()
        db.add(row)
    db.commit()
    return added, updated
