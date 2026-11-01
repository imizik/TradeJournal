"""Offline eval for the copilot (docs/copilot-lab.md § Measuring the copilot).

    python -m scripts.copilot_eval run --model fake                      # free: the scripted model on fixture evidence
    python -m scripts.copilot_eval run --model claude-sonnet-5-5 --max-cost-usd 1 --out backend/data/copilot_eval/runs/sonnet
    python -m scripts.copilot_eval grade --run <dir> [--judge --max-cost-usd 1]
    python -m scripts.copilot_eval report --run <dir> [--run <other dir>]
    python -m scripts.copilot_eval export --out backend/data/copilot_eval/owner-cases.jsonl

``run`` plays each case through ``copilot.run_turn`` with the scripted model or the Anthropic API, on fixture or replay
evidence, and records the answer, every tool result the turn read, the metrics and the cost. Answers are cached by
case, model, effort, evidence, system prompt and tool schemas, so a re-run is free and a prompt change is never read
from stale answers. ``grade`` runs the deterministic checks in ``app.ai.copilot_graders`` and, on request, an Opus
rubric judge. ``report`` tabulates runs and compares two of them case by case. ``export`` turns the owner's real saved
questions into a case file with ids stripped.

Nothing here writes ``copilot_turn`` or touches a provider; a paid run needs ``--max-cost-usd`` and stops at it.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.ai import copilot, copilot_graders, copilot_tools
from app.ai.copilot_fixture import FixtureEvidence

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_CASES = BACKEND / "tests" / "fixtures" / "copilot_eval" / "starter.jsonl"
DATA_DIR = BACKEND / "data" / "copilot_eval"  # gitignored
RUBRIC = Path(__file__).with_name("copilot_eval_rubric.md")
FIXTURE_NOW = datetime(2026, 10, 23, 11, 12)  # the fixture scenario's moment, New York
JUDGE_MODEL = "claude-opus-5-5"
MAX_JUDGE_EVIDENCE_CHARS = 12_000
BOOTSTRAP_DRAWS, BOOTSTRAP_SEED, CI_LEVEL = 2000, 20261031, 0.95
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SKIP_TITLES = ("Morning brief", "Week review", "Your week")
JUDGE_SCHEMA = {"type": "object", "additionalProperties": False,
                "properties": {**{k: {"type": "integer", "minimum": 1, "maximum": 5} for k in
                                  ("decision_relevance", "uses_position_and_plan", "thesis_apart_from_position", "counter_case",
                                   "changes_view", "length_fit")}, "notes": {"type": "string"}},
                "required": ["decision_relevance", "uses_position_and_plan", "thesis_apart_from_position", "counter_case",
                             "changes_view", "length_fit", "notes"]}
JUDGE_ITEMS = [k for k in JUDGE_SCHEMA["required"] if k != "notes"]


def _err(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


# --------------------------------------------------------------------------- cases and records

def load_cases(path: Path) -> list[dict]:
    cases = []
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case, dict) or not case.get("id") or not case.get("question"):
            raise ValueError(f"{path}:{line_no}: a case needs an id and a question")
        case.setdefault("expects", {})
        cases.append(case)
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError(f"{path}: case ids repeat")
    return cases


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, default=str) + "\n" for row in rows))


class RecordingEvidence:
    """Wraps an evidence object and keeps every read the turn makes (name, arguments, result), including the owner
    context, so the graders can check the answer's figures against what the model was actually shown."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[dict] = []

    @property
    def label(self) -> str:
        return getattr(self._inner, "label", "")

    def __getattr__(self, name: str):
        value = getattr(self._inner, name)
        if not callable(value):
            return value

        def wrapped(*args, **kwargs):
            call = {"name": name, "args": kwargs if kwargs else list(args)}
            try:
                result = value(*args, **kwargs)
            except Exception as exc:
                self.calls.append({**call, "error": type(exc).__name__})
                raise
            self.calls.append({**call, "result": result})
            return result

        return wrapped


def cache_key(case: dict, model: str, effort: str, backend: str, evidence: str, replay_at: str | None) -> str:
    """The same case on the same prompt, tools, model and evidence gives the same answer; anything else re-runs."""
    payload = {"case": case, "model": model, "effort": effort, "backend": backend, "evidence": evidence, "replay_at": replay_at,
               "system_prompt": copilot.SYSTEM_PROMPT, "tools": copilot_tools.TOOLS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def settings_for(model: str, effort: str, evidence: str, turn_budget_usd: float) -> copilot.Settings:
    backend = "fake" if model == "fake" else "anthropic"
    return copilot.Settings(enabled=True, backend=backend, evidence=evidence, model=copilot.DEFAULT_MODEL if backend == "fake" else model,
                            effort=effort, fallbacks=False, key_configured=bool(os.environ.get("ANTHROPIC_API_KEY")),
                            turn_budget_usd=turn_budget_usd)


def case_moment(case: dict) -> datetime:
    at = case.get("at")
    return datetime.fromisoformat(at) if at else FIXTURE_NOW


async def run_case(case: dict, history: list[dict], cfg: copilot.Settings, adapter, evidence, now: datetime,
                   carry_id: str | None) -> dict:
    """One turn, as the desk would run it, recorded in full."""
    recording = RecordingEvidence(evidence)
    text, tools_seen, proposals, error, metrics, out_carry = [], [], [], None, {}, None
    async for event in copilot.run_turn(history, case.get("symbol"), cfg, adapter, recording, now, carry_id=carry_id):
        kind = event.get("type")
        if kind == "text":
            text.append(event["delta"])
        elif kind == "tool" and event.get("status") in ("ok", "error"):
            tools_seen.append({"name": event.get("name"), "status": event.get("status"), "ms": event.get("ms")})
        elif kind == "proposal":
            proposals.append(event.get("kind"))
        elif kind == "error" and error is None:
            error = event.get("code")
        elif kind == "done":
            metrics, out_carry = event.get("metrics") or {}, event.get("carry_id")
    return {"id": case["id"], "workflow": case.get("workflow"), "symbol": case.get("symbol"), "question": case["question"],
            "history": history[:-1], "at": now.isoformat(timespec="minutes"), "model": metrics.get("model") or cfg.model,
            "effort": cfg.effort, "backend": cfg.backend, "evidence": cfg.evidence, "text": "".join(text),
            "tools": recording.calls, "tool_events": tools_seen, "proposals": proposals, "error": error, "metrics": metrics,
            "cost_usd": float(metrics.get("cost_usd") or 0.0), "cached": False, "carry_id": out_carry}


async def run_all(cases: list[dict], args, cfg_for, adapter, evidence_for, replay_at: str | None) -> tuple[list[dict], float]:
    cache_dir = DATA_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict] = {}
    spent = 0.0
    cap = args.max_cost_usd
    for case in cases:
        backend = "fake" if args.model == "fake" else "anthropic"
        key = cache_dir / f"{cache_key(case, args.model, args.effort, backend, args.evidence, replay_at)}.json"
        parent = records.get(case["carry_from"]) if case.get("carry_from") else None
        if case.get("carry_from") and parent is None:
            print(f"{case['id']}: carry_from {case['carry_from']} must come earlier in the case file", file=sys.stderr)
        history = [{"role": "user", "content": case["question"]}]
        carry_id = None
        carry_state = None
        if parent is not None and not parent.get("skipped"):
            history = [{"role": "user", "content": parent["question"]}, {"role": "assistant", "content": parent["text"]}, *history]
            carry_id = parent.get("carry_id") if not parent.get("cached") else None
            carry_state = "ok" if carry_id else "unavailable"
        if key.is_file() and not args.no_cache:
            record = json.loads(key.read_text())
            record.update(cached=True, carry_id=None, carry=carry_state if carry_state else record.get("carry"))
            records[case["id"]] = record
            continue
        if backend == "anthropic" and cap is not None and spent >= cap:
            records[case["id"]] = {"id": case["id"], "workflow": case.get("workflow"), "symbol": case.get("symbol"),
                                   "question": case["question"], "skipped": "budget", "cost_usd": 0.0, "cached": False}
            continue
        remaining = (cap - spent) if cap is not None else 0.25
        cfg = cfg_for(min(0.25, max(remaining, 0.01)))
        record = await run_case(case, history, cfg, adapter, evidence_for(case), case_moment(case), carry_id)
        record["carry"] = carry_state
        spent += record["cost_usd"]
        if backend == "anthropic" or not args.no_cache:
            key.write_text(json.dumps(record, default=str))
        records[case["id"]] = record
        print(f"{case['id']}: {record['error'] or 'ok'} · {len(record['tools'])} reads · {record['metrics'].get('total_ms')} ms · ${record['cost_usd']:.4f}")
    return list(records.values()), spent


def cmd_run(args) -> int:
    cases = load_cases(Path(args.cases))
    paid = args.model != "fake"
    if paid and args.max_cost_usd is None:
        return _err("A paid run needs --max-cost-usd; nothing was sent.")
    if paid and not os.environ.get("ANTHROPIC_API_KEY"):
        return _err("ANTHROPIC_API_KEY is not set; nothing was sent.")
    replay_at = None
    if args.evidence == "replay":
        from app.ai import copilot_replay
        from app.environment import describe
        if not describe().is_local:
            return _err("Replay runs only against a local database.")
        if not args.replay_store or not args.replay_at:
            return _err("Replay needs --replay-store and --replay-at.")
        replay_at = args.replay_at

        def evidence_for(case):
            return copilot_replay.ReplayEvidence(args.replay_store, copilot_replay.parse_at(case.get("at") or args.replay_at))
    else:
        def evidence_for(case):
            return FixtureEvidence()

    def cfg_for(turn_budget: float) -> copilot.Settings:
        return settings_for(args.model, args.effort, args.evidence, turn_budget)

    adapter = copilot.FakeAdapter(0) if not paid else copilot.AnthropicAdapter(cfg_for(0.25))
    out = Path(args.out) if args.out else DATA_DIR / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.model}-{args.effort}"
    started = datetime.now()
    try:
        records, spent = asyncio.run(run_all(cases, args, cfg_for, adapter, evidence_for, replay_at))
    finally:
        if hasattr(adapter, "aclose"):
            asyncio.run(adapter.aclose())
    write_jsonl(out / "records.jsonl", records)
    meta = {"model": args.model, "effort": args.effort, "backend": "fake" if not paid else "anthropic", "evidence": args.evidence,
            "replay_at": replay_at, "cases": str(Path(args.cases).resolve()), "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"), "count": len(records),
            "skipped": sum(1 for r in records if r.get("skipped")), "cached": sum(1 for r in records if r.get("cached")),
            "cost_usd": round(spent, 4), "prompt_sha": hashlib.sha256(copilot.SYSTEM_PROMPT.encode()).hexdigest()[:12],
            "tools_sha": hashlib.sha256(json.dumps(copilot_tools.TOOLS, sort_keys=True).encode()).hexdigest()[:12]}
    (out / "run.json").write_text(json.dumps(meta, indent=2))
    print(f"{len(records)} cases → {out} · ${spent:.4f} spent · {meta['cached']} cached · {meta['skipped']} skipped")
    return 0


# --------------------------------------------------------------------------- grade

def judge_one(record: dict, case: dict, rubric: str, model: str, client=None) -> dict:
    """The rubric judge: one structured answer from the API (``api_runner.ask``, PR #631). Raises ImportError before it."""
    from app.ai import api_runner
    owner = next((t.get("result") for t in record.get("tools") or [] if t.get("name") == "owner_context"), None)
    reads = [{"tool": t["name"], "args": t.get("args"), "result": t.get("result")} for t in record.get("tools") or []
             if t.get("name") != "owner_context"]
    evidence = json.dumps(reads, default=str)[:MAX_JUDGE_EVIDENCE_CHARS]
    message = (f"QUESTION:\n{record['question']}\n\nOWNER CONTEXT:\n{json.dumps(owner, default=str)[:4000]}\n\n"
               f"TOOL RESULTS THE COPILOT READ:\n{evidence}\n\nANSWER:\n{record.get('text') or ''}\n\n"
               f"Case notes: {json.dumps(case.get('expects') or {})}")
    answer = api_runner.ask(rubric, message, JUDGE_SCHEMA, model=model, client=client)
    scores = {k: int(answer.data[k]) for k in JUDGE_ITEMS}
    return {**scores, "total": sum(scores.values()), "notes": str(answer.data.get("notes", ""))[:300],
            "model": answer.model, "usd": answer.usd, "rubric_sha": hashlib.sha256(rubric.encode()).hexdigest()[:12]}


def cmd_grade(args) -> int:
    run_dir = Path(args.run)
    records = read_jsonl(run_dir / "records.jsonl")
    cases = {c["id"]: c for c in load_cases(Path(args.cases))}
    rubric = RUBRIC.read_text()
    if args.judge and args.max_cost_usd is None:
        return _err("The judge spends API credits; give --max-cost-usd.")
    if args.judge:
        try:
            from app.ai import api_runner  # noqa: F401  (the judge needs PR #631's runner)
        except ImportError:
            return _err("The rubric judge needs app.ai.api_runner (PR #631); run without --judge until it lands.")
    grades, spent = [], 0.0
    for record in records:
        case = cases.get(record["id"], {"id": record["id"], "expects": {}})
        checks = copilot_graders.grade(record, case)
        row = {"id": record["id"], "checks": [{"name": c.name, "state": c.state, "detail": c.detail} for c in checks],
               "summary": copilot_graders.summary(checks), "judge": None}
        if args.judge and not record.get("error") and not record.get("skipped"):
            if spent >= args.max_cost_usd:
                row["judge"] = {"skipped": "budget"}
            else:
                row["judge"] = judge_one(record, case, rubric, args.judge_model)
                spent += row["judge"]["usd"]
        grades.append(row)
        failed = [c.name for c in checks if c.passed is False]
        print(f"{record['id']}: {row['summary']['pass']} pass, {row['summary']['fail']} fail" + (f" ({', '.join(failed)})" if failed else ""))
    write_jsonl(run_dir / "grades.jsonl", grades)
    if args.judge:
        print(f"judge: ${spent:.4f}")
    return 0


# --------------------------------------------------------------------------- report

def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(math.ceil(q * len(ordered))) - 1)]


def case_bootstrap(per_case: dict[str, tuple[float, int]], draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED):
    """Ratio-of-sums mean and percentile CI, resampling cases with replacement. ``per_case`` maps a case id to
    (sum, count). Returns (mean, lo, hi), or (mean, None, None) with fewer than two cases. Copied from
    research/opening_lab/evaluate.py ``session_bootstrap``, keyed by case instead of session."""
    keys = sorted(k for k, (_, n) in per_case.items() if n)
    total = sum(per_case[k][1] for k in keys)
    if not total:
        return None, None, None
    mean = sum(per_case[k][0] for k in keys) / total
    if len(keys) < 2:
        return mean, None, None
    sums, counts = [per_case[k][0] for k in keys], [per_case[k][1] for k in keys]
    rng, idx, stats = random.Random(seed), range(len(keys)), []
    for _ in range(draws):
        pick = rng.choices(idx, k=len(keys))
        stats.append(sum(sums[i] for i in pick) / sum(counts[i] for i in pick))
    stats.sort()
    tail = (1 - CI_LEVEL) / 2
    return mean, stats[int(math.floor(tail * (draws - 1)))], stats[int(math.ceil((1 - tail) * (draws - 1)))]


def load_run(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "run.json").read_text()) if (run_dir / "run.json").is_file() else {}
    records = {r["id"]: r for r in read_jsonl(run_dir / "records.jsonl")}
    grades = {g["id"]: g for g in read_jsonl(run_dir / "grades.jsonl")} if (run_dir / "grades.jsonl").is_file() else {}
    return {"dir": str(run_dir), "meta": meta, "records": records, "grades": grades}


def summarize_run(run: dict) -> dict:
    records, grades = run["records"], run["grades"]
    done = [r for r in records.values() if not r.get("skipped") and not r.get("error")]
    checks: dict[str, list[bool]] = {}
    for g in grades.values():
        for c in g["checks"]:
            if c["state"] != "n/a":
                checks.setdefault(c["name"], []).append(c["state"] == "pass")
    judged = [g["judge"] for g in grades.values() if g.get("judge") and "total" in g["judge"]]
    first = [r["metrics"].get("first_text_ms") for r in done if r.get("metrics", {}).get("first_text_ms") is not None]
    total = [r["metrics"].get("total_ms") for r in done if r.get("metrics", {}).get("total_ms") is not None]
    return {"dir": run["dir"], "model": run["meta"].get("model"), "effort": run["meta"].get("effort"), "backend": run["meta"].get("backend"),
            "evidence": run["meta"].get("evidence"), "cases": len(records), "completed": len(done),
            "errors": sum(1 for r in records.values() if r.get("error")), "skipped": sum(1 for r in records.values() if r.get("skipped")),
            "checks": {name: {"pass_rate": round(sum(v) / len(v), 3), "n": len(v)} for name, v in sorted(checks.items())},
            "judge": {k: round(statistics.fmean(j[k] for j in judged), 2) for k in [*JUDGE_ITEMS, "total"]} if judged else None,
            "first_text_ms": {"p50": _percentile(first, 0.5), "p90": _percentile(first, 0.9)},
            "total_ms": {"p50": _percentile(total, 0.5), "p90": _percentile(total, 0.9)},
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in records.values()), 4),
            "cost_per_case_usd": round(sum(r.get("cost_usd") or 0 for r in records.values()) / max(len(records), 1), 4)}


def compare_runs(a: dict, b: dict) -> dict:
    """Per check, B minus A pass rate over the cases both runs graded, with a case-bootstrap interval; the same for the
    judge total when both runs were judged."""
    shared = sorted(set(a["grades"]) & set(b["grades"]))
    out: dict[str, Any] = {"shared_cases": len(shared), "checks": {}}
    names = {c["name"] for g in a["grades"].values() for c in g["checks"]}
    for name in sorted(names):
        per_case = {}
        for cid in shared:
            sa = next((c["state"] for c in a["grades"][cid]["checks"] if c["name"] == name), "n/a")
            sb = next((c["state"] for c in b["grades"][cid]["checks"] if c["name"] == name), "n/a")
            if "n/a" in (sa, sb):
                continue
            per_case[cid] = ((sb == "pass") - (sa == "pass"), 1)
        mean, lo, hi = case_bootstrap(per_case)
        out["checks"][name] = {"b_minus_a": None if mean is None else round(mean, 3), "lo": lo, "hi": hi, "n": len(per_case)}
    judged = {cid: (b["grades"][cid]["judge"]["total"] - a["grades"][cid]["judge"]["total"], 1) for cid in shared
              if (a["grades"][cid].get("judge") or {}).get("total") is not None and (b["grades"][cid].get("judge") or {}).get("total") is not None}
    mean, lo, hi = case_bootstrap(judged)
    out["judge_total_b_minus_a"] = {"mean": None if mean is None else round(mean, 2), "lo": lo, "hi": hi, "n": len(judged)}
    return out


def render(summaries: list[dict], comparison: dict | None) -> str:
    lines = []
    for s in summaries:
        lines.append(f"{s['dir']}: {s['model']} · effort {s['effort']} · {s['backend']} · {s['evidence']} · "
                     f"{s['completed']}/{s['cases']} completed ({s['errors']} errors, {s['skipped']} skipped) · "
                     f"${s['cost_usd']} total, ${s['cost_per_case_usd']} a case")
        lines.append(f"  first text p50 {s['first_text_ms']['p50']} ms, p90 {s['first_text_ms']['p90']} ms · "
                     f"total p50 {s['total_ms']['p50']} ms, p90 {s['total_ms']['p90']} ms")
        for name, c in s["checks"].items():
            lines.append(f"  {name:<20} {c['pass_rate']:.0%} of {c['n']}")
        if s["judge"]:
            lines.append("  judge " + ", ".join(f"{k} {v}" for k, v in s["judge"].items()))
    if comparison:
        lines.append(f"B minus A over {comparison['shared_cases']} shared cases (95% case-bootstrap):")
        for name, c in comparison["checks"].items():
            if c["b_minus_a"] is None:
                continue
            ci = f" [{c['lo']:+.3f}, {c['hi']:+.3f}]" if c["lo"] is not None else ""
            lines.append(f"  {name:<20} {c['b_minus_a']:+.3f}{ci} (n={c['n']})")
        j = comparison["judge_total_b_minus_a"]
        if j["mean"] is not None:
            ci = f" [{j['lo']:+.2f}, {j['hi']:+.2f}]" if j["lo"] is not None else ""
            lines.append(f"  judge total          {j['mean']:+.2f}{ci} (n={j['n']})")
    return "\n".join(lines)


def cmd_report(args) -> int:
    runs = [load_run(Path(p)) for p in args.run]
    summaries = [summarize_run(r) for r in runs]
    comparison = compare_runs(runs[0], runs[1]) if len(runs) == 2 else None
    text = render(summaries, comparison)
    print(text)
    out = Path(args.out) if args.out else Path(runs[-1]["dir"]) / "report.json"
    out.write_text(json.dumps({"runs": summaries, "comparison": comparison}, indent=2, default=str))
    return 0


# --------------------------------------------------------------------------- export

def _scrub(text: str) -> str:
    return UUID.sub("<id>", text or "")


def export_cases(since: datetime, out: Path, session=None) -> int:
    """The owner's real questions from saved copilot conversations as cases (ids replaced, briefs and week reviews left
    out). Never into the test fixtures; the owner decides what to keep."""
    from contextlib import nullcontext

    from sqlmodel import Session, col, select

    from app.ai.copilot_context import user_text
    from app.database import engine
    from app.models import CopilotInvestigation
    if "tests/fixtures" in str(out.resolve()).replace(os.sep, "/"):
        raise ValueError("export never writes into tests/fixtures; pick a path under backend/data/copilot_eval")
    cases = []
    with (Session(engine) if session is None else nullcontext(session)) as db:
        rows = db.exec(select(CopilotInvestigation).where(CopilotInvestigation.source == "copilot",
                                                           col(CopilotInvestigation.updated_at) >= since)
                       .order_by(col(CopilotInvestigation.updated_at).desc())).all()
        for row in rows:
            if (row.title or "").startswith(SKIP_TITLES):
                continue
            transcript = json.loads(row.transcript_json)
            for i, message in enumerate(transcript):
                if message.get("role") != "user":
                    continue
                answer = transcript[i + 1] if i + 1 < len(transcript) and transcript[i + 1].get("role") == "assistant" else {}
                following = transcript[i + 2] if i + 2 < len(transcript) and transcript[i + 2].get("role") == "user" else {}
                cases.append({"id": hashlib.sha1(f"{row.id}:{i}".encode()).hexdigest()[:12], "workflow": "owner",
                              "symbol": row.symbol, "question": _scrub(user_text(message.get("content") or ""))[:2000],
                              "at": (row.created_at or row.updated_at).isoformat(timespec="minutes"),
                              "rating": answer.get("rating"), "next_question": _scrub(following.get("content") or "")[:300] or None,
                              "expects": {}})
    write_jsonl(out, cases)
    return len(cases)


def cmd_export(args) -> int:
    try:
        n = export_cases(datetime.now(UTC).replace(tzinfo=None) - timedelta(days=args.since), Path(args.out))
    except ValueError as exc:
        return _err(str(exc))
    print(f"{n} cases → {args.out}")
    return 0


# --------------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="copilot_eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="play the cases through the copilot and record the answers")
    run.add_argument("--cases", default=str(DEFAULT_CASES))
    run.add_argument("--model", default="fake", help="fake (the scripted model, free) or a Claude model id")
    run.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    run.add_argument("--evidence", default="fixture", choices=["fixture", "replay"])
    run.add_argument("--replay-store", help="replay: a read-only Radar snapshot file")
    run.add_argument("--replay-at", help="replay: New York time inside the recorded session, e.g. 2026-10-23T11:12")
    run.add_argument("--out", help="run directory (default under backend/data/copilot_eval/runs)")
    run.add_argument("--max-cost-usd", type=float, help="required for a paid model; the run stops at it")
    run.add_argument("--no-cache", action="store_true", help="re-run every case even when a cached answer exists")
    grade = sub.add_parser("grade", help="deterministic checks and, on request, the rubric judge")
    grade.add_argument("--run", required=True)
    grade.add_argument("--cases", default=str(DEFAULT_CASES))
    grade.add_argument("--judge", action="store_true")
    grade.add_argument("--judge-model", default=JUDGE_MODEL)
    grade.add_argument("--max-cost-usd", type=float, help="required with --judge; judging stops at it")
    report = sub.add_parser("report", help="tabulate one run, or compare two")
    report.add_argument("--run", action="append", required=True)
    report.add_argument("--out")
    export = sub.add_parser("export", help="the owner's real questions as a case file, ids stripped")
    export.add_argument("--since", type=int, default=30, help="days")
    export.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.monotonic()
    code = {"run": cmd_run, "grade": cmd_grade, "report": cmd_report, "export": cmd_export}[args.command](args)
    if code == 0 and args.command != "report":
        print(f"done in {time.monotonic() - started:.1f} s")
    return code


if __name__ == "__main__":
    sys.exit(main())
