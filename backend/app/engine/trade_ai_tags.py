"""Model-written review tags on closed trades (``TradeAiTag``): setup, mistakes and whether the trade broke the cut rule.

Read-only here. A tag is anchored in its trade's first entry fill (account and ``raw_email_id``), so it follows the trade
through a rebuild. ``upsert`` is only for the one-off loader script; nothing in the app writes tags.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Iterable, Optional

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


# --- The tag record for the check service: pure, over published rows (no database) ---------------------------------
#
# The publisher maps the narrow tag view (deploy/check_scope.py, ``pretrade_tag_source``) to ``tag_rows``; the check
# service joins them to the history rows (``pretrade_check.feature_row``) and the add record (``add_check``) by the
# hashed first-entry fill key. Tags were written after the fact with each trade's outcome visible, so they are the
# owner's history by setup, never a live classifier and never a verdict.

TAG_ROW_KEYS = frozenset({"source_fill_key", "setup", "primary_mistake", "mistakes", "broke_cut_rule",
                          "rule_broken_computed", "grade"})
MIN_TAGGED = 8  # below this a setup is "not enough history" (pretrade_check.MIN_TRADES)
EXTENDED_PCT = 2.5  # beyond VWAP in the trade's direction: the scalper's "getting extended" line
HINDSIGHT = ("Opus tagged each closed trade after the fact with its outcome visible: this is your record by "
             "setup, not a read of this entry, and it never changes the verdict.")
NO_SETUP = ("no_clear_setup", "unclear", "none")


def tag_rows(records: Iterable[dict]) -> list[dict]:
    """Narrow-view rows to the published tag rows, one per hashed first-entry fill key."""
    rows = {}
    for item in records:
        item = dict(item)
        mistakes = json.loads(item["mistakes_json"] or "[]")
        rows[item["source_fill_key"]] = {
            "source_fill_key": item["source_fill_key"], "setup": str(item["setup"]),
            "primary_mistake": item["primary_mistake"] or "none",
            "mistakes": [str(m) for m in mistakes] if isinstance(mistakes, list) else [],
            "broke_cut_rule": bool(item["broke_cut_rule"]), "rule_broken_computed": bool(item["rule_broken_computed"]),
            "grade": item["grade"]}
    return [rows[key] for key in sorted(rows)]


def _norm(value: Optional[str]) -> str:
    return "_".join(str(value or "").lower().replace("-", " ").split())


def _is_chase(tag: dict) -> bool:
    return "chase" in tag["setup"] or any("chase" in m for m in (tag["primary_mistake"], *tag["mistakes"]))


def _no_setup(tag: dict) -> bool:
    return tag["setup"] in NO_SETUP or "no_clear" in tag["setup"]


def _record(trades: list[tuple[dict, dict]]) -> dict:
    """Count, wins and dollars of (history row, tag) pairs; ``enough`` at MIN_TAGGED trades."""
    pnl = [row["realized_pnl"] for row, _ in trades if row["realized_pnl"] is not None]
    out = {"trades": len(trades), "enough": len(trades) >= MIN_TAGGED,
           "total_pnl": round(sum(pnl), 2), "wins": sum(1 for v in pnl if v > 0),
           "broke_cut_rule": sum(1 for _, tag in trades if tag["rule_broken_computed"])}
    out["win_rate"] = round(out["wins"] / len(pnl), 3) if pnl else None
    return out


def _dollars(value: float) -> str:
    return f"-${-value:,.0f}" if value < 0 else f"+${value:,.0f}"


def _said(name: str, record: dict) -> str:
    verb = "lost" if record["total_pnl"] < 0 else "made"
    return (f"{record['trades']} trades tagged {name} {verb} ${abs(record['total_pnl']):,.0f} "
            f"({record['wins']} won)")


def tagged_history(rows: Iterable[dict], tags: Optional[Iterable[dict]], cutoff_ny: datetime) -> list[tuple[dict, dict]]:
    """(history row, tag) for each tagged trade closed before the cutoff (naive New York wall time)."""
    by_key = {tag["source_fill_key"]: tag for tag in tags or ()}
    return [(row, by_key[row["source_fill_key"]]) for row in rows
            if row["source_fill_key"] in by_key and datetime.fromisoformat(row["closed_at"]) < cutoff_ny]


def setups(tagged: list[tuple[dict, dict]]) -> list[dict]:
    """Every setup's record, worst dollars first."""
    groups: dict[str, list] = {}
    for row, tag in tagged:
        groups.setdefault(tag["setup"], []).append((row, tag))
    return sorted(({"setup": name, **_record(items)} for name, items in groups.items()),
                  key=lambda item: (item["total_pnl"], item["setup"]))


def match_setup(stated: Optional[str], known: Iterable[str]) -> Optional[str]:
    """The tag name the owner's stated setup means: exact, else the one known name containing it."""
    stated, known = _norm(stated), sorted(set(known))
    if not stated:
        return None
    if stated in known:
        return stated
    hits = [name for name in known if stated in name]
    return hits[0] if len(hits) == 1 else None


def pretrade_setup_record(idea: dict, analysis: dict, rows: Iterable[dict], tags: Optional[Iterable[dict]],
                          cutoff_ny: datetime, similar_keys: Iterable[str], stated: Optional[str] = None) -> dict:
    """His tagged record for the entry being checked: the setup he names (or the no-setup record when he names
    none), what the live tape looks like (extended past VWAP like a chase, or a fresh VWAP reclaim) and how his
    similar entries were tagged. Context beside the rules verdict; it never changes it."""
    if tags is None:
        return {"available": False, "lines": [], "note": "trade tags are not published yet; nothing was invented"}
    tagged = tagged_history(rows, tags, cutoff_ny)
    table = setups(tagged)
    lines, reads = [], []
    name = match_setup(stated, (item["setup"] for item in table))
    stated_record = None
    if stated:
        if name is None:
            lines.append(f"No tagged history matches the setup \"{stated}\"; known setups are listed in setups.")
        else:
            stated_record = next(item for item in table if item["setup"] == name)
            lines.append(f"You called this {name}: your {_said(name, stated_record)}.")
    else:
        none = [(row, tag) for row, tag in tagged if _no_setup(tag)]
        if none:
            record = _record(none)
            reads.append({"read": "no_setup_named", **record})
            lines.append(f"No setup named. Your {_said('no clear setup', record)}; name the setup or skip it.")
    intraday = (analysis.get("data") or {}).get("intraday") or {}
    long = idea["side"] != "short"
    vs_vwap, price, vwap, prev = (intraday.get(k) for k in ("price_vs_vwap_pct", "price", "vwap", "prev_bar_close"))
    if vs_vwap is not None and (vs_vwap if long else -vs_vwap) >= EXTENDED_PCT:
        chased = [(row, tag) for row, tag in tagged if _is_chase(tag)]
        record = _record(chased)
        reads.append({"read": "extended_like_a_chase", "beyond_vwap_pct": round(abs(vs_vwap), 2), **record})
        if chased:
            lines.append(f"Price is {abs(vs_vwap):.1f}% past VWAP, the shape of a chase: your "
                         f"{_said('as a chase', record)}.")
    if None not in (price, vwap, prev) and (prev < vwap < price if long else prev > vwap > price):
        reclaims = [(row, tag) for row, tag in tagged if "reclaim" in tag["setup"]]
        record = _record(reclaims)
        reads.append({"read": "fresh_vwap_reclaim", **record})
        if reclaims:
            lines.append(f"This is a fresh VWAP {'reclaim' if long else 'loss'}: your {_said('VWAP reclaim', record)}.")
    similar_keys = set(similar_keys)
    similar = setups([(row, tag) for row, tag in tagged if row["source_fill_key"] in similar_keys])
    if similar:
        top = ", ".join(f"{item['setup']} {item['trades']} ({_dollars(item['total_pnl'])})"
                        for item in sorted(similar, key=lambda item: (-item["trades"], item["setup"]))[:3])
        lines.append(f"Your similar entries were tagged: {top}.")
    return {"available": True, "tagged_trades": len(tagged), "stated": stated, "matched_setup": name,
            "stated_record": stated_record, "reads": reads, "similar": similar, "setups": table,
            "headline": lines[0] if lines else None, "lines": lines, "note": HINDSIGHT}


def add_setup_record(answer: dict, add_rows: Optional[Iterable[dict]], rows: Iterable[dict],
                     tags: Optional[Iterable[dict]], cutoff_ny: datetime, stated: Optional[str] = None) -> dict:
    """His tagged record for an add (``add_check.add_view``'s answer): the setup he names, and how the positions
    where he added below cost in the same kind of spot were tagged (cut-rule breaks and setups)."""
    if tags is None:
        return {"available": False, "lines": [], "note": "trade tags are not published yet; nothing was invented"}
    by_key = {tag["source_fill_key"]: tag for tag in tags}
    tagged = tagged_history(rows, by_key.values(), cutoff_ny)
    table = setups(tagged)
    lines = []
    name = match_setup(stated, (item["setup"] for item in table))
    stated_record = stated_adds = None
    prior = [row for row in add_rows or () if datetime.fromisoformat(row["closed_at"]) < cutoff_ny
             and row.get("source_fill_key") in by_key]
    if stated and name is None:
        lines.append(f"No tagged history matches the setup \"{stated}\"; known setups are listed in setups.")
    elif name:
        stated_record = next(item for item in table if item["setup"] == name)
        lines.append(f"Your {_said(name, stated_record)}.")
        mine = [row for row in prior if by_key[row["source_fill_key"]]["setup"] == name]
        if mine:
            added = sum(add["pnl"] for row in mine for add in row["adds"])
            stated_adds = {"positions": len(mine), "ended_green": sum(1 for row in mine if row["realized_pnl"] > 0),
                           "position_pnl": round(sum(row["realized_pnl"] for row in mine), 2),
                           "added_contracts_pnl": round(added, 2)}
            lines.append(f"On {name} trades you added below cost {len(mine)} times: the added contracts made "
                         f"{_dollars(added)}, the positions {_dollars(stated_adds['position_pnl'])}.")
    spot = None
    now = answer.get("now")
    if now and now["pct_vs_cost"] < 0:
        short = now["days_to_expiration"] <= 3
        same = [row for row in prior if any((add["dte"] <= 3) == short for add in row["adds"])]
        if same:
            broke = [row for row in same if by_key[row["source_fill_key"]]["rule_broken_computed"]]
            names = setups([({"realized_pnl": row["realized_pnl"]}, by_key[row["source_fill_key"]]) for row in same])
            spot = {"positions": len(same), "broke_cut_rule": len(broke),
                    "broke_cut_rule_pnl": round(sum(row["realized_pnl"] for row in broke), 2),
                    "setups": sorted(names, key=lambda item: (-item["trades"], item["setup"]))[:3]}
            line = (f"Of {len(same)} tagged positions where you added below cost "
                    f"{'short-dated' if short else 'longer-dated'}, {len(broke)} broke the cut rule")
            lines.append(line + (f" ({_dollars(spot['broke_cut_rule_pnl'])})." if broke else "."))
    return {"available": True, "stated": stated, "matched_setup": name, "stated_record": stated_record,
            "stated_adds": stated_adds, "same_spot": spot, "setups": table,
            "headline": lines[0] if lines else None, "lines": lines, "note": HINDSIGHT}
