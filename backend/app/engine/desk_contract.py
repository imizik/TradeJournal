"""A held option's own price on the desk chart (``GET /copilot/desk/contract``, docs/copilot-lab.md § The desk).

When the selected book row is a held single-leg option, the centre chart can show the contract itself instead of the
stock: its intraday price, the owner's fills on it, and (on the screen) his P&L at the cursor and the stock's price at
the same moment.

- **Where the price comes from.** Tradier's 1-minute time and sales for the OCC symbol (the trades printed on the
  contract), through the shared chart feed: its single-flight, its four places and its 60-calls-a-minute budget, the
  same read the stock chart makes for a ticker. One request covers the last few calendar days, so the latest session
  with trades is shown even before today's first one; it is kept ``LIVE_TTL`` seconds while the market can move, longer
  after. Polygon's option aggregates are end-of-day on this plan (a same-day request is refused), so they are not used.
- **Marks where trades are sparse.** A thin contract prints a few trades an hour. The desk's live prices already quote
  each held contract's mark (bid/ask midpoint) every few seconds while a desk is open (``desk_ticks``); the minutes
  they saw today come back as ``marks``, labelled as marks, never mixed into the trade candles.
- **The stock at the same moment.** The underlying's minutes for the shown day: today's from the chart feed's
  low-priority read (the same request, and cache, as the stock chart's), an earlier session's from disk.
- **Fills.** The journal's fills on this contract that belong to its open trades, and its fills on the shown day; a
  roll's derived price is left off (not a market premium). Prices are per share, as the contract is quoted.

Nothing invented: no trades and no marks is ``state`` "none", and the desk shows no Contract toggle. Display only:
nothing is written, Robinhood is never read here (the book's provisional Robinhood fills are drawn by the desk from
the order lines it already has).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

STEP = 120  # 2-minute candles, as the stock chart's 2m
LOOKBACK_DAYS = 5  # calendar days read back, so a session with trades is found across a weekend or holiday
LIVE_TTL = 55  # the desk reads again once a minute while visible; one read serves every tab
CLOSED_TTL = 1800
DENSE = 0.6  # of the 2-minute slots between the first and last trade, at least this share traded: candles, else a line
MAX_FILLS = 20
SOURCE = "Tradier time and sales (trades)"

_OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _params(occ: str, today: date) -> dict:
    """One request key for the day: the last ``LOOKBACK_DAYS`` from the open to today's 20:00 (only existing bars come back)."""
    start = today - timedelta(days=LOOKBACK_DAYS)
    return {"symbol": occ, "interval": "1min", "session_filter": "all",
            "start": start.strftime("%Y-%m-%d 09:30"), "end": today.strftime("%Y-%m-%d 20:00")}


def _ny_day(stamp: int) -> date:
    return datetime.fromtimestamp(stamp, ET).date()


def _slot(stamp: int) -> int:
    return int(stamp) - int(stamp) % STEP


def _candles(minutes: list[dict]) -> list[dict]:
    """Minute trades as 2-minute candles on the even minute (only slots with a trade)."""
    out: list[dict] = []
    for bar in minutes:
        slot = _slot(bar["time"])
        last = out[-1] if out else None
        if last is None or last["time"] != slot:
            out.append({"time": slot, "open": float(bar["open"]), "high": float(bar["high"]), "low": float(bar["low"]),
                        "close": float(bar["close"]), "volume": float(bar.get("volume") or 0)})
            continue
        last.update(high=max(last["high"], float(bar["high"])), low=min(last["low"], float(bar["low"])),
                    close=float(bar["close"]), volume=last["volume"] + float(bar.get("volume") or 0))
    return out


def style(candles: list[dict]) -> str:
    """``candles`` when trades fill at least ``DENSE`` of the 2-minute slots between the first and last; else ``line``
    (a few prints an hour drawn as candles would be a row of dashes)."""
    if len(candles) < 2:
        return "line"
    slots = (candles[-1]["time"] - candles[0]["time"]) // STEP + 1
    return "candles" if len(candles) / slots >= DENSE else "line"


def _stock_minutes(symbol: str, day: date, today: date, now: float) -> list[dict]:
    """The underlying's minute bars on ``day``: today's from the chart feed's low read (the stock chart's request), an
    earlier session's from disk or the feed's cache. Empty when none can be had; never a reason to fail the read."""
    from app.engine import desk_context
    from app.engine.chart_feed import chart_feed
    try:
        if day == today:
            return chart_feed.today_minutes(symbol, now, max_age=180)
        sessions = desk_context.stored_sessions(symbol, today, 1)
        if sessions and sessions[-1][0] == day:
            return sessions[-1][2]
        return desk_context.cached_minutes(symbol, day)
    except Exception:  # noqa: BLE001 -- the stock line in the tooltip is extra
        log.info("desk contract: %s minutes for %s unavailable", symbol, day)
        return []


def _stock(minutes: list[dict], day: date) -> list[dict]:
    """The underlying's close at the end of each 2-minute slot of ``day``."""
    out: dict[int, float] = {}
    for bar in minutes:
        stamp = int(bar["time"])
        if _ny_day(stamp) == day:
            out[_slot(stamp)] = float(bar["close"])
    return [{"time": t, "price": out[t]} for t in sorted(out)]


def fills(db: Session, symbol: str, terms: dict, day: date) -> list[dict]:
    """The journal's fills on the contract: those in its open trades, and those on ``day`` (Webull and roll prices left
    off), oldest first, each at its per-share premium."""
    from app.models import Account, Fill, Trade, TradeFill
    webull = select(Account.id).where(Account.broker == "webull")
    same = (Fill.ticker == symbol, Fill.instrument_type == "option", Fill.option_type == terms["option_type"],
            Fill.strike == terms["strike"], Fill.expiration == terms["expiration"], Fill.account_id.not_in(webull))
    open_trades = select(Trade.id).where(Trade.ticker == symbol, Trade.status == "open", Trade.account_id.not_in(webull))
    held = select(TradeFill.fill_id).where(TradeFill.trade_id.in_(open_trades))
    start = datetime.combine(day, datetime.min.time())
    rows = db.exec(select(Fill).where(*same).where(Fill.id.in_(held) | (Fill.executed_at >= start))
                   .order_by(Fill.executed_at.desc()).limit(MAX_FILLS)).all()
    out = []
    for fill in reversed(rows):
        if (fill.raw_email_id or "").startswith("roll:"):
            continue
        at = int(fill.executed_at.replace(tzinfo=ET).timestamp())
        side = "buy" if fill.side.startswith("buy") else "sell"
        contracts = float(fill.contracts)
        premium = round(float(fill.price) / 100, 4)  # the journal keeps an option fill's price per contract
        verb = "Bought" if side == "buy" else "Sold"
        out.append({"at": at, "side": side, "opening": fill.side in ("buy_to_open", "sell_to_open"), "contracts": contracts,
                    "price": premium, "provisional": False,
                    "text": f"{verb} {contracts:g} at {premium:.2f}"})
    return out


def _terms(symbol: str, occ: str) -> dict | None:
    """The OCC symbol's contract when it is ``symbol``'s (built back from its parts), else None."""
    from app.engine.occ import occ_symbol, parse_occ
    if not _TICKER.match(symbol) or not _OCC.match(occ):
        return None
    parsed = parse_occ(occ)
    if not parsed:
        return None
    if occ_symbol(symbol, parsed["expiration"], parsed["option_type"], parsed["strike"]) != occ:
        return None
    return parsed


def read(db: Session, symbol: str, occ: str, now: float) -> dict:
    """The contract's latest session with trades as 2-minute candles (``style`` says candles or a line), today's
    recorded marks, the underlying's price per slot and the owner's fills. ``state``: ok, none (nothing to draw) or
    unavailable (with ``reason``)."""
    from app.engine import desk_ticks
    from app.engine.chart_feed import ChartFeedError, _rows, chart_feed
    from app.engine.chart_math import normalize_bars
    from app.engine.chart_journal import contract_label
    from app.engine.desk_context import _live

    symbol, occ = symbol.strip().upper(), occ.strip().upper()
    today = datetime.fromtimestamp(now, ET).date()
    live = _live(now)
    base = {"symbol": symbol, "occ": occ, "label": None, "step": STEP, "as_of": int(now), "live": live, "day": None,
            "source": SOURCE, "style": "line", "bars": [], "marks": [], "stock": [], "fills": [], "stale": None, "reason": None}
    terms = _terms(symbol, occ)
    if terms is None:
        return {**base, "state": "unavailable", "reason": "That is not one of this ticker's option contracts."}
    base["label"] = contract_label(symbol, "option", terms["option_type"], terms["strike"], terms["expiration"])
    try:
        data, _fetched, issue = chart_feed.read("/v1/markets/timesales", _params(occ, today), LIVE_TTL if live else CLOSED_TTL)
    except ChartFeedError as exc:
        return {**base, "state": "unavailable", "reason": str(exc)}
    minutes = normalize_bars(_rows(data, "series", "data"))
    marks = desk_ticks.marks(occ, now)
    days = sorted({_ny_day(b["time"]) for b in minutes})
    day = today if marks else (days[-1] if days else None)  # today's marks show today even before its first trade
    if day is None:
        return {**base, "state": "none", "reason": "No trades in this contract in the last few sessions."}
    bars = _candles([b for b in minutes if _ny_day(b["time"]) == day])
    slots = {_slot(t): p for t, p in marks} if day == today else {}  # each 2-minute slot's newest mark
    shown_marks = [{"time": t, "price": slots[t]} for t in sorted(slots)]
    if not bars and not shown_marks:
        return {**base, "state": "none", "reason": "No trades in this contract in the last few sessions."}
    return {**base, "state": "ok", "day": day.isoformat(), "style": style(bars), "bars": bars, "marks": shown_marks,
            "stock": _stock(_stock_minutes(symbol, day, today, now), day), "fills": fills(db, symbol, terms, day),
            "stale": issue}
