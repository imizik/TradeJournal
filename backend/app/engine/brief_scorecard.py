"""The brief scorecard: did the copilot's 09:00 morning brief name the day's movers (docs/copilot-lab.md § The brief
scorecard)?

For each morning brief (one ``PremarketPrep`` row with its saved investigation) in the last days: the distinct known
symbols its answer text names as whole uppercase tokens, and how many of them moved 3+ points against SPY over that
day's regular session. Known symbols are the journal's traded tickers, Radar's universe (``spoken_tickers``) and the
brief's backdrop ETFs. Bars come from storage only (the day replay's readers); a symbol without both endpoints is
unknown and is counted as named, never as moved. A token match, not the manual audit of
``research/notes/morning-brief-scorecard.md``. Counts only: no symbol or brief text leaves the server, nothing is
written, no model is called.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import logging
import re
import threading
import uuid

from sqlmodel import Session, select

from app.engine.chart_math import ET, session_windows

log = logging.getLogger(__name__)

HIT_PP = 3.0
MAX_ROWS = 30
# All-caps words in brief text that are not tickers here, even where a known symbol shares the letters.
STOP = frozenset({"A", "I", "AI", "AM", "PM", "ET", "CPI", "PPI", "PCE", "GDP", "PMI", "NFP", "FOMC", "EPS", "IV", "DTE",
                  "ATM", "OTM", "ITM", "VWAP", "ORB", "ETF", "USD", "US", "MA", "EMA", "SMA", "RSI", "ATH", "YTD", "HOD",
                  "LOD", "IPO", "CEO", "OK", "PT"})
# A whole token: not part of a word or number, "S&P" or "U.S."; a leading "$" is allowed.
TOKEN = re.compile(r"(?<![\w&.$])\$?([A-Z]{1,6})(?![\w&]|\.[A-Za-z])")

_cache: dict[tuple[date, str], dict] = {}
_lock = threading.Lock()


def named(text: str, known: frozenset[str]) -> list[str]:
    """The distinct known symbols in ``text`` as whole uppercase tokens, in first-seen order."""
    seen: dict[str, None] = {}
    for match in TOKEN.finditer(text or ""):
        symbol = match.group(1)
        if symbol in known and symbol not in STOP:
            seen.setdefault(symbol, None)
    return list(seen)


def _regular(day: date) -> tuple[int, int]:
    """The regular session's start and end in epoch seconds (the clock hours; no calendar read)."""
    window = next((w for w in session_windows(day) if w[0] == "regular"), ("regular", 570, 960))
    midnight = int(datetime(day.year, day.month, day.day, tzinfo=ET).timestamp())
    return midnight + window[1] * 60, midnight + window[2] * 60


def session_return(bars: list[dict], day: date) -> float | None:
    """The 09:30 minute's open to the last regular minute's close so far; None without the 09:30 minute (no
    fill-forward)."""
    start, end = _regular(day)
    regular = [b for b in bars if start <= b.get("time", -1) < end]
    if not regular or regular[0]["time"] != start or not regular[0].get("open"):
        return None
    return regular[-1]["close"] / regular[0]["open"] - 1


def excess_pp(symbol_return: float | None, spy_return: float | None) -> float | None:
    """100 × (symbol return − SPY return): a difference in percentage points; None when either is unknown."""
    if symbol_return is None or spy_return is None:
        return None
    return 100 * (symbol_return - spy_return)


def _bars(symbol: str, day: date, today: date) -> list[dict]:
    """Storage only, as the day replay reads: the stored session, else (today) the chart feed's cached minutes."""
    from app.engine import ping_images
    stored = ping_images.stored_bars(symbol, day)
    if stored:
        return stored
    return ping_images.today_bars(symbol) if day == today else []


def score(symbols: list[str], day: date, now_et: datetime) -> dict:
    """One brief's counts: named, moved (|excess| >= 3 pp), unknown, and its state."""
    today = now_et.date()
    spy = session_return(_bars("SPY", day, today), day)
    moved = unknown = 0
    for symbol in symbols:
        if symbol == "SPY":
            excess = 0.0 if spy is not None else None
        else:
            excess = excess_pp(session_return(_bars(symbol, day, today), day), spy) if spy is not None else None
        if excess is None:
            unknown += 1
        elif abs(excess) >= HIT_PP:
            moved += 1
    if day == today and now_et.timestamp() < _regular(day)[1]:
        state = "in_progress"
    elif symbols and unknown == len(symbols):
        state = "no_bars"
    else:
        state = "ok"
    return {"day": day.isoformat(), "named": len(symbols), "moved": moved, "unknown": unknown, "state": state}


def _known(db: Session) -> frozenset[str]:
    from app.engine import spoken_tickers
    from app.engine.jo_morning_market import BACKDROP
    return spoken_tickers.known_symbols(spoken_tickers.traded(db)) | frozenset(BACKDROP)


def _text(transcript_json: str) -> str:
    """The brief's answer lines: assistant messages only (the question carries the whole pack)."""
    messages = json.loads(transcript_json or "[]")
    return "\n".join(str(m.get("content") or "") for m in messages if isinstance(m, dict) and m.get("role") == "assistant")


def _briefs(db: Session, since: date, until: date) -> list[tuple[date, str, str]]:
    """(day, brief id, transcript) for each prep in the window with a saved investigation, newest first."""
    from app.models import CopilotInvestigation, PremarketPrep
    rows = db.exec(select(PremarketPrep.day, PremarketPrep.investigation_id).where(
        PremarketPrep.day >= since, PremarketPrep.day <= until, PremarketPrep.investigation_id.is_not(None))
        .order_by(PremarketPrep.day.desc()).limit(MAX_ROWS)).all()
    out = []
    for day, investigation_id in rows:
        try:
            saved = db.get(CopilotInvestigation, uuid.UUID(str(investigation_id)))
        except ValueError:
            saved = None
        if saved is not None:
            out.append((day, str(investigation_id), saved.transcript_json))
    return out


def brief_scorecard(db: Session, now_et: datetime, days: int = 7) -> dict:
    """The last ``days`` New York days' morning briefs, newest first, with pooled totals. A finished day's row is cached
    in process by (day, brief id) once all its symbols had bars, so a second read costs nothing."""
    today = now_et.date()
    out: dict = {"days": days, "as_of": now_et.isoformat(timespec="seconds")}
    try:
        briefs = _briefs(db, today - timedelta(days=days - 1), today)
        known = _known(db) if briefs else frozenset()
    except Exception as exc:  # noqa: BLE001 - an unreadable store marks the card unavailable, not the desk
        db.rollback()
        log.warning("brief scorecard unavailable: %s", type(exc).__name__)
        return {**out, "state": "unavailable"}
    rows = []
    for day, brief_id, transcript in briefs:
        key = (day, brief_id)
        with _lock:
            cached = _cache.get(key)
        if cached is not None:
            rows.append(cached)
            continue
        try:
            row = score(named(_text(transcript), known), day, now_et)
        except Exception as exc:  # noqa: BLE001 - one brief's failure marks that row only
            log.warning("brief scorecard row %s unavailable: %s", day, type(exc).__name__)
            rows.append({"day": day.isoformat(), "state": "unavailable"})
            continue
        if day < today and row["unknown"] == 0:
            with _lock:
                _cache[key] = row
        rows.append(row)
    scored = [r for r in rows if "named" in r]
    return {**out, "state": "ok", "briefs": len(rows), "named": sum(r["named"] for r in scored),
            "moved": sum(r["moved"] for r in scored), "unknown": sum(r["unknown"] for r in scored), "rows": rows}
