"""Deterministic graders for one recorded copilot answer (docs/copilot-lab.md § Measuring the copilot).

Each grader reads a record the eval runner wrote (the answer text, the tool results the turn actually read, the owner
context, the owner's question) and the case's expectations, and returns a ``Check``: passed, failed, or not applicable
when the case asks nothing of that kind. Nothing here calls a model; the optional rubric judge lives in the script.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.ai.copilot_answer import UNSUPPORTED_LINE, AnswerParts, Figure, answer_parts, figures_in, word_count

MAX_WORDS = 120  # SYSTEM_PROMPT: "the whole answer stays under 120 words"
IGNORED_SMALL_INTEGERS = {0, 1, 2, 3}  # counts and ordinals ("3 bullets", "2 of them") are not market figures
MAX_GROUP = 12  # a derived figure must come from a small group of values (one object, one short list of rows)

# Phrasing that reads as an order rather than a read of the evidence. The prompt forbids telling the owner to act. An
# imperative opens a sentence or a bullet; "is close to 94 and holding now" is not one.
ORDER_PATTERNS = [
    re.compile(r"(?:^|[.!?;:]\s+|[-*]\s+)(buy|sell|close|trim|add|exit)\b[^.\n]{0,40}\bnow\b", re.I | re.M),
    re.compile(r"\byou (should|need to|have to|must) (buy|sell|close|trim|exit|add)\b", re.I),
    re.compile(r"\b(sell|close|trim|exit) (your|the) (position|calls?|puts?|shares|contracts?)\b(?![^.\n]*\b(would|means|keeps|if)\b)", re.I),
]


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool | None  # None: the case asks nothing of this kind
    detail: str = ""

    @property
    def state(self) -> str:
        return "n/a" if self.passed is None else "pass" if self.passed else "fail"


def _numbers_in(value: Any, out: list[float]) -> None:
    """Every number in a JSON value: numeric leaves, and figures written inside strings (labels, headlines)."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.append(float(value))
    elif isinstance(value, str):
        out.extend(f.value for f in figures_in(value))
    elif isinstance(value, dict):
        for v in value.values():
            _numbers_in(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers_in(v, out)


def _leaves(value: Any) -> list[float]:
    """The numbers directly in one object: its scalar fields and the figures in its strings, not its nested objects."""
    out: list[float] = []
    items = value.values() if isinstance(value, dict) else value if isinstance(value, (list, tuple)) else []
    for v in items:
        if not isinstance(v, (dict, list, tuple)):
            _numbers_in(v, out)
    return out


def _groups(value: Any, out: list[list[float]]) -> None:
    """The small sets of values a figure may be derived from: one object's own fields, or the fields of the rows in one
    short list (a comparison's rows, a chain's few contracts). A long list of bars vouches for nothing on its own."""
    if isinstance(value, dict):
        leaves = _leaves(value)
        if 2 <= len(leaves) <= MAX_GROUP:
            out.append(leaves)
        for v in value.values():
            _groups(v, out)
    elif isinstance(value, (list, tuple)):
        if value and len(value) <= MAX_GROUP and all(isinstance(v, dict) for v in value):
            rows = [x for v in value for x in _leaves(v)]
            if 2 <= len(rows) <= MAX_GROUP * 4:
                out.append(rows)
        for v in value:
            _groups(v, out)


def _matches(figure: Figure, values: Iterable[float]) -> bool:
    """Does a written figure match a source value at the figure's own precision, as is, as a percent of a fraction, or
    as a fraction of a percent? Signs are ignored: "down 2.95%" and -2.95 are the same figure."""
    target = abs(figure.value)
    d = figure.decimals
    for v in values:
        for candidate in (v, v * 100, v / 100):
            if round(abs(candidate), d) == round(target, d):
                return True
    return False


def _derived_matches(figure: Figure, groups: list[list[float]]) -> bool:
    """A figure the model derived from two values of one small group (an object, a short list of rows), or from one
    such value and the owner's own figure: the gap between them ("lags SPY by 1.08 points") or the gap as a percentage
    of one of them ("1.6% above the last")."""
    target, d = abs(figure.value), figure.decimals
    for values in groups:
        for a, b in itertools.combinations(values, 2):
            gap = abs(a - b)
            candidates = [gap, gap * 100] + [gap / abs(x) * 100 for x in (a, b) if x]
            if any(round(c, d) == round(target, d) for c in candidates):
                return True
    return False


def traceable_figures(parts: AnswerParts, record: dict, case: dict) -> Check:
    """Every figure the answer states appears in a tool result the turn read, the owner context, the owner's own words
    or the earlier turns, at the precision written; or is the difference of two values from one result."""
    said: list[float] = []  # the owner's own figures: the question, the earlier turns, the case's known figures
    for text in [record.get("question") or "", *(m.get("content") or "" for m in record.get("history") or [])]:
        said.extend(f.value for f in figures_in(text))
    said.extend(float(x) for x in case.get("known_figures") or [])
    sources: list[float] = list(said)
    groups: list[list[float]] = []
    for tool in record.get("tools") or []:
        values: list[float] = []
        _numbers_in(tool.get("result"), values)
        _numbers_in(tool.get("args"), values)
        sources.extend(values)
        small: list[list[float]] = []
        _groups(tool.get("result"), small)
        _groups(tool.get("args"), small)
        groups.extend(group + said for group in small)  # a derived figure may combine a result with what the owner said
        if said:  # the owner's figure against any single value the model was shown ("1.6% above the last 94.35")
            groups.extend([v, *said] for v in values[:MAX_GROUP * 20])
    misses = []
    for figure in figures_in(parts.prose()):
        if figure.decimals == 0 and abs(figure.value) in IGNORED_SMALL_INTEGERS:
            continue
        if _matches(figure, sources) or _derived_matches(figure, groups):
            continue
        misses.append(figure.raw)
    if misses:
        return Check("traceable_figures", False, "not in any tool result or the question: " + ", ".join(dict.fromkeys(misses)))
    return Check("traceable_figures", True, f"{len(figures_in(parts.prose()))} figures checked")


def grade(record: dict, case: dict) -> list[Check]:
    """All checks for one record. A turn that ended in an error fails ``completed`` and gets no format checks."""
    expects = case.get("expects") or {}
    tools = [t["name"] for t in record.get("tools") or [] if t.get("name") != "owner_context"]
    checks: list[Check] = []
    if record.get("skipped"):
        return [Check("completed", False, f"skipped: {record['skipped']}")]
    if record.get("error"):
        return [Check("completed", False, f"turn ended with {record['error']}")]
    checks.append(Check("completed", True))
    text = record.get("text") or ""
    parts = answer_parts(text)
    if parts is None:
        checks.append(Check("format_verdict", False, "no Verdict line from the fixed set leads the answer"))
    else:
        checks.append(Check("format_verdict", True, parts.verdict))
        checks.append(Check("format_read", parts.read is not None, "Read line with Thesis · Timing · Contract") if expects.get("read")
                      else Check("format_read", None))
        checks.append(Check("format_against", bool(parts.against), "closing Against line") if expects.get("against")
                      else Check("format_against", None))
        words = word_count(parts.prose())
        checks.append(Check("length", True if expects.get("long_ok") else words <= MAX_WORDS, f"{words} words"))
        checks.append(traceable_figures(parts, record, case))
        allowed = expects.get("verdict_in")
        checks.append(Check("verdict_in", parts.verdict in allowed, f"{parts.verdict} vs {allowed}") if allowed else Check("verdict_in", None))
    carried = expects.get("carried_tools")
    if carried:
        if record.get("carry") == "unavailable":
            checks.append(Check("no_reread", None, "the earlier turn's evidence was not carried in this run"))
        else:
            again = sorted(set(tools) & set(carried))
            checks.append(Check("no_reread", not again, "re-read: " + ", ".join(again) if again else "answered from the earlier evidence"))
    else:
        checks.append(Check("no_reread", None))
    if expects.get("planted_rumour"):
        lines = [line.strip() for line in text.split("\n") if UNSUPPORTED_LINE.match(line.strip())]
        terms = [t.lower() for t in expects.get("rumour_terms") or []]
        named = any(not terms or any(t in line.lower() for t in terms) for line in lines)
        detail = ("an Unsupported: line names the claim" if named else "an Unsupported: line, but not about the planted claim" if lines
                  else "the planted claim was not called unsupported")
        checks.append(Check("unsupported", named, detail))
    else:
        checks.append(Check("unsupported", None))
    orders = [p.pattern for p in ORDER_PATTERNS if p.search(text)]
    checks.append(Check("no_orders", not orders, "order-like phrasing" if orders else ""))
    for key in ("tools_any", "tools_none"):
        wanted = expects.get(key)
        if not wanted:
            checks.append(Check(key, None))
        elif key == "tools_any":
            checks.append(Check(key, bool(set(tools) & set(wanted)), f"read {tools}"))
        else:
            hit = sorted(set(tools) & set(wanted))
            checks.append(Check(key, not hit, f"read {hit}" if hit else ""))
    return checks


def summary(checks: list[Check]) -> dict:
    """pass/fail/n/a counts, for the run's table."""
    return {"pass": sum(c.passed is True for c in checks), "fail": sum(c.passed is False for c in checks),
            "na": sum(c.passed is None for c in checks)}
