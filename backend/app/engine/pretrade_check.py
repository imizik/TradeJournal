"""Deterministic pre-trade check: rules verdict + own similar-trades card.

Pure functions over a scalp analysis (``scalper.build_scalp_analysis``) and
per-trade feature rows. No network, no database writes, no model call, never
places or sizes orders. See docs/agent/advisor-pretrade-check-contract.md.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from statistics import median
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models import Account, Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

RULES_VERSION = "pretrade-rules-v1"
SWING_RULES_VERSION = "pretrade-swing-v1"
# Textbook swing defaults fixed before any test on Isaac's trades (docs/swing-strategy-roadmap.md section 5).
SWING_EXTENDED_ATR = 1.5
SWING_RSI_HOT = 70
SWING_TIGHT_STOP_ATR = 0.5
NY = ZoneInfo("America/New_York")
# Display policy, not proof: below these the card says "not enough history".
MIN_TRADES = 8
MIN_DAYS = 3
# History downgrade (v1): a sufficient matching cohort that mostly loses.
WEAK_WIN_RATE = 0.40
WAIT_EXPIRY_MINUTES = 30
SESSION_CLOSE = (16, 0)
EXCLUDED_BROKERS = {"webull"}  # Dormant by owner choice; never in the card.
SIDES = {"call": "long", "put": "short"}


def _ny_wall(moment_utc: datetime) -> datetime:
    """UTC receipt time -> naive New York wall time, the journal's convention."""
    if moment_utc.tzinfo is None:
        raise ValueError("Check receipt time must be timezone-aware UTC")
    return moment_utc.astimezone(NY).replace(tzinfo=None)


def _vwap_bucket(pct: Optional[float]) -> Optional[str]:
    if pct is None:
        return None
    if pct < -0.5:
        return "below"
    if pct > 0.5:
        return "above"
    return "at"


def _rvol_bucket(rvol: Optional[float]) -> Optional[str]:
    if rvol is None:
        return None
    return "low" if rvol < 1.0 else "normal" if rvol < 2.0 else "high"


def _flag(value) -> Optional[bool]:
    return None if value is None else bool(value)


def _side(instrument: str, option_type: Optional[str]) -> Optional[str]:
    if instrument == "option":
        return option_type if option_type in SIDES else None
    return "stock" if instrument == "stock" else None


def feature_row(trade: Trade, entry_fill: Fill, context: Optional[FillMarketContext],
                path: Optional[TradePathMetrics]) -> dict:
    """One closed trade's cohort dimensions and outcome measures.

    Stores source fill keys, never bare trade IDs: FIFO rebuilds recreate trades.
    """
    return {
        "closed_at": trade.closed_at.isoformat(),  # naive New York wall time
        "opened_at": trade.opened_at.isoformat(),
        "underlying": trade.ticker.upper(),
        "side": _side(trade.instrument_type, trade.option_type),
        "time_bucket": (context.entry_time_bucket if context else None) or trade.entry_time_bucket,
        "vwap_bucket": _vwap_bucket(context.entry_vs_vwap_pct) if context else None,
        "trend_aligned": _flag(context.is_trend_aligned) if context else None,
        "chase": _flag(context.is_chase_entry) if context else None,
        "late_move": _flag(context.is_late_move) if context else None,
        "rvol_bucket": _rvol_bucket(context.rvol_time_adjusted) if context else None,
        "dte_bucket": context.dte_bucket if context else None,
        "realized_pnl": float(trade.realized_pnl) if trade.realized_pnl is not None else None,
        "pnl_pct": float(trade.pnl_pct) if trade.pnl_pct is not None else None,
        "mfe_pct": path.underlying_mfe_pct if path else None,
        "mae_pct": path.underlying_mae_pct if path else None,
        "giveback_pct": path.underlying_giveback_pct if path else None,
        "source_fill_key": entry_fill.raw_email_id,
    }


def build_feature_rows(session: Session) -> list[dict]:
    """Read-only: one row per closed/expired trade outside excluded brokers."""
    trades = session.exec(
        select(Trade, Account).join(Account, Trade.account_id == Account.id)
        .where(Trade.status.in_(("closed", "expired")), Trade.closed_at.is_not(None))
    ).all()
    rows = []
    for trade, account in trades:
        if (account.broker or "").lower() in EXCLUDED_BROKERS:
            continue
        entries = session.exec(
            select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
            .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")
            .order_by(Fill.executed_at, Fill.raw_email_id)
        ).all()
        if not entries:
            continue
        first = entries[0]
        rows.append(feature_row(trade, first, session.get(FillMarketContext, first.id),
            session.get(TradePathMetrics, trade.id)))
    return rows


def idea_features(idea: dict, analysis: dict) -> dict:
    """The same cohort dimensions for the idea being checked, from live data."""
    request = analysis.get("request") or {}
    intraday = (analysis.get("data") or {}).get("intraday") or {}
    minutes = intraday.get("minutes_since_open")
    bucket = None
    if minutes is not None and 0 <= minutes < 390:
        # Same boundaries as fill contexts: open 9:30-10:00, mid to 15:00, close to 16:00.
        bucket = "open" if minutes < 30 else "mid" if minutes < 330 else "close"
    return {
        "underlying": idea["ticker"].upper(),
        "side": _side(request.get("instrument") or idea["instrument"], request.get("option_type") or idea.get("option_type")),
        "time_bucket": bucket,
        "vwap_bucket": _vwap_bucket(intraday.get("price_vs_vwap_pct")),
        "rvol_bucket": _rvol_bucket(intraday.get("rvol")),
    }


def _summary(rows: list[dict]) -> dict:
    days = {row["closed_at"][:10] for row in rows}
    weeks = {datetime.fromisoformat(row["closed_at"]).isocalendar()[:2] for row in rows}
    pnl = [row["realized_pnl"] for row in rows if row["realized_pnl"] is not None]
    returns = [row["pnl_pct"] for row in rows if row["pnl_pct"] is not None]
    mfe = [row["mfe_pct"] for row in rows if row["mfe_pct"] is not None]
    mae = [row["mae_pct"] for row in rows if row["mae_pct"] is not None]
    enough = len(rows) >= MIN_TRADES and len(days) >= MIN_DAYS
    result = {"trades": len(rows), "distinct_days": len(days), "distinct_weeks": len(weeks), "enough": enough}
    if not enough:
        result["note"] = "not enough history"
        return result
    wins = sum(1 for value in pnl if value > 0)
    result.update({
        "win_rate": round(wins / len(pnl), 3) if pnl else None,
        "total_pnl": round(sum(pnl), 2) if pnl else None,
        "avg_pnl": round(sum(pnl) / len(pnl), 2) if pnl else None,
        "median_return_pct": round(median(returns), 2) if returns else None,
        "median_mfe_pct": round(median(mfe), 3) if mfe else None,
        "median_mae_pct": round(median(mae), 3) if mae else None,
        "coverage": {"pnl": len(pnl), "path": len(mfe)},
    })
    losers = [row for row in rows if (row["realized_pnl"] or 0) < 0]
    if len(losers) >= 3:
        bucket, count = Counter(row["time_bucket"] for row in losers).most_common(1)[0]
        if bucket and count / len(losers) >= 0.6:
            result["loser_pattern"] = f"{count} of {len(losers)} losers entered in the {bucket} bucket"
    return result


def history_card(rows: Iterable[dict], features: dict, receipt_utc: datetime) -> dict:
    """Similar closed trades before the check's receipt, by two cohorts."""
    cutoff = _ny_wall(receipt_utc)
    prior = [row for row in rows if datetime.fromisoformat(row["closed_at"]) < cutoff]
    same_side = [row for row in prior if row["underlying"] == features["underlying"] and row["side"] == features["side"]]
    setup_keys = ("time_bucket", "vwap_bucket")
    setup = [row for row in same_side
             if all(features[key] is not None and row[key] == features[key] for key in setup_keys)]
    return {
        "as_of_ny": cutoff.isoformat(timespec="seconds"),
        "cohorts": [
            {"name": "same_setup", "definition": {key: features[key] for key in ("underlying", "side", *setup_keys)},
             **_summary(setup)},
            {"name": "same_ticker_side", "definition": {key: features[key] for key in ("underlying", "side")},
             **_summary(same_side)},
        ],
        "source_fill_keys": sorted(row["source_fill_key"] for row in setup),
    }


def swing_history_card(rows: Iterable[dict], features: dict, receipt_utc: datetime) -> dict:
    """Closed trades before the check on this ticker and side: those held overnight first, then all."""
    cutoff = _ny_wall(receipt_utc)
    prior = [row for row in rows if datetime.fromisoformat(row["closed_at"]) < cutoff]
    same_side = [row for row in prior if row["underlying"] == features["underlying"] and row["side"] == features["side"]]
    overnight = [row for row in same_side if row["closed_at"][:10] > row["opened_at"][:10]]
    definition = {key: features[key] for key in ("underlying", "side")}
    return {
        "as_of_ny": cutoff.isoformat(timespec="seconds"),
        "cohorts": [
            {"name": "same_ticker_side_overnight", "definition": {**definition, "held": "overnight"}, **_summary(overnight)},
            {"name": "same_ticker_side", "definition": definition, **_summary(same_side)},
        ],
        "source_fill_keys": sorted(row["source_fill_key"] for row in overnight),
    }


def _next_session_close(receipt_utc: datetime) -> str:
    """Swing waits last until the next weekday's close (holidays are not modelled)."""
    day = receipt_utc.astimezone(NY).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, *SESSION_CLOSE, tzinfo=NY).isoformat(timespec="minutes")


def swing_verdict(analysis: dict, history: dict, idea: dict, receipt_utc: datetime) -> dict:
    """Multi-day ideas from completed daily bars: trend, extension and pullback, stop in daily ATRs.

    Long: trend is price above the 50-day average; the 9-day EMA above the 20-day is aligned. Extended (more than
    1.5 ATR past the 20-day EMA, or RSI over 70) waits for a pullback; a pullback in progress waits for the 9-day EMA
    to cross back. Against the trend passes. Short mirrors it. Textbook defaults, not fitted to Isaac's trades.
    """
    data = analysis.get("data") or {}
    daily = data.get("daily") or {}
    price = ((data.get("snapshot") or {}).get("price") or (data.get("intraday") or {}).get("price")
             or daily.get("last_close"))
    sma50, ema9, ema20, atr, rsi = (daily.get(key) for key in ("sma_50", "ema_9", "ema_20", "atr_14", "rsi_14"))
    up = idea.get("side") != "short"
    sign = 1 if up else -1
    word = "above" if up else "below"
    reasons, wait_for = [], None
    risk = {"stop": idea.get("stop"), "note": "no stop given; none invented"}
    if None in (price, sma50, ema9, ema20, atr, rsi) or not atr:
        return {"verdict": "insufficient_data", "wait_for": None, "risk_check": risk,
                "reasons": [{"source": "daily", "text": "not enough daily history to score a swing (needs 50 sessions)"}]}
    stretch = sign * (price - ema20) / atr
    hot = rsi > SWING_RSI_HOT if up else rsi < 100 - SWING_RSI_HOT
    if sign * (price - sma50) <= 0:
        verdict = "pass"
        reasons.append({"source": "daily", "text": f"price {price} is not {word} the 50-day average {sma50}: against the trend"})
    elif stretch > SWING_EXTENDED_ATR or hot:
        verdict = "wait"
        wait_for = {"condition": f"a pullback toward the 20-day EMA {ema20}", "expires_at": _next_session_close(receipt_utc)}
        reasons.append({"source": "daily", "text": f"extended: {stretch:.1f} ATR from the 20-day EMA, RSI {rsi:.0f}"})
    elif sign * (ema9 - ema20) <= 0:
        verdict = "wait"
        wait_for = {"condition": f"the 9-day EMA back {word} the 20-day EMA {ema20}", "expires_at": _next_session_close(receipt_utc)}
        reasons.append({"source": "daily", "text": f"pullback in progress inside the trend: 9-day EMA {ema9} vs 20-day {ema20}"})
    else:
        verdict = "go"
        reasons.append({"source": "daily", "text": f"trend intact: {word} the 50-day average {sma50}, 9-day EMA {word} "
                        f"the 20-day, {stretch:.1f} ATR from it, RSI {rsi:.0f}"})
    same = history["cohorts"][0]
    if verdict == "go" and same.get("enough") and (same.get("win_rate") or 0) < WEAK_WIN_RATE and (same.get("avg_pnl") or 0) < 0:
        verdict = "wait"
        wait_for = {"condition": f"a pullback toward the 20-day EMA {ema20}", "expires_at": _next_session_close(receipt_utc)}
        reasons.append({"source": "history", "text": f"your {same['trades']} similar overnight trades won "
                        f"{same['win_rate']:.0%} with average P&L {same['avg_pnl']}"})
    stop = idea.get("stop")
    if stop is not None:
        distance = sign * (price - stop)
        risk = {"stop": stop, "reference_price": price, "distance_pct": round(distance / price * 100, 3),
                "distance_atr": round(distance / atr, 2), "daily_atr": atr}
        if distance <= 0 and verdict in ("go", "wait"):
            verdict, wait_for = "pass", None
            reasons.append({"source": "risk", "text": "stop is on the wrong side of the price for this direction"})
    return {"verdict": verdict, "wait_for": wait_for, "reasons": reasons[:3], "risk_check": risk}


def _wait_expiry(receipt_utc: datetime) -> str:
    ny = receipt_utc.astimezone(NY)
    close = ny.replace(hour=SESSION_CLOSE[0], minute=SESSION_CLOSE[1], second=0, microsecond=0)
    return min(ny + timedelta(minutes=WAIT_EXPIRY_MINUTES), close).isoformat(timespec="minutes")


def _risk_check(idea: dict, assessment: dict, analysis: dict) -> tuple[dict, Optional[str]]:
    stop, entry = idea.get("stop"), idea.get("entry")
    intraday = (analysis.get("data") or {}).get("intraday") or {}
    price = entry if entry is not None else intraday.get("price")
    if stop is None:
        return {"stop": None, "note": "no stop given; none invented"}, None
    if price is None:
        return {"stop": stop, "note": "no live or entry price to measure the stop against"}, None
    long_side = (assessment.get("direction_evaluated") or "long") == "long"
    distance = (price - stop) if long_side else (stop - price)
    result = {"stop": stop, "reference_price": price,
              "distance_pct": round(distance / price * 100, 3), "scorer_invalidation": assessment.get("invalidation")}
    if distance <= 0:
        return result, "stop is on the wrong side of the price for this direction"
    return result, None


def rules_verdict(analysis: dict, history: dict, idea: dict, receipt_utc: datetime) -> dict:
    """Roadmap mapping (docs/advisor-roadmap.md#rules-verdict-mapping), versioned."""
    assessment = analysis.get("assessment") or {}
    data = analysis.get("data") or {}
    market_state = assessment.get("market_state") or data.get("market_state") or "closed"
    stale = bool((data.get("staleness") or {}).get("is_stale"))
    risk, risk_problem = _risk_check(idea, assessment, analysis)
    reasons, wait_for = [], None
    if idea.get("horizon") != "intraday":
        verdict = "insufficient_data"
        reasons.append({"source": "rules", "text": "only regular-session intraday ideas are scored"})
    elif market_state != "rth":
        verdict = "insufficient_data"
        reasons.append({"source": "live", "text": "outside the regular session — not a judgment on the idea"})
    elif stale or assessment.get("setup_score") is None:
        verdict = "insufficient_data"
        reasons.append({"source": "live", "text": "live data is stale or the setup could not be scored"})
    elif assessment.get("verdict") in ("long_scalp", "short_scalp"):
        verdict = "go"
        reasons.append({"source": "live", "text": f"setup {assessment.get('setup_score')}, "
                        f"liquidity {assessment.get('liquidity_score')}, risk {assessment.get('risk_score')}"})
    elif assessment.get("verdict") == "wait":
        verdict = "wait"
        wait_for = {"condition": assessment.get("trigger"), "expires_at": _wait_expiry(receipt_utc)}
        reasons.extend({"source": "live", "text": text} for text in (assessment.get("reasons_against") or [])[:1])
    else:
        verdict = "pass"
        reasons.extend({"source": "live", "text": text} for text in (assessment.get("reasons_against") or [])[:1])

    same_setup = history["cohorts"][0]
    if verdict == "go" and same_setup.get("enough") and (same_setup.get("win_rate") or 0) < WEAK_WIN_RATE \
            and (same_setup.get("avg_pnl") or 0) < 0:
        verdict = "wait"
        wait_for = {"condition": assessment.get("trigger"), "expires_at": _wait_expiry(receipt_utc)}
        reasons.append({"source": "history", "text": f"your {same_setup['trades']} similar trades won "
                        f"{same_setup['win_rate']:.0%} with average P&L {same_setup['avg_pnl']}"})
    if risk_problem and verdict in ("go", "wait"):
        verdict = "pass"
        wait_for = None
        reasons.append({"source": "risk", "text": risk_problem})
    return {"verdict": verdict, "wait_for": wait_for, "reasons": reasons[:3], "risk_check": risk}


OPTION_FIELDS = ("contract", "option_type", "expiration", "strike", "dte", "moneyness", "moneyness_pct", "bid", "ask",
                 "mid", "spread_pct", "iv", "delta", "gamma", "theta", "last_trade_price", "quote_time", "feed")


def option_summary(option: Optional[dict], stop: Optional[float] = None,
                   underlying_price: Optional[float] = None) -> Optional[dict]:
    """The contract's live quote and greeks, plus per-contract cost, daily decay and a delta-only stop estimate."""
    if not option:
        return None
    result = {key: option.get(key) for key in OPTION_FIELDS}
    mid, delta, theta = option.get("mid"), option.get("delta"), option.get("theta")
    result["cost_per_contract"] = round(mid * 100, 2) if mid else None
    result["theta_per_contract_per_day"] = round(theta * 100, 2) if theta is not None else None
    if stop is not None and underlying_price and mid and delta is not None:
        estimate = max(0.0, mid + (stop - underlying_price) * delta)
        result["at_stop"] = {"estimated_premium": round(estimate, 4),
                             "estimated_loss_per_contract": round((mid - estimate) * 100, 2),
                             "method": "delta only (ignores gamma, theta and IV change); an estimate, not a quote"}
    return result


def _caveats(analysis: dict, history: dict) -> list[str]:
    data = analysis.get("data") or {}
    assessment = analysis.get("assessment") or {}
    caveats = []
    if (data.get("staleness") or {}).get("is_stale"):
        caveats.append("live quotes/bars are stale")
    caveats.extend(f"missing: {item}" for item in (assessment.get("missing") or []))
    caveats.extend(note for note in (assessment.get("data_source_notes") or []) if "iex" in note.lower())
    if not history["cohorts"][0].get("enough"):
        caveats.append("similar-setup history is too thin to show rates")
    return caveats


def macro_context(receipt_utc: datetime) -> dict:
    """Scheduled FOMC, CPI and jobs releases today and next trading day (the Daily Review's official calendar)."""
    from app.ai.review_context import macro_events

    try:
        return macro_events(receipt_utc.astimezone(NY).date())
    except Exception as exc:  # A missing or uncovered calendar is a gap, never an invented "no events".
        return {"events": None, "gap": f"macro calendar unavailable ({type(exc).__name__})"}


def _macro_caveats(macro: dict, receipt_utc: datetime, swing: bool) -> list[str]:
    if macro.get("events") is None:
        return [macro.get("gap") or "macro calendar unavailable"]
    now = receipt_utc.astimezone(NY).strftime("%H:%M")
    notes = []
    for event in macro["events"]:
        if event["when"] == "today" and event["time_et"] >= now:
            notes.append(f"{event['event']} at {event['time_et']} ET today: expect a volatility spike")
        elif event["when"] == "today":
            notes.append(f"{event['event']} came out at {event['time_et']} ET today")
        elif swing:
            notes.append(f"{event['event']} at {event['time_et']} ET {event['when']}: inside a swing hold")
    return notes


def run_check(idea: dict, analysis: dict, rows: Iterable[dict], receipt_utc: datetime) -> dict:
    """The answer contract for one idea. Same inputs, same answer."""
    for key in ("ticker", "side", "instrument", "horizon"):
        if not idea.get(key):
            raise ValueError(f"{key} is required")
    if idea["side"] not in ("long", "short") or idea["instrument"] not in ("stock", "option") \
            or idea["horizon"] not in ("intraday", "swing"):
        raise ValueError("side long|short, instrument stock|option, horizon intraday|swing")
    rows = list(rows)
    swing = idea["horizon"] == "swing"
    history = (swing_history_card if swing else history_card)(rows, idea_features(idea, analysis), receipt_utc)
    rules = (swing_verdict if swing else rules_verdict)(analysis, history, idea, receipt_utc)
    assessment = analysis.get("assessment") or {}
    data = analysis.get("data") or {}
    intraday = data.get("intraday") or {}
    live = {"price": intraday.get("price"), "vwap": intraday.get("vwap"), "rvol": intraday.get("rvol"),
            "market_state": assessment.get("market_state"), "scalp_verdict": assessment.get("verdict"),
            "setup_score": assessment.get("setup_score"), "trigger": assessment.get("trigger"),
            "invalidation": assessment.get("invalidation"), "generated_at": assessment.get("generated_at"),
            "staleness": data.get("staleness")}
    would_change = assessment.get("trigger") if rules["verdict"] in ("wait", "pass") else assessment.get("invalidation")
    caveats = _caveats(analysis, history)
    if swing:
        daily = data.get("daily") or {}
        live["daily"] = {key: daily.get(key) for key in ("as_of_date", "last_close", "ema_9", "ema_20", "sma_50",
                                                         "sma_200", "rsi_14", "atr_14", "pct_vs_sma_50", "pct_vs_sma_200")}
        sma50 = daily.get("sma_50")
        would_change = ((rules["wait_for"] or {}).get("condition") if rules["verdict"] == "wait"
                        else f"a daily close {'below' if idea['side'] != 'short' else 'above'} the 50-day average {sma50}"
                        if rules["verdict"] == "go" and sma50 else
                        f"a daily close back {'above' if idea['side'] != 'short' else 'below'} the 50-day average {sma50}"
                        if sma50 else None)
        caveats = [c for c in caveats if c != "live quotes/bars are stale"]  # Daily bars decide a swing.
        caveats += ["swing rules are textbook defaults, not yet tested on your trades",
                    "earnings date not checked (no calendar source yet)"]
    option = option_summary(data.get("option"), idea.get("stop"), intraday.get("price")) if idea["instrument"] == "option" else None
    macro = macro_context(receipt_utc)
    caveats = _macro_caveats(macro, receipt_utc, swing) + caveats
    answer = {"rules_version": SWING_RULES_VERSION if swing else RULES_VERSION, "receipt_utc": receipt_utc.astimezone(timezone.utc).isoformat(),
              "idea": idea, **rules, "would_change": would_change, "history": history, "live": live, "option": option,
              "macro": macro, "caveats": caveats}
    answer["live_context_sha256"] = hashlib.sha256(
        json.dumps({"request": analysis.get("request"), "data": data}, sort_keys=True, default=str).encode()).hexdigest()
    return answer


LINK_VERSION = "pretrade-link-v1"


def check_window(answer: dict, receipt_utc: datetime) -> tuple[datetime, datetime]:
    """Fixed before the outcome is known: receipt to the wait expiry, else to that session's close (NY wall time)."""
    start = _ny_wall(receipt_utc)
    close = start.replace(hour=SESSION_CLOSE[0], minute=SESSION_CLOSE[1], second=0, microsecond=0)
    end = close
    if answer.get("verdict") == "wait" and answer.get("wait_for"):
        end = min(datetime.fromisoformat(answer["wait_for"]["expires_at"]).astimezone(NY).replace(tzinfo=None), close)
    return start, max(start, end)


def check_outcome(idea: dict, answer: dict, receipt_utc: datetime, rows: Optional[Iterable[dict]],
                  features_generated_at: Optional[datetime], now_utc: datetime) -> dict:
    """What happened after a check, from closed trades only (docs/advisor-roadmap.md#checks-and-captures).

    "traded" means a trade on the same underlying and side opened inside the window; it is not proof the
    check was followed. "no_closed_trade" never claims no position: an open one appears after it closes.
    """
    if idea.get("horizon") != "intraday":
        return {"state": "not_linked", "link_version": LINK_VERSION, "note": "swing checks are not linked yet"}
    start, end = check_window(answer, receipt_utc)
    window = {"from_ny": start.isoformat(timespec="minutes"), "to_ny": end.isoformat(timespec="minutes")}
    base = {"link_version": LINK_VERSION, "window": window}
    if _ny_wall(now_utc) < end:
        return {**base, "state": "pending", "note": "the check's window is still open"}
    if rows is None or features_generated_at is None or _ny_wall(features_generated_at) < end:
        return {**base, "state": "pending", "note": "trade history has not been refreshed since the window closed"}
    side = _side(idea["instrument"], idea.get("option_type"))
    trades = sorted((row for row in rows if row["underlying"] == idea["ticker"].upper() and row["side"] == side
                     and start <= datetime.fromisoformat(row["opened_at"]) <= end), key=lambda row: row["opened_at"])
    if not trades:
        return {**base, "state": "no_closed_trade",
                "note": "no closed trade on this ticker and side opened in the window; an open one would appear after it closes"}
    pnl = [row["realized_pnl"] for row in trades if row["realized_pnl"] is not None]
    # Aggregates only: the approved scope shares own-trade summaries, not individual trades.
    return {**base, "state": "traded", "trade_count": len(trades), "wins": sum(1 for value in pnl if value > 0),
        "total_pnl": round(sum(pnl), 2) if pnl else None, "first_opened_at": trades[0]["opened_at"],
        "note": "a trade on this ticker and side opened in the window; not proof the check was followed"}


POSITION_VERSION = "pretrade-position-v1"


def _hold_summary(rows: list[dict]) -> dict:
    """The cohort summary plus how long those trades were held."""
    result = _summary(rows)
    if result.get("enough"):
        holds = [(datetime.fromisoformat(row["closed_at"]) - datetime.fromisoformat(row["opened_at"])).total_seconds() / 60
                 for row in rows]
        giveback = [row["giveback_pct"] for row in rows if row["giveback_pct"] is not None]
        result["median_hold_minutes"] = round(median(holds)) if holds else None
        result["median_giveback_pct"] = round(median(giveback), 3) if giveback else None
    return result


def position_view(position: dict, rows: Iterable[dict], analysis: dict, receipt_utc: datetime,
                  stop: Optional[float] = None) -> dict:
    """One open position now: live underlying, time held, stop distance, and how similar closed trades went.

    Facts only; no verdict. Unrealized P&L uses the live mid (options) or price (shares) when available.
    """
    now_ny = _ny_wall(receipt_utc)
    opened = datetime.fromisoformat(position["opened_at"])
    side = _side(position["instrument_type"], position.get("option_type"))
    ticker = position["ticker"].upper()
    data = analysis.get("data") or {}
    intraday = data.get("intraday") or {}
    price = intraday.get("price")
    prior = [row for row in rows if datetime.fromisoformat(row["closed_at"]) < now_ny
             and row["underlying"] == ticker and row["side"] == side]
    same_entry = [row for row in prior if position.get("entry_time_bucket") and row["time_bucket"] == position["entry_time_bucket"]]
    stop_check = {"stop": stop, "note": "no stop given; none invented"}
    if stop is not None and price:
        bearish = side == "put"
        distance = (stop - price) if bearish else (price - stop)
        stop_check = {"stop": stop, "underlying_price": price, "distance_pct": round(distance / price * 100, 3),
                      "breached": distance <= 0}
    expiration = position.get("expiration")
    caveats = ["treated as a bought position (calls/puts/shares); a sold option or short would read inverted"]
    option = None
    mark = None
    if position["instrument_type"] == "option":
        option = option_summary(data.get("option"), stop, price)
        mid = (option or {}).get("mid")
        contracts = position.get("contracts")
        if mid and contracts:
            value = round(mid * 100 * contracts, 2)
            paid = position.get("total_premium_paid")
            mark = {"value_now": value, "paid": paid, "unrealized_pnl": round(value - paid, 2) if paid else None,
                    "unrealized_pct": round((value - paid) / paid * 100, 2) if paid else None,
                    "basis": "mid of the live bid/ask x 100 x contracts; a fill could differ by the spread"}
        else:
            caveats.append("no live quote for this contract; P&L is not computed")
    elif price and position.get("contracts") and position.get("total_premium_paid"):
        value = round(price * position["contracts"], 2)
        mark = {"value_now": value, "paid": position["total_premium_paid"],
                "unrealized_pnl": round(value - position["total_premium_paid"], 2),
                "unrealized_pct": round((value - position["total_premium_paid"]) / position["total_premium_paid"] * 100, 2),
                "basis": "live underlying price x shares"}
    if (data.get("staleness") or {}).get("is_stale"):
        caveats.append("live quotes/bars are stale")
    return {
        "position_version": POSITION_VERSION,
        "position": position,
        "held_minutes": max(0, round((now_ny - opened).total_seconds() / 60)),
        "days_to_expiration": (datetime.fromisoformat(expiration).date() - now_ny.date()).days if expiration else None,
        "live": {"price": price, "vwap": intraday.get("vwap"), "price_vs_vwap_pct": intraday.get("price_vs_vwap_pct"),
                 "rvol": intraday.get("rvol"), "market_state": (analysis.get("assessment") or {}).get("market_state")
                 or data.get("market_state"), "staleness": data.get("staleness")},
        "stop_check": stop_check,
        "option": option,
        "mark": mark,
        "history": {"as_of_ny": now_ny.isoformat(timespec="seconds"), "cohorts": [
            {"name": "same_ticker_side", **_hold_summary(prior)},
            {"name": "same_ticker_side_entry_time", "entry_time_bucket": position.get("entry_time_bucket"),
             **_hold_summary(same_entry)}]},
        "caveats": caveats,
    }


PREOPEN_VERSION = "pretrade-preopen-v1"
PREOPEN_RECENT_DAYS = 30
PREOPEN_HEADLINES = 5


def preopen_tickers(positions: Iterable[dict], rows: Iterable[dict], receipt_utc: datetime, limit: int) -> list[str]:
    """Default watchlist: tickers held now, then the most-traded tickers of the last 30 days."""
    cutoff = _ny_wall(receipt_utc) - timedelta(days=PREOPEN_RECENT_DAYS)
    held = [p["ticker"].upper() for p in positions]
    recent = Counter(row["underlying"].upper() for row in rows if datetime.fromisoformat(row["closed_at"]) >= cutoff)
    return list(dict.fromkeys([*held, *(ticker for ticker, _ in recent.most_common())]))[:limit]


def preopen_view(ticker: str, rows: Iterable[dict], analysis: dict, receipt_utc: datetime,
                 positions: Iterable[dict] = ()) -> dict:
    """Before the bell, one ticker: where it trades versus yesterday, its last-24h headlines, and how Isaac has
    traded it.

    Facts only; no verdict. Premarket reads are not session reads, and small cohorts say so.
    """
    now_ny = _ny_wall(receipt_utc)
    ticker = ticker.upper()
    data = analysis.get("data") or {}
    snapshot = data.get("snapshot") or {}
    intraday = data.get("intraday") or {}
    prior = [row for row in rows if datetime.fromisoformat(row["closed_at"]) < now_ny and row["underlying"].upper() == ticker]
    sides = []
    for side in sorted({row["side"] for row in prior}):
        same = [row for row in prior if row["side"] == side]
        by_time = []
        for bucket in sorted({row["time_bucket"] for row in same if row["time_bucket"]}):
            group = [row for row in same if row["time_bucket"] == bucket]
            pnl = [row["realized_pnl"] for row in group if row["realized_pnl"] is not None]
            by_time.append({"time_bucket": bucket, "trades": len(group),
                            "win_rate": round(sum(1 for v in pnl if v > 0) / len(pnl), 3) if len(pnl) >= 3 else None,
                            "total_pnl": round(sum(pnl), 2) if pnl else None})
        sides.append({"side": side, **_hold_summary(same), "by_entry_time": by_time})
    caveats = []
    if (data.get("staleness") or {}).get("is_stale"):
        caveats.append("live quotes/bars are stale")
    caveats.extend(data.get("missing") or [])
    return {
        "preopen_version": PREOPEN_VERSION,
        "ticker": ticker,
        "live": {"price": snapshot.get("price") or intraday.get("price"), "prev_close": snapshot.get("prev_close"),
                 "change_pct": snapshot.get("change_pct"), "gap_pct": snapshot.get("gap_pct"),
                 "premarket_high": intraday.get("premarket_high"), "premarket_low": intraday.get("premarket_low"),
                 "premarket_volume": intraday.get("premarket_volume"),
                 "market_state": (analysis.get("assessment") or {}).get("market_state") or data.get("market_state"),
                 "staleness": data.get("staleness")},
        "news": [{key: article.get(key) for key in ("headline", "source", "created_at", "url")}
                 for article in (data.get("news") or [])[:PREOPEN_HEADLINES]],
        "held_now": [{key: p.get(key) for key in ("instrument_type", "option_type", "strike", "expiration", "contracts",
                      "total_premium_paid", "opened_at")} for p in positions if p["ticker"].upper() == ticker],
        "history": {"as_of_ny": now_ny.isoformat(timespec="seconds"), "trades": len(prior),
                    "last_closed": max((row["closed_at"] for row in prior), default=None), "by_side": sides},
        "caveats": caveats,
    }


MOVE_VERSION = "pretrade-move-v1"


def _bar_time(bar: dict) -> datetime:
    return _ny_wall(datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00")))


def price_after(idea: dict, answer: dict, receipt_utc: datetime, bars: Optional[list[dict]], now_utc: datetime) -> dict:
    """How the underlying moved after a check, inside the check's own fixed window, in the idea's direction.

    Positive means the move went the idea's way. Options are measured on the underlying only; the premium is
    not replayed. "so_far" while the window is open; never extrapolated.
    """
    base = {"move_version": MOVE_VERSION}
    if idea.get("horizon") != "intraday":
        return {**base, "state": "not_measured", "note": "swing checks are not measured yet"}
    start, end = check_window(answer, receipt_utc)
    reference = (answer.get("live") or {}).get("price")
    window = {"from_ny": start.isoformat(timespec="minutes"), "to_ny": end.isoformat(timespec="minutes")}
    if not reference:
        return {**base, "state": "no_reference", "window": window, "note": "the check had no live price to measure from"}
    if start >= end:
        return {**base, "state": "no_window", "window": window, "note": "checked after the close; no session left to measure"}
    if bars is None:
        return {**base, "state": "unavailable", "window": window, "note": "minute bars could not be read"}
    inside = sorted((bar for bar in bars if start <= _bar_time(bar) < end), key=lambda bar: str(bar["t"]))
    if not inside:
        return {**base, "state": "no_bars", "window": window, "note": "no minute bars after the check yet"}
    up = idea.get("side") != "short"
    high, low, last = max(bar["h"] for bar in inside), min(bar["l"] for bar in inside), inside[-1]["c"]

    def pct(price):
        return round((price - reference) / reference * 100 * (1 if up else -1), 3)

    result = {**base, "state": "complete" if _ny_wall(now_utc) >= end else "so_far", "window": window,
              "reference_price": reference, "last_price": last, "last_bar_ny": _bar_time(inside[-1]).isoformat(timespec="minutes"),
              "move_pct": pct(last), "best_pct": pct(high if up else low), "worst_pct": pct(low if up else high),
              "basis": "underlying 1-minute bars; positive = the idea's direction"}
    stop = idea.get("stop")
    if stop:
        hit = next((bar for bar in inside if (bar["l"] <= stop if up else bar["h"] >= stop)), None)
        result["stop_hit_ny"] = _bar_time(hit).isoformat(timespec="minutes") if hit else None
    return result


SETTLE_DELAY_HOURS = 12  # Late fill emails and same-day closes reach the history file well within this.
FINAL_MOVES = ("complete", "no_reference", "no_window", "no_bars")


def result_final(idea: dict, answer: dict, receipt_utc: datetime, result: dict,
                 features_generated_at: Optional[datetime], positions: Optional[Iterable[dict]]) -> bool:
    """Whether a check's result can no longer change, so it may be saved for good.

    Needs a closed-trade link, a finished move, a history file at least 12 hours past the window, and current
    open positions with none on this ticker and side opened inside the window (it would link once it closes).
    """
    if result["outcome"].get("state") not in ("traded", "no_closed_trade") or result["move"].get("state") not in FINAL_MOVES:
        return False
    start, end = check_window(answer, receipt_utc)
    if features_generated_at is None or _ny_wall(features_generated_at) < end + timedelta(hours=SETTLE_DELAY_HOURS):
        return False
    if positions is None:
        return False
    side = _side(idea["instrument"], idea.get("option_type"))
    return not any(p["ticker"].upper() == idea["ticker"].upper()
                   and _side(p["instrument_type"], p.get("option_type")) == side
                   and start <= datetime.fromisoformat(p["opened_at"]) <= end for p in positions)


GRADE_VERSION = "pretrade-grade-v1"
MIN_GRADE_GROUP = 10  # Display policy: below this a group says "not enough evidence".


def _moves(items: list[dict]) -> dict:
    moves = [item["move"]["move_pct"] for item in items if (item.get("move") or {}).get("state") == "complete"]
    result = {"checks": len(items), "measured": len(moves), "enough": len(items) >= MIN_GRADE_GROUP}
    if moves:
        result.update({"median_move_pct": round(median(moves), 3),
                       "went_the_idea_way": sum(1 for value in moves if value > 0)})
    if not result["enough"]:
        result["note"] = "not enough evidence"
    return result


def grade_results(items: Iterable[dict]) -> dict:
    """Saved checks with their final results -> results by verdict, followed versus overrode, rules versus Jo.

    Each item: verdict (rules), model_verdict (or None), outcome (check_outcome) and move (price_after).
    Followed: go and traded, or wait/pass and no trade. Overrode: the other way round. Swing and
    insufficient_data checks are counted but not graded.
    """
    items = [item for item in items if item["outcome"].get("state") in ("traded", "no_closed_trade")]
    by_verdict = {}
    for verdict in ("go", "wait", "pass"):
        group = [item for item in items if item["verdict"] == verdict]
        traded = [item for item in group if item["outcome"]["state"] == "traded"]
        pnl = [item["outcome"]["total_pnl"] for item in traded if item["outcome"].get("total_pnl") is not None]
        by_verdict[verdict] = {**_moves(group), "traded": len(traded), "traded_pnl": round(sum(pnl), 2) if pnl else None}
    graded = [item for item in items if item["verdict"] in ("go", "wait", "pass")]
    followed = [item for item in graded if (item["verdict"] == "go") == (item["outcome"]["state"] == "traded")]
    overrode = [item for item in graded if item not in followed]
    took_against = [item for item in overrode if item["verdict"] != "go"]
    skipped_go = [item for item in overrode if item["verdict"] == "go"]
    against_pnl = [item["outcome"]["total_pnl"] for item in took_against if item["outcome"].get("total_pnl") is not None]
    with_model = [item for item in graded if item.get("model_verdict")]
    by_model = {}
    for verdict in ("go", "wait", "pass"):
        by_model[verdict] = _moves([item for item in with_model if item["model_verdict"] == verdict])
    return {
        "grade_version": GRADE_VERSION,
        "final_checks": len(items),
        "by_rules_verdict": by_verdict,
        "followed": len(followed),
        "overrode": {"total": len(overrode),
                     "traded_against_wait_or_pass": {**_moves(took_against),
                                                     "pnl": round(sum(against_pnl), 2) if against_pnl else None},
                     "skipped_a_go": _moves(skipped_go)},
        "jo": {"with_verdict": len(with_model),
               "agrees_with_rules": sum(1 for item in with_model if item["model_verdict"] == item["verdict"]),
               "by_jo_verdict": by_model},
        "note": "Closed trades and underlying moves only; small groups are not evidence of an edge.",
    }
