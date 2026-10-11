"""What else the Daily Review coach sees about a day, beyond the trades themselves.

Each part is read on its own and degrades on its own: a part that fails or has
no data is left out and named in ``gaps``, never guessed. Everything is as of
the review day except the saved chart levels, which are the trader's current
levels (they may have been added or moved since) and are labelled so.

- ``plans``: the plans the trader captured (Charts C3.5) for each trade, with
  their notes and transcript, and the day's plans that were never traded.
- ``tags``: the trader's tags on each trade.
- ``market``: SPY, QQQ, IWM and SMH that day (change, gap, where they closed in
  their range, range against their 20-day normal), SPY's and QQQ's intraday
  shape, VIX and the 10-year yield.
- ``tickers``: for each traded underlying, its move against the market and its
  sector ETF, earnings within a week either side, the day's headlines, its
  option open-interest walls and the trader's levels and alerts that fired.
- ``macro``: scheduled FOMC, CPI and jobs releases that day and the next
  (``app/data/macro_calendar.json``).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import json
import logging
from pathlib import Path
from statistics import mean
from typing import Callable
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models import (CaptureLink, ChartSettingsRecord, Fill, LevelAlert, LevelAlertEvent, OptionChainSnapshot, Tag,
                        Trade, TradeCapture, TradeCaptureNote, TradeFill, TradeTag)

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
MARKET = ("SPY", "QQQ", "IWM", "SMH")
INTRADAY = ("SPY", "QQQ")
MACRO_FILE = Path(__file__).resolve().parents[1] / "data" / "macro_calendar.json"
HEADLINES = 5
EARNINGS_WINDOW = 7
WALL_BAND = 0.12  # strikes within 12% of the price
# Semiconductors trade with SMH more than with their Morningstar sector's ETF.
SEMIS = {"NVDA", "AMD", "AVGO", "MU", "INTC", "QCOM", "TSM", "ARM", "MRVL", "SMCI", "AMAT", "LRCX", "KLAC", "TXN", "ON",
         "MCHP", "ADI", "NXPI", "ASML", "SNDK", "WDC", "STX", "ALAB", "CRDO", "COHR", "MPWR", "TER", "ENTG", "GFS", "SWKS"}
SECTOR_ETF = {"Technology": "XLK", "Communication Services": "XLC", "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
              "Energy": "XLE", "Financial Services": "XLF", "Healthcare": "XLV", "Industrials": "XLI", "Basic Materials": "XLB",
              "Real Estate": "XLRE", "Utilities": "XLU"}
FUNDS = {"SPY", "QQQ", "IWM", "DIA", "SMH", "SPX", "SPXW", "XSP", "NDX", "VIX", "TLT", "GLD", "SLV", "USO", "SOXL", "TQQQ", "SQQQ"}


def build(session: Session, day: date, trades: list[Trade]) -> dict:
    """The extra context for one review day. Never raises: what fails is named in ``gaps``."""
    gaps: list[str] = []
    underlyings = sorted({trade.ticker.upper() for trade in trades})
    context: dict = {"gaps": gaps}

    def part(name: str, read: Callable[[], object], gap: str) -> object | None:
        try:
            value = read()
        except Exception as exc:  # one source failing must not cost the review
            log.warning("Review context %s failed for %s", name, day, exc_info=True)
            gaps.append(f"{gap} ({type(exc).__name__})")
            return None
        if value in (None, {}, []):
            gaps.append(gap)
            return None
        return value

    context["plans"] = part("plans", lambda: plans(session, day, trades), "No captured trade plans for this day")
    context["tags"] = part("tags", lambda: tags(session, trades), "No tags on these trades")
    daily = part("daily bars", lambda: daily_moves(day, [*MARKET, *underlyings, *sector_etfs(underlyings).values()]),
                 "Daily bars unavailable, so market and relative moves are unknown") or {}
    context["market"] = {
        "indexes": {symbol: daily[symbol] for symbol in MARKET if symbol in daily} or None,
        "intraday": part("intraday", lambda: intraday_shape(day), "SPY/QQQ minute bars unavailable, so the market's intraday shape is unknown"),
        "volatility": part("vix", lambda: gauges(day), "VIX and 10-year yield unavailable"),
    }
    context["macro"] = part("macro", lambda: macro_events(day), "Macro calendar unavailable for this day")
    context["tickers"] = part("tickers", lambda: ticker_context(session, day, underlyings, daily, gaps), "No per-ticker context")
    return context


# ---------------------------------------------------------------- the trader's own records

def _ny(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).astimezone(ET).strftime("%Y-%m-%d %H:%M")


def plans(session: Session, day: date, trades: list[Trade]) -> dict:
    """Captured plans linked to each trade (by its fills' source identities), and the day's plans never traded."""
    trade_ids = [trade.id for trade in trades]
    keys = session.exec(select(TradeFill.trade_id, Fill.raw_email_id, Fill.account_id)
                        .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id.in_(trade_ids))).all() if trade_ids else []
    by_key = {(raw, account): trade_id for trade_id, raw, account in keys}
    links = session.exec(select(CaptureLink).where(CaptureLink.unlinked_at.is_(None),
                                                   CaptureLink.source_key.in_({raw for _, raw, _ in keys}))).all() if keys else []
    linked: dict = {}
    for link in links:
        trade_id = by_key.get((link.source_key, link.account_id))
        if trade_id:
            linked[link.capture_id] = trade_id
    start = datetime.combine(day, time.min, ET).astimezone(timezone.utc).replace(tzinfo=None)
    end = start + timedelta(days=1)
    captures = session.exec(select(TradeCapture).where(
        (TradeCapture.id.in_(list(linked))) | ((TradeCapture.received_at >= start) & (TradeCapture.received_at < end)))).all()
    if not captures:
        return {}
    notes: dict = defaultdict(list)
    for note in session.exec(select(TradeCaptureNote).where(TradeCaptureNote.capture_id.in_([c.id for c in captures]))
                             .order_by(TradeCaptureNote.created_at)).all():
        notes[note.capture_id].append(note.text)
    opened = {trade.id: trade.opened_at for trade in trades}
    by_trade: dict[str, list] = defaultdict(list)
    untraded = []
    for capture in sorted(captures, key=lambda c: c.received_at):
        row = {
            "captured_at": _ny(capture.received_at), "underlying": capture.underlying, "side": capture.side,
            "setup": capture.setup_label, "plan": capture.wording or capture.note, "note": capture.note if capture.wording else None,
            "strike": capture.strike, "expiration": capture.expiration.isoformat() if capture.expiration else None,
            "quantity": capture.quantity, "voice_transcript": capture.transcript_text, "later_notes": notes.get(capture.id) or None,
            "marked_not_taken": capture.not_taken_at is not None,
        }
        trade_id = linked.get(capture.id)
        if trade_id:
            entry = opened.get(trade_id)
            if entry:
                captured = capture.received_at.replace(tzinfo=timezone.utc).astimezone(ET).replace(tzinfo=None)
                row["minutes_before_entry"] = round((entry - captured).total_seconds() / 60)
            by_trade[str(trade_id)].append({key: value for key, value in row.items() if value not in (None, False)})
        else:
            untraded.append({key: value for key, value in row.items() if value not in (None, False)})
    return {key: value for key, value in {"by_trade": dict(by_trade), "not_traded": untraded}.items() if value}


def tags(session: Session, trades: list[Trade]) -> dict:
    ids = [trade.id for trade in trades]
    rows = session.exec(select(TradeTag.trade_id, Tag.name).join(Tag, Tag.id == TradeTag.tag_id).where(TradeTag.trade_id.in_(ids))).all() if ids else []
    found: dict[str, list[str]] = defaultdict(list)
    for trade_id, name in rows:
        found[str(trade_id)].append(name)
    return dict(found)


def saved_levels(session: Session, symbols: list[str]) -> dict[str, list[dict]]:
    record = session.get(ChartSettingsRecord, "default")
    if record is None:
        return {}
    try:
        levels = json.loads(record.data_json).get("levels") or {}
    except ValueError:
        return {}
    out = {}
    for symbol in symbols:
        rows = [{"price": level.get("price"), "label": level.get("label") or None} for level in levels.get(symbol) or []
                if isinstance(level, dict) and isinstance(level.get("price"), (int, float))]
        if rows:
            out[symbol] = sorted(rows, key=lambda row: row["price"])
    return out


def fired_alerts(session: Session, day: date, symbols: list[str]) -> dict[str, list[dict]]:
    start = datetime.combine(day, time.min, ET).astimezone(timezone.utc).replace(tzinfo=None)
    rows = session.exec(select(LevelAlert.symbol, LevelAlert.label, LevelAlert.condition, LevelAlert.direction, LevelAlertEvent.level,
                               LevelAlertEvent.price, LevelAlertEvent.event_at)
                        .join(LevelAlertEvent, LevelAlertEvent.alert_id == LevelAlert.id)
                        .where(LevelAlert.symbol.in_(symbols), LevelAlertEvent.event_at >= start,
                               LevelAlertEvent.event_at < start + timedelta(days=1))).all() if symbols else []
    out: dict[str, list[dict]] = defaultdict(list)
    for symbol, label, condition, direction, level, price, event_at in sorted(rows, key=lambda row: row[-1]):
        out[symbol].append({"at": _ny(event_at)[-5:], "level": level, "price": price, "label": label or None,
                            "condition": f"{condition} {direction}"})
    return dict(out)


def open_interest_walls(session: Session, day: date, symbol: str, spot: float | None) -> dict | None:
    """The biggest call and put open-interest strikes near the price, from the latest snapshot on or before the day."""
    latest = session.exec(select(OptionChainSnapshot.session_date).where(OptionChainSnapshot.underlying == symbol,
                                                                         OptionChainSnapshot.session_date <= day)
                          .order_by(OptionChainSnapshot.session_date.desc()).limit(1)).first()
    if latest is None or not spot:
        return None
    totals: dict[tuple[str, float], int] = defaultdict(int)
    for snapshot in session.exec(select(OptionChainSnapshot).where(OptionChainSnapshot.underlying == symbol,
                                                                   OptionChainSnapshot.session_date == latest,
                                                                   OptionChainSnapshot.expiration >= day,
                                                                   OptionChainSnapshot.expiration <= day + timedelta(days=45))).all():
        try:
            payload = json.loads(snapshot.data_json)
            columns = payload["columns"]
            side_at, strike_at, oi_at = columns.index("type"), columns.index("strike"), columns.index("open_interest")
        except (KeyError, ValueError, TypeError):
            continue
        for row in payload["rows"]:
            strike, oi = row[strike_at], row[oi_at]
            if oi and abs(float(strike) / spot - 1) <= WALL_BAND:
                totals[(row[side_at], float(strike))] += int(oi)
    if not totals:
        return None
    top = lambda side: [{"strike": strike, "open_interest": oi} for (kind, strike), oi in  # noqa: E731
                        sorted(totals.items(), key=lambda item: -item[1]) if kind == side][:3]
    calls, puts = sum(oi for (kind, _), oi in totals.items() if kind == "call"), sum(oi for (kind, _), oi in totals.items() if kind == "put")
    return {"as_of_session": latest.isoformat(), "expirations": "next 45 days", "call_walls": top("call"), "put_walls": top("put"),
            "put_call_oi": round(puts / calls, 2) if calls else None}


# ---------------------------------------------------------------- market

def daily_moves(day: date, symbols: list[str]) -> dict[str, dict]:
    """Each symbol's day from daily bars: change, gap, close position in its range, and range against its 20-day normal."""
    from app.engine import alpaca

    bars = alpaca.fetch_daily_bars(sorted(set(symbols)), day - timedelta(days=45), day)
    out = {}
    for symbol, rows in bars.items():
        dated = [(alpaca._bar_et_date(bar), bar) for bar in rows]
        dated = [(when, bar) for when, bar in dated if when and when <= day]
        if not dated or dated[-1][0] != day or len(dated) < 2:
            continue
        today, before = dated[-1][1], dated[-2][1]
        high, low, close, open_, prev = today["h"], today["l"], today["c"], today["o"], before["c"]
        ranges = [(bar["h"] - bar["l"]) / bar["c"] for _, bar in dated[-21:-1] if bar.get("c")]
        out[symbol] = {
            "change_pct": round((close / prev - 1) * 100, 2), "gap_pct": round((open_ / prev - 1) * 100, 2),
            "open_to_close_pct": round((close / open_ - 1) * 100, 2),
            "close_in_range": round((close - low) / (high - low), 2) if high > low else None,
            "range_vs_20d": round(((high - low) / close) / mean(ranges), 2) if ranges else None,
            "close": round(close, 2),
        }
    return out


def intraday_shape(day: date) -> dict:
    """SPY's and QQQ's session from completed minute bars: trend or chop, VWAP, and when the high and low printed."""
    from app.engine import alpaca

    bars = alpaca.fetch_minute_bars_for_date(list(INTRADAY), day)
    out = {}
    for symbol, rows in bars.items():
        session = []
        for bar in rows:
            when = datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).astimezone(ET)
            if time(9, 30) <= when.time() < time(16, 0):
                session.append((when, bar))
        if len(session) < 30:
            continue
        closes = [bar["c"] for _, bar in session]
        path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
        volume = sum(bar["v"] for _, bar in session)
        vwap = sum(bar.get("vw", bar["c"]) * bar["v"] for _, bar in session) / volume if volume else None
        high = max(session, key=lambda item: item[1]["h"])
        low = min(session, key=lambda item: item[1]["l"])
        first_hour = [bar for when, bar in session if when.time() < time(10, 30)]
        whole = high[1]["h"] - low[1]["l"]
        out[symbol] = {
            # 1 is a straight line open to close; near 0 is chop that went nowhere.
            "trend_efficiency": round(abs(closes[-1] - session[0][1]["o"]) / path, 2) if path else None,
            "close_vs_vwap_pct": round((closes[-1] / vwap - 1) * 100, 2) if vwap else None,
            "high_at": high[0].strftime("%H:%M"), "low_at": low[0].strftime("%H:%M"),
            "first_hour_share_of_range": round((max(b["h"] for b in first_hour) - min(b["l"] for b in first_hour)) / whole, 2)
            if first_hour and whole else None,
        }
    return out


def gauges(day: date) -> dict:
    """VIX and the 10-year yield (^TNX, percent) that day and their change, from yfinance (unofficial)."""
    import yfinance as yf

    out = {}
    for symbol, name in (("^VIX", "vix"), ("^TNX", "ten_year_yield")):
        history = yf.Ticker(symbol).history(start=(day - timedelta(days=10)).isoformat(), end=(day + timedelta(days=1)).isoformat(),
                                            interval="1d", auto_adjust=False)
        closes = [(index.date(), float(value)) for index, value in history["Close"].dropna().items()]
        closes = [item for item in closes if item[0] <= day]
        if len(closes) >= 2 and closes[-1][0] == day:
            out[name] = {"close": round(closes[-1][1], 2), "change": round(closes[-1][1] - closes[-2][1], 2)}
    if out:
        out["source"] = "yfinance (unofficial)"
    return out


def macro_events(day: date) -> dict:
    calendar = json.loads(MACRO_FILE.read_text())
    if day.isoformat() > calendar["covers_through"]:
        raise LookupError("the macro calendar does not cover this day")
    window = {day.isoformat(): "today", (day + timedelta(days=1)).isoformat(): "next day"}
    events = [{"when": window[event["date"]], "time_et": event["time"], "event": event["name"], "kind": event["kind"]}
              for event in calendar["events"] if event["date"] in window]
    return {"events": events, "calendar": "FOMC, CPI and jobs reports only"}


# ---------------------------------------------------------------- per ticker

def sector_etfs(symbols: list[str]) -> dict[str, str]:
    out = {}
    for symbol in symbols:
        if symbol in FUNDS:
            continue
        if symbol in SEMIS:
            out[symbol] = "SMH"
            continue
        try:
            from app.engine import symbol_info_tradier

            sector = symbol_info_tradier.symbol_events.overview(symbol).get("datasets", {}).get("company", {}).get("sector")
        except Exception:
            sector = None
        if sector in SECTOR_ETF:
            out[symbol] = SECTOR_ETF[sector]
    return out


def ticker_context(session: Session, day: date, symbols: list[str], daily: dict, gaps: list[str]) -> dict:
    sectors = sector_etfs(symbols)
    news = _headlines(day, [symbol for symbol in symbols if symbol not in FUNDS], gaps)
    levels = saved_levels(session, symbols)
    alerts = fired_alerts(session, day, symbols)
    out = {}
    for symbol in symbols:
        row: dict = {}
        move = daily.get(symbol)
        if move:
            row["day"] = move
            spy = daily.get("SPY")
            if spy:
                row["vs_spy_pct"] = round(move["change_pct"] - spy["change_pct"], 2)
            etf = sectors.get(symbol)
            if etf and daily.get(etf):
                row["sector_etf"] = etf
                row["vs_sector_pct"] = round(move["change_pct"] - daily[etf]["change_pct"], 2)
        earnings = _earnings_near(symbol, day) if symbol not in FUNDS else None
        if earnings:
            row["earnings"] = earnings
        if news.get(symbol):
            row["headlines"] = news[symbol]
        try:
            walls = open_interest_walls(session, day, symbol, move["close"] if move else None)
        except Exception:
            log.warning("Open-interest walls failed for %s", symbol, exc_info=True)
            walls = None
        if walls:
            row["options_open_interest"] = walls
        if levels.get(symbol):
            row["your_saved_levels_now"] = levels[symbol]
        if alerts.get(symbol):
            row["your_alerts_fired"] = alerts[symbol]
        if row:
            out[symbol] = row
    return out


def _earnings_near(symbol: str, day: date) -> dict | None:
    try:
        from app.engine import symbol_info_tradier

        view = symbol_info_tradier.symbol_events.events(symbol, day)["earnings"]
    except Exception:
        return None
    near = {}
    upcoming = view.get("next")
    if upcoming and (date.fromisoformat(upcoming["date"]) - day).days <= EARNINGS_WINDOW:
        near["next"] = {**upcoming, "days_after": (date.fromisoformat(upcoming["date"]) - day).days}
    past = next((row for row in view.get("reports") or [] if (day - date.fromisoformat(row["date"])).days <= EARNINGS_WINDOW), None)
    if past:
        near["last"] = {**past, "days_before": (day - date.fromisoformat(past["date"])).days}
    return near or None


def _headlines(day: date, symbols: list[str], gaps: list[str]) -> dict[str, list[str]]:
    if not symbols:
        return {}
    from app.engine.news import fetch_news

    start = datetime.combine(day, time(4, 0), ET)
    try:
        articles = fetch_news(symbols=symbols, start=start, end=start + timedelta(hours=16), limit=50)
    except Exception as exc:
        gaps.append(f"Headlines unavailable ({type(exc).__name__})")
        return {}
    out: dict[str, list[str]] = defaultdict(list)
    for article in sorted(articles, key=lambda item: item.get("created_at") or ""):
        stamp = str(article.get("created_at") or "")
        try:
            at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(ET).strftime("%H:%M")
        except ValueError:
            at = "?"
        for symbol in article.get("symbols") or []:
            if symbol in symbols and len(out[symbol]) < HEADLINES:
                out[symbol].append(f"{at} {article.get('headline')}")
    return dict(out)
