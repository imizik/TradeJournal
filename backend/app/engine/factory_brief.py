"""The strategy factory's weekly brief: what the idea model sees, and what it may propose.

Each week an idea model (Claude, called by `scripts/strategy_factory.py week`)
reads a brief: the factory's building blocks, every idea in the ledger and how
it fared, what the discovery-period trades of recent ideas show, and its own
earlier lessons. It answers with a few new candidates as specs. This module
writes the brief, checks the answer, and writes the week's report.

The model never runs anything. A proposal becomes a candidate only if it is a
valid spec within these rules, and the factory then judges it like any other:

- the core universe and the default costs, always: picking tickers or costs
  after seeing results is selection, not an edge;
- at most two filters;
- nothing already in the ledger, and no two alike in one week;
- at most `WEEKLY_BUDGET` new candidates a week (a learned filter's rules
  count too when they are new), so the bar at confirmation rises slowly.

Exam results reach the brief only as passed or failed.

Pure: no network, no database.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date
from typing import Any

from app.engine.factory_data import ET, FEATURES
from app.engine.factory_rules import (
    CORE_UNIVERSE,
    FAMILIES,
    Costs,
    Spec,
    Trade,
    canonical,
    family_sides,
    parse_spec,
    spec_id,
)

WEEKLY_BUDGET = 3
MAX_FILTERS = 2
LESSON_WEEKS = 4

SYSTEM_PROMPT = """\
You propose experiments for the strategy factory, an automated pipeline that \
judges trading-strategy ideas on historical US stock data. Each week you read \
what has been tried and what was learned, and propose a few new candidates as \
specs; the factory then judges them without you. Most candidates fail, and a \
week where nothing passes is a normal week. Propose the ideas most likely to \
be genuinely better than chance; a candidate that passes by luck costs real \
money later.

How the factory judges a candidate. Every stage compares it with random \
entries: an entry every 15 minutes with the candidate's own exits, costs and \
stop rule.
1. Screen, on the discovery period (July 2023 to September 2024): at least \
100 trades, average R above 0 after costs, and better than random entries \
with t >= 2 (t is clustered by week).
2. Confirmation, on October 2024 to March 2026 in two halves: positive and \
better than random in each half; across both, t above a bar that rises with \
every candidate that ever reaches this stage (Bonferroni at 5%); still \
positive with costs tripled; money made on at least half the tickers; not \
carried by one ticker. A learned filter must also beat the same rules \
without it.
3. Exam, once, on the locked holdout from April 2026.
A weak idea that slips through the screen raises the bar for every later \
idea, so one well-reasoned candidate is worth more than three variations.

The rules. The factory rejects a proposal that breaks the first four.
1. Trade the core universe and the default costs: leave out "tickers" and \
"costs". Choosing either after seeing results is selection, not an edge.
2. At most two filters.
3. Nothing already in the ledger; the factory computes an id from the rules, \
so a renamed copy is still a copy.
4. Only the families, settings and features in the catalog. When an idea \
needs a building block that does not exist, do not approximate it: name it \
under "wanted".
5. One hypothesis per idea. When building on an earlier candidate, change \
one thing (the entry, the exit, or one filter) and say which.
6. Round, coarse values: targets such as 1, 1.5, 2 or 3R; a stop moved at \
0.5 or 1R or trailing 1 or 2R; holds such as 20, 60 or 120 minutes, or 1 to 3 \
sessions; timeframes of 1, 5, 15 or 30 minutes; \
thresholds at round numbers (0, plus or minus 0.5 or 1, rvol 1.5 or 2). \
Tuning a number to history is overfitting.
7. The discovery evidence is there to be mined, but an idea drawn from it is \
fitted to the screen's data, so its real test is confirmation; mark it.
8. Prefer ideas that answer a documented failure: for example, entries that \
beat random but lose after costs suggest fewer trades with more room per \
trade; results that depend on one regime suggest a market filter.
9. At most two ideas from the same family in one week.

Answer in the given JSON format. Each idea's spec_json is the spec as a JSON \
string with "family" and whatever differs from that family's defaults. \
"lessons" is what the ledger says now, in three to six plain sentences for a \
trader who does not read code. "wanted" lists missing building blocks that \
would let you test better ideas."""

IDEAS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "hypothesis": {"type": "string"},
                    "builds_on": {"type": "string"},
                    "change": {"type": "string"},
                    "from_evidence": {"type": "boolean"},
                    "spec_json": {"type": "string"},
                },
                "required": ["title", "hypothesis", "builds_on", "change", "from_evidence", "spec_json"],
                "additionalProperties": False,
            },
        },
        "lessons": {"type": "string"},
        "wanted": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ideas", "lessons", "wanted"],
    "additionalProperties": False,
}


def answer_problem(answer: Any) -> str | None:
    """Why an answer does not fit IDEAS_SCHEMA, or None. The API holds its
    answer to the schema; one written in a Claude Code session (`/factory-week`)
    gets this check instead."""
    types = {"string": str, "boolean": bool, "array": list}

    def check(value: Any, schema: Mapping[str, Any], where: str) -> str | None:
        if schema["type"] == "object":
            if not isinstance(value, Mapping):
                return f"{where} is not an object"
            missing = sorted(set(schema["required"]) - set(value))
            extra = sorted(set(value) - set(schema["properties"]))
            if missing:
                return f"{where} lacks {', '.join(missing)}"
            if extra:
                return f"{where} has {', '.join(extra)}, which the format does not"
            for key, part in schema["properties"].items():
                problem = check(value[key], part, f"{where}.{key}")
                if problem:
                    return problem
            return None
        if not isinstance(value, types[schema["type"]]):
            return f"{where} is not a {schema['type']}"
        if schema["type"] == "array":
            for k, item in enumerate(value):
                problem = check(item, schema["items"], f"{where}[{k}]")
                if problem:
                    return problem
        return None

    return check(answer, IDEAS_SCHEMA, "answer")

SPEC_FORMAT = """\
A spec is a JSON object. Only "family" is required; everything else defaults \
to that family's values in the catalog.
- "family": one of the catalog's families.
- "params": the family's settings to change, e.g. {"confirm_bars": 2}.
- "timeframe": bar minutes, dividing 30 (1, 2, 3, 5, 10, 15, 30).
- "exits": {"target_r": R or null, "max_sessions": sessions held (1 is flat \
by the close), "max_minutes": minutes or null, "breakeven_r": R or null, \
"trail_r": R or null}. The last two move the stop, and are off unless set: \
after each completed bar, to the entry once the best price so far is \
breakeven_r R in favour, and to trail_r R behind the best price, whichever \
is tighter; it never moves back. breakeven_r must be below target_r. An \
exit at a moved stop is named "breakeven" or "trail" in the evidence.
- "window": [HHMM, HHMM], the fill times allowed, or null for any time.
- "limits": {"max_entries", "max_losses", "max_loss_r"} per ticker and \
session, each null for none.
- "filters": up to two of {"feature": name, "min": x, "max": y}, either bound \
optional; a signal is taken only when the feature is within them.
- "model": {"kind": "logistic", "features": [...]} adds a learned filter \
trained on the discovery trades of the same spec without it. Name its \
features; without a list it reads the ten from "minutes" to "risk"."""


# --- the catalog ----------------------------------------------------------------


def catalog() -> dict[str, Any]:
    """Every family with its settings and defaults, and every feature."""
    families = {}
    for name, cls in FAMILIES.items():
        rules = cls()
        families[name] = {
            "about": inspect.cleandoc(cls.__doc__ or ""),
            "sides": ["long" if side == 1 else "short" for side in family_sides(rules)],
            "settings": {f.name: getattr(rules, f.name) for f in fields(cls)},
            "defaults": cls.defaults,
        }
    return {"families": families, "features": FEATURES}


# --- the ledger, as the model sees it ------------------------------------------


def _round(value: Any) -> Any:
    return round(value, 3) if isinstance(value, float) else value


def _brief_stats(stats: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trades": stats.get("n"),
        "avg_r": _round(stats.get("mean_r")),
        "random_r": _round(stats.get("random_r")),
        "vs_random": _round(stats.get("edge")),
        "t": _round(stats.get("edge_t")),
        "profit_factor": _round(stats.get("profit_factor")),
        "tickers_up": f"{stats.get('tickers_up')}/{stats.get('tickers')}",
    }


def spec_changes(spec: Mapping[str, Any]) -> dict[str, Any]:
    """What a canonical spec (as the ledger stores it) changes from its family's
    defaults, in the spec format a proposal is written in: the window as HHMM,
    filter bounds as min and max."""
    base = canonical(parse_spec({"family": spec["family"]}))
    changes: dict[str, Any] = {}
    for key, value in spec.items():
        if key == "params":
            changed = {k: v for k, v in value.items() if base["params"].get(k) != v}
            if changed:
                changes["params"] = changed
        elif key != "family" and base.get(key) != value:
            if key == "window" and value:
                value = [minute // 60 * 100 + minute % 60 for minute in value]
            elif key == "filters":
                value = [{"feature": item["feature"],
                          **{bound: item[stored] for bound, stored in (("min", "low"), ("max", "high"))
                             if item.get(stored) is not None}} for item in value]
            changes[key] = value
    return changes


def ledger_digest(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every idea in the ledger, compact. A later line for the same id replaces
    an earlier one, keeping a hand-research summary of the same rules."""
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        item: dict[str, Any] = {"id": record["id"], "name": record["name"], "verdict": record["verdict"]}
        if record.get("source") == "hand research":
            item["tested"] = "by hand, before the factory existed"
            item["summary"] = record.get("summary", "")
        else:
            earlier = latest.get(record["id"], {})
            if earlier.get("tested", "").startswith("by hand"):
                item["by_hand_before"] = earlier["summary"]
            elif "by_hand_before" in earlier:
                item["by_hand_before"] = earlier["by_hand_before"]
            item["family"] = record["spec"]["family"]
            item["changes_from_defaults"] = spec_changes(record["spec"])
            item["notes"] = record.get("notes", "")
            periods = record.get("periods") or {}
            item["results"] = {name: _brief_stats(periods[name])
                               for name in ("discovery", "confirm_a", "confirm_b", "confirm", "confirm_x3")
                               if name in periods}
            if "holdout" in periods:
                item["exam"] = {"passed": "passed", "awaiting_exam": "not enough holdout trades yet"}.get(
                    record["verdict"], "failed")
        latest[record["id"]] = item
    return list(latest.values())


# --- discovery evidence --------------------------------------------------------

HOURS = (("09:30-10:30", 570, 630), ("10:30-12:00", 630, 720), ("12:00-14:00", 720, 840), ("14:00-16:00", 840, 960))


def _summary(rs: Sequence[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0}
    wins = [r for r in rs if r > 0]
    return {"trades": len(rs), "avg_r": round(sum(rs) / len(rs), 3), "win_pct": round(100 * len(wins) / len(rs), 1)}


def evidence(trades: Iterable[Trade]) -> dict[str, Any]:
    """What separated better discovery trades from worse ones: average R
    overall, by side, time of day and exit, and by fifths of each feature."""
    closed = [t for t in trades if t.closed]
    out: dict[str, Any] = {"all": _summary([t.r for t in closed])}
    by_side: dict[str, list[float]] = defaultdict(list)
    by_hour: dict[str, list[float]] = defaultdict(list)
    by_exit: dict[str, list[float]] = defaultdict(list)
    for t in closed:
        by_side["long" if t.side == 1 else "short"].append(t.r)
        local = t.signal_time.astimezone(ET)
        minute = local.hour * 60 + local.minute
        for label, first, last in HOURS:
            if first <= minute < last:
                by_hour[label].append(t.r)
        by_exit[t.exit_reason].append(t.r)
    out["by_side"] = {k: _summary(v) for k, v in sorted(by_side.items())}
    out["by_signal_time"] = {label: _summary(by_hour[label]) for label, _, _ in HOURS if by_hour[label]}
    out["by_exit"] = {k: _summary(v) for k, v in sorted(by_exit.items())}
    fifths: dict[str, list[dict[str, Any]]] = {}
    for name in FEATURES:
        pairs = sorted((t.features[name], t.r) for t in closed
                       if not math.isnan(t.features.get(name, math.nan)))
        if len(pairs) < 25:
            continue
        rows = []
        for k in range(5):
            chunk = pairs[k * len(pairs) // 5:(k + 1) * len(pairs) // 5]
            rows.append({"from": round(chunk[0][0], 2), "to": round(chunk[-1][0], 2),
                         **_summary([r for _, r in chunk])})
        fifths[name] = rows
    out["by_feature_fifth"] = fifths
    return out


# --- the brief -------------------------------------------------------------------


def brief(
    today: date,
    records: Sequence[Mapping[str, Any]],
    evidence_by_idea: Mapping[str, Mapping[str, Any]],
    lessons: Sequence[tuple[str, str]],
    budget: int,
    bar_t: float,
    candidates: int,
) -> str:
    """The user turn of the weekly request; the rules are in SYSTEM_PROMPT."""
    sections = [
        f"Today is {today.isoformat()}. Propose up to {budget} new candidates this week.",
        f"The bar at confirmation is t >= {bar_t:.2f}: {candidates} candidates have reached that stage, "
        f"counting the ideas tested by hand before the factory existed.",
        "## Spec format\n" + SPEC_FORMAT,
        "## Catalog: the families, their settings and defaults, and the features\n"
        + json.dumps(catalog(), indent=1, default=str),
        "## Ledger: every idea so far\n" + json.dumps(ledger_digest(records), indent=1, default=str),
        "## Discovery evidence (July 2023 - September 2024 only)\n"
        "Each entry is one idea's discovery-period trades, with its average R by side, by the signal's time "
        "of day, by exit, and by fifths of each feature (lowest to highest). Entries are keyed by ledger id; "
        "a family name means that family with its default settings.\n"
        + json.dumps(evidence_by_idea, indent=1, default=str),
    ]
    if lessons:
        sections.append("## Your lessons from earlier weeks\n" + "\n\n".join(
            f"{day}: {text}" for day, text in lessons))
    return "\n\n".join(sections)


# --- the answer ------------------------------------------------------------------


@dataclass
class Proposal:
    title: str
    hypothesis: str
    builds_on: str
    change: str
    from_evidence: bool
    spec: Spec | None = None
    data: dict[str, Any] | None = None  # the spec as proposed, with its name and notes: what gets saved
    runs: int = 0  # candidates it adds to the ledger: its own, and its rules' when they are new
    problem: str = ""

    @property
    def id(self) -> str:
        return spec_id(self.spec) if self.spec is not None else ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "idea"


def review(answer: Mapping[str, Any], known: set[str], budget: int) -> list[Proposal]:
    """Each proposed idea, accepted (with its spec) or with the reason it was refused."""
    proposals: list[Proposal] = []
    seen = set(known)
    left = budget
    for idea in answer.get("ideas", []):
        p = Proposal(str(idea.get("title", "")).strip(), str(idea.get("hypothesis", "")).strip(),
                     str(idea.get("builds_on", "")).strip(), str(idea.get("change", "")).strip(),
                     bool(idea.get("from_evidence")))
        proposals.append(p)
        try:
            data = json.loads(idea.get("spec_json", ""))
        except json.JSONDecodeError:
            p.problem = "its spec is not valid JSON"
            continue
        if not isinstance(data, dict):
            p.problem = "its spec is not a JSON object"
            continue
        if data.get("tickers") not in (None, "core", list(CORE_UNIVERSE)):
            p.problem = "it picks its own tickers"
            continue
        if data.get("costs"):
            try:
                same_costs = Costs(**data["costs"]) == Costs()
            except TypeError:
                same_costs = False
            if not same_costs:
                p.problem = "it changes the costs"
                continue
        if isinstance(data.get("filters"), (list, tuple)) and len(data["filters"]) > MAX_FILTERS:
            p.problem = f"it has more than {MAX_FILTERS} filters"
            continue
        if not p.title or not p.hypothesis:
            p.problem = "it has no title or no hypothesis"
            continue
        data["name"] = p.title
        data["notes"] = " ".join(part for part in (
            p.hypothesis,
            f"Builds on {p.builds_on}: {p.change}" if p.builds_on else f"New idea: {p.change}" if p.change else "",
            "Drawn from the discovery evidence, so the screen is not an independent test of it."
            if p.from_evidence else "",
        ) if part)
        try:
            spec = parse_spec(data)
        except (TypeError, ValueError, AttributeError, KeyError) as exc:  # parse_spec raises ValueError; the rest are a net
            p.problem = f"its spec is invalid: {exc}"
            continue
        identifier = spec_id(spec)
        if identifier in seen:
            p.problem = "the same rules are already in the ledger" if identifier in known else "it repeats another idea this week"
            continue
        parent = spec.parent()
        runs = 1 + (parent is not None and spec_id(parent) not in seen)
        if runs > left:
            p.problem = "it does not fit this week's budget"
            continue
        p.spec, p.data, p.runs = spec, data, runs
        seen.add(identifier)
        if parent is not None:
            seen.add(spec_id(parent))
        left -= runs
    return proposals


def spec_file(p: Proposal) -> tuple[str, dict[str, Any]]:
    """A file name and the JSON to save for an accepted proposal: the spec as
    proposed, with its name and notes, which parses back to the same id."""
    assert p.spec is not None and p.data is not None
    data = {"name": p.data["name"], **{k: v for k, v in p.data.items() if k not in ("name", "notes")},
            "notes": p.data["notes"]}
    assert spec_id(parse_spec(data)) == p.id
    return f"{_slug(p.title)}.json", data


# --- the week's report -------------------------------------------------------------

VERDICT_TEXT = {
    "failed_screen": "failed the screen",
    "failed_confirmation": "failed confirmation",
    "passed_confirmation": "passed confirmation (no exam run)",
    "awaiting_exam": "passed confirmation; waiting for enough holdout trades",
    "failed_exam": "passed confirmation, failed the exam",
    "passed": "PASSED every gate",
}


def _result_line(stats: Mapping[str, Any] | None) -> str:
    if not stats or not stats.get("n"):
        return "no trades"
    t = stats.get("edge_t")
    return (f"{stats['n']:,} trades, {stats['mean_r']:+.3f}R a trade, "
            f"{(stats.get('edge') or 0):+.3f}R vs random" + (f" (t {t:.2f})" if t is not None else ""))


def weekly_report(
    day: date,
    proposals: Sequence[Proposal],
    records: Mapping[str, Mapping[str, Any]],
    answer: Mapping[str, Any],
    ledger_note: str,
    footer: str,
) -> tuple[str, str]:
    """The week's report in Markdown, and a one-paragraph summary for the phone.

    `records` maps each ledger id run this week to its new ledger line (a
    learned filter's rules included)."""
    accepted = [p for p in proposals if p.spec is not None]
    judged = [records[p.id] for p in accepted if p.id in records]
    passed = [r for r in judged if r["verdict"] in ("passed", "awaiting_exam", "passed_confirmation")]
    confirmed = [r for r in judged if r.get("reached_confirmation")]
    ideas = f"{len(judged)} idea{'' if len(judged) == 1 else 's'}"
    if not accepted:
        headline = "No idea was accepted this week, so nothing was judged."
    elif passed:
        headline = f"{len(passed)} of {ideas} passed confirmation: " + ", ".join(r["name"] for r in passed) + "."
    else:
        headline = f"{ideas} judged, none passed" + (
            f" ({len(confirmed)} reached confirmation)." if confirmed else "; all stopped at the screen.")
    lines = [f"# Strategy factory, week of {day.isoformat()}", "", f"**{headline}** {ledger_note}", ""]
    if judged:
        lines += ["| Idea | Verdict | Discovery | Confirmation |", "|---|---|---|---|"]
        for p in accepted:
            r = records.get(p.id)
            if r is None:
                continue
            periods = r.get("periods") or {}
            lines.append(f"| {p.title} | {VERDICT_TEXT.get(r['verdict'], r['verdict'])} | "
                         f"{_result_line(periods.get('discovery'))} | "
                         f"{_result_line(periods.get('confirm')) if 'confirm' in periods else '—'} |")
        lines.append("")
    lines += ["## The ideas", ""]
    for k, p in enumerate(accepted, start=1):
        r = records.get(p.id, {})
        lines += [f"### {k}. {p.title} (`{p.id}`)", "", p.hypothesis, "",
                  f"- Builds on: {p.builds_on or 'nothing, a new idea'}. Change: {p.change or '—'}.",
                  f"- From the discovery evidence: {'yes' if p.from_evidence else 'no'}.",
                  f"- Verdict: {VERDICT_TEXT.get(r.get('verdict', ''), r.get('verdict', 'not run'))}."]
        parent = p.spec.parent() if p.spec is not None else None
        if parent is not None and spec_id(parent) in records:
            lines.append(f"- Its rules without the model were new, so they were judged first: "
                         f"{VERDICT_TEXT.get(records[spec_id(parent)]['verdict'], records[spec_id(parent)]['verdict'])}.")
        for gate, result in (r.get("gates") or {}).items():
            failed = [text for text, ok in result["checks"] if not ok]
            if failed:
                lines.append(f"- {gate.capitalize()} failed on: " + "; ".join(failed) + ".")
        lines.append("")
    refused = [p for p in proposals if p.spec is None]
    if refused:
        lines += ["## Refused proposals", ""] + [f"- {p.title or 'untitled'}: {p.problem}." for p in refused] + [""]
    lines += ["## What the ledger says now", "", str(answer.get("lessons", "")).strip(), ""]
    wanted = [w for w in answer.get("wanted", []) if str(w).strip()]
    if wanted:
        lines += ["## Building blocks wanted", ""] + [f"- {w}" for w in wanted] + [""]
    lines += ["---", footer, ""]
    best = max(judged, key=lambda r: ((r.get("periods") or {}).get("discovery") or {}).get("edge_t") or -99,
               default=None)
    summary = headline + (f" Closest: {best['name']} ({VERDICT_TEXT.get(best['verdict'], best['verdict'])})."
                          if best is not None and not passed else "") + f" {ledger_note}"
    return "\n".join(lines), summary


def lessons_from(report: str) -> str:
    """The "What the ledger says now" section of an earlier report."""
    match = re.search(r"^## What the ledger says now\n\n(.*?)(?=\n## |\n---|\Z)", report, re.S | re.M)
    return match.group(1).strip() if match else ""

