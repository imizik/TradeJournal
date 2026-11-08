"""The answer scorecard: how the copilot's answers went over the last days (docs/copilot-lab.md § The answer scorecard).

Two reads, joined in Python: ``copilot_turn`` rows (what each turn was, what it cost, how long the owner waited, whether
it failed) and the owner's saved conversations (each answer's Helped / Didn't, whether the next message pushed back or
followed up). An answer meets its turn through the ``turn_id`` the browser saved in its metrics. Counts and medians only:
nothing here changes a prompt, a model or a budget, and no answer text leaves the database.
"""
from __future__ import annotations

import json
import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlmodel import Session, col, select

from app.models import CopilotInvestigation, CopilotTurn

log = logging.getLogger(__name__)

MAX_INVESTIGATIONS = 500
MIN_RATED = 3  # a Helped rate under this many ratings is null, not a number
TOP = 5
PUSHBACK = "push back on"
TITLE_KINDS = (("Morning brief", "prep"), ("Week review", "week_review"), ("Your week", "week_review"))
TOOL_BUCKETS = ("none", "1", "2-3", "4+")


def _section(out: dict, db: Session, name: str, build: Callable[[], Any]) -> None:
    """One part of the card; a failure marks that part unavailable and leaves the others (Postgres refuses every later
    statement in an aborted transaction, so the session is rolled back first)."""
    try:
        out[name] = build()
    except Exception as exc:  # noqa: BLE001 - one unreadable part must not take the card down
        db.rollback()
        log.warning("answer scorecard %s unavailable: %s", name, type(exc).__name__)
        out[name] = {"state": "unavailable"}


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(math.ceil(q * len(ordered))) - 1))]


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _ny_day(stamp: datetime) -> str:
    from app.engine.chart_math import ET
    from datetime import UTC
    return stamp.replace(tzinfo=UTC).astimezone(ET).date().isoformat()


def _tool_bucket(n: int) -> str:
    return "none" if n == 0 else "1" if n == 1 else "2-3" if n <= 3 else "4+"


def _tools(turn: CopilotTurn) -> list:
    """The turn's tool names; a malformed value reads as none rather than failing the whole card."""
    try:
        names = json.loads(turn.tool_names or "[]")
    except ValueError:
        return []
    return names if isinstance(names, list) else []


def _kind_from_title(title: str | None) -> str | None:
    for prefix, kind in TITLE_KINDS:
        if (title or "").startswith(prefix):
            return kind
    return None


def _answers(db: Session, since: datetime, turns: dict[str, CopilotTurn]) -> list[dict]:
    """Every saved answer in the window: its rating, kind, source, model, tools, what the owner did next, and its turn;
    with its transcript ``index``, the ``question`` before it and when it was asked (``at``, naive UTC) for the desk's
    Rate yesterday card."""
    rows = db.exec(select(CopilotInvestigation.id, CopilotInvestigation.title, CopilotInvestigation.created_at, CopilotInvestigation.transcript_json)
                   .where(CopilotInvestigation.source == "copilot", col(CopilotInvestigation.updated_at) >= since)
                   .order_by(col(CopilotInvestigation.updated_at).desc()).limit(MAX_INVESTIGATIONS)).all()
    answers = []
    for inv_id, title, created_at, transcript_json in rows:
        try:
            transcript = json.loads(transcript_json or "[]")
        except ValueError:
            continue
        for i, message in enumerate(transcript):
            if message.get("role") != "assistant" or message.get("plan_context"):
                continue
            metrics = message.get("metrics") or {}
            turn = turns.get(str(metrics.get("turn_id") or ""))
            if turn is None and not (metrics.get("turn_id") is None and created_at is not None and created_at >= since):
                continue  # an older answer, or one whose turn is outside the window
            following = transcript[i + 1] if i + 1 < len(transcript) and transcript[i + 1].get("role") == "user" else None
            next_text = (following or {}).get("content") or ""
            asked = transcript[i - 1] if i and transcript[i - 1].get("role") == "user" else None
            tools = _tools(turn) if turn is not None else (metrics.get("tools") or [])
            answers.append({
                "investigation_id": str(inv_id), "title": title, "rating": message.get("rating"), "index": i,
                "question": (asked or {}).get("content"), "at": turn.started_at if turn is not None else created_at,
                "kind": (turn.kind if turn is not None and turn.kind else None) or _kind_from_title(title) or "ask",
                "source": (turn.source if turn is not None else None) or "desk",
                "model": (turn.model if turn is not None else None) or metrics.get("model"),
                "backend": (turn.backend if turn is not None else None) or metrics.get("backend"),
                "tools": [t for t in tools if t != "owner_context"], "turn": turn,
                "pushback": next_text.strip().lower().startswith(PUSHBACK), "follow_up": following is not None,
                "error": (turn.error if turn is not None else None) or metrics.get("error"),
            })
    return answers


def _ratings(answers: list[dict], key: Callable[[dict], str]) -> dict[str, dict]:
    groups: dict[str, dict] = defaultdict(lambda: {"answers": 0, "rated": 0, "helped": 0, "didnt": 0, "cost_usd": 0.0, "first_text_ms": []})
    for a in answers:
        g = groups[str(key(a))]
        g["answers"] += 1
        if a["rating"] in ("helped", "didnt"):
            g["rated"] += 1
            g[a["rating"]] += 1
        if a["turn"] is not None:
            g["cost_usd"] += float(a["turn"].cost_usd or 0)
            if a["turn"].first_text_ms is not None and not a["turn"].error:
                g["first_text_ms"].append(a["turn"].first_text_ms)
    return {name: {"answers": g["answers"], "rated": g["rated"], "helped": g["helped"], "didnt": g["didnt"],
                   "helped_rate": _rate(g["helped"], g["rated"]) if g["rated"] >= MIN_RATED else None,
                   "cost_usd": round(g["cost_usd"], 4), "first_text_ms_p50": _percentile(g["first_text_ms"], 0.5)}
            for name, g in sorted(groups.items())}


def _timings(turn: CopilotTurn) -> dict | None:
    """The turn's recorded split (``copilot_spend.timings_json``); None for an older row or a malformed value."""
    try:
        value = json.loads(turn.timings) if turn.timings else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _spread(values: list) -> dict:
    found = [v for v in values if isinstance(v, (int, float))]
    return {"p50": _percentile(found, 0.5), "p90": _percentile(found, 0.9)}


def timings(turns: list[CopilotTurn]) -> dict:
    """Where the owner's wait went, over turns that did not fail and recorded it. By kind: the owner context read, the
    model's time in a round that asked for tools, those tools' wall clock (they run side by side), and the model's time
    in the answer round (on Sonnet the answer after a tool result arrives whole, so this is most of its first text). By
    tool, every call: its time and the median of its split (``queue_ms`` waiting for a worker thread, ``feed_wait_ms``
    queued in the chart feed (the same read in flight, a provider slot), ``feed_ms`` in the chart feed's provider reads)."""
    timed = [(t, p) for t in turns if not t.error and (p := _timings(t)) is not None]
    by_kind: dict[str, dict] = {}
    for kind in sorted({t.kind or "unknown" for t, _ in timed}):
        mine = [p for t, p in timed if (t.kind or "unknown") == kind]
        rounds = [[r for r in p.get("rounds") or [] if isinstance(r, dict)] for p in mine]
        by_kind[kind] = {
            "turns": len(mine),
            "owner_context_ms": _spread([(p.get("owner_context") or {}).get("ms") for p in mine]),
            "tool_round_model_ms": _spread([r.get("model_ms") for rs in rounds for r in rs if "tools_ms" in r]),
            "tool_round_tools_ms": _spread([r.get("tools_ms") for rs in rounds for r in rs]),
            "answer_round_model_ms": _spread([rs[-1].get("model_ms") for rs in rounds if rs and "tools_ms" not in rs[-1]]),
        }
    calls: dict[str, list[dict]] = defaultdict(list)
    for _, p in timed:
        for call in p.get("tools") or []:
            if isinstance(call, dict) and call.get("name"):
                calls[str(call["name"])].append(call)
    by_tool = {name: {"calls": len(rows), "errors": sum(r.get("status") == "error" for r in rows), "ms": _spread([r.get("ms") for r in rows]),
                      **{f"{k}_p50": _spread([r.get(k) for r in rows])["p50"] for k in ("queue_ms", "feed_wait_ms", "feed_ms")}}
               for name, rows in sorted(calls.items())}
    return {"turns": len(timed), "by_kind": by_kind, "by_tool": by_tool}


def answer_scorecard(db: Session, now: datetime, days: int = 7) -> dict:
    """The card for the last ``days`` New York days ending now (``now`` is naive UTC, as the rows are stored)."""
    since = now - timedelta(days=days)
    out: dict[str, Any] = {"state": "ok", "window": {"days": days, "since": since.isoformat(timespec="minutes"),
                                                       "until": now.isoformat(timespec="minutes")}}
    turns_list: list[CopilotTurn] = []

    def read_turns():
        nonlocal turns_list
        turns_list = [t for t in db.exec(select(CopilotTurn).where(col(CopilotTurn.started_at) >= since)).all() if t.backend != "fake"]
        db.expunge_all()  # plain objects from here on: a later section's rollback must not make each row re-read itself
        return {"total": len(turns_list), "by_kind": dict(sorted(Counter(t.kind or "unknown" for t in turns_list).items())),
                "by_source": dict(sorted(Counter(t.source or "unknown" for t in turns_list).items()))}

    _section(out, db, "turns", read_turns)
    turns = {str(t.id): t for t in turns_list}
    answers: list[dict] = []

    def read_answers():
        nonlocal answers
        answers = _answers(db, since, turns)
        rated = [a for a in answers if a["rating"] in ("helped", "didnt")]
        helped = sum(a["rating"] == "helped" for a in rated)
        return {"total": len(answers), "rated": len(rated), "helped": helped, "didnt": len(rated) - helped,
                "helped_rate": _rate(helped, len(rated)) if len(rated) >= MIN_RATED else None,
                "pushback": sum(a["pushback"] for a in answers), "pushback_rate": _rate(sum(a["pushback"] for a in answers), len(answers)),
                "follow_ups": sum(a["follow_up"] for a in answers), "follow_up_rate": _rate(sum(a["follow_up"] for a in answers), len(answers)),
                "failed": sum(1 for a in answers if a["error"])}

    _section(out, db, "answers", read_answers)
    _section(out, db, "by_kind", lambda: _ratings(answers, lambda a: a["kind"]))
    _section(out, db, "by_source", lambda: _ratings(answers, lambda a: a["source"]))
    _section(out, db, "by_model", lambda: _ratings(answers, lambda a: a["model"] or "unknown"))
    _section(out, db, "by_backend", lambda: _ratings(answers, lambda a: a["backend"] or "unknown"))
    _section(out, db, "by_tools", lambda: _ratings(answers, lambda a: _tool_bucket(len(a["tools"]))))

    def tool_mixes():
        mixes = Counter(" + ".join(sorted(set(a["tools"]))) or "none" for a in answers)
        return [{"tools": mix, "answers": n} for mix, n in mixes.most_common(TOP)]

    _section(out, db, "top_tool_mixes", tool_mixes)

    def latency():
        by_kind: dict[str, dict] = {}
        for kind in sorted({t.kind or "unknown" for t in turns_list}):
            ok = [t for t in turns_list if (t.kind or "unknown") == kind and not t.error]
            first = [t.first_text_ms for t in ok if t.first_text_ms is not None]
            total = [t.total_ms for t in ok if t.total_ms is not None]
            silence = [t.max_silence_ms for t in ok if t.max_silence_ms is not None]
            by_kind[kind] = {"turns": len(ok), "first_text_ms": {"p50": _percentile(first, 0.5), "p90": _percentile(first, 0.9)},
                             "total_ms": {"p50": _percentile(total, 0.5), "p90": _percentile(total, 0.9)},
                             "max_silence_ms_p50": _percentile(silence, 0.5)}
        return by_kind

    _section(out, db, "latency", latency)
    _section(out, db, "timings", lambda: timings(turns_list))
    _section(out, db, "failed", lambda: dict(sorted(Counter(t.error for t in turns_list if t.error).items())))

    def spend():
        days_: dict[tuple[str, str, str], dict] = defaultdict(lambda: {"usd": 0.0, "turns": 0})
        for t in turns_list:
            key = (_ny_day(t.started_at), t.kind or "unknown", t.billing)
            days_[key]["usd"] += float(t.cost_usd or 0)
            days_[key]["turns"] += 1
        return [{"day": d, "kind": k, "billing": b, "usd": round(v["usd"], 4), "turns": v["turns"]}
                for (d, k, b), v in sorted(days_.items())]

    _section(out, db, "spend_by_day", spend)

    def cost():
        by_turn = [float(t.cost_usd or 0) for t in turns_list]
        threads: dict[str, dict] = defaultdict(lambda: {"usd": 0.0, "turns": 0, "title": None})
        for a in answers:
            if a["turn"] is not None:
                th = threads[a["investigation_id"]]
                th["usd"] += float(a["turn"].cost_usd or 0)
                th["turns"] += 1
                th["title"] = a["title"]
        top = sorted(threads.items(), key=lambda kv: -kv[1]["usd"])[:TOP]
        api = [t for t in turns_list if t.billing == "api"]
        read = sum(t.cache_read_input_tokens or 0 for t in api)
        inputs = sum(t.input_tokens or 0 for t in api) + read
        return {"total_usd": round(sum(by_turn), 4), "per_turn_usd": round(sum(by_turn) / len(by_turn), 4) if by_turn else None,
                "top_threads": [{"investigation_id": k, "title": (v["title"] or "")[:80], "usd": round(v["usd"], 4), "turns": v["turns"]} for k, v in top],
                "cache": {"read_tokens": read, "input_tokens": inputs, "read_share": _rate(read, inputs)}}

    _section(out, db, "cost", cost)
    return out
