"""External market context for the pre-trade check (advisor step 9): next earnings dates and live VIX.

Read from Tradier with the key the private backend already has, for the symbols
Isaac holds, has traded in the last 30 days or watches on Charts (up to 40), and
stored as a current snapshot in ``market_context_item``. The isolated check
service never reads this table directly: its publisher reads a narrow view of it
(``deploy/check_scope.py``). A kind whose read fails keeps its older rows and is
reported, never replaced by guesses. See docs/agent/advisor-pretrade-check-contract.md.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_
from sqlmodel import Session, select

from app.models import Account, ChartSettingsRecord, MarketContextItem, Trade

NY = ZoneInfo("America/New_York")
MAX_SYMBOLS = 40
RECENT_DAYS = 30
SOURCE = "Tradier"
# Index and fund symbols have no earnings; skipping them saves calendar reads.
NO_EARNINGS = {"SPY", "QQQ", "IWM", "DIA", "SMH", "SPX", "SPXW", "XSP", "NDX", "VIX", "TLT", "GLD", "SLV", "USO",
               "SOXL", "TQQQ", "SQQQ"}


def tracked_symbols(session: Session, today: date) -> list[str]:
    """Held now, then traded in the last 30 days (most recent first), then the Charts watchlist; Webull excluded."""
    not_webull = or_(Account.broker.is_(None), Account.broker != "webull")  # Dormant by the owner's choice.
    held = session.exec(select(Trade.ticker).join(Account, Account.id == Trade.account_id)
                        .where(Trade.status == "open").where(not_webull)).all()
    since = datetime.combine(today - timedelta(days=RECENT_DAYS), datetime.min.time())
    recent = session.exec(select(Trade.ticker).join(Account, Account.id == Trade.account_id)
                          .where(Trade.opened_at >= since).where(not_webull)
                          .order_by(Trade.opened_at.desc())).all()
    settings = session.get(ChartSettingsRecord, "default")
    try:
        watchlist = json.loads(settings.data_json).get("watchlist") if settings else None
    except (ValueError, AttributeError):
        watchlist = None
    watched = [name for name in watchlist if isinstance(name, str)] if isinstance(watchlist, list) else []
    names = [str(name or "").strip().upper() for name in [*held, *recent, *watched]]
    return [name for name in dict.fromkeys(names) if name and name.isascii() and len(name) <= 6][:MAX_SYMBOLS]


def _earnings_rows(symbols: list[str], today: date, facts: Callable[[list[str], date], dict],
                   fetched: datetime) -> tuple[Optional[list[MarketContextItem]], Optional[str]]:
    wanted = [symbol for symbol in symbols if symbol not in NO_EARNINGS]
    if not wanted:
        return [], None
    try:
        found = facts(wanted, today)
    except Exception as exc:  # A provider error keeps the older rows; it is reported, not raised.
        return None, f"earnings calendar unavailable ({type(exc).__name__})"
    rows, problems, stale = [], [], 0
    for symbol in wanted:
        earnings = (found.get(symbol) or {}).get("earnings") or {}
        if earnings.get("state") == "unavailable":
            problems.append(earnings.get("message") or "unavailable")
            continue
        if earnings.get("message"):
            stale += 1  # Served from an older cached calendar after a failed read.
        read_at = earnings.get("fetched_at")
        upcoming = earnings.get("next")
        if upcoming:
            rows.append(MarketContextItem(kind="earnings", symbol=symbol, event_date=date.fromisoformat(upcoming["date"]),
                                          status=upcoming.get("status"), label=upcoming.get("label"),
                                          fetched_at=(datetime.fromtimestamp(read_at, timezone.utc).replace(tzinfo=None)
                                                      if read_at else fetched), source=SOURCE))
    if problems and len(problems) == len(wanted):
        return None, f"earnings calendar unavailable ({problems[0]})"  # Keep the older rows.
    notes = [f"earnings missing for {len(problems)} of {len(wanted)} symbols"] if problems else []
    if stale:
        notes.append(f"earnings for {stale} symbols from an older cached calendar (refresh failed)")
    return rows, "; ".join(notes) or None


def _vix_rows(quotes: Callable[[list[str]], dict], fetched: datetime) -> tuple[Optional[list[MarketContextItem]], Optional[str]]:
    try:
        quote = quotes(["VIX"]).get("VIX")
    except Exception as exc:  # One provider error must not discard the earnings read or fail the job.
        return None, f"VIX quote unavailable ({type(exc).__name__})"
    last = getattr(quote, "last", None)
    if not last:
        return None, "VIX quote unavailable"
    raw = getattr(quote, "raw", None) or {}
    try:
        previous = float(raw.get("prevclose")) if raw.get("prevclose") is not None else None
    except (TypeError, ValueError):
        previous = None
    stamp = getattr(quote, "trade_date", None)  # Tradier milliseconds.
    observed = datetime.fromtimestamp(stamp / 1000, timezone.utc).replace(tzinfo=None) if stamp else None
    return [MarketContextItem(kind="vix", symbol="VIX", value=float(last),
                              change_pct=round((last - previous) / previous * 100, 2) if previous else None,
                              observed_at=observed, fetched_at=fetched, source=SOURCE)], None


def refresh(session: Session, today: Optional[date] = None, *, facts=None, quotes=None,
            clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> tuple[int, str]:
    """Replace the earnings and VIX snapshot. Returns (rows written, summary) for the job runner."""
    if facts is None or quotes is None:
        from app.engine import symbol_info_tradier, tradier

        if not tradier.tradier_configured():
            raise RuntimeError("Set TRADIER_API_KEY on the private backend to read earnings and VIX")
        facts = facts or symbol_info_tradier.symbol_events.review_facts
        quotes = quotes or tradier.get_quotes
    today = today or clock().astimezone(NY).date()
    fetched = clock().astimezone(timezone.utc).replace(tzinfo=None)
    symbols = tracked_symbols(session, today)
    notes, written = [], 0
    for kind, (rows, note) in (("earnings", _earnings_rows(symbols, today, facts, fetched)),
                               ("vix", _vix_rows(quotes, fetched))):
        if note:
            notes.append(note)
        if rows is None:
            continue
        session.exec(delete(MarketContextItem).where(MarketContextItem.kind == kind))
        session.add_all(rows)
        written += len(rows)
    session.commit()
    summary = f"{written} rows for {len(symbols)} symbols" + (f"; {'; '.join(notes)}" if notes else "")
    return written, summary
