"""Today's setup-scanner candidates on the copilot desk (docs/copilot-lab.md § Scanner on the desk).

Display only. The scanner's rules, scoring, schedule and records are untouched: this reads the ``ScannerCandidate`` rows
and their events the scanner already saved (``setup_scanner``), as the Scanner page does, and adds nothing to them.
No provider call, no Robinhood, no ping, no write.

- **Which rows.** Today's candidates (New York date), newest bar first, without a ticker he set to Not following
  (hidden stays silent). When that setting cannot be read nothing is shown.
- **New to him.** A candidate on a name he neither holds (open journal trades, Webull left out), watches (``desk_watch``)
  nor has a live plan on is marked ``new``; that is the point of showing it. When his book cannot be read nothing is
  marked new rather than guessing.
- **Radar too.** A candidate on the same name and day, in the same direction, as a Radar setup card carries that card
  (``radar``) so the desk shows it once, with the card's own Plan it.
- **Freshness.** ``monitoring`` is the Scanner page's own read of the running scanner (``routers/scanner._monitoring``),
  passed in by the route.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
import logging
from urllib.parse import urlencode

from sqlmodel import Session, col, select

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

MAX_ROWS = 20
SETUP_WORDS = {("orb", "long"): "Opening-range break (long)", ("orb", "short"): "Opening-range break (short)",
               ("fade", "long"): "VWAP fade (long)", ("fade", "short"): "VWAP fade (short)"}
RADAR_DIRECTION = {"long": "up", "short": "down"}


def _iso(moment: datetime | None) -> str | None:
    return moment.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if moment else None


def _number(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN is no level


def _contract_line(contract: dict | None) -> str | None:
    """The Scanner page's contract words: ``11-14 95C · Δ0.45``."""
    if not contract:
        return None
    try:
        letter = "C" if contract["option_type"] == "call" else "P"
        strike = float(contract["strike"])
        return f"{contract['expiration'][5:]} {strike:g}{letter} · Δ{abs(float(contract['delta'])):.2f}"
    except (KeyError, TypeError, ValueError):
        return None


def _followed(db: Session) -> set[str] | None:
    """Names he already follows: held, watched or planned. None when they cannot be read (then nothing is marked new)."""
    from app.engine import desk_feed, desk_watch
    try:
        book = desk_feed._book(db)
        return set(book["held"]) | set(book["plans"]) | set(desk_watch.state(db)["symbols"])
    except Exception:  # noqa: BLE001 -- unknown book: mark nothing new rather than guess
        log.warning("Desk scanner: held/watched names could not be read", exc_info=True)
        db.rollback()
        return None


def _radar_cards(db: Session, day: date) -> dict[tuple[str, str], dict]:
    """Today's Radar setup cards by (symbol, direction), newest first wins, as the Feed's Radar setup card shows them."""
    from app.engine import desk_radar_setups
    from app.models import RadarSetup
    out: dict[tuple[str, str], dict] = {}
    for row in db.exec(select(RadarSetup).where(RadarSetup.session_date == day.isoformat())
                       .order_by(col(RadarSetup.created_at).desc())).all():
        if (row.symbol, row.direction) in out:
            continue
        card = desk_radar_setups.view(db, row)
        out[(row.symbol, row.direction)] = {
            "id": card["id"], "event_id": row.event_id, "words": card["words"], "levels_line": card["levels_line"],
            "plan_state": card["plan_state"], "investigation_id": card["investigation_id"],
            "href": f"/copilot-lab?{urlencode({'symbol': row.symbol, 'radar': row.event_id})}",
        }
    return out


def row_view(candidate, state: dict, *, new: bool, radar: dict | None) -> dict:
    """One candidate as the desk shows it: the levels the scanner saved and its rules paper result."""
    from app.engine.setup_scanner import status_of
    facts = json.loads(candidate.facts_json or "{}")
    contract = json.loads(candidate.contract_json) if candidate.contract_json else None
    exit_ = state.get("exit")
    return {
        "id": str(candidate.id), "symbol": candidate.symbol, "setup": candidate.setup, "direction": candidate.direction,
        "words": SETUP_WORDS.get((candidate.setup, candidate.direction), candidate.setup),
        "bar_end": _iso(candidate.bar_end), "trigger": _number(facts.get("close")),
        "stop": candidate.stop, "target": candidate.target, "vwap": _number(facts.get("vwap")),
        "range_high": _number(facts.get("opening_range_high")), "range_low": _number(facts.get("opening_range_low")),
        "flags": json.loads(candidate.flags_json or "[]"), "contract_line": _contract_line(contract),
        "status": status_of(candidate, state),
        "pnl": exit_.get("pnl") if exit_ else None, "exit_reason": exit_.get("reason") if exit_ else None,
        "new": new, "radar": radar,
    }


def _base(state: str, monitoring: dict | None, **more) -> dict:
    return {"state": state, "day": None, "monitoring": monitoring, "rows": [], "message": None, "simulated": False, **more}


def view(db: Session, monitoring: dict | None, now: float, *, mode: str = "live") -> dict:
    """What ``GET /copilot/scanner`` returns."""
    from app.engine import day_journal
    from app.engine.setup_scanner import SetupScanner, enabled, fold
    from app.models import ScannerCandidate
    if mode == "fixture":
        return _fixture(db, now)
    if mode == "replay":
        return _base("unavailable", monitoring, message="Replay shows no live scanner setups.")
    if not enabled():
        return _base("off", monitoring)
    day = datetime.fromtimestamp(now, ET).date()
    try:
        hidden = day_journal.not_following(db)
    except Exception:  # noqa: BLE001 -- not knowing what is hidden, show nothing rather than a hidden ticker
        log.warning("Desk scanner: not-followed tickers could not be read", exc_info=True)
        db.rollback()
        return _base("unavailable", monitoring, day=day.isoformat(),
                     message="Which tickers you follow could not be read, so nothing is shown.")
    found = [c for c in db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date == day)
                                .order_by(col(ScannerCandidate.bar_end).desc())).all() if c.symbol not in hidden]
    followed = _followed(db) if found else set()
    radar = _radar_cards(db, day) if found else {}
    rows = [row_view(c, fold(SetupScanner._events(db, c.id)),
                     new=followed is not None and c.symbol not in followed,
                     radar=radar.get((c.symbol, RADAR_DIRECTION.get(c.direction, ""))))
            for c in found[:MAX_ROWS]]
    return _base("ok", monitoring, day=day.isoformat(), rows=rows)


def _fixture(db: Session, now: float) -> dict:
    """SIMULATED (sandbox only): two invented candidates, NBIS (the copilot fixture's held name) and CRWV (not followed
    yet), on the fixture session. Hidden names stay out as in the live view."""
    from app.ai.copilot_fixture import AT, SESSION
    from app.engine import day_journal
    at = datetime.fromisoformat(AT.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)
    monitoring = {"state": "fresh", "checked_at": _iso(at), "last_judged_bar_end": _iso(at), "symbols_judged": 12,
                  "symbols_selected": 12}
    invented = [
        {"id": "fixture-nbis", "symbol": "NBIS", "setup": "orb", "direction": "long", "trigger": 94.12, "stop": 93.18,
         "target": 96.0, "vwap": 93.6, "range_high": 94.05, "range_low": 92.9, "contract_line": "11-21 95C · Δ0.46",
         "status": "open", "pnl": None, "exit_reason": None, "new": False},
        {"id": "fixture-crwv", "symbol": "CRWV", "setup": "fade", "direction": "short", "trigger": 52.4, "stop": 53.15,
         "target": 51.3, "vwap": 51.8, "range_high": 53.0, "range_low": 51.6, "contract_line": "11-21 52P · Δ0.41",
         "status": "exit", "pnl": 42.0, "exit_reason": "target", "new": True, "minutes": 25},
    ]
    try:
        hidden = day_journal.not_following(db)
    except Exception:  # noqa: BLE001 -- as live: not knowing what is hidden, show nothing
        db.rollback()
        return _base("unavailable", monitoring, message="Which tickers you follow could not be read, so nothing is shown.")
    rows = [{**{k: v for k, v in r.items() if k != "minutes"}, "words": SETUP_WORDS[(r["setup"], r["direction"])],
             "bar_end": _iso(at - timedelta(minutes=r.get("minutes", 0))), "flags": [], "radar": None}
            for r in invented if r["symbol"] not in hidden]
    return _base("ok", monitoring, day=SESSION, rows=rows, simulated=True)
