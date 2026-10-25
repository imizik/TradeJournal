"""Spoken tickers back to symbols for the copilot's hold-to-talk (docs/copilot-lab.md).

Speech to text hears "NBIS" as "N-B-I-S", "en bee eye ess", "en bis" or "Nebius". This maps those back to a symbol
the app knows (Radar's universe plus every ticker the owner has traded) and nothing else: a phrase changes only when
exactly one known symbol fits it, so unclear speech stays as heard.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from sqlmodel import Session, select

DATA = Path(__file__).resolve().parents[1] / "data"

# Letter names as speech to text writes them. Common English words ("see", "you", "are", "why", "eye") count only
# inside a run of three or more, so "I see" stays a sentence.
LETTERS = {
    "a": "A", "ay": "A", "bee": "B", "be": "B", "cee": "C", "see": "C", "sea": "C", "dee": "D", "ee": "E", "ef": "F", "eff": "F",
    "gee": "G", "jee": "G", "aitch": "H", "eye": "I", "jay": "J", "kay": "K", "el": "L", "ell": "L", "em": "M", "en": "N",
    "oh": "O", "pee": "P", "pea": "P", "cue": "Q", "queue": "Q", "ar": "R", "are": "R", "ess": "S", "es": "S", "tee": "T",
    "tea": "T", "you": "U", "vee": "V", "ex": "X", "why": "Y", "zee": "Z", "zed": "Z",
}
COMMON = {"a", "be", "see", "sea", "eye", "oh", "are", "you", "why", "tea", "pea", "es", "queue", "ex"}
# First words of company names that are ordinary English; only the full name maps for these.
NAME_STOP = {"advanced", "alphabet", "amazon", "applied", "arm", "cipher", "coherent", "constellation", "core", "digital",
             "elastic", "intel", "micron", "palo", "western"}
SYMBOL = re.compile(r"[A-Z]{1,6}")
WORD = re.compile(r"[A-Za-z]+")
JOIN = re.compile(r"[\s.,-]*")  # what may sit between the letters of a spelled-out symbol


@lru_cache(maxsize=1)
def _radar() -> frozenset[str]:
    return frozenset(row["symbol"] for row in json.loads((DATA / "radar_universe.json").read_text())["symbols"])


@lru_cache(maxsize=1)
def _names() -> dict[str, str]:
    companies = json.loads((DATA / "ai_buildout_seed.json").read_text()).get("companies", {})
    return {symbol: row["name"] for symbol, row in companies.items() if row.get("name")}


def traded(db: Session) -> list[str]:
    """The owner's traded tickers, most traded first."""
    from sqlalchemy import func
    from app.models import Trade
    rows = db.exec(select(Trade.ticker, func.count()).group_by(Trade.ticker).order_by(func.count().desc())).all()
    return [t.upper() for t, _ in rows if t and SYMBOL.fullmatch(t.upper())]


def known_symbols(traded_tickers: list[str] = ()) -> frozenset[str]:
    """Radar's universe and the owner's traded tickers."""
    return frozenset(s for s in (*_radar(), *traded_tickers) if SYMBOL.fullmatch(s))


def _aliases(known: frozenset[str]) -> dict[str, str]:
    """Lowercase company names (and distinctive first words) to symbols; an ambiguous first word maps to nothing."""
    out: dict[str, str] = {}
    first: dict[str, set[str]] = {}
    for symbol, name in _names().items():
        if symbol not in known:
            continue
        words = re.findall(r"[a-z]+", name.lower())
        if not words:
            continue
        if len(words) > 1 or words[0] not in NAME_STOP:
            out[" ".join(words)] = symbol
        if len(words[0]) >= 4 and words[0] not in NAME_STOP and words[0].upper() != symbol:
            first.setdefault(words[0], set()).add(symbol)
    for word, symbols in first.items():
        if len(symbols) == 1:
            out.setdefault(word, next(iter(symbols)))
    return out


def prompt_for(known: frozenset[str], traded_first: list[str] = (), limit: int = 90) -> str:
    """Vocabulary for Whisper: the symbols it should expect to hear, the owner's most traded first (Whisper reads
    only the last couple of hundred tokens of a prompt, so the list is capped)."""
    ordered = list(dict.fromkeys([*traded_first, *sorted(known)]))
    return "Tickers: " + ", ".join(ordered[:limit]) + "."


def _letter(word: str, run: int) -> str | None:
    """A single letter or a letter's name, as that letter; a common word counts only in a run of three or more."""
    if len(word) == 1:
        # "a" and "I" are words too: "it a I think" is not AI.
        return None if word.lower() in ("a", "i") and run < 3 else word.upper()
    bare = word.lower()
    if bare in COMMON and run < 3:
        return None
    return LETTERS.get(bare)


def map_tickers(text: str, known: frozenset[str]) -> tuple[str, list[dict]]:
    """``text`` with spoken tickers written as symbols, and what changed. Unmatched speech is left exactly as heard."""
    words = [(m.start(), m.end(), m.group()) for m in WORD.finditer(text)]
    aliases = _aliases(known)
    changes: list[tuple[int, int, str]] = []

    def joined(i: int, j: int) -> bool:
        return all(JOIN.fullmatch(text[words[k][1]:words[k + 1][0]]) for k in range(i, j))

    i = 0
    while i < len(words):
        found: tuple[int, str] | None = None
        # 1. Company names, longest first ("applied digital", never "applied" alone).
        for size in (4, 3, 2, 1):
            if i + size <= len(words) and all(re.fullmatch(r"\s+", text[words[k][1]:words[k + 1][0]]) for k in range(i, i + size - 1)):
                phrase = " ".join(w[2].lower() for w in words[i:i + size])
                if phrase in aliases:
                    found = (size, aliases[phrase])
                    break
        # 2. Spelled out: "N-B-I-S", "N. B. I. S.", "en bee eye ess", or a letter and a capitalised piece ("N-BIS").
        if found is None:
            for size in range(min(6, len(words) - i), 1, -1):
                if not joined(i, i + size - 1):
                    continue
                parts = [_letter(w[2], size) or (w[2] if w[2].isupper() and len(w[2]) >= 2 else None) for w in words[i:i + size]]
                letters = sum(1 for w in words[i:i + size] if _letter(w[2], size))
                if all(parts) and letters and "".join(parts) in known:  # type: ignore[arg-type]
                    found = (size, "".join(parts))  # type: ignore[arg-type]
                    break
        # 3. A letter's name, then the rest said as a word: "en bis" is N + BIS.
        if found is None and i + 1 < len(words) and joined(i, i + 1):
            letter = _letter(words[i][2], 2) if len(words[i][2]) > 1 else None
            rest = words[i + 1][2].upper()
            for candidate in (letter + rest, letter + re.sub(r"(.)\1$", r"\1", rest)) if letter else ():
                if candidate in known:
                    found = (2, candidate)
                    break
        if found is None:
            i += 1
            continue
        size, symbol = found
        start, end = words[i][0], words[i + size - 1][1]
        if text[start:end] != symbol:
            changes.append((start, end, symbol))
        i += size
    out = text
    for start, end, symbol in reversed(changes):
        out = out[:start] + symbol + out[end:]
    return out, [{"heard": text[start:end], "symbol": symbol} for start, end, symbol in changes]
