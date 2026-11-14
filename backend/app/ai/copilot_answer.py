"""The copilot's answer format, read back (docs/copilot-lab.md § Measuring the copilot).

A Python port of ``answerParts`` in ``frontend/lib/copilot.ts``: the Verdict line first, an optional Read line, the
body (or a Compare block), then the closing Against and Changes-if lines. The two parsers must agree; change them
together. Used by the offline eval's graders (``copilot_graders``), never on the request path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

VERDICTS = ("Hold", "Wait", "Pass", "Focus", "Draft", "Pattern", "Broken", "Unclear")

# The separator after the verdict word is a dash in the format; a colon or a full stop ("Verdict: Wait. Not yet.") is read
# the same way, since the model writes one now and then (two of 23 answers on 2026-11-07) and the owner should still see the
# verdict tag. Kept in step with VERDICT_LINE in frontend/lib/copilot.ts.
VERDICT_LINE = re.compile(r"^\**verdict\**\s*:\s*\**([a-z]+)\**\s*(?:—|–|--|-|:|\.)\s*(.+)$", re.I)
CHANGES_LINE = re.compile(r"^(?:[-*]\s+)?\**changes if\**\s*:\**\s*(.+?)\**$", re.I)
AGAINST_LINE = re.compile(r"^(?:[-*]\s+)?\**against\**\s*:\**\s*(.+?)\**$", re.I)
UNSUPPORTED_LINE = re.compile(r"^(?:[-*]\s+)?\**unsupported\**\s*:", re.I)
READ_LINE = re.compile(r"^\**read\**\s*:\**\s*(.+?)\**$", re.I)
READ_PART = re.compile(r"^(thesis|timing|contract)\s+(.+)$", re.I)
COMPARE_LINE = re.compile(r"^\**compare\**\s*:\**\s*(.+?)\s+\|\s+(.+?)\**$", re.I)
COMPARE_ROW = re.compile(r"^(?:[-*]\s+)?\**(needs|risks|breaks if|costs)\**\s*:\**\s*(.+?)\s+\|\s+(.+?)\**$", re.I)
NOTE_LINE = re.compile(r"^_\(.*\)_$")  # the scripted model's own labels, which may come first

# The length rule, in one place: SYSTEM_PROMPT states it, ANSWER_SHAPE repeats it where the answer is written, and the
# eval's ``length`` check measures it over ``AnswerParts.prose()`` (the Read line aside).
MAX_WORDS = 120
HEADLINE_WORDS, BULLET_WORDS, AGAINST_WORDS, CHANGES_WORDS = 15, 16, 20, 15  # 15 + 3 × 16 + 20 + 15 = 98 < 120
COMPARE_CELL_WORDS = 6  # a compare block replaces the bullets: 15 + 10 × 6 + 20 + 15 = 110 < 120
# The bullet budget was 22 until 2026-11-08: Sonnet 5.5 kept to three bullets but wrote each as two or three sentences of
# 25–35 words, so answers landed at a 128-word median (docs/copilot-lab.md, Answer-length re-measure). 16 words as exactly
# one sentence leaves that overshoot room under the limit.

# Sent as the last text of the owner's message and after every tool-result batch, so the model reads it right before it
# writes. The same rule in the middle of the 3,700-word system prompt was not followed: on 2026-11-06 Sonnet 5.5 wrote
# 150–295 words (four or five multi-sentence bullets, a closing note) on 20 of 22 eval cases. The scripted model never
# reads it as the owner's words (``copilot_context.user_text`` strips it).
ANSWER_SHAPE = (
    f"[Answer shape: under {MAX_WORDS} words in all, a hard limit unless the owner asks for more (\"more\", \"why\", "
    f"\"go deeper\") or a trade or week review. Verdict headline at most {HEADLINE_WORDS} words. The Read line. Body: "
    f"at most 3 bullets, each one sentence of at most {BULLET_WORDS} words with figures and as-of, no bold label; a "
    f"second sentence is cut or becomes the next bullet. A compare block replaces the bullets: none beside it, four rows at "
    f"most, cells at most {COMPARE_CELL_WORDS} words. Against at most {AGAINST_WORDS} words. Changes if at most "
    f"{CHANGES_WORDS} words. Nothing else: no simulated-data line (two headline words), closing note, \"nothing is "
    "saved\" line or repeated card fields. Prose without a Verdict line keeps the limit.]"
)

# The other jobs' own shapes (docs/copilot-lab.md § How the copilot reasons, Jobs), sent where ANSWER_SHAPE is on a desk
# turn. Until 2026-11-10 every job got the desk's, so the morning brief was told "at most 10 plain lines, no headings"
# and then, right after, "Verdict line, Read line, three bullets". Each starts "[Answer shape:" like the desk's.
TELEGRAM_SHAPE = (
    f"[Answer shape: a phone chat, plain text. Under {MAX_WORDS} words unless the owner asks for more. Verdict line "
    f"first (headline at most {HEADLINE_WORDS} words) on a trading decision. Then at most 3 short plain lines, one "
    "sentence each with its figure and as-of; then Against, and Changes if when one thing would change it. No Read line, "
    "no Compare rows or table, no headings, bold or bullets markup, no closing note.]"
)
PREP_SHAPE = (
    "[Answer shape: the morning brief: only the short plain lines the message lists, in its order and within its line "
    "count. No Verdict, Read, Against or Changes if line, no headings, bullets or bold, nothing before or after.]"
)
COMPANION_SHAPE = (
    "[Answer shape: exactly the lines this message asks for, in its order and within its word limit, the Verdict line "
    "first. No Read line, extra bullets, compare block or closing note.]"
)
WEEK_SHAPE = (
    "[Answer shape: the Verdict line, then the review in short one-fact lines with their counts, in the order the "
    "instructions give; take the room the review needs and no more. No closing note or repeated card fields.]"
)
CHECK_SHAPE = (
    "[Answer shape: a call check: the Reading line (\"?\" for anything not stated), the Verdict line (Pass, Wait or "
    "Draft; Unclear only when no ticker can be read), three or four Tile lines (label | value), Against, Changes if, and "
    "Also only for other calls in the message. Nothing else: no preamble, bullets, markdown or closing note.]"
)
DESK_READ_SHAPE = (
    f"[Answer shape: the desk's read: three or four lines in all. The Verdict line (headline at most 12 words, never "
    f"Draft), one or two bullets of one sentence each, at most {BULLET_WORDS} words with figures and as-of (where it is "
    "against the owner's levels, then what is moving it today), then Changes if, at most "
    f"{CHANGES_WORDS} words. No Read or Against line, no headings, bold or closing note.]"
)
DAY_READ_SHAPE = (
    "[Answer shape: the day read: four to six short plain lines, P&L, Plans, Biggest, Tomorrow (and one more only when "
    "it changes the picture), under 110 words in all. Every dollar figure exactly as the facts write it. No Verdict line, "
    "markdown, bullets or closing note.]"
)
PAPER_REVIEW_SHAPE = (
    "[Answer shape: the paper review: four to six short plain lines, Week, Worked, Stops and targets, Next week (and one "
    "more only when it changes the picture), under 120 words in all. Every dollar figure exactly as the facts write it; "
    "paper and real kept apart. No Verdict line, markdown, bullets or closing note.]"
)
SHAPES = (ANSWER_SHAPE, TELEGRAM_SHAPE, PREP_SHAPE, COMPANION_SHAPE, WEEK_SHAPE, CHECK_SHAPE, DESK_READ_SHAPE, DAY_READ_SHAPE,
          PAPER_REVIEW_SHAPE)


def without_shape(content: str) -> str:
    """A prepared message without the job's shape reminder at its end (``copilot_context.user_text`` strips only the
    desk's)."""
    for shape in SHAPES:
        content = content.removesuffix("\n\n" + shape)
    return content


@dataclass(frozen=True)
class Compare:
    a: str
    b: str
    rows: tuple[tuple[str, str, str], ...]  # (label, a, b)


@dataclass(frozen=True)
class AnswerParts:
    verdict: str
    headline: str
    read: tuple[tuple[str, str], ...] | None  # ((Thesis, holds), (Timing, early), (Contract, n/a))
    body: str
    compare: Compare | None
    against: str | None
    changes_if: str | None

    def prose(self) -> str:
        """Everything the owner reads as the answer: headline, body, compare cells, Against and Changes if; the scripted
        model's note lines and the Read line left out."""
        pieces = [self.headline, *(line for line in self.body.split("\n") if line.strip() and not NOTE_LINE.match(line.strip()))]
        if self.compare:
            pieces += [self.compare.a, self.compare.b, *(cell for row in self.compare.rows for cell in row[1:])]
        pieces += [p for p in (self.against, self.changes_if) if p]
        return "\n".join(pieces)


def _skip_notes(lines: list[str], at: int) -> int:
    while at < len(lines) and (not lines[at].strip() or NOTE_LINE.match(lines[at].strip())):
        at += 1
    return at


def answer_parts(text: str) -> AnswerParts | None:
    """The answer's parts, or None for text without the structure (an older answer, an unknown verdict word)."""
    lines = text.split("\n")
    at = _skip_notes(lines, 0)
    found = VERDICT_LINE.match(lines[at].strip()) if at < len(lines) else None
    verdict = next((v for v in VERDICTS if found and v.lower() == found.group(1).lower()), None)
    if not found or not verdict:
        return None
    rest = lines[:at] + lines[at + 1:]
    nxt = _skip_notes(rest, at)
    read = None
    read_line = READ_LINE.match(rest[nxt].strip()) if nxt < len(rest) else None
    if read_line:
        parts = [READ_PART.match(p.strip()) for p in re.split(r"\s*[·|;]\s*", read_line.group(1))]
        if len(parts) == 3 and all(parts):
            read = tuple((p.group(1)[0].upper() + p.group(1)[1:].lower(), p.group(2).strip()) for p in parts)
            del rest[nxt]

    def closing(pattern: re.Pattern) -> str | None:
        last = len(rest) - 1
        while last >= 0 and not rest[last].strip():
            last -= 1
        hit = pattern.match(rest[last].strip()) if last >= 0 else None
        if hit:
            del rest[last]
            return hit.group(1).strip() or None
        return None

    changes_if = closing(CHANGES_LINE)
    against = closing(AGAINST_LINE)
    compare = None
    start = next((i for i, line in enumerate(rest) if COMPARE_LINE.match(line.strip())), -1)
    if start >= 0:
        sides = COMPARE_LINE.match(rest[start].strip())
        rows: list[tuple[str, str, str]] = []
        for line in rest[start + 1:]:
            row = COMPARE_ROW.match(line.strip())
            if not row:
                break
            rows.append((row.group(1)[0].upper() + row.group(1)[1:].lower(), row.group(2).strip(), row.group(3).strip()))
        if len(rows) >= 2:
            compare = Compare(sides.group(1).strip(), sides.group(2).strip(), tuple(rows))
            del rest[start:start + len(rows) + 1]
    return AnswerParts(verdict=verdict, headline=found.group(2).replace("**", "").strip(), read=read,
                       body="\n".join(rest).strip(), compare=compare, against=against, changes_if=changes_if)


def word_count(text: str) -> int:
    return len(text.split())


# --------------------------------------------------------------------------- numbers in prose

# A number the owner would read as a figure: 94.35, 1,528, -2.95, 4.5%, $610. Skipped: clock times (10:40), ISO, M/D and
# month-name dates (2026-10-23, 10/30, Nov 21), hex and other id-like runs, and a number glued to letters (5m, 1D, Q3, 12.5x).
# A sign counts only when no digit precedes it, so "5-10" is two figures and "-2.95" one.
_NUMBER = re.compile(r"(?<![\w/:.])(?:(?<!\d)[-+])?\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?%?(?![\w/:]|\.\d)")
# Capitalised month names only (the scoped flag turns off re.I there), so "market 21" and "may 5" stay figures.
_MONTH = r"(?-i:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b\.?)"
_TIME_OR_DATE = re.compile(r"\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b" + _MONTH + r"\s+\d{1,2}\b|\b\d{1,2}\s+" + _MONTH + r"(?!\.?\s+\d)"
                           + r"|[0-9a-f]{8}(?:-[0-9a-f]{4}){1,3}(?:-[0-9a-f]{12})?", re.I)


@dataclass(frozen=True)
class Figure:
    value: float
    decimals: int
    raw: str


def figures_in(text: str) -> list[Figure]:
    """Every figure in ``text`` (see ``_NUMBER``), with the precision it was written at."""
    masked = _TIME_OR_DATE.sub(lambda m: " " * len(m.group(0)), text)
    out = []
    for match in _NUMBER.finditer(masked):
        whole, frac = match.group(1).replace(",", ""), match.group(2) or ""
        raw = match.group(0)
        sign = -1.0 if raw.startswith("-") else 1.0
        out.append(Figure(sign * float(whole + frac), len(frac) - 1 if frac else 0, raw))
    return out
